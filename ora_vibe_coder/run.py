"""Run to Completion: one fixed route driven only by what was actually saved.

The route is rote — Specification, Plan, Build (the Programming Loop),
independent verification, then Correction and back to verification — entered
at the active stage. Every step is one ordinary work turn through the existing
turn machinery, so the existing saved-file readback decides what each step
achieved; the driver never replays a step, never substitutes a tool, and never
claims a pass the saved records do not show. Runs, their briefs and their
outcomes are retained in the project's existing `.vibe/` turn folders; there is
no separate run store.

This module also builds the step requests the screen's manual buttons use, so
manual and automated requests cannot drift apart.
"""

import json
from pathlib import Path
import re
import threading
import time

from . import conversation
from .handoff import prepare_request, quoted
from .hosts import HOSTS as TOOL_LABELS
from .project import ProjectError, not_started, read_text
from .status import reported_status, review_basis, canonical_verdict

# The route, in order. "correction" returns to "verification".
ROUTE = ("specification", "planning", "build", "verification")
CORRECTION = "correction"
# The peers that can exchange turns in-app; Hermes and Qwen Code have no
# Bridge work mode, so an unattended run cannot use them for any role.
CONVERSATION_PEERS = frozenset({"codex", "claude", "zcode", "minimax"})
ROLE_NAMES = {"specification": "Specification", "specification_review": "Specification Review",
              "specification_second_opinion": "Specification Review Second Opinion",
              "planning": "Planning", "planning_review": "Planning Review",
              "planning_second_opinion": "Planning Review Second Opinion",
              "implementation": "Implementation", "review": "Implementation Review",
              "verification": "Verification", "correction": "Correction"}
OPTIONAL_ROLES = frozenset({"specification_second_opinion", "planning_second_opinion"})
STAGE_ROLE = {"specification": "specification", "planning": "planning", "programming": "implementation",
              "programming-result": "implementation", "verification": "verification"}

STEP_ROLE = {"specification": "specification", "planning": "planning", "build": "implementation",
             "verification": "verification", "correction": "correction"}
STEP_STAGE = {"specification": "specification", "planning": "planning", "build": "programming",
              "result": "programming-result", "verification": "verification",
              "correction": "programming", "create-plan": "planning", "implement-plan": "programming"}
# The stage whose own step falls back to the step-3 selection when no override
# or default names it: the stage the run was entered at.
ENTRY_STEP_ROLE = {"specification": "specification", "planning": "planning", "build": "implementation"}
NO_PROGRESS_LIMIT = 3
STEP_TITLES = {"specification": "Specification", "planning": "Plan", "build": "Build",
               "verification": "Independent verification", "correction": "Correction",
               "result": "Programming Result"}

# --- Step instructions, shared by the manual buttons and every run ------------

DEFAULT_INPUTS = {
    "create-plan": "Create the Plan from the current Specification.",
    "implement-plan": "Implement the current Plan, using the Specification to judge the intended behavior.",
    "specification": ("Work toward a complete, implementation-neutral Specification from the available "
                      "material, questions and the run brief below. Revise the one current Specification "
                      "in place; do not start the Plan or implementation."),
    "planning": ("Create or revise the one current Plan from the current Specification and the project's "
                 "actual state, with implementation steps and appropriate checks. Revise it in place."),
    "result": ("Update the one current Programming Result from the implementation actually performed. "
               "Record what was built, the code location and delivered revisions, checks and review "
               "evidence, and remaining work. Do not create a numbered copy or claim unfinished work "
               "is complete."),
    "verification": ("Coordinate a fresh, independent Ora Verification review of the current implementation "
                     "against the Specification and Plan. The implementation agent must not be its own "
                     "verifier. Save or update one truthful Verification Report, including findings and "
                     "any incomplete checks, and return the result to the user."),
    "correction": ("Correct the in-scope material findings in the current Verification Report using the "
                   "approved Specification and Plan. Perform the normal checks and implementation review "
                   "needed for those corrections, then update the one current Programming Result with what "
                   "changed, what was checked, and anything still outstanding. Stop there. Do not run or "
                   "commission a new Ora Verification review or update the Verification Report in this "
                   "turn; fresh independent verification follows separately. If no report exists, explain "
                   "what evidence is missing before changing code."),
}


