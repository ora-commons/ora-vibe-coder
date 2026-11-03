"""Run to Completion: one fixed route driven only by what was actually saved.

The route is rote — Specification, Plan, Build (the Programming Loop),
independent verification, then Correction, which settles in place — entered
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
from .status import (VALUES, correction_dispositions, reported_status,
                     review_disposition, verification_finding_labels)

# The route, in order. Correction settles in place: a settled correction
# completes the run; an unsettled one is retried as correction.
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
NO_PROGRESS_LIMIT = 3

# --- Step instructions, shared by the manual buttons and every run ------------

DEFAULT_INPUTS = {
    "create-plan": "Create the Plan from the current Specification.",
    "implement-plan": ("Implement the current Plan, using the Specification to judge the intended behavior. "
                       "Use the Programming Loop with a separate fresh reviewer, then save the one current "
                       "Programming Result from the actual work, checks, review, delivery and remaining work."),
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
                     "any incomplete checks, and return the result to the user. The report's opening YAML "
                     "carries `status:` — exactly PASSED, NOT PASSED or INCOMPLETE — and `disposition:` — "
                     "exactly SETTLED, CORRECTION, SEVERE, INCOMPLETE or ASK USER; decide both only after "
                     "the review is finished. Enumerate every finding on its own line with a "
                     "stable label the correction can cite — `- R1 — <finding>`, `- R2 — …`, and `S1`, "
                     "`S2` … for severe findings. Identify every severe finding: unrecoverable data "
                     "loss, security exposure, and unauthorized or erroneous spending, sending or "
                     "publishing; a traced path from an actual permitted input to the harm is sufficient. "
                     "A previously recorded severe finding settles only on a recorded fix with evidence "
                     "that its harmful path was removed."),
    "correction": ("Correct the findings recorded in the current Verification Report using the approved "
                   "Specification and Plan. Fix each one the smallest way or reject it with a concrete "
                   "recorded reason — a reasoned rejection settles a non-severe finding; a severe finding "
                   "settles only through a recorded fix with evidence that its harmful path was removed. "
                   "Perform the normal checks and implementation review needed for those corrections, then "
                   "update the one current Programming Result with what changed, what was checked, the "
                   "disposition of every finding, and anything still outstanding. Record the disposition "
                   "of every finding on its own line in the Programming Result, citing each finding by "
                   "the stable label the Verification Report gave it: "
                   "`- <label> — FIXED — <what changed and the evidence>` "
                   "or `- <label> — REJECTED — <concrete reason>`. The Programming Result's opening YAML "
                   "carries `status:` — exactly PASSED, NOT PASSED or INCOMPLETE — and `disposition:` — "
                   "exactly one current value: SETTLED, SEVERE, INCOMPLETE or ASK USER. Stop there. "
                   "Do not run or commission a new "
                   "Ora Verification review or update the Verification Report in this turn; a settled "
                   "correction completes the work as completed after correction. If no report exists, "
                   "explain what evidence is missing before changing code."),
}


def verifier_direction(verifier, project=None):
    if not verifier:
        return ("No independent verifier has been selected. Show the user the available qualified "
                "reviewers and ask them to choose before commissioning one. Do not silently select "
                "a reviewer.")
    if isinstance(verifier, dict):
        tool = verifier.get("tool", "")
        requested = model_label(tool, verifier.get("model", ""), verifier.get("effort", ""))
        verifier = TOOL_LABELS.get(tool, (tool,))[0]
        direction = f"Requested independent verifier choices (not verified): {requested}. Carry these choices into the fresh verifier assignment. "
    else:
        direction = ""
    direction += (f"The user selected {verifier} as the independent verifier. Commission a fresh {verifier} "
                  "session that did not implement this work. If this chat cannot launch that session, explain "
                  "how the user can start it with this complete request. If the verifier is unavailable or "
                  "cannot be separated from the implementation agent, report that and ask before substituting.")
    if project is not None and conversation.retained_pictures_text(project):
        direction += (" The request names where pictures attached to earlier messages are kept; carry that "
                      "retained-pictures note into the verifier's brief so the verifier can open them when wanted.")
    return direction


def result_direction(project):
    saved = project.material("Programming Result")
    if not saved["path"]:
        return ("No Programming Result was found. Continue with the available code and requirements, "
                "and disclose the missing report.")
    return (f"The Programming Result was found at {saved['path']}. Its displayed status is "
            f"{reported_status('programming', saved['text'] or '', saved['path'])['label']}; "
            "read the report and actual candidate directly rather than treating the badge as proof.")


def build_input(step, project, user_text="", verifier=None, extra=()):
    """The step's fixed assignment, with any user brief as preserved context.

    The default instruction carries the stage boundary; the brief rides along
    as context, never replacing the assignment, so it cannot widen a step."""
    parts = []
    text = user_text or ""
    if step in DEFAULT_INPUTS:
        parts.append(DEFAULT_INPUTS[step])
    if text.strip():
        parts.append("The user's brief for this work, preserved as context for the intended outcome:\n\n" + text)
    if step == "verification":
        parts.append(verifier_direction(verifier or "", project))
        parts.append(result_direction(project))
        parts.append("Record the verifier's actual tool and model/provider when reported; a different "
                     "harness name alone does not prove a different AI provider. Honor any cross-vendor "
                     "requirement in the accepted project materials, or ask if it cannot be confirmed.")
    parts.extend(part for part in extra if part)
    return "\n\n".join(parts)


def step_request(project, step, user_text, destination, material=(), verifier=None, extra=(), supplied_documents=None,
                 model="", effort="", portable=False):
    """One complete step request, shared by the manual buttons and the run.

    Returns the full prepared packet text. Ordinary requests are saved as
    `Handoff.md`; implementation requests through the existing
    `implement-plan` purpose.
    """
    stage = STEP_STAGE[step]
    return prepare_request(project, stage, build_input(step, project, user_text, verifier, extra),
                           destination, list(material or []), supplied_documents=supplied_documents,
                           model=model, effort=effort, portable=portable)


# --- Resolving each assignment's tool and model -------------------------------

def resolve_assignment(role, config, entry, step3_tool, defaults):
    """Run override, saved default, then the selected harness's own defaults."""
    override = (config or {}).get("roles", {}).get(role)
    if isinstance(override, dict):
        if override.get("tool") or role in OPTIONAL_ROLES:
            return override.get("tool", ""), override.get("model", ""), override.get("effort", ""), "run override"
        if role in {"review", "correction"}:
            return resolve_assignment("implementation", config, entry, step3_tool, defaults)
        return step3_tool or "", "", "", "run override"
    default = (defaults or {}).get(role) or {}
    if default.get("tool") or role in OPTIONAL_ROLES:
        return default.get("tool", ""), default.get("model", ""), default.get("effort", ""), "saved default"
    if role in {"review", "correction"}:
        return resolve_assignment("implementation", config, entry, step3_tool, defaults)
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
    """The report's opening YAML status value — PASSED, NOT PASSED, INCOMPLETE
    or user closure — or '' when missing or unreadable. The raw value routes
    the run; REVIEW INCOMPLETE is a screen label only."""
    label = reported_status("verification", text or "", "")["label"]
    return label if label in VALUES["verification"] else ""


