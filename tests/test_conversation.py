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
from unittest.mock import patch

from ora_vibe_coder import conversation
from ora_vibe_coder.conversation import (
    MAINTENANCE_CONTENT, MAINTENANCE_CONTENT_END, MAINTENANCE_END, MAINTENANCE_FIND,
    MAINTENANCE_FIND_END, MAINTENANCE_REPLACE, MAINTENANCE_REPLACE_END, MAINTENANCE_START,
)
from ora_vibe_coder.handoff import prepare_request
from ora_vibe_coder.project import ProjectError, ProjectStore
from ora_vibe_coder.server import LocalServer

# Task-owned fixtures stay under /private/tmp on this platform.
TEST_ROOT = Path("/private/tmp") if Path("/private/tmp").is_dir() else Path(tempfile.gettempdir())

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
    run.add_argument("--attachment", action="append")
    run.add_argument("--note-ref")
    run.add_argument("--purpose")
    check = sub.add_parser("check")
    check.add_argument("--peer", required=True)
    check.add_argument("--mode")
    check.add_argument("--json", action="store_true")
    args = parser.parse_args()
    session = pathlib.Path(args.session)
    if args.command == "check":
        print(json.dumps({"peer": args.peer, "mode": args.mode or "review", "ready": True,
                          "warnings": [], "work": "supported", "image": "supported"}))
        return 0
    body = sys.stdin.read()
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
        delay = float(os.environ.get("VIBE_FAKE_DELAY", "0"))
        waited = 0.0
        while waited < delay:
            step = min(0.25, delay - waited)
            time.sleep(step)
            waited += step
            if not args.no_timeout and waited > float(os.environ.get("VIBE_FAKE_CAP", "900")):
                emit({"event": "finished", "phase": "run", "outcome": "failure", "reason": "fake former deadline"})
                return 1
            emit({"event": "heartbeat", "phase": "peer-call", "elapsed_seconds": round(waited, 3),
                  "child_running": True})
    if os.environ.get("VIBE_FAKE_FAIL") or os.environ.get("VIBE_FAKE_FAIL_PURPOSE_" + (args.purpose or "").upper()):
        if args.events_jsonl:
            emit({"event": "finished", "phase": "run", "outcome": "failure",
                  "request_path": str(request), "warnings": ["fake warning"],
                  "reason": "the fake peer refused the call",
                  "next_action": "resolve the fake refusal"})
        sys.stderr.write("PEER_FAILURE the fake peer refused the call\\n")
        return 1
    purpose = args.purpose or ""
    reply_file = os.environ.get("VIBE_FAKE_REPLY_PURPOSE_" + purpose.upper())
    reply_sequence = os.environ.get("VIBE_FAKE_REPLY_SEQUENCE_" + purpose.upper(), "")
    if reply_sequence:
        # Reliability rounds replay scripted replies in order; the pipeline is
        # strictly sequential, so one counter file per purpose is deterministic.
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
        # Reported identity rides the finished event, as the real runtime's
        # extended surface carries it: optional model/provider fields, present
        # only when the tool reported them and never as placeholders.
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
        (self.bridge / "bridge").mkdir(parents=True)
        (self.bridge / "bridge" / "__init__.py").write_text("", encoding="utf-8")
        (self.bridge / "bridge" / "__main__.py").write_text(FAKE_BRIDGE, encoding="utf-8")
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
            [sys.executable, "-m", "bridge", "run", "--session", str(session), "--timeout", "60",
             "--events-jsonl", "--note-ref", note_ref, "--purpose", purpose],
            cwd=str(self.bridge), input="scripted request body", capture_output=True,
            text=True, encoding="utf-8", shell=False,
            env={**os.environ, "VIBE_FAKE_REPLY_FILE": self.scripted_reply(reply)})
        self.assertEqual(result.returncode, 0, result.stderr)
        return folder