def verifier_direction(verifier):
    if not verifier:
        return ("No independent verifier has been selected. Show the user the available qualified "
                "reviewers and ask them to choose before commissioning one. Do not silently select "
                "a reviewer.")
    return (f"The user selected {verifier} as the independent verifier. Commission a fresh {verifier} "
            "session that did not implement this work. If this chat cannot launch that session, explain "
            "how the user can start it with this complete request. If the verifier is unavailable or "
            "cannot be separated from the implementation agent, report that and ask before substituting.")


def result_direction(project):
    saved = project.material("Programming Result")
    if not saved["path"]:
        return ("No Programming Result was found. Continue with the available code and requirements, "
                "and disclose the missing report.")
    return (f"The Programming Result was found at {saved['path']}. Its displayed status is "
            f"{reported_status('programming', saved['text'] or '', saved['path'], field='Status')['label']}; "
            "read the report and actual candidate directly rather than treating the badge as proof.")


def progress_contract():
    """The verifier's Progress section, from the second verification onward."""
    return ("## Progress against the best verified state\n\n"
            "The best verified state's report is quoted below. Your new report must carry a section "
            "headed exactly `Progress` whose first line is exactly `Improved` or `Not improved`, "
            "followed by one `- ` bullet per piece of evidence. Each bullet names either a concrete "
            "reduction in affected behavior — what failed in the best verified state, what fails now, "
            "and the check that shows it — or a cause newly confirmed, with the evidence that confirms "
            "it. None of these is improvement: rewording, splitting or merging findings, fixing one "
            "defect while another of equal effect appears, or returning to an earlier state.")


def build_input(step, project, user_text="", verifier=None, extra=()):
    """The step's fixed assignment, with any user brief as preserved context.

    Every step keeps its full default instruction — including the boundary of
    what this step's own stage permits, such as not starting the Plan or
    implementation from the Specification step — and the user's unsent text
    rides along as preserved context for the intended outcome, never replacing
    the assignment. A brief therefore cannot widen a step beyond its stage.
    """
    parts = []
    text = (user_text or "").strip()
    if step in DEFAULT_INPUTS:
        parts.append(DEFAULT_INPUTS[step])
    if text:
        parts.append("The user's brief for this work, preserved as context for the intended outcome:\n\n" + text)
    if step == "verification":
        parts.append(verifier_direction(verifier or ""))
        parts.append(result_direction(project))
        parts.append("Record the verifier's actual tool and model/provider when reported; a different "
                     "harness name alone does not prove a different AI provider. Honor any cross-vendor "
                     "requirement in the accepted project materials, or ask if it cannot be confirmed.")
    parts.extend(part for part in extra if part)
    return "\n\n".join(parts)


def step_request(project, step, user_text, destination, material=(), verifier=None, extra=(), supplied_documents=None,
                 model="", effort=""):
    """One complete step request, shared by the manual buttons and the run.

    Returns the full prepared packet text. Ordinary requests are saved as
    `Handoff.md`; implementation requests through the existing
    `implement-plan` purpose.
    """
    stage = STEP_STAGE[step]
    return prepare_request(project, stage, build_input(step, project, user_text, verifier, extra),
                           destination, list(material or []), supplied_documents=supplied_documents,
                           model=model, effort=effort)


# --- Resolving each assignment's tool and model -------------------------------

def resolve_assignment(role, config, entry, step3_tool, defaults):
    """Run override, saved default, then the selected harness's own defaults."""
    override = (config or {}).get("roles", {}).get(role)
    if isinstance(override, dict):
        if override.get("tool") or role in OPTIONAL_ROLES:
            return override.get("tool", ""), override.get("model", ""), override.get("effort", ""), "run override"
        return step3_tool or "", "", "", "run override"
    default = (defaults or {}).get(role) or {}
    if default.get("tool") or role in OPTIONAL_ROLES:
        return default.get("tool", ""), default.get("model", ""), default.get("effort", ""), "saved default"
    return step3_tool or "", "", "", "selected harness"


def implementation_direction(tool, model, effort, reviewer, r_model, r_effort, *, conditional=False):
    direction = ("If the user's authorized work uses the bundled Programming Loop, use these selected choices. "
                 "These choices do not request implementation or require the Loop for an ordinary question. "
                 if conditional else "Use the bundled Programming Loop as the structured method for this work. ")
    return (direction +
            f"Name its executor choice as {model_label(tool, model, effort)}, and its separate fresh "
            f"reviewer choice as {model_label(reviewer, r_model, r_effort)}; the Loop's own host "
            "adapters carry those choices to the workers they create.")


