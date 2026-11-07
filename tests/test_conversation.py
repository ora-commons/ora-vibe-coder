import base64
import http.client
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from unittest.mock import patch

from ora_vibe_coder import conversation, handoff, run as run_module
from ora_vibe_coder.conversation import (
    MAINTENANCE_CONTENT, MAINTENANCE_CONTENT_END, MAINTENANCE_END, MAINTENANCE_FIND,
    MAINTENANCE_FIND_END, MAINTENANCE_REPLACE, MAINTENANCE_REPLACE_END, MAINTENANCE_START,
)
from ora_vibe_coder.handoff import prepare_request
from ora_vibe_coder.launcher import Settings
from ora_vibe_coder.project import ProjectError, ProjectStore
from ora_vibe_coder.server import LocalServer

TEST_ROOT = Path(tempfile.gettempdir())

FAKE_BRIDGE = '''
"""A fake Agent Bridge: the documented record/run surface under test control."""
import argparse, json, os, pathlib, signal, subprocess, sys, time

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
    parser = argparse.ArgumentParser(prog="bridge")
    sub = parser.add_subparsers(dest="command")
    record = sub.add_parser("record")
    record.add_argument("--session", required=True)
    record.add_argument("--kind", required=True)
    record.add_argument("--initiator")
    record.add_argument("--peer")
    record.add_argument("--project")
    record.add_argument("--mode")
    record.add_argument("--access-path", action="append")
    run = sub.add_parser("run")
    run.add_argument("--session", required=True)
    run.add_argument("--timeout", type=float, default=900.0)
    run.add_argument("--no-timeout", action="store_true")
    run.add_argument("--events-jsonl", action="store_true")
    run.add_argument("--work-input-jsonl", action="store_true")
    run.add_argument("--attachment", action="append")
    run.add_argument("--note-ref")
    run.add_argument("--purpose")
    run.add_argument("--work-permission")
    run.add_argument("--model")
    run.add_argument("--effort")
    check = sub.add_parser("check")
    check.add_argument("--peer", required=True)
    check.add_argument("--mode")
    check.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.command == "check":
        work = os.environ.get("VIBE_FAKE_CHECK_WORK", "supported")
        peer_work = os.environ.get("VIBE_FAKE_CHECK_PEER_WORK_" + args.peer.upper())
        if peer_work:
            work = peer_work
        result = {"peer": args.peer, "mode": args.mode or "review", "ready": True,
                  "warnings": [], "image": "supported"}
        if work != "missing":
            result["work"] = work
        print(json.dumps(result))
        return 0
    session = pathlib.Path(args.session)
    body = json.loads(sys.stdin.readline())["body"] if getattr(args, "work_input_jsonl", False) else sys.stdin.read()
    if args.command == "record":
        if args.kind == "session-create":
            if (session / "SESSION.md").exists():
                sys.stderr.write("SESSION_EXISTS\\n")
                return 1
            (session / "messages").mkdir(parents=True, exist_ok=True)
            lines = ["# Session", "", "Bridge-Format: 3",
                     "Initiator: " + str(args.initiator), "Peer: " + str(args.peer),
                     "Mode: " + str(args.mode)]
            if args.project:
                lines.append("Project: " + args.project)
            for path in args.access_path or []:
                lines.append("Access-Path: " + path)
            (session / "SESSION.md").write_text(
                "\\n".join(lines) + "\\n\\n## Body\\n\\n" + body, encoding="utf-8")
            print(session / "SESSION.md")
            return 0
        if args.kind == "note":
            if not (session / "SESSION.md").is_file():
                sys.stderr.write("SESSION_NOT_FOUND\\n")
                return 1
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
    if not body.strip():
        sys.stderr.write("USAGE_ERROR empty body\\n")
        return 1
    sequence = next_sequence(session)
    request = session / "messages" / ("%04d-initiator-to-peer.md" % sequence)
    headers = ["# Message %04d" % sequence, "From: vibe-coder", "To: peer"]
    if args.note_ref:
        headers.append("Note-Ref: " + args.note_ref)
    if args.purpose:
        headers.append("Purpose: " + args.purpose)
    if args.work_permission:
        headers.append("Work-Permission: " + args.work_permission)
    for item in args.attachment or []:
        headers.append("Attachment: " + item)
    request.write_text("\\n".join(headers) + "\\n\\n## Body\\n\\n" + body, encoding="utf-8")
    if os.environ.get("VIBE_FAKE_IGNORE_TERM"):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if os.environ.get("VIBE_FAKE_CHILD_PID"):
        child = subprocess.Popen([sys.executable, "-c", "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"])
        pathlib.Path(os.environ["VIBE_FAKE_CHILD_PID"]).write_text(str(child.pid))
    if os.environ.get("VIBE_FAKE_WRITE_FILE"):
        pathlib.Path(os.environ["VIBE_FAKE_WRITE_FILE"]).write_text("# Programming Result\\n\\nStatus: INCOMPLETE\\n\\nPartial work remains.\\n")
    if args.events_jsonl:
        emit({"event": "started", "phase": "run", "peer": "peer", "mode": "work"})
        emit({"event": "heartbeat", "phase": "prerequisites", "elapsed_seconds": 0.05, "child_running": True})
        time.sleep(float(os.environ.get("VIBE_FAKE_DELAY", "0")))
    if os.environ.get("VIBE_FAKE_FAIL") or os.environ.get("VIBE_FAKE_FAIL_PURPOSE_" + (args.purpose or "").upper()):
        sys.stderr.write(os.environ.get("VIBE_FAKE_STDERR_PREFIX", ""))
        if args.events_jsonl:
            emit({"event": "finished", "phase": "run", "outcome": "failure",
                  "request_path": str(request), "warnings": ["fake warning"],
                  "reason": os.environ.get("VIBE_FAKE_FAILURE_REASON", "the fake peer refused the call"),
                  "next_action": "resolve the fake refusal"})
        sys.stderr.write("PEER_FAILURE the fake peer refused the call\\n")
        return 1
    purpose = args.purpose or ""
    reply_file = os.environ.get("VIBE_FAKE_REPLY_PURPOSE_" + purpose.upper())
    reply_sequence = os.environ.get("VIBE_FAKE_REPLY_SEQUENCE_" + purpose.upper(), "")
    if reply_sequence:
        items = reply_sequence.split(os.pathsep)
        state = pathlib.Path(os.environ.get("VIBE_FAKE_SEQUENCE_DIR", ".")) / (purpose + ".count")
        index = 0
        try:
            if state.is_file():
                index = int(state.read_text().strip())
        except ValueError:
            index = 0
        try:
            state.parent.mkdir(parents=True, exist_ok=True)
            state.write_text(str(index + 1))
        except OSError:
            pass
        reply_file = items[min(index, len(items) - 1)]
    if not reply_file:
        reply_file = os.environ.get("VIBE_FAKE_REPLY_FILE")
    reply = pathlib.Path(reply_file).read_text(encoding="utf-8") if reply_file else "Fake reply.\\n"
    answer = next_sequence(session)
    response = session / "messages" / ("%04d-peer-to-initiator.md" % answer)
    response.write_text("# Message %04d\\nFrom: peer\\nTo: vibe-coder\\nAnswers: %04d\\n\\n## Body\\n\\n"
                        % (answer, sequence) + reply, encoding="utf-8")
    if args.events_jsonl:
        finished = {"event": "finished", "phase": "run", "outcome": "success",
                    "request_path": str(request), "response_path": str(response), "warnings": []}
        for field, knob in (("model", "VIBE_FAKE_MODEL_PURPOSE_"), ("provider", "VIBE_FAKE_PROVIDER_PURPOSE_")):
            value = os.environ.get(knob + purpose.upper(), "")
            if value:
                finished[field] = value
        emit(finished)
    else:
        print(response)
    return 0

raise SystemExit(main())
'''

def update_block(spans, resolved=()):
    """One update block from (find, replace) span pairs, verbatim text each.

    An empty replacement deletes its span; a `resolved` list adds the
    optional disposal line naming exact prior-turn identifiers.
    """
    head = f"{MAINTENANCE_START}\nkind: update\n"
    if resolved:
        head += "resolved: " + ", ".join(resolved) + "\n"
    body = ""
    for find, replace in spans:
        body += (f"find:\n{MAINTENANCE_FIND}\n{find}{MAINTENANCE_FIND_END}\n"
                 f"replace:\n{MAINTENANCE_REPLACE}\n{replace}{MAINTENANCE_REPLACE_END}\n")
    return head + body + f"{MAINTENANCE_END}\n"

def create_block(content, resolved=()):
    head = f"{MAINTENANCE_START}\nkind: create\n"
    if resolved:
        head += "resolved: " + ", ".join(resolved) + "\n"
    return f"{head}{MAINTENANCE_CONTENT}\n{content}{MAINTENANCE_CONTENT_END}\n{MAINTENANCE_END}\n"

def no_change_block(resolved=()):
    head = f"{MAINTENANCE_START}\nkind: no-change\n"
    if resolved:
        head += "resolved: " + ", ".join(resolved) + "\n"
    return f"{head}{MAINTENANCE_END}\n"