class Conversation(ConversationCase):

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
        # Legacy timeout warnings remain available without dominating the reason.
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
        images = [{"name": "../shot one.png", "data": base64.b64encode(payload).decode("ascii")}]
        handle = self.turn(project, text, fail=True, images=images)
        self.assertEqual(handle.snapshot()["state"], "failed")
        self.assertIn("fake peer refused", handle.snapshot()["reason"])
        folder = project.root / ".vibe"
        turns = conversation.turn_folders(project)
        self.assertEqual(len(turns), 1)
        session = turns[0] / "session"
        messages = {path.name: conversation.parse_message(path)
                    for path in sorted((session / "messages").glob("*.md"))}
        note = next(message for message in messages.values() if message["kind"] == "note"
                    and (conversation.note_fields(message["body"]) or {}).get("Note") == "user")
        self.assertEqual(conversation.user_text_of(note["body"]), text)  # Byte-exact user text.
        request = next(message for message in messages.values() if message["kind"] == "request")
        self.assertEqual(request["headers"]["Note-Ref"], [note["sequence"]])
        self.assertEqual(request["headers"]["Purpose"], ["work"])
        self.assertNotIn("peer-to-initiator", "".join(messages))  # No reply was invented.
        saved = turns[0] / "attachments" / "0001-shot-one.png"
        self.assertEqual(saved.read_bytes(), payload)  # Original image bytes retained.
        outcome = next(message for message in messages.values() if message["kind"] == "note"
                       and (conversation.note_fields(message["body"]) or {}).get("Note") == "outcome")
        fields = conversation.note_fields(outcome["body"])
        self.assertEqual(fields["Turn-Outcome"], "failed")
        self.assertEqual(fields["Maintenance"], "none")
        self.assertIn("fake peer refused", fields["Reason"])
        self.assertEqual(self.registry_text(project), before)  # No maintenance was applied.
        view = conversation.read_conversation(project)
        self.assertEqual(view[0]["state"], "failed")
        self.assertEqual(view[0]["text"], text)
        self.assertEqual(view[0]["images"], ["0001-shot-one.png"])
        self.assertFalse(view[0]["maintenance"]["unsaved"])  # No reply existed, so nothing was proposed.
        self.assertIn("fake peer refused", view[0]["maintenance"]["notice"])  # The failure reason is surfaced.

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

    def test_five_real_exchanges_exclude_other_purposes_and_old_packets(self):
        project = self.project()
        for number in range(1, 8):
            self.turn(project, f"round {number} question", f"round {number} answer.\n" + no_change_block())
        self.scripted_turn(project, "review", "assessment question", "assessment answer.\n")
        self.scripted_turn(project, "evaluate", "reliability pass", "reliability answer.\n")
        exchanges = conversation.recent_exchanges(project)
        self.assertEqual([exchange["text"] for exchange in exchanges],
                         [f"round {number} question" for number in range(3, 8)])  # The last five real ones.
        self.assertEqual([exchange["answer"] for exchange in exchanges],
                         [f"round {number} answer.\n" for number in range(3, 8)])  # Blocks stripped.
        # An old prepared packet is not conversation history, even when saved in the project.
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

    def test_late_reply_routes_to_origin_and_shared_locations_serialize(self):
        code = self.home / "shared repository"
        code.mkdir()
        first, second = self.project("First", code=code), self.project("Second", code=code)
        original = self.registry_text(first)
        reply = ("Working in the shared folder.\n"
                 + update_block((("## Open questions\n\n", "## Open questions\n\n## Added\n\nFrom the first project.\n\n"),)))
        environment = {"VIBE_FAKE_REPLY_FILE": self.scripted_reply(reply), "VIBE_FAKE_DELAY": "1.5"}
        with patch.dict(os.environ, environment):
            handle = conversation.start_turn(self.registry, first, "codex", "programming",
                                             "start the shared work", [])
            self.assertIn(handle.snapshot()["state"], {"starting", "running"})
            # One work turn per project, and the shared resolved location is serialized.
            with self.assertRaisesRegex(ProjectError, "One work turn per project"):
                conversation.start_turn(self.registry, first, "codex", "programming", "again", [])
            with self.assertRaisesRegex(ProjectError, "Another work turn is already writing"):
                conversation.start_turn(self.registry, second, "codex", "programming", "competing", [])
            # Reading and switching stay available while the turn works.
            self.assertEqual(conversation.read_conversation(second), [])
            self.assertTrue(handle.done.wait(timeout=20))
        snapshot = handle.snapshot()
        self.assertEqual((snapshot["state"], snapshot["maintenance"]), ("finished", "applied"))
        self.assertGreaterEqual(snapshot["elapsed_seconds"], 1.4)
        # The late reply and its maintenance landed on the originating project only.
        self.assertIn("From the first project.", self.registry_text(first))
        self.assertNotIn("From the first project.", self.registry_text(second))
        view = conversation.read_conversation(first)
        self.assertEqual(view[0]["state"], "complete")
        self.assertEqual(view[0]["reply"], "Working in the shared folder.\n")
        self.assertEqual(view[0]["maintenance"]["outcome"], "applied")
        # After the conflicting operation finished, the second project's turn is admitted.
        self.assertEqual(self.turn(second, "now the second project", "Second answer.\n" + no_change_block())
                         .snapshot()["state"], "finished")
        self.assertEqual([turn["text"] for turn in conversation.read_conversation(second)],
                         ["now the second project"])

    def test_nested_projects_sharing_one_registry_serialize_on_that_file(self):
        parent = self.project("Parent")
        # A project nested inside the parent's folder: the two roots do not
        # overlap as folder locations, and the parent's Registry association
        # resolves onto the child's own starter Registry — one shared file.
        key = self.store.create("Nested", "Nested", "Description", "Goals", under=parent.root)
        nested = self.store.projects[key]
        shared = nested.root / "Registry.md"
        brief = parent.brief()
        parent.save_brief(parent.brief_text(), brief["name"], brief["description"], brief["goals"],
                          {"Registry": "Nested/Registry.md"})
        reply = "Parent answer.\n" + update_block(
            (("## Notes\n\n", "## Notes\n\n- The parent project's durable fact.\n\n"),))
        with patch.dict(os.environ, {"VIBE_FAKE_REPLY_FILE": self.scripted_reply(reply),
                                     "VIBE_FAKE_DELAY": "1.5"}):
            handle = conversation.start_turn(self.registry, parent, "codex", "programming",
                                             "record through the shared registry", [])
            self.assertIn(handle.snapshot()["state"], {"starting", "running"})
            # The shared document target — not the folders — is the overlap, so
            # the nested project's competing turn is refused while the parent's
            # runs, exactly as a shared code folder refuses it.
            with self.assertRaisesRegex(ProjectError, "Another work turn is already writing"):
                conversation.start_turn(self.registry, nested, "codex", "programming", "competing", [])
            # Containment alone is not overlap: an unrelated project writing
            # its own different files is admitted concurrently and finishes.
            unrelated = self.project("Unrelated")
            independent = conversation.start_turn(self.registry, unrelated, "codex", "programming",
                                                  "independent work", [])
            self.assertTrue(handle.done.wait(timeout=20))
            self.assertTrue(independent.done.wait(timeout=20))
        self.assertEqual(handle.snapshot()["maintenance"], "applied")
        self.assertIn("The parent project's durable fact.", shared.read_text(encoding="utf-8"))
        # The parent's own starter Registry was not the target; only the
        # shared, associated file changed.
        self.assertNotIn("The parent project's durable fact.",
                         (parent.root / "Registry.md").read_text(encoding="utf-8"))
        # After the parent's turn finished, the nested project's own turn is
        # admitted and writes the same file through its own resolution.
        self.assertEqual(self.turn(nested, "now the nested project", "Nested answer.\n" + no_change_block())
                         .snapshot()["state"], "finished")
        self.assertIn("The parent project's durable fact.", shared.read_text(encoding="utf-8"))

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
        # Reopening derives the same records with no in-memory help: a fresh store on the same home.
        reopened = ProjectStore(self.home)
        again = reopened.projects[reopened.open(project.root)]
        self.assertEqual([item["turn"] for item in conversation.unresolved_maintenance(again)],
                         [item["turn"] for item in unresolved])
        self.assertEqual(len(conversation.read_conversation(again)), 6)
        # An actually applied maintenance that names the stalled turn on its
        # resolved line disposes of it; no second call is made for that
        # purpose, and nothing else clears it.
        current = self.registry_text(project)
        settled = current.replace("## Open questions\n\n", "## Open questions\n\n- Resolved by the later turn.\n\n")
        stalled = conversation.turn_folders(project)[0].name
        self.turn(project, "resolve it now", "Settling answer.\n"
                  + update_block((("## Open questions\n\n", "## Open questions\n\n- Resolved by the later turn.\n\n"),),
                                 resolved=(stalled,)))
        self.assertEqual(self.registry_text(project), settled)
        self.assertEqual(conversation.unresolved_maintenance(project), [])

    def test_registry_write_failure_retains_the_proposal_as_unresolved(self):
        project = self.project()
        starter = self.registry_text(project)
        proposal = starter.replace("## Notes\n\n", "## Notes\n\n- The decision the failed write dropped before.\n\n")
        reply = "The complete answer.\n" + update_block((("## Notes\n\n", "## Notes\n\n- The decision the failed write dropped before.\n\n"),))
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
        # Two earlier turns leave unresolved proposals of their own.
        self.turn(project, "first stalled", "First answer.\n"
                  + update_block((("absent anchor one\n", "## Notes\n\n- First proposal.\n\n"),)))
        self.turn(project, "second stalled", "Second answer.\n"
                  + update_block((("absent anchor two\n", "## Notes\n\n- Second proposal.\n\n"),)))
        folders = conversation.turn_folders(project)
        first, second = folders[0].name, folders[1].name
        self.assertEqual([item["turn"] for item in conversation.unresolved_maintenance(project)],
                         [first, second])
        # An identifier the request did not supply invalidates the whole
        # block: nothing applies, and every earlier proposal survives it.
        handle = self.turn(project, "name an unknown turn", "Naming the unknown.\n"
                           + update_block((("## Notes\n\n", "## Notes\n\n- The new durable fact.\n\n"),),
                                          resolved=("9999-00000000-000000",)))
        self.assertEqual(handle.snapshot()["maintenance"], "malformed")
        self.assertNotIn("The new durable fact", self.registry_text(project))
        folders = conversation.turn_folders(project)
        self.assertEqual([item["turn"] for item in conversation.unresolved_maintenance(project)],
                         [first, second, folders[2].name])
        # An accepted no-change disposes exactly the proposal it names; the
        # unrelated ones survive the dismissal.
        self.turn(project, "dismiss the first",
                  "The first proposal should not apply: it was superseded, and this answer says why.\n"
                  + no_change_block(resolved=(first,)))
        self.assertEqual([item["turn"] for item in conversation.unresolved_maintenance(project)],
                         [second, folders[2].name])
        # An applied update that names the rest disposes of them.
        self.turn(project, "settle the rest", "Settling answer.\n"
                  + update_block((("## Notes\n\n", "## Notes\n\n- Settled durable fact.\n\n"),),
                                 resolved=(second, folders[2].name)))
        self.assertIn("- Settled durable fact.", self.registry_text(project))
        self.assertEqual(conversation.unresolved_maintenance(project), [])
        # The disposal is recorded in the outcome note and survives a reopen.
        reopened = ProjectStore(self.home)
        again = reopened.projects[reopened.open(project.root)]
        self.assertEqual(conversation.unresolved_maintenance(again), [])
        folders = conversation.turn_folders(project)
        outcome = conversation.read_turn(folders[4])["outcome"]
        self.assertEqual(outcome["resolved"], [second, folders[2].name])

    def test_span_updates_validate_all_spans_before_one_write(self):
        project = self.project()
        # Two narrow spans in one block: both locate exactly once and one
        # write applies them together.
        self.turn(project, "two narrow edits", "Narrow edits.\n"
                  + update_block((("## Notes\n\n", "## Notes\n\n- First narrow fact.\n\n"),
                                  ("## Open questions\n\n", "## Open questions\n\n- First open question.\n\n"))))
        current = self.registry_text(project)
        self.assertIn("- First narrow fact.", current)
        self.assertIn("- First open question.", current)
        # A later span that fails to locate leaves the whole block — and the
        # document — untouched: every span validates before the single write.
        self.turn(project, "second span drifted", "Mixed answer.\n"
                  + update_block((("## Notes\n\n", "## Notes\n\n- Would apply.\n\n"),
                                  ("anchor that is not present\n", "never\n"))))
        self.assertEqual(self.registry_text(project), current)
        turn = conversation.read_conversation(project)[-1]
        self.assertEqual(turn["maintenance"]["outcome"], "stale")
        self.assertTrue(turn["maintenance"]["unsaved"])
        # An anchor that appears twice is not unique: stale, nothing written.
        duplicated = current.replace("## Open questions\n\n", "## Open questions\n\n## Open questions\n\n")
        (project.root / "Registry.md").write_text(duplicated, encoding="utf-8")
        self.turn(project, "ambiguous anchor", "Ambiguous answer.\n"
                  + update_block((("## Open questions\n\n", "## Questions\n\n"),)))
        self.assertEqual(self.registry_text(project), duplicated)
        self.assertEqual(conversation.read_conversation(project)[-1]["maintenance"]["outcome"], "stale")
        # Overlapping spans contradict each other: malformed, nothing written.
        self.turn(project, "overlapping spans", "Overlap answer.\n"
                  + update_block((("## Notes\n\n- First narrow fact.\n\n", "replaced whole\n\n"),
                                  ("First narrow fact.\n\n", "replaced tail\n\n"))))
        self.assertEqual(self.registry_text(project), duplicated)
        self.assertEqual(conversation.read_conversation(project)[-1]["maintenance"]["outcome"], "malformed")
        # An empty replacement deletes exactly its span.
        self.turn(project, "delete the duplicate", "Deleting answer.\n"
                  + update_block((("## Open questions\n\n## Open questions\n\n", ""),)))
        after = self.registry_text(project)
        self.assertNotIn("## Open questions", after)  # Both matched anchor lines are gone.
        self.assertIn("- First open question.", after)  # The surrounding text survives.

    def test_changed_line_anchor_is_stale_and_end_of_document_anchor_is_tolerated(self):
        project = self.project()
        # The changed-value shape: the anchor's exact text is absent, and its
        # newline-stripped form matches inside a longer line. Splicing the
        # replacement there would corrupt `Budget: 100` into `Budget: 20\n0`
        # while reporting success; the span is stale and nothing is written.
        (project.root / "Registry.md").write_text("Budget: 100\n", encoding="utf-8")
        self.turn(project, "change the budget", "Budget answer.\n"
                  + update_block((("Budget: 10\n", "Budget: 20\n"),)))
        self.assertEqual(self.registry_text(project), "Budget: 100\n")  # The changed value survives.
        turn = conversation.read_conversation(project)[-1]
        self.assertEqual(turn["maintenance"]["outcome"], "stale")
        self.assertTrue(turn["maintenance"]["unsaved"])
        self.assertIn("nothing was applied", conversation.unresolved_maintenance(project)[-1]["reason"])
        # The same shortened anchor mid-document — a line that grew while the
        # document continues — is stale too, never matched against an interior
        # line even though the document also continues past it.
        (project.root / "Registry.md").write_text("Ledger\n\nBudget: 100\n\nCarried\n", encoding="utf-8")
        self.turn(project, "change the carried budget", "Carried answer.\n"
                  + update_block((("Budget: 10\n", "Budget: 20\n"),)))
        self.assertEqual(self.registry_text(project), "Ledger\n\nBudget: 100\n\nCarried\n")
        self.assertEqual(conversation.read_conversation(project)[-1]["maintenance"]["outcome"], "stale")
        # A missing final line ending is still tolerated when the otherwise
        # exact anchor reaches the end of the document: the anchor's last line
        # is the document's last line, and the write lands cleanly.
        (project.root / "Registry.md").write_text("Ledger\n\nBudget: 10", encoding="utf-8")
        self.turn(project, "update the last line", "Last-line answer.\n"
                  + update_block((("Budget: 10\n", "Budget: 20\n"),)))
        self.assertEqual(self.registry_text(project), "Ledger\n\nBudget: 20\n")
        self.assertEqual(conversation.read_conversation(project)[-1]["maintenance"]["outcome"], "applied")
        # When the shortened form matches both inside an earlier line and at
        # the document's end, only the end-of-document match is tolerated.
        (project.root / "Registry.md").write_text("Budget: 100\nLedger\nBudget: 10", encoding="utf-8")
        self.turn(project, "update the final entry", "Final answer.\n"
                  + update_block((("Budget: 10\n", "Budget: 20\n"),)))
        self.assertEqual(self.registry_text(project), "Budget: 100\nLedger\nBudget: 20\n")
        self.assertEqual(conversation.read_conversation(project)[-1]["maintenance"]["outcome"], "applied")
        # An ambiguity that hides in the tolerated shape: one exact match plus
        # a trimmed end-of-document match of the same anchor. Both eligible
        # locations are counted together under one rule, so the edit refuses
        # as stale instead of silently applying at the first while a second
        # eligible location exists.
        (project.root / "Registry.md").write_text("Budget: 10\n\nTail: Budget: 10", encoding="utf-8")
        self.turn(project, "ambiguous tail without ending", "Tail answer.\n"
                  + update_block((("Budget: 10\n", "Budget: 20\n"),)))
        self.assertEqual(self.registry_text(project), "Budget: 10\n\nTail: Budget: 10")
        self.assertEqual(conversation.read_conversation(project)[-1]["maintenance"]["outcome"], "stale")
        # With the final line ending present, the same text is an ordinary
        # duplicate anchor and refuses the same way.
        (project.root / "Registry.md").write_text("Budget: 10\n\nTail: Budget: 10\n", encoding="utf-8")
        self.turn(project, "ambiguous tail with ending", "Ending answer.\n"
                  + update_block((("Budget: 10\n", "Budget: 20\n"),)))
        self.assertEqual(self.registry_text(project), "Budget: 10\n\nTail: Budget: 10\n")
        self.assertEqual(conversation.read_conversation(project)[-1]["maintenance"]["outcome"], "stale")

    def test_interrupted_span_update_reconciles_by_span_reflection(self):
        project = self.project()
        starter = self.registry_text(project)
        insertion = (("## Notes\n\n", "## Notes\n\n- The interrupted span edit.\n\n"),)
        self.scripted_turn(project, "work", "the interrupted span question",
                           "Interrupted span answer.\n" + update_block(insertion))
        turns = conversation.read_conversation(project)
        self.assertEqual(turns[0]["maintenance"]["outcome"], "unconfirmed")
        self.assertEqual(len(conversation.unresolved_maintenance(project)), 1)
        # The Registry never received the edit: the anchor stands alone and
        # the inserted text is absent, so the proposal stays unresolved.
        self.assertNotIn("interrupted span edit", self.registry_text(project))
        # Once the content reflects the spans — an insertion keeps its anchor
        # and carries the inserted text — the proposal is resolved with no
        # replay of the request.
        proposal = starter.replace("## Notes\n\n", "## Notes\n\n- The interrupted span edit.\n\n")
        (project.root / "Registry.md").write_text(proposal, encoding="utf-8")
        self.assertEqual(conversation.unresolved_maintenance(project), [])
        # A deletion span reconciles on its absent anchor alone, while the
        # insertion above stays reflected.
        self.scripted_turn(project, "work", "the interrupted deletion question",
                           "Interrupted deletion answer.\n"
                           + update_block((("## Open questions\n\n", ""),)))
        self.assertEqual(conversation.unresolved_maintenance(project)[-1]["maintenance"], "unconfirmed")
        (project.root / "Registry.md").write_text(proposal.replace("## Open questions\n\n", ""), encoding="utf-8")
        self.assertEqual(conversation.unresolved_maintenance(project), [])

    def test_ambiguous_reflection_retains_the_interrupted_proposal(self):
        project = self.project()
        # Two unresolved occurrences of the anchor, with the replacement text
        # already present at the second: ordinary application rejects the
        # ambiguous anchor, so interrupted-save reconciliation must not read
        # replacement presence alone as proof the proposal was applied.
        current = "## Decisions\nPending\n\n## Decisions\nAccepted\n"
        (project.root / "Registry.md").write_text(current, encoding="utf-8")
        spans = (("## Decisions\n", "## Decisions\nAccepted\n"),)
        _visible, raw, _fault = conversation.split_maintenance("Answer.\n" + update_block(spans))
        maintenance, _registry, _reason, _resolved = conversation.apply_maintenance(
            project, conversation.parse_maintenance(raw))
        self.assertEqual(maintenance, "stale")  # Ordinary application refuses the duplicate anchor.
        self.assertEqual(self.registry_text(project), current)
        self.scripted_turn(project, "work", "the ambiguous proposal",
                           "Ambiguous answer.\n" + update_block(spans))
        turns = conversation.read_conversation(project)
        self.assertEqual(turns[-1]["maintenance"]["outcome"], "unconfirmed")  # Retained, never dropped.
        self.assertTrue(turns[-1]["maintenance"]["unsaved"])
        unresolved = conversation.unresolved_maintenance(project)
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["maintenance"], "unconfirmed")
        self.assertIn("Accepted", unresolved[0]["block"])  # The proposal stays supplied for future context.
        # Once the reflection is unambiguous — the replacement present and no
        # anchor occurrence outside it — the same proposal resolves with no
        # replay of the request.
        (project.root / "Registry.md").write_text(
            "## Decisions\nAccepted\n\nPending decision still open.\n", encoding="utf-8")
        self.assertEqual(conversation.unresolved_maintenance(project), [])
        self.assertIsNone(conversation.read_conversation(project)[-1]["maintenance"])

    def test_interrupted_changed_value_is_retained_not_read_as_applied(self):
        project = self.project()
        # The round-10 reproduction: the current Registry carries a changed
        # value whose text merely starts with the proposal's replacement.
        # Ordinary application refuses the span as stale; a reconciliation
        # looser than application once stripped the replacement's line ending
        # and searched anywhere, so `Budget: 10` matched the prefix of
        # `Budget: 100` and the interrupted proposal was discarded as though
        # applied — silently dropping an unsaved decision from future context.
        (project.root / "Registry.md").write_text("Budget: 100\n", encoding="utf-8")
        spans = (("Budget: 20\n", "Budget: 10\n"),)
        self.scripted_turn(project, "work", "change the budget", "Budget answer.\n" + update_block(spans))
        turns = conversation.read_conversation(project)
        self.assertEqual(turns[-1]["maintenance"]["outcome"], "unconfirmed")  # Retained, never dropped.
        self.assertTrue(turns[-1]["maintenance"]["unsaved"])
        self.assertEqual(self.registry_text(project), "Budget: 100\n")  # The changed value survives.
        unresolved = conversation.unresolved_maintenance(project)
        self.assertEqual(len(unresolved), 1)
        self.assertIn("Budget: 10", unresolved[0]["block"])  # The proposal stays supplied for future context.
        # A replacement shortened inside a longer line is held to the same
        # line boundary mid-document, exactly as application holds the anchor.
        (project.root / "Registry.md").write_text("Ledger\n\nBudget: 100\n\nCarried\n", encoding="utf-8")
        self.assertEqual(len(conversation.unresolved_maintenance(project)), 1)
        # Once the Registry truly carries the replacement — exactly, as a
        # complete line — the same proposal resolves with no replay.
        (project.root / "Registry.md").write_text("Ledger\n\nBudget: 10\n\nCarried\n", encoding="utf-8")
        self.assertEqual(conversation.unresolved_maintenance(project), [])
        self.assertIsNone(conversation.read_conversation(project)[-1]["maintenance"])
        # The missing-final-newline tolerance still resolves, consistently
        # with application: only while the otherwise exact replacement reaches
        # the end of the document.
        (project.root / "Registry.md").write_text("Ledger\n\nBudget: 10", encoding="utf-8")
        self.scripted_turn(project, "work", "the settled budget question",
                           "Settled budget answer.\n" + update_block(spans))
        self.assertEqual(conversation.unresolved_maintenance(project), [])

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
        # Containment, not top-level-only: the nested Registry receives the
        # automatic update.
        self.turn(project, "update the nested registry", "Nested answer.\n"
                  + update_block((("## Notes\n\n", "## Notes\n\n- Nested durable fact.\n\n"),)))
        self.assertIn("- Nested durable fact.", (nested / "Registry.md").read_text(encoding="utf-8"))
        self.assertEqual(conversation.read_conversation(project)[-1]["maintenance"]["outcome"], "applied")
        # Links and outside-project documents are still refused.
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
        # The same containment governs the assessment save path.
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
        # This checkout's own vendored component is what every call runs from.
        with patch.object(conversation, "BRIDGE_HOME", None):
            application = Path(conversation.__file__).resolve().parents[1]
            self.assertEqual(conversation.bridge_root(), application / "components" / "agent-bridge")
        # The same order under a synthetic layout: a developer checkout beside
        # the application never overrides the repository's own vendor.
        repository = self.root / "repository"
        (repository / "components" / "agent-bridge" / "bridge").mkdir(parents=True)
        (repository / "components" / "agent-bridge" / "bridge" / "__main__.py").write_text("", encoding="utf-8")
        developer = self.root / "agent-bridge"  # Beside the "application".
        (developer / "bridge").mkdir(parents=True)
        (developer / "bridge" / "__main__.py").write_text("", encoding="utf-8")
        candidates = conversation._bridge_candidates(repository)
        self.assertEqual(candidates, (repository / "components" / "agent-bridge", developer))
        self.assertEqual(next((candidate for candidate in candidates
                               if (candidate / "bridge" / "__main__.py").is_file()), None),
                         repository / "components" / "agent-bridge")
        # The installed layout ships no components/ tree beside the app, so
        # the copy bundled beside the application serves it.
        apps = self.root / "apps"
        application = apps / "Ora Vibe Coder"
        application.mkdir(parents=True)
        beside = apps / "agent-bridge"
        (beside / "bridge").mkdir(parents=True)
        (beside / "bridge" / "__main__.py").write_text("", encoding="utf-8")
        self.assertEqual(next((candidate for candidate in conversation._bridge_candidates(application)
                               if (candidate / "bridge" / "__main__.py").is_file()), None),
                         beside)

    def test_readiness_poll_reads_only_and_recheck_starts_one_worker(self):
        server = LocalServer(self.home)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01})
        thread.start()

        def close():
            if thread.is_alive():
                server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.addCleanup(close)

        def request(body):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("POST", "/api/readiness", json.dumps(body),
                               headers={"Content-Type": "application/json", "X-Ora-Token": server.token})
            response = connection.getresponse()
            data = json.loads(response.read())
            connection.close()
            return response.status, data

        calls = []
        gate = threading.Event()

        def gated_check(peer, **_kwargs):
            calls.append(peer)
            gate.wait(10)
            return {"peer": peer, "ready": True, "warnings": []}

        with patch.object(conversation, "bridge_check", gated_check):
            # An ordinary poll only reads: no worker, no probe, no restart.
            status, report = request({})
            self.assertEqual((status, report["checking"], report["peers"]), (200, False, None))
            self.assertEqual(calls, [])
            # The recheck starts exactly one worker, still behind the
            # single-worker guard when asked again while it runs.
            status, report = request({"recheck": True})
            self.assertEqual(status, 200)
            self.assertTrue(report["checking"])
            status, again = request({"recheck": True})  # Retained while the sweep runs...
            self.assertTrue(again["checking"])
            status, twice = request({"recheck": True})  # ...and a second queued recheck collapses into the same one.
            self.assertTrue(twice["checking"])
            for _ in range(3):
                request({})  # Polls while the check runs never restart it.
            deadline = time.monotonic() + 5
            while not calls and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(calls, list(conversation.PEERS)[:1])  # One worker, still on its first probe.
            gate.set()  # Let the sweep finish; the one retained recheck then runs its own full pass.
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                status, report = request({})
                if not report["checking"] and len(calls) >= 2 * len(conversation.PEERS):
                    break
                time.sleep(0.01)
            self.assertFalse(report["checking"])  # The chain ends when every sweep completes.
            self.assertEqual([facts["peer"] for facts in report["peers"]], list(conversation.PEERS))
            self.assertEqual(calls, list(conversation.PEERS) * 2)  # One sweep plus exactly one retained recheck.
            for _ in range(3):
                request({})  # Finished-check polls start nothing.
            self.assertEqual(calls, list(conversation.PEERS) * 2)

    def test_note_less_reply_reconciles_against_current_registry_on_reopen(self):
        project = self.project()
        starter = self.registry_text(project)
        spans = (("## Decisions\n\n", "## Decisions\n\n- The interrupted turn's decision.\n\n"),)
        proposal = starter.replace("## Decisions\n\n", "## Decisions\n\n- The interrupted turn's decision.\n\n")
        # A reply preserved just before interruption, with no outcome note.
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
        result = subprocess.run(
            [sys.executable, "-m", "bridge", "run", "--session", str(session), "--timeout", "60",
             "--events-jsonl", "--note-ref", note_ref, "--purpose", "work"],
            cwd=str(self.bridge), input="the dispatched request", capture_output=True,
            text=True, encoding="utf-8", shell=False,
            env={**os.environ, "VIBE_FAKE_REPLY_FILE": self.scripted_reply(
                "Interrupted answer.\n" + update_block(spans))})
        self.assertEqual(result.returncode, 0, result.stderr)
        reopened = ProjectStore(self.home)  # A fresh store on the same home: the reopen path.
        again = reopened.projects[reopened.open(project.root)]
        self.assertEqual(len(conversation.turn_folders(again)), 1)  # No replay: nothing new was sent.
        turns = conversation.read_conversation(again)
        self.assertEqual(turns[0]["state"], "complete")  # The preserved reply is displayed.
        self.assertEqual(turns[0]["reply"], "Interrupted answer.\n")  # The answer itself is preserved.
        self.assertFalse(turns[0]["outcome_recorded"])  # No live operation owns it: genuinely interrupted.
        # The display surfaces the reconciliation: the interrupted turn's
        # maintenance reads as unconfirmed and unsaved, with its reason — the
        # answer above is never replaced or hidden by the notice.
        self.assertEqual(turns[0]["maintenance"]["outcome"], "unconfirmed")
        self.assertTrue(turns[0]["maintenance"]["unsaved"])
        self.assertIn("interrupted", turns[0]["maintenance"]["notice"].lower())
        self.assertIn("never applied", turns[0]["maintenance"]["notice"])
        unresolved = conversation.unresolved_maintenance(again)
        self.assertEqual(len(unresolved), 1)  # Surfaced as unresolved against current content.
        self.assertEqual(unresolved[0]["maintenance"], "unconfirmed")
        self.assertIn("The interrupted turn's decision.", unresolved[0]["block"])
        # Once the Registry actually carries the proposal, it is resolved: no
        # request is replayed to find that out, and the displayed turn stops
        # claiming unconfirmed maintenance.
        (project.root / "Registry.md").write_text(proposal, encoding="utf-8")
        self.assertEqual(conversation.unresolved_maintenance(again), [])
        self.assertEqual(len(conversation.turn_folders(again)), 1)
        settled = conversation.read_conversation(again)
        self.assertIsNone(settled[0]["maintenance"])
        self.assertEqual(settled[0]["state"], "complete")
        self.assertFalse(settled[0]["outcome_recorded"])  # Reconciliation resolved the display; the record still has no outcome note.

    def test_complete_reply_without_outcome_reads_unreflected_until_noted(self):
        # The completion race: a reply and its maintenance outcome save
        # separately, and a conversation view loaded between the two saves
        # displays the turn complete with a derived unconfirmed maintenance
        # state. The record must expose that its outcome is missing, so the
        # poll refreshes a terminal operation whose outcome is not yet
        # reflected — and stops once the outcome note exists.
        project = self.project()
        starter = self.registry_text(project)
        proposal = starter.replace("## Decisions\n\n", "## Decisions\n\n- The raced turn's decision.\n\n")
        reply = "The complete answer.\n" + update_block(
            (("## Decisions\n\n", "## Decisions\n\n- The raced turn's decision.\n\n"),))
        folder = self.scripted_turn(project, "work", "the raced question", reply)
        turns = conversation.read_conversation(project)
        self.assertEqual(turns[0]["state"], "complete")  # The reply itself completes the turn...
        self.assertFalse(turns[0]["outcome_recorded"])  # ...while its outcome is missing: unreflected.
        self.assertEqual(turns[0]["maintenance"]["outcome"], "unconfirmed")
        self.assertTrue(turns[0]["maintenance"]["unsaved"])
        # The turn finishes after that view: maintenance applies and the
        # outcome note is recorded through the application's own writers.
        _visible, block, _fault = conversation.split_maintenance(reply)
        maintenance, registry, reason, resolved = conversation.apply_maintenance(
            project, conversation.parse_maintenance(block))
        self.assertEqual(maintenance, "applied")
        self.assertEqual(resolved, [])  # Nothing was supplied to dispose.
        conversation.bridge_call(
            ["record", "--session", str(folder / "session"), "--kind", "note"],
            conversation.outcome_note_body("programming", "finished", maintenance, registry, reason, block, resolved))
        settled = conversation.read_conversation(project)
        self.assertEqual(settled[0]["state"], "complete")
        self.assertTrue(settled[0]["outcome_recorded"])  # Reflected: no further refresh is needed.
        self.assertEqual(settled[0]["maintenance"]["outcome"], "applied")
        self.assertFalse(settled[0]["maintenance"]["unsaved"])
        self.assertIn("- The raced turn's decision.", self.registry_text(project))

    def test_interrupted_missing_or_malformed_maintenance_surfaces_the_condition(self):
        project = self.project()
        unterminated = f"{MAINTENANCE_START}\nkind: no-change\n"  # The closing marker never arrived.
        for label, reply, expected in (
            ("missing", "Interrupted answer.\n", "missing"),
            ("unterminated", "Interrupted answer.\n" + unterminated, "malformed"),
            ("multiple-openings", "Interrupted answer.\n" + no_change_block() + no_change_block(), "malformed"),
        ):
            with self.subTest(label=label):
                # A reply preserved just before interruption, with no outcome
                # note: the normal completion path would have recorded the
                # missing/malformed condition, so reconciliation must too.
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
        # A later turn whose maintenance actually applies resolves the
        # conditions, but only by naming them on its resolved line.
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
        server = LocalServer(self.home)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01})
        thread.start()

        def close():
            if thread.is_alive():
                server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.addCleanup(close)

        def request(path, body, headers=None):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            actual = {"Content-Type": "application/json", "X-Ora-Token": server.token}
            actual.update(headers or {})
            connection.request("POST", path, json.dumps(body), headers=actual)
            response = connection.getresponse()
            data = json.loads(response.read())
            connection.close()
            return response.status, data

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
            # The acknowledgement names the originating turn's retained
            # originals, so the browser's restorable draft is keyed to this
            # project and this turn, never to whichever project is displayed.
            self.assertEqual(started["images"], ["0001-shot-one.png"])
            self.assertIn(started["operation"]["state"], {"starting", "running"})
            # Another project's report never carries this turn's operation:
            # the acknowledgement and its result stay bound to their origin.
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
        # Event diagnostics and failed outcome recording stay in the aggregate
        # for retained accounting, but have distinct presentation lists.
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
            "## REVISED ASSESSMENT\n\nStage: Specification\nVerdict: INCOMPLETE\nBasis: " + "b" * 64 +
            "\n- One deficiency, now with the named import format.\n\n"
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
                       stage="specification", provider_author="", provider_reviewer="",
                       model_author="", author_output=None, evaluator_output=None,
                       revision_output=None):
        environment = {
            "VIBE_FAKE_REPLY_PURPOSE_AUTHOR": self.pass_reply(
                "author", author_output or "Stage: Specification\nVerdict: INCOMPLETE\nBasis: "
                + "b" * 64 + "\n- One deficiency.\n"),
            "VIBE_FAKE_REPLY_PURPOSE_REVISE": self.pass_reply(
                "revise", revision_output or revision_reply(changelog)),
            "VIBE_FAKE_SEQUENCE_DIR": str(self.replies / f"counts-{time.monotonic_ns()}"),
        }
        if provider_author:
            environment["VIBE_FAKE_PROVIDER_PURPOSE_AUTHOR"] = provider_author
            environment["VIBE_FAKE_PROVIDER_PURPOSE_REVISE"] = provider_author
        if provider_reviewer:
            environment["VIBE_FAKE_PROVIDER_PURPOSE_EVALUATE"] = provider_reviewer
        if model_author:
            environment["VIBE_FAKE_MODEL_PURPOSE_AUTHOR"] = model_author
            environment["VIBE_FAKE_MODEL_PURPOSE_REVISE"] = model_author
        if len(evaluate) == 1:
            environment["VIBE_FAKE_REPLY_PURPOSE_EVALUATE"] = self.pass_reply(
                "evaluate", evaluator_output or evaluation_reply(evaluate[0]))
        else:
            environment["VIBE_FAKE_REPLY_SEQUENCE_EVALUATE"] = os.pathsep.join(
                self.pass_reply(f"evaluate-{index}", evaluation_reply(verdict))
                for index, verdict in enumerate(evaluate))
        if fail_evaluate:
            environment["VIBE_FAKE_FAIL_PURPOSE_EVALUATE"] = "1"
        with patch.dict(os.environ, environment):
            handle = conversation.start_assessment(self.registry, project, tool, stage, reviewer, iterate)
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
                answer = (f"## Current review\n\nStage: {role}\nVerdict: COMPLETE\n"
                          f"Basis: {review_basis(original)}\n")
                handle = self.second_opinion(project, stage=stage, reviewer="", author_output=answer)
                self.assertEqual((handle.snapshot()["state"], handle.snapshot()["maintenance"]),
                                 ("finished", "applied"))
                self.assertEqual(len(conversation.turn_folders(project)), 1)
                run = conversation.read_reliability_runs(project)[0]
                self.assertEqual((run["reviewer"], run["assessment"], run["output"]),
                                 ("", "applied", answer.split("\n\n", 1)[1].strip()))
                facts = assessment_facts(stage, document.read_text(encoding="utf-8"))
                self.assertEqual((facts["verdict"], facts["applies"]), ("COMPLETE", "current"))

    def test_clear_review_variants_preserve_reasoning_without_extra_passes(self):
        from ora_vibe_coder.status import assessment_facts

        variants = ("COMPLETE\n\nAll required decisions are present.\n",
                    "**Status: COMPLETE.**\n\n## Findings\n\nNo material gaps remain.\n",
                    "The Specification is complete.\n\nIts acceptance checks describe the intended behavior.\n",
                    "Status: COMPLETE\n\n## Current result\nVerdict: COMPLETE\n\n"
                    "## Earlier review\n### Result\nStatus: INCOMPLETE\n",
                    "Status: COMPLETE\n\n## Findings\nQuoted historical illustration:\n"
                    "```markdown\n## Current review\n### Result\nStatus: INCOMPLETE\n```\nReasoning retained.\n")
        for index, answer in enumerate(variants):
            with self.subTest(answer=answer):
                project = self.project(f"Variant{index}")
                handle = self.second_opinion(project, reviewer="", author_output=answer)
                self.assertEqual((handle.snapshot()["state"], handle.snapshot()["maintenance"]), ("finished", "applied"))
                saved = (project.root / "Specification.md").read_text()
                self.assertIn(answer.strip().splitlines()[-1], saved)
                self.assertEqual(assessment_facts("specification", saved)["verdict"], "COMPLETE")
                if "## Earlier review" in answer:
                    self.assertIn("### Earlier review\n#### Result\nStatus: INCOMPLETE", saved)
                if "```markdown" in answer:
                    self.assertIn("```markdown\n## Current review\n### Result\nStatus: INCOMPLETE\n```", saved)
                self.assertEqual(len(conversation.turn_folders(project)), 1)

    def test_review_binds_target_and_records_changed_content_as_earlier(self):
        from ora_vibe_coder.status import assessment_facts

        for selection_changes in (False, True):
            project = self.project("Selection" if selection_changes else "Content")
            document = project.root / "Specification.md"
            original = document.read_text()
            alternate = project.root / "Other specification.md"
            alternate.write_text("# Alternate\n\n## Requirements\n\nA different work item.\n")
            reply = self.pass_reply("author", "Verdict: COMPLETE\n\nAll required choices are recorded.\n")
            with patch.dict(os.environ, {"VIBE_FAKE_REPLY_PURPOSE_AUTHOR": reply, "VIBE_FAKE_DELAY": "0.35"}):
                handle = conversation.start_assessment(self.registry, project, "codex", "specification", "", False)
                if selection_changes:
                    self.associate(project, "Specification", alternate)
                else:
                    document.write_text(original + "\n## Added requirement\n\nPreserve incoming records.\n")
                self.assertTrue(handle.done.wait(10))
            if selection_changes:
                self.assertEqual(document.read_text(), original)
                self.assertNotIn("Current review", alternate.read_text())
                self.assertEqual(handle.artifact["outcome"], "selection-changed")
                self.assertNotEqual(handle.maintenance, "applied")
            else:
                saved = document.read_text()
                self.assertIn("Preserve incoming records.", saved)
                self.assertEqual(assessment_facts("specification", saved)["applies"], "earlier")
                self.assertEqual(handle.artifact["applies"], "earlier")

    def test_review_records_its_own_basis_when_ai_omits_or_mislabels_it(self):
        from ora_vibe_coder.status import assessment_facts, review_basis

        for stage, role in (("specification", "Specification"), ("planning", "Plan")):
            with self.subTest(stage=stage):
                project = self.project(role)
                document = project.root / f"{role}.md"
                if stage == "planning":
                    document.write_text("# Plan\n\n## Approach\n\nImplement the defined work.\n", encoding="utf-8")
                basis = review_basis(document.read_text(encoding="utf-8"))
                answer = ("## Current review\n\n**Verdict: COMPLETE**\n\n"
                          "Basis as supplied: not copied correctly\n\nThe document sufficiently guides the work.\n")
                handle = self.second_opinion(project, stage=stage, reviewer="", author_output=answer)
                self.assertEqual(handle.snapshot()["state"], "finished")
                saved = document.read_text(encoding="utf-8")
                self.assertIn(f"Basis: {basis}", saved)
                self.assertNotIn("not copied correctly", saved)
                self.assertIn("sufficiently guides", saved)
                facts = assessment_facts(stage, saved)
                self.assertEqual((facts["verdict"], facts["applies"], facts["issues"]),
                                 ("COMPLETE", "current", []))

    def test_conflicting_ai_verdicts_do_not_become_a_complete_review(self):
        project = self.project()
        document = project.root / "Specification.md"
        original = document.read_text(encoding="utf-8")
        for answer in ("Verdict: COMPLETE\nVerdict: INCOMPLETE\n",
                       "Verdict: COMPLETE — INCOMPLETE\n",
                       "Verdict: COMPLETE\nReview verdict: INCOMPLETE\n"):
            with self.subTest(answer=answer):
                handle = self.second_opinion(project, reviewer="", author_output="## Current review\n\n" + answer)
                self.assertEqual(handle.snapshot()["state"], "failed")
                self.assertEqual(document.read_text(encoding="utf-8"), original)

    def test_review_preserves_other_opening_facts_without_duplicate_verdict(self):
        from ora_vibe_coder.status import assessment_facts

        project = self.project()
        document = project.root / "Specification.md"
        answer = ("## Current review\n\nFindings: None\nVerdict: COMPLETE\n\n"
                  "The current Specification sufficiently guides the work.\n")
        handle = self.second_opinion(project, reviewer="", author_output=answer)
        self.assertEqual(handle.snapshot()["state"], "finished")
        saved = document.read_text(encoding="utf-8")
        self.assertIn("Findings: None", saved)
        self.assertEqual(saved.count("Verdict: COMPLETE"), 1)
        self.assertEqual((assessment_facts("specification", saved)["verdict"],
                          assessment_facts("specification", saved)["issues"]), ("COMPLETE", []))

    def test_one_model_review_keeps_document_when_assessment_is_malformed(self):
        project = self.project()
        document = project.root / "Specification.md"
        original = document.read_text(encoding="utf-8")
        handle = self.second_opinion(project, reviewer="", author_output="The specification looks complete.")
        self.assertEqual(handle.snapshot()["state"], "failed")
        self.assertEqual(document.read_text(encoding="utf-8"), original)
        self.assertEqual(len(conversation.turn_folders(project)), 1)
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
        # The shared criteria reach all three passes identically; only the
        # per-pass scaffold differs.
        def shared(request):
            return conversation.section_body(request, "Shared task and criteria — identical for author, evaluator, and reviser")
        self.assertEqual(shared(passes[0]["request"]), shared(passes[1]["request"]))
        self.assertEqual(shared(passes[0]["request"]), shared(passes[2]["request"]))
        self.assertIn("Standing rules for this review pipeline", passes[0]["request"])  # Vendored preamble.
        self.assertIn("UNCERTAINTIES", passes[1]["request"])
        self.assertNotIn("FLAGGED CLAIMS", passes[1]["request"])  # Web verification omitted.
        self.assertIn("Capitulation", passes[2]["request"])
        self.assertIn("guide, not instructions", passes[2]["request"])
        run = conversation.read_reliability_runs(project)[0]
        self.assertEqual((run["tool"], run["reviewer"]), ("codex", "claude"))
        # Neither pass reported its model/provider identity, so lab diversity
        # is honestly unknown — never inferred from the harness names.
        self.assertIsNone(run["same_lab"])
        self.assertEqual((run["rounds"], run["agreement"], run["assessment"]), (1, "partial", "applied"))
        self.assertIn("named import format", run["output"])
        self.assertEqual(run["changes"], "Named the import format.")
        self.assertIn("## VERDICT", run["evaluation"])  # Full evaluation retained one disclosure away.
        document = (project.root / "Specification.md").read_text(encoding="utf-8")
        self.assertIn("## Current review", document)  # The revised assessment was saved.
        self.assertIn("named import format", document)
        # Reliability passes are never real exchanges and never enter the display.
        self.assertEqual(conversation.recent_exchanges(project), [])
        self.assertEqual(conversation.read_conversation(project), [])
        from ora_vibe_coder import reliability
        # The provenance record is static and self-contained: which sources
        # were originally copied, at which revision, with which digests. No
        # test reads the live Ora checkout, so an ordinary update there never
        # fails this application's own tests.
        record = reliability.pins()
        self.assertEqual(record["revision"], reliability.ORA_REVISION)
        self.assertEqual(record["repository"], reliability.ORA_REPOSITORY)
        self.assertEqual(record["sources"], reliability.ORA_SOURCES)
        self.assertEqual(set(record["sources"]), {"preamble", "evaluate", "revise"})
        for name, facts in record["sources"].items():
            with self.subTest(pin=name):
                self.assertEqual(set(facts), {"source", "sha256"})
                self.assertRegex(facts["source"], r"^(boot|frameworks)/[^/].*\.md$")
                self.assertRegex(facts["sha256"], r"^[0-9a-f]{64}$")

    def test_second_opinion_saves_complete_review_with_repeated_heading(self):
        from ora_vibe_coder.status import assessment_facts, basis_text, review_basis

        project = self.project()
        document = project.root / "Specification.md"
        original = document.read_text(encoding="utf-8")
        assessment = ("Stage: Specification\nVerdict: COMPLETE\nBasis: "
                      + review_basis(original) + "\n")
        revision = ("## REVISED ASSESSMENT\n\n## Current review\n\n"
                    + assessment + "\n## CHANGELOG\n\nNo substantive changes.\n")
        handle = self.second_opinion(
            project, iterate=True, author_output="## Current review\n\n" + assessment,
            evaluator_output=evaluation_reply("`pass`"), revision_output=revision)

        saved = document.read_text(encoding="utf-8")
        facts = assessment_facts("specification", saved)
        run = conversation.read_reliability_runs(project)[0]
        self.assertEqual((handle.snapshot()["state"], run["agreement"], run["assessment"]),
                         ("finished", "pass", "applied"))
        self.assertEqual((facts["verdict"], facts["applies"], facts["issues"]),
                         ("COMPLETE", "current", []))
        self.assertEqual(saved.count("## Current review"), 1)
        self.assertEqual(basis_text(saved), basis_text(original))
        self.assertEqual(run["output"], assessment.strip())

    def test_same_lab_label_missing_document_and_stage_refusals(self):
        project = self.project()
        self.second_opinion(project, tool="codex", reviewer="codex")
        run = conversation.read_reliability_runs(project)[0]
        # The same harness is a fact; the lab is still known only from what a
        # run reports, and this run reported no identity: unknown, not "same".
        self.assertIsNone(run["same_lab"])
        self.assertIn("## Current review", (project.root / "Specification.md").read_text(encoding="utf-8"))
        other = self.project("Two")
        (other.root / "Specification.md").unlink()
        with self.assertRaisesRegex(ProjectError, "No Specification document is resolved"):
            conversation.start_assessment(self.registry, other, "codex", "specification", "claude", False)
        with self.assertRaisesRegex(ProjectError, "Specification and Plan workspaces"):
            conversation.start_assessment(self.registry, project, "codex", "programming", "claude", False)
        # When both passes' events do report a provider, the retained records
        # carry it and the derived label states the confirmed fact.
        self.second_opinion(project, tool="codex", reviewer="claude",
                            provider_author="OpenAI", provider_reviewer="Anthropic")
        confirmed = conversation.read_reliability_runs(project)[1]
        self.assertIs(confirmed["same_lab"], False)  # Different labs, now established.
        self.assertEqual((confirmed["author_provider"], confirmed["reviewer_provider"]), ("OpenAI", "Anthropic"))

    def test_pass_local_identity_never_carries_between_passes(self):
        project = self.project()
        # The author's tool reports its identity on its finished event; the
        # reviewer's reports none. The reviewer pass must stay unknown — the
        # shared operation handle never carries the author's report over to
        # the evaluate pass — so lab diversity is unconfirmed, never "same".
        self.second_opinion(project, provider_author="OpenAI", model_author="gpt-5.5-codex")
        run = conversation.read_reliability_runs(project)[0]
        self.assertEqual(run["author_provider"], "OpenAI")
        self.assertEqual(run["reviewer_provider"], "")
        self.assertIsNone(run["same_lab"])  # One side unknown: unconfirmed.
        outcome = self.run_outcome_fields(project)[0]
        self.assertEqual((outcome.get("Author-Model"), outcome.get("Author-Provider")),
                         ("gpt-5.5-codex", "OpenAI"))  # Only what the author's run reported.
        self.assertNotIn("Reviewer-Model", outcome)
        self.assertNotIn("Reviewer-Provider", outcome)
        # When both passes genuinely report, the label states the fact either
        # way: same provider confirms "same lab", different providers
        # confirms "different labs".
        self.second_opinion(project, provider_author="OpenAI", provider_reviewer="OpenAI")
        self.second_opinion(project, provider_author="OpenAI", provider_reviewer="Anthropic")
        same, different = conversation.read_reliability_runs(project)[1:3]
        self.assertIs(same["same_lab"], True)
        self.assertIs(different["same_lab"], False)
        self.assertEqual((different["author_provider"], different["reviewer_provider"]),
                         ("OpenAI", "Anthropic"))

    def test_plan_workspace_second_opinion_routes_consistently(self):
        project = self.project()
        (project.root / "Plan.md").write_text(
            "# Plan\n\n## Approach\n\nOne executable approach.\n", encoding="utf-8")
        self.second_opinion(project, tool="codex", reviewer="claude", stage="planning")
        folders = conversation.turn_folders(project)
        self.assertEqual(len(folders), 3)  # The Plan workspace runs end to end.
        author = conversation.parse_message(
            next(p for p in sorted((folders[0] / "session" / "messages").glob("*.md"))
                 if p.name.endswith("-initiator-to-peer.md")))
        self.assertIn("## Plan\n\nSource:", author["body"])        # Plan materials supplied.
        self.assertIn("actionable", author["body"])               # The planning sufficiency question.
        self.assertNotIn("## Request\n\nSource:", author["body"])  # Exactly the review-plan material set.
        run = conversation.read_reliability_runs(project)[0]
        self.assertEqual(run["stage"], "review-plan")              # One stage key in records and display.
        self.assertEqual((run["state"], run["assessment"]), ("complete", "applied"))
        self.assertIn("## Current review", (project.root / "Plan.md").read_text(encoding="utf-8"))

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
        # The completed author pass is retained; nothing was retried.
        passes = [self.pass_facts(folder) for folder in conversation.turn_folders(project)]
        self.assertEqual([item["purpose"] for item in passes], ["author", "evaluate"])

    def retained_pass(self, project, purpose, reply, run_name=None):
        """One retained pipeline pass recorded without any run outcome note.

        The interrupted mid-run shape on disk: the pass ran and answered, but
        the whole run's outcome was never recorded.
        """
        peer = "claude" if purpose == conversation.PURPOSE_EVALUATE else "codex"
        folder = conversation.reserve_turn_folder(project)
        session = folder / "session"
        conversation.bridge_call(
            ["record", "--session", str(session), "--kind", "session-create",
             "--initiator", "vibe-coder", "--peer", peer, "--mode", "work",
             "--access-path", str(project.root)], "mid-run pass\n")
        note = conversation.bridge_call(
            ["record", "--session", str(session), "--kind", "note"],
            conversation.run_note_body(purpose, "review-specification", peer,
                                       run_name or folder.name, "claude", False, 1))
        note_ref = re.match(r"(\d{4})-", Path(note).name)[1]
        result = subprocess.run(
            [sys.executable, "-m", "bridge", "run", "--session", str(session), "--timeout", "60",
             "--events-jsonl", "--note-ref", note_ref, "--purpose", purpose],
            cwd=str(self.bridge), input="pass request body", capture_output=True,
            text=True, encoding="utf-8", shell=False,
            env={**os.environ, "VIBE_FAKE_REPLY_FILE": self.pass_reply(purpose, reply)})
        self.assertEqual(result.returncode, 0, result.stderr)
        return folder

    def test_mid_pipeline_replies_leave_the_run_open_at_the_record_level(self):
        # A run's terminality is its own outcome note, never its author pass's
        # completion: switching back mid-pipeline — the author answered, the
        # revision still pending — must read open, so the poll that later
        # observes the finished operation refreshes the conversation and the
        # final revised output is displayed instead of staying absent.
        project = self.project()
        author = self.retained_pass(
            project, conversation.PURPOSE_AUTHOR,
            "Stage: Specification\nVerdict: INCOMPLETE\nBasis: " + "b" * 64 + "\n- One deficiency.\n")
        runs = conversation.read_reliability_runs(project)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["state"], "open")  # The author answered; the run has not ended.
        self.assertIsNone(runs[0]["output"])
        self.assertEqual(runs[0]["passes"], [])     # No evaluation or revision ran yet.
        self.retained_pass(project, conversation.PURPOSE_EVALUATE, evaluation_reply("partial"),
                           run_name=author.name)
        runs = conversation.read_reliability_runs(project)
        self.assertEqual(runs[0]["state"], "open")  # The evaluator answered; the revision is still pending.
        self.assertIn("## VERDICT", runs[0]["evaluation"])
        self.assertIsNone(runs[0]["output"])
        # A completed run through the real pipeline still reads complete.
        self.second_opinion(project)
        finished = conversation.read_reliability_runs(project)[1]
        self.assertEqual((finished["state"], finished["assessment"]), ("complete", "applied"))
        self.assertIn("named import format", finished["output"])