def model_label(tool, model, effort):
    """The honest label: requested names are named as requested, never as proof."""
    parts = [f"{TOOL_LABELS[tool][0]}" if tool in TOOL_LABELS else (tool or "no tool")]
    parts.append(f"model {model} (requested)" if model else "its own configured model")
    if effort:
        parts.append(f"effort {effort} (requested)")
    return ", ".join(parts)


def unsupported_roles(config, entry, step3_tool, defaults):
    """Roles whose resolved tool cannot exchange turns in-app.

    Disclosed before the run starts, with the role and tool named; nothing is
    silently substituted, and the run stays unavailable until a supported tool
    is chosen in Configure Path.
    """
    unsupported = []
    for role in {**{STEP_ROLE[step]: "" for step in ROUTE}, "review": "", "correction": ""}:
        tool, _model, _effort, _origin = resolve_assignment(role, config, entry, step3_tool, defaults)
        if tool and tool not in CONVERSATION_PEERS:
            unsupported.append((role, tool))
    return unsupported


# --- Reading what a verification report says ----------------------------------

def verification_verdict(text):
    """PASSED, NOT PASSED, REVIEW INCOMPLETE — or '' when unreadable."""
    label = reported_status("verification", text or "", "", field="Verdict")["label"]
    if label == "INCOMPLETE" or label.startswith("NOT PASSED — REVIEW INCOMPLETE") or label.startswith("NOT PASSED — REVISION INCOMPLETE"):
        return "REVIEW INCOMPLETE"
    if label.startswith("NOT PASSED"):
        return "NOT PASSED"
    if label.startswith("PASSED") or label.startswith("ONE PASS COMPLETE"):
        return "PASSED"
    return ""


def progress_of(text):
    """Whether a NOT PASSED report's Progress section shows evidenced improvement."""
    body = conversation.section_body(text, "Progress")
    if body is None:
        return False, "its Progress section is missing"
    lines = [line for line in body.split("\n") if line.strip()]
    if not lines:
        return False, "its Progress section is empty"
    first = lines[0].strip().strip("*`_")
    if first == "Not improved":
        return False, "it says Not improved"
    if first != "Improved":
        return False, "its Progress section does not begin with Improved or Not improved"
    if not any(line.strip().startswith("- ") and line.strip()[2:].strip() for line in lines[1:]):
        return False, "it says Improved with no evidence bullet"
    return True, ""


def questions_paused(driver_status):
    """The pause questions a run is waiting on, for the composer's answer box."""
    return list(driver_status.get("questions") or []) if driver_status.get("state") == "paused-question" else []


# --- The retained run record ---------------------------------------------------

PURPOSE_RUN = "run"
RUN_START = "run-start"
RUN_OUTCOME = "run-outcome"
RUN_EVIDENCE = "run-evidence"


def run_note_body(kind, run, fields):
    listed = [f"Note: {kind}", f"Purpose: {PURPOSE_RUN}", f"Run: {run}"]
    listed += [f"{key}: {value}" for key, value in fields.items()]
    return "".join(f"Vibe-{field}\n" for field in listed) + "\n"


def _record_run_note(project, folder, kind, run, fields, body=None):
    session = folder / "session"
    arguments = ["record", "--session", str(session), "--kind", "session-create",
                 "--initiator", conversation.INITIATOR, "--peer", "codex", "--mode", "review",
                 "--access-path", str(project.root)]
    conversation.bridge_call(arguments, f"Vibe run note {kind} — run {run}\nProject: {project.root}\n")
    note = conversation.bridge_call(["record", "--session", str(session), "--kind", "note"],
                                    run_note_body(kind, run, fields) + (body or ""))
    if not re.match(r"(\d{4})-", Path(note).name):
        raise ProjectError("Agent Bridge returned an unrecognized record path; the run note was not saved.")


def run_note_fields(folder):
    """The Vibe- fields of a folder's retained run notes, oldest note first."""
    found = []
    messages = Path(folder) / "session" / "messages"
    if not messages.is_dir():
        return found
    for path in sorted(messages.glob("*.md")):
        try:
            message = conversation.parse_message(path)
        except (OSError, UnicodeDecodeError):
            continue
        if message["kind"] != "note":
            continue
        fields = conversation.note_fields(message["body"]) or {}
        if fields.get("Purpose") == PURPOSE_RUN:
            found.append(fields)
    return found