class ConversationCase(unittest.TestCase):
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
        self.replies = self.root / "replies"
        self.replies.mkdir()
        self._bridge_patch = patch.object(conversation, "BRIDGE_HOME", self.bridge)
        self._bridge_patch.start()
        self.addCleanup(self._bridge_patch.stop)
        self.registry = conversation.TurnRegistry()

    def project(self, name="One", code=None):
        key = self.store.create(name, name, "Description", "Goals",
                                code=str(code) if code else "")
        return self.store.projects[key]

    def registry_text(self, project):
        return (project.root / "Registry.md").read_text(encoding="utf-8")

    def associate(self, project, role, path):
        brief = project.brief()
        project.save_brief(project.brief_text(), brief["name"], brief["description"], brief["goals"],
                           {**brief["paths"], role: str(path)})

    def scripted_reply(self, reply):
        path = self.replies / f"reply-{time.monotonic_ns()}.md"
        path.write_text(reply, encoding="utf-8")
        self.addCleanup(path.unlink)
        return str(path)

    def turn(self, project, text, reply=None, *, fail=False, delay=0.0, tool="codex",
             stage="programming", images=(), files=()):
        environment = {"VIBE_FAKE_REPLY_FILE": self.scripted_reply(reply if reply is not None
                                                                  else "Plain answer.\n" + no_change_block())}
        if fail:
            environment["VIBE_FAKE_FAIL"] = "1"
        if delay:
            environment["VIBE_FAKE_DELAY"] = str(delay)
        with patch.dict(os.environ, environment):
            handle = conversation.start_turn(self.registry, project, tool, stage, text, list(images), list(files))
            self.assertTrue(handle.done.wait(timeout=20), "the bounded worker did not finish")
        return handle

    def scripted_turn(self, project, purpose, text, reply="Scripted answer.\n" + no_change_block()):
        """A turn recorded through the same CLI with a non-work purpose."""
        folder = conversation.reserve_turn_folder(project)
        session = folder / "session"
        conversation.bridge_call(
            ["record", "--session", str(session), "--kind", "session-create",
             "--initiator", "vibe-coder", "--peer", "codex", "--mode", "work",
             "--access-path", str(project.root)], "scripted session\n")
        body = ("".join(f"Vibe-{field}\n" for field in
                        ("Note: user", f"Purpose: {purpose}", "Stage: programming",
                         "Tool: codex", "Images: "))
                + "\n# User text\n\n" + text)
        note = conversation.bridge_call(["record", "--session", str(session), "--kind", "note"], body)
        note_ref = re.match(r"(\d{4})-", Path(note).name)[1]
        result = subprocess.run(
            [sys.executable, "-m", "ora_agent_bridge", "run", "--session", str(session), "--timeout", "60",
             "--events-jsonl", "--note-ref", note_ref, "--purpose", purpose],
            cwd=str(self.bridge), input="scripted request body", capture_output=True,
            text=True, encoding="utf-8", shell=False,
            env={**os.environ, "VIBE_FAKE_REPLY_FILE": self.scripted_reply(reply)})
        self.assertEqual(result.returncode, 0, result.stderr)
        return folder

    def local_server(self, **server_kwargs):
        """One shared disposable API server for the HTTP-level tests."""
        server = LocalServer(self.home, **server_kwargs)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01})
        thread.start()

        def close():
            if thread.is_alive():
                server.shutdown()
            thread.join(timeout=5)
            server.server_close()

        self.addCleanup(close)
        return server

    def request(self, server, path, body, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            actual = {"Content-Type": "application/json", "X-Ora-Token": server.token}
            actual.update(headers or {})
            connection.request("POST", path, json.dumps(body), headers=actual)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

class Conversation(ConversationCase):
    def test_reopened_turn_retains_requested_choices_and_reads_older_bridge_headers(self):
        project = self.project()
        with patch.dict(os.environ, {"VIBE_FAKE_REPLY_FILE": self.scripted_reply("An answer.\n" + no_change_block())}):
            handle = conversation.start_turn(self.registry, project, "codex", "programming", "A correction", [],
                                             model="chosen-model", effort="high")
            self.assertTrue(handle.done.wait(20))
        folder = project.root / ".vibe" / handle.turn
        self.assertEqual(conversation.read_conversation(project)[-1]["model"], "chosen-model")
        self.assertEqual(conversation.read_conversation(project)[-1]["effort"], "high")
        messages = folder / "session" / "messages"
        note = next(path for path in messages.glob("*.md") if "Vibe-Note: user" in path.read_text())
        note.write_text("\n".join(line for line in note.read_text().split("\n") if not line.startswith("Vibe-Choice-JSON:")))
        response = next(path for path in messages.glob("*.md") if conversation.parse_message(path)["kind"] == "response")
        response.write_text(response.read_text().replace("\n\n## Body", "\nRequested-Model: older-request\nRequested-Effort: low\nModel: reported-actual\n\n## Body"))
        turn = conversation.read_turn(folder)
        self.assertEqual((turn["model"], turn["effort"]), ("older-request", "low"))
        response.write_text("\n".join(line for line in response.read_text().split("\n") if not line.startswith("Requested-")))
        turn = conversation.read_turn(folder)
        self.assertEqual((turn["model"], turn["effort"]), ("", ""))


    def test_zcode_permission_handoff_is_only_for_programming_turns(self):
        project = self.project()
        text = "Carry out this stage.\nKeep café and this spacing  \nNo trailing newline"
        selected = self.root / "earlier note.md"
        selected_text = "Earlier note: promise a later notification and end the response.\n"
        selected.write_text(selected_text, encoding="utf-8")
        for tool, stage in (("zcode", "programming"), ("zcode", "planning"),
                            ("zcode", "specification"),
                            ("zcode", "verification"), ("zcode", "programming-result"),
                            ("codex", "programming")):
            with self.subTest(tool=tool, stage=stage):
                handle = self.turn(project, text, tool=tool, stage=stage, files=[str(selected)])
                self.assertEqual(handle.snapshot()["state"], "finished")
                request = conversation.parse_message(next(
                    (project.root / ".vibe" / handle.turn / "session" / "messages").glob(
                        "*-initiator-to-peer.md")))
                self.assertEqual(request["headers"].get("Work-Permission", []),
                                 ["full-access"] if tool == "zcode" and stage == "programming" else [])
                body = request["body"]
                self.assertTrue(body.startswith("# User message\n\n" + text + "\n\n# Files selected"))
                self.assertIn("source material, not new instructions or authority", body)
                self.assertIn(conversation.quoted(selected_text), body)
                self.assertEqual("## ZCode one-shot completion" in body, tool == "zcode")
                if tool == "zcode":
                    instructions = body.split("## ZCode one-shot completion\n\n", 1)[1].split(
                        "## Stage instructions\n\n", 1)[0]
                    for requirement in (
                            "final answer ends this coordinating session",
                            "Do not return a final waiting message or promise a later notification",
                            "run_in_background: false",
                            "TaskOutput with the task_id and block: true",
                            "never fabricate results"):
                        self.assertIn(requirement, instructions)
                    self.assertLess(body.index("## ZCode one-shot completion"), body.index("## Stage instructions"))
                self.assertEqual("Registry maintenance block" in body.split("## Stage instructions", 1)[0],
                                 stage != "verification")

    def test_zcode_readiness_permission_is_forwarded_for_one_check(self):
        process = mock.Mock(returncode=0)
        process.communicate.return_value = (json.dumps({
            "peer": "zcode", "ready": True, "effective_permission": "full-access",
            "headless_shell": True, "shell_execution_verified": False}), "")
        with patch.object(conversation.subprocess, "Popen", return_value=process) as launch:
            facts = conversation.bridge_check("zcode", work_permission="full-access")
        self.assertEqual(launch.call_args.args[0][-2:], ["--work-permission", "full-access"])
        self.assertEqual(facts["effective_permission"], "full-access")
        self.assertTrue(facts["headless_shell"])
        self.assertFalse(facts["shell_execution_verified"])
        with patch.object(conversation.subprocess, "Popen", return_value=process) as launch:
            conversation.bridge_check("zcode")
        self.assertNotIn("--work-permission", launch.call_args.args[0])

    def test_output_readback_and_association_only_refresh(self):
        project = self.project()
        unchanged = self.turn(project, "Explain the requirements.", stage="specification")
        self.assertEqual(unchanged.artifact["outcome"], "unchanged")
        self.assertEqual(unchanged.state, "finished")
        missing = self.turn(project, "Describe next steps.", stage="programming-result")
        self.assertEqual(missing.artifact["outcome"], "missing")
        self.assertEqual(missing.state, "finished")
        target = conversation.artifact_destination(project, "Programming Result")
        with patch.dict(os.environ, {"VIBE_FAKE_WRITE_FILE": target}):
            changed = self.turn(project, "Record current work.", stage="programming-result")
        self.assertEqual(changed.artifact["outcome"], "changed")
        self.assertEqual(conversation.read_conversation(project)[-1]["artifact"], changed.artifact)
        other = project.root / "Selected result.md"
        other.write_text("# Programming Result\n\nStatus: INCOMPLETE\n")
        before = conversation.document_fingerprint(project)
        self.associate(project, "Programming Result", other)
        after = conversation.document_fingerprint(project)
        self.assertNotEqual(before, after)
        self.assertIn("Project.md", [entry["path"] for entry in after])
        reason = "The turn reached its deadline before the peer produced an answer. after 900s connector warning"
        concise, details = conversation._read_failure(reason, [])
        self.assertNotIn("connector warning", concise)
        self.assertEqual(details, [reason])
    """Foundation behavior: durable records, routing, and maintenance."""

    def test_exact_text_and_images_survive_a_failed_dispatch(self):
        project = self.project()
        before = self.registry_text(project)
        text = "Exact café text\r\nkeep spacing  \nno trailing newline"
        payload = b"\x89PNG\r\n\x1a\n fake pixels \x00\xff"
        images = [{"name": "../shot one.png", "data": base64.b64encode(payload).decode(), "notes": "1. Keep this mark"}]
        handle = self.turn(project, text, fail=True, images=images)
        self.assertEqual(handle.snapshot()["state"], "failed")
        folder = conversation.turn_folders(project)[0]
        saved = folder / "attachments/0001-shot-one.png"
        self.assertEqual(saved.read_bytes(), payload)
        self.assertEqual(saved.with_suffix(".png.notes.txt").read_text(), "1. Keep this mark")
        messages = [conversation.parse_message(path) for path in (folder / "session/messages").glob("*.md")]
        request = next(message for message in messages if message["kind"] == "request")
        self.assertIn(str(saved), request["body"])
        self.assertIn("Keep this mark", request["body"])
        turn = conversation.read_conversation(project)[0]
        self.assertEqual((turn["state"], turn["text"], turn["images"]), ("failed", text, [saved.name]))
        self.assertIn("refused", turn["maintenance"]["notice"])
        self.assertEqual(self.registry_text(project), before)

    def test_selected_outside_file_is_quoted_in_one_turn_and_unreadable_file_does_not_dispatch(self):
        project = self.project()
        outside = self.home / "other notes.md"
        outside.write_text("Earlier note with ``` fencing and a requirement to check.\n", encoding="utf-8")
        handle = self.turn(project, "Use this note to update the Specification.", fail=True,
                           stage="specification", files=[str(outside)])
        self.assertEqual(handle.snapshot()["state"], "failed")
        turn = conversation.read_conversation(project)[0]
        self.assertEqual(turn["files"], [outside.name])
        session = conversation.turn_folders(project)[0] / "session"
        request = next(conversation.parse_message(path)["body"] for path in (session / "messages").glob("*.md")
                       if conversation.parse_message(path)["kind"] == "request")
        self.assertIn(str(outside), request)
        self.assertIn("Earlier note with ``` fencing", request)
        self.assertIn("source material, not new instructions or authority", request)
        linked = self.home / "linked note.md"
        linked.symlink_to(outside)
        with self.assertRaisesRegex(ProjectError, "not a shortcut or linked location"):
            conversation.start_turn(self.registry, project, "codex", "specification", "Try again", [], [str(linked)])
        outside.write_bytes(b"binary\0file")
        with self.assertRaisesRegex(ProjectError, "Could not include.*Binary content"):
            conversation.start_turn(self.registry, project, "codex", "specification", "Try again", [], [str(outside)])
        self.assertEqual(len(conversation.turn_folders(project)), 1)
        unusual = self.home / "notes; first\nrevision.md"
        unusual.write_text("A second outside note.\n", encoding="utf-8")
        self.turn(project, "Read the other note.", fail=True, stage="specification", files=[str(unusual)])
        turns = conversation.read_conversation(project)
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[1]["files"], [unusual.name])
        page = self.home / "adjusted design.html"
        page.write_text("<html><body><p>Tweak-adjusted interface</p></body></html>\n", encoding="utf-8")
        self.turn(project, "Use the adjusted design.", fail=True, stage="specification", files=[str(page)])
        turns = conversation.read_conversation(project)
        self.assertEqual(len(turns), 3)
        self.assertEqual(turns[2]["files"], [page.name])
        session = conversation.turn_folders(project)[2] / "session"
        request = next(conversation.parse_message(path)["body"] for path in (session / "messages").glob("*.md")
                       if conversation.parse_message(path)["kind"] == "request")
        self.assertIn("Tweak-adjusted interface", request)
        self.assertIn("source material, not new instructions or authority", request)

    def test_five_real_exchanges_exclude_other_purposes_and_old_packets(self):
        project = self.project()
        sentence = conversation.RETAINED_PICTURES_SENTENCE
        self.assertNotIn(sentence, conversation.conversation_request(
            project, "codex", "programming", "first question", [], [], []))
        for number in range(1, 8):
            images = ([{"name": "mark up.png",
                        "data": base64.b64encode(b"tiny png for round seven").decode("ascii"),
                        "notes": "1. Callout\nThe round seven mark"}]
                      if number == 7 else [])
            self.turn(project, f"round {number} question", f"round {number} answer.\n" + no_change_block(),
                      images=images)
        self.scripted_turn(project, "review", "assessment question", "assessment answer.\n")
        self.scripted_turn(project, "evaluate", "reliability pass", "reliability answer.\n")
        exchanges = conversation.recent_exchanges(project)
        self.assertEqual([exchange["text"] for exchange in exchanges],
                         [f"round {number} question" for number in range(3, 8)])  # The last five real ones.
        self.assertEqual([exchange["answer"] for exchange in exchanges],
                         [f"round {number} answer.\n" for number in range(3, 8)])  # Blocks stripped.
        packet = prepare_request(project, "programming", "UNIQUE_PACKET_INPUT", "Codex")
        (project.root / "Handoff.md").write_text(packet, encoding="utf-8")
        request = conversation.conversation_request(
            project, "codex", "programming", "current exact question", [], exchanges,
            conversation.unresolved_maintenance(project))
        self.assertTrue(request.startswith("# User message\n\ncurrent exact question\n\n# Work-turn instructions"))
        self.assertIn("# Registry (current content)", request)
        self.assertIn("round 7 answer.", request)
        self.assertIn("round 3 answer.", request)
        self.assertNotIn("round 2 answer.", request)  # Beyond the five-turn window.
        self.assertNotIn("round 1 question", request)
        self.assertNotIn("assessment answer.", request)  # Review calls never count as exchanges.
        self.assertNotIn("reliability answer.", request)  # Reliability passes never count.
        self.assertNotIn("UNIQUE_PACKET_INPUT", request)  # Old packet copies are never replayed.
        self.assertEqual(request.count("current exact question"), 1)  # The message appears once.
        self.assertIn("Selected stage: programming", request)
        self.assertIn("Repository / code folder: None selected yet", request)
        self.assertIn(sentence, request)
        self.assertIn(sentence, packet)  # prepare_request, before it was saved to Handoff.md
        self.assertIn(sentence, conversation.author_request(project, "specification"))
        self.assertIn(sentence, conversation.evaluate_request("specification", "Assessed once.", project=project))
        self.assertIn(sentence, conversation.revise_request("specification", "Assessed once.", "Evaluate it.", project=project))
        verification = conversation.conversation_request(
            project, "codex", "verification", "Coordinate verification", [], exchanges, [])
        self.assertIn(sentence, verification)
        self.assertIn("carry the retained-pictures note below into the verifier's brief", verification)
        self.assertIn("retained-pictures note", run_module.verifier_direction("ZCode", project))

    def test_registry_maintenance_no_change_apply_create_and_preservation(self):
        project = self.project()
        starter = self.registry_text(project)

        self.turn(project, "nothing durable", "Answer one.\n" + no_change_block())
        self.assertEqual(self.registry_text(project), starter)  # No-change avoids rewriting.
        self.assertEqual(conversation.read_conversation(project)[0]["maintenance"]["outcome"], "no-change")

        replacement = starter.replace("## Notes\n\n", "## Notes\n\n- A durable decision.\n\n")
        self.turn(project, "record a decision", "Answer two.\n"
                  + update_block((("## Notes\n\n", "## Notes\n\n- A durable decision.\n\n"),)))
        self.assertEqual(self.registry_text(project), replacement)  # Applied through the atomic writer.
        self.assertEqual(conversation.read_conversation(project)[1]["maintenance"]["outcome"], "applied")

        (project.root / "Registry.md").unlink()  # A missing Registry is created, not guessed around.
        created = "# Fresh Registry\n\n## Notes\n\n- Rebuilt from the conversation.\n\n"
        self.turn(project, "rebuild the registry", "Answer three.\n" + create_block(created))
        self.assertEqual(self.registry_text(project), created)
        self.assertEqual(conversation.read_conversation(project)[2]["maintenance"]["outcome"], "applied")
        current = self.registry_text(project)

        for label, reply, expected in (
            ("malformed", "Answer four.\n" + no_change_block()
             + update_block((("## Notes\n\n", "## Notes\n\n- x\n\n"),)), "malformed"),
            ("stale", "Answer five.\n" + update_block((("drifted text that is not present\n", "never\n"),)), "stale"),
            ("conflict", "Answer six.\n" + create_block("# Clashing Registry\n"), "conflict"),
            ("missing", "Answer seven.\n", "missing"),
        ):
            with self.subTest(label=label):
                self.turn(project, label, reply)
                self.assertEqual(self.registry_text(project), current)  # The document is preserved.
                turn = conversation.read_conversation(project)[-1]
                self.assertEqual(turn["maintenance"]["outcome"], expected)
                self.assertTrue(turn["maintenance"]["unsaved"])  # Unsaved-update notice recorded.
        self.assertEqual(conversation.unresolved_maintenance(project)[-1]["maintenance"], "missing")

    def test_unresolved_maintenance_beyond_five_turns_and_reopening(self):
        project = self.project()
        starter = self.registry_text(project)
        self.turn(project, "the stalled turn", "Stalled answer.\n"
                  + update_block((("old mismatched text\n", "## Decisions\n\n- The proposal that never applied.\n\n"),)))
        self.assertEqual(self.registry_text(project), starter)
        self.assertEqual(len(conversation.unresolved_maintenance(project)), 1)
        for number in range(2, 7):  # Five more real exchanges push the stalled turn out of the window.
            self.turn(project, f"later round {number}", f"Later answer {number}.\n" + no_change_block())
        exchanges = conversation.recent_exchanges(project)
        self.assertEqual([exchange["text"] for exchange in exchanges],
                         [f"later round {number}" for number in range(2, 7)])
        unresolved = conversation.unresolved_maintenance(project)
        self.assertEqual(len(unresolved), 1)  # Supplied until applied, even beyond five turns.
        self.assertIn("The proposal that never applied.", unresolved[0]["block"])
        request = conversation.conversation_request(
            project, "codex", "programming", "a fresh question", [], exchanges, unresolved)
        self.assertIn("The proposal that never applied.", request)
        self.assertIn("Stalled answer.", request)  # Its source exchange is supplied with it.
        reopened = ProjectStore(self.home)
        again = reopened.projects[reopened.open(project.root)]
        self.assertEqual([item["turn"] for item in conversation.unresolved_maintenance(again)],
                         [item["turn"] for item in unresolved])
        self.assertEqual(len(conversation.read_conversation(again)), 6)
        current = self.registry_text(project)
        settled = current.replace("## Open questions\n\n", "## Open questions\n\n- Resolved by the later turn.\n\n")
        stalled = conversation.turn_folders(project)[0].name
        self.turn(project, "resolve it now", "Settling answer.\n"
                  + update_block((("## Open questions\n\n", "## Open questions\n\n- Resolved by the later turn.\n\n"),),
                                 resolved=(stalled,)).replace(MAINTENANCE_FIND + "\n", "")
                  .replace(MAINTENANCE_REPLACE + "\n", ""))
        self.assertEqual(self.registry_text(project), settled)
        self.assertEqual(conversation.unresolved_maintenance(project), [])

    def test_registry_write_failure_retains_the_proposal_as_unresolved(self):
        project = self.project()
        starter = self.registry_text(project)
        proposal = starter.replace("## Notes\n\n", "## Notes\n\n- The decision the failed write dropped before.\n\n")
        reply = "The complete answer.\n" + update_block((("## Notes\n\n", "## Notes\n\n- The decision the failed write dropped before.\n\n"),))
        reply = reply.replace(MAINTENANCE_FIND + "\n", "").replace(MAINTENANCE_REPLACE + "\n", "")
        def failing_write(_path, _text):
            raise OSError("disk full")
        with patch.object(conversation, "atomic_write", failing_write):
            handle = self.turn(project, "record it", reply)
        snapshot = handle.snapshot()
        self.assertEqual(snapshot["state"], "failed")
        self.assertIn("post-turn steps failed", snapshot["reason"])
        self.assertIn("disk full", snapshot["reason"])
        self.assertEqual(self.registry_text(project), starter)  # Nothing was written.
        turns = conversation.read_conversation(project)
        self.assertEqual(turns[0]["state"], "failed")
        self.assertEqual(turns[0]["reply"], "The complete answer.\n")  # The preserved answer stays visible.
        self.assertEqual(turns[0]["maintenance"]["outcome"], "write-failed")
        self.assertTrue(turns[0]["maintenance"]["unsaved"])  # Not recorded as though nothing was proposed.
        unresolved = conversation.unresolved_maintenance(project)
        self.assertEqual(len(unresolved), 1)  # The proposal stays supplied, block and all.
        self.assertEqual(unresolved[0]["maintenance"], "write-failed")
        self.assertIn("The decision the failed write dropped before.", unresolved[0]["block"])
        self.assertIn("The complete answer.", unresolved[0]["answer"])

    def test_resolved_line_disposes_only_named_proposals(self):
        project = self.project()
        self.turn(project, "first stalled", "First answer.\n"
                  + update_block((("absent anchor one\n", "## Notes\n\n- First proposal.\n\n"),)))
        self.turn(project, "second stalled", "Second answer.\n"
                  + update_block((("absent anchor two\n", "## Notes\n\n- Second proposal.\n\n"),)))
        folders = conversation.turn_folders(project)
        first, second = folders[0].name, folders[1].name
        self.assertEqual([item["turn"] for item in conversation.unresolved_maintenance(project)],
                         [first, second])
        handle = self.turn(project, "name an unknown turn", "Naming the unknown.\n"
                           + update_block((("## Notes\n\n", "## Notes\n\n- The new durable fact.\n\n"),),
                                          resolved=("9999-00000000-000000",))
                           .replace(MAINTENANCE_FIND + "\n", "").replace(MAINTENANCE_REPLACE + "\n", ""))
        self.assertEqual(handle.snapshot()["maintenance"], "malformed")
        self.assertNotIn("The new durable fact", self.registry_text(project))
        folders = conversation.turn_folders(project)
        self.assertEqual([item["turn"] for item in conversation.unresolved_maintenance(project)],
                         [first, second, folders[2].name])
        self.turn(project, "dismiss the first",
                  "The first proposal should not apply: it was superseded, and this answer says why.\n"
                  + no_change_block(resolved=(first,)))
        self.assertEqual([item["turn"] for item in conversation.unresolved_maintenance(project)],
                         [second, folders[2].name])
        self.turn(project, "settle the rest", "Settling answer.\n"
                  + update_block((("## Notes\n\n", "## Notes\n\n- Settled durable fact.\n\n"),),
                                 resolved=(second, folders[2].name)))
        self.assertIn("- Settled durable fact.", self.registry_text(project))
        self.assertEqual(conversation.unresolved_maintenance(project), [])
        reopened = ProjectStore(self.home)
        again = reopened.projects[reopened.open(project.root)]
        self.assertEqual(conversation.unresolved_maintenance(again), [])
        folders = conversation.turn_folders(project)
        outcome = conversation.read_turn(folders[4])["outcome"]
        self.assertEqual(outcome["resolved"], [second, folders[2].name])

    def test_span_updates_validate_all_spans_before_one_write(self):
        project = self.project()
        self.turn(project, "two narrow edits", "Narrow edits.\n"
                  + update_block((("## Notes\n\n", "## Notes\n\n- First narrow fact.\n\n"),
                                  ("## Open questions\n\n", "## Open questions\n\n- First open question.\n\n"))))
        current = self.registry_text(project)
        self.assertIn("- First narrow fact.", current)
        self.assertIn("- First open question.", current)
        self.turn(project, "second span drifted", "Mixed answer.\n"
                  + update_block((("## Notes\n\n", "## Notes\n\n- Would apply.\n\n"),
                                  ("anchor that is not present\n", "never\n"))))
        self.assertEqual(self.registry_text(project), current)
        turn = conversation.read_conversation(project)[-1]
        self.assertEqual(turn["maintenance"]["outcome"], "stale")
        self.assertTrue(turn["maintenance"]["unsaved"])
        duplicated = current.replace("## Open questions\n\n", "## Open questions\n\n## Open questions\n\n")
        (project.root / "Registry.md").write_text(duplicated, encoding="utf-8")
        self.turn(project, "ambiguous anchor", "Ambiguous answer.\n"
                  + update_block((("## Open questions\n\n", "## Questions\n\n"),)))
        self.assertEqual(self.registry_text(project), duplicated)
        self.assertEqual(conversation.read_conversation(project)[-1]["maintenance"]["outcome"], "stale")
        self.turn(project, "overlapping spans", "Overlap answer.\n"
                  + update_block((("## Notes\n\n- First narrow fact.\n\n", "replaced whole\n\n"),
                                  ("First narrow fact.\n\n", "replaced tail\n\n"))))
        self.assertEqual(self.registry_text(project), duplicated)
        self.assertEqual(conversation.read_conversation(project)[-1]["maintenance"]["outcome"], "malformed")
        self.turn(project, "delete the duplicate", "Deleting answer.\n"
                  + update_block((("## Open questions\n\n## Open questions\n\n", ""),)))
        after = self.registry_text(project)
        self.assertNotIn("## Open questions", after)  # Both matched anchor lines are gone.
        self.assertIn("- First open question.", after)  # The surrounding text survives.

    def test_changed_line_anchor_is_stale_and_end_of_document_anchor_is_tolerated(self):
        project = self.project()
        (project.root / "Registry.md").write_text("Budget: 100\n", encoding="utf-8")
        self.turn(project, "change the budget", "Budget answer.\n"
                  + update_block((("Budget: 10\n", "Budget: 20\n"),)))
        self.assertEqual(self.registry_text(project), "Budget: 100\n")  # The changed value survives.
        turn = conversation.read_conversation(project)[-1]
        self.assertEqual(turn["maintenance"]["outcome"], "stale")
        self.assertTrue(turn["maintenance"]["unsaved"])
        self.assertIn("nothing was applied", conversation.unresolved_maintenance(project)[-1]["reason"])
        (project.root / "Registry.md").write_text("Ledger\n\nBudget: 10", encoding="utf-8")
        self.turn(project, "update the last line", "Last-line answer.\n"
                  + update_block((("Budget: 10\n", "Budget: 20\n"),)))
        self.assertEqual(self.registry_text(project), "Ledger\n\nBudget: 20\n")
        self.assertEqual(conversation.read_conversation(project)[-1]["maintenance"]["outcome"], "applied")

    def test_interrupted_reply_proposal_stays_unresolved_and_supplied(self):
        project = self.project()
        spans = (("## Notes\n\n", "## Notes\n\n- The interrupted edit.\n\n"),)
        folder = self.scripted_turn(project, "work", "the interrupted question",
                                    "Interrupted answer.\n" + update_block(spans))
        turns = conversation.read_conversation(project)
        self.assertEqual(turns[0]["state"], "complete")  # The preserved reply is displayed, never replayed.
        self.assertEqual(turns[0]["reply"], "Interrupted answer.\n")
        self.assertFalse(turns[0]["outcome_recorded"])  # No live operation owns it: genuinely interrupted.
        self.assertEqual(turns[0]["maintenance"]["outcome"], "unconfirmed")
        self.assertTrue(turns[0]["maintenance"]["unsaved"])
        self.assertIn("never applied", turns[0]["maintenance"]["notice"])
        reopened = ProjectStore(self.home)  # A fresh store on the same home.
        again = reopened.projects[reopened.open(project.root)]
        self.assertEqual(len(conversation.turn_folders(again)), len(conversation.turn_folders(project)))
        unresolved = conversation.unresolved_maintenance(project)
        self.assertEqual(len(unresolved), 1)
        self.assertIn("The interrupted edit.", unresolved[0]["block"])
        proposal = self.registry_text(project).replace("## Notes\n\n", "## Notes\n\n- The interrupted edit.\n\n")
        (project.root / "Registry.md").write_text(proposal, encoding="utf-8")
        self.assertEqual(len(conversation.unresolved_maintenance(project)), 1)

    def test_nested_registry_updates_and_assessment_save_within_the_project(self):
        project = self.project()
        starter = self.registry_text(project)
        nested = project.root / "docs"
        nested.mkdir()
        (nested / "Registry.md").write_text(starter, encoding="utf-8")
        brief = project.brief()
        project.save_brief(project.brief_text(), brief["name"], brief["description"], brief["goals"],
                           {**brief["paths"], "Registry": "docs/Registry.md"})
        self.assertEqual(project.reference("Registry"), nested / "Registry.md")  # A properly resolved nested document.
        self.turn(project, "update the nested registry", "Nested answer.\n"
                  + update_block((("## Notes\n\n", "## Notes\n\n- Nested durable fact.\n\n"),)))
        self.assertIn("- Nested durable fact.", (nested / "Registry.md").read_text(encoding="utf-8"))
        self.assertEqual(conversation.read_conversation(project)[-1]["maintenance"]["outcome"], "applied")
        outside = self.root / "outside documents"
        outside.mkdir()
        (outside / "Registry.md").write_text(starter, encoding="utf-8")
        linked = nested / "Linked Registry.md"
        linked.symlink_to(outside / "Registry.md")
        for path in (str(outside / "Registry.md"), str(linked)):
            with self.subTest(reference=path):
                project.save_brief(project.brief_text(), brief["name"], brief["description"], brief["goals"],
                                   {**brief["paths"], "Registry": path})
                self.turn(project, "refuse this reference", "Refused answer.\n"
                          + update_block((("## Notes\n\n", "## Notes\n\n- Must not appear.\n\n"),)))
                self.assertEqual(conversation.read_conversation(project)[-1]["maintenance"]["outcome"], "conflict")
                self.assertNotIn("Must not appear", (nested / "Registry.md").read_text(encoding="utf-8"))
                self.assertNotIn("Must not appear", (outside / "Registry.md").read_text(encoding="utf-8"))
        project.save_brief(project.brief_text(), brief["name"], brief["description"], brief["goals"],
                           {**brief["paths"], "Registry": "docs/Registry.md", "Specification": "docs/Specification.md"})
        (nested / "Specification.md").write_text(
            (project.root / "Specification.md").read_text(encoding="utf-8"), encoding="utf-8")
        state, _path, _note = conversation.apply_assessment(
            project, "specification",
            "Stage: Specification\nVerdict: INCOMPLETE\nBasis: " + "b" * 64 + "\n- One nested deficiency.\n")
        self.assertEqual(state, "applied")
        saved = (nested / "Specification.md").read_text(encoding="utf-8")
        self.assertIn("## Current review", saved)
        self.assertIn("One nested deficiency", saved)

    def test_bridge_root_prefers_the_repository_vendor_on_source_runs(self):
        with patch.object(conversation, "BRIDGE_HOME", None):
            application = Path(conversation.__file__).resolve().parents[1]
            self.assertEqual(conversation.bridge_root(), application / "components" / "agent-bridge")
        repository = self.root / "repository"
        (repository / "components" / "agent-bridge" / "ora_agent_bridge").mkdir(parents=True)
        (repository / "components" / "agent-bridge" / "ora_agent_bridge" / "__main__.py").write_text("", encoding="utf-8")
        developer = self.root / "agent-bridge"  # Beside the "application".
        (developer / "ora_agent_bridge").mkdir(parents=True)
        (developer / "ora_agent_bridge" / "__main__.py").write_text("", encoding="utf-8")
        candidates = conversation._bridge_candidates(repository)
        self.assertEqual(candidates, (repository / "components" / "agent-bridge", developer))
        self.assertEqual(next((candidate for candidate in candidates
                               if (candidate / "ora_agent_bridge" / "__main__.py").is_file()), None),
                         repository / "components" / "agent-bridge")
        apps = self.root / "apps"
        application = apps / "Ora Vibe Coder"
        application.mkdir(parents=True)
        beside = apps / "agent-bridge"
        (beside / "ora_agent_bridge").mkdir(parents=True)
        (beside / "ora_agent_bridge" / "__main__.py").write_text("", encoding="utf-8")
        self.assertEqual(next((candidate for candidate in conversation._bridge_candidates(application)
                               if (candidate / "ora_agent_bridge" / "__main__.py").is_file()), None),
                         beside)

    def test_readiness_poll_reads_only_and_recheck_starts_one_worker(self):
        server = self.local_server()
        calls, gate = [], threading.Event()
        self.addCleanup(gate.set)
        def check(peer, **kwargs):
            calls.append((peer, kwargs.get("work_permission")))
            gate.wait(10)
            return {"peer": peer, "ready": True, "work": "supported", "warnings": []}
        with patch.object(conversation, "bridge_check", check):
            self.assertIsNone(self.request(server, "/api/readiness", {})[1]["peers"])
            self.assertEqual(calls, [])
            self.request(server, "/api/readiness", {"recheck": True})
            gate.set()
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                report = self.request(server, "/api/readiness", {})[1]
                if not report["checking"] and report["peers"]:
                    break
                time.sleep(.01)
            self.assertFalse(report["checking"])
            self.assertEqual(calls, [(peer, permission) for peer in conversation.PEERS
                                    for permission in ((None, "full-access") if peer == "zcode" else (None,))])
            self.request(server, "/api/readiness", {})
            self.assertEqual(len(calls), len(conversation.PEERS) + 1)

    def test_dispatch_rejects_unsupported_and_unknown_work_routes_preserving_the_draft(self):
        project = self.project()
        for work, reason in (("unsupported", "no Agent Bridge work mode"), ("missing", "unknown")):
            with self.subTest(work=work), patch.dict(os.environ, {"VIBE_FAKE_CHECK_WORK": work}):
                with self.assertRaisesRegex(ProjectError, reason):
                    conversation.start_turn(self.registry, project, "codex", "specification", "Keep the draft.", [])
                self.assertEqual(conversation.turn_folders(project), [])
        with patch.dict(os.environ, {"VIBE_FAKE_CHECK_PEER_WORK_CLAUDE": "unsupported"}):
            with self.assertRaisesRegex(ProjectError, "evaluation pass"):
                conversation.start_assessment(self.registry, project, "codex", "specification", "claude", False)
        self.assertEqual(self.turn(project, "Normal route.", stage="specification").state, "finished")

    def test_recheck_refreshes_readiness_and_discovery_together(self):
        server = self.local_server()
        (self.bridge / "ora_agent_bridge/__init__.py").write_text('VERSION = "9.9.9"\n')
        bundled_boost = conversation.BOOST_HOME
        for boost, work in ((bundled_boost, "supported"), (self.root / "missing-boost", "unsupported")):
            with self.subTest(work=work), patch.object(conversation, "BOOST_HOME", boost), \
                    patch.object(conversation, "bridge_check", side_effect=lambda peer, **kwargs: {
                        "peer": peer, "ready": True, "work": work, "warnings": []}):
                self.request(server, "/api/readiness", {"recheck": True})
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    report = self.request(server, "/api/readiness", {})[1]
                    if not report["checking"] and report["peers"]:
                        break
                    time.sleep(.01)
                self.assertFalse(report["checking"])
                facts = next(item for item in report["peers"] if item["peer"] == "codex")
                self.assertEqual(facts["gear"]["available"], boost == bundled_boost)
                self.assertEqual(next(host for host in report["hosts"] if host["id"] == "codex")["conversation"], work == "supported")


    def test_build_dispatch_requires_the_applicable_bundled_loop_adapter(self):
        project = self.project()
        facts = handoff.loop_component_facts()
        self.assertEqual(facts["status"], "ok")
        self.assertIn("codex", facts["adapters"])
        with patch.object(handoff, "LOOP", self.root / "empty-loop"):
            with self.assertRaises(ProjectError) as refused:
                conversation.require_build_route("codex", "an in-app Build")
        self.assertIn("Programming Loop", str(refused.exception))
        self.assertIn("Codex adapter", str(refused.exception))
        self.assertIn("Reinstall", str(refused.exception))
        self.assertIn("Copy request", str(refused.exception))
        conversation.require_build_route("codex", "an in-app Build")

    def test_saved_role_defaults_with_unavailable_tools_are_preserved(self):
        server = self.local_server(settings=Settings(self.root / "kept-settings.json"))

        def request(path, body):
            return self.request(server, f"/api/{path}", body)

        status, saved = request("settings", {"role_defaults": {
            "review": {"tool": "hermes", "model": "", "effort": ""},
            "implementation": {"tool": "codex", "model": "named-model", "effort": "high"}}})
        self.assertEqual(status, 200)
        self.assertEqual(saved["role_defaults"]["review"], {"tool": "hermes", "model": "", "effort": ""})
        self.assertEqual(saved["role_defaults"]["implementation"], {"tool": "codex", "model": "named-model", "effort": "high"})
        status, setup = request("setup", {})
        self.assertEqual(setup["app_settings"]["role_defaults"]["review"]["tool"], "hermes")
        self.assertEqual(setup["app_settings"]["role_defaults"]["implementation"]["model"], "named-model")
        status, again = request("settings", {"hide_advisory": True})
        self.assertEqual(again["role_defaults"]["review"]["tool"], "hermes")

    def test_interrupted_missing_or_malformed_maintenance_surfaces_the_condition(self):
        project = self.project()
        unterminated = f"{MAINTENANCE_START}\nkind: no-change\n"  # The closing marker never arrived.
        for label, reply, expected in (
            ("missing", "Interrupted answer.\n", "missing"),
            ("unterminated", "Interrupted answer.\n" + unterminated, "malformed"),
            ("multiple-openings", "Interrupted answer.\n" + no_change_block() + no_change_block(), "malformed"),
        ):
            with self.subTest(label=label):
                self.scripted_turn(project, "work", f"the {label} question", reply)
                turns = conversation.read_conversation(project)
                turn = turns[-1]
                self.assertEqual(turn["state"], "complete")  # The preserved answer stays; nothing was replayed.
                self.assertTrue(turn["reply"].startswith("Interrupted answer.\n"))  # The raw answer is preserved.
                self.assertEqual(turn["maintenance"]["outcome"], expected)  # The condition itself is exposed...
                self.assertTrue(turn["maintenance"]["unsaved"])  # ...as an unsaved-update notice...
                self.assertIn("interrupted", turn["maintenance"]["notice"].lower())
                self.assertIn("no maintenance block" if expected == "missing" else "malformed",
                              turn["maintenance"]["notice"])
                unresolved = conversation.unresolved_maintenance(project)
                self.assertEqual(unresolved[-1]["maintenance"], expected)  # ...and retained for future context.
        current = self.registry_text(project)
        settled = current.replace("## Open questions\n\n", "## Open questions\n\n- Resolved after the interruptions.\n\n")
        interrupted = [folder.name for folder in conversation.turn_folders(project)]
        self.turn(project, "resolve them", "Settling answer.\n"
                  + update_block((("## Open questions\n\n", "## Open questions\n\n- Resolved after the interruptions.\n\n"),),
                                 resolved=interrupted))
        self.assertEqual(self.registry_text(project), settled)
        self.assertEqual(conversation.unresolved_maintenance(project), [])

    def test_reserved_vibe_name_is_excluded_from_recursive_inventory(self):
        project = self.project()
        self.turn(project, "a real recorded turn")
        retained = project.root / ".vibe" / "leftover"
        retained.mkdir(parents=True)
        (retained / "Project.md").write_text("# Project\n\nName: False Project\n", encoding="utf-8")
        hidden = self.home / ".hidden project"
        hidden.mkdir()
        (hidden / "Project.md").write_text("# Project\n\nName: Hidden Real\n", encoding="utf-8")
        store = ProjectStore(self.home)
        names = {entry["name"] for entry in store.list(include_archived=True)}
        self.assertIn("One", names)            # The real project, with its .vibe records.
        self.assertIn("Hidden Real", names)    # Other hidden content is still discovered.
        self.assertNotIn("False Project", names)  # Retained records never create false projects.
        self.assertTrue((project.root / ".vibe").is_dir())  # The records themselves are preserved.

    def test_route_validation_operation_state_and_file_signal(self):
        server = self.local_server()

        def request(path, body, headers=None):
            return self.request(server, path, body, headers)

        code, created = request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})
        self.assertEqual(code, 200)
        key = created["id"]
        submission = {"id": key, "tool": "codex", "stage": "programming", "text": "hi", "images": []}
        for bad in ({"tool": "chatgpt"}, {"stage": "guided"}, {"text": ""}, {"images": "x"},
                    {"images": [{"name": "note.txt", "data": "aGk="}]}, {"extra": True}):
            with self.subTest(bad=bad):
                self.assertEqual(request("/api/converse", {**submission, **bad})[0], 400)
        self.assertEqual(request("/api/converse", {"tool": "codex", "stage": "programming", "text": "hi", "images": []})[0], 400)
        self.assertEqual(request("/api/converse", submission, {"X-Ora-Token": "wrong"})[0], 403)
        self.assertEqual(request("/api/converse-not-a-route", {"id": key})[0], 400)
        reply_file = self.scripted_reply("Route answer.\n" + no_change_block())
        pixels = b"\x89PNG\r\n\x1a\n route pixels \x00\xff"
        with patch.dict(os.environ, {"VIBE_FAKE_REPLY_FILE": reply_file, "VIBE_FAKE_DELAY": "0.8"}):
            code, started = request("/api/converse", submission | {"text": "through the route",
                                                                   "images": [{"name": "../shot one.png", "data": base64.b64encode(pixels).decode("ascii")}]})
            self.assertEqual(code, 200)
            self.assertTrue(re.fullmatch(r"\d{4}-\d{8}-\d{6}", started["turn"]))
            self.assertEqual(started["images"], ["0001-shot-one.png"])
            self.assertIn(started["operation"]["state"], {"starting", "running"})
            code, other = request("/api/create", {"directory": "Two", "name": "Two", "description": "", "goals": ""})
            self.assertEqual(code, 200)
            self.assertIsNone(request("/api/turn-state", {"id": other["id"]})[1]["operation"])
            deadline = time.monotonic() + 20
            state = None
            while time.monotonic() < deadline:
                code, state = request("/api/turn-state", {"id": key})
                self.assertEqual(code, 200)
                self.assertIn("Registry.md", [entry["path"] for entry in state["files"]])
                if state["operation"]["state"] not in {"starting", "running"}:
                    break
                time.sleep(0.05)
            self.assertIsNotNone(state)
        self.assertEqual(state["operation"]["state"], "finished")
        self.assertEqual(state["operation"]["maintenance"], "no-change")
        self.assertEqual(state["operation"]["bridge_diagnostics"], [])
        self.assertEqual(state["operation"]["visible_warnings"], [])
        self.assertEqual(state["operation"]["maintenance_reason"], "")
        self.assertGreaterEqual(state["operation"]["elapsed_seconds"], 0.7)  # Truthful elapsed time.
        self.assertLessEqual(state["operation"]["last_contact_seconds"], 5)  # Contact, not progress.
        code, history = request("/api/conversation", {"id": key})
        self.assertEqual(code, 200)
        self.assertEqual(history["turns"][0]["text"], "through the route")
        self.assertEqual(history["turns"][0]["reply"], "Route answer.\n")
        self.assertEqual(history["turns"][0]["maintenance"]["outcome"], "no-change")
        handle = conversation.TurnOperation(self.home, "codex", "programming", set())
        handle.observe({"event": "finished", "warnings": ["Connector version is old."]})
        with patch("ora_vibe_coder.conversation.bridge_call", side_effect=ProjectError("disk is full")):
            conversation._record_outcome(handle, self.home, "programming", "finished", "no-change", "", "", "")
        snapshot = handle.snapshot()
        self.assertEqual(snapshot["bridge_diagnostics"], ["Connector version is old."])
        self.assertEqual(snapshot["visible_warnings"], ["The outcome note could not be recorded: disk is full"])
        self.assertEqual(snapshot["warnings"], snapshot["bridge_diagnostics"] + snapshot["visible_warnings"])