class Lifetime(ConversationCase):
    """Switch and quit lifetime: drained close, and reopening without replay."""

    def server(self):
        server = LocalServer(self.home)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01})
        thread.start()

        def close():
            if thread.is_alive():
                server.shutdown()
            thread.join(timeout=5)
            server.server_close()

        self.addCleanup(close)
        return server

    def request(self, server, path, body):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            connection.request("POST", path, json.dumps(body),
                               headers={"Content-Type": "application/json", "X-Ora-Token": server.token})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_fake_long_turn_has_no_automatic_deadline(self):
        project = self.project()
        with patch.dict(os.environ, {"VIBE_FAKE_CAP": "0.03"}):
            handle = self.turn(project, "Wait for the full answer.", delay=0.4)
        self.assertEqual(handle.state, "finished")
        self.assertGreater(handle.duration, 0.4)
        self.assertEqual(len(conversation.turn_folders(project)), 1)
        self.assertEqual(conversation.read_conversation(project)[0]["state"], "complete")

    def test_bundled_bridge_long_turn_and_explicit_stop(self):
        # Only the connector is replaced: parsing, sessions, records, events,
        # no-timeout, and process cleanup come from the actual shipped bundle.
        bundle = Path(conversation.__file__).resolve().parents[1] / "components" / "agent-bridge" / "bridge"
        shim = self.root / "bundled-fixture"
        package = shim / "bridge"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text((bundle / "__init__.py").read_text()
                                            + f"\n__path__.append({str(bundle)!r})\n")
        target = shim / "peer.py"
        reply = "Bundled reply.\n" + no_change_block()
        target.write_text("import os,pathlib,sys,time\n"
                          "sys.stdin.read()\n"
                          "pathlib.Path(os.environ['VIBE_BUNDLE_STARTED']).write_text('started')\n"
                          "time.sleep(float(os.environ['VIBE_BUNDLE_DELAY']))\n"
                          f"print({reply!r})\n")
        (package / "__main__.py").write_text(
            "import os,sys\nfrom bridge import cli,codex,peer\nfrom bridge.connectors import PeerCommand\n"
            f"assert cli.__file__ == {str(bundle / 'cli.py')!r}\n"
            "cli.DEFAULT_TIMEOUT_SECONDS = 0.03\npeer.HEARTBEAT_SECONDS = 0.03\n"
            "def fake(deadline,cwd,**kwargs):\n"
            f"    return PeerCommand(argv=(sys.executable,{str(target)!r}), cwd=cwd, env=tuple(os.environ.items()))\n"
            "codex.build_work_command = fake\nraise SystemExit(cli.main())\n")
        marker = self.root / "bundle-started"
        with patch.object(conversation, "BRIDGE_HOME", shim), patch.dict(
                os.environ, {"VIBE_BUNDLE_STARTED": str(marker), "VIBE_BUNDLE_DELAY": "0.25"}):
            project = self.project("BundledComplete")
            handle = conversation.start_turn(self.registry, project, "codex", "programming", "Wait for the answer.", [])
            self.assertTrue(handle.done.wait(10))
            handle.worker.join(2)
            self.assertEqual(handle.state, "finished", handle.reason)
            self.assertEqual(conversation.read_conversation(project)[0]["reply"], "Bundled reply.\n")
            self.assertGreater(handle.duration, 0.25)
            self.assertEqual(len(conversation.turn_folders(project)), 1)
            marker.unlink()
            with patch.dict(os.environ, {"VIBE_BUNDLE_DELAY": "30"}):
                project = self.project("BundledStop")
                handle = conversation.start_turn(self.registry, project, "codex", "programming", "Stop explicitly.", [])
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(marker.exists())
                self.registry.drain()
            self.assertFalse(handle.worker.is_alive())
            self.assertEqual(handle.state, "interrupted")
            self.assertTrue(handle.outcome_recorded)
            self.assertEqual(handle.live_children(), [])
            turns = conversation.read_conversation(project)
            self.assertEqual((len(turns), turns[0]["state"], turns[0]["reply"]), (1, "interrupted", None))

    def test_stop_during_startup_records_interruption(self):
        project = self.project()
        run = conversation._bridge_run
        def stop_before_run(handle, *args):
            handle.cancel()
            return run(handle, *args)
        with patch.object(conversation, "_bridge_run", side_effect=stop_before_run):
            handle = self.turn(project, "Do not replay this request.")
        handle.worker.join(2)
        self.assertFalse(handle.worker.is_alive())
        self.assertEqual(handle.state, "interrupted")
        self.assertTrue(handle.outcome_recorded)
        self.assertEqual(conversation.read_conversation(project)[0]["state"], "interrupted")
        self.assertEqual(list((project.root / ".vibe").glob("*/session/messages/*-initiator-to-peer.md")), [])

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

    def test_control_c_uses_the_same_stop_path(self):
        from ora_vibe_coder.launcher import serve

        server = LocalServer(self.home)
        project = self.project()
        with patch.dict(os.environ, {"VIBE_FAKE_DELAY": "30"}):
            handle = conversation.start_turn(server.conversation, project, "codex", "programming", "Working", [])
            original_join = threading.Thread.join
            interrupted = []
            def join(thread, timeout=None):
                if thread.name == "Ora Vibe Coder local interface" and not interrupted:
                    interrupted.append(True)
                    raise KeyboardInterrupt()
                return original_join(thread, timeout)
            with patch.object(threading.Thread, "join", join):
                serve(server, no_browser=True)
        self.assertEqual(handle.state, "interrupted")
        self.assertTrue(handle.outcome_recorded)
        self.assertFalse(handle.worker.is_alive())

    def test_quit_interrupts_the_in_flight_turn_without_applying_an_unfinished_reply(self):
        server = self.server()
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
            # No new work is admitted while closing.
            status, refused = self.request(server, "/api/converse",
                                           {"id": key, "tool": "codex", "stage": "programming",
                                            "text": "after stop", "images": []})
            self.assertEqual(status, 400)
            self.assertIn("closing", refused["error"])
            # The server records an interrupted outcome, then exits.
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
            # Wait for the exit itself.
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
        # A dispatched request that never received a reply: the interrupted state on disk.
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


if __name__ == "__main__":
    unittest.main()
