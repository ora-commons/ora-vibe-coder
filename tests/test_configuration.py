"""Configuration behavior: native metadata and individual role dispatch, no live model calls."""
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

from ora_vibe_coder import conversation, hosts
from ora_vibe_coder.launcher import Settings
from ora_vibe_coder.server import LocalServer


class Configuration(unittest.TestCase):
    def test_codex_inventory_uses_effective_config_and_metadata_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            log = root / "requests.jsonl"
            script = root / "native.py"
            script.write_text('''import json,sys
for line in sys.stdin:
 request=json.loads(line)
 with open(sys.argv[1],"a") as log:log.write(json.dumps(request)+"\\n")
 if "id" not in request:continue
 method=request["method"]
 result={}
 if method=="config/read":result={"config":{"model":"configured-model","model_reasoning_effort":"high"}}
 if method=="model/list":result={"data":[{"model":"configured-model","displayName":"Configured model","supportedReasoningEfforts":[{"reasoningEffort":"low"},{"reasoningEffort":"high"}],"defaultReasoningEffort":"low"},{"model":"recommended-model","isDefault":True}],"nextCursor":None}
 print(json.dumps({"id":request["id"],"result":result}),flush=True)
''')
            with mock.patch.object(hosts, "executable", return_value=[sys.executable, str(script), str(log)]):
                inventory = hosts.model_inventory("codex")
            self.assertEqual(inventory["configured_model"], "configured-model")
            self.assertEqual(inventory["configured_effort"], "high")
            self.assertEqual(inventory["models"][0]["efforts"], ["low", "high"])
            self.assertEqual([json.loads(line)["method"] for line in log.read_text().splitlines()],
                             ["initialize", "initialized", "config/read", "model/list"])

    def test_native_claude_minimax_and_inaccessible_defaults(self):
        reply = {"type": "control_response", "response": {"request_id": "vibe-model-metadata", "subtype": "success",
                 "response": {"models": [{"value": "native-choice", "displayName": "Native choice", "supportedEffortLevels": ["low", "high"]}]}}}
        with mock.patch.object(hosts, "executable", return_value=["native-harness"]), \
                mock.patch.object(hosts.subprocess, "run", return_value=mock.Mock(stdout=json.dumps(reply))) as query:
            inventory = hosts.model_inventory("claude")
            self.assertEqual(inventory["models"][0]["efforts"], ["low", "high"])
            self.assertEqual(inventory["configured_model"], "")
            request = json.loads(query.call_args.kwargs["input"])
            self.assertEqual(request["request"], {"subtype": "initialize"})
            self.assertNotIn("prompt", request)
            self.assertIn("--no-session-persistence", query.call_args.args[0])
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "config.yaml").write_text("provider:\n  local-provider:\n    models:\n      native-model:\n        options:\n          ignored: true\ndefaultModel: local-provider/native-model\n")
            with mock.patch.dict(os.environ, {"MINIMAX_DATA_DIR": directory}), \
                    mock.patch.object(hosts, "executable", return_value=["native-harness"]), \
                    mock.patch.object(hosts.subprocess, "run") as command:
                inventory = hosts.model_inventory("minimax")
                self.assertEqual(inventory["configured_model"], "local-provider/native-model")
                self.assertEqual(inventory["models"][0]["id"], "local-provider/native-model")
                self.assertEqual(inventory["models"][0]["efforts"], [])
                command.assert_not_called()
        with mock.patch.object(hosts, "executable", return_value=None):
            self.assertEqual(hosts.model_inventory("codex")["models"], [])
        with mock.patch.object(hosts, "executable", return_value=["native-harness"]), \
                mock.patch.object(hosts.subprocess, "Popen", side_effect=OSError("Unsupported metadata")):
            self.assertIn("inaccessible or unsupported", hosts.model_inventory("codex")["reason"])
            self.assertEqual(hosts.model_inventory("zcode")["models"], [])

    def test_individual_actions_deliver_distinct_saved_role_choices(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            settings = Settings(root / "settings.json")
            choices = {role: {"tool": tool, "model": role + "-model", "effort": effort} for role, tool, effort in (
                ("specification", "codex", "high"), ("planning", "claude", "low"),
                ("implementation", "codex", "high"), ("review", "claude", "low"),
                ("verification", "claude", "low"), ("correction", "codex", "high"),
                ("specification_review", "claude", "high"), ("specification_second_opinion", "codex", "low"),
                ("planning_review", "codex", "low"), ("planning_second_opinion", "claude", "high"))}
            settings.update(role_defaults=choices, best_guess=True, hide_advisory=True)
            server = LocalServer(root, settings=Settings(settings.path))
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01})
            thread.start()
            def request(action, data, expected=200):
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                connection.request("POST", "/api/" + action, json.dumps(data), headers={"Content-Type": "application/json", "X-Ora-Token": server.token})
                response = connection.getresponse()
                result = json.loads(response.read()); connection.close()
                self.assertEqual(response.status, expected, result)
                return result
            try:
                project_id = request("create", {"directory": "Sample", "name": "Sample", "description": "A sample tool", "goals": "A working tool"})["id"]
                handle = mock.Mock(turn="turn", retained_images=[])
                handle.snapshot.return_value = {"state": "running"}
                with mock.patch("ora_vibe_coder.conversation.start_turn", return_value=handle) as turn, \
                        mock.patch("ora_vibe_coder.conversation.start_assessment", return_value=handle) as review, \
                        mock.patch("ora_vibe_coder.conversation.require_work_route"), \
                        mock.patch("ora_vibe_coder.conversation.require_build_route"):
                    for stage, role in (("specification", "specification"), ("planning", "planning"), ("programming", "implementation"), ("verification", "verification")):
                        request("converse", {"id": project_id, "tool": choices[role]["tool"], "stage": stage, "text": "Work on the sample.", "images": []})
                        self.assertEqual(turn.call_args.args[4], "Work on the sample.")
                        self.assertEqual(turn.call_args.kwargs["model"], choices[role]["model"])
                        self.assertEqual(turn.call_args.kwargs["effort"], choices[role]["effort"])
                    guidance = turn.call_args_list[2].kwargs["application_instructions"]
                    self.assertIn("If the user's authorized work uses the bundled Programming Loop", guidance)
                    self.assertIn("review-model", guidance)
                    for stage in ("specification", "planning"):
                        primary, peer = choices[stage + "_review"], choices[stage + "_second_opinion"]
                        request("review", {"id": project_id, "stage": stage, "tool": primary["tool"], "reviewer": peer["tool"], "iterate": False})
                        self.assertEqual(review.call_args.kwargs, {"model": primary["model"], "effort": primary["effort"], "reviewer_model": peer["model"], "reviewer_effort": peer["effort"]})
                    for step, role in (("create-plan", "planning"), ("implement-plan", "implementation"), ("result", "implementation"), ("verification", "verification"), ("correction", "correction")):
                        request("deliver", {"id": project_id, "step": step, "action": "send", "tool": "zcode", "text": "Work on the sample."})
                        self.assertEqual(turn.call_args.args[2], choices[role]["tool"])
                        self.assertEqual(turn.call_args.kwargs["model"], choices[role]["model"])
                        self.assertEqual(turn.call_args.kwargs["effort"], choices[role]["effort"])
                        if step in {"implement-plan", "correction"}:
                            self.assertIn("review-model", turn.call_args.args[4])
                # An ordinary question keeps the user's exact text in both
                # durable records and the delivered request. Saved review
                # choices belong to the app's conditional instruction section.
                from tests.test_conversation import FAKE_BRIDGE, no_change_block
                bridge = root / "bridge-home"
                (bridge / "bridge").mkdir(parents=True)
                (bridge / "bridge" / "__init__.py").write_text("")
                (bridge / "bridge" / "__main__.py").write_text(FAKE_BRIDGE.replace(
                    "body = sys.stdin.read()", "body = sys.stdin.buffer.read().decode('utf-8')"))
                reply = root / "reply.md"
                reply.write_text("The function explains the sample.\n" + no_change_block())
                user_text = "What does this function do?\r\n\r\nKeep café spacing  \n"
                with mock.patch.object(conversation, "BRIDGE_HOME", bridge), \
                        mock.patch.dict(os.environ, {"VIBE_FAKE_REPLY_FILE": str(reply)}):
                    request("converse", {"id": project_id, "tool": "codex", "stage": "programming", "text": user_text, "images": []})
                    project = server.store.projects[project_id]
                    actual = server.conversation.by_project[str(project.root)]
                    self.assertTrue(actual.done.wait(20), "the fake conversation did not finish")
                    self.assertEqual(actual.state, "finished")
                retained = conversation.read_conversation(project)[-1]
                self.assertEqual(retained["text"].encode("utf-8"), user_text.encode("utf-8"))
                messages = [conversation.parse_message(path) for path in
                            (project.root / ".vibe" / actual.turn / "session" / "messages").glob("*.md")]
                delivered = next(message["body"] for message in messages if message["kind"] == "request")
                user_section, instructions = delivered.split("\n\n# Work-turn instructions\n\n", 1)
                self.assertEqual(user_section.encode("utf-8"), ("# User message\n\n" + user_text).encode("utf-8"))
                self.assertIn(guidance, instructions.split("## Stage instructions", 1)[0])
                # Build's generic Copy route preserves the exact user's words,
                # and supplies the same conditional role guidance as a work
                # turn, whether this is implementation or an ordinary question.
                for instruction in ("Use the Programming Loop to implement the sample.\r\nKeep café spacing  \n", user_text):
                    preview = request("preview", {"id": project_id, "stage": "programming", "input": instruction,
                                                  "destination": "Codex", "context": {"material": []}})["text"]
                    user_section, app_section = preview.split("\n\n---\n\n# Framework instructions\n\n", 1)
                    self.assertEqual(user_section.encode("utf-8"), ("# User request\n\n" + instruction).encode("utf-8"))
                    self.assertIn("## Selected implementation choices\n\n" + guidance, app_section)
                    self.assertIn("These choices do not request implementation or require the Loop for an ordinary question.", app_section)
                    self.assertIn("Codex, model implementation-model (requested), effort high (requested)", app_section)
                    self.assertIn("Claude Code, model review-model (requested), effort low (requested)", app_section)
                # Exercise the real terminal vector with a local fake harness:
                # no model call, native settings change, or desktop is involved.
                receipt = root / "terminal-argv.jsonl"
                fake = root / "fake-harness.py"
                fake.write_text("import json,sys\nwith open(sys.argv[1], 'a') as log: log.write(json.dumps(sys.argv[2:]) + '\\n')\nif '--json' in sys.argv: print(json.dumps({'sessionId': 'sess_sample_receipt'}))\n")
                operations = []
                packets = []
                native_run = hosts.subprocess.run
                def terminal_launch(args, **kwargs):
                    if args[0] != "fake-terminal":
                        return native_run(args, **kwargs)
                    operation = Path(args[-1])
                    operations.append(operation)
                    packets.append((operation / "assignment.md").read_text())
                    self.assertEqual(hosts.run_operation(operation), 0)
                    return mock.Mock(returncode=0)
                with mock.patch.object(hosts, "executable", return_value=[sys.executable, str(fake), str(receipt)]) as executable, \
                        mock.patch.object(hosts, "terminal_arguments", side_effect=lambda operation, platform: (["fake-terminal", str(operation)], {})), \
                        mock.patch.object(hosts.subprocess, "run", side_effect=terminal_launch):
                    for step, role in (("create-plan", "planning"), ("implement-plan", "implementation"), ("result", "implementation"), ("verification", "verification"), ("correction", "correction")):
                        copied = request("deliver", {"id": project_id, "step": step, "action": "copy", "tool": "zcode", "text": "Work on the sample."})
                        self.assertIn(f'"model": "{choices[role]["model"]}"', copied["text"])
                        self.assertIn(f'"effort": "{choices[role]["effort"]}"', copied["text"])
                        self.assertIn("Requested harness choices (not verified)", copied["text"])
                        request("deliver", {"id": project_id, "step": step, "action": "terminal", "tool": "zcode", "text": "Work on the sample."})
                        self.assertEqual(packets[-1], copied["text"])
                        argv = json.loads(receipt.read_text().splitlines()[-1])
                        expected = (["-m", choices[role]["model"], "-c", "model_reasoning_effort=" + choices[role]["effort"]]
                                    if choices[role]["tool"] == "codex" else ["--model", choices[role]["model"], "--effort", choices[role]["effort"]])
                        self.assertEqual(argv[:-1], expected)
                    # External document review is addressed to the independent
                    # Reviewer, including its saved model/effort. A deliberate
                    # other Reviewer uses that harness's native defaults.
                    for stage, purpose in (("specification", "review-specification"), ("planning", "review-plan")):
                        role = stage + "_review"
                        primary = choices[role]
                        destination = hosts.HOSTS[primary["tool"]][0]
                        prepared = request("prepare", {"id": project_id, "stage": purpose, "input": "Review the current document.",
                                                       "destination": destination, "context": {"material": []}, "expected": project.handoff_text()})
                        self.assertIn("Selected receiving harness (a label, not compatibility evidence): " + destination, prepared["text"])
                        self.assertIn(f'"model": "{primary["model"]}"', prepared["text"])
                        self.assertIn(f'"effort": "{primary["effort"]}"', prepared["text"])
                        # Changing global defaults cannot retarget or rewrite
                        # the review that was already prepared and displayed.
                        settings.update(role_defaults={**choices, role: choices[stage]})
                        copied = request("copy", {"id": project_id, "displayed": prepared["text"]})
                        self.assertEqual(copied["text"], prepared["text"])
                        request("continue", {"id": project_id, "displayed": copied["text"], "destination": destination, "route": "terminal"})
                        self.assertEqual(packets[-1], prepared["text"])
                        self.assertEqual(executable.call_args.args[0], primary["tool"])
                        expected = (["-m", primary["model"], "-c", "model_reasoning_effort=" + primary["effort"]]
                                    if primary["tool"] == "codex" else ["--model", primary["model"], "--effort", primary["effort"]])
                        self.assertEqual(json.loads(receipt.read_text().splitlines()[-1])[:-1], expected)
                        with mock.patch.object(hosts, "desktop_application", return_value=root / "Fake.app") as desktop, \
                                mock.patch.object(hosts.subprocess, "run", return_value=mock.Mock(returncode=0)) as launch:
                            request("continue", {"id": project_id, "displayed": copied["text"], "destination": destination, "route": "desktop"})
                            self.assertEqual(desktop.call_args.args[0], primary["tool"])
                            self.assertTrue(launch.call_args.args[0][-1].startswith(primary["tool"] + "://"))
                            self.assertEqual(project.handoff_text(), prepared["text"])
                        settings.update(role_defaults=choices)
                        override = choices[stage]["tool"]
                        destination = hosts.HOSTS[override][0]
                        prepared = request("prepare", {"id": project_id, "stage": purpose, "input": "Review the current document.",
                                                       "destination": destination, "context": {"material": []}, "expected": copied["text"]})
                        self.assertIn('"harness": "' + destination + '", "model": "", "effort": ""', prepared["text"])
                        request("continue", {"id": project_id, "displayed": prepared["text"], "destination": destination, "route": "terminal"})
                        self.assertEqual(executable.call_args.args[0], override)
                        self.assertEqual(len(json.loads(receipt.read_text().splitlines()[-1])), 1)
                    # A previously prepared request retains its choices even
                    # when global defaults change before its manual delivery.
                    prepared = request("prepare", {"id": project_id, "stage": "planning", "input": "Plan the sample.",
                                                   "destination": "Claude Code", "context": {"material": []}, "expected": project.handoff_text()})
                    settings.update(role_defaults={**choices, "planning": {"tool": "codex", "model": "new-default", "effort": "high"}})
                    request("continue", {"id": project_id, "displayed": prepared["text"], "destination": "Claude Code", "route": "terminal"})
                    self.assertEqual(json.loads(receipt.read_text().splitlines()[-1])[:-1], ["--model", "planning-model", "--effort", "low"])
                    settings.update(role_defaults=choices)
                    # Native defaults emit no override flags. Tools whose
                    # interactive contract has no choice flags refuse named
                    # choices and preserve Copy rather than silently dropping them.
                    for host in ("codex", "claude", "minimax", "zcode", "hermes", "qwen"):
                        settings.update(role_defaults={**choices, "planning": {"tool": host, "model": "", "effort": ""}})
                        request("deliver", {"id": project_id, "step": "create-plan", "action": "terminal", "tool": "zcode", "text": "Plan the sample."})
                        argv = json.loads(receipt.read_text().splitlines()[-1])
                        if host in {"codex", "claude", "minimax"}:
                            self.assertEqual(len(argv), 1)
                        if host not in {"codex", "claude"}:
                            settings.update(role_defaults={**choices, "planning": {"tool": host, "model": "requested-model", "effort": ""}})
                            before = len(operations)
                            refused = request("deliver", {"id": project_id, "step": "create-plan", "action": "terminal", "tool": "zcode", "text": "Plan the sample."}, expected=400)
                            self.assertIn("cannot accept named model or effort", refused["error"])
                            self.assertEqual(len(operations), before)
                            copied = request("deliver", {"id": project_id, "step": "create-plan", "action": "copy", "tool": "zcode", "text": "Plan the sample."})
                            self.assertIn('"model": "requested-model"', copied["text"])
                    settings.update(role_defaults=choices)
                self.assertTrue(all(not operation.exists() for operation in operations))
                saved = request("setup", {})["app_settings"]
                self.assertEqual(saved["role_defaults"], choices)
                self.assertTrue(saved["best_guess"])
                self.assertTrue(saved["hide_advisory"])
            finally:
                server.shutdown(); thread.join(); server.server_close()