# --- The retained run record ---------------------------------------------------

PURPOSE_RUN = "run"
RUN_START = "run-start"
RUN_ANSWER = "run-answer"
RUN_OUTCOME = "run-outcome"


def run_note_body(kind, run, fields):
    listed = [f"Note: {kind}", f"Purpose: {PURPOSE_RUN}", f"Run: {run}"]
    listed += [f"{key}: {value}" for key, value in fields.items()]
    return "".join(f"Vibe-{field}\n" for field in listed) + "\n"


def _record_run_note(project, folder, kind, run, fields, body=None):
    session = folder / "session"
    conversation.open_session(project, session, "codex",
                              f"Vibe run note {kind} — run {run}\nProject: {project.root}\n", mode="review")
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
        self.findings_settled = 0
        self.attempt_note = ""
        self.verdicts = []
        self.stop_requested = False
        self.resume_answer = ""
        # A paused-question answer can carry pictures (with notes) and files,
        # held in the wire shape start_turn accepts until its step dispatches.
        self.resume_images = []
        self.resume_files = []
        self.handle = None
        self.action_step = ""
        self.action_elapsed = 0
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
        # The brief's pictures ride in the wire shape start_turn accepts, so
        # the run-start note retains them once and the first dispatched step
        # re-supplies them unchanged.
        prepared = conversation.prepare_images(self.brief_images)
        folder = conversation.reserve_turn_folder(self.project)
        self.run = folder.name
        conversation.save_attachments(folder, prepared)
        fields = {"Brief": self.brief or "(no text)",
                  "Brief-Files-JSON": json.dumps(self.brief_files, ensure_ascii=True),
                  "Brief-Images": "; ".join(name for name, _data, _notes in prepared),
                  "Entry": self.entry,
                  "Config-JSON": json.dumps(self.config, ensure_ascii=True)}
        _record_run_note(self.project, folder, RUN_START, self.run, fields)

    def request_stop(self):
        self.stop_requested = True
        with self.lock:
            handle = self.handle
        if handle is not None:
            handle.cancel()

    def receive_answer(self, text, images=(), files=()):
        """One answered pause: the count resets and the same step resumes.

        Answer pictures and files ride the resumed step, with their originals
        retained in the run record before the pause clears, so nothing can
        lose an answer the page already cleared."""
        prepared = conversation.prepare_images(list(images))  # Validates before the pause clears.
        if (not isinstance(files, (list, tuple)) or len(files) > 10
                or any(not isinstance(path, str) or not path for path in files)):
            raise ProjectError("Choose at most 10 Markdown, text or HTML files for this answer.")
        # The retained answer record is written before the in-memory answer
        # exists, so a reader can also read the originals.
        answer = (text or "").strip()
        folder = conversation.reserve_turn_folder(self.project)
        conversation.save_attachments(folder, prepared)
        _record_run_note(self.project, folder, RUN_ANSWER, self.run,
                         {"Answer-Images": "; ".join(name for name, _data, _notes in prepared),
                          "Answer-Files-JSON": json.dumps(list(files), ensure_ascii=True)},
                         ("\n# The user's answer to this run's paused questions\n\n" + quoted(answer)) if answer else None)
        with self.lock:
            self.resume_answer = answer
            self.resume_images = list(images)
            self.resume_files = list(files)
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
            if self.state == "paused-failure" and not self.stop_requested and not (self.handle and self.handle.dispatched):
                self.state = "running"
                self.reason = ""
                return True
        return False

    def _brief_pending(self):
        """True while the entry step's brief has not reached its AI yet."""
        return self.step == self.entry and not self.brief_used

    def pending_brief(self):
        """The brief a paused entry step still owes its AI: consumed only by
        the first attempt that actually dispatches."""
        return self.brief if self._brief_pending() else ""

    def pending_pictures(self):
        """The brief pictures a paused entry step still owes its AI; a copy
        names them as not included, originals retained in the run record."""
        return [item.get("name", "") for item in self.brief_images] if self._brief_pending() else []

    def pending_files(self):
        """Selected brief files still owed to the entry step's first dispatch."""
        return list(self.brief_files) if self._brief_pending() else []

    def pending_answer(self):
        """The answer a paused step still owes its AI: (text, picture names,
        files). Consumed by the first dispatched attempt that carries it; a
        newer answer arrived meanwhile stays."""
        with self.lock:
            return (self.resume_answer,
                    [item.get("name", "") for item in self.resume_images],
                    list(self.resume_files))

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
        if self.stop_requested:
            return False
        with self.lock:
            if self.action_step != self.step:
                self.action_step, self.action_elapsed = self.step, 0
            elif self.handle is not None:
                self.action_elapsed += self.handle.snapshot()["elapsed_seconds"]
            # Admission and route checks belong to this attempt. A prior
            # dispatched turn must not make an unsent repeat look dispatched.
            self.handle = None
            self.reason = ""
        tool, model, effort, origin = self._assignment()
        if tool not in CONVERSATION_PEERS:
            self._pause_failure(f"{ROLE_NAMES[STEP_ROLE[self.step]]} is assigned to {TOOL_LABELS.get(tool, (tool,))[0]}, "
                                "which cannot exchange turns in-app, so an unattended run cannot use it. "
                                "Choose a supported tool in Configure Path; nothing was substituted.")
            return False
        # Dispatch-time revalidation against the actual current components:
        # every role needs the Bridge work route, Build-family steps also the
        # applicable Loop adapter. The reason rides the pause; nothing is
        # substituted.
        try:
            action = f"the {ROLE_NAMES[STEP_ROLE[self.step]]} step"
            conversation.require_work_route(tool, action)
            if self.step in {"build", "correction"}:
                conversation.require_build_route(tool, action)
        except ProjectError as error:
            self._pause_failure(f"{error} Fix it and resume, or stop the run. "
                                "Copy request beside Waiting can deliver this step manually.")
            return False
        extra = []
        corrections = []
        for folder in conversation.turn_folders(self.project):
            prior = conversation.read_turn(folder)
            if prior["fields"].get("Run") == self.run:
                corrections.extend(item["text"] for item in prior["inputs"] if item.get("status") == "accepted")
        if corrections:
            extra.append("## Current user instructions received during this run\n\n" + "\n\n".join(corrections))
        verifier = None
        if self.step in {"build", "correction"}:
            reviewer, r_model, r_effort, _origin = self._assignment_for("review")
            review_choice = self.config.get("roles", {}).get("review", self.defaults.get("review", {}))
            if not review_choice.get("tool"):
                reviewer, r_model, r_effort = tool, model, effort
            extra.append(implementation_direction(tool, model, effort, reviewer, r_model, r_effort))
        if self.step == "verification":
            verifier = {"tool": tool, "model": model, "effort": effort}
        if self.attempt_note:
            extra.append("## Changed approach required\n\n" + self.attempt_note)
        if self.config.get("best_guess"):
            extra.append("When a decision or fact you need is missing, make a reasonable best guess, "
                         "record it explicitly as an assumption in your saved document, and continue. "
                         "Do not ask the user.")
        user_text = self.pending_brief()
        answer = ""
        answer_images = []
        answer_files = []
        with self.lock:
            answer = self.resume_answer
            answer_images, answer_files = self.resume_images, self.resume_files
        if answer:
            extra.append("## The user's answer to your paused questions\n\n" + answer)
        extra.append(f"This step runs on {model_label(tool, model, effort)} ({origin} for this run).")
        text = build_input(self.step, self.project, user_text, verifier, extra)
        # The brief's pictures ride the first dispatch; an answer's pictures
        # and files ride the resumed step it answered.
        images = (self.brief_images if self._brief_pending() else []) + list(answer_images)
        files = self.pending_files() + list(answer_files)
        self.step_requested = model_label(tool, model, effort)
        try:
            # Stop and dispatch share the lock: a stop already requested wins.
            with self.lock:
                if self.stop_requested:
                    return False
                supplied_documents = self.project.approve_transition(self.step)
                self.handle = conversation.start_turn(
                    self.registry, self.project, tool, STEP_STAGE[self.step], text, images, files,
                    run_fields={"Run": self.run, "Run-Step": self.step}, model=model, effort=effort,
                supplied_documents=supplied_documents, cancel_requested=lambda: self.stop_requested,
                activity="Reviewing" if self.step == "verification" else
                         "Coding" if self.step == "build" else "Correcting" if self.step == "correction" else
                         "Creating" if not_started(self.project.material("Specification" if self.step == "specification" else "Plan")["text"] or "") else "Updating")
        except (ProjectError, OSError) as error:
            self._pause_failure(f"The step could not start: {error} Fix it and resume, or stop the run. "
                                "Copy request beside Waiting can deliver this step manually.")
            return False
        self.handle.done.wait()
        model_reported, _provider = self.handle.observed_identity()
        with self.lock:
            # Dispatch alone does not prove a process started; unsent input
            # stays available to Continue and manual copy.
            if self.handle.dispatched:
                self.brief_used = True
                if self.resume_answer == answer:
                    # A newer answer that arrived meanwhile stays.
                    self.resume_answer = ""
                    self.resume_images = []
                    self.resume_files = []
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
        # Questions pause the run; in best-guess mode the repeat counts as an
        # attempt without progress.
        if questions:
            if self.config.get("best_guess"):
                return self._best_guess_repeat("\n".join(questions))
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
                saved = self.project.material("Programming Result")
                if reported_status("programming", saved["text"] or "", "")["label"] == "CLOSED BY USER — UNRESOLVED FINDINGS":
                    self._end("unfinished",
                              "The Programming Result records user closure with unresolved findings. The run "
                              "ends unfinished; nothing is claimed to have passed.")
                    return False
                if step == "build":
                    self.observation = "Programming Result saved."
                    self._advance()
                    return True
                return self._decide_correction_result()
            self._no_result("the step did not save the Programming Result during this step")
            return True
        if step == "verification":
            return self._decide_verification(handle, artifact)
        self._no_result("the step produced nothing the run can read")
        return True

    def _decide_correction_result(self):
        """A correction settles through its saved Programming Result.

        Settlement requires a settled YAML disposition, at least one fix or
        reasoned rejection, and a severe (S) finding settles only through its
        own recorded fix. Quality never holds a run back: a settled correction
        whose status is not PASSED finishes and says so. The route never
        selects verification again after correction; the only recoveries are
        a genuinely unsettled result and owner decisions."""
        saved = self.project.material("Programming Result")
        disposition = review_disposition(saved["text"] or "")
        status = reported_status("programming", saved["text"] or "", "")["label"]
        if disposition == "SETTLED":
            entries = correction_dispositions(saved["text"] or "")
            pending = self.project.material("Verification Report")
            pending_text = pending["text"] or ""
            severe_pending = review_disposition(pending_text) == "SEVERE"
            if not entries:
                self._correction_not_settled(
                    "its Programming Result declared SETTLED but recorded no fix or "
                    "reasoned rejection of any finding")
                return True
            # A severe (S) finding settles only through its own recorded fix;
            # every other decision is recorded, not mechanically enforced.
            supplied = verification_finding_labels(pending_text)
            recorded = {}
            for label, decision, _reason in entries:
                recorded.setdefault(label, decision)
            unfixed_severe = [label for label in supplied
                              if label.startswith("S") and recorded.get(label) != "FIXED"]
            if unfixed_severe:
                self._correction_not_settled(
                    f"the severe finding(s) {', '.join(unfixed_severe)} settle only "
                    "through their own recorded fix with evidence — a rejection or "
                    "an unrelated fix cannot settle them")
                return True
            if severe_pending and not any(item[1] == "FIXED" for item in entries):
                self._correction_not_settled(
                    "the Verification Report recorded a severe finding, which settles "
                    "only through a recorded fix with evidence — a rejection alone "
                    "cannot settle it")
                return True
            self.observation = "Programming Result: settled correction."
            if status != "PASSED":
                self._end("unfinished",
                          f"Correction settled every finding with recorded reasons and the run is finished, but "
                          f"the Programming Result's own status reads {status}, not PASSED. Nothing is claimed "
                          "to have passed; read the saved report before relying on this work.")
                return False
            self._end("complete",
                      "Correction settled every finding with recorded reasons — completed after "
                      "correction, without another verification pass.")
            return False
        if disposition == "SEVERE":
            self._pause_for_owner(
                "The correction's Programming Result records an unresolved severe finding. A severe "
                "finding settles only through a recorded fix with evidence that its harmful path was "
                "removed; a rejection does not stand. Answer to guide the correction, or stop the run.")
            return False
        if disposition == "ASK USER":
            if self.config.get("best_guess"):
                return self._best_guess_repeat("The saved Programming Result left a decision for the user (ASK USER).")
            self._pause_for_owner(
                "The correction's Programming Result records a decision only you can make (ASK USER). "
                "Answer it to continue the correction, or stop the run.")
            return False
        self._correction_not_settled(
            "its Programming Result did not carry a settled `disposition: SETTLED` in its opening "
            "YAML, recording every finding fixed or rejected with reasons"
            if not disposition else
            f"its Programming Result declared `{disposition}`, so the correction is not settled")
        return True

    def _correction_not_settled(self, reason):
        # Corrections continue while they make progress: another of the
        # report's findings settled restarts the count of attempts.
        report = self.project.material("Verification Report")["text"] or ""
        result = self.project.material("Programming Result")["text"] or ""
        settled = len(set(verification_finding_labels(report)) & {entry[0] for entry in correction_dispositions(result)})
        if settled > self.findings_settled:
            self.findings_settled, self.no_progress = settled, 0
        self.no_progress += 1
        self.attempt_note = (f"The previous correction did not settle its findings: {reason}. "
                             "Actually resolve every recorded finding — fix it the smallest way or "
                             "reject it with a concrete reason — then save the one current Programming "
                             "Result with that disposition of every finding and opening YAML "
                             "`disposition: SETTLED`. A saved success word alone is not a settled "
                             "correction.")
        self.observation = "Correction not settled."
        if self.no_progress >= NO_PROGRESS_LIMIT:
            self._end_unfinished_no_progress(reason)

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
                                 "Verification Report in this step, with a readable verdict and disposition.")
            self.observation = "Verification Report: not a result of this run."
            if self.no_progress >= NO_PROGRESS_LIMIT:
                self._end_unfinished_no_progress(reason)
            return True
        verdict = verification_verdict(report["text"])
        disposition = review_disposition(report["text"])
        # User closure and a severe finding stop the run whatever else the
        # report's fields say: neither is retried away.
        stopping = verdict == "CLOSED BY USER — UNRESOLVED FINDINGS" or disposition == "SEVERE"
        if not stopping and (not verdict or not disposition):
            missing = ("no `status:` value in its opening YAML" if not verdict else
                       "no valid `disposition:` value in its opening YAML — missing, duplicated or "
                       "off-list values read as incomplete")
            self.no_progress += 1
            self.attempt_note = (f"The previous verification saved a report with {missing}. "
                                 "Investigate the cause and change the approach, then save one current "
                                 "Verification Report whose opening YAML `status:` states PASSED or "
                                 "NOT PASSED and whose `disposition:` states one of SETTLED, "
                                 "CORRECTION, SEVERE, INCOMPLETE or ASK USER.")
            self.observation = f"Verification Report: {missing}."
            if self.no_progress >= NO_PROGRESS_LIMIT:
                self._end_unfinished_no_progress(f"the saved Verification Report has {missing}")
            return True
        contradictory = not stopping and (
            (verdict == "PASSED" and disposition != "SETTLED")
            or (verdict == "NOT PASSED" and disposition == "SETTLED")
            or (verdict == "INCOMPLETE" and disposition in {"SETTLED", "CORRECTION"})
        )
        if contradictory:
            self.no_progress += 1
            self.attempt_note = (f"The previous verification's `status: {verdict}` contradicts its "
                                 f"`disposition: {disposition}`. Resolve the contradiction "
                                 "and save one current Verification Report whose two YAML values "
                                 "agree.")
            self.observation = "Verification Report: contradictory verdict and disposition."
            if self.no_progress >= NO_PROGRESS_LIMIT:
                self._end_unfinished_no_progress("the saved Verification Report contradicts itself")
            return True
        with self.lock:
            self.verdicts.append(verdict or "VERDICT MISSING")
        if verdict == "CLOSED BY USER — UNRESOLVED FINDINGS":
            self._end("unfinished",
                      "The Verification Report records user closure with unresolved findings. The run "
                      "ends unfinished; nothing is claimed to have passed.")
            return False
        if disposition == "SEVERE":
            # When the run resumes, the answer guides the correction that must
            # fix the severe finding with evidence.
            self.step = "correction"
            self._pause_for_owner(
                "The Verification Report records an unresolved severe finding. A severe finding settles "
                "only through a recorded fix with evidence that its harmful path was removed; a rejection "
                "does not stand. Answer to guide the correction, or stop the run — the run cannot "
                "complete while the severe finding stands.")
            return False
        if disposition == "ASK USER":
            # A missing authority or unresolved product choice outranks ordinary
            # incompleteness, unless this run chose best guesses over pauses.
            if self.config.get("best_guess"):
                return self._best_guess_repeat("The saved Verification Report left a decision for the user (ASK USER).")
            self._pause_for_owner(
                "The Verification Report's disposition is ASK USER: a missing authority or an unresolved "
                "product choice needs your decision. Answer it and the verification is retried with your "
                "decision, or stop the run.")
            return False
        if verdict == "INCOMPLETE" or disposition == "INCOMPLETE":
            self.no_progress += 1
            self.attempt_note = ("The previous verification did not finish. Investigate the cause and "
                                 "change the approach, then complete or rerun the review so one current "
                                 "report states a full verdict and disposition.")
            self.observation = "Verification Report: INCOMPLETE."
            if self.no_progress >= NO_PROGRESS_LIMIT:
                self._end_unfinished_no_progress("verification stayed INCOMPLETE")
            return True
        if disposition == "SETTLED":
            self.observation = "Verification Report: SETTLED."
            self._end("complete", "Verification settled with no unresolved finding; the run is complete.")
            return False
        self.observation = "Verification Report: findings require builder decisions. Correction follows."
        self.step = "correction"
        return True

    def _best_guess_repeat(self, asked):
        self.no_progress += 1
        self.attempt_note = ("The previous attempt asked the user instead of continuing. "
                             "It said:\n\n" + quoted(asked) +
                             "\n\nMake and record a best guess for each decision as an assumption in your "
                             "saved document, and continue. A best guess never authorizes a destructive or "
                             "external action.")
        self.observation = "Step asked questions; a best-guess repeat was sent."
        if self.no_progress >= NO_PROGRESS_LIMIT:
            self._end_unfinished_no_progress("the step kept asking instead of making best guesses")
        return True

    def _pause_for_owner(self, question):
        with self.lock:
            self.state = "paused-question"
            self.questions = [question]
            self.observation = "Paused for your decision."
        self._observe(f"Paused: {question}")

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
            self.reason = (reason + " " + (
                "Inspect the saved files and retained response. Stop this run, then use the conversation to request only the remaining work; the original step will not repeat."
                if self.handle and self.handle.dispatched else
                "Resolve this sign-in, permission or service condition, then Continue to start the step. Nothing was dispatched."))
            self.observation = "Waiting for recovery."
        self._observe(f"Paused: {reason}")

    def _end_unfinished_no_progress(self, what):
        self._end("unfinished",
                  f"The run ended unfinished after {NO_PROGRESS_LIMIT} attempts without progress: {what}. "
                  "The best available artifact is the work already saved in the project. Nothing is "
                  "claimed to have passed; the real check status is what the saved reports say.")

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
            elapsed = self.action_elapsed
            state, step, action_step = self.state, self.step, self.action_step
            config = dict(self.config)
            effective_roles = {role: dict(zip(("tool", "model", "effort"), self._assignment_for(role)[:3]))
                               for role in ROLE_NAMES}
        operation = handle.snapshot() if handle is not None and action_step == step else None
        live = operation and operation.get("state") in {"starting", "running"}
        return {"run": self.run, "state": state, "step": step, "entry": self.entry,
                "reason": self.reason, "questions": list(self.questions),
                "observation": self.observation, "no_progress": self.no_progress,
                "verdicts": list(self.verdicts),
                "model": self.step_requested, "reported_model": self.reported_model,
                "elapsed_seconds": round(elapsed + (operation.get("elapsed_seconds", 0) if operation else 0), 1),
                "activity": operation.get("activity", "") if operation else "",
                "operation": operation, "stopped": self.stop_requested,
                "last_contact_seconds": operation.get("last_contact_seconds") if live else None,
                "config": config, "effective_roles": effective_roles,
                "role_choices": {**self.defaults, **config.get("roles", {})}}


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