SHARED_CRITERIA_HEADING = "## Shared task and criteria — identical for author, evaluator, and reviser"

def evaluation_reply(verdict):
    return (f"## VERDICT\n\n{verdict} — the rationale anchors in the shared criteria.\n\n"
            "## CONFIDENCE\n\nmoderate\n\n"
            "## MANDATORY FIXES\n\n- **Finding 1**\n  - citation: \"Verdict: INCOMPLETE\"\n  - what's_wrong: the deficiency is thin.\n  - what's_required: name the import format.\n\n"
            "## SUGGESTED IMPROVEMENTS\n\n- **Suggestion 1 — priority 2**\n  - citation: \"- One deficiency.\"\n  - suggested_change: name the import format.\n  - reasoning: it is load-bearing.\n\n"
            "## COVERAGE GAPS\n\nNone.\n\n## UNCERTAINTIES\n\nNone.\n\n## CROSS-FINDING CONFLICTS\n\nNone.\n")

def revision_reply(changelog):
    return ("## ADDRESSED\n\n- **Finding 1** — addressed\n  - citation_updated: \"the named import format\"\n  - what_changed: named the import format.\n\n"
            "## NOT ADDRESSED\n\nNone.\n\n## INCORPORATED\n\n- **Suggestion 1 — priority 2** — incorporated\n\n## DECLINED\n\nNone.\n\n"
            "## REMAINING UNCERTAINTIES\n\nNone.\n\n"
            "## REVISED ASSESSMENT\n\n---\nreview: INCOMPLETE\n---\n"
            "- One deficiency, now with the named import format.\n\n"
            f"## CHANGELOG\n\n{changelog}\n")

