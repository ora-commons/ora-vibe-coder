"""One fixed, external-only Ora validation path."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from .adapters import BridgeAdapter, BridgeProvenance, BridgeResponse
from .errors import CallFailure, MalformedResponse, OraReviewError
from .models import AnswerBoundary, StageMaterial, UserMaterial
from .packet import PacketBuilder, sha256_text
from .record import RunRecord


VALIDATOR_INITIATOR = "ora-validator"
_SAFE_ROOT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]*$", re.ASCII)
_SAFE_PEER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", re.ASCII)
_ROOT_HEADER = re.compile(
    r"^## (?P<root>.+) — (?P<decision>ACCEPT|REJECT)$"
)
_VALIDATION_MARKER = re.compile(
    r"<<<ORA-VALIDATION-(?:BEGIN|END):[^\r\n>]+>>>"
)
_STRUCTURAL_HEADING = re.compile(r"^[ ]{0,3}#{1,6}(?:[ \t]+|$)")
_AGGREGATE_VERDICT = re.compile(
    r"^[ ]{0,3}(?:(?:#{1,6}[ \t]+)?(?:OVERALL[ \t]+)?"
    r"(?:VERDICT|RESULT|STATUS|DECISION):|"
    r"\*\*(?:OVERALL[ \t]+)?(?:VERDICT|RESULT|STATUS|DECISION):\*\*)"
    r"[ \t]*(?:PASS|FAIL)[ \t]*\r?$",
    re.MULTILINE | re.IGNORECASE,
)
_SPLIT_AGGREGATE_VERDICT = re.compile(
    r"^[ ]{0,3}#{1,6}[ \t]+OVERALL(?:[ \t]+#+)?[ \t]*\r?\n"
    r"(?:[ \t]*\r?\n)*[ ]{0,3}(?:PASS|FAIL)[ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)
_FIELDS = ("BEHAVIOR", "MECHANISM", "EVIDENCE", "LIMITATIONS")
_OUTSIDE_ROOT_VERDICT = re.compile(
    r"^[ ]{0,3}#{1,6}[ \t]+[A-Za-z0-9][A-Za-z0-9._:/@+-]*[ \t]+"
    r"—[ \t]+(?:ACCEPT|REJECT|PASS|FAIL)(?:[ \t]+#+)?[ \t]*\r?$",
    re.MULTILINE | re.IGNORECASE | re.ASCII,
)
_OUTSIDE_LABELLED_VERDICT = re.compile(
    r"^[ ]{0,3}(?:(?:#{1,6}[ \t]+)?(?:OVERALL[ \t]+)?"
    r"(?:VERDICT|RESULT|STATUS|DECISION|CORRECTION):|"
    r"\*\*(?:OVERALL[ \t]+)?"
    r"(?:VERDICT|RESULT|STATUS|DECISION|CORRECTION):\*\*)"
    r"[ \t]*(?:ACCEPT|REJECT|PASS|FAIL)[.!]?(?:[ \t]+#+)?[ \t]*\r?$",
    re.MULTILINE | re.IGNORECASE,
)
_OUTSIDE_STANDALONE_VERDICT = re.compile(
    r"^[ ]{0,3}(?:(?:#{1,6}|[-*+])[ \t]+)?(?:\*\*|__|`)?"
    r"(?:ACCEPT|REJECT|PASS|FAIL)(?:\*\*|__|`)?[.!]?"
    r"(?:[ \t]+#+)?[ \t]*\r?$",
    re.MULTILINE | re.IGNORECASE,
)
_OUTSIDE_VALIDATOR_FIELD = re.compile(
    r"^[ ]{0,3}#{1,6}[ \t]+(?:BEHAVIOR|MECHANISM|EVIDENCE|LIMITATIONS)"
    r"(?:[ \t]+#+)?[ \t]*\r?$",
    re.MULTILINE | re.IGNORECASE,
)
_OUTSIDE_TRUSTED_WRAPPER = re.compile(
    r"^[ ]{0,3}(?:#{1,6}[ \t]+Ora Validator Result"
    r"(?:[ \t]+#+)?[ \t]*\r?$|"
    r"(?:Route|Selected peer|Bridge format|Bridge direction|Bridge session|"
    r"Response message(?: SHA-256)?|Response body SHA-256|Fallback):|"
    r"Peer-authored root decisions(?:,|:))",
    re.MULTILINE | re.IGNORECASE,
)


@dataclass(frozen=True)
class ValidationRequest:
    request: str
    roots: tuple[str, ...]
    peer: str
    run_root: Path | None = None


@dataclass(frozen=True)
class RootDecision:
    root: str
    decision: str
    behavior: str
    mechanism: str
    evidence: str
    limitations: str


@dataclass(frozen=True)
class ValidationResult:
    output: str
    run_path: str
    readiness: str
    notices: tuple[str, ...]
    decisions: tuple[RootDecision, ...]
    provenance: BridgeProvenance


class _PreparedPeer(Protocol):
    last_call_notice: str

    def call_with_provenance(
        self, packet: str, *, role: str
    ) -> BridgeResponse: ...


PeerFactory = Callable[..., tuple[_PreparedPeer, str]]
StatusSink = Callable[[str], None]


def _contains_outside_certification_material(text: str) -> bool:
    return bool(
        _OUTSIDE_ROOT_VERDICT.search(text)
        or _OUTSIDE_LABELLED_VERDICT.search(text)
        or _OUTSIDE_STANDALONE_VERDICT.search(text)
        or _OUTSIDE_VALIDATOR_FIELD.search(text)
        or _OUTSIDE_TRUSTED_WRAPPER.search(text)
    )


def _extract_validation_body(
    response: str,
    boundary: AnswerBoundary,
) -> str:
    markers = tuple(_VALIDATION_MARKER.findall(response))
    if response.count(boundary.begin) != 1 or response.count(boundary.end) != 1:
        raise MalformedResponse(
            "The external response did not contain exactly one supplied validation "
            "boundary pair."
        )
    if markers != (boundary.begin, boundary.end):
        raise MalformedResponse(
            "The external response contained an additional or foreign validation marker."
        )
    start_marker = response.index(boundary.begin)
    end_marker = response.index(boundary.end)
    if end_marker <= start_marker:
        raise MalformedResponse("The validation boundary order was invalid.")
    before = response[:start_marker]
    after = response[end_marker + len(boundary.end) :]
    if (
        _contains_outside_certification_material(before)
        or _contains_outside_certification_material(after)
    ):
        raise MalformedResponse(
            "The external response contained ambiguous certification material outside "
            "the validation boundaries."
        )
    start = start_marker + len(boundary.begin)
    body = response[start:end_marker]
    if body.startswith("\r\n"):
        body = body[2:]
    elif body.startswith("\n"):
        body = body[1:]
    if body.endswith("\r\n"):
        body = body[:-2]
    elif body.endswith("\n"):
        body = body[:-1]
    if not body.strip():
        raise MalformedResponse("The validation boundaries contained no root decisions.")
    return body


def parse_root_decisions(
    response: str,
    *,
    boundary: AnswerBoundary,
    requested_roots: tuple[str, ...],
) -> tuple[str, tuple[RootDecision, ...]]:
    """Parse only the fixed per-root decision shape."""

    body = _extract_validation_body(response, boundary)
    lines = body.splitlines()
    if (
        _AGGREGATE_VERDICT.search(body)
        or _SPLIT_AGGREGATE_VERDICT.search(body)
        or any(line.strip() in {"PASS", "FAIL"} for line in lines)
    ):
        raise MalformedResponse(
            "The external response used an aggregate PASS/FAIL verdict; Ora Validator "
            "requires one ACCEPT or REJECT decision per requested root."
        )

    requested = set(requested_roots)
    decisions: list[RootDecision] = []
    seen: set[str] = set()
    index = 0

    while index < len(lines):
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index >= len(lines):
            break

        header = _ROOT_HEADER.fullmatch(lines[index])
        if header is None:
            raise MalformedResponse(
                f"Expected an exact per-root ACCEPT or REJECT heading at line {index + 1}."
            )
        root = header.group("root")
        decision = header.group("decision")
        if root not in requested:
            raise MalformedResponse(
                f"The external response included unexpected root `{root}`."
            )
        if root in seen:
            raise MalformedResponse(
                f"The external response repeated root `{root}`."
            )
        seen.add(root)
        index += 1

        values: dict[str, str] = {}
        for field in _FIELDS:
            while index < len(lines) and not lines[index].strip():
                index += 1
            expected = f"### {field}"
            if index >= len(lines) or lines[index] != expected:
                raise MalformedResponse(
                    f"Root `{root}` must contain exactly one `{expected}` field in "
                    "the required order."
                )
            index += 1
            value_start = index
            while index < len(lines) and _STRUCTURAL_HEADING.match(lines[index]) is None:
                index += 1
            value = "\n".join(lines[value_start:index]).strip()
            if not value:
                raise MalformedResponse(
                    f"Root `{root}` has an empty `{expected}` field."
                )
            values[field] = value

        decisions.append(
            RootDecision(
                root=root,
                decision=decision,
                behavior=values["BEHAVIOR"],
                mechanism=values["MECHANISM"],
                evidence=values["EVIDENCE"],
                limitations=values["LIMITATIONS"],
            )
        )

    missing = [root for root in requested_roots if root not in seen]
    if missing:
        formatted = ", ".join(f"`{root}`" for root in missing)
        raise MalformedResponse(
            f"The external response omitted requested root(s): {formatted}."
        )
    return body, tuple(decisions)


class ValidationRunner:
    """Send one protected packet to one explicit peer and never fall back."""

    INSTRUCTIONS = ("universal.md", "validator.md", "output-validator.md")

    def __init__(
        self,
        *,
        peer_factory: PeerFactory = BridgeAdapter.prepare,
        packet_builder: PacketBuilder | None = None,
        status_sink: StatusSink | None = None,
    ) -> None:
        self.peer_factory = peer_factory
        self.packet_builder = packet_builder or PacketBuilder()
        self.status_sink = status_sink or (lambda _message: None)
        self.run_path: str | None = None

    def run(self, request: ValidationRequest) -> ValidationResult:
        self._validate_request(request)
        material = UserMaterial(original=request.request)
        root_manifest = json.dumps(
            list(request.roots),
            ensure_ascii=True,
            indent=2,
        )
        snapshot = self.packet_builder.snapshot_instructions(self.INSTRUCTIONS)
        record = RunRecord.create(
            tool="ora-validator",
            ending="one external call",
            route="external",
            material=material,
            instruction_snapshot=snapshot,
            run_root=request.run_root,
            selected_peer=request.peer,
            requested_roots=request.roots,
        )
        self.run_path = str(record.path)

        try:
            peer, readiness = self.peer_factory(
                peer=request.peer,
                initiator=VALIDATOR_INITIATOR,
            )
            record.append_artifact("Agent Bridge readiness", readiness)
            self.status_sink(readiness)

            stage_material = (
                StageMaterial(
                    "REQUESTED ROOT IDS — EXACT CLI CONFIGURATION",
                    root_manifest,
                ),
            )
            boundary = self.packet_builder.validation_boundary(
                (request.request, root_manifest)
            )
            packet = self.packet_builder.build(
                material=material,
                role_files=("validator.md",),
                output_file="output-validator.md",
                stage_material=stage_material,
                answer_boundary=boundary,
            )
            response = peer.call_with_provenance(
                packet,
                role="ora-validator-external-validation",
            )
            notice = peer.last_call_notice
            if notice:
                record.append_artifact("Agent Bridge call notice", notice)
                self.status_sink(notice)
            record.append_artifact(
                "External response body before mechanical validation",
                response.body,
            )
            self._verify_provenance(response, request)
            provenance_text = self._render_provenance(response.provenance)
            record.append("Verified transport provenance", provenance_text)
            decision_body, decisions = parse_root_decisions(
                response.body,
                boundary=boundary,
                requested_roots=request.roots,
            )
            output = self._render_output(response.provenance, decision_body)
            record.append_artifact("Certified Ora Validator output", output)
            record.finish("VALIDATION COMPLETE")
        except (CallFailure, MalformedResponse, OraReviewError) as failure:
            usable = getattr(failure, "usable_response", None)
            if usable is not None:
                record.append_artifact(
                    "Uncertified response after transport failure",
                    usable,
                )
            detail = (
                failure.display()
                if isinstance(failure, CallFailure)
                else str(failure)
            )
            record.append_artifact(
                "Technical failure — no certification",
                detail,
            )
            record.finish("TECHNICAL FAILURE — NO CERTIFICATION")
            raise

        notices = (notice,) if notice else ()
        return ValidationResult(
            output=output,
            run_path=str(record.path),
            readiness=readiness,
            notices=notices,
            decisions=decisions,
            provenance=response.provenance,
        )

    @staticmethod
    def _validate_request(request: ValidationRequest) -> None:
        if request.request == "":
            raise OraReviewError("The validator request file is empty.")
        if not request.roots:
            raise OraReviewError("At least one --root ID is required.")
        if len(set(request.roots)) != len(request.roots):
            raise OraReviewError("Each requested root must be named exactly once.")
        for root in request.roots:
            if _SAFE_ROOT.fullmatch(root) is None:
                raise OraReviewError(
                    f"Root ID `{root}` is not a safe nonempty CLI token. Use ASCII "
                    "letters, digits, and . _ : / @ + - characters."
                )
        if _SAFE_PEER.fullmatch(request.peer) is None:
            raise OraReviewError("--peer TARGET must be a safe nonempty CLI token.")

    @staticmethod
    def _verify_provenance(
        response: BridgeResponse,
        request: ValidationRequest,
    ) -> None:
        provenance = response.provenance
        if (
            provenance.bridge_format != 2
            or not provenance.session_verified
            or provenance.peer != request.peer
            or provenance.initiator != VALIDATOR_INITIATOR
            or provenance.from_label != request.peer
            or provenance.to_label != VALIDATOR_INITIATOR
        ):
            raise MalformedResponse(
                "The external response provenance did not prove the selected peer, "
                "Format 2 session, and exact peer-to-validator direction."
            )

        session = provenance.session_dir.expanduser().resolve()
        response_path = provenance.response_path.expanduser().resolve()
        expected_name = (
            f"{provenance.message_sequence:04d}-peer-to-initiator.md"
        )
        if (
            response_path.parent != session / "messages"
            or response_path.name != expected_name
        ):
            raise MalformedResponse(
                "The external response provenance had an ambiguous message identity."
            )
        BridgeAdapter._verify_session_record(
            session,
            peer=request.peer,
            initiator=VALIDATOR_INITIATOR,
        )
        try:
            raw = response_path.read_bytes()
        except OSError as failure:
            raise MalformedResponse(
                f"The verified external response message could not be reread: {failure}"
            ) from failure
        if hashlib.sha256(raw).hexdigest() != provenance.response_sha256:
            raise MalformedResponse(
                "The external response message changed after transport verification."
            )
        if sha256_text(response.body) != provenance.body_sha256:
            raise MalformedResponse(
                "The external response body digest did not match its transport provenance."
            )

    @staticmethod
    def _render_provenance(provenance: BridgeProvenance) -> str:
        return "\n".join(
            (
                "Route: **external**",
                f"Selected peer: {json.dumps(provenance.peer)}",
                f"Bridge format: `{provenance.bridge_format}`",
                "Bridge direction: "
                f"{json.dumps(provenance.from_label)} → "
                f"{json.dumps(provenance.to_label)}",
                f"Bridge session: {json.dumps(str(provenance.session_dir))}",
                f"Response message: {json.dumps(provenance.response_path.name)} "
                f"(`# Message {provenance.message_sequence:04d}`)",
                f"Response message SHA-256: `{provenance.response_sha256}`",
                f"Response body SHA-256: `{provenance.body_sha256}`",
                "Fallback: **none**",
            )
        )

    @classmethod
    def _render_output(
        cls,
        provenance: BridgeProvenance,
        decision_body: str,
    ) -> str:
        return (
            "# Ora Validator Result\n\n"
            f"{cls._render_provenance(provenance)}\n\n"
            "Peer-authored root decisions, copied exactly after mechanical validation:\n\n"
            f"{decision_body}\n"
        )