def read_runs(project):
    """Runs derived from the retained notes, oldest first.

    A run with no run-outcome note and no live driver reads as unfinished: the
    existing interrupted-turn detection covers its steps, and nothing replays.
    """
    runs = {}
    for folder in conversation.turn_folders(project):
        for fields in run_note_fields(folder):
            run = fields.get("Run", "")
            if not run:
                continue
            kind = fields.get("Note", "")
            entry = runs.setdefault(run, {"run": run, "state": "open", "reason": "", "steps": []})
            if kind == RUN_START:
                entry["started"] = folder.name
                try:
                    entry["config"] = json.loads(fields.get("Config-JSON", "null") or "null")
                except ValueError:
                    entry["config"] = None
            elif kind == RUN_OUTCOME:
                outcome = fields.get("Run-Outcome", "")
                entry["state"] = outcome if outcome in {"complete", "unfinished"} else "open"
                entry["reason"] = fields.get("Reason", "")
            elif kind == RUN_EVIDENCE:
                entry["best_verified"] = True
        turn = conversation.read_turn(folder)
        if turn["purpose"] == conversation.PURPOSE_WORK and turn["fields"].get("Run"):
            run = turn["fields"]["Run"]
            if run in runs:
                runs[run]["steps"].append({"step": turn["fields"].get("Run-Step", ""),
                                           "state": turn["state"], "turn": folder.name})
    return [runs[name] for name in sorted(runs)]


# --- The driver ----------------------------------------------------------------

