"""The two fixed Ora review graphs. No configurable workflow lives here."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generic, Sequence, TypeVar

from .errors import CallFailure, MalformedResponse, OraReviewError
from .models import (
    CallAdapter,
    ReviewHistory,
    RunResult,
    StageMaterial,
    UserMaterial,
)
from .packet import PacketBuilder, extract_answer, parse_verdict
from .record import RunRecord


@dataclass(frozen=True)
class RunRequest:
    material: UserMaterial
    existing_answer: str | None = None
    consensus: bool = False
    breadth: str = "analytical"
    run_root: Path | None = None
    initial_notices: tuple[str, ...] = ()


@dataclass(frozen=True)
class CycleResult:
    history: ReviewHistory
    technical_incomplete: bool


T = TypeVar("T")


@dataclass(frozen=True)
class _ParsedCall(Generic[T]):
    response: str
    value: T


class _StageIncomplete(OraReviewError):
    pass


class ReviewRunner:
    """Run Gear 3 or Gear 4 with injected fresh-call adapters."""

    GEAR3_INSTRUCTIONS = (
        "universal.md",
        "initial-answer.md",
        "reviewer.md",
        "reviser.md",
        "output-answer.md",
        "output-review.md",
        "output-revision.md",
    )
    GEAR4_INSTRUCTIONS = (
        "universal.md",
        "reviewer.md",
        "reviser.md",
        "depth.md",
        "breadth-analytical.md",
        "breadth-committed.md",
        "review-depth.md",
        "review-breadth.md",
        "revise-depth.md",
        "revise-breadth.md",
        "consolidator.md",
        "review-consolidated.md",
        "revise-consolidated.md",
        "initial-answer.md",
        "output-answer.md",
        "output-review.md",
        "output-revision.md",
    )

    def __init__(
        self,
        native: CallAdapter,
        peer: CallAdapter | None = None,
        *,
        packet_builder: PacketBuilder | None = None,
    ) -> None:
        self.native = native
        self.native_engine = native.engine
        self.native_model_selector = getattr(native, "model", None)
        self.peer = peer
        self.packet_builder = packet_builder or PacketBuilder()
        self._peer_active = peer is not None
        self._notices: list[str] = []
        self._transport_incomplete = False
        self.latest_user_deliverable_answer: str | None = None
        self.run_path: str | None = None

    def run_gear3(self, request: RunRequest) -> RunResult:
        self._reset_route(request.initial_notices)
        self._validate_material(request.material)
        self.latest_user_deliverable_answer = request.existing_answer
        ending = "consensus" if request.consensus else "one-pass"
        snapshot = self.packet_builder.snapshot_instructions(self.GEAR3_INSTRUCTIONS)
        record = RunRecord.create(
            tool="ora-gear-3",
            ending=ending,
            route="external" if self._peer_active else "internal",
            native_engine=self.native_engine,
            native_model_selector=self.native_model_selector,
            material=request.material,
            instruction_snapshot=snapshot,
            run_root=request.run_root,
        )
        self.run_path = str(record.path)

        cycle = self._gear3_graph(request, record)
        history = cycle.history
        record.finish(history.status or "NOT PASSED", self._notices)
        return RunResult(
            answer=history.current_answer,
            status=history.status or "NOT PASSED",
            run_path=str(record.path),
            notices=tuple(self._notices),
            technical_incomplete=(
                cycle.technical_incomplete or self._transport_incomplete
            ),
        )

    def run_gear4(self, request: RunRequest) -> RunResult:
        self._reset_route(request.initial_notices)
        self._validate_material(request.material)
        self.latest_user_deliverable_answer = None
        if request.existing_answer is not None:
            raise OraReviewError(
                "Ora Gear 4 always generates two blind lanes; it does not accept an existing answer."
            )
        if request.breadth not in {"analytical", "committed"}:
            raise OraReviewError("Breadth must be `analytical` or `committed`.")
        if request.breadth == "committed" and (
            request.material.commitment is None
            or not request.material.commitment.strip()
        ):
            raise OraReviewError(
                "Committed Breadth requires a separate non-empty commitment in the user's words."
            )

        ending = "consensus" if request.consensus else "one-pass"
        snapshot = self.packet_builder.snapshot_instructions(self.GEAR4_INSTRUCTIONS)
        record = RunRecord.create(
            tool="ora-gear-4",
            ending=ending,
            route="external" if self._peer_active else "internal",
            native_engine=self.native_engine,
            native_model_selector=self.native_model_selector,
            material=request.material,
            instruction_snapshot=snapshot,
            run_root=request.run_root,
            breadth=request.breadth,
        )
        self.run_path = str(record.path)

        depth: str | None = None
        breadth: str | None = None
        draft_failures: list[str] = []
        try:
            depth = self._answer_call(
                material=request.material,
                role_files=("depth.md",),
                stage_material=(),
                prefer_peer=False,
                role="gear-4-depth-draft",
                record=record,
                record_title="Depth draft",
                user_deliverable=False,
            ).value
            record.append_artifact("Complete original blind Depth answer", depth)
        except _StageIncomplete as failure:
            draft_failures.append(f"Depth: {failure}")

        breadth_role = (
            "breadth-committed.md"
            if request.breadth == "committed"
            else "breadth-analytical.md"
        )
        try:
            breadth = self._answer_call(
                material=request.material,
                role_files=(breadth_role,),
                stage_material=(),
                prefer_peer=True,
                role="gear-4-breadth-draft",
                record=record,
                record_title="Breadth draft",
                user_deliverable=False,
            ).value
            record.append_artifact("Complete original blind Breadth answer", breadth)
        except _StageIncomplete as failure:
            draft_failures.append(f"Breadth: {failure}")

        if depth is None or breadth is None:
            return self._gear3_fallback(request, record, draft_failures)

        depth_cycle = self._review_cycle(
            material=request.material,
            current_answer=depth,
            consensus=request.consensus,
            reviewer_role_files=("reviewer.md", "review-depth.md"),
            reviser_role_files=("reviser.md", "revise-depth.md"),
            reviewer_prefers_peer=True,
            reviser_prefers_peer=False,
            role_prefix="gear-4-depth",
            record=record,
            one_pass_revised_status="NOT RE-REVIEWED",
            user_deliverable=False,
        )
        record.append(
            "Depth lane result",
            f"Status: **{depth_cycle.history.status or 'NOT PASSED'}**",
        )

        breadth_cycle = self._review_cycle(
            material=request.material,
            current_answer=breadth,
            consensus=request.consensus,
            reviewer_role_files=("reviewer.md", "review-breadth.md"),
            reviser_role_files=("reviser.md", "revise-breadth.md"),
            reviewer_prefers_peer=False,
            reviser_prefers_peer=True,
            role_prefix="gear-4-breadth",
            record=record,
            one_pass_revised_status="NOT RE-REVIEWED",
            user_deliverable=False,
        )
        record.append(
            "Breadth lane result",
            f"Status: **{breadth_cycle.history.status or 'NOT PASSED'}**",
        )

        lane_material = [
            *self._history_material("DEPTH", depth_cycle.history),
            *self._history_material("BREADTH", breadth_cycle.history),
        ]
        try:
            consolidated = self._answer_call(
                material=request.material,
                role_files=("consolidator.md",),
                stage_material=lane_material,
                prefer_peer=False,
                role="gear-4-consolidation",
                record=record,
                record_title="Consolidation",
                user_deliverable=True,
            ).value
        except _StageIncomplete as failure:
            return self._gear3_fallback(request, record, [f"Consolidation: {failure}"])

        record.append_artifact("Complete original consolidated answer", consolidated)
        final_cycle = self._review_cycle(
            material=request.material,
            current_answer=consolidated,
            consensus=request.consensus,
            reviewer_role_files=("reviewer.md", "review-consolidated.md"),
            reviser_role_files=("reviser.md", "revise-consolidated.md"),
            reviewer_prefers_peer=True,
            reviser_prefers_peer=False,
            role_prefix="gear-4-consolidated-answer",
            record=record,
            one_pass_revised_status="ONE PASS COMPLETE — REVISED, NOT RE-REVIEWED",
            extra_stage_material=lane_material,
            user_deliverable=True,
        )

        history = final_cycle.history
        technical_incomplete = (
            depth_cycle.technical_incomplete
            or breadth_cycle.technical_incomplete
            or final_cycle.technical_incomplete
            or self._transport_incomplete
        )
        record.finish(history.status or "NOT PASSED", self._notices)
        return RunResult(
            answer=history.current_answer,
            status=history.status or "NOT PASSED",
            run_path=str(record.path),
            notices=tuple(self._notices),
            technical_incomplete=technical_incomplete,
        )

    def _gear3_graph(self, request: RunRequest, record: RunRecord) -> CycleResult:
        if request.existing_answer is None:
            try:
                current = self._answer_call(
                    material=request.material,
                    role_files=("initial-answer.md",),
                    stage_material=(),
                    prefer_peer=False,
                    role="gear-3-initial-answer",
                    record=record,
                    record_title="Initial answer call",
                    user_deliverable=True,
                ).value
            except _StageIncomplete as failure:
                notice = str(failure)
                self._notices.append(notice)
                record.append("Terminal technical failure", notice)
                record.finish("TECHNICAL FAILURE — NO COMPLETE ANSWER", self._notices)
                raise CallFailure(
                    notice,
                    "Run Ora Gear 3 again after the native harness is ready. "
                    f"The incomplete run record is `{record.path}`.",
                ) from failure
            record.append_artifact("Complete initial answer", current)
        else:
            current = request.existing_answer
            record.append_artifact("Caller-supplied complete current answer", current)

        return self._review_cycle(
            material=request.material,
            current_answer=current,
            consensus=request.consensus,
            reviewer_role_files=("reviewer.md",),
            reviser_role_files=("reviser.md",),
            reviewer_prefers_peer=True,
            reviser_prefers_peer=False,
            role_prefix="gear-3",
            record=record,
            one_pass_revised_status="ONE PASS COMPLETE — REVISED, NOT RE-REVIEWED",
            user_deliverable=True,
        )

    def _gear3_fallback(
        self,
        request: RunRequest,
        record: RunRecord,
        failures: Sequence[str],
    ) -> RunResult:
        marker = "GEAR 4 UNAVAILABLE — GEAR 3 FALLBACK"
        details = "; ".join(failures) if failures else "Gear 4 input was unavailable."
        notice = f"{marker}. {details}"
        self._notices.append(notice)
        record.append("Gear 4 fallback", notice)
        self._transport_incomplete = False
        fallback_request = RunRequest(
            material=request.material,
            consensus=request.consensus,
            run_root=request.run_root,
        )
        cycle = self._gear3_graph(fallback_request, record)
        history = cycle.history
        record.finish(history.status or "NOT PASSED", self._notices)
        return RunResult(
            answer=history.current_answer,
            status=history.status or "NOT PASSED",
            run_path=str(record.path),
            notices=tuple(self._notices),
            technical_incomplete=(
                cycle.technical_incomplete or self._transport_incomplete
            ),
        )

    @staticmethod
    def _history_material(prefix: str, history: ReviewHistory) -> list[StageMaterial]:
        material = [
            StageMaterial(f"{prefix} ORIGINAL BLIND ANSWER", history.original_answer),
            StageMaterial(f"{prefix} COMPLETE CURRENT ANSWER", history.current_answer),
        ]
        for index, review in enumerate(history.reviews, start=1):
            material.append(StageMaterial(f"{prefix} COMPLETE REVIEW {index}", review))
            if index <= len(history.revisions):
                material.append(
                    StageMaterial(
                        f"{prefix} COMPLETE REVISER RESPONSE {index}",
                        history.revisions[index - 1],
                    )
                )
        material.append(
            StageMaterial(f"{prefix} LANE QUALITY STATUS", history.status or "NOT PASSED")
        )
        for index, notice in enumerate(history.notices, start=1):
            material.append(
                StageMaterial(f"{prefix} LANE EXECUTION NOTICE {index}", notice)
            )
        return material

    def _review_cycle(
        self,
        *,
        material: UserMaterial,
        current_answer: str,
        consensus: bool,
        reviewer_role_files: Sequence[str],
        reviser_role_files: Sequence[str],
        reviewer_prefers_peer: bool,
        reviser_prefers_peer: bool,
        role_prefix: str,
        record: RunRecord,
        one_pass_revised_status: str,
        user_deliverable: bool,
        extra_stage_material: Sequence[StageMaterial] = (),
    ) -> CycleResult:
        history = ReviewHistory(
            original_answer=current_answer,
            current_answer=current_answer,
        )
        review_limit = 3 if consensus else 1

        for review_number in range(1, review_limit + 1):
            stage = [
                *extra_stage_material,
                StageMaterial("COMPLETE CURRENT ANSWER", history.current_answer),
            ]
            for index, review in enumerate(history.reviews, start=1):
                stage.append(StageMaterial(f"PRIOR COMPLETE REVIEW {index}", review))
                if index <= len(history.revisions):
                    stage.append(
                        StageMaterial(
                            f"PRIOR COMPLETE REVISER RESPONSE {index}",
                            history.revisions[index - 1],
                        )
                    )
            try:
                reviewed = self._review_call(
                    material=material,
                    role_files=reviewer_role_files,
                    stage_material=stage,
                    prefer_peer=reviewer_prefers_peer,
                    role=f"{role_prefix}-review-{review_number}",
                    record=record,
                    record_title=f"{role_prefix} review {review_number}",
                )
            except _StageIncomplete as failure:
                notice = str(failure)
                history.notices.append(notice)
                self._notices.append(notice)
                history.status = "NOT PASSED — REVIEW INCOMPLETE"
                return CycleResult(history, True)

            history.reviews.append(reviewed.response)
            history.verdicts.append(reviewed.value)
            record.append_artifact(
                f"{role_prefix} complete review {review_number}", reviewed.response
            )
            if reviewed.value == "PASS":
                history.status = "PASSED"
                return CycleResult(history, False)

            if consensus and review_number == review_limit:
                history.status = "NOT PASSED"
                return CycleResult(history, False)

            revision_number = len(history.revisions) + 1
            revision_stage = [
                *extra_stage_material,
                StageMaterial("COMPLETE CURRENT ANSWER", history.current_answer),
                StageMaterial("COMPLETE CURRENT REVIEW", reviewed.response),
            ]
            for index, review in enumerate(history.reviews[:-1], start=1):
                revision_stage.append(
                    StageMaterial(f"PRIOR COMPLETE REVIEW {index}", review)
                )
                if index <= len(history.revisions):
                    revision_stage.append(
                        StageMaterial(
                            f"PRIOR COMPLETE REVISER RESPONSE {index}",
                            history.revisions[index - 1],
                        )
                    )
            try:
                revised = self._answer_call(
                    material=material,
                    role_files=reviser_role_files,
                    output_file="output-revision.md",
                    stage_material=revision_stage,
                    prefer_peer=reviser_prefers_peer,
                    role=f"{role_prefix}-revision-{revision_number}",
                    record=record,
                    record_title=f"{role_prefix} revision {revision_number}",
                    user_deliverable=user_deliverable,
                )
            except _StageIncomplete as failure:
                notice = str(failure)
                history.notices.append(notice)
                self._notices.append(notice)
                history.status = "NOT PASSED — REVISION INCOMPLETE"
                return CycleResult(history, True)

            history.revisions.append(revised.response)
            history.current_answer = revised.value
            record.append_artifact(
                f"{role_prefix} complete reviser response {revision_number}",
                revised.response,
            )
            record.append_artifact(
                f"{role_prefix} complete current answer after revision {revision_number}",
                revised.value,
            )
            if not consensus:
                history.status = one_pass_revised_status
                return CycleResult(history, False)

        raise AssertionError("The fixed review loop exceeded its declared ceiling.")

    def _answer_call(
        self,
        *,
        material: UserMaterial,
        role_files: Sequence[str],
        stage_material: Sequence[StageMaterial],
        prefer_peer: bool,
        role: str,
        record: RunRecord,
        record_title: str,
        user_deliverable: bool,
        output_file: str = "output-answer.md",
    ) -> _ParsedCall[str]:
        collision_bodies = [
            material.original,
            *material.later_user_messages,
            *material.prior_assistant_turns,
            *material.governing_context,
            *(item.body for item in stage_material),
        ]
        if material.commitment is not None:
            collision_bodies.append(material.commitment)
        boundary = self.packet_builder.answer_boundary(collision_bodies)
        packet = self.packet_builder.build(
            material=material,
            role_files=role_files,
            output_file=output_file,
            stage_material=stage_material,
            answer_boundary=boundary,
        )
        result = self._execute_with_recovery(
            packet=packet,
            prefer_peer=prefer_peer,
            role=role,
            record=record,
            record_title=record_title,
            parser=lambda response: extract_answer(response, boundary),
        )
        if user_deliverable:
            self.latest_user_deliverable_answer = result.value
        return result

    def _review_call(
        self,
        *,
        material: UserMaterial,
        role_files: Sequence[str],
        stage_material: Sequence[StageMaterial],
        prefer_peer: bool,
        role: str,
        record: RunRecord,
        record_title: str,
    ) -> _ParsedCall[str]:
        packet = self.packet_builder.build(
            material=material,
            role_files=role_files,
            output_file="output-review.md",
            stage_material=stage_material,
        )
        return self._execute_with_recovery(
            packet=packet,
            prefer_peer=prefer_peer,
            role=role,
            record=record,
            record_title=record_title,
            parser=parse_verdict,
        )

    def _execute_with_recovery(
        self,
        *,
        packet: str,
        prefer_peer: bool,
        role: str,
        record: RunRecord,
        record_title: str,
        parser: Callable[[str], T],
    ) -> _ParsedCall[T]:
        use_peer = prefer_peer and self._peer_active and self.peer is not None
        adapter = self.peer if use_peer else self.native
        attempts = 1 if use_peer else 2

        for attempt in range(1, attempts + 1):
            try:
                try:
                    response = adapter.call(packet, role=role)
                    if not use_peer:
                        self._record_native_model_attribution(
                            record, record_title, role
                        )
                finally:
                    disclosure = getattr(adapter, "last_call_notice", "")
                    if disclosure:
                        notice = f"Role `{role}`: {disclosure}"
                        self._notices.append(notice)
                        record.append(f"{record_title} transport notice", notice)
                value = parser(response)
                return _ParsedCall(response, value)
            except (CallFailure, MalformedResponse) as failure:
                if isinstance(failure, CallFailure) and failure.usable_response is not None:
                    try:
                        value = parser(failure.usable_response)
                    except MalformedResponse:
                        pass
                    else:
                        detail = failure.display()
                        transport = (
                            "an Agent Bridge"
                            if use_peer
                            else f"the native `{self.native_engine}` engine"
                        )
                        notice = (
                            f"Role `{role}` used a complete response found after "
                            f"{transport} transport failure: {detail}"
                        )
                        if use_peer:
                            self._peer_active = False
                            notice += (
                                " Remaining peer-owned roles will use fresh internal "
                                f"`{self.native_engine}` calls."
                            )
                        self._notices.append(notice)
                        self._transport_incomplete = True
                        record.append(f"{record_title} transport notice", notice)
                        return _ParsedCall(failure.usable_response, value)
                detail = failure.display() if isinstance(failure, CallFailure) else str(failure)
                record.append(
                    f"{record_title} technical attempt {attempt}",
                    detail,
                )
                if attempt < attempts:
                    continue
                if use_peer:
                    self._peer_active = False
                    notice = (
                        f"Peer role `{role}` was unavailable or malformed: {detail} "
                        "Remaining peer-owned roles will use fresh internal "
                        f"`{self.native_engine}` calls."
                    )
                    self._notices.append(notice)
                    record.append("Route changed to internal", notice)
                    try:
                        response = self.native.call(packet, role=role)
                        self._record_native_model_attribution(
                            record, record_title, role
                        )
                        value = parser(response)
                        return _ParsedCall(response, value)
                    except (CallFailure, MalformedResponse) as native_failure:
                        native_detail = (
                            native_failure.display()
                            if isinstance(native_failure, CallFailure)
                            else str(native_failure)
                        )
                        record.append(
                            f"{record_title} internal recovery",
                            native_detail,
                        )
                        raise _StageIncomplete(
                            f"Role `{role}` did not complete after peer failure and one "
                            f"fresh internal `{self.native_engine}` recovery: "
                            f"{native_detail}"
                        ) from native_failure
                raise _StageIncomplete(
                    f"Role `{role}` did not complete after one fresh internal "
                    f"`{self.native_engine}` recovery: "
                    f"{detail}"
                ) from failure

        raise AssertionError("Unreachable fixed recovery branch.")

    def _record_native_model_attribution(
        self,
        record: RunRecord,
        record_title: str,
        role: str,
    ) -> None:
        effective_model = getattr(self.native, "effective_model", None)
        if effective_model is None:
            return
        selector = self.native_model_selector or "not explicitly selected"
        record.append(
            f"{record_title} native model attribution",
            f"Role: `{role}`\n\n"
            f"Requested native model selector: `{selector}`\n\n"
            f"Returned effective native model: `{effective_model}`",
        )

    def _reset_route(self, initial_notices: Sequence[str]) -> None:
        self._peer_active = self.peer is not None
        self._notices = list(initial_notices)
        self._transport_incomplete = False

    @staticmethod
    def _validate_material(material: UserMaterial) -> None:
        if material.original == "":
            raise OraReviewError("The original user request is empty.")
