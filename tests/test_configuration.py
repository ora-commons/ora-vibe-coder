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

from ora_vibe_coder import hosts
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
                    request("converse", {"id": project_id, "tool": "codex", "stage": "programming", "text": "Work on the sample.", "images": []})
                    self.assertEqual((turn.call_args.kwargs["model"], turn.call_args.kwargs["effort"]), ("implementation-model", "high"))
                    request("review", {"id": project_id, "stage": "specification", "tool": "claude", "reviewer": "codex", "iterate": False})
                    self.assertEqual(review.call_args.kwargs, {"model": "specification_review-model", "effort": "high",
                                                               "reviewer_model": "specification_second_opinion-model", "reviewer_effort": "low"})
                    request("deliver", {"id": project_id, "step": "implement-plan", "action": "send", "tool": "codex", "text": "Work on the sample."})
                    self.assertEqual((turn.call_args.args[2], turn.call_args.kwargs["model"]), ("codex", "implementation-model"))
                    self.assertIn("review-model", turn.call_args.args[4])  # The Loop reviewer choice rides the instruction.
                    self.assertIn("status: APPROVED", (root / "Sample/Plan.md").read_text())
                    override = {"implementation": {"tool": "claude", "model": "one-time-model", "effort": "low"}}
                    request("deliver", {"id": project_id, "step": "implement-plan", "action": "send", "tool": "claude", "text": "Work on the sample.", "roles": override})
                    self.assertEqual((turn.call_args.args[2], turn.call_args.kwargs["model"], turn.call_args.kwargs["effort"]), ("claude", "one-time-model", "low"))
                preview = request("preview", {"id": project_id, "stage": "programming", "input": "What does this function do?",
                                              "destination": "Codex", "context": {"material": []}})["text"]
                _user, app_section = preview.split("\n\n---\n\n# Framework instructions\n\n", 1)
                self.assertNotIn("Requested harness choices (not verified):", app_section)
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
                with mock.patch.object(hosts, "executable", return_value=[sys.executable, str(fake), str(receipt)]), \
                        mock.patch.object(hosts, "terminal_arguments", side_effect=lambda operation, platform: (["fake-terminal", str(operation)], {})), \
                        mock.patch.object(hosts.subprocess, "run", side_effect=terminal_launch):
                    for action in ("copy", "terminal"):
                        specification = root / "Sample/Specification.md"
                        specification.write_text("# Specification\n\nStatus: DRAFT\n\nKeep files.\n")
                        request("deliver", {"id": project_id, "step": "create-plan", "action": action, "tool": "claude", "text": "Plan the sample."})
                        self.assertIn("status: APPROVED", specification.read_text())
                    self.assertIn('"model": "planning-model"', packets[-1])
                    argv = json.loads(receipt.read_text().splitlines()[-1])
                    self.assertEqual(argv[:-1], ["--model", "planning-model", "--effort", "low"])
                    settings.update(role_defaults={**choices, "planning": {"tool": "codex", "model": "", "effort": ""}})
                    request("deliver", {"id": project_id, "step": "create-plan", "action": "terminal", "tool": "codex", "text": "Plan the sample."})
                    self.assertEqual(len(json.loads(receipt.read_text().splitlines()[-1])), 1)  # Native default: no flags.
                    settings.update(role_defaults={**choices, "planning": {"tool": "hermes", "model": "requested-model", "effort": ""}})
                    before = len(operations)
                    refused = request("deliver", {"id": project_id, "step": "create-plan", "action": "terminal", "tool": "hermes", "text": "Plan the sample."}, expected=400)
                    self.assertIn("cannot accept named model or effort", refused["error"])
                    self.assertEqual(len(operations), before)
                    settings.update(role_defaults=choices)
                self.assertTrue(all(not operation.exists() for operation in operations))
                saved = request("setup", {})["app_settings"]
                self.assertEqual(saved["role_defaults"], choices)
                self.assertTrue(saved["best_guess"])
                self.assertTrue(saved["hide_advisory"])
            finally:
                server.shutdown(); thread.join(); server.server_close()

    def test_project_configuration_is_persistent_and_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            settings = Settings(root / "settings.json")
            global_roles = {"implementation": {"tool": "codex", "model": "global-model", "effort": "high"},
                            "planning": {"tool": "codex", "model": "global-plan", "effort": "high"}}
            settings.update(role_defaults=global_roles, best_guess=True, hide_advisory=True)
            server = LocalServer(root, settings=settings)
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01})
            thread.start()
            def request(action, body):
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                connection.request("POST", "/api/" + action, json.dumps(body), headers={"Content-Type": "application/json", "X-Ora-Token": server.token})
                response = connection.getresponse(); result = json.loads(response.read()); connection.close()
                self.assertEqual(response.status, 200, result)
                return result
            first = request("create", {"directory": "One", "name": "One", "description": "", "goals": ""})["id"]
            second = request("create", {"directory": "Two", "name": "Two", "description": "", "goals": ""})["id"]
            try:
                handle = mock.Mock(turn="fake", retained_images=[])
                handle.snapshot.return_value = {"state": "finished"}
                with mock.patch("ora_vibe_coder.conversation.start_turn", return_value=handle) as turn, \
                        mock.patch("ora_vibe_coder.conversation.require_work_route"), \
                        mock.patch("ora_vibe_coder.conversation.require_build_route"):
                    request("project-settings", {"id": first, "best_guess": False,
                                                 "roles": {"implementation": {"tool": "claude", "model": "project-model", "effort": "low"}}})
                    request("deliver", {"id": first, "step": "implement-plan", "action": "send", "tool": "claude", "text": "Build."})
                    self.assertEqual((turn.call_args.args[2], turn.call_args.kwargs["model"], turn.call_args.kwargs["effort"]),
                                     ("claude", "project-model", "low"))
                    saved = request("project", {"id": first})["configuration"]
                    self.assertEqual(saved["roles"]["implementation"], {"tool": "claude", "model": "project-model", "effort": "low"})
                    self.assertFalse(saved["best_guess"])
                    self.assertEqual(settings.read()["role_defaults"], global_roles)
                    request("deliver", {"id": second, "step": "implement-plan", "action": "send", "tool": "codex", "text": "Build."})
                    self.assertEqual((turn.call_args.args[2], turn.call_args.kwargs["model"]), ("codex", "global-model"))
                    request("project-settings", {"id": first, "clear": True})
                    self.assertEqual(request("project", {"id": first})["configuration"], {})
                    request("deliver", {"id": first, "step": "implement-plan", "action": "send", "tool": "codex", "text": "Build."})
                    self.assertEqual(turn.call_args.kwargs["model"], "global-model")
                    self.assertEqual(settings.read()["role_defaults"], global_roles)
            finally:
                server.shutdown(); thread.join(); server.server_close()