class RunDriver:
    """One live Run to Completion, in memory while it works."""

    def __init__(self, registry, project, entry, brief, config, defaults, step3_tool, attachments=None, files=()):
        self.registry = registry
        self.project = project
        self.entry = entry
        self.brief = brief or ""
        # Brief pictures keep the wire shape start_turn's images parameter
        # takes, so they ride the first dispatched entry step unchanged.
        self.brief_images = list(attachments or [])
        self.brief_files = list(files or [])
        self.config = config or {}
        self.defaults = defaults or {}
        self.step3_tool = step3_tool or ""
        self.run = ""
        self.step = entry if entry in ROUTE else "build"
        self.state = "starting"
        self.reason = ""
        self.questions = []
        self.observation = ""
        self.no_progress = 0
        self.attempt_note = ""
        self.repeat_best_guess = False
        self.best_report = None
        self.not_passed_seen = False
        self.verdicts = []
        self.stop_requested = False
        self.resume_answer = ""
        self.handle = None
        self.worker = None
        self.brief_used = False
        self.step_requested = ""
        self.reported_model = ""
        self.started = time.monotonic()
        self.started_wall = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.lock = threading.Lock()
        self.done = threading.Event()

    # -- lifecycle ----------------------------------------------------------

    def start(self):
        self._record_start()
        self.state = "running"
        self.worker = threading.Thread(target=self._drive, daemon=False,
                                       name=f"Ora Vibe Coder run {self.run}")
        self.worker.start()

    def _record_start(self):
        # The brief's pictures are held in the wire shape every turn accepts —
        # the same {"name", "data"} dicts start_turn normalizes through
        # prepare_images — so the run-start note validates and retains them
        # once here, and the first dispatched entry step re-supplies them
        # unchanged, exactly like the brief's text and files.
        prepared = conversation.prepare_images(self.brief_images)
        folder = conversation.reserve_turn_folder(self.project)
        self.run = folder.name
        conversation.save_attachments(folder, prepared)
        fields = {"Brief": self.brief or "(no text)",
                  "Brief-Files-JSON": json.dumps(self.brief_files, ensure_ascii=True),
                  "Brief-Images": "; ".join(name for name, _data in prepared),
                  "Entry": self.entry,
                  "Config-JSON": json.dumps(self.config, ensure_ascii=True)}
        _record_run_note(self.project, folder, RUN_START, self.run, fields)

    def request_stop(self):
        with self.lock:
            self.stop_requested = True
            handle = self.handle
        if handle is not None:
            handle.cancel()

    def receive_answer(self, text):
        """One answered pause: the count resets and the same step resumes."""
        with self.lock:
            self.resume_answer = (text or "").strip()
            self.no_progress = 0
            self.attempt_note = ""
            if self.state == "paused-question":
                self.state = "running"

    def configure(self, config):
        """Per-run overrides, stored in this run's record; never saved settings."""
        with self.lock:
            self.config = config or self.config
        folder = conversation.reserve_turn_folder(self.project)
        _record_run_note(self.project, folder, RUN_START, self.run,
                         {"Config-JSON": json.dumps(self.config, ensure_ascii=True),
                          "Reconfigures": self.run})

    def resume(self):
        with self.lock:
            if self.state in {"paused-failure"}:
                self.state = "running"
                self.reason = ""
                return True
        return False

    def _brief_pending(self):
        """True while the entry step's brief has not reached its AI yet."""
        return self.step == self.entry and not self.brief_used

    def pending_brief(self):
        """The brief a paused entry step still owes its AI, or "".

        A start that never dispatched did not consume the brief, so the
        step's retry and the Copy request fallback both re-supply it; it is
        consumed only by the first attempt that actually dispatches.
        """
        return self.brief if self._brief_pending() else ""

    def pending_pictures(self):
        """The names of the brief pictures a paused entry step still owes its AI.

        A copy cannot carry pictures, so the manual fallback names each one
        as not included instead of silently dropping it; the pictures stay
        retained in this project's run record.
        """
        return [item.get("name", "") for item in self.brief_images] if self._brief_pending() else []

    # -- the fixed route ----------------------------------------------------

    def _drive(self):
        try:
            self._loop()
        except BaseException as error:  # Never lose the run without a record.
            self._end("unfinished", f"The run failed: {error}")
        finally:
            self.done.set()

    def _loop(self):
        while True:
            if self.stop_requested:
                self._end("unfinished", "Stopped by the user. Files already changed remain; the run never replays by itself.")
                return
            if self.state in {"complete", "unfinished"}:
                return
            if self.state.startswith("paused"):
                self._wait_for_resume()
                continue
            if not self._send_step():
                continue  # Paused or ended; the checks above route the next pass.

    def _wait_for_resume(self):
        """Block the driver until a resume, an answer, or a stop arrives."""
        while True:
            if self.stop_requested:
                self._end("unfinished", "Stopped by the user. Files already changed remain; the run never replays by itself.")
                return
            with self.lock:
                if self.state == "running":
                    return
            time.sleep(0.3)

    def _send_step(self):
        """Send the current step once and decide what followed, per the order."""
        tool, model, effort, origin = self._assignment()
        if tool not in CONVERSATION_PEERS:
            self._pause_failure(f"{ROLE_NAMES[STEP_ROLE[self.step]]} is assigned to {TOOL_LABELS.get(tool, (tool,))[0]}, "
                                "which cannot exchange turns in-app, so an unattended run cannot use it. "
                                "Choose a supported tool in Configure Path; nothing was substituted.")
            return False
        # Dispatch-time revalidation against the actual current components,
        # so a stale screen cannot start an unsupported route: every role's
        # tool needs the Bridge work route, and the Build-family steps also
        # need the applicable bundled Loop adapter. The named component,
        # reason and remedy ride the pause; nothing is substituted.
        try:
            action = f"the {ROLE_NAMES[STEP_ROLE[self.step]]} step"
            conversation.require_work_route(tool, action)
            if self.step in {"build", "correction"}:
                conversation.require_build_route(tool, action)
        except ProjectError as error:
            self._pause_failure(f"{error} Fix it and resume, or stop the run. "
                                "Copy request under the run banner can deliver this step manually.")
            return False
        extra = []
        verifier = None
        if self.step in {"build", "correction"}:
            reviewer, r_model, r_effort, _origin = self._assignment_for("review")
            extra.append(implementation_direction(tool, model, effort, reviewer, r_model, r_effort))
        if self.step == "verification":
            verifier = TOOL_LABELS.get(tool, (tool,))[0]
            if self.best_report is not None:
                extra.append(progress_contract())
                extra.append("## The best verified state — quoted data\n\n" + quoted(self.best_report))
        if self.attempt_note:
            extra.append("## Changed approach required\n\n" + self.attempt_note)
        if self.config.get("best_guess"):
            extra.append("When a decision or fact you need is missing, make a reasonable best guess, "
                         "record it explicitly as an assumption in your saved document, and continue. "
                         "Do not ask the user.")
        user_text = self.pending_brief()
        answer = ""
        with self.lock:
            answer, self.resume_answer = self.resume_answer, ""
        if answer:
            extra.append("## The user's answer to your paused questions\n\n" + answer)
        extra.append(f"This step runs on {model_label(tool, model, effort)} ({origin} for this run).")
        text = build_input(self.step, self.project, user_text, verifier, extra)
        images = self.brief_images if self._brief_pending() else []
        files = self.brief_files if self._brief_pending() else []
        self.step_requested = model_label(tool, model, effort)
        try:
            supplied_documents = self.project.approve_transition(self.step)
            self.handle = conversation.start_turn(
                self.registry, self.project, tool, STEP_STAGE[self.step], text, images, files,
                run_fields={"Run": self.run, "Run-Step": self.step}, model=model, effort=effort,
                supplied_documents=supplied_documents)
        except (ProjectError, OSError) as error:
            self._pause_failure(f"The step could not start: {error} Fix it and resume, or stop the run. "
                                "Copy request under the run banner can deliver this step manually.")
            return False
        # The brief is consumed only now that its step's turn was admitted and
        # dispatched: the failed start above left it pending, so the retry and
        # the Copy request fallback re-supply it instead of dropping it.
        self.brief_used = True
        self.handle.done.wait()
        model_reported, _provider = self.handle.observed_identity()
        with self.lock:
            self.reported_model = model_reported
        return self._decide()

    def _assignment(self):
        return self._assignment_for(STEP_ROLE[self.step])

    def assignment(self, role=None):
        """The resolved (tool, model, effort, origin) for this or a named role."""
        return self._assignment_for(role or STEP_ROLE[self.step])

    def _assignment_for(self, role):
        return resolve_assignment(role, self.config, self.entry, self.step3_tool, self.defaults)

    def _decide(self):
        handle = self.handle
        turn = conversation.read_turn(self.project.root / conversation.VIBE / handle.turn) if handle.turn else {}
        reply = turn.get("reply")
        if handle.state == "interrupted":
            with self.lock:
                stopped = self.stop_requested
            self._end("unfinished",
                      "Stopped by the user. Files already changed remain; the run never replays by itself."
                      if stopped else conversation.INTERRUPTED_REASON)
            return False
        if handle.state == "failed":
            self._pause_failure(handle.reason or "The step's tool call failed with no recorded reason.")
            return False
        questions = conversation.questions_in(reply) if reply else []
        if reply and "no actionable product brief" in reply.casefold():
            self._end("unfinished", "The step's AI refused the work: no actionable product brief. "
                      "Add material to the project and start a new run.")
            return False
        # 2. Questions for you pause the run; in best-guess mode the step is
        #    sent again and that repeat counts as an attempt without progress.
        if questions:
            if self.config.get("best_guess"):
                self.no_progress += 1
                self.attempt_note = ("The previous attempt asked the user questions instead of continuing. "
                                     "It said:\n\n" + quoted("\n".join(questions)) +
                                     "\n\nMake and record a best guess for each of those questions as an "
                                     "assumption in your saved document, and continue.")
                self.observation = "Step asked questions; a best-guess repeat was sent."
                if self.no_progress >= NO_PROGRESS_LIMIT:
                    self._end_unfinished_no_progress("the step kept asking instead of making best guesses")
                return True
            with self.lock:
                self.state = "paused-question"
                self.questions = questions
                self.observation = "Paused for your answer."
            self._observe("Paused: the step asked questions only you can answer.")
            return False
        return self._decide_result(handle, turn)

    def _decide_result(self, handle, turn):
        step = self.step
        artifact = handle.artifact or {}
        changed = artifact.get("outcome") == "changed"
        if step in {"specification", "planning"}:
            role = "Specification" if step == "specification" else "Plan"
            item = self.project.material(role)
            ok = item["text"] is not None and not not_started(item["text"])
            if ok:
                self.observation = f"{role} saved." if changed else f"The existing {role} stands."
                self._advance()
                return True
            self._no_result(f"the step did not leave a filled-in {role}")
            return True
        if step in {"build", "correction"}:
            ok = changed and artifact.get("role") == "Programming Result"
            if ok:
                self.observation = "Programming Result saved."
                if step == "build":
                    self._advance()
                else:
                    # A correction's own saved result neither raises nor resets
                    # the count; the verification that follows judges it.
                    self.step = "verification"
                return True
            self._no_result("the step did not save the Programming Result during this step")
            return True
        if step == "verification":
            return self._decide_verification(handle, artifact)
        self._no_result("the step produced nothing the run can read")
        return True

    def _decide_verification(self, handle, artifact):
        report = self.project.material("Verification Report")
        current = (artifact.get("role") == "Verification Report" and artifact.get("outcome") == "changed"
                   and report["text"] is not None)
        if not current:
            reason = ("the Verification Report was not saved during this verification step, so no result of "
                      "this run exists whatever the earlier report says"
                      if artifact.get("outcome") != "changed" else "the saved Verification Report could not be read back")
            self.no_progress += 1
            self.attempt_note = (f"The previous verification attempt failed: {reason}. "
                                 "Investigate the cause and change the approach, then save or update the one current "
                                 "Verification Report in this step, with a readable verdict.")
            self.observation = "Verification Report: not a result of this run."
            if self.no_progress >= NO_PROGRESS_LIMIT:
                self._end_unfinished_no_progress(reason)
            return True
        verdict = verification_verdict(report["text"])
        if not verdict:
            self.no_progress += 1
            self.attempt_note = ("The previous verification saved a report whose verdict cannot be read. "
                                 "Investigate the cause and change the approach, then save one current Verification "
                                 "Report whose verdict line states PASSED or NOT PASSED.")
            self.observation = "Verification Report: verdict unreadable."
            if self.no_progress >= NO_PROGRESS_LIMIT:
                self._end_unfinished_no_progress("the saved Verification Report has no readable verdict")
            return True
        with self.lock:
            self.verdicts.append(verdict)
        if verdict == "PASSED":
            self.observation = "Verification Report: PASSED."
            self._end("complete", "Verification passed; the run is complete.")
            return False
        if verdict == "REVIEW INCOMPLETE":
            self.no_progress += 1
            self.attempt_note = ("The previous verification did not finish: the report records REVIEW INCOMPLETE. "
                                 "Investigate the cause and change the approach, then complete or rerun the review so "
                                 "one current report states a full verdict.")
            self.observation = "Verification Report: REVIEW INCOMPLETE."
            if self.no_progress >= NO_PROGRESS_LIMIT:
                self._end_unfinished_no_progress("verification stayed REVIEW INCOMPLETE")
            return True
        # NOT PASSED: the first becomes the best verified state; a later one
        # must show evidenced improvement over the best one, not the previous.
        if not self.not_passed_seen:
            self.not_passed_seen = True
            self.no_progress = 0
            self._remember_best(report["text"])
            self.observation = "Verification Report: NOT PASSED. Correction follows."
            self.step = "correction"
            return True
        improved, why_not = progress_of(report["text"])
        if improved:
            self.no_progress = 0
            self.attempt_note = ""
            self._remember_best(report["text"])
            self.observation = "Verification Report: NOT PASSED, improved over the best verified state. Correction follows."
            self.step = "correction"
            return True
        self.no_progress += 1
        self.attempt_note = (f"The previous correction did not improve on the best verified state ({why_not}). "
                             "Investigate the cause and change the approach; rewording findings or trading one "
                             "defect for another of equal effect is not improvement.")
        self.observation = "Verification Report: NOT PASSED, not improved."
        if self.no_progress >= NO_PROGRESS_LIMIT:
            self._end_unfinished_no_progress(f"the report was Not improved ({why_not})")
        return True

    def _remember_best(self, text):
        self.best_report = text
        folder = conversation.reserve_turn_folder(self.project)
        _record_run_note(self.project, folder, RUN_EVIDENCE, self.run,
                         {"Verdict": "NOT PASSED", "Order": "best verified state"},
                         "\n# Best verified state — the report's full text\n\n" + quoted(text))

    def _advance(self):
        self.no_progress = 0
        self.attempt_note = ""
        order = list(ROUTE)
        self.step = order[min(order.index(self.step) + 1, len(order) - 1)] if self.step in order else "verification"

    def _no_result(self, what):
        self.no_progress += 1
        reason = self.handle.reason or self.observation or "no reason was recorded"
        self.attempt_note = (f"The previous attempt failed to produce its required result: {what}. "
                             f"Its stated reason, quoted:\n\n{quoted(reason)}\n\n"
                             "Investigate why it produced nothing and change the approach.")
        self.observation = f"No result: {what}."
        if self.no_progress >= NO_PROGRESS_LIMIT:
            self._end_unfinished_no_progress(what)

    def _pause_failure(self, reason):
        with self.lock:
            self.state = "paused-failure"
            self.reason = reason
            self.observation = "Paused: operational failure."
        self._observe(f"Paused: {reason}")

    def _end_unfinished_no_progress(self, what):
        best = "The best available artifact is the best verified state's NOT PASSED report." if self.best_report else (
            "The best available artifact is the work already saved in the project.")
        self._end("unfinished",
                  f"The run ended unfinished after {NO_PROGRESS_LIMIT} attempts without progress: {what}. "
                  f"{best} Nothing is claimed to have passed; the real check status is what the saved reports say.")

    def _end(self, outcome, reason):
        # The durable outcome note is written before the in-memory state claims
        # it, so a reader that sees the terminal state can also read the record.
        with self.lock:
            if self.state in {"complete", "unfinished"}:
                return
            self.state = "ending"
        try:
            folder = conversation.reserve_turn_folder(self.project)
            _record_run_note(self.project, folder, RUN_OUTCOME, self.run,
                             {"Run-Outcome": outcome, "Reason": " ".join(reason.split())})
        except (OSError, ProjectError):
            pass
        with self.lock:
            self.state = outcome
            self.reason = reason
        self._observe(reason)

    def _observe(self, observation):
        with self.lock:
            self.last_observation = observation

    # -- status -------------------------------------------------------------

    def status(self):
        with self.lock:
            handle = self.handle
            elapsed = time.monotonic() - self.started
            state, step = self.state, self.step
            config = dict(self.config)
            effective_roles = {role: dict(zip(("tool", "model", "effort"), self._assignment_for(role)[:3]))
                               for role in ROLE_NAMES}
        operation = handle.snapshot() if handle is not None else None
        live = operation and operation.get("state") in {"starting", "running"}
        return {"run": self.run, "state": state, "step": step, "entry": self.entry,
                "reason": self.reason, "questions": list(self.questions),
                "observation": self.observation, "no_progress": self.no_progress,
                "best_verified": self.best_report is not None,
                "verdicts": list(self.verdicts),
                "model": self.step_requested, "reported_model": self.reported_model,
                "elapsed_seconds": round(operation.get("elapsed_seconds") if live else elapsed, 1),
                "last_contact_seconds": operation.get("last_contact_seconds") if live else None,
                "config": config, "effective_roles": effective_roles}