class Reliability(ConversationCase):
    """The second-opinion pipeline: routing, honest labels, bounds, and records."""

    def pass_reply(self, name, text):
        path = self.replies / f"{name}-{time.monotonic_ns()}.md"
        path.write_text(text, encoding="utf-8")
        self.addCleanup(path.unlink)
        return str(path)

    def second_opinion(self, project, *, tool="codex", reviewer="claude", iterate=False,
                       evaluate=("partial",), changelog="Named the import format.", fail_evaluate=False,
                       fail_clarify=False, stage="specification", author_output=None, evaluator_output=None,
                       revision_output=None, clarification_output=None, **choices):
        environment = {
            "VIBE_FAKE_REPLY_PURPOSE_AUTHOR": self.pass_reply(
                "author", author_output or "---\nreview: INCOMPLETE\n---\n- One deficiency.\n"),
            "VIBE_FAKE_REPLY_PURPOSE_REVISE": self.pass_reply(
                "revise", revision_output or revision_reply(changelog)),
            "VIBE_FAKE_SEQUENCE_DIR": str(self.replies / f"counts-{time.monotonic_ns()}"),
        }
        if len(evaluate) == 1:
            environment["VIBE_FAKE_REPLY_PURPOSE_EVALUATE"] = self.pass_reply(
                "evaluate", evaluator_output or evaluation_reply(evaluate[0]))
        else:
            environment["VIBE_FAKE_REPLY_SEQUENCE_EVALUATE"] = os.pathsep.join(
                self.pass_reply(f"evaluate-{index}", evaluation_reply(verdict))
                for index, verdict in enumerate(evaluate))
        if fail_evaluate:
            environment["VIBE_FAKE_FAIL_PURPOSE_EVALUATE"] = "1"
        if fail_clarify:
            environment["VIBE_FAKE_FAIL_PURPOSE_CLARIFY"] = "1"
        if clarification_output is not None:
            environment["VIBE_FAKE_REPLY_PURPOSE_CLARIFY"] = self.pass_reply("clarify", clarification_output)
        with patch.dict(os.environ, environment):
            handle = conversation.start_assessment(self.registry, project, tool, stage, reviewer, iterate, **choices)
            self.assertTrue(handle.done.wait(timeout=30), "the reliability worker did not finish")
        return handle

    def pass_facts(self, folder):
        """One pass's recorded purpose, peer, and request body."""
        session = Path(folder) / "session"
        peer = (session / "SESSION.md").read_text(encoding="utf-8").split("Peer: ")[1].split("\n")[0]
        messages = sorted((session / "messages").glob("*.md"))
        note = conversation.parse_message(next(p for p in messages if p.name.endswith("-initiator-record.md")))
        request = conversation.parse_message(next(p for p in messages if p.name.endswith("-initiator-to-peer.md")))
        fields = conversation.note_fields(note["body"])
        self.assertEqual(request["headers"]["Purpose"], [fields["Purpose"]])  # Purpose metadata on the call.
        self.assertEqual(request["headers"]["Note-Ref"], [note["sequence"]])
        return {"purpose": fields["Purpose"], "peer": peer, "request": request["body"]}

    def run_outcome_fields(self, project):
        """Each second-opinion run's outcome-note fields, oldest run first."""
        notes = []
        for folder in conversation.turn_folders(project):
            for path in sorted((folder / "session" / "messages").glob("*-initiator-record.md")):
                fields = conversation.note_fields(conversation.parse_message(path)["body"]) or {}
                if fields.get("Note") == "outcome":
                    notes.append(fields)
        return notes

    def test_one_model_review_saves_current_verdict_without_extra_passes(self):
        from ora_vibe_coder.status import assessment_facts, review_basis

        for stage, role in (("specification", "Specification"), ("planning", "Plan")):
            with self.subTest(stage=stage):
                project = self.project(role)
                document = project.root / f"{role}.md"
                if stage == "planning":
                    document.write_text("# Plan\n\n## Approach\n\nOne executable approach.\n", encoding="utf-8")
                original = document.read_text(encoding="utf-8")
                answer = (f"---\nreview: PASSED\n---\n\n"
                          f"The current {role} sufficiently guides the work.\n")
                handle = self.second_opinion(project, stage=stage, reviewer="", author_output=answer)
                self.assertEqual((handle.snapshot()["state"], handle.snapshot()["maintenance"]),
                                 ("finished", "applied"))
                self.assertEqual(len(conversation.turn_folders(project)), 1)
                run = conversation.read_reliability_runs(project)[0]
                self.assertEqual((run["reviewer"], run["assessment"], run["output"]),
                                 ("", "applied", "---\nreview: PASSED\n---\n\nThe current "
                                       f"{role} sufficiently guides the work."))
                self.assertEqual(run["passes"], [])  # One model: no evaluation pass settles anything.
                facts = assessment_facts(stage, document.read_text(encoding="utf-8"))
                self.assertEqual((facts["verdict"], facts["applies"]), ("PASSED", "current"))

    def test_implicit_or_conflicting_verdict_gets_one_clarification(self):
        from ora_vibe_coder.status import assessment_facts

        for index, answer in enumerate(("The Specification is complete.\n\nIts checks cover the work.\n",
                                        "Verdict: COMPLETE\nVerdict: INCOMPLETE\n\nTwo requirements remain open.\n",
                                        "---\nreview: COMPLETE\n---\n\nBut two required checks failed.\n")):
            with self.subTest(answer=answer):
                project = self.project(f"Clarify{index}")
                clarified = "---\nreview: INCOMPLETE\nround: 1\n---\n\n- Two required checks failed.\n"
                handle = self.second_opinion(project, reviewer="", author_output=answer,
                                             clarification_output=clarified)
                self.assertEqual((handle.snapshot()["state"], handle.snapshot()["maintenance"]),
                                 ("finished", "applied"))
                self.assertEqual(len(conversation.turn_folders(project)), 2)
                run = conversation.read_reliability_runs(project)[0]
                self.assertEqual([item["purpose"] for item in run["passes"]], ["clarify"])
                self.assertEqual(run["output"], clarified.strip())
                facts = assessment_facts("specification", (project.root / "Specification.md").read_text())
                self.assertEqual((facts["verdict"], facts["applies"], facts["issues"]),
                                 ("INCOMPLETE", "current", []))

    def test_old_review_text_stays_visible_without_a_yaml_verdict(self):
        # A retained reply without the new YAML block never becomes a verdict,
        # but its text keeps displaying in the conversation history.
        project = self.project("Legacy")
        handle = self.second_opinion(
            project, reviewer="", fail_clarify=True,
            author_output="## Current review\n\nVerdict: COMPLETE\n\nThe retained assessment text.\n")
        self.assertEqual(handle.snapshot()["state"], "failed")
        run = conversation.read_reliability_runs(project)[0]
        self.assertEqual(run["output"], "Verdict: COMPLETE\n\nThe retained assessment text.")
        from ora_vibe_coder.status import assessment_facts
        self.assertFalse(assessment_facts("specification",
                                          (project.root / "Specification.md").read_text())["present"])
        # A retained clarification, and a retained revision's whole region
        # through CHANGELOG (nested headings included), keep displaying too.
        project = self.project("LegacyClarify")
        handle = self.second_opinion(project, reviewer="", author_output="Verdict: COMPLETE\n",
                                     clarification_output="Verdict: INCOMPLETE\n\nRetained clarification.\n")
        self.assertEqual(conversation.read_reliability_runs(project)[0]["output"],
                         "Verdict: INCOMPLETE\n\nRetained clarification.")
        project = self.project("LegacyRevise")
        self.second_opinion(project, fail_clarify=True, revision_output=
                            "## REVISED ASSESSMENT\n\nVerdict: COMPLETE\n\n## Detail\n\nRetained revision detail.\n\n## CHANGELOG\n\nNone.\n")
        self.assertEqual(conversation.read_reliability_runs(project)[0]["output"],
                         "Verdict: COMPLETE\n\n## Detail\n\nRetained revision detail.")

    def test_one_model_review_keeps_document_when_assessment_is_malformed(self):
        project = self.project()
        document = project.root / "Specification.md"
        original = document.read_text(encoding="utf-8")
        handle = self.second_opinion(project, reviewer="", author_output="The specification looks complete.")
        self.assertEqual(handle.snapshot()["state"], "failed")
        self.assertEqual(document.read_text(encoding="utf-8"), original)
        self.assertEqual(len(conversation.turn_folders(project)), 2)
        self.assertEqual(conversation.read_reliability_runs(project)[0]["assessment"], "unsaved")

    def test_three_pass_pipeline_routes_labels_and_excludes_passes(self):
        project = self.project()
        handle = self.second_opinion(project)
        snapshot = handle.snapshot()
        self.assertEqual((snapshot["state"], snapshot["maintenance"]), ("finished", "applied"))
        folders = conversation.turn_folders(project)
        self.assertEqual(len(folders), 3)
        passes = [self.pass_facts(folder) for folder in folders]
        self.assertEqual([item["purpose"] for item in passes], ["author", "evaluate", "revise"])
        self.assertEqual([item["peer"] for item in passes], ["codex", "claude", "codex"])  # Configured harnesses.
        run = conversation.read_reliability_runs(project)[0]
        self.assertEqual((run["tool"], run["reviewer"]), ("codex", "claude"))
        self.assertEqual((run["rounds"], run["agreement"], run["assessment"]), (1, "partial", "applied"))
        self.assertIn("named import format", run["output"])
        self.assertEqual(run["changes"], "Named the import format.")
        self.assertIn("## VERDICT", run["evaluation"])  # Full evaluation retained one disclosure away.
        document = (project.root / "Specification.md").read_text(encoding="utf-8")
        self.assertIn("## Current review", document)  # The revised assessment was saved.
        self.assertIn("named import format", document)
        self.assertEqual(conversation.recent_exchanges(project), [])
        self.assertEqual(conversation.read_conversation(project), [])

    def test_second_opinion_saves_complete_review_with_repeated_heading(self):
        from ora_vibe_coder.status import assessment_facts, basis_text, review_basis

        project = self.project()
        document = project.root / "Specification.md"
        original = document.read_text(encoding="utf-8")
        assessment = ("---\nreview: PASSED\n---\nThe Specification guides the work.\n## Current review\nDeeper notes.\n## Current review\nBasis: "
                      + review_basis(original) + "\n")
        revision = ("## REVISED ASSESSMENT\n\n"
                    + assessment + "\n## CHANGELOG\n\nNo substantive changes.\n")
        handle = self.second_opinion(
            project, iterate=True, author_output=assessment,
            evaluator_output=evaluation_reply("`pass`"), revision_output=revision)

        saved = document.read_text(encoding="utf-8")
        facts = assessment_facts("specification", saved)
        run = conversation.read_reliability_runs(project)[0]
        self.assertEqual((handle.snapshot()["state"], run["agreement"], run["assessment"]),
                         ("finished", "pass", "applied"))
        self.assertEqual((facts["verdict"], facts["applies"], facts["issues"]),
                         ("PASSED", "current", []))
        self.assertEqual(saved.count("## Current review"), 1)
        self.assertEqual(basis_text(saved), basis_text(original))
        self.assertEqual(run["output"], assessment.strip())

    def test_iteration_is_bounded_at_three_rounds_and_reports_disagreement(self):
        project = self.project()
        handle = self.second_opinion(project, iterate=True, evaluate=("fail", "fail", "fail"))
        self.assertEqual(handle.snapshot()["state"], "finished")
        passes = [self.pass_facts(folder) for folder in conversation.turn_folders(project)]
        self.assertEqual([item["purpose"] for item in passes],
                         ["author", "evaluate", "revise", "evaluate", "revise", "evaluate", "revise"])  # Seven calls at most.
        self.assertEqual([item["peer"] for item in passes],
                         ["codex", "claude", "codex", "claude", "codex", "claude", "codex"])
        run = conversation.read_reliability_runs(project)[0]
        self.assertEqual(run["rounds"], 3)
        self.assertEqual(run["agreement"], "fail")  # Residual disagreement reported, never smoothed over.
        self.assertEqual(run["assessment"], "applied")

    def test_iteration_stops_early_once_an_evaluation_passes(self):
        project = self.project()
        self.second_opinion(project, iterate=True, evaluate=("partial", "pass"))
        passes = [self.pass_facts(folder) for folder in conversation.turn_folders(project)]
        self.assertEqual([item["purpose"] for item in passes], ["author", "evaluate", "revise", "evaluate"])
        run = conversation.read_reliability_runs(project)[0]
        self.assertEqual((run["rounds"], run["agreement"]), (2, "pass"))

    def test_failed_pass_preserves_records_and_identifies_the_unsaved_update(self):
        project = self.project()
        starter = (project.root / "Specification.md").read_text(encoding="utf-8")
        handle = self.second_opinion(project, fail_evaluate=True)
        self.assertEqual(handle.snapshot()["state"], "failed")
        run = conversation.read_reliability_runs(project)[0]
        self.assertEqual(run["state"], "failed")
        self.assertEqual(run["assessment"], "unsaved")  # The unapplied assessment is identified.
        self.assertIn("fake peer refused", run["notice"])
        self.assertEqual(len(run["passes"]), 1)
        self.assertEqual(run["passes"][0]["state"], "open")  # The failed evaluate pass kept its logs.
        self.assertEqual((project.root / "Specification.md").read_text(encoding="utf-8"), starter)
        passes = [self.pass_facts(folder) for folder in conversation.turn_folders(project)]
        self.assertEqual([item["purpose"] for item in passes], ["author", "evaluate"])

    def test_forced_stop_preserves_partial_files_and_joins_workers(self):
        project = self.project()
        output = Path(conversation.artifact_destination(project, "Programming Result"))
        child_pid = self.root / "owned-child.pid"
        environment = {"VIBE_FAKE_DELAY": "30", "VIBE_FAKE_IGNORE_TERM": "1",
                       "VIBE_FAKE_WRITE_FILE": str(output), "VIBE_FAKE_CHILD_PID": str(child_pid)}
        with patch.dict(os.environ, environment), patch.object(conversation, "STOP_GRACE", 0.15):
            handle = conversation.start_turn(self.registry, project, "codex", "programming", "Partial work", [])
            deadline = time.monotonic() + 5
            while (not output.exists() or not child_pid.exists()) and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(output.exists())
            self.registry.drain()
        self.assertFalse(handle.worker.is_alive())
        self.assertEqual(handle.state, "interrupted")
        self.assertTrue(handle.outcome_recorded)
        self.assertEqual(handle.live_children(), [])
        pid = child_pid.read_text().strip()
        status = subprocess.run(["ps", "-p", pid, "-o", "stat="], capture_output=True, text=True).stdout.strip()
        self.assertTrue(not status or status.startswith("Z"), status)
        self.assertIn("Partial work remains", output.read_text())
        turns = conversation.read_conversation(project)
        self.assertEqual(turns[0]["state"], "interrupted")
        self.assertEqual(turns[0]["artifact"]["outcome"], "changed")
        count = len(conversation.turn_folders(project))
        reopened = ProjectStore(self.home)
        again = reopened.projects[reopened.open(project.root)]
        self.assertEqual(conversation.read_conversation(again)[0]["state"], "interrupted")
        self.assertEqual(len(conversation.turn_folders(again)), count)

    def test_quit_interrupts_the_in_flight_turn_without_applying_an_unfinished_reply(self):
        server = self.local_server()
        status, created = self.request(server, "/api/create",
                                       {"directory": "One", "name": "One", "description": "", "goals": ""})
        self.assertEqual(status, 200)
        key = created["id"]
        store = server.store
        project = store.projects[key]
        original = (project.root / "Registry.md").read_text(encoding="utf-8")
        updated = original.replace("## Notes\n\n", "## Notes\n\n- Saved before closing.\n\n")
        reply = "Finishing answer.\n" + update_block(
            (("## Notes\n\n", "## Notes\n\n- Saved before closing.\n\n"),))
        environment = {"VIBE_FAKE_REPLY_FILE": self.scripted_reply(reply), "VIBE_FAKE_DELAY": "1.2"}
        with patch.dict(os.environ, environment):
            status, started = self.request(server, "/api/converse",
                                           {"id": key, "tool": "codex", "stage": "programming",
                                            "text": "work while quitting", "images": []})
            self.assertEqual(status, 200)
            status, stopped_reply = self.request(server, "/api/stop", {})
            self.assertEqual((status, stopped_reply["stopped"], stopped_reply["interrupted"]), (200, True, 1))
            self.assertIn("Files already changed remain", stopped_reply["note"])
            status, refused = self.request(server, "/api/converse",
                                           {"id": key, "tool": "codex", "stage": "programming",
                                            "text": "after stop", "images": []})
            self.assertEqual(status, 400)
            self.assertIn("closing", refused["error"])
            deadline = time.monotonic() + 30
            state = None
            while time.monotonic() < deadline:
                try:
                    status, state = self.request(server, "/api/turn-state", {"id": key})
                except (OSError, http.client.HTTPException):
                    break  # The server exited; polling stops with it.
                if state["operation"]["state"] == "interrupted":
                    break
                time.sleep(0.05)
            deadline = time.monotonic() + 30
            exited = False
            while time.monotonic() < deadline:
                try:
                    self.request(server, "/api/turn-state", {"id": key})
                    time.sleep(0.05)
                except (OSError, http.client.HTTPException):
                    exited = True
                    break
            self.assertTrue(exited, "the stopping server did not exit")
        self.assertNotIn("- Saved before closing.", self.registry_text(project))
        turns = conversation.read_conversation(project)
        self.assertEqual([turn["state"] for turn in turns], ["interrupted"])
        self.assertEqual(conversation.read_reliability_runs(project), [])

    def test_reopen_derives_unfinished_submissions_without_replay(self):
        project = self.project()
        folder = conversation.reserve_turn_folder(project)
        session = folder / "session"
        conversation.bridge_call(
            ["record", "--session", str(session), "--kind", "session-create",
             "--initiator", "vibe-coder", "--peer", "codex", "--mode", "work",
             "--access-path", str(project.root)], "interrupted session\n")
        note = conversation.bridge_call(
            ["record", "--session", str(session), "--kind", "note"],
            conversation.user_note_body("programming", "codex", "the interrupted question", []))
        note_ref = re.match(r"(\d{4})-", Path(note).name)[1]
        (session / "messages" / "0002-initiator-to-peer.md").write_text(
            f"# Message 0002\nFrom: vibe-coder\nTo: peer\nNote-Ref: {note_ref}\nPurpose: work\n\n"
            "## Body\n\nthe dispatched request\n", encoding="utf-8")
        reopened = ProjectStore(self.home)  # A fresh store on the same home: the reopen path.
        again = reopened.projects[reopened.open(project.root)]
        turns = conversation.read_conversation(again)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["state"], "open")  # Unfinished and interrupted; nothing replayed.
        self.assertEqual(turns[0]["text"], "the interrupted question")
        self.assertEqual(conversation.recent_exchanges(again), [])  # No final answer, so no exchange.
        self.assertEqual(conversation.unresolved_maintenance(again), [])
        self.assertEqual(conversation.read_reliability_runs(again), [])

