"""Run to Completion under a fake Bridge: the fixed route, read from what was saved.

Each fake `run` consumes one directive from a scenario directory — the reply
text, the files it writes, or a failure — so every step's outcome is scripted
while the driver itself decides only from the saved records, exactly as it does
live.
"""

import base64
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from unittest import mock
import unittest

from ora_vibe_coder import conversation, run as run_module
from ora_vibe_coder.launcher import Settings
from ora_vibe_coder.project import Project, ProjectStore, ProjectError
from ora_vibe_coder.server import LocalServer

TEST_ROOT = Path(tempfile.gettempdir())

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
    runp.add_argument("--model")
    runp.add_argument("--effort")
    runp.add_argument("--events-jsonl", action="store_true")
    runp.add_argument("--work-input-jsonl", action="store_true")
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
                          "warnings": [], "work": "supported"}))
        return 0
    session = pathlib.Path(args.session)
    body = json.loads(sys.stdin.readline())["body"] if getattr(args, "work_input_jsonl", False) else sys.stdin.read()
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

def report(verdict, disposition=None, findings=None):
    if disposition is None:
        disposition = ("SETTLED" if verdict.startswith("PASSED") else
                       "INCOMPLETE" if "INCOMPLETE" in verdict else "CORRECTION")
    text = f"---\nstatus: {verdict}\ndisposition: {disposition}\n---\n# Verification Report\n\nWhat was checked and found.\n"
    if findings is not None:
        text += "\n## Findings\n\n" + "\n".join(f"- {item}" for item in findings) + "\n"
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

    def local_server(self):
        """One shared disposable server and POST helper for the API tests."""
        server = LocalServer(self.home, settings=Settings(self.root / "settings.json"))
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
        return server, post

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

    def test_a_failed_brief_save_prevents_the_start(self):
        project = self.project()
        with mock.patch.dict(os.environ, {"VIBE_FAKE_FAIL_RUN_NOTES": "1"}):
            with self.assertRaises(ProjectError):
                self.start(project)
        self.assertIsNone(self.runs.find(project))
        self.assertEqual(run_module.read_runs(project), [])
        self.assertFalse(list((project.root / ".vibe").glob("*/session/messages/*")))

    def test_copy_request_for_a_paused_entry_step_carries_the_brief(self):
        server, post = self.local_server()

        _status, created = post("/api/create", {"directory": "Two", "name": "Two", "description": "", "goals": ""})
        root = self.home / "Two"
        blocker = server.conversation.admit(root, "codex", "programming", frozenset({str(root)}))
        self.addCleanup(blocker.finish, "finished")
        brief_file = self.root / "selected brief.txt"
        brief_text = "Exact selected brief: preserve the blue route.\n"
        brief_file.write_text(brief_text, encoding="utf-8")
        detail_file = self.root / "selected details.md"
        detail_text = "# Selected details\n\n```text\nNested material stays intact.\n```\n"
        detail_file.write_text(detail_text, encoding="utf-8")
        payload = b"tiny png payload for the run brief"
        picture = {"name": "sketch.png", "data": base64.b64encode(payload).decode("ascii")}
        _code, started = post("/api/run-start", {"id": created["id"], "entry": "specification",
                                                 "text": "Build the small tool from this brief.",
                                                 "images": [picture], "files": [str(brief_file), str(detail_file)], "tool": "codex"})
        self.wait_for(lambda: post("/api/turn-state", {"id": created["id"]})[1]
                      ["run"]["active"]["state"] == "paused-failure",
                      message="the entry step never paused on the refused start")
        _code, copied = post("/api/run-copy", {"id": created["id"]})
        self.assertIn("Build the small tool from this brief.", copied["text"])
        self.assertNotIn("Requested harness choices", copied["text"])
        self.assertNotIn("Selected receiving harness", copied["text"])
        self.assertIn("do not start the Plan or implementation", copied["text"])
        for selected, original in ((brief_file, brief_text), (detail_file, detail_text)):
            self.assertIn(f"## Selected material: {selected}\n", copied["text"])
            self.assertIn(original, copied["text"])
            self.assertEqual(selected.read_text(encoding="utf-8"), original)
        self.assertIn("Brief pictures not included: sketch.png.", copied["text"])
        self.assertNotIn(picture["data"], copied["text"])
        self.assertEqual(copied["pictures"], ["sketch.png"])
        self.assertTrue(Path(copied["path"]).is_file())
        self.assertEqual(Path(copied["path"]).read_text(encoding="utf-8"), copied["text"])
        project = self.store.projects[self.store.open(root)]
        kept = sorted(path.name for folder in conversation.turn_folders(project)
                      for path in (folder / "attachments").glob("*"))
        self.assertEqual(kept, ["0001-sketch.png"])
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

    def approve_pair(self, project):
        for stage, role in (("specification", "Specification"), ("planning", "Plan")):
            path = project.root / f"{role}.md"
            path.write_text(f"---\nstatus: AWAITING APPROVAL\n---\n# {role}\n\n## Requirements\nKeep records for 30 days.\n")
            project.approve_document(stage, path.read_text(), str(path))

    def test_matching_approved_documents_start_implementation(self):
        counter = 0
        for entry, count in (("specification", 2), ("planning", 2), ("specification", 1), ("planning", 0)):
            with self.subTest(entry=entry, approved=count):
                project = self.project(f"Approved {entry} {count}")
                self.approve_pair(project)
                if count < 2:
                    plan = project.root / "Plan.md"
                    plan.write_text(plan.read_text().replace("status: APPROVED", "status: AWAITING APPROVAL"))
                if count == 0:
                    spec = project.root / "Specification.md"
                    spec.write_text(spec.read_text().replace("status: APPROVED", "status: AWAITING APPROVAL"))
                if count == 2:
                    # A reused Project may already cache the earlier approved
                    # copy when another session approves a newer real version.
                    project.snapshot()
                    plan = project.root / "Plan.md"
                    plan.write_text(plan.read_text().replace("30 days", "90 days"))
                    Project(project.root).approve_document("planning", plan.read_text(), str(plan))
                    # Supported recording/layout equivalences keep approval.
                    for role in ("Specification", "Plan"):
                        path = project.root / f"{role}.md"
                        path.write_text(path.read_text().replace("## Requirements", "## **Requirements**")
                                        .replace("days.", "days.  ").replace("status: APPROVED", "status: APPROVED\nreview: PASSED"))
                selected = self.root / f"selected-{counter}.txt"
                selected.write_text("Preserve this exact selected detail.\n")
                picture = {"name": "sketch.png", "data": base64.b64encode(b"original drawing").decode()}
                self.directive(counter, reply=reply_with_questions("Which approved color?"))
                counter += 1
                expected = "build" if count == 2 else entry
                driver = self.runs.start(self.registry, project, entry, "The exact user brief.",
                    {"roles": {}, "hide_advisory": True}, {}, "codex", [picture], [str(selected)])
                paused = self.settle(driver, lambda state: state["state"] == "paused-question")
                self.assertEqual((paused["entry"], paused["step"]), (expected, expected))
                request = self.own_message(self.step_requests(project)[0])
                self.assertEqual(request.count("The exact user brief."), 1)
                self.assertIn("Preserve this exact selected detail.", request)
                turns = [conversation.read_turn(folder) for folder in conversation.turn_folders(project)]
                work = [turn for turn in turns if turn["purpose"] == conversation.PURPOSE_WORK]
                self.assertEqual([turn["fields"]["Run-Step"] for turn in work], [expected])
                self.assertIn("sketch.png", request)
                if count == 2:
                    self.directive(counter, writes={str(project.root / f"{project.brief()['name']} — Programming Result.md"):
                        "# Programming Result\n\nStatus: COMPLETE\n\nDelivered.\n"})
                    self.directive(counter + 1, reply=reply_with_questions("Which verification environment?"))
                    counter += 2
                    driver.receive_answer("Use blue.")
                    self.settle(driver, lambda state: state["questions"] == ["Which verification environment?"])
                    for later in self.step_requests(project)[1:]:
                        own = self.own_message(later)
                        self.assertNotIn("The exact user brief.", own)
                        self.assertNotIn("Preserve this exact selected detail.", own)
                driver.request_stop()
                self.assertTrue(driver.done.wait(5))

    def test_run_requires_current_approval_confirmation(self):
        server, post = self.local_server()
        for changed, missing, preferences in ((("Specification",), False, False), (("Plan",), False, True),
                                               (("Specification", "Plan"), False, True), (("Specification",), True, True)):
            with self.subTest(changed=changed, missing=missing, best_guess=preferences):
                name = "Case " + str(len(server.store.projects))
                created = post("/api/create", {"directory": name, "name": name, "description": "", "goals": ""})[1]
                project = server.store.projects[created["id"]]
                self.approve_pair(project)
                for role in changed:
                    path = project.root / f"{role}.md"
                    if missing:
                        # A matching reviewed snapshot is useful review evidence,
                        # but is not a retained approval.
                        from ora_vibe_coder.status import review_basis
                        current = path.read_text()
                        reviewed = current.replace("status: APPROVED", "status: APPROVED\nreview: PASSED\nreview basis: " + review_basis(current))
                        path.write_text(reviewed)
                        folder = conversation.reserve_turn_folder(project)
                        messages = folder / "session" / "messages"
                        messages.mkdir(parents=True)
                        (messages / "0001-initiator-to-peer.md").write_text(
                            "# Message 0001\nFrom: vibe-coder\nTo: peer\n\n## Body\n\n## " + role +
                            "\n\nSource:\n\n```text\n" + str(path) + "\n```\n\n```text\n" + current + "\n```\n")
                        for note in (project.root / ".vibe").glob("*/session/messages/*-initiator-record.md"):
                            if "Vibe-Role: " + role + "\n" in note.read_text():
                                note.unlink()
                    else:
                        path.write_text(path.read_text().replace("30 days", "90 days"))
                before = {str(path): path.read_bytes() for path in project.root.rglob("*") if path.is_file()}
                request = {"id": created["id"], "entry": "planning", "text": "Keep the brief.", "images": [], "files": [],
                           "tool": "codex", "config": {"hide_advisory": preferences, "best_guess": preferences}}
                code, result = post("/api/run-start", request)
                self.assertEqual(code, 200)
                confirmation = result["approval_confirmation"]
                self.assertEqual({item["role"] for item in confirmation["documents"] if item["state"] in {"changed", "missing"}}, set(changed))
                for item in confirmation["documents"]:
                    if item["role"] in changed:
                        self.assertEqual(item["state"], "missing" if missing else "changed")
                        if not missing:
                            self.assertIn("-Keep records for 30 days.", item["difference"])
                            self.assertIn("+Keep records for 90 days.", item["difference"])
                        self.assertEqual(item["text"], Path(item["path"]).read_text())
                # Even a bare confirmation flag cannot replace the explicit choice.
                self.assertIn("approval_confirmation", post("/api/run-start", dict(request, confirmation=True))[1])
                self.assertIsNone(server.runs.find(project))
                self.assertFalse((self.scenario / "directive.count").exists())
                self.assertEqual({str(path): path.read_bytes() for path in project.root.rglob("*") if path.is_file()}, before)
                # Direct callers receive the same unavoidable preflight.
                with self.assertRaises(run_module.RunApprovalRequired):
                    self.start(project, "planning", config={"roles": {}, "best_guess": True, "hide_advisory": True})

    def test_run_confirmation_rechecks_displayed_documents(self):
        server, post = self.local_server()
        counter = 0
        for edit in ("Specification", "Plan", "resolved path"):
            with self.subTest(edit=edit):
                name = "Stale " + str(counter)
                created = post("/api/create", {"directory": name, "name": name, "description": "", "goals": ""})[1]
                project = server.store.projects[created["id"]]
                self.approve_pair(project)
                plan = project.root / "Plan.md"
                plan.write_text(plan.read_text().replace("30 days", "90 days"))
                if edit == "resolved path":
                    # Deliberately associated path remains spelled identically
                    # while an in-project parent link selects another file.
                    for target in ("old", "new"):
                        folder = project.root / target
                        folder.mkdir()
                        (folder / "Specification.md").write_text((project.root / "Specification.md").read_text())
                    (project.root / "chosen").symlink_to(project.root / "old", target_is_directory=True)
                    overview = project.root / "Project.md"
                    overview.write_text(overview.read_text().replace("## Artifact Paths", "## Artifact Paths\n\n- Specification: chosen/Specification.md"))
                    project.approve_document("specification", (project.root / "chosen/Specification.md").read_text(), str(project.root / "chosen/Specification.md"))
                request = {"id": created["id"], "entry": "specification", "text": "Retain exact brief.", "images": [], "files": [], "tool": "codex"}
                prompt = post("/api/run-start", request)[1]["approval_confirmation"]
                before_notes = set((project.root / ".vibe").glob("*/session/messages/*"))
                if edit == "resolved path":
                    (project.root / "chosen").unlink()
                    (project.root / "chosen").symlink_to(project.root / "new", target_is_directory=True)
                else:
                    path = project.root / f"{edit}.md"
                    path.write_text(path.read_text().replace("days.", "days, with backups."))
                refreshed = post("/api/run-start", dict(request, confirmation=prompt["token"]))[1]["approval_confirmation"]
                self.assertTrue(refreshed["stale"])
                self.assertNotEqual(refreshed["token"], prompt["token"])
                self.assertEqual(set((project.root / ".vibe").glob("*/session/messages/*")), before_notes)
                self.assertIsNone(server.runs.find(project))
                # Consent to the refreshed contents records only those versions.
                chosen = {item["role"]: item["text"] for item in refreshed["documents"]}
                self.directive(counter, reply=reply_with_questions("Which deployment target?"))
                counter += 1
                result = post("/api/run-start", dict(request, confirmation=refreshed["token"]))[1]
                driver = server.runs.find(project)
                self.assertEqual(result["run"]["entry"], "build")
                self.settle(driver, lambda state: state["state"] == "paused-question")
                for role, text in chosen.items():
                    self.assertEqual(project._approved_document(role, project.material(role)["path"], fresh=True)["text"], text)
                driver.request_stop()
                self.assertTrue(driver.done.wait(5))

    def test_a_run_from_the_plan_workspace_enters_at_the_planning_step(self):
        server, post = self.local_server()
        steps = ("specification", "planning", "build", "verification")
        counter = 0
        for entry, start in (("specification", 0), ("planning", 1), ("build", 2)):
            with self.subTest(entry=entry):
                name = entry.title()
                created = post("/api/create", {"directory": name, "name": name, "description": "", "goals": ""})[1]
                root = self.home / name
                outputs = (("Specification.md", "# Specification\n\nA useful product brief.\n"),
                           ("Plan.md", "# Plan\n\nAn executable approach.\n"),
                           (f"{name} — Programming Result.md", "# Programming Result\n\nStatus: COMPLETE\n\nDelivered.\n"),
                           (f"{name} — Verification Report.md", report("PASSED")))
                self.directive(counter, reply=reply_with_questions("Which behavior?"))
                counter += 1
                for path, text in outputs[start:]:
                    self.directive(counter, reply="Saved.", writes={str(root / path): text})
                    counter += 1
                code, started = post("/api/run-start", {"id": created["id"], "entry": entry,
                    "text": "Keep this brief.", "images": [], "files": [], "tool": "codex"})
                self.assertEqual(code, 200)
                self.assertEqual(started["run"]["entry"], entry)
                project = server.store.projects[created["id"]]
                driver = server.runs.find(project)
                paused = self.settle(driver, lambda state: state["state"] == "paused-question")
                self.assertEqual(paused["questions"], ["Which behavior?"])
                driver.receive_answer("Use the agreed behavior.")
                self.wait_for(lambda: (post("/api/turn-state", {"id": created["id"]})[1]["run"].get("last") or {}).get("state") == "complete")
                project = server.store.projects[created["id"]]
                turns = [conversation.read_turn(folder) for folder in conversation.turn_folders(project)]
                self.assertEqual([turn["fields"]["Run-Step"] for turn in turns if turn["purpose"] == conversation.PURPOSE_WORK], [steps[start], *steps[start:]])
                requests = self.step_requests(project)
                self.assertIn("Keep this brief.", self.own_message(requests[0]))
                for request in requests[1:]:
                    self.assertNotIn("Keep this brief.", self.own_message(request))
                if start < 2:
                    self.assertIn("status: APPROVED", (root / "Plan.md").read_text())
                if start == 0:
                    self.assertIn("status: APPROVED", (root / "Specification.md").read_text())

    def test_deliver_send_with_a_picture_attaches_it_to_the_started_turn(self):
        server, post = self.local_server()

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
        payload = b"tiny png payload for the run answer"
        answer_picture = {"name": "answer shot.png",
                          "data": base64.b64encode(payload).decode("ascii"),
                          "notes": "1. Callout\nUse SQLite for the marked area"}
        driver.receive_answer("Use SQLite everywhere.", [answer_picture], [])
        retained = [folder for folder in conversation.turn_folders(project)
                    if (folder / "attachments" / "0001-answer-shot.png").is_file()]
        self.assertGreaterEqual(len(retained), 1)
        self.assertEqual((retained[0] / "attachments" / "0001-answer-shot.png").read_bytes(), payload)
        self.assertEqual((retained[0] / "attachments" / "0001-answer-shot.png.notes.txt").read_text(encoding="utf-8"),
                         "1. Callout\nUse SQLite for the marked area")
        paused_verification = self.settle(driver, lambda status: status["state"] == "paused-question" and status["step"] == "verification")
        self.assertEqual(paused_verification["step"], "verification")
        self.directive(3, reply="Verified.\n", writes={str(root / "One — Verification Report.md"): report("PASSED")})
        driver.receive_answer("The work is signed off.")
        self.settle(driver, lambda status: status["state"] == "complete")
        requests = self.step_requests(project)
        self.assertIn("Use SQLite everywhere.", requests[1])
        self.assertIn("The work is signed off.", requests[3])
        carried = [folder for folder in conversation.turn_folders(project)
                   if (folder / "attachments").is_dir()]
        self.assertEqual(len(carried), 2)
        for record in carried:
            self.assertEqual((record / "attachments" / "0001-answer-shot.png").read_bytes(), payload)
            self.assertEqual((record / "attachments" / "0001-answer-shot.png.notes.txt").read_text(encoding="utf-8"),
                             "1. Callout\nUse SQLite for the marked area")
        self.assertLess(requests[1].index("0001-answer-shot.png"),
                        requests[1].index("Use SQLite for the marked area"))
        self.assertNotIn("0001-answer-shot.png", requests[3])
        self.assertEqual(driver.status()["no_progress"], 0)

    def test_unchanged_older_passed_report_never_completes_and_three_attempts_end_unfinished(self):
        project = self.project()
        root = project.root
        (root / "Specification.md").write_text("# S\n\n## Description\n\nFilled.\n", encoding="utf-8")
        (root / "Plan.md").write_text("# P\n\n## Approach\n\nFilled.\n", encoding="utf-8")
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

    def test_not_passed_goes_to_correction_which_settles_and_completes(self):
        with self.subTest(name="a severe finding settles only through its own recorded fix"):
            project = self.project("Two")
            root = project.root
            (root / "Specification.md").write_text("# S\n\n## Description\n\nFilled.\n", encoding="utf-8")
            (root / "Plan.md").write_text("# P\n\n## Approach\n\nFilled.\n", encoding="utf-8")
            self.directive(0, reply="Built.\n", writes={
                str(root / "Two — Programming Result.md"): "# Programming Result\n\nStatus: COMPLETE\n\nDelivered.\n"})
            self.directive(1, reply="Found a severe defect.\n", writes={str(root / "Two — Verification Report.md"): report(
                "NOT PASSED", disposition="SEVERE",
                findings=["S1 — the export sends the collected addresses to an outside endpoint.",
                          "R1 — the login check accepts an empty password."])})
            driver = self.start(project, "build")
            paused = self.settle(driver, lambda status: status["state"] == "paused-question")
            self.assertIn("severe finding", paused["questions"][0])
            self.directive(2, reply="Rejected the integration claim.\n", writes={
                str(root / "Two — Programming Result.md"): "---\nstatus: PASSED\ndisposition: SETTLED\n---\n"
                                                               "# Programming Result\n\n"
                                                               "- S1 — REJECTED — the outside send is the vendor's required integration; no change.\n"
                                                               "- R1 — FIXED — corrected the login check; the empty-password case now fails.\n"})
            self.directive(3, reply="Resolved the severe finding.\n", writes={
                str(root / "Two — Programming Result.md"): "---\nstatus: PASSED\ndisposition: SETTLED\n---\n"
                                                               "# Programming Result\n\n"
                                                               "- S1 — FIXED — removed the outside send; the export writes only the local file, verified by its check.\n"
                                                               "- R1 — FIXED — corrected the login check; the empty-password case now fails.\n"})
            driver.receive_answer("Remove the outside send; keep everything else.", [], [])
            final = self.settle(driver, lambda status: status["state"] == "complete", timeout=60)
            self.assertEqual(final["verdicts"], ["NOT PASSED"])
            self.assertIn("completed after correction", final["reason"])
            corrections = self.step_requests(project, "correction")
            self.assertEqual(len(corrections), 2)
            self.assertIn("the severe finding(s) S1", corrections[1])
            self.assertIn("own recorded fix with evidence", corrections[1])
            self.assertEqual(len(self.step_requests(project, "verification")), 1)
            saved = project.snapshot()
            self.assertEqual(saved["programming_result"]["status"]["label"], "PASSED")
            self.assertEqual(saved["verification"]["status"]["label"], "CORRECTED")
            self.assertEqual(saved["verification"]["status"]["literal"], "NOT PASSED")
            self.assertIn("status: NOT PASSED", project.material("Verification Report")["text"])

    def test_verification_routing_severe_ask_user_and_user_closure(self):
        counter = 0
        closure = ("---\nstatus: CLOSED BY USER — UNRESOLVED FINDINGS\ndisposition: SETTLED\n---\n"
                   "# Programming Result\n\n- R1 — FIXED — corrected the login check.\n")
        for report_text, closing, expected in (
                # SEVERE reaches the owner whatever the status says; it is never retried.
                (report("INCOMPLETE", disposition="SEVERE"), False, ("paused-question", "severe finding")),
                (report("PASSED", disposition="SEVERE"), False, ("paused-question", "severe finding")),
                ("---\ndisposition: SEVERE\n---\n# Verification Report\n", False, ("paused-question", "severe finding")),
                (report("NOT PASSED", disposition="ASK USER"), False, ("paused-question", "ASK USER")),
                # ASK USER outranks an INCOMPLETE status; closure in a saved Result ends unfinished.
                (report("INCOMPLETE", disposition="ASK USER"), False, ("paused-question", "ASK USER")),
                ("---\nstatus: CLOSED BY USER — UNRESOLVED FINDINGS\n---\n# Verification Report\n", False, ("unfinished", "user closure")),
                (None, True, ("unfinished", "user closure")),
                (report("NOT PASSED", disposition="CORRECTION"), True, ("unfinished", "user closure"))):
            name = f"Route{counter}"
            with self.subTest(expected=expected[1]):
                project = self.project(name)
                root = project.root
                (root / "Specification.md").write_text("# S\n\n## Description\n\nFilled.\n", encoding="utf-8")
                (root / "Plan.md").write_text("# P\n\n## Approach\n\nFilled.\n", encoding="utf-8")
                self.directive(counter, reply="Built.\n", writes={
                    str(root / f"{name} — Programming Result.md"): closure if closing and report_text is None else
                        "---\nstatus: PASSED\n---\n# Programming Result\n\nBuilt for the run.\n"})
                counter += 1
                if report_text is not None:
                    self.directive(counter, reply="Reported.\n",
                                   writes={str(root / f"{name} — Verification Report.md"): report_text})
                    counter += 1
                if closing and report_text is not None:
                    self.directive(counter, reply="Closed by the user.\n", writes={
                        str(root / f"{name} — Programming Result.md"): closure})
                    counter += 1
                driver = self.start(project, "build")
                final = self.settle(driver, lambda status: status["state"] == expected[0])
                self.assertIn(expected[1], final["questions"][0] if final["questions"] else final["reason"])

    def test_a_settled_correction_finishes_with_a_warning_whatever_its_status(self):
        project = self.project()
        root = project.root
        (root / "Specification.md").write_text("# S\n\n## Description\n\nFilled.\n", encoding="utf-8")
        (root / "Plan.md").write_text("# P\n\n## Approach\n\nFilled.\n", encoding="utf-8")
        _n, writes = self.build_step_ok(root)
        self.directive(0, reply="Built.\n", writes=writes)
        self.directive(1, reply="Found one defect.\n", writes={str(root / "One — Verification Report.md"):
            report("NOT PASSED", disposition="CORRECTION",
                   findings=["R1 — the login check accepts an empty password."])})
        self.directive(2, reply="Settled but unfinished.\n", writes={
            str(root / "One — Programming Result.md"): "---\nstatus: INCOMPLETE\ndisposition: SETTLED\n---\n"
                                                       "# Programming Result\n\n- R1 — FIXED — corrected; the check passes.\n"})
        driver = self.start(project, "build")
        final = self.settle(driver, lambda status: status["state"] == "unfinished", timeout=60)
        self.assertIn("status reads INCOMPLETE, not PASSED", final["reason"])
        self.assertEqual(len(self.step_requests(project, "correction")), 1)

    def test_a_best_guess_run_does_not_pause_for_ask_user(self):
        project = self.project()
        root = project.root
        (root / "Specification.md").write_text("# S\n\n## Description\n\nFilled.\n", encoding="utf-8")
        (root / "Plan.md").write_text("# P\n\n## Approach\n\nFilled.\n", encoding="utf-8")
        _n, writes = self.build_step_ok(root)
        self.directive(0, reply="Built.\n", writes=writes)
        self.directive(1, reply="Needs a choice.\n", writes={str(root / "One — Verification Report.md"): report("NOT PASSED", disposition="ASK USER")})
        self.directive(2, reply="Guessed.\n", writes={str(root / "One — Verification Report.md"): report("PASSED")})
        driver = self.start(project, "build", config={"roles": {}, "best_guess": True, "hide_advisory": False})
        self.settle(driver, lambda status: status["state"] == "complete", timeout=60)

    def test_correction_that_is_not_settled_is_retried_then_settling_completes(self):
        project = self.project()
        root = project.root
        (root / "Specification.md").write_text("# S\n\n## Description\n\nFilled.\n", encoding="utf-8")
        (root / "Plan.md").write_text("# P\n\n## Approach\n\nFilled.\n", encoding="utf-8")
        (root / "One — Programming Result.md").write_text("# Programming Result\n\nStatus: COMPLETE\n\nDelivered.\n", encoding="utf-8")
        _n, writes = self.build_step_ok(root)
        self.directive(0, reply="Built for the run.\n", writes=writes)
        self.directive(1, reply="Found two defects.\n", writes={str(root / "One — Verification Report.md"):
            report("NOT PASSED", disposition="CORRECTION",
                   findings=["R1 — the login check accepts an empty password.",
                             "R2 — the export omits the trailing summary row."])})
        self.directive(2, reply="Interrupted mid-correction.\n", writes={
            str(root / "One — Programming Result.md"): "---\nstatus: INCOMPLETE\ndisposition: INCOMPLETE\n---\n"
                                                       "# Programming Result\n\nWork began on the defect.\n"})
        self.directive(3, reply="Resolved both.\n", writes={
            str(root / "One — Programming Result.md"): "---\nstatus: PASSED\ndisposition: SETTLED\n---\n"
                                                       "# Programming Result\n\n"
                                                       "- R1 — FIXED — corrected the login check; the empty-password case now fails.\n"
                                                       "- R2 — REJECTED — the summary row is outside the approved Specification; no change.\n"})
        driver = self.start(project, "build")
        final = self.settle(driver, lambda status: status["state"] == "complete", timeout=60)
        self.assertEqual(final["verdicts"], ["NOT PASSED"])
        self.assertIn("completed after correction", final["reason"])
        steps = [turn["fields"].get("Run-Step") for turn in
                 (conversation.read_turn(folder) for folder in conversation.turn_folders(project))
                 if turn["purpose"] == conversation.PURPOSE_WORK and turn["fields"].get("Run")]
        self.assertEqual(steps, ["build", "verification", "correction", "correction"])
        corrections = self.step_requests(project, "correction")
        self.assertEqual(len(corrections), 2)
        self.assertIn("declared `INCOMPLETE`", corrections[1])
        self.assertIn("Actually resolve every recorded finding", corrections[1])
        self.assertEqual(len(self.step_requests(project, "verification")), 1)

    def test_unsettled_corrections_count_no_progress_and_end_unfinished(self):
        project = self.project()
        root = project.root
        (root / "Specification.md").write_text("# S\n\n## Description\n\nFilled.\n", encoding="utf-8")
        (root / "Plan.md").write_text("# P\n\n## Approach\n\nFilled.\n", encoding="utf-8")
        (root / "One — Programming Result.md").write_text("# Programming Result\n\nStatus: COMPLETE\n\nDelivered.\n", encoding="utf-8")
        _n, writes = self.build_step_ok(root)
        self.directive(0, reply="Built for the run.\n", writes=writes)
        self.directive(1, reply="Found one defect.\n", writes={str(root / "One — Verification Report.md"):
            report("NOT PASSED", disposition="CORRECTION",
                   findings=["R1 — the login check accepts an empty password."])})
        for index in range(2, 5):
            self.directive(index, reply=f"Correction attempt {index} done.\n", writes={
                str(root / "One — Programming Result.md"): f"# Programming Result\n\nStatus: COMPLETE\n\nCorrection attempt {index}.\n"})
        driver = self.start(project, "build")
        final = self.settle(driver, lambda status: status["state"] == "unfinished")
        self.assertIn("did not carry a settled `disposition: SETTLED`", final["reason"])
        corrections = self.step_requests(project, "correction")
        self.assertEqual(len(corrections), 3)
        for repeat in corrections[1:]:
            self.assertIn("Actually resolve every recorded finding", repeat)
            self.assertIn("A saved success word alone is not a settled correction", repeat)
        self.assertEqual(len(self.step_requests(project, "verification")), 1)

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
        time.sleep(0.4)
        self.assertIsNone(self.runs.find(project))
        self.assertEqual((self.scenario / "directive.count").read_text(), "1")
        self.assertIn("Filled", (root / "Specification.md").read_text())
        self.assertFalse(driver.handle.live_children())
        self.assertFalse(driver.resume())

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
        self.assertIn("Inspect the saved files", paused["reason"])
        self.assertTrue(paused["operation"]["dispatched"])
        frozen = paused["elapsed_seconds"]
        self.assertEqual(driver.status()["elapsed_seconds"], frozen)
        self.assertEqual((self.scenario / "directive.count").read_text(), "2")
        blocked = self.project("Permission")
        with mock.patch.object(conversation, "require_work_route", side_effect=ProjectError("Native permission is required.")):
            second = self.start(blocked)
            waiting = self.settle(second, lambda state: state["state"] == "paused-failure")
            self.assertIn("permission", waiting["reason"])
            self.assertIn("Nothing was dispatched", waiting["reason"])
            self.assertIsNone(waiting["operation"])
            self.assertEqual(waiting["elapsed_seconds"], 0)
            second.request_stop()
            self.assertTrue(second.done.wait(10))

    def test_transient_failure_recovers_without_replaying_changed_work(self):
        import errno
        project = self.project()
        self.directive(0, reply="Recovered before dispatch.")
        popen, rejected = conversation.subprocess.Popen, []
        def unavailable(argv, *args, **kwargs):
            if "run" in argv and not rejected:
                rejected.append(argv)
                raise OSError(errno.EAGAIN, "temporarily unavailable")
            return popen(argv, *args, **kwargs)
        with mock.patch.object(conversation.subprocess, "Popen", side_effect=unavailable):
            safe = conversation.start_turn(self.registry, project, "codex", "specification", "Create it", [])
            self.assertTrue(safe.done.wait(10))
        self.assertEqual((safe.state, len(rejected)), ("finished", 1))
        code = self.root / "code"
        code.mkdir()
        project.save_brief(project.brief_text(), "One", "Description", "Goals", {"Code": str(code)})
        changed = code / "main.py"
        self.directive(1, fail=True, reason="temporary service unavailable", writes={str(changed): "saved work"})
        driver = self.start(project, "build")
        paused = self.settle(driver, lambda state: state["state"] == "paused-failure")
        self.assertIn("Inspect the saved files", paused["reason"])
        self.assertFalse(driver.resume())
        self.assertEqual(changed.read_text(), "saved work")
        self.assertEqual((self.scenario / "directive.count").read_text(), "2")

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
            {str(root / "One — Verification Report.md"): report(
                "NOT PASSED", findings=["R1 — the saved result omits the required check evidence."])},
            {str(root / "One — Programming Result.md"):
                "---\nstatus: PASSED\ndisposition: SETTLED\n---\n# Programming Result\n\n"
                "- R1 — FIXED — corrected; the check passes.\n"},
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
        order = ["specification", "planning", "implementation", "verification", "correction"]
        self.assertEqual([(entry["model"], entry["effort"]) for entry in work_calls],
                         [(choices[role]["model"], choices[role]["effort"]) for role in order])
        for step in ("build", "correction"):
            self.assertIn("review-model (requested)", self.step_requests(project, step)[0])
        self.assertEqual(final["reported_model"], "reported-native-model")
        for config in ({"roles": {}}, {"roles": {"review": {"tool": "", "model": "", "effort": ""}}}):
            defaults = {"implementation": choices["implementation"]}
            if config["roles"]:
                defaults["review"] = choices["review"]
            self.assertEqual(run_module.resolve_assignment("review", config, "build", "zcode", defaults)[:3],
                             ("codex", "implementation-model", "high"))
        self.assertIn("Requested independent verifier choices (not verified): Claude Code, model verification-model (requested), effort low (requested)", self.step_requests(project, "verification")[0])
        self.assertEqual(run_module.resolve_assignment("correction", {"roles": {}}, "build", "claude",
                                                       {"implementation": choices["implementation"]})[:3],
                         ("codex", "implementation-model", "high"))

    def test_skip_review_warning_switch_round_trip(self):
        server, post = self.local_server()

        _status, created = post("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})
        self.assertFalse(post("/api/setup", {})[1]["app_settings"]["hide_advisory"])
        self.assertTrue(post("/api/settings", {"hide_advisory": True})[1]["hide_advisory"])
        self.assertTrue(Settings(self.root / "settings.json").read()["hide_advisory"])
        self.assertTrue(post("/api/settings", {"hide_advisory": False})[1]["hide_advisory"] is False)
        (self.home / "One" / "Specification.md").write_text(
            "# Specification\n\n## Description\n\nSomething to build.\n", encoding="utf-8")
        _code, refusal = post("/api/run-start", {"id": created["id"], "entry": "specification", "text": "",
                                                  "images": [], "files": [], "tool": "hermes"})
        self.assertIn("cannot exchange turns in-app", refusal["error"])

    def test_a_run_refuses_only_when_there_is_literally_nothing_to_build(self):
        server, post = self.local_server()
        for name, description, expected in (("Empty", "", "literally nothing to build"),
                                            ("Described", "A small tool.", "cannot exchange turns in-app")):
            _status, created = post("/api/create", {"directory": name, "name": name, "description": description, "goals": ""})
            _code, refusal = post("/api/run-start", {"id": created["id"], "entry": "specification", "text": "",
                                                      "images": [], "files": [], "tool": "hermes"})
            self.assertIn(expected, refusal["error"])

if __name__ == "__main__":
    unittest.main()