class RunRegistry:
    """Live run drivers in memory, one per project at a time."""

    def __init__(self):
        self.lock = threading.Lock()
        self.by_project = {}

    def find(self, project):
        with self.lock:
            driver = self.by_project.get(str(project.root))
        return driver if driver and driver.state not in {"complete", "unfinished", "ending"} else None

    def last(self, project):
        with self.lock:
            return self.by_project.get(str(project.root))

    def start(self, registry, project, entry, brief, config, defaults, step3_tool, images, files):
        current = self.find(project)
        if current is not None:
            raise ProjectError("A Run to Completion is already active in this project. Stop it before starting another.")
        unsupported = unsupported_roles(config, entry, step3_tool, defaults)
        if unsupported:
            role, tool = unsupported[0]
            raise ProjectError(f"{ROLE_NAMES[role]} is assigned to {TOOL_LABELS.get(tool, (tool,))[0]}, "
                               "which cannot exchange turns in-app, so an unattended run cannot use it. "
                               "Choose a supported tool in Configure Path; nothing was substituted and the run did not start.")
        driver = RunDriver(registry, project, entry, brief, config, defaults, step3_tool, images, files)
        driver.start()  # Raises on a failed brief save; the run never starts.
        with self.lock:
            self.by_project[str(project.root)] = driver
        return driver

    def stop(self, project):
        driver = self.find(project)
        if driver is None:
            raise ProjectError("No run is active in this project.")
        driver.request_stop()
        return driver

    def drain(self):
        """Request stop on every live run; Stop Vibe ends them with the turns."""
        with self.lock:
            drivers = [driver for driver in self.by_project.values()
                       if driver.state not in {"complete", "unfinished"}]
        for driver in drivers:
            driver.request_stop()
        for driver in drivers:
            driver.done.wait(10)
