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
                        request("deliver", {"id": project_id, "step": step, "action": "send", "tool": choices[role]["tool"], "text": "Work on the sample."})
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
                    self.assertNotIn("## Selected implementation choices", app_section)
                    self.assertNotIn("Requested harness choices (not verified):", app_section)
                    self.assertNotIn("# Codex adapter", app_section)
                    self.assertNotIn("implementation-model", app_section)
                # A deliberate one-time selection wins over saved choices, including native defaults.
                with mock.patch("ora_vibe_coder.conversation.start_turn", return_value=handle) as turn, \
                        mock.patch("ora_vibe_coder.conversation.require_build_route"):
                    request("deliver", {"id": project_id, "step": "implement-plan", "action": "send", "tool": "zcode", "text": user_text})
                    self.assertEqual((turn.call_args.args[2], turn.call_args.kwargs["model"], turn.call_args.kwargs["effort"]), ("zcode", "", ""))
                    self.assertIn(user_text, turn.call_args.args[4])
                    override = {"implementation": {"tool": "claude", "model": "one-time-model", "effort": "low"}}
                    request("deliver", {"id": project_id, "step": "implement-plan", "action": "send", "tool": "claude", "text": user_text, "roles": override})
                    self.assertEqual((turn.call_args.args[2], turn.call_args.kwargs["model"], turn.call_args.kwargs["effort"]), ("claude", "one-time-model", "low"))
                    request("deliver", {"id": project_id, "step": "implement-plan", "action": "send", "tool": "codex", "text": user_text,
                                        "roles": {"implementation": {"tool": "codex", "model": "", "effort": ""}}})
                    self.assertEqual((turn.call_args.kwargs["model"], turn.call_args.kwargs["effort"]), ("", ""))
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
                        copied = request("deliver", {"id": project_id, "step": step, "action": "copy", "tool": choices[role]["tool"], "text": "Work on the sample."})
                        self.assertNotIn("Requested harness choices (not verified)", copied["text"])
                        self.assertNotIn("## Selected implementation choices", copied["text"])
                        request("deliver", {"id": project_id, "step": step, "action": "terminal", "tool": choices[role]["tool"], "text": "Work on the sample."})
                        self.assertIn(f'"model": "{choices[role]["model"]}"', packets[-1])
                        self.assertIn(f'"effort": "{choices[role]["effort"]}"', packets[-1])
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
                    prepared = request("deliver", {"id": project_id, "step": "create-plan", "action": "terminal", "tool": "claude", "text": "Plan the sample."})
                    prepared = {"text": project.handoff_text()}
                    settings.update(role_defaults={**choices, "planning": {"tool": "codex", "model": "new-default", "effort": "high"}})
                    request("continue", {"id": project_id, "displayed": prepared["text"], "destination": "Claude Code", "route": "terminal"})
                    self.assertEqual(json.loads(receipt.read_text().splitlines()[-1])[:-1], ["--model", "planning-model", "--effort", "low"])
                    settings.update(role_defaults=choices)
                    # Native defaults emit no override flags. Tools whose
                    # interactive contract has no choice flags refuse named
                    # choices and preserve Copy rather than silently dropping them.
                    for host in ("codex", "claude", "minimax", "zcode", "hermes", "qwen"):
                        settings.update(role_defaults={**choices, "planning": {"tool": host, "model": "", "effort": ""}})
                        request("deliver", {"id": project_id, "step": "create-plan", "action": "terminal", "tool": host, "text": "Plan the sample."})
                        argv = json.loads(receipt.read_text().splitlines()[-1])
                        if host in {"codex", "claude", "minimax"}:
                            self.assertEqual(len(argv), 1)
                        if host not in {"codex", "claude"}:
                            settings.update(role_defaults={**choices, "planning": {"tool": host, "model": "requested-model", "effort": ""}})
                            before = len(operations)
                            refused = request("deliver", {"id": project_id, "step": "create-plan", "action": "terminal", "tool": host, "text": "Plan the sample."}, expected=400)
                            self.assertIn("cannot accept named model or effort", refused["error"])
                            self.assertEqual(len(operations), before)
                            copied = request("deliver", {"id": project_id, "step": "create-plan", "action": "copy", "tool": host, "text": "Plan the sample."})
                            self.assertNotIn("requested-model", copied["text"])
                    settings.update(role_defaults=choices)
                self.assertTrue(all(not operation.exists() for operation in operations))
                saved = request("setup", {})["app_settings"]
                self.assertEqual(saved["role_defaults"], choices)
                self.assertTrue(saved["best_guess"])
                self.assertTrue(saved["hide_advisory"])
            finally:
                server.shutdown(); thread.join(); server.server_close()

    def test_project_configuration_is_persistent_and_isolated(self):
        from playwright.sync_api import expect, sync_playwright
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            settings = Settings(root / "settings.json")
            global_roles = {"implementation": {"tool": "codex", "model": "global-model", "effort": "high"},
                            "planning": {"tool": "codex", "model": "global-plan", "effort": "high"},
                            "planning_second_opinion": {"tool": "claude", "model": "peer", "effort": "low"}}
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
            native = {"models": [{"id": "project-model", "efforts": ["low", "high"]}], "reason": "Local fake inventory."}
            def ready(peer, **kwargs):
                return {"peer": peer, "ready": True, "work": "supported", "authentication": "confirmed", "warnings": []}
            try:
                with mock.patch("ora_vibe_coder.server.model_inventory", return_value=native), \
                        mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), \
                        mock.patch.object(conversation, "bridge_check", side_effect=ready), sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    try:
                        page = browser.new_page(viewport={"width": 1440, "height": 1100})
                        errors = []; page.on("pageerror", lambda error: errors.append(str(error)))
                        page.goto(server.url)
                        page.locator("#project").select_option(first)
                        page.wait_for_function("() => workspace !== '' && lastFiles !== null")
                        page.locator('[data-stage="plan"]').click()
                        page.locator("#next-step").evaluate("element => element.open = true")
                        chooser = page.locator("#implementation-choice")
                        expect(chooser).to_be_visible()
                        expect(chooser.locator(".role-tool")).to_have_value("codex")
                        chooser.locator(".role-tool").select_option("claude")
                        expect(chooser.locator('.role-model option[value="project-model"]')).to_have_count(1)
                        chooser.locator(".role-model").select_option("project-model")
                        chooser.locator(".role-effort").select_option("low")
                        expect(page.locator("#transition")).to_have_text("Send to Claude Code")
                        # The one-time choice is for implementation; step 3 still writes the Plan.
                        expect(page.locator("#destination")).to_have_value("Codex")
                        captured = []
                        def deliver(route):
                            captured.append(route.request.post_data_json)
                            route.fulfill(json={"turn": "fake", "operation": {"state": "finished", "turn": "fake"}, "images": []})
                        page.route("**/api/deliver", deliver)
                        run_calls = []
                        active = {"run": "fake-active", "state": "running", "step": "planning", "model": "captured-model",
                                  "questions": [], "effective_roles": global_roles, "config": {}}
                        def run_request(route):
                            body = route.request.post_data_json
                            run_calls.append(body)
                            active["config"] = body["config"]
                            route.fulfill(json={"run": active})
                        page.route("**/api/run-start", run_request)
                        page.route("**/api/run-configure", run_request)
                        page.route("**/api/run-stop", lambda route: route.fulfill(json={"run": {"active": None}}))
                        expect(page.locator("#run-completion")).to_be_enabled()
                        page.evaluate("() => stopPolling()")
                        page.locator("#run-completion").click()
                        page.wait_for_function("() => runActive?.run === 'fake-active'")
                        self.assertEqual(run_calls[-1]["config"]["roles"]["implementation"]["tool"], "claude")
                        expect(chooser.locator(".role-tool")).to_have_value("codex")
                        expect(page.locator("#transition")).to_have_text("Send to Codex")
                        expect(page.locator("#destination")).to_have_value("Codex")
                        page.locator("#run-completion").click()
                        page.wait_for_function("() => runActive === null")
                        page.locator("#transition").click()
                        page.locator("#implementation-proceed").click()
                        page.wait_for_function("() => lastOperation?.turn === 'fake'")
                        self.assertEqual(captured[-1]["tool"], "codex")
                        self.assertEqual(captured[-1]["roles"], {})
                        evidence = os.environ.get("VIBE_CONFIGURATION_EVIDENCE")
                        if evidence:
                            Path(evidence).mkdir(parents=True, exist_ok=True)
                            page.screenshot(path=str(Path(evidence) / "consumed-implementation-choice-reset.png"))
                        chooser.locator(".role-tool").select_option("claude")
                        expect(chooser.locator('.role-model option[value="project-model"]')).to_have_count(1)
                        chooser.locator(".role-model").select_option("project-model")
                        chooser.locator(".role-effort").select_option("low")
                        page.locator("#message").fill("  Keep my exact words.  \n")
                        page.locator("#transition").click()
                        expect(page.locator("#implementation-warning")).to_be_visible()
                        page.locator("#implementation-proceed").click()
                        page.wait_for_function("() => document.getElementById('message').value === ''")
                        self.assertEqual(captured[-1]["tool"], "claude")
                        self.assertEqual(captured[-1]["roles"]["implementation"], {"tool": "claude", "model": "project-model", "effort": "low"})
                        self.assertEqual(captured[-1]["text"], "  Keep my exact words.  \n")
                        evidence = os.environ.get("VIBE_CONFIGURATION_EVIDENCE")
                        if evidence:
                            Path(evidence).mkdir(parents=True, exist_ok=True)
                            page.screenshot(path=str(Path(evidence) / "inline-implementation-choice.png"))
                            page.set_viewport_size({"width": 420, "height": 900})
                            page.get_by_role("button", name="Show document", exact=True).click()
                            chooser.scroll_into_view_if_needed()
                            fits = chooser.locator("select").evaluate_all("""selects => selects.every(select => {
                                const canvas = document.createElement('canvas'), context = canvas.getContext('2d');
                                context.font = getComputedStyle(select).font;
                                return context.measureText(select.selectedOptions[0].textContent).width + 40 <= select.clientWidth;
                            })""")
                            self.assertTrue(fits, "The selected one-time tool, model and effort must be readable on a narrow screen.")
                            page.screenshot(path=str(Path(evidence) / "inline-implementation-choice-narrow.png"))
                            page.set_viewport_size({"width": 1440, "height": 1100})
                        page.locator("#configure-path").click()
                        page.locator("#settings-best-guess").uncheck()
                        page.locator("#settings-hide-advisory").uncheck()
                        page.locator('#settings-roles [data-role="planning_second_opinion"] .role-tool').select_option("")
                        page.locator("#project-settings-save").click()
                        expect(page.locator("#settings-panel")).to_be_hidden()
                        saved = request("project", {"id": first})["configuration"]
                        self.assertEqual(saved["roles"]["implementation"]["model"], "project-model")
                        self.assertEqual(settings.read()["role_defaults"], global_roles)
                        self.assertEqual(set(settings.read()["project_defaults"]), {str(root / "One")})
                        server.settings = Settings(settings.path)
                        page.reload()
                        page.wait_for_function("() => project !== null && workspace !== ''")
                        page.locator('[data-stage="plan"]').click()
                        expect(page.locator("#transition")).to_have_text("Send to Claude Code")
                        # Settings must show the same saved project values as Configure Path.
                        page.locator("#settings").click()
                        expect(page.locator('#settings-roles [data-role="implementation"] .role-model')).to_have_value("project-model")
                        expect(page.locator('#settings-roles [data-role="planning_second_opinion"] .role-tool')).to_have_value("")
                        expect(page.locator("#settings-best-guess")).not_to_be_checked()
                        expect(page.locator("#settings-hide-advisory")).not_to_be_checked()
                        if evidence: page.screenshot(path=str(Path(evidence) / "project-settings-reopened.png"))
                        page.locator('#settings-roles [data-role="correction"] .role-tool').select_option("claude")
                        page.locator("#project-settings-save").click()
                        expect(page.locator("#settings-panel")).to_be_hidden()
                        saved = request("project", {"id": first})["configuration"]
                        self.assertEqual(saved["roles"]["implementation"], {"tool": "claude", "model": "project-model", "effort": "low"})
                        self.assertEqual(saved["roles"]["planning_second_opinion"]["tool"], "")
                        self.assertFalse(saved["best_guess"])
                        self.assertFalse(saved["hide_advisory"])
                        # An explicit Use selected harness row keeps the deliberately chosen writer.
                        page.locator("#destination").select_option("Claude Code")
                        page.locator("#configure-path").click()
                        page.locator('#settings-roles [data-role="planning"] .role-tool').select_option("")
                        page.locator("#settings-best-guess").check()
                        page.locator("#settings-hide-advisory").check()
                        page.locator("#configure-save").click()
                        expect(page.locator("#destination")).to_have_value("Claude Code")
                        page.route("**/api/converse", deliver)
                        page.locator("#message").fill("Explain the Plan.")
                        page.locator("#send").click()
                        page.wait_for_function("() => document.getElementById('message').value === ''")
                        self.assertEqual(captured[-1]["tool"], "claude")
                        self.assertEqual(captured[-1]["roles"]["planning"], {"tool": "", "model": "", "effort": ""})
                        page.locator("#configure-path").click()
                        page.locator("#configure-clear").click()
                        page.wait_for_function("() => pendingRunConfig?.best_guess === false && pendingRunConfig?.hide_advisory === false")
                        expect(page.locator("#destination")).to_have_value("Codex")
                        # The next run and a deliberate refresh of an active run use project flags.
                        active["effective_roles"] = saved["roles"]
                        expect(page.locator("#run-completion")).to_be_enabled()
                        page.evaluate("() => stopPolling()")
                        page.locator("#message").fill("Build the saved project.")
                        page.locator("#run-completion").click()
                        expect(page.locator("#run-warning")).to_be_visible()
                        page.locator("#run-warning-continue").click()
                        page.wait_for_function("() => runActive?.run === 'fake-active'")
                        self.assertFalse(run_calls[-1]["config"]["best_guess"])
                        self.assertFalse(run_calls[-1]["config"]["hide_advisory"])
                        page.locator("#configure-path").click()
                        page.locator("#settings-best-guess").check()
                        page.locator("#settings-hide-advisory").check()
                        page.locator("#configure-save").click()
                        page.wait_for_function("() => runActive?.config?.best_guess === true")
                        page.locator("#configure-path").click()
                        page.locator("#configure-clear").click()
                        page.wait_for_function("() => runActive?.config?.best_guess === false && runActive?.config?.hide_advisory === false")
                        self.assertFalse(run_calls[-1]["config"]["best_guess"])
                        self.assertFalse(run_calls[-1]["config"]["hide_advisory"])
                        self.assertEqual(run_calls[-1]["config"]["roles"], saved["roles"])
                        self.assertEqual(page.evaluate("() => runActive.model"), "captured-model")
                        page.evaluate("() => updateRunState({active:null})")
                        page.locator("#project").select_option(second)
                        page.wait_for_function("() => project?.name === 'Two' && workspace !== ''")
                        page.locator('[data-stage="plan"]').click()
                        expect(page.locator("#transition")).to_have_text("Send to Codex")
                        self.assertEqual(errors, [])
                    finally:
                        browser.close()
                handle = mock.Mock(turn="fake", retained_images=[])
                handle.snapshot.return_value = {"state": "finished"}
                with mock.patch.object(conversation, "start_turn", return_value=handle) as turn, \
                        mock.patch.object(conversation, "require_build_route"), \
                        mock.patch.object(conversation, "start_assessment", return_value=handle) as assessment:
                    request("deliver", {"id": first, "step": "implement-plan", "action": "send", "tool": "claude", "text": "Build."})
                    self.assertEqual((turn.call_args.args[2], turn.call_args.kwargs["model"], turn.call_args.kwargs["effort"]), ("claude", "project-model", "low"))
                    request("deliver", {"id": first, "step": "implement-plan", "action": "send", "tool": "claude", "text": "Build.",
                                        "roles": {"implementation": {"tool": "claude", "model": "", "effort": ""}}})
                    self.assertEqual((turn.call_args.kwargs["model"], turn.call_args.kwargs["effort"]), ("", ""))
                    request("project-settings", {"id": first, "roles": {"planning_second_opinion": {"tool": ""}}})
                    request("review", {"id": first, "stage": "planning", "tool": "codex", "reviewer": "", "iterate": False})
                    self.assertEqual(assessment.call_args.args[4], "")
                request("project-settings", {"id": first, "clear": True})
                self.assertEqual(request("project", {"id": first})["configuration"], {})
                self.assertEqual(request("project", {"id": second})["configuration"], {})
                self.assertEqual(settings.read()["role_defaults"], global_roles)
            finally:
                server.shutdown(); thread.join(); server.server_close()
