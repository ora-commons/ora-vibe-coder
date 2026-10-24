"""Run to Completion under a fake Bridge: the fixed route, read from what was saved.

Each fake `run` consumes one directive from a scenario directory — the reply
text, the files it writes, or a failure — so every step's outcome is scripted
while the driver itself decides only from the saved records, exactly as it does
live.
"""

import base64
import json
import os
from pathlib import Path
import tempfile
import time
from unittest import mock
import unittest

from ora_vibe_coder import conversation, run as run_module
from ora_vibe_coder.launcher import Settings
from ora_vibe_coder.project import ProjectStore, ProjectError

TEST_ROOT = Path("/private/tmp") if Path("/private/tmp").is_dir() else Path(tempfile.gettempdir())

FAKE_BRIDGE = '''
"""A fake Agent Bridge whose runs consume scripted step directives."""
import argparse, json, os, pathlib, sys, time

def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\\n")
    sys.stdout.flush()

def next_sequence(session):
    messages = session / "messages"
    if not messages.is_dir():
        return 1
    numbers = [int(p.name[:4]) for p in messages.iterdir()
               if p.name[:4].isdigit() and p.suffix == ".md"]
    return max(numbers, default=0) + 1

def main():
    parser = argparse.ArgumentParser(prog="bridge", allow_abbrev=False)
    sub = parser.add_subparsers(dest="command")
    record = sub.add_parser("record")
    record.add_argument("--session", required=True)
    record.add_argument("--kind", required=True)
    record.add_argument("--initiator")
    record.add_argument("--peer")
    record.add_argument("--project")
    record.add_argument("--mode")
    record.add_argument("--access-path", action="append")
    runp = sub.add_parser("run")
    runp.add_argument("--session", required=True)
    runp.add_argument("--timeout", type=float)
    runp.add_argument("--no-timeout", action="store_true")
    runp.add_argument("--max-steps", type=int)
    runp.add_argument("--require-model")
    runp.add_argument("--model")
    runp.add_argument("--effort")
    runp.add_argument("--events-jsonl", action="store_true")
    runp.add_argument("--attachment", action="append")
    runp.add_argument("--note-ref")
    runp.add_argument("--purpose")
    runp.add_argument("--work-permission")
    check = sub.add_parser("check")
    check.add_argument("--peer", required=True)
    check.add_argument("--mode")
    check.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.command == "check":
        print(json.dumps({"peer": args.peer, "mode": args.mode or "review", "ready": True,
                          "warnings": [], "work": "supported",
                          "model_switch": "-m" if args.peer == "codex" else None}))
        return 0
    session = pathlib.Path(args.session)
    body = sys.stdin.read()
    if args.command == "record":
        if os.environ.get("VIBE_FAKE_FAIL_RUN_NOTES") and "Note: run-start" in body:
            sys.stderr.write("NOTE_WRITE_FAILED\\n")
            return 1
        if args.kind == "session-create":
            (session / "messages").mkdir(parents=True, exist_ok=True)
            (session / "SESSION.md").write_text(
                "# Session\\nBridge-Format: 3\\n\\n## Body\\n\\n" + body, encoding="utf-8")
            print(session / "SESSION.md")
            return 0
        if args.kind == "note":
            sequence = next_sequence(session)
            path = session / "messages" / ("%04d-initiator-record.md" % sequence)
            path.write_text("# Message %04d\\nRecord: note\\nFrom: vibe-coder\\n\\n## Body\\n\\n" % sequence + body,
                            encoding="utf-8")
            print(path)
            return 0
        sys.stderr.write("UNKNOWN_RECORD_KIND\\n")
        return 1
    if not (session / "SESSION.md").is_file():
        sys.stderr.write("SESSION_NOT_FOUND\\n")
        return 1
    log = os.environ.get("VIBE_FAKE_ARGV_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as stream:
            stream.write(json.dumps({"model": args.model, "effort": args.effort,
                                     "work_permission": args.work_permission,
                                     "purpose": args.purpose}) + "\\n")
    scenario = pathlib.Path(os.environ["VIBE_FAKE_SCENARIO_DIR"])
    counter = scenario / "directive.count"
    index = 0
    if counter.is_file():
        index = int(counter.read_text().strip())
    counter.write_text(str(index + 1))
    directive = {}
    source = scenario / f"{index}.json"
    if source.is_file():
        directive = json.loads(source.read_text(encoding="utf-8"))
    sequence = next_sequence(session)
    request = session / "messages" / ("%04d-initiator-to-peer.md" % sequence)
    headers = ["# Message %04d" % sequence, "From: vibe-coder", "To: peer",
               "Note-Ref: " + str(args.note_ref), "Purpose: " + str(args.purpose)]
    for item in args.attachment or []:
        headers.append("Attachment: " + item)
    request.write_text("\\n".join(headers) + "\\n\\n## Body\\n\\n" + body, encoding="utf-8")
    for name, text in (directive.get("writes") or {}).items():
        pathlib.Path(name).write_text(text, encoding="utf-8")
    if directive.get("delay"):
        time.sleep(float(directive["delay"]))
    if directive.get("fail"):
        if args.events_jsonl:
            emit({"event": "finished", "phase": "run", "outcome": "failure",
                  "request_path": str(request),
                  "reason": directive.get("reason", "the fake transport failed"),
                  "next_action": "fix the fake transport"})
        return 1
    reply = directive.get("reply", "Done.\\n")
    answer = next_sequence(session)
    response = session / "messages" / ("%04d-peer-to-initiator.md" % answer)
    response.write_text("# Message %04d\\nFrom: peer\\nTo: vibe-coder\\nAnswers: %04d\\n\\n## Body\\n\\n"
                        % (answer, sequence) + reply, encoding="utf-8")
    if args.events_jsonl:
        finished = {"event": "finished", "phase": "run", "outcome": "success",
                    "request_path": str(request), "response_path": str(response), "warnings": []}
        if directive.get("model"):
            finished["model"] = directive["model"]
        emit(finished)
    else:
        print(response)
    return 0


raise SystemExit(main())
'''


def reply_with_questions(*questions):
    return ("Working on it.\n\n## Questions for you\n\n"
            + "\n".join(f"- {question}" for question in questions) + "\n")


def report(verdict, progress=None):
    text = f"# Verification Report\n\nVerdict: {verdict}\n\nWhat was checked and found.\n"
    if progress is not None:
        text += f"\n## Progress\n\n{progress}\n"
    return text


class RunCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=str(TEST_ROOT))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "projects"
        self.home.mkdir()
        self.store = ProjectStore(self.home)
        self.bridge = self.root / "bridge-home"
        (self.bridge / "ora_agent_bridge").mkdir(parents=True)
        (self.bridge / "ora_agent_bridge" / "__init__.py").write_text("", encoding="utf-8")
        (self.bridge / "ora_agent_bridge" / "__main__.py").write_text(FAKE_BRIDGE, encoding="utf-8")
        self.scenario = self.root / "scenario"
        self.scenario.mkdir()
        self.argv_log = self.root / "argv.jsonl"
        self.environ = {"VIBE_FAKE_SCENARIO_DIR": str(self.scenario), "VIBE_FAKE_ARGV_LOG": str(self.argv_log)}
        self._env_patch = mock.patch.dict(os.environ, self.environ)
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)
        self._bridge_patch = mock.patch.object(conversation, "BRIDGE_HOME", self.bridge)
        self._bridge_patch.start()
        self.addCleanup(self._bridge_patch.stop)
        self.registry = conversation.TurnRegistry()
        self.runs = run_module.RunRegistry()
        # A paused run's driver thread outlives its assertion; Stop ends it.
        self.addCleanup(self.runs.drain)

    def project(self, name="One"):
        key = self.store.create(name, name, "Description", "Goals")
        return self.store.projects[key]

    def directive(self, index, **directive):
        (self.scenario / f"{index}.json").write_text(json.dumps(directive), encoding="utf-8")

    def start(self, project, entry="specification", brief="Build the small tool.", config=None,
              defaults=None, tool="codex"):
        return self.runs.start(self.registry, project, entry, brief,
                               config or {"roles": {}, "best_guess": False, "hide_advisory": False},
                               defaults or {}, tool, [], [])

    def settle(self, driver, predicate, timeout=30):
        """Wait until the driver's status satisfies the predicate."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = driver.status()
            if predicate(status):
                return status
            time.sleep(0.05)
        self.fail(f"run never reached the expected state: {driver.status()}")

    def wait_for(self, predicate, timeout=20, message="condition never met"):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.05)
        self.fail(message)

    def build_step_ok(self, root, index=0, note="Delivered for the run."):
        return index, {str(root / "One — Programming Result.md"):
                       f"# Programming Result\n\nStatus: COMPLETE\n\n{note}\n"}

    def step_requests(self, project, step=None):
        """The saved request bodies of the run's step turns, oldest first."""
        requests = []
        for folder in conversation.turn_folders(project):
            turn = conversation.read_turn(folder)
            if turn["purpose"] == conversation.PURPOSE_WORK and turn["fields"].get("Run"):
                if step and turn["fields"].get("Run-Step") != step:
                    continue
                messages = sorted((folder / "session" / "messages").glob("*-initiator-to-peer.md"))
                if messages:
                    requests.append(conversation.parse_message(messages[-1])["body"])
        return requests

    def own_message(self, request):
        """The request's own user-message text, before the work-turn section.

        Later steps legitimately quote earlier exchanges — brief included — as
        project history; only the request's own instruction section says
        whether a step was handed the brief itself.
        """
        return request.split("\n\n# Work-turn instructions", 1)[0]

    # -- the scenarios -------------------------------------------------------

    def test_run_from_specification_consumes_the_brief_once_and_completes(self):
        self.addCleanup(self.registry.drain)
        project = self.project()
        root = project.root
        # Run to Completion takes priority over an optional comparison that
        # was already using the work slot, without pausing for its answer.
        self.directive(0, reply="MATERIAL\nRequirements changed.\n", delay=30)
        comparison = conversation.start_aux(self.registry, project, "codex", conversation.PURPOSE_MATERIALITY,
                                            "specification", "Compare the two retained versions.", {"Key": "old:new"})
        self.wait_for(lambda: comparison.state == "running" and (self.scenario / "directive.count").is_file()
                      and (self.scenario / "directive.count").read_text() == "1")
        self.directive(1, reply="Specification drafted.\n", writes={
            str(root / "Specification.md"): "# One — Specification\n\n## Description\n\nA real product brief.\n"})
        self.directive(2, reply="Planned.\n", writes={
            str(root / "Plan.md"): "# One — Plan\n\n## Approach\n\nSteps are laid out.\n"})
        self.directive(3, reply="Built.\n", writes={
            str(root / "One — Programming Result.md"): "# Programming Result\n\nStatus: COMPLETE\n\nDelivered.\n"})
        self.directive(4, reply="Verified.\n", writes={
            str(root / "One — Verification Report.md"): report("PASSED")})
        driver = self.start(project, "specification", "Build the small tool from this brief.")
        final = self.settle(driver, lambda status: status["state"] == "complete")
        self.assertEqual(comparison.state, "interrupted")
        self.assertFalse(comparison.worker.is_alive())
        self.assertFalse(comparison.live_children())
        self.assertNotIn("specification:old:new", conversation.read_aux_answers(project))
        self.assertEqual(final["verdicts"], ["PASSED"])
        requests = self.step_requests(project)
        self.assertEqual(len(requests), 4)
        # The brief is carried by the entry step once — beside its fixed
        # assignment, never in place of it — and no later step's own
        # instruction repeats it.
        self.assertIn("Build the small tool from this brief.", self.own_message(requests[0]))
        for later in requests[1:]:
            self.assertNotIn("Build the small tool from this brief.", self.own_message(later))
        runs = run_module.read_runs(project)
        self.assertEqual(runs[-1]["state"], "complete")
        self.assertTrue(all(step["state"] == "complete" for step in runs[-1]["steps"]))

    def test_a_brief_carrying_entry_step_keeps_its_fixed_stage_assignment(self):
        project = self.project()
        root = project.root
        self.directive(0, reply="Specification drafted.\n", writes={
            str(root / "Specification.md"): "# One — Specification\n\n## Description\n\nA real product brief.\n"})
        self.directive(1, reply="Planned.\n", writes={
            str(root / "Plan.md"): "# One — Plan\n\n## Approach\n\nSteps are laid out.\n"})
        self.directive(2, reply="Built.\n", writes={
            str(root / "One — Programming Result.md"): "# Programming Result\n\nStatus: COMPLETE\n\nDelivered.\n"})
        self.directive(3, reply="Verified.\n", writes={
            str(root / "One — Verification Report.md"): report("PASSED")})
        brief = "Build the whole final deliverable, including every part and its checks."
        driver = self.start(project, "specification", brief)
        final = self.settle(driver, lambda status: status["state"] == "complete")
        self.assertEqual(final["verdicts"], ["PASSED"])
        requests = self.step_requests(project)
        self.assertEqual(len(requests), 4)
        # The dispatched entry request retains the fixed Specification
        # assignment — its stage boundary included — and carries the user's
        # brief beside it as preserved context, never replacing the boundary.
        entry_message = self.own_message(requests[0])
        self.assertIn("Work toward a complete, implementation-neutral Specification", entry_message)
        self.assertIn("do not start the Plan or implementation", entry_message)
        self.assertIn(brief, entry_message)
        for later in requests[1:]:
            self.assertNotIn(brief, self.own_message(later))

    def test_a_failed_brief_save_prevents_the_start(self):
        project = self.project()
        with mock.patch.dict(os.environ, {"VIBE_FAKE_FAIL_RUN_NOTES": "1"}):
            with self.assertRaises(ProjectError):
                self.start(project)
        self.assertIsNone(self.runs.find(project))
        self.assertEqual(run_module.read_runs(project), [])
        self.assertFalse(list((project.root / ".vibe").glob("*/session/messages/*")))

    def test_a_start_that_never_dispatched_re_supplies_the_brief_on_resume(self):
        project = self.project()
        root = project.root
        brief = "Build the small tool from this brief."
        # Clicking Run while an ordinary turn is still working: run-start does
        # not check for one, so the entry step's first start is refused by the
        # one-work-turn rule and never dispatches.
        blocker = self.registry.admit(root, "codex", "programming", frozenset({str(root)}))
        self.directive(0, reply="Specification drafted.\n", writes={
            str(root / "Specification.md"): "# One — Specification\n\n## Description\n\nA real product brief.\n"})
        self.directive(1, reply="Planned.\n", writes={
            str(root / "Plan.md"): "# One — Plan\n\n## Approach\n\nSteps are laid out.\n"})
        self.directive(2, reply="Built.\n", writes={
            str(root / "One — Programming Result.md"): "# Programming Result\n\nStatus: COMPLETE\n\nDelivered.\n"})
        self.directive(3, reply="Verified.\n", writes={
            str(root / "One — Verification Report.md"): report("PASSED")})
        driver = self.start(project, "specification", brief)
        paused = self.settle(driver, lambda status: status["state"] == "paused-failure")
        self.assertIn("One work turn per project", paused["reason"])
        # The start never dispatched, so the brief was not consumed: it stays
        # owed to the entry step, not silently dropped by the pause.
        self.assertEqual(driver.pending_brief(), brief)
        blocker.finish("finished")
        self.assertTrue(driver.resume())
        final = self.settle(driver, lambda status: status["state"] == "complete")
        self.assertEqual(final["verdicts"], ["PASSED"])
        requests = self.step_requests(project)
        self.assertEqual(len(requests), 4)
        # The first actually-dispatched attempt carries the brief; no later
        # step repeats it.
        self.assertIn(brief, self.own_message(requests[0]))
        for later in requests[1:]:
            self.assertNotIn(brief, self.own_message(later))
        self.assertEqual(driver.pending_brief(), "")

    def test_copy_request_for_a_paused_entry_step_carries_the_brief(self):
        import http.client
        import threading
        from ora_vibe_coder.server import LocalServer
        settings = Settings(self.root / "settings.json")
        server = LocalServer(self.home, settings=settings)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01})
        thread.start()
        self.addCleanup(lambda: (server.runs.drain(), server.shutdown(), thread.join(),
                                 server.server_close()))

        def post(path, body):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("POST", path, json.dumps(body),
                               headers={"Content-Type": "application/json", "X-Ora-Token": server.token})
            response = connection.getresponse()
            data = json.loads(response.read())
            connection.close()
            return response.status, data

        _status, created = post("/api/create", {"directory": "Two", "name": "Two", "description": "", "goals": ""})
        root = self.home / "Two"
        # An ordinary in-flight turn for the same project: run-start does not
        # check for one, so the run pauses when its entry step cannot start.
        blocker = server.conversation.admit(root, "codex", "programming", frozenset({str(root)}))
        self.addCleanup(blocker.finish, "finished")
        brief_file = self.root / "selected brief.txt"
        brief_text = "Exact selected brief: preserve the blue route.\n"
        brief_file.write_text(brief_text, encoding="utf-8")
        detail_file = self.root / "selected details.md"
        detail_text = "# Selected details\n\n```text\nNested material stays intact.\n```\n"
        detail_file.write_text(detail_text, encoding="utf-8")
        _code, started = post("/api/run-start", {"id": created["id"], "entry": "specification",
                                                 "text": "Build the small tool from this brief.",
                                                 "images": [], "files": [str(brief_file), str(detail_file)], "tool": "codex"})
        self.wait_for(lambda: post("/api/turn-state", {"id": created["id"]})[1]
                      ["run"]["active"]["state"] == "paused-failure",
                      message="the entry step never paused on the refused start")
        # The manual fallback for the paused entry step delivers the brief too,
        # so it never disappears behind a manual delivery — with the fixed
        # stage assignment still governing the step.
        _code, copied = post("/api/run-copy", {"id": created["id"]})
        self.assertIn("Build the small tool from this brief.", copied["text"])
        self.assertNotIn("Requested harness choices", copied["text"])
        self.assertNotIn("Selected receiving harness", copied["text"])
        self.assertIn("do not start the Plan or implementation", copied["text"])
        for selected, original in ((brief_file, brief_text), (detail_file, detail_text)):
            self.assertIn(f"## Selected material: {selected}\n", copied["text"])
            self.assertIn(original, copied["text"])
            self.assertEqual(selected.read_text(encoding="utf-8"), original)
        self.assertTrue(Path(copied["path"]).is_file())
        self.assertEqual(Path(copied["path"]).read_text(encoding="utf-8"), copied["text"])
        blocker.finish("finished")
        self.directive(0, reply=reply_with_questions("Which route should the Specification use?"))
        _code, resumed = post("/api/run-resume", {"id": created["id"]})
        self.wait_for(lambda: post("/api/turn-state", {"id": created["id"]})[1]
                      ["run"]["active"]["state"] == "paused-question",
                      message="the dispatched entry step never paused for its answer")
        _code, later_copy = post("/api/run-copy", {"id": created["id"]})
        for consumed in ("Build the small tool from this brief.", str(brief_file), str(detail_file),
                         "Exact selected brief: preserve the blue route.", "Nested material stays intact."):
            self.assertNotIn(consumed, later_copy["text"])
        _code, stopped = post("/api/run-stop", {"id": created["id"]})
        self.assertEqual(stopped["run"]["last"]["state"], "unfinished")

    def test_a_run_from_the_plan_workspace_enters_at_the_planning_step(self):
        import http.client
        import threading
        from ora_vibe_coder.server import LocalServer
        settings = Settings(self.root / "settings.json")
        server = LocalServer(self.home, settings=settings)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01})
        thread.start()
        self.addCleanup(lambda: (server.runs.drain(), server.shutdown(), thread.join(),
                                 server.server_close()))

        def post(path, body):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("POST", path, json.dumps(body),
                               headers={"Content-Type": "application/json", "X-Ora-Token": server.token})
            response = connection.getresponse()
            data = json.loads(response.read())
            connection.close()
            return response.status, data

        def run_steps(root):
            project = self.store.projects[self.store.open(root)]
            return [turn["fields"].get("Run-Step") for turn in
                    (conversation.read_turn(folder) for folder in conversation.turn_folders(project))
                    if turn["purpose"] == conversation.PURPOSE_WORK and turn["fields"].get("Run")]

        def wait_complete(identifier, workspace):
            self.wait_for(lambda: (post("/api/turn-state", {"id": identifier})[1]
                                   ["run"].get("last") or {}).get("state") == "complete",
                          timeout=60, message=f"the run from the {workspace} workspace never completed")

        # The Plan workspace sends "planning" — the canonical route name every
        # other layer uses — so the real start route accepts it and the run
        # begins at step 2, earlier stages not redone, and proceeds.
        _status, created = post("/api/create", {"directory": "Two", "name": "Two", "description": "", "goals": ""})
        root = self.home / "Two"
        self.directive(0, reply="Planned.\n", writes={
            str(root / "Plan.md"): "# Two — Plan\n\n## Approach\n\nSteps are laid out.\n"})
        self.directive(1, reply="Built.\n", writes={
            str(root / "Two — Programming Result.md"): "# Programming Result\n\nStatus: COMPLETE\n\nDelivered.\n"})
        self.directive(2, reply="Verified.\n", writes={
            str(root / "Two — Verification Report.md"): report("PASSED")})
        code, started = post("/api/run-start", {"id": created["id"], "entry": "planning",
                                                "text": "Build the small tool from this brief.",
                                                "images": [], "files": [], "tool": "codex"})
        self.assertEqual(code, 200)
        self.assertEqual(started["run"]["entry"], "planning")
        wait_complete(created["id"], "Plan")
        self.assertEqual(run_steps(root), ["planning", "build", "verification"])
        requests = self.step_requests(self.store.projects[self.store.open(root)])
        self.assertEqual(len(requests), 3)
        self.assertIn("Build the small tool from this brief.", self.own_message(requests[0]))
        for later in requests[1:]:
            self.assertNotIn("Build the small tool from this brief.", self.own_message(later))

        # The Specification and Build & Verify workspaces keep their own
        # entries: step 1 and step 3, unchanged.
        _status, created_spec = post("/api/create", {"directory": "Three", "name": "Three", "description": "", "goals": ""})
        root_spec = self.home / "Three"
        self.directive(3, reply="Specification drafted.\n", writes={
            str(root_spec / "Specification.md"): "# Three — Specification\n\n## Description\n\nA real product brief.\n"})
        self.directive(4, reply="Planned.\n", writes={
            str(root_spec / "Plan.md"): "# Three — Plan\n\n## Approach\n\nSteps are laid out.\n"})
        self.directive(5, reply="Built.\n", writes={
            str(root_spec / "Three — Programming Result.md"): "# Programming Result\n\nStatus: COMPLETE\n\nDelivered.\n"})
        self.directive(6, reply="Verified.\n", writes={
            str(root_spec / "Three — Verification Report.md"): report("PASSED")})
        code_spec, started_spec = post("/api/run-start", {"id": created_spec["id"], "entry": "specification",
                                                          "text": "Build it from the Specification.",
                                                          "images": [], "files": [], "tool": "codex"})
        self.assertEqual(code_spec, 200)
        self.assertEqual(started_spec["run"]["entry"], "specification")
        wait_complete(created_spec["id"], "Specification")
        self.assertEqual(run_steps(root_spec), ["specification", "planning", "build", "verification"])

        _status, created_build = post("/api/create", {"directory": "Four", "name": "Four", "description": "", "goals": ""})
        root_build = self.home / "Four"
        self.directive(7, reply="Built.\n", writes={
            str(root_build / "Four — Programming Result.md"): "# Programming Result\n\nStatus: COMPLETE\n\nDelivered.\n"})
        self.directive(8, reply="Verified.\n", writes={
            str(root_build / "Four — Verification Report.md"): report("PASSED")})
        code_build, started_build = post("/api/run-start", {"id": created_build["id"], "entry": "build",
                                                            "text": "Build it directly.",
                                                            "images": [], "files": [], "tool": "codex"})
        self.assertEqual(code_build, 200)
        self.assertEqual(started_build["run"]["entry"], "build")
        wait_complete(created_build["id"], "Build & Verify")
        self.assertEqual(run_steps(root_build), ["build", "verification"])

    def test_run_copy_names_the_pending_brief_pictures_as_not_included(self):
        import http.client
        import threading
        from ora_vibe_coder.server import LocalServer
        settings = Settings(self.root / "settings.json")
        server = LocalServer(self.home, settings=settings)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01})
        thread.start()
        self.addCleanup(lambda: (server.runs.drain(), server.shutdown(), thread.join(),
                                 server.server_close()))

        def post(path, body):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("POST", path, json.dumps(body),
                               headers={"Content-Type": "application/json", "X-Ora-Token": server.token})
            response = connection.getresponse()
            data = json.loads(response.read())
            connection.close()
            return response.status, data

        _status, created = post("/api/create", {"directory": "Two", "name": "Two", "description": "", "goals": ""})
        root = self.home / "Two"
        # An in-flight ordinary turn keeps the entry step from dispatching, so
        # the brief — its pictures included — stays pending behind the pause.
        blocker = server.conversation.admit(root, "codex", "programming", frozenset({str(root)}))
        self.addCleanup(blocker.finish, "finished")
        payload = b"tiny png payload for the run brief"
        picture = {"name": "sketch.png", "data": base64.b64encode(payload).decode("ascii")}
        _code, started = post("/api/run-start", {"id": created["id"], "entry": "build",
                                                 "text": "Build the small tool from this brief.",
                                                 "images": [picture], "files": [], "tool": "codex"})
        self.wait_for(lambda: post("/api/turn-state", {"id": created["id"]})[1]
                      ["run"]["active"]["state"] == "paused-failure",
                      message="the entry step never paused on the refused start")
        _code, copied = post("/api/run-copy", {"id": created["id"]})
        # The manual packet carries the brief, and — because a copy cannot
        # carry pictures — names the pending brief picture as not included
        # instead of silently dropping it. The response carries the name, per
        # the one-click Copy response shape, so the banner can say pictures
        # were left out.
        self.assertIn("# User request\n\n", copied["text"])
        self.assertIn("Build the small tool from this brief.", copied["text"])
        self.assertNotIn("Requested harness choices", copied["text"])
        self.assertNotIn("Selected receiving harness", copied["text"])
        self.assertIn("Brief pictures not included: sketch.png.", copied["text"])
        self.assertNotIn(picture["data"], copied["text"])
        self.assertEqual(copied["pictures"], ["sketch.png"])
        saved = Path(copied["path"]).read_text(encoding="utf-8")
        self.assertIn("Brief pictures not included: sketch.png.", saved)
        # Delivery-disclosure only: the picture stays retained in the run record.
        project = self.store.projects[self.store.open(root)]
        kept = sorted(path.name for folder in conversation.turn_folders(project)
                      for path in (folder / "attachments").glob("*"))
        self.assertEqual(kept, ["0001-sketch.png"])
        blocker.finish("finished")
        _code, stopped = post("/api/run-stop", {"id": created["id"]})
        self.assertEqual(stopped["run"]["last"]["state"], "unfinished")

    def test_run_brief_pictures_start_the_run_and_ride_the_first_step_once(self):
        import http.client
        import threading
        from ora_vibe_coder.server import LocalServer
        settings = Settings(self.root / "settings.json")
        server = LocalServer(self.home, settings=settings)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01})
        thread.start()
        self.addCleanup(lambda: (server.runs.drain(), server.shutdown(), thread.join(),
                                 server.server_close()))

        def post(path, body):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("POST", path, json.dumps(body),
                               headers={"Content-Type": "application/json", "X-Ora-Token": server.token})
            response = connection.getresponse()
            data = json.loads(response.read())
            connection.close()
            return response.status, data

        _status, created = post("/api/create", {"directory": "Two", "name": "Two", "description": "", "goals": ""})
        root = self.home / "Two"
        payload = b"tiny png payload for the run brief"
        picture = {"name": "sketch.png", "data": base64.b64encode(payload).decode("ascii")}
        self.directive(0, reply="Built.\n", writes={
            str(root / "Two — Programming Result.md"): "# Programming Result\n\nStatus: COMPLETE\n\nDelivered.\n"})
        self.directive(1, reply="Verified.\n", writes={
            str(root / "Two — Verification Report.md"): report("PASSED")})
        code, started = post("/api/run-start", {"id": created["id"], "entry": "build",
                                                "text": "Build the small tool from this brief.",
                                                "images": [picture], "files": [], "tool": "codex"})
        # Brief pictures pass through in the wire shape every turn accepts, so
        # the start records its brief instead of failing on the attachment.
        self.assertEqual(code, 200)
        self.assertIn("run", started)
        self.wait_for(lambda: (post("/api/turn-state", {"id": created["id"]})[1]
                               ["run"].get("last") or {}).get("state") == "complete",
                      timeout=60, message="the run with brief pictures never completed")
        project = self.store.projects[self.store.open(root)]
        notes = [(folder, fields) for folder in conversation.turn_folders(project)
                 for fields in run_module.run_note_fields(folder)
                 if fields.get("Note") == run_module.RUN_START and not fields.get("Reconfigures")]
        self.assertEqual(len(notes), 1)
        note_folder, fields = notes[0]
        self.assertEqual(fields["Brief-Images"], "sketch.png")
        self.assertEqual((note_folder / "attachments" / "0001-sketch.png").read_bytes(), payload)
        # The pictures ride the first dispatched entry step exactly once: the
        # build turn retains and dispatches them; the verification turn does not.
        step_attachments = {}
        for folder in conversation.turn_folders(project):
            turn = conversation.read_turn(folder)
            if turn["purpose"] == conversation.PURPOSE_WORK and turn["fields"].get("Run"):
                kept = sorted(path.name for path in (folder / "attachments").glob("*"))
                step_attachments[turn["fields"]["Run-Step"]] = kept
        self.assertEqual(step_attachments.get("build"), ["0001-sketch.png"])
        self.assertEqual(step_attachments.get("verification"), [])
        requests = self.step_requests(project)
        self.assertEqual(len(requests), 2)
        self.assertIn("0001-sketch.png", requests[0])
        self.assertNotIn("0001-sketch.png", requests[1])

    def test_deliver_send_with_a_picture_attaches_it_to_the_started_turn(self):
        import http.client
        import threading
        from ora_vibe_coder.server import LocalServer
        settings = Settings(self.root / "settings.json")
        server = LocalServer(self.home, settings=settings)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01})
        thread.start()
        self.addCleanup(lambda: (server.runs.drain(), server.shutdown(), thread.join(),
                                 server.server_close()))

        def post(path, body):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("POST", path, json.dumps(body),
                               headers={"Content-Type": "application/json", "X-Ora-Token": server.token})
            response = connection.getresponse()
            data = json.loads(response.read())
            connection.close()
            return response.status, data

        _status, created = post("/api/create", {"directory": "Two", "name": "Two", "description": "", "goals": ""})
        root = self.home / "Two"
        plan = root / "Plan.md"
        original = "---\nstatus: AWAITING APPROVAL\nreview: NOT PASSED\n---\n# Plan\n\n## Approach\nUse the agreed storage.\n"
        plan.write_text(original)
        preview_data = {"id": created["id"], "stage": "implement-plan", "input": "Implement.", "destination": "ZCode", "context": {"material": []}}
        self.assertEqual(post("/api/preview", preview_data)[0], 200)
        self.assertEqual(plan.read_text(), original)  # Viewing a packet grants no approval.
        stale = {"path": str(plan), "expected": original}
        plan.write_text(original.replace("agreed storage", "revised storage"))
        refused, _notice = post("/api/deliver", {"id": created["id"], "step": "implement-plan", "action": "copy", "tool": "zcode", "text": "Implement.", "upstream": stale})
        self.assertEqual(refused, 409)
        self.assertNotIn("status: APPROVED", plan.read_text())
        plan.write_text(original)
        original_save = server.store.projects[created["id"]].save_packet
        def edit_after_packet(*args, **kwargs):
            result = original_save(*args, **kwargs)
            plan.write_text(original.replace("agreed storage", "unseen later storage"))
            return result
        payload = b"tiny png payload for the delivered send"
        with mock.patch.object(server.store.projects[created["id"]], "save_packet", side_effect=edit_after_packet):
            code, delivered = post("/api/deliver", {"id": created["id"], "step": "implement-plan", "action": "send",
                                                "tool": "zcode", "text": "Implement the Plan.",
                                                "images": [{"name": "wire.png",
                                                            "data": base64.b64encode(payload).decode("ascii")}],
                                                "files": []})
        self.assertEqual(code, 200)
        self.assertIn("turn", delivered)
        self.assertEqual(delivered["images"], ["0001-wire.png"])
        folder = root / ".vibe" / delivered["turn"]
        self.assertEqual((folder / "attachments" / "0001-wire.png").read_bytes(), payload)
        messages = folder / "session" / "messages"
        self.wait_for(lambda: list(messages.glob("*-peer-to-initiator.md")),
                      timeout=60, message="the delivered turn never finished")
        dispatched = sorted(messages.glob("*-initiator-to-peer.md"))[-1].read_text(encoding="utf-8")
        self.assertIn("Attachment: ", dispatched)
        self.assertIn("0001-wire.png", dispatched)
        self.assertIn("Use the agreed storage.", dispatched)
        self.assertNotIn("unseen later storage", dispatched)
        self.assertIn("status: APPROVED", dispatched)
        self.assertIn("review: NOT PASSED", dispatched)
        self.assertIn("Use the agreed storage.", (root / "Two — Implementation Request.md").read_text())
        calls = [json.loads(line) for line in self.argv_log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(calls[-1]["work_permission"], "full-access")

    def test_question_pauses_in_build_and_verification_and_answers_resume_the_same_step(self):
        project = self.project()
        root = project.root
        (root / "Specification.md").write_text("# S\n\n## Description\n\nFilled.\n", encoding="utf-8")
        (root / "Plan.md").write_text("# P\n\n## Approach\n\nFilled.\n", encoding="utf-8")
        self.directive(0, reply=reply_with_questions("Which storage engine should the build use?"))
        paused = self.settle(self.start(project, "build"), lambda status: status["state"] == "paused-question")
        self.assertEqual(paused["step"], "build")
        self.assertIn("storage engine", paused["questions"][0])
        self.directive(1, reply="Built with SQLite.\n", writes={
            str(root / "One — Programming Result.md"): "# Programming Result\n\nStatus: COMPLETE\n\nDelivered.\n"})
        self.directive(2, reply=reply_with_questions("Who signs off the release checklist?"))
        driver = self.runs.find(project)
        driver.receive_answer("Use SQLite everywhere.")
        paused_verification = self.settle(driver, lambda status: status["state"] == "paused-question" and status["step"] == "verification")
        self.assertEqual(paused_verification["step"], "verification")
        self.directive(3, reply="Verified.\n", writes={str(root / "One — Verification Report.md"): report("PASSED")})
        driver.receive_answer("Lawrence signs off.")
        self.settle(driver, lambda status: status["state"] == "complete")
        requests = self.step_requests(project)
        self.assertIn("Use SQLite everywhere.", requests[1])
        self.assertIn("Lawrence signs off.", requests[3])
        # The answer resets the no-progress count and the same step resumed.
        self.assertEqual(driver.status()["no_progress"], 0)

    def test_best_guess_mode_resends_the_step_and_counts_no_progress(self):
        project = self.project()
        root = project.root
        (root / "Specification.md").write_text("# S\n\n## Description\n\nFilled.\n", encoding="utf-8")
        (root / "Plan.md").write_text("# P\n\n## Approach\n\nFilled.\n", encoding="utf-8")
        self.directive(0, reply=reply_with_questions("Which port should the server use?"))
        self.directive(1, reply="Built on port 8080 as an assumption.\n", writes={
            str(root / "One — Programming Result.md"): "# Programming Result\n\nStatus: COMPLETE\n\nAssumption recorded: port 8080.\n"})
        self.directive(2, reply=reply_with_questions("Which verifier may I commission?"))
        self.directive(3, reply="Verified.\n", writes={str(root / "One — Verification Report.md"): report("PASSED")})
        driver = self.start(project, "build", config={"roles": {}, "best_guess": True, "hide_advisory": False})
        # The build step that asked is resent with the best-guess instruction
        # instead of pausing, and the repeat counts as no progress.
        working = self.settle(driver, lambda status: status["state"] == "running" and status["no_progress"] >= 1)
        self.assertGreaterEqual(working["no_progress"], 1)
        self.wait_for(lambda: len(self.step_requests(project, "build")) >= 2,
                      message="the best-guess repeat was never sent")
        requests = self.step_requests(project, "build")
        self.assertIn("best guess", requests[1].lower())
        self.assertIn("Which port should the server use?", requests[1])
        verification_question = self.settle(driver, lambda status: status["state"] == "running"
                                            and status["step"] == "verification")
        self.assertEqual(verification_question["step"], "verification")
        self.settle(driver, lambda status: status["state"] == "complete")

    def test_unchanged_older_passed_report_never_completes_and_three_attempts_end_unfinished(self):
        project = self.project()
        root = project.root
        (root / "Specification.md").write_text("# S\n\n## Description\n\nFilled.\n", encoding="utf-8")
        (root / "Plan.md").write_text("# P\n\n## Approach\n\nFilled.\n", encoding="utf-8")
        # An 8-October-style PASSED report left exactly as it was.
        (root / "One — Programming Result.md").write_text("# Programming Result\n\nStatus: COMPLETE\n\nDelivered.\n", encoding="utf-8")
        (root / "One — Verification Report.md").write_text(
            "# Verification Report\n\nVerdict: PASSED\n\nThe 8 October pass.\n", encoding="utf-8")
        self.directive(0, reply="A fresh Programming Result for this run.\n", writes={
            str(root / "One — Programming Result.md"): "# Programming Result\n\nStatus: COMPLETE\n\nRedelivered for the run.\n"})
        for index in range(1, 4):
            self.directive(index, reply=f"Verification attempt {index} done; the report stands.\n")
        driver = self.start(project, "build")
        final = self.settle(driver, lambda status: status["state"] == "unfinished")
        self.assertIn("not saved during this verification step", final["reason"])
        self.assertIn("Nothing is claimed to have passed", final["reason"])
        requests = self.step_requests(project, "verification")
        self.assertEqual(len(requests), 3)
        for repeat in requests[1:]:
            self.assertIn("Investigate the cause", repeat)
        self.assertEqual(driver.status()["verdicts"], [])

    def test_not_passed_goes_to_correction_then_verification_passes(self):
        project = self.project()
        root = project.root
        (root / "Specification.md").write_text("# S\n\n## Description\n\nFilled.\n", encoding="utf-8")
        (root / "Plan.md").write_text("# P\n\n## Approach\n\nFilled.\n", encoding="utf-8")
        self.directive(0, reply="Built.\n", writes={
            str(root / "One — Programming Result.md"): "# Programming Result\n\nStatus: COMPLETE\n\nDelivered.\n"})
        self.directive(1, reply="Found one defect.\n", writes={str(root / "One — Verification Report.md"): report("NOT PASSED")})
        self.directive(2, reply="Corrected the defect.\n", writes={
            str(root / "One — Programming Result.md"): "# Programming Result\n\nStatus: COMPLETE\n\nCorrected.\n"})
        self.directive(3, reply="Verified again.\n", writes={str(root / "One — Verification Report.md"): report("PASSED")})
        driver = self.start(project, "build", tool="zcode")
        at_correction = self.settle(driver, lambda status: status["step"] == "correction" or status["state"] == "complete")
        final = self.settle(driver, lambda status: status["state"] == "complete")
        self.assertEqual(final["verdicts"], ["NOT PASSED", "PASSED"])
        steps = [turn["fields"].get("Run-Step") for turn in
                 (conversation.read_turn(folder) for folder in conversation.turn_folders(project))
                 if turn["purpose"] == conversation.PURPOSE_WORK and turn["fields"].get("Run")]
        self.assertEqual(steps, ["build", "verification", "correction", "verification"])
        calls = [json.loads(line) for line in self.argv_log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([call["work_permission"] for call in calls if call["purpose"] == "work"],
                         ["full-access", None, "full-access", None])

    def test_repeated_review_incomplete_repeats_with_changed_approach_and_ends_unfinished(self):
        project = self.project()
        root = project.root
        (root / "Specification.md").write_text("# S\n\n## Description\n\nFilled.\n", encoding="utf-8")
        (root / "Plan.md").write_text("# P\n\n## Approach\n\nFilled.\n", encoding="utf-8")
        (root / "One — Programming Result.md").write_text("# Programming Result\n\nStatus: COMPLETE\n\nDelivered.\n", encoding="utf-8")
        _n, writes = self.build_step_ok(root)
        self.directive(0, reply="Built for the run.\n", writes=writes)
        for index in range(1, 4):
            self.directive(index, reply="The review did not finish.\n", writes={
                str(root / "One — Verification Report.md"):
                    report("NOT PASSED — REVIEW INCOMPLETE") + f"\nAttempt {index}.\n"})
        driver = self.start(project, "build")
        final = self.settle(driver, lambda status: status["state"] == "unfinished")
        self.assertIn("REVIEW INCOMPLETE", final["reason"])
        requests = self.step_requests(project, "verification")
        self.assertEqual(len(requests), 3)
        for repeat in requests[1:]:
            self.assertIn("did not finish", repeat)
            self.assertIn("change the approach", repeat)

    def test_improved_with_evidence_keeps_corrections_going_past_three_attempts(self):
        project = self.project()
        root = project.root
        (root / "Specification.md").write_text("# S\n\n## Description\n\nFilled.\n", encoding="utf-8")
        (root / "Plan.md").write_text("# P\n\n## Approach\n\nFilled.\n", encoding="utf-8")
        (root / "One — Programming Result.md").write_text("# Programming Result\n\nStatus: COMPLETE\n\nDelivered.\n", encoding="utf-8")
        _n, writes = self.build_step_ok(root)
        self.directive(0, reply="Built for the run.\n", writes=writes)
        self.directive(1, reply="First check.\n", writes={str(root / "One — Verification Report.md"):
            report("NOT PASSED", "The login form fails for every user.\n\n- The login form rejected all users in the best verified state; now only SSO users fail, shown by the login check.\n")})
        index = 2
        for round_index in range(1, 5):
            self.directive(index, reply=f"Correction {round_index}.\n", writes={
                str(root / "One — Programming Result.md"): f"# Programming Result\n\nStatus: COMPLETE\n\nCorrection {round_index}.\n"})
            self.directive(index + 1, reply=f"Check {round_index}.\n", writes={
                str(root / "One — Verification Report.md"):
                    report("NOT PASSED", f"Improved\n\n- Round {round_index}: fewer users fail the login check than in the best verified state, shown by the login check.\n")})
            index += 2
        # The fifth correction — still showing improvement, so still continuing —
        # is the one the final PASSED verification follows.
        self.directive(index, reply="Correction five.\n", writes={
            str(root / "One — Programming Result.md"): "# Programming Result\n\nStatus: COMPLETE\n\nCorrection five.\n"})
        self.directive(index + 1, reply="All fixed.\n", writes={str(root / "One — Verification Report.md"): report("PASSED")})
        driver = self.start(project, "build")
        final = self.settle(driver, lambda status: status["state"] == "complete", timeout=60)
        self.assertEqual(len(final["verdicts"]), 6)
        self.assertEqual(final["verdicts"][:5], ["NOT PASSED"] * 5)
        self.assertEqual(final["verdicts"][5], "PASSED")
        self.assertEqual(final["no_progress"], 0)

    def test_not_improved_counts_no_progress_and_best_report_is_resupplied(self):
        project = self.project()
        root = project.root
        (root / "Specification.md").write_text("# S\n\n## Description\n\nFilled.\n", encoding="utf-8")
        (root / "Plan.md").write_text("# P\n\n## Approach\n\nFilled.\n", encoding="utf-8")
        (root / "One — Programming Result.md").write_text("# Programming Result\n\nStatus: COMPLETE\n\nDelivered.\n", encoding="utf-8")
        _n, writes = self.build_step_ok(root)
        self.directive(0, reply="Built for the run.\n", writes=writes)
        self.directive(1, reply="First check.\n", writes={str(root / "One — Verification Report.md"):
            report("NOT PASSED", "Improved\n\n- BEST-STATE-MARKER-ONE everything failed here.\n")})
        self.directive(2, reply="Correction one.\n", writes={
            str(root / "One — Programming Result.md"): "# Programming Result\n\nStatus: COMPLETE\n\nCorrection one.\n"})
        self.directive(3, reply="Second check.\n", writes={str(root / "One — Verification Report.md"):
            report("NOT PASSED", "Not improved\n\nSECOND-REPORT-MARKER\n")})
        self.directive(4, reply="Correction two.\n", writes={
            str(root / "One — Programming Result.md"): "# Programming Result\n\nStatus: COMPLETE\n\nCorrection two.\n"})
        self.directive(5, reply="Third check.\n", writes={str(root / "One — Verification Report.md"):
            report("NOT PASSED", "Improved\n")})
        self.directive(6, reply="Correction three.\n", writes={
            str(root / "One — Programming Result.md"): "# Programming Result\n\nStatus: COMPLETE\n\nCorrection three.\n"})
        self.directive(7, reply="Fourth check.\n", writes={str(root / "One — Verification Report.md"):
            report("NOT PASSED", "")})
        driver = self.start(project, "build")
        final = self.settle(driver, lambda status: status["state"] == "unfinished")
        self.assertIn("Not improved", final["reason"])
        requests = self.step_requests(project, "verification")
        self.assertEqual(len(requests), 4)
        # From the second verification onward the request supplies the best
        # verified state's report — the first one, never merely the previous
        # (Not improved) one.
        for later in requests[1:]:
            self.assertIn("## The best verified state", later)
            at = later.index("## The best verified state")
            end = later.find("\n## Changed approach", at)
            quoted = later[at:end if end > 0 else None]
            self.assertIn("BEST-STATE-MARKER-ONE", quoted)
            self.assertNotIn("SECOND-REPORT-MARKER", quoted)
            self.assertIn("Progress", later)

    def test_stop_run_records_unfinished_without_replay(self):
        project = self.project()
        root = project.root
        self.directive(0, delay=1.5, reply="Slow specification.\n", writes={
            str(root / "Specification.md"): "# S\n\n## Description\n\nFilled.\n"})
        driver = self.start(project, "specification")
        time.sleep(0.4)
        self.runs.stop(project)
        final = self.settle(driver, lambda status: status["state"] == "unfinished")
        self.assertIn("Stopped by the user", final["reason"])
        self.assertIsNone(self.runs.find(project))
        records = run_module.read_runs(project)
        self.assertEqual(records[-1]["state"], "unfinished")
        # No replay: nothing restarts the run after its stop.
        time.sleep(0.4)
        self.assertIsNone(self.runs.find(project))

    def test_operational_failure_pauses_and_is_never_a_content_refusal(self):
        project = self.project()
        root = project.root
        (root / "Specification.md").write_text("# S\n\n## Description\n\nFilled.\n", encoding="utf-8")
        (root / "Plan.md").write_text("# P\n\n## Approach\n\nFilled.\n", encoding="utf-8")
        _n, writes = self.build_step_ok(root)
        self.directive(0, reply="Built for the run.\n", writes=writes)
        self.directive(1, fail=True, reason="The peer harness is not signed in.")
        driver = self.start(project, "build")
        paused = self.settle(driver, lambda status: status["state"] == "paused-failure")
        self.assertIn("not signed in", paused["reason"])
        self.assertNotIn("nothing to build", paused["reason"])
        self.assertNotIn("no actionable product brief", paused["reason"])

    def test_unsupported_role_refused_before_start_with_disclosure(self):
        project = self.project()
        for config, defaults in (({}, {"verification": {"tool": "hermes"}}),
                                 ({"roles": {"verification": {"tool": "hermes"}}}, {"verification": {"tool": "codex"}})):
            with self.subTest(config=config), self.assertRaises(ProjectError) as refused:
                self.start(project, "build", config=config, defaults=defaults)
            self.assertIn("Verification", refused.exception.args[0])
            self.assertIn("Hermes", refused.exception.args[0])
            self.assertIn("cannot exchange turns in-app", refused.exception.args[0])
        self.assertIsNone(self.runs.find(project))
        self.assertEqual(run_module.read_runs(project), [])

    def test_per_run_override_leaves_saved_defaults_unchanged(self):
        settings = Settings(self.root / "settings.json")
        defaults = {"implementation": {"tool": "claude", "model": "saved-model", "effort": "high"},
                    "review": {"tool": "hermes", "model": "", "effort": ""},
                    "specification_second_opinion": {"tool": "claude", "model": "peer-model", "effort": "low"}}
        settings.update(role_defaults=defaults)
        for index, selected_override in enumerate((False, True)):
            with self.subTest(selected_override=selected_override):
                project = self.project("Selected" if selected_override else "Inherited")
                root = project.root
                (root / "Specification.md").write_text("# S\n\n## Description\n\nFilled.\n", encoding="utf-8")
                (root / "Plan.md").write_text("# P\n\n## Approach\n\nFilled.\n", encoding="utf-8")
                name = project.brief()["name"]
                self.directive(index * 2, reply="Built.\n", writes={
                    str(root / f"{name} — Programming Result.md"): "# Programming Result\n\nStatus: COMPLETE\n\nDelivered.\n"})
                self.directive(index * 2 + 1, reply="Verified.\n", writes={str(root / f"{name} — Verification Report.md"): report("PASSED")})
                roles = {"review": {"tool": "codex"}, "verification": {"tool": "zcode"},
                         "specification_second_opinion": {"tool": ""}}
                if selected_override:
                    roles["implementation"] = {"tool": "", "model": "ignored-stale-model", "effort": "low"}
                driver = self.start(project, "build", config={"roles": roles, "best_guess": False, "hide_advisory": False},
                                    defaults=settings.read()["role_defaults"], tool="codex")
                self.settle(driver, lambda status: status["state"] == "complete")
                tools = [conversation.read_turn(root / ".vibe" / step["turn"])["tool"]
                         for step in run_module.read_runs(project)[-1]["steps"]]
                self.assertEqual(tools, ["codex" if selected_override else "claude", "zcode"])
                self.assertEqual(driver.assignment("specification_second_opinion")[:3], ("", "", ""))
                self.assertEqual(settings.read()["role_defaults"], defaults)
        work_calls = [entry for entry in map(json.loads, self.argv_log.read_text().splitlines()) if entry["purpose"] == "work"]
        self.assertEqual([(entry["model"], entry["effort"]) for entry in work_calls],
                         [("saved-model", "high"), (None, None), (None, None), (None, None)])

    def test_requested_model_and_effort_reach_the_bridge_call(self):
        project = self.project()
        root = project.root
        writes = [
            {str(root / "Specification.md"): "# Specification\n\n## Description\n\nA sample tool.\n"},
            {str(root / "Plan.md"): "# Plan\n\n## Approach\n\nOne executable approach.\n"},
            {str(root / "One — Programming Result.md"): "# Programming Result\n\nStatus: COMPLETE\n\nDelivered.\n"},
            {str(root / "One — Verification Report.md"): report("NOT PASSED")},
            {str(root / "One — Programming Result.md"): "# Programming Result\n\nStatus: COMPLETE\n\nCorrected.\n"},
            {str(root / "One — Verification Report.md"): report("PASSED")},
        ]
        for index, files in enumerate(writes):
            self.directive(index, reply="Saved.\n", model="reported-native-model", writes=files)
        choices = {role: {"tool": tool, "model": role + "-model", "effort": effort} for role, tool, effort in (
            ("specification", "codex", "high"), ("planning", "claude", "low"),
            ("implementation", "codex", "high"), ("review", "claude", "low"),
            ("verification", "claude", "low"), ("correction", "codex", "high"))}
        driver = self.start(project, "specification", defaults=choices, tool="zcode")
        final = self.settle(driver, lambda status: status["state"] == "complete")
        argv = [json.loads(line) for line in self.argv_log.read_text(encoding="utf-8").splitlines()]
        work_calls = [entry for entry in argv if entry.get("purpose") == "work"]
        order = ["specification", "planning", "implementation", "verification", "correction", "verification"]
        self.assertEqual([(entry["model"], entry["effort"]) for entry in work_calls],
                         [(choices[role]["model"], choices[role]["effort"]) for role in order])
        for step in ("build", "correction"):
            self.assertIn("review-model (requested)", self.step_requests(project, step)[0])
        self.assertEqual(final["reported_model"], "reported-native-model")

    def test_skip_review_warning_switch_round_trip(self):
        import http.client
        import threading
        from ora_vibe_coder.server import LocalServer
        settings = Settings(self.root / "settings.json")
        server = LocalServer(self.home, settings=settings)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01})
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), thread.join(), server.server_close()))

        def post(path, body):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("POST", path, json.dumps(body),
                               headers={"Content-Type": "application/json", "X-Ora-Token": server.token})
            response = connection.getresponse()
            data = json.loads(response.read())
            connection.close()
            return response.status, data

        _status, created = post("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})
        # On by default, off, and on again: one switch in Settings governs it.
        self.assertTrue(post("/api/setup", {})[1]["app_settings"]["warn_skip_review"])
        self.assertTrue(post("/api/settings", {"warn_skip_review": False})[1]["warn_skip_review"] is False)
        self.assertFalse(Settings(self.root / "settings.json").read()["warn_skip_review"])
        self.assertTrue(post("/api/settings", {"warn_skip_review": True})[1]["warn_skip_review"] is True)
        # A project with something actionable refuses only on the unsupported
        # role, disclosed, before any start.
        (self.home / "One" / "Specification.md").write_text(
            "# Specification\n\n## Description\n\nSomething to build.\n", encoding="utf-8")
        _code, refusal = post("/api/run-start", {"id": created["id"], "entry": "specification", "text": "",
                                                  "images": [], "files": [], "tool": "hermes"})
        self.assertIn("cannot exchange turns in-app", refusal["error"])


if __name__ == "__main__":
    unittest.main()