class AuxiliaryCalls(ConversationCase):
    """The read-only sorting call, remembered per content key."""

    def aux_replies(self, **files):
        written = {}
        for name, text in files.items():
            path = self.replies / name
            path.write_text(text, encoding="utf-8")
            written[name] = str(path)
        return written

    def test_sorting_two_strict_lists_and_malformed_is_failed(self):
        project = self.project()
        written = self.aux_replies(sorting="## AI can fix\n\n- Fix the failing check.\n\n## Needs your input\n\n- Choose the storage engine.\n")
        with mock.patch.dict(os.environ, {"VIBE_FAKE_REPLY_PURPOSE_SORTING": written["sorting"]}):
            handle = conversation.start_aux(self.registry, project, "claude", conversation.PURPOSE_SORTING,
                                            "verification", "sort these findings", {"Key": "report-basis"})
            handle.done.wait(10)
            self.assertEqual(handle.state, "finished")
        answer = conversation.read_aux_answers(project)["verification:report-basis"]["answer"]
        self.assertEqual(answer, {"ai": ["Fix the failing check."], "user": ["Choose the storage engine."]})
        written = self.aux_replies(malformed="## AI can fix\n\n- Only one list.\n")
        with mock.patch.dict(os.environ, {"VIBE_FAKE_REPLY_PURPOSE_SORTING": written["malformed"]}):
            handle = conversation.start_aux(self.registry, project, "claude", conversation.PURPOSE_SORTING,
                                            "specification", "sort these findings", {"Key": "spec-basis"})
            handle.done.wait(10)
            self.assertEqual(handle.state, "failed")
            self.assertIn("exactly one", handle.reason)
        self.assertNotIn("specification:spec-basis", conversation.read_aux_answers(project))

    def test_turn_questions_come_only_from_the_exact_section(self):
        project = self.project()
        written = self.aux_replies(questions="Done with the work.\n\n## Questions for you\n\n- Which engine should the build use?\n- Who signs off the release?\n\n<!-- vibe-maintenance:start -->\nkind: no-change\n<!-- vibe-maintenance:end -->\n")
        with mock.patch.dict(os.environ, {"VIBE_FAKE_REPLY_PURPOSE_WORK": written["questions"]}):
            handle = conversation.start_turn(self.registry, project, "codex", "specification",
                                             "Work on it", [], [])
            handle.done.wait(10)
        turns = conversation.read_conversation(project)
        self.assertEqual(turns[-1]["questions"],
                         ["Which engine should the build use?", "Who signs off the release?"])
        written = self.aux_replies(no_questions="No section, just prose asking maybe?\n")
        with mock.patch.dict(os.environ, {"VIBE_FAKE_REPLY_PURPOSE_WORK": written["no_questions"]}):
            handle = conversation.start_turn(self.registry, project, "codex", "specification",
                                             "Work on it again", [], [])
            handle.done.wait(10)
        self.assertEqual(conversation.read_conversation(project)[-1]["questions"], [])

if __name__ == "__main__":
    unittest.main()
