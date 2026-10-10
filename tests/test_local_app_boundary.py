import http.client
import contextlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest import mock

from ora_vibe_coder import __main__ as app_entry, conversation, hosts
from ora_vibe_coder.installer import install, launcher_files, remove
from ora_vibe_coder.launcher import AppLock, Settings, request_quit, serve
from ora_vibe_coder.project import ProjectStore
from ora_vibe_coder.server import LocalServer, REQUEST_LIMIT


class LocalBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.server = LocalServer(self.home)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01})
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        if self.thread.is_alive():
            self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    def select_project(self, page, project_id):
        if page.locator("#project-controls").is_hidden():
            page.locator("#project-options").click()
        page.locator("#project").select_option(project_id)

    def test_project_header_reclaims_work_space_and_bounds_controls(self):
        try:
            from playwright.sync_api import expect, sync_playwright
        except ImportError:
            self.skipTest("Playwright is not installed for the browser check")
        first = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
        second = self.request("/api/create", {"directory": "Two", "name": "Two", "description": "", "goals": ""})[1]["id"]
        with sync_playwright() as playwright:
            if not Path(playwright.chromium.executable_path).is_file():
                self.skipTest("Playwright's Chromium is not installed for the browser check")
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 720})
                page.goto(self.server.url)
                expect(page.locator("#project-controls")).to_be_visible()
                expect(page.locator("#project-compact")).to_be_hidden()
                self.select_project(page, first)
                page.wait_for_function("() => pollTimer !== null && lastFiles !== null")
                expect(page.locator("#project-compact-name")).to_have_text("One")
                expect(page.locator("#project-controls")).to_be_hidden()
                expect(page.locator("#project-options")).to_have_attribute("aria-expanded", "false")
                compact_top = page.locator("#top").bounding_box()["height"]
                compact_work_y = page.locator("#work-step").bounding_box()["y"]
                expect(page.locator("#message")).to_be_visible()

                for width, height in ((1280, 720), (800, 560)):
                    page.set_viewport_size({"width": width, "height": height})
                    compact_height = page.locator("#top").bounding_box()["height"]
                    page.locator("#project-options").click()
                    expect(page.locator("#project-controls")).to_be_visible()
                    expect(page.locator("#project-options")).to_have_attribute("aria-expanded", "true")
                    expanded_height = page.locator("#top").bounding_box()["height"]
                    self.assertGreater(expanded_height, compact_height)
                    main = page.locator(".top-main").bounding_box()
                    row = page.locator(".project-row").bounding_box()
                    card = page.locator("#project-card").bounding_box()
                    self.assertLessEqual(row["x"] + row["width"], main["x"] + main["width"])
                    self.assertLessEqual(card["x"] + card["width"], main["x"] + main["width"])
                    self.assertLess(abs((row["x"] + row["width"]) - (card["x"] + card["width"])), 1)
                    self.assertFalse(page.locator("#project-card").evaluate("element => element.open"))
                    page.locator("#project-card > summary").click()
                    expect(page.locator("#project-card")).to_have_attribute("open", "")
                    expect(page.locator("#project-name")).to_be_visible()
                    page.locator("#project-options").click()
                    expect(page.locator("#project-controls")).to_be_hidden()
                    expect(page.locator("#project-options")).to_have_attribute("aria-expanded", "false")
                    self.assertLess(page.locator("#top").bounding_box()["height"], expanded_height)

                page.set_viewport_size({"width": 1280, "height": 720})
                self.assertLessEqual(abs(page.locator("#top").bounding_box()["height"] - compact_top), 1)
                self.assertLessEqual(abs(page.locator("#work-step").bounding_box()["y"] - compact_work_y), 1)
                page.locator("#project-options").click()
                self.select_project(page, second)
                expect(page.locator("#project-compact-name")).to_have_text("Two")
                expect(page.locator("#project-controls")).to_be_hidden()
                self.select_project(page, first)
                expect(page.locator("#project-compact-name")).to_have_text("One")
            finally:
                browser.close()

    def test_completed_turn_status(self):
        try:
            from playwright.sync_api import expect, sync_playwright
        except ImportError:
            self.skipTest("Playwright is not installed for the browser check")
        project_id = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
        second_id = self.request("/api/create", {"directory": "Two", "name": "Two", "description": "", "goals": ""})[1]["id"]
        with sync_playwright() as playwright:
            if not Path(playwright.chromium.executable_path).is_file():
                self.skipTest("Playwright's Chromium is not installed for the browser check")
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(self.server.url)
                self.select_project(page, project_id)
                page.wait_for_function("() => pollTimer !== null && lastFiles !== null")
                page.evaluate("() => stopPolling()")
                page.evaluate("operation => updateOperation(operation)",
                              {"turn": "finished-turn", "state": "running", "elapsed_seconds": 5,
                               "last_contact_seconds": 2, "phase": "starting"})
                expect(page.locator("#turn-note")).to_have_text("Working — 5s elapsed, last Bridge contact 2s ago.")
                operation = {"turn": "finished-turn", "state": "finished", "elapsed_seconds": 7,
                             "maintenance": "applied", "warnings": ["Connector version is old."],
                             "bridge_diagnostics": ["Connector version is old."], "visible_warnings": []}
                page.evaluate("operation => updateOperation(operation)", operation)
                expect(page.locator("#turn-note > span")).to_have_text("Reply complete in 7s. Registry updated.")
                expect(page.locator("#turn-note .bridge-details")).not_to_have_attribute("open", "")
                expect(page.locator("#turn-note .bridge-details summary")).to_have_text("Technical details (1)")
                expect(page.locator("#turn-note .bridge-details li")).to_be_hidden()
                page.locator("#turn-note .bridge-details summary").click()
                expect(page.locator("#turn-note .bridge-details li")).to_have_text("Connector version is old.")

                operation.update({"maintenance": "stale", "maintenance_reason": "The Registry changed, so nothing was applied.",
                                  "warnings": [], "bridge_diagnostics": [], "visible_warnings": []})
                page.evaluate("operation => updateOperation(operation)", operation)
                expect(page.locator("#turn-note > span")).to_contain_text("Registry update not applied (stale). The Registry changed")
                expect(page.locator("#turn-note .turn-warning")).to_have_count(0)

                operation.update({
                                  "warnings": ["Connector version is old.", "The outcome note could not be recorded: disk is full.", "Other warning."],
                                  "bridge_diagnostics": ["Connector version is old."],
                                  "visible_warnings": ["The outcome note could not be recorded: disk is full."]})
                page.evaluate("operation => updateOperation(operation)", operation)
                expect(page.locator("#turn-note > span")).to_contain_text("Registry update not applied (stale). The Registry changed")
                expect(page.locator("#turn-note .turn-warning")).to_have_count(2)
                expect(page.locator("#turn-note .turn-warning").first).to_contain_text("outcome note could not be recorded")
                expect(page.locator("#turn-note .turn-warning").last).to_have_text("Other warning.")
                expect(page.locator("#turn-note .bridge-details li")).to_be_hidden()
                page.locator("#turn-note .bridge-details summary").click()
                expect(page.locator("#turn-note .bridge-details li")).to_be_visible()

                operation.update({"state": "failed", "reason": "The coding tool refused the request."})
                page.evaluate("operation => updateOperation(operation)", operation)
                expect(page.locator("#turn-note > span")).to_contain_text("The turn failed: The coding tool refused the request.")

                page.locator("#turn-note .bridge-details").evaluate("element => element.open = false")
                operation.update({"state": "interrupted", "reason": "Stopped by the user. Files already changed remain.",
                                  "artifact": {"role": "Programming Result", "path": "/selected/Programming Result.md",
                                               "outcome": "unchanged", "reason": ""}})
                page.evaluate("operation => updateOperation(operation)", operation)
                expect(page.locator("#turn-note > span")).to_contain_text("Interrupted: Stopped by the user.")
                expect(page.locator("#turn-note .artifact-readback")).to_contain_text("read back unchanged")
                expect(page.locator("#turn-note .bridge-details")).not_to_have_attribute("open", "")

                review = {"turn": "review-run", "stage": "review-specification", "state": "finished",
                          "elapsed_seconds": 9, "maintenance": "applied", "warnings": [],
                          "bridge_diagnostics": [], "visible_warnings": []}
                page.evaluate("operation => updateOperation(operation)", review)
                expect(page.locator("#turn-note > span")).to_have_text("Review completed in 9s. Assessment saved.")
                expect(page.locator("#turn-note")).not_to_contain_text("Registry")

                review.update({"stage": "review-plan", "maintenance": "unsaved",
                               "maintenance_reason": "The document could not be read: permission denied.",
                               "warnings": ["Connector version is old."],
                               "bridge_diagnostics": ["Connector version is old."]})
                page.evaluate("operation => updateOperation(operation)", review)
                expect(page.locator("#turn-note > span")).to_have_text(
                    "Review completed in 9s. Assessment not saved. The document could not be read: permission denied.")
                expect(page.locator("#turn-note .bridge-details li")).to_be_hidden()
                page.evaluate("() => lostContact()")
                expect(page.locator("#turn-note .bridge-details summary")).to_have_text("Technical details (1)")
                expect(page.locator("#turn-note .bridge-details li")).to_be_hidden()
                expect(page.locator("#turn-note .turn-warning")).to_contain_text("Lost contact with the local server")
                page.evaluate("() => { contactRestored(); updateOperation(lastOperation); }")
                expect(page.locator("#turn-note .turn-warning")).to_have_count(0)
                expect(page.locator("#turn-note .bridge-details li")).to_be_hidden()

                page.locator('.rail[data-stage="build"]').click()
                expect(page.get_by_label("What should the AI change or explain in the implementation?")).to_be_visible()
                page.locator("#build-reply-stage").select_option("verification")
                expect(page.locator("#message-label")).to_have_text("Reply to the verification coordinator")
                page.locator('.rail[data-stage="specification"]').click()
                expect(page.locator("#message-label")).to_have_text("What should the AI change or explain in the Specification?")
                page.locator('.rail[data-stage="plan"]').click()
                expect(page.locator("#message-label")).to_have_text("What should the AI change or explain in the Plan?")
                page.evaluate("operation => updateOperation(operation)", {
                    "turn": "long-failed-turn", "stage": "plan", "state": "failed",
                    "reason": "The peer harness reported a failure. " * 80,
                    "warnings": ["The saved Plan is unchanged."],
                    "bridge_diagnostics": [], "visible_warnings": [],
                })
                note = page.locator("#turn-note")
                self.assertTrue(note.evaluate("element => element.scrollHeight > element.clientHeight"))
                self.assertEqual(note.evaluate("element => getComputedStyle(element).overflowY"), "scroll")
                note.evaluate("element => element.scrollTop = element.scrollHeight")
                self.assertGreater(note.evaluate("element => element.scrollTop"), 0)
                self.assertTrue(page.locator("#message").evaluate("element => {"
                    " const input = element.getBoundingClientRect();"
                    " const pane = document.getElementById('work-step-body').getBoundingClientRect();"
                    " return input.height > 0 && input.top >= pane.top && input.bottom <= pane.bottom;"
                    "}"))
                page.evaluate("() => {"
                              " const conversation = document.getElementById('conversation');"
                              " conversation.classList.add('resized');"
                              " conversation.style.setProperty('--conversation-size', '80%');"
                              "}")
                self.assertTrue(page.locator("#message").evaluate("element => {"
                    " const input = element.getBoundingClientRect();"
                    " const pane = document.getElementById('work-step-body').getBoundingClientRect();"
                    " return input.height > 0 && input.top >= pane.top && input.bottom <= pane.bottom;"
                    "}"))
                self.select_project(page, second_id)
                page.wait_for_function("id => currentId === id && !!project && workspace === 'specification'", arg=second_id)
                expect(page.locator("#message-label")).to_have_text("What should the AI change or explain in the Specification?")
                self.select_project(page, project_id)
                page.wait_for_function("id => currentId === id && !!project && workspace === 'specification'", arg=project_id)
                expect(page.locator("#message-label")).to_have_text("What should the AI change or explain in the Specification?")
            finally:
                browser.close()

    def request(self, path, body, headers=None, method="POST"):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        actual = {"Content-Type": "application/json", "X-Ora-Token": self.server.token}
        actual.update(headers or {})
        connection.request(method, path, json.dumps(body), headers=actual)
        response = connection.getresponse()
        data = response.read()
        result = response.status, json.loads(data) if response.getheader("Content-Type", "").startswith("application/json") else data, dict(response.getheaders())
        connection.close()
        return result

    def synthetic_release(self):
        """A disposable package exercises setup without held product Markdown."""
        source = self.home / "synthetic release"
        files = {
            "ora_vibe_coder/__init__.py": "",
            "ora_vibe_coder/__main__.py": "def main():\n    return None\n",
            "ora_vibe_coder/server.py": "BOUNDARY = 'synthetic application'\n",
            "ora_vibe_coder/static/index.html": "<!doctype html><title>synthetic application</title>\n",
            "plugins/ora-vibe-coder/VERSION": "0.2.0\n",
            "plugins/ora-vibe-coder/references/shared-contract.md": "# Synthetic shared source\n",
            "plugins/ora-vibe-coder/frameworks/stage.md": "# Synthetic stage source\n",
        }
        for name in ("ora-specification", "ora-planning", "ora-programming", "ora-verification", "ora-vibe-coder"):
            files[f"plugins/ora-vibe-coder/skills/{name}/SKILL.md"] = (
                "---\nname: " + name + "\ndescription: Synthetic installer fixture.\n---\n"
                "Read [shared](../../references/shared-contract.md).\n"
            )
        for host in hosts.HOSTS:
            files[f"plugins/ora-vibe-coder/resources/programming-loop/adapters/{host}.md"] = f"# Synthetic {host} operations\n"
        files["plugins/ora-vibe-coder/resources/programming-loop/VERSION"] = "1.0.0\n"
        files["plugins/ora-vibe-coder/resources/programming-loop/scripts/install.py"] = '''
import argparse, json, shutil
from pathlib import Path

HOSTS = {"codex": ".codex", "claude": ".claude", "zcode": ".zcode", "hermes": ".hermes", "qwen": ".qwen", "minimax": ".minimax"}
parser = argparse.ArgumentParser()
parser.add_argument("action", choices=("install", "remove", "install-check", "remove-check"))
parser.add_argument("--host", choices=HOSTS, required=True)
parser.add_argument("--home", type=Path, required=True)
args = parser.parse_args()
skill = args.home / HOSTS[args.host] / "skills/programming-loop"
if args.action == "install-check" or args.action == "remove-check":
    raise SystemExit(0)
if args.action == "install":
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text("synthetic loop entry")
    (skill / "SOURCE.json").write_text(json.dumps({"component": "programming-loop", "source": "programming-loop"}))
elif skill.exists():
    shutil.rmtree(skill)
'''
        for name, text in files.items():
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        # The release ships the reviewed Bridge runtime exactly as pinned.
        shutil.copytree(
            Path(__file__).resolve().parents[1] / "components/agent-bridge",
            source / "components/agent-bridge",
        )
        return source

    def test_first_specification_suggestion_and_message_file_selection(self):
        try:
            from playwright.sync_api import expect, sync_playwright
        except ImportError:
            self.skipTest("Playwright is not installed for the browser check")
        project_id = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
        other_id = self.request("/api/create", {"directory": "Two", "name": "Two", "description": "", "goals": ""})[1]["id"]
        shared = self.home / "Other notes"
        shared.mkdir()
        note = shared / "Outside context.md"
        note.write_text("A note from another folder.\n", encoding="utf-8")
        submitted = []
        with sync_playwright() as playwright:
            if not Path(playwright.chromium.executable_path).is_file():
                self.skipTest("Playwright's Chromium is not installed for the browser check")
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.route("**/api/converse", lambda route: (
                    submitted.append(route.request.post_data_json),
                    route.fulfill(status=400, content_type="application/json", body='{"error":"Test stopped before dispatch."}')
                ))
                page.goto(self.server.url)
                self.select_project(page, project_id)
                expect(page.locator("#message")).to_have_attribute("placeholder", re.compile("Read the relevant documents"))
                expect(page.locator("#message-suggestion-note")).to_be_visible()
                page.locator("#message").fill("My own instruction")
                expect(page.locator("#message-suggestion-note")).to_be_hidden()
                page.locator("#message").fill("")
                page.locator("#add-message-files").click()
                expect(page.locator("#file-title")).to_have_text("Add files to this message")
                page.locator("#file-path").fill(str(shared))
                page.locator("#file-go").click()
                page.locator("#file-list button", has_text=note.name).click()
                page.locator("#file-cancel").click()
                expect(page.locator("#message-files")).to_contain_text(note.name)
                page.locator("#destination").select_option(label="Codex")
                page.locator("#message").press("Enter")
                expect(page.locator("#notice")).to_contain_text("Test stopped before dispatch")
                self.assertEqual(submitted[0]["text"], page.locator("#message").get_attribute("placeholder"))
                self.assertEqual(submitted[0]["files"], [str(note)])
                expect(page.locator("#message-files")).to_contain_text(note.name)
                page.evaluate("() => Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {writeText: () => new Promise((resolve, reject) => { window.rejectClipboard = reject; document.body.dataset.clipboardPending = 'true'; })}})")
                page.locator("#copy-current").click()
                expect(page.locator("body")).to_have_attribute("data-clipboard-pending", "true")
                self.select_project(page, other_id)
                expect(page.locator("#project-name")).to_have_text("Two")
                page.evaluate("window.rejectClipboard(new Error('clipboard denied'))")
                expect(page.locator("#raw")).not_to_contain_text("A note from another folder")
                expect(page.locator("#reader")).not_to_contain_text("A note from another folder")
                page.locator('.rail[data-stage="plan"]').click()
                expect(page.locator("#message-suggestion-note")).to_be_hidden()
            finally:
                browser.close()

    def test_coding_tool_follows_project_across_stages_without_another_readiness_check(self):
        try:
            from playwright.sync_api import expect, sync_playwright
        except ImportError:
            self.skipTest("Playwright is not installed for the browser check")

        first = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
        second = self.request("/api/create", {"directory": "Two", "name": "Two", "description": "", "goals": ""})[1]["id"]
        overview = self.home / "Two" / "Project.md"
        overview.write_text(overview.read_text(encoding="utf-8").replace("Verification: NOT STARTED", "Verification: PASSED"), encoding="utf-8")
        def ready(peer, **kwargs):
            if peer == "qwen":
                return {"peer": peer, "ready": False, "work": "unsupported", "authentication": "unknown", "warnings": []}
            if peer == "claude":
                return {"peer": peer, "ready": True, "work": "supported", "authentication": "unknown", "warnings": []}
            return {"peer": peer, "ready": True, "work": "supported", "authentication": "confirmed", "warnings": []}

        with mock.patch("ora_vibe_coder.conversation.bridge_check", side_effect=ready) as probes, \
                mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), \
                mock.patch.object(hosts, "desktop_application", side_effect=lambda host, platform=None: None if host == "qwen" else Path("/Applications") / hosts.DESKTOP_APPS[host]):
            with sync_playwright() as playwright:
                if not Path(playwright.chromium.executable_path).is_file():
                    self.skipTest("Playwright's Chromium is not installed for the browser check")
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.goto(self.server.url)
                    self.select_project(page, first)
                    expect(page.locator("#stage-title")).to_have_text("Specification")
                    self.assertEqual(page.locator(".project-row .step-number").inner_text(), "1")
                    self.assertEqual(page.locator("#project-card .step-number").inner_text(), "2")
                    self.assertEqual(page.locator(".first-step .step-number").inner_text(), "3")
                    self.assertEqual([page.locator(f"#{step} .step-number").inner_text()
                                      for step in ("work-step", "review-step", "next-step")], ["4", "5", "6"])
                    self.assertEqual(page.locator("#split").get_attribute("data-mode"), "split")
                    self.assertEqual(page.locator("#split").get_attribute("data-orientation"), "split")
                    self.assertEqual(page.locator("#split-flip, #expand-chat, #expand-doc").count(), 0)
                    head = page.locator("#stage-panel").bounding_box()
                    title = page.locator("#stage-title").bounding_box()
                    tool = page.locator(".first-step").bounding_box()
                    self.assertLess(abs(title["x"] + title["width"] / 2 - (head["x"] + head["width"] / 2)), 5)
                    self.assertLess(tool["x"] + tool["width"], title["x"])
                    rail_widths = [rail.bounding_box()["width"] for rail in page.locator(".rail").all()]
                    self.assertLess(max(rail_widths) - min(rail_widths), 1)
                    self.assertTrue(all(abs(width - 32) < 1 for width in rail_widths))
                    self.assertGreater(float(page.locator("#stage-title").evaluate("element => getComputedStyle(element).fontSize").removesuffix("px")), 20)
                    self.assertEqual(page.locator("#work-step summary").count(), 0)
                    expect(page.locator("#work-step-body")).to_be_visible()
                    page.locator("#conversation").evaluate("element => { for (let i = 0; i < 30; i++) { const line = document.createElement('p'); line.textContent = `Saved conversation line ${i}`; line.style.minHeight = '70px'; element.appendChild(line); } }")
                    scroll = page.locator("#conversation").evaluate("element => { const before = [element.clientHeight, element.scrollHeight]; element.scrollTop = element.scrollHeight; return [...before, element.scrollTop]; }")
                    self.assertGreater(scroll[1], scroll[0])
                    self.assertGreater(scroll[2], 0)
                    expect(page.locator("#message")).to_be_visible()
                    right = page.locator("#pane-doc").bounding_box()
                    review = page.locator("#review-step").bounding_box()
                    next_step = page.locator("#next-step").bounding_box()
                    self.assertGreaterEqual(review["x"], right["x"])
                    self.assertGreaterEqual(next_step["y"], review["y"] + review["height"])
                    split = page.locator("#split").bounding_box()
                    footer = page.locator(".flow-footer").bounding_box()
                    self.assertLessEqual(abs(split["y"] + split["height"] - footer["y"]), 1)
                    self.assertLess(footer["height"], 45)
                    page.set_viewport_size({"width": 800, "height": 900})
                    expect(page.locator("#single-toggle")).to_be_visible()
                    expect(page.locator("#split")).to_have_attribute("data-mode", "chat")
                    page.locator("#single-toggle").click()
                    expect(page.locator("#split")).to_have_attribute("data-mode", "doc")
                    page.set_viewport_size({"width": 1280, "height": 720})
                    expect(page.locator("#split")).to_have_attribute("data-mode", "split")
                    page.locator("#destination").select_option(label="Codex")
                    expect(page.locator("#readiness")).to_contain_text("Codex: ready")
                    page.set_viewport_size({"width": 1600, "height": 900})
                    tool = page.locator(".first-step").bounding_box()
                    recheck = page.locator("#recheck").bounding_box()
                    self.assertLessEqual(tool["x"] + tool["width"] - (recheck["x"] + recheck["width"]), 12)
                    page.set_viewport_size({"width": 1280, "height": 720})
                    checked = probes.call_count

                    page.locator('.rail[data-stage="plan"]').click()
                    expect(page.locator("#stage-title")).to_have_text("Plan")
                    self.assertTrue(all(abs(rail.bounding_box()["width"] - 32) < 1 for rail in page.locator(".rail").all()))
                    self.assertEqual(page.locator("#destination").input_value(), "Codex")
                    self.assertIn("Codex: ready", page.locator("#readiness").inner_text())
                    self.assertEqual(probes.call_count, checked)

                    page.locator("#destination").select_option(label="Claude Code")
                    page.locator('.rail[data-stage="specification"]').click()
                    expect(page.locator("#stage-title")).to_have_text("Specification")
                    self.assertEqual(page.locator("#destination").input_value(), "Claude Code")

                    self.select_project(page, second)
                    expect(page.locator("#project-name")).to_have_text("Two")
                    expect(page.locator("#stage-panel")).to_be_visible()
                    expect(page.locator("#destination")).to_have_value("")
                    self.select_project(page, first)
                    expect(page.locator("#project-name")).to_have_text("One")
                    expect(page.locator("#destination")).to_have_value("Claude Code")
                    page.locator('.rail[data-stage="plan"]').click()
                    page.locator("#portable-handoff").evaluate("element => element.open = true")
                    page.locator("#prepare").click()
                    expect(page.locator("#result-title")).to_have_text("External Plan review request")
                    actions = [page.locator(f"#{item}").bounding_box() for item in ("continue", "terminal", "copy")]
                    self.assertTrue(all(abs(action["y"] - actions[0]["y"]) < 1 for action in actions))
                    self.assertTrue(all(left["x"] + left["width"] <= right["x"] for left, right in zip(actions, actions[1:])))
                    page.locator("#prepared").evaluate("element => element.style.width = '240px'")
                    narrow = page.locator(".prepared-actions").bounding_box()
                    actions = [page.locator(f"#{item}").bounding_box() for item in ("continue", "terminal", "copy")]
                    self.assertTrue(all(abs(action["y"] - actions[0]["y"]) < 1 for action in actions))
                    self.assertLessEqual(max(action["x"] + action["width"] for action in actions), narrow["x"] + narrow["width"] + 1)
                    page.locator("#prepared").evaluate("element => element.style.width = ''")
                    with mock.patch("ora_vibe_coder.server.continue_in", return_value={"message": "Desktop request opened."}) as opened:
                        page.locator("#continue").click()
                        expect(page.locator("#notice")).to_have_text("Desktop request opened.")
                        self.assertEqual(opened.call_args.kwargs["route"], "desktop")
                    with mock.patch("ora_vibe_coder.server.continue_in", return_value={"message": "Terminal request opened."}) as opened:
                        page.locator("#terminal").click()
                        expect(page.locator("#notice")).to_have_text("Terminal request opened.")
                        self.assertEqual(opened.call_args.kwargs["route"], "terminal")
                    expect(page.locator("#prepared-path")).to_have_value(str(self.home / "One" / "Handoff.md"))
                    page.locator("#copy-path").click()
                    expect(page.locator("#notice")).to_contain_text(re.compile("Saved file path copied|saved file path is selected"))
                    page.locator("#next-step").evaluate("element => element.open = true")
                    page.locator("#transition").click()
                    expect(page.locator("#result-title")).to_have_text("Implementation request")
                    expect(page.locator("#continue")).to_have_text("Open Claude Code desktop with request")
                    expect(page.locator("#continue")).to_be_enabled()
                    expect(page.locator("#terminal")).to_have_text("Open Claude Code in Terminal")
                    expect(page.locator("#terminal")).to_be_enabled()
                    expect(page.locator("#readiness")).to_contain_text("sign-in unconfirmed")
                    page.evaluate("() => { readinessState.peers.find(peer => peer.peer === 'claude').authentication = 'required'; updateHost(); }")
                    expect(page.locator("#terminal")).to_be_disabled()
                    page.evaluate("() => { readinessState.peers.find(peer => peer.peer === 'claude').authentication = 'unknown'; updateHost(); }")
                    expect(page.locator("#terminal")).to_be_enabled()
                    page.locator("#destination").select_option(label="Qwen Code")
                    expect(page.locator("#continue")).to_be_disabled()
                    expect(page.locator("#terminal")).to_be_disabled()
                    expect(page.locator("#copy")).to_be_enabled()
                    page.locator("#destination").select_option(label="Claude Code")
                    implementation = self.home / "One" / "One — Implementation Request.md"
                    expect(page.locator("#prepared-path")).to_have_value(str(implementation))
                    self.assertIn("Implement the current Plan", implementation.read_text(encoding="utf-8"))
                    self.assertIn("Framework instructions", implementation.read_text(encoding="utf-8"))
                    self.assertIn("Review the current Plan", (self.home / "One" / "Handoff.md").read_text(encoding="utf-8"))
                    expect(page.locator("#reader")).to_contain_text("Implement the current Plan")
                    page.locator("#copy").click()
                    expect(page.locator("#implementation-warning")).to_be_visible()
                    expect(page.locator("#implementation-warning-text")).to_contain_text("Specification")
                    expect(page.locator("#implementation-warning-text")).to_contain_text("Plan")
                    page.locator("#implementation-back").click()
                    expect(page.locator("#implementation-warning")).not_to_be_visible()
                    implementation.write_text("My edited implementation request", encoding="utf-8")
                    page.locator("#transition").click()
                    expect(page.locator("#result-kind")).to_contain_text("Existing implementation request")
                    self.assertEqual(implementation.read_text(encoding="utf-8"), "My edited implementation request")
                    expect(page.locator("#prepared-path")).to_have_value(str(implementation))
                    page.locator("#transition").click()
                    expect(page.locator("#result-kind")).to_have_text("Prepared request · Not sent")
                    self.assertIn("Framework instructions", implementation.read_text(encoding="utf-8"))

                    from ora_vibe_coder.status import review_basis
                    for label in ("Specification", "Plan"):
                        document = self.home / "One" / f"{label}.md"
                        original = document.read_text(encoding="utf-8")
                        # The app's own assessment save format (#57): a content-v2
                        # basis, so a later edit truthfully reads as "earlier".
                        reviewed = original + f"\n## Current review\n\nStage: {label}\nVerdict: COMPLETE\nBasis: I read the current {label}; its SHA-256 content hash is `<basis>`.\nBasis format: content-v2\n"
                        document.write_text(reviewed.replace("<basis>", review_basis(reviewed)), encoding="utf-8")
                    assessments = self.request("/api/project", {"id": first})[1]["assessments"]
                    for stage in ("specification", "planning"):
                        self.assertEqual(assessments[stage]["verdict"], "COMPLETE")
                        self.assertEqual(assessments[stage]["applies"], "current")
                    page.locator("#refresh").click()
                    expect(page.locator("#notice")).to_contain_text("Saved files reread")
                    expect(page.locator("#assessment")).to_have_text("COMPLETE")
                    expect(page.locator("#review-step-title")).to_have_text("Review the Plan")
                    self.assertEqual(page.locator(".result-head #assessment").count(), 0)
                    verdict = page.locator("#assessment").bounding_box()
                    review_bar = page.locator("#review-step > summary").bounding_box()
                    self.assertLess(abs(verdict["x"] + verdict["width"] / 2 - (review_bar["x"] + review_bar["width"] / 2)), 5)
                    columns = page.locator("#split").evaluate("element => element.style.gridTemplateColumns")
                    page.locator("#split").evaluate("element => element.style.gridTemplateColumns = 'minmax(200px, 1fr) 6px 240px'")
                    page.locator("#review-step-title").evaluate("element => element.textContent = 'Review the Specification'")
                    narrow_title = page.locator("#review-step .review-label").bounding_box()
                    narrow_verdict = page.locator("#assessment").bounding_box()
                    narrow_bar = page.locator("#review-step > summary").bounding_box()
                    self.assertLessEqual(narrow_title["y"] + narrow_title["height"], narrow_verdict["y"])
                    self.assertLess(abs(narrow_verdict["x"] + narrow_verdict["width"] / 2 - (narrow_bar["x"] + narrow_bar["width"] / 2)), 5)
                    page.locator("#review-step-title").evaluate("element => element.textContent = 'Review the Plan'")
                    page.locator("#split").evaluate("(element, value) => element.style.gridTemplateColumns = value", columns)
                    for item in ("label", "select", "button"):
                        control = page.locator(f".result-tools {item}").bounding_box()
                        self.assertTrue(
                            verdict["x"] + verdict["width"] <= control["x"]
                            or control["x"] + control["width"] <= verdict["x"]
                            or verdict["y"] + verdict["height"] <= control["y"]
                            or control["y"] + control["height"] <= verdict["y"],
                            f"The COMPLETE verdict overlaps the document {item} control",
                        )
                    page.locator("#copy").click()
                    expect(page.locator("#notice")).to_contain_text(re.compile("Full raw Markdown copied|Clipboard access"))
                    expect(page.locator("#implementation-warning")).not_to_be_visible()
                    plan = self.home / "One" / "Plan.md"
                    valid_plan = plan.read_text(encoding="utf-8")
                    plan.write_text(valid_plan.replace("SHA-256 content hash", "unidentified hash"), encoding="utf-8")
                    page.locator("#refresh").click()
                    expect(page.locator("#assessment")).to_have_text("COMPLETE")
                    page.locator("#copy").click()
                    expect(page.locator("#implementation-warning")).not_to_be_visible()
                    # An older clear review without a fingerprint still lets
                    # the user use the completed Plan; its tooltip states the
                    # document-version uncertainty instead of blocking work.
                    plan.write_text(re.sub(r"(?m)^Basis:.*\n", "", valid_plan), encoding="utf-8")
                    page.locator("#refresh").click()
                    expect(page.locator("#assessment")).to_have_text("COMPLETE")
                    expect(page.locator("#assessment")).to_have_attribute(
                        "title", re.compile("does not identify which document version"))
                    page.locator("#notice").evaluate("element => element.textContent = ''")
                    page.locator("#copy").click()
                    expect(page.locator("#notice")).to_contain_text(re.compile("Full raw Markdown copied|Clipboard access"))
                    expect(page.locator("#implementation-warning")).not_to_be_visible()
                    plan.write_text(valid_plan.replace("## Current review", "A new requirement.\n\n## Current review"), encoding="utf-8")
                    page.locator("#refresh").click()
                    page.locator("#copy").click()
                    expect(page.locator("#implementation-warning-text")).to_contain_text("Plan was changed after its review")
                    page.locator("#implementation-back").click()
                    plan.write_text(valid_plan, encoding="utf-8")
                    page.locator("#refresh").click()
                    expect(page.locator("#assessment")).to_have_text("COMPLETE")
                    implementation.write_text("Edited again after preparation", encoding="utf-8")
                    page.locator("#copy").click()
                    expect(page.locator("#result-kind")).to_contain_text("Saved request changed")
                    expect(page.locator("#prepared-path")).to_have_value(str(implementation))
                    page.locator("#copy").click()
                    expect(page.locator("#notice")).to_contain_text(re.compile("Full raw Markdown copied|Clipboard access"))
                    page.locator("#assessment").click()
                    self.assertFalse(page.locator("#review-step").evaluate("element => element.open"))

                    self.select_project(page, second)
                    expect(page.locator("#project-name")).to_have_text("Two")
                    expect(page.locator("#stage-panel")).to_be_visible()
                    page.locator("#destination").select_option(label="Codex")
                    page.locator('.rail[data-stage="build"]').click()
                    expect(page.locator("#stage-title")).to_have_text("Build & Verify")
                    expect(page.locator('.rail[data-stage="build"] .rail-label')).to_have_text("Build & Verify")
                    expect(page.locator("#work-step-title")).to_have_text("Work with AI on the implementation")
                    self.assertTrue(all(abs(rail.bounding_box()["width"] - 32) < 1 for rail in page.locator(".rail").all()))
                    self.assertEqual([page.locator(f"#{step} .step-number").inner_text()
                                      for step in ("result-step", "review-step", "next-step")], ["5", "6", "7"])
                    expect(page.locator("#reader")).to_contain_text("No saved Programming Result or Verification Report found")
                    expect(page.locator("#result-status")).to_have_text("NO RESULT")
                    expect(page.locator("#assessment")).to_have_text("NOT VERIFIED")
                    expect(page.locator('.rail[data-stage="build"] .status-icon')).to_have_text("○")
                    expect(page.locator("#project-completion")).to_be_hidden()
                    result_file = self.home / "Two" / "Programming Result.md"
                    result_file.write_text("# Built work\n\nThe implementation was delivered.\n", encoding="utf-8")
                    page.locator("#refresh").click()
                    expect(page.locator("#document")).to_have_value("Programming Result.md")
                    expect(page.locator("#result-status")).to_have_text("RESULT UNCLEAR")
                    result_file.write_bytes(b"\xff")
                    page.locator("#refresh").click()
                    expect(page.locator("#result-status")).to_have_text("COULD NOT READ")
                    expect(page.locator("#result-status")).to_have_attribute("title", re.compile("Not readable UTF-8"))
                    result_file.write_text("# Built work\n\nThe implementation was delivered.\n", encoding="utf-8")
                    page.locator("#refresh").click()
                    expect(page.locator("#result-status")).to_have_text("RESULT UNCLEAR")
                    page.locator("#destination").select_option("")
                    page.locator("#result-step").evaluate("element => element.open = true")
                    page.locator("#request-result").click()
                    expect(page.locator("#build-action-copy")).to_be_enabled()
                    expect(page.locator("#build-action-send")).to_be_disabled()
                    page.locator("#build-action-cancel").click()
                    page.locator("#review-step").evaluate("element => element.open = true")
                    expect(page.locator("#verification-choice")).to_be_visible()
                    page.locator("#verification-verifier").select_option(label="Claude Code")
                    copied_verification = []
                    page.on("request", lambda request: copied_verification.append(request.post_data_json)
                            if request.url.endswith("/api/preview") and request.post_data_json.get("stage") == "verification" else None)
                    page.locator("#review").click()
                    expect(page.locator("#build-action-dialog")).to_be_visible()
                    expect(page.locator("#build-action-copy")).to_be_enabled()
                    expect(page.locator("#build-action-send")).to_be_disabled()
                    page.locator("#build-action-copy").click()
                    expect(page.locator("#notice")).to_contain_text(re.compile("independent reviewer|Clipboard access"))
                    self.assertEqual(copied_verification[-1]["destination"], "External AI chat")
                    self.assertIn("selected Claude Code as the independent verifier", copied_verification[-1]["input"])
                    page.locator("#destination").select_option(label="Codex")
                    result_file.write_text("# Built work\n\nProgramming completed 8 October 2026 under the approved Plan. The Specification review was COMPLETE.\n\nActual programming result.\n", encoding="utf-8")
                    page.locator("#refresh").click()
                    expect(page.locator("#document")).to_have_value("Programming Result.md")
                    expect(page.locator("#reader")).to_contain_text("Actual programming result")
                    expect(page.locator("#result-status")).to_have_text("COMPLETE")
                    expect(page.locator("#assessment")).to_have_text("NOT VERIFIED")
                    expect(page.locator("#project-completion")).to_be_hidden()
                    report_file = self.home / "Two" / "Verification Report.md"
                    report_file.write_text("# Independent review\n\nNo verdict stated.\n", encoding="utf-8")
                    page.locator("#refresh").click()
                    expect(page.locator("#assessment")).to_have_text("VERDICT UNCLEAR")
                    report_file.write_text("# Independent review\n\nVerdict: NOT PASSED\n\nA finding.\n", encoding="utf-8")
                    expect(page.locator("#document")).to_have_value("Verification Report.md", timeout=7000)
                    expect(page.locator("#reader")).to_contain_text("A finding")
                    expect(page.locator("#assessment")).to_have_text("NOT PASSED")
                    expect(page.locator('.rail[data-stage="build"] .status-icon')).to_have_text("!")
                    expect(page.locator("#project-completion")).to_be_hidden()
                    report_file.write_text("# Independent review\n\n**Verdict: PASSED** (latest review)\n\nAll checks passed.\n", encoding="utf-8")
                    expect(page.locator("#assessment")).to_have_text("PASSED", timeout=7000)
                    expect(page.locator('.rail[data-stage="build"] .status-icon')).to_have_text("✓")
                    page.locator("#project-options").click()
                    expect(page.locator("#project-completion")).to_be_visible()
                    for status, bar in (("#result-status", "#result-step > summary"),
                                        ("#assessment", "#review-step > summary"),
                                        ("#project-completion", "#project-card > summary")):
                        word = page.locator(status).bounding_box()
                        heading = page.locator(bar).bounding_box()
                        self.assertLess(abs(word["x"] + word["width"] / 2 -
                                            (heading["x"] + heading["width"] / 2)), 5)
                    green = page.evaluate("""() => { const probe = document.createElement('span');
                        probe.style.color = 'var(--ovc-green)'; document.body.append(probe);
                        const color = getComputedStyle(probe).color; probe.remove(); return color; }""")
                    for status in ("#result-status", "#assessment", "#project-completion"):
                        self.assertEqual(page.locator(status).evaluate("element => getComputedStyle(element).color"), green)
                    page.locator("#project-options").click()
                    page.locator("#document").select_option("Programming Result.md")
                    page.locator("#refresh").click()
                    expect(page.locator("#document")).to_have_value("Programming Result.md")
                    page.locator("#result-step").evaluate("element => element.open = true")
                    page.locator("#request-result").click()
                    expect(page.locator("#build-action-title")).to_have_text("Save the Programming Result")
                    page.locator("#build-action-cancel").click()
                    page.locator("#review-step").evaluate("element => element.open = true")
                    page.locator("#review").click()
                    expect(page.locator("#build-action-note")).to_contain_text("fresh reviewer")
                    page.locator("#build-action-copy").click()
                    expect(page.locator("#notice")).to_contain_text(re.compile("independent reviewer|Clipboard access"))
                    self.assertIn("selected Claude Code as the independent verifier", copied_verification[-1]["input"])
                    self.assertFalse((self.home / "Two" / "Handoff.md").exists())
                    with mock.patch("ora_vibe_coder.conversation.start_turn") as submitted:
                        handle = submitted.return_value
                        handle.turn = "test-verification-turn"
                        handle.snapshot.return_value = {"turn": handle.turn, "state": "finished", "elapsed_seconds": 0}
                        page.locator("#review").click()
                        page.locator("#build-action-send").click()
                        expect(page.locator("#build-action-dialog")).not_to_be_visible()
                        submitted.assert_called_once()
                        self.assertEqual(submitted.call_args.args[3], "verification")
                        self.assertIn("selected Claude Code as the independent verifier", submitted.call_args.args[4])
                    expect(page.locator("#build-reply-stage")).to_have_value("verification")
                    expect(page.locator("#send")).to_contain_text("independent verification")
                    page.locator("#message").fill("Use the available independent reviewer and report back.")
                    with mock.patch("ora_vibe_coder.conversation.start_turn") as followup:
                        handle = followup.return_value
                        handle.turn = "test-verification-followup"
                        handle.snapshot.return_value = {"turn": handle.turn, "state": "finished", "elapsed_seconds": 0}
                        page.locator("#send").click()
                        followup.assert_called_once()
                        self.assertEqual(followup.call_args.args[3], "verification")
                    page.locator("#next-step").evaluate("element => element.open = true")
                    page.locator("#transition").click()
                    expect(page.locator("#build-action-title")).to_have_text("Correct the implementation")
                    page.locator("#build-action-copy").click()
                    expect(page.locator("#implementation-warning")).to_be_visible()
                    page.locator("#implementation-back").click()
                    page.locator("#message").fill("Fix the implementation")
                    page.locator("#build-reply-stage").select_option("programming")
                    page.locator("#copy-current").click()
                    expect(page.locator("#implementation-warning")).to_be_visible()
                    page.locator("#implementation-back").click()
                    page.locator("#send").click()
                    expect(page.locator("#implementation-warning")).to_be_visible()
                    page.locator("#implementation-back").click()
                    expect(page.locator("#message")).to_have_value("Fix the implementation")
                    self.select_project(page, first)
                    expect(page.locator("#project-completion")).to_be_hidden()
                finally:
                    browser.close()

    def test_document_outcomes_and_build_send_copy_agree(self):
        from playwright.sync_api import expect, sync_playwright
        project_id = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
        folder = self.home / "One"
        for role in ("Specification", "Plan"):
            (folder / f"{role}.md").write_text(f"# {role}\n\n## Scope\nThe agreed work.\n\n## Current review\nVerdict: COMPLETE\n", encoding="utf-8")
        result = folder / "Programming Result current.md"
        report = folder / "Verification Report current.md"
        result.write_text("# Programming Result\n\nProgramming completed 8 October 2026 under the approved Plan.\n", encoding="utf-8")
        report.write_text("# Verification Report\n\nStatus: PASSED\n\n## Result\nThe corrected delivery meets its requirements.\n", encoding="utf-8")
        evidence = folder / "Selected evidence.txt"
        evidence.write_text("EXACT_SELECTED_EVIDENCE", encoding="utf-8")
        def ready(peer, **kwargs):
            return {"peer": peer, "ready": True, "work": "supported", "authentication": "unknown", "warnings": []}
        with mock.patch("ora_vibe_coder.conversation.bridge_check", side_effect=ready), \
                mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(self.server.url)
                self.select_project(page, project_id)
                expect(page.locator("#assessment")).to_have_text("COMPLETE")
                expect(page.locator("#assessment-note")).to_contain_text("does not identify which document version")
                page.locator('.rail[data-stage="plan"]').click()
                expect(page.locator("#assessment")).to_have_text("COMPLETE")
                page.locator('.rail[data-stage="build"]').click()
                expect(page.locator("#result-status")).to_have_text("COMPLETE")
                expect(page.locator("#assessment")).to_have_text("PASSED")
                expect(page.locator("#assessment-note summary")).to_contain_text(report.name)
                expect(page.locator("#reader")).to_contain_text("Status: PASSED")
                expect(page.locator("#project-completion")).to_have_text("REPORTED COMPLETE")

                report.write_text("# Verification Report\n\n**Verdict: PASSED.** But the current candidate failed.\n", encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).not_to_have_text("PASSED")
                expect(page.locator("#assessment-note")).to_contain_text("current candidate failed")
                expect(page.locator("#project-completion")).to_be_hidden()
                report.write_text("# Verification Report\n\nStatus: PASSED\n\n## Earlier review\nVerdict: NOT PASSED\n", encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("PASSED")

                # Copy stays available with no selected or authenticated tool.
                page.locator("#destination").select_option("")
                page.locator("#review-step").evaluate("element => element.open = true")
                page.locator("#review").click()
                expect(page.locator("#build-action-copy")).to_be_enabled()
                expect(page.locator("#build-action-send")).to_be_disabled()
                page.locator("#build-action-cancel").click()
                page.locator("#destination").select_option(label="Codex")
                page.locator("#verification-verifier").select_option(label="Claude Code")
                page.evaluate("path => material().push({path, name: 'Selected evidence.txt'})", str(evidence))
                previews, sends = [], []
                page.on("request", lambda request: previews.append(request.post_data_json)
                        if request.url.endswith("/api/preview") else None)
                def capture_send(route):
                    sends.append(route.request.post_data_json)
                    route.fulfill(json={"turn": f"fake-{len(sends)}", "operation": {"turn": f"fake-{len(sends)}", "state": "finished", "elapsed_seconds": 0}, "images": []})
                page.route("**/api/converse", capture_send)
                for action, button in (("verify", "#review"), ("correct", "#transition")):
                    if action == "correct":
                        page.locator("#next-step").evaluate("element => element.open = true")
                    page.locator(button).click()
                    with page.expect_request("**/api/preview") as copy_request:
                        page.locator("#build-action-copy").click()
                    expect(page.locator("#build-action-dialog")).not_to_be_visible()
                    page.wait_for_function("() => document.getElementById('notice').textContent.includes('copied') || document.getElementById('notice').textContent.includes('Clipboard access')")
                    copied = copy_request.value.post_data_json
                    page.locator(button).click()
                    with page.expect_request("**/api/converse") as send_request:
                        page.locator("#build-action-send").click()
                    expect(page.locator("#build-action-dialog")).not_to_be_visible()
                    page.wait_for_function("() => document.getElementById('turn-note').textContent.includes('Reply complete')")
                    sent = send_request.value.post_data_json
                    self.assertEqual(sent["text"], copied["input"])
                    self.assertEqual(sent["files"], copied["context"]["material"])
                    self.assertEqual(sent["files"], [str(evidence)])
                    if action == "verify":
                        self.assertIn("selected Claude Code as the independent verifier", sent["text"])
                    else:
                        self.assertIn("Stop there.", sent["text"])
                        self.assertIn("Do not run or commission a new Ora Verification", sent["text"])
                self.assertFalse((folder / "Handoff.md").exists())
            finally:
                browser.close()

    def test_native_quit_uses_the_explicit_stop_path(self):
        settings = Settings(self.home / "native-settings.json")
        (self.home / "running.json").write_text(json.dumps({"url": self.server.url}), encoding="utf-8")
        for confirmed in (False, True):
            with self.subTest(confirmed=confirmed), \
                    mock.patch("ora_vibe_coder.launcher._post", side_effect=[
                        {"visible_input": False, "active_turns": 1}, {"stopped": True}]) as post:
                asked = mock.Mock(return_value=confirmed)
                self.assertEqual(request_quit(settings, dialog=asked, platform="darwin"), confirmed)
                asked.assert_called_once_with("darwin")
                self.assertEqual([call.args[2] for call in post.call_args_list],
                                 ["/api/quit-state", "/api/stop"] if confirmed else ["/api/quit-state"])

    def test_copy_ready_requests_use_the_right_ora_method_without_replacing_a_saved_request(self):
        project_id = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
        outgoing = self.home / "One" / "Handoff.md"
        outgoing.write_text("Existing review request\n", encoding="utf-8")
        for stage, method, title in (("planning", "ora-planning", "Ora Planning"),
                                     ("implement-plan", "ora-programming", "Ora Programming"),
                                     ("programming-result", "ora-programming", "Ora Programming"),
                                     ("verification", "ora-verification", "Ora Verification")):
            with self.subTest(stage=stage):
                status, response, _ = self.request("/api/preview", {"id": project_id, "stage": stage,
                    "input": "Exact instruction", "destination": "Codex", "context": {"material": []}})
                self.assertEqual(status, 200)
                self.assertTrue(response["text"].startswith("# User request\n\nExact instruction"))
                self.assertIn(f"Selected stage: {method}", response["text"])
                self.assertIn(f"# {title}", response["text"])
                self.assertEqual(outgoing.read_text(encoding="utf-8"), "Existing review request\n")
                if stage == "programming-result":
                    self.assertIn("Do not resume implementation under this report-only request", response["text"])
        report = self.home / "One" / "Verification Report.md"
        report.write_text("Verdict: NOT PASSED\n\nFix the actual finding.\n", encoding="utf-8")
        status, response, _ = self.request("/api/preview", {"id": project_id, "stage": "programming",
            "input": "Correct the current findings", "destination": "Codex", "context": {"material": []}})
        self.assertEqual(status, 200)
        self.assertIn("Fix the actual finding.", response["text"])
        self.assertIn(f"Source:\n\n```text\n{report}\n```", response["text"])

    def test_verification_turn_does_not_offer_or_apply_registry_maintenance(self):
        project_id = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
        project = self.server.store.projects[project_id]
        registry = project.root / "Registry.md"
        original = registry.read_bytes()
        request = conversation.conversation_request(project, "codex", "verification", "Check independently", [], [], [])
        self.assertIn("Do not propose or apply Registry maintenance", request)
        self.assertNotIn("## Registry maintenance block", request)
        evidence = self.home / "outside evidence.md"
        evidence.write_text("External observation.\n", encoding="utf-8")
        status, preview, _ = self.request("/api/preview", {"id": project_id, "stage": "verification",
            "input": "Check independently", "destination": "Codex", "context": {"material": [str(evidence)]}})
        self.assertEqual(status, 200)
        self.assertIn("External observation.", preview["text"])
        self.assertIn("Files selected as evidence", preview["text"])
        self.assertNotIn("Organize their useful content into this project's Registry", preview["text"])
        # An honest handle that was never stopped: is_cancelled() must return
        # a real False (#57), or _complete_turn reads the turn as interrupted.
        fake_handle = mock.Mock(warnings=[])
        fake_handle.is_cancelled.return_value = False
        with mock.patch("ora_vibe_coder.conversation._record_outcome") as record:
            conversation._complete_turn(fake_handle, project, project.root / ".vibe", "verification",
                                        "<!-- vibe-maintenance:start -->\nkind: no-change\n<!-- vibe-maintenance:end -->")
        self.assertEqual(registry.read_bytes(), original)
        self.assertEqual(record.call_args.args[4], conversation.NOT_EVALUATED)

    def test_wrong_host_origin_token_and_unselected_or_arbitrary_paths(self):
        status, page, headers = self.request("/", {}, method="GET")
        self.assertEqual(status, 200)
        page = page.decode("utf-8")
        self.assertIn("Enter adds a new line. Control+Enter or Command+Enter prepares the request.", page)
        self.assertEqual(page.count('class="rail" data-stage='), 3)
        status, stylesheet, _ = self.request("/static/style.css", {}, method="GET")
        self.assertEqual(status, 200)
        stylesheet = stylesheet.decode("utf-8")

        def declarations(selector):
            match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", stylesheet)
            self.assertIsNotNone(match)
            return {
                name.strip(): value.strip()
                for name, value in (
                    declaration.split(":", 1)
                    for declaration in match.group(1).split(";")
                    if ":" in declaration
                )
            }

        base_notice = declarations("#notice")
        notice = declarations("body:has(.modal:not([hidden])) #notice")
        modal = declarations(".modal")
        picker = declarations("#folder-picker, #file-picker")
        self.assertEqual(notice["position"], "fixed")
        self.assertEqual(base_notice["overflow"], "auto")
        self.assertGreater(
            int(notice["z-index"]),
            int(picker["z-index"]),
        )
        self.assertGreater(int(picker["z-index"]), int(modal["z-index"]))
        viewport_height = 720
        notice_top = int(notice["inset"].split()[0].removesuffix("px"))
        notice_limit = re.fullmatch(
            r"calc\((\d+)vh - (\d+)px\)", notice["max-height"]
        )
        self.assertIsNotNone(notice_limit)
        notice_bottom = notice_top + (
            int(notice_limit.group(1)) / 100 * viewport_height
            - int(notice_limit.group(2))
        )
        modal_top = (
            int(modal["inset"].split()[0].removesuffix("vh"))
            / 100
            * viewport_height
        )
        self.assertLess(notice_bottom, modal_top)
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        for headers in ({"X-Ora-Token": "wrong"}, {"Host": "evil.example"}, {"Origin": "https://evil.example"}, {"Origin": "null"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("/api/projects", {}, headers)[0], 403)
        self.assertEqual(self.request("/api/projects", {})[0], 200)
        self.assertEqual(self.request("/api/projects", {}, {"Origin": self.server.origin})[0], 200)
        self.assertEqual(self.request("/api/read", {"path": "/etc/passwd"})[0], 400)
        self.assertEqual(self.request("/etc/passwd", {}, method="GET")[0], 404)
        self.assertEqual(self.request("/static/../server.py", {}, method="GET")[0], 404)
        self.assertEqual(self.request("/api/write", {"path": "/tmp/nope", "text": "bad"})[0], 400)

        # The same-origin attachment route sits behind the full boundary —
        # host, origin, and the tab's token, the last carried in the query
        # because an image load cannot carry headers — and serves only a
        # retained original of an opened project's turn.
        code, created, _ = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})
        self.assertEqual(code, 200)
        key = created["id"]
        retained = self.home / "One" / ".vibe" / "0001-20260101-000000" / "attachments"
        retained.mkdir(parents=True)
        pixels = b"\x89PNG\r\n\x1a\n boundary pixels"
        (retained / "0001-shot.png").write_bytes(pixels)
        (retained / "0002-link.png").symlink_to(retained / "0001-shot.png")
        good = f"/api/attachment?token={self.server.token}&id={key}&turn=0001-20260101-000000&name=0001-shot.png"
        status, body, headers = self.request(good, {}, method="GET")
        self.assertEqual((status, body), (200, pixels))
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertIn("img-src 'self' blob:", headers["Content-Security-Policy"])  # Same-origin originals plus in-memory blob: previews.
        self.assertEqual(self.request(good.replace(f"token={self.server.token}", "token=wrong"), {}, method="GET")[0], 403)
        for headers in ({"Host": "evil.example"}, {"Origin": "https://evil.example"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request(good, {}, headers)[0], 403)
        for bad in (good.replace("name=0001-shot.png", "name=0002-link.png"),
                    good.replace("turn=0001-20260101-000000", "turn=zzzz"),
                    good.replace("name=0001-shot.png", "name=..%2Fescape.png"),
                    good.replace(f"id={key}", "id=unopened"),
                    good.replace("name=0001-shot.png", "name=0003-absent.png"),
                    "/api/attachment?token=x",
                    good + "&extra=1"):
            with self.subTest(bad=bad):
                self.assertIn(self.request(bad, {}, method="GET")[0], {400, 404})

        # A linked parent directory cannot relocate the retained-attachment
        # location itself: confinement covers every path component from the
        # project's reserved .vibe root down to the served file, so a turn's
        # attachments folder — or the turn folder itself — symlinked outside
        # the project serves nothing even through an otherwise valid name.
        outside = self.home / "outside attachments"
        outside.mkdir()
        (outside / "0001-external.png").write_bytes(b"\x89PNG\r\n\x1a\n external pixels")
        linked_attachments = self.home / "One" / ".vibe" / "0002-20260101-000000"
        linked_attachments.mkdir(parents=True)
        (linked_attachments / "attachments").symlink_to(outside)
        linked_turn = self.home / "outside turn"
        (linked_turn / "attachments").mkdir(parents=True)
        (linked_turn / "attachments" / "0001-external.png").write_bytes(b"\x89PNG\r\n\x1a\n turn pixels")
        (self.home / "One" / ".vibe" / "0003-20260101-000000").symlink_to(linked_turn)
        for linked in (f"/api/attachment?token={self.server.token}&id={key}&turn=0002-20260101-000000&name=0001-external.png",
                       f"/api/attachment?token={self.server.token}&id={key}&turn=0003-20260101-000000&name=0001-external.png"):
            with self.subTest(linked=linked.rsplit("turn=", 1)[1]):
                self.assertEqual(self.request(linked, {}, method="GET")[0], 404)

    def test_check_updates_answers_and_failure_path_use_a_stand_in_lookup(self):
        # The deliberate check answers one of four ways through a stand-in
        # release record: no request leaves the machine in this test.
        running = (Path(__file__).resolve().parents[1] / "plugins" / "ora-vibe-coder" / "VERSION").read_text(encoding="utf-8").strip()
        major, minor, patch = (int(part) for part in running.split("."))
        page = lambda tag: f"https://github.com/ora-commons/ora-vibe-coder/releases/tag/v{tag}"
        def stand_in(tag):
            return lambda: {"tag_name": f"v{tag}", "html_url": page(tag)}
        for tag, expected in ((f"{major}.{minor + 1}.0", "newer"), (f"{major}.{minor}.{patch}", "same"), ("0.0.1", "ahead")):
            with self.subTest(answer=expected):
                self.server.update_lookup = stand_in(tag)
                status, result, _ = self.request("/api/check-updates", {})
                self.assertEqual(status, 200)
                self.assertEqual(result["answer"], expected)
                if expected == "newer":
                    self.assertIn(f"{major}.{minor + 1}.0", result["label"])
                    self.assertEqual(result["url"], page(f"{major}.{minor + 1}.0"))
                    self.assertRegex(result["note"], r"Stop Vibe.*Install or update")
                elif expected == "same":
                    self.assertIn("up to date", result["label"])
                    self.assertIsNone(result["url"])
                else:
                    self.assertIn("newer than the newest public release", result["label"])
                    self.assertIsNone(result["url"])
        for name, stand in (("transport failure", lambda: (_ for _ in ()).throw(OSError("rate limited"))),
                            ("unreadable record", lambda: {"message": "API rate limit exceeded"})):
            with self.subTest(failure=name):
                self.server.update_lookup = stand
                status, result, _ = self.request("/api/check-updates", {})
                self.assertEqual((status, result["answer"]), (200, "cant_tell"))
                self.assertIn("Couldn't check for updates.", result["label"])
                self.assertNotIn("up to date", result["label"])  # A failure is never reported as up to date.
                self.assertIsNone(result["url"])

    def test_malformed_or_cross_boundary_writes_preserve_project(self):
        code, response, _ = self.request("/api/create", {"directory": "One", "name": "One", "description": "Keep", "goals": "Goals"})
        self.assertEqual(code, 200)
        key = response["id"]
        _, project, _ = self.request("/api/project", {"id": key})
        original = (self.home / "One" / "Project.md").read_bytes()
        for paths in ({"Specification": "../outside.md"}, {"Plan": "Handoff.md"}, {"Unexpected": "bad"}):
            code, _, _ = self.request("/api/save", {"id": key, "expected": project["raw"], "name": "One", "description": "Bad", "goals": "", "paths": paths})
            self.assertEqual(code, 400)
            self.assertEqual((self.home / "One" / "Project.md").read_bytes(), original)
        self.assertEqual(self.request("/api/save", {"id": key, "name": []})[0], 400)
        self.assertEqual(self.request("/api/projects", {"extra": True})[0], 400)
        self.assertEqual(self.request("/api/create", {"directory": "../escape", "name": "bad", "description": "", "goals": ""})[0], 400)
        code, _, _ = self.request("/api/projects", {}, {"Content-Length": str(REQUEST_LIMIT + 1)})
        self.assertEqual(code, 400)

    def test_brief_alone_never_grants_external_access_and_stop_exits(self):
        code, data, _ = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})
        key = data["id"]
        external = self.home / "outside.md"
        external.write_text("Do not read without explicit selection", encoding="utf-8")
        _, project, _ = self.request("/api/project", {"id": key})
        self.request("/api/save", {"id": key, "expected": project["raw"], "name": "One", "description": "", "goals": "", "paths": {"Specification": str(external)}})
        _, document, _ = self.request("/api/read", {"id": key, "role": "Specification"})
        self.assertIsNone(document["text"])
        self.assertTrue(document["needs_selection"])
        self.assertEqual(self.request("/api/approve-reference", {"id": key, "role": "Specification", "path": "/wrong/path"})[0], 400)
        self.assertEqual(self.request("/api/approve-reference", {"id": key, "role": "Specification", "path": str(external)})[0], 200)
        self.assertEqual(self.request("/api/read", {"id": key, "role": "Specification"})[1]["text"], external.read_text())
        status, body, headers = self.request("/api/stop", {})
        self.assertEqual((status, body), (200, {"stopped": True, "interrupted": 0, "note": ""}))
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())
        self.assertIn("img-src 'self'", headers["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertTrue(external.exists())
        self.server.server_close()

        # Native Quit helper, end to end through the launch record it reads:
        # a visible-input Cancel leaves the local server serving, and an
        # empty-input quit stops it. The launch URL's fragment carries only
        # the token, which must not derail the helper's API requests.
        self.server = LocalServer(self.home)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01})
        self.thread.start()
        settings = Settings(self.home / "settings.json")
        (self.home / "running.json").write_text(json.dumps({"url": self.server.url}), encoding="utf-8")
        self.request("/api/input-state", {"visible": True})
        cancelled = []
        self.assertFalse(request_quit(settings, dialog=lambda platform=None: cancelled.append(platform) or False))
        self.assertEqual(cancelled, [None])
        self.assertTrue(self.thread.is_alive())
        self.assertEqual(self.request("/api/quit-state", {})[1], {"visible_input": True, "active_turns": 0})
        self.request("/api/input-state", {"visible": False})
        self.assertTrue(request_quit(settings, dialog=self.fail))
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())

    def test_guided_stage_prerequisites(self):
        # No lifecycle gate remains: planning and programming assignments stay
        # preparable with missing, incomplete, unreviewed, or unapproved
        # documents, and assessments are advisory facts that never block.
        code, data, _ = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})
        self.assertEqual(code, 200)
        key = data["id"]
        root = self.home / "One"
        (root / "Request.md").write_text("# Request\n\n## Goals\nDeliver.\n", encoding="utf-8")
        (root / "Specification.md").write_text("# Specification\n\nStatus: DRAFT\n\n## Body\nBehavior.\n", encoding="utf-8")
        context = {"material": []}

        def prepare(stage, input_text="Proceed"):
            existing = root / ("One — Implementation Request.md" if stage == "implement-plan" else "Handoff.md")
            return self.request("/api/prepare", {"id": key, "stage": stage, "input": input_text, "destination": "Codex",
                                                 "context": context,
                                                 "expected": existing.read_text(encoding="utf-8") if existing.exists() else None})

        def specification_text():
            return (root / "Specification.md").read_text(encoding="utf-8")

        def snapshot():
            _, body, _ = self.request("/api/project", {"id": key})
            return body

        # Forward actions are available with nothing reviewed or approved, and
        # write only the outgoing file.
        for stage in ("create-plan", "implement-plan"):
            status, body, _ = prepare(stage)
            self.assertEqual(status, 200)
            self.assertEqual(body["path"], str(root / ("One — Implementation Request.md" if stage == "implement-plan" else "Handoff.md")))
        forward = (root / "Handoff.md").read_text(encoding="utf-8")
        self.assertTrue(forward.startswith("# User request\n\nProceed"))
        handoff = root / "Handoff.md"
        handoff.write_text("Hand-edited handoff\n", encoding="utf-8")
        request = {"id": key, "stage": "create-plan", "input": "New plan request", "destination": "Codex",
                   "context": context, "expected": None}
        status, conflict, _ = self.request("/api/prepare", request)
        self.assertEqual(status, 409)
        self.assertEqual(conflict["current"], "Hand-edited handoff\n")
        self.assertEqual(handoff.read_text(encoding="utf-8"), "Hand-edited handoff\n")
        handoff.write_text("Changed while reviewing\n", encoding="utf-8")
        request["expected"] = conflict["current"]
        status, conflict, _ = self.request("/api/prepare", request)
        self.assertEqual(status, 409)
        self.assertEqual(conflict["current"], "Changed while reviewing\n")
        self.assertEqual(handoff.read_text(encoding="utf-8"), "Changed while reviewing\n")
        request["expected"] = conflict["current"]
        status, replacement, _ = self.request("/api/prepare", request)
        self.assertEqual(status, 200)
        self.assertEqual(handoff.read_text(encoding="utf-8"), replacement["text"])
        self.assertIn("New plan request", replacement["text"])
        status, copied, _ = self.request("/api/copy", {"id": key, "displayed": replacement["text"]})
        self.assertEqual(status, 200)
        self.assertEqual(copied["text"], replacement["text"])
        handoff.write_text("Changed after preparation\n", encoding="utf-8")
        status, conflict, _ = self.request("/api/copy", {"id": key, "displayed": replacement["text"]})
        self.assertEqual(status, 409)
        self.assertEqual(conflict["current"], "Changed after preparation\n")
        self.assertEqual(handoff.read_text(encoding="utf-8"), "Changed after preparation\n")
        implementation = (root / "One — Implementation Request.md").read_text(encoding="utf-8")
        self.assertIn("Selected stage: ora-programming", implementation)
        self.assertIn("# Ora Programming", implementation)
        self.assertIn("## Plan", implementation)
        self.assertEqual(self.request("/api/copy", {"id": key, "displayed": implementation, "purpose": "implement-plan"})[1]["text"], implementation)
        self.assertNotIn("Verified gate for this forward assignment", forward)
        self.assertIn("Status: DRAFT", specification_text())
        self.assertIn("Programming: NOT STARTED", (root / "Project.md").read_text(encoding="utf-8"))
        self.assertFalse((root / "One — 03 Implementation Plan.md").exists())  # Preparing creates no Plan.

        # A draft Status and a recorded FAILED legacy verdict stay advisory:
        # nothing blocks, and no gate text appears.
        from ora_vibe_coder.status import review_basis
        basis = review_basis(specification_text())
        (root / "Specification.md").write_text(
            f"# Specification\n\nStatus: DRAFT\n\n## Current review\n\nStage: Specification\nVerdict: NOT PASSED\nBasis: {basis}\n\nNot yet.\n\n## Body\nBehavior.\n",
            encoding="utf-8")
        status, body, _ = prepare("create-plan")
        self.assertEqual(status, 200)
        state = snapshot()
        self.assertEqual(state["assessments"]["specification"]["verdict"], "NOT PASSED")
        self.assertEqual(state["assessments"]["specification"]["applies"], "unconfirmed")  # Legacy record.

        # A saved completeness assessment in the app's recorded format (#57:
        # content-v2 basis) drives the display facts: the count comes from the
        # findings list, and the document-only basis means a later edit
        # identifies it as earlier — still without blocking.
        (root / "Specification.md").write_text(
            f"# Specification\n\nStatus: DRAFT\n\n## Current review\n\nStage: Specification\nVerdict: INCOMPLETE\nBasis: {basis}\nBasis format: content-v2\n\n- First gap.\n- Second gap.\n\n## Body\nBehavior.\n",
            encoding="utf-8")
        state = snapshot()
        assessment = state["assessments"]["specification"]
        self.assertEqual((assessment["verdict"], assessment["findings"], assessment["applies"]), ("INCOMPLETE", 2, "current"))
        status, body, _ = prepare("review-specification")
        self.assertEqual(status, 200)
        review_packet = (root / "Handoff.md").read_text(encoding="utf-8")
        self.assertIn("Saving the assessment", review_packet)
        self.assertIn("Verdict: COMPLETE    (or INCOMPLETE)", review_packet)
        (root / "Specification.md").write_text(
            specification_text().replace("## Body\nBehavior.", "## Body\nBehavior, revised."),
            encoding="utf-8")
        state = snapshot()
        self.assertEqual(state["assessments"]["specification"]["applies"], "earlier")
        for stage in ("specification", "planning", "create-plan", "implement-plan", "programming"):
            self.assertEqual(prepare(stage)[0], 200)
        # An unreviewed Plan stays equally preparable; untouched starter
        # templates report Not started, distinct from Not reviewed.
        state = snapshot()
        self.assertEqual(state["assessments"]["planning"]["untouched"], True)
        self.assertFalse(state["assessments"]["planning"]["present"])
        loop_packet = (root / "Handoff.md").read_text(encoding="utf-8")
        self.assertIn("Programming Loop", loop_packet)
        self.assertIn("Repository / code folder", loop_packet)
        self.assertIn("No code folder selected", loop_packet)
        self.assertIn("Programming: NOT STARTED", (root / "Project.md").read_text(encoding="utf-8"))
        # Preparing never writes stage documents: the folder holds only the intended files.
        self.assertEqual(sorted(path.name for path in root.iterdir()),
                         ["Handoff.md", "One — Implementation Request.md", "Plan.md", "Project.md", "Registry.md", "Request.md", "Specification.md"])
        self.assertIn("One — Implementation Request.md", [entry["name"] for entry in snapshot()["reader"]])
        self.assertNotEqual(forward, implementation)

    def test_documents_inventory_startup_and_preferences(self):
        # Normal startup builds its inventory automatically under the injected
        # root (the disposable twin of the user's Documents folder); the saved
        # projects-home setting no longer takes part in startup at all.
        preferences = Settings(self.home / "settings.json")
        preferences.update(unrelated="keep", projects_home=str(self.home / "gone"))
        self.server.settings = preferences
        active = self.home / "active project"
        active.mkdir()
        (active / "Project.md").write_text("# Project\n\nName: Active\n\n## Description\n\nHere.\n", encoding="utf-8")
        archived = self.home / "archived project"
        archived.mkdir()
        (archived / "Project.md").write_text("# Project\n\nName: Archived\nProject state: ARCHIVED\n", encoding="utf-8")
        self.server.store = ProjectStore(self.home)

        status, setup, _ = self.request("/api/setup", {})
        self.assertEqual(status, 200)
        self.assertEqual(setup["home"], str(self.home))  # Automatic root; no folder-selection step.
        self.assertEqual(setup["last_project"], "")     # Nothing has been opened yet.
        self.assertEqual(setup["recent_projects"], [])
        status, inventory, _ = self.request("/api/projects", {})
        self.assertEqual(status, 200)
        self.assertEqual([entry["label"] for entry in inventory["projects"]], ["Active", "Archived"])  # Labels and order come from the server.
        by_path = {entry["path"]: entry for entry in inventory["projects"]}
        self.assertFalse(by_path[str(active)]["archived"])
        self.assertTrue(by_path[str(archived)]["archived"])  # Marked so the client restores active projects only.

        # Opening an archived project does not reactivate it, and the recent
        # settings stay useful without determining the inventory.
        self.assertEqual(self.request("/api/open", {"path": str(archived)})[0], 200)
        _, refreshed, _ = self.request("/api/projects", {})
        entry = next(item for item in refreshed["projects"] if item["path"] == str(archived))
        self.assertTrue(entry["archived"])
        self.assertEqual(preferences.read()["last_project"], str(archived))
        self.assertNotEqual(preferences.read().get("projects_home"), str(self.home))
        self.assertEqual(preferences.read()["unrelated"], "keep")
        # The obsolete folder-selection operation no longer exists.
        self.assertEqual(self.request("/api/select-home", {"path": str(self.home)})[0], 400)

        # The rescan route repeats discovery: new definitions appear and ones
        # moved outside the root disappear, without a server restart.
        newcomer = self.home / "newcomer"
        newcomer.mkdir()
        (newcomer / "Project.md").write_text("# Project\n\nName: Newcomer\n", encoding="utf-8")
        outside = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, outside)
        os.rename(active, outside / "moved away")
        status, rescanned, _ = self.request("/api/rescan", {})
        self.assertEqual(status, 200)
        self.assertEqual([entry["label"] for entry in rescanned["projects"]], ["Archived", "Newcomer"])

        # The creation chooser is restricted to the discovery root on the server:
        # navigation stops at the boundary and outside locations are refused.
        status, folders, _ = self.request("/api/folders", {"path": str(archived), "limit": str(self.home)})
        self.assertEqual(status, 200)
        self.assertEqual(folders["parent"], str(self.home))
        self.assertEqual(self.request("/api/folders", {"path": str(outside / "moved away"), "limit": str(self.home)})[0], 400)
        self.assertEqual(self.request("/api/create", {"directory": "Escape", "name": "Escape", "description": "", "goals": "", "under": str(outside)})[0], 400)
        self.assertFalse((outside / "Escape").exists())
        self.assertEqual(self.request("/api/folders", {"path": str(self.home)})[1]["parent"], str(self.home.parent))  # The unlimited manual route is unchanged.

    def test_configured_projects_folder_excludes_worktree_copies(self):
        projects = self.home / "Projects"
        real = projects / "Ora" / "One"
        copied = self.home / ".claude" / "worktrees" / "copy" / "Projects" / "Ora" / "One"
        for folder in (real, copied):
            folder.mkdir(parents=True)
            (folder / "Project.md").write_text("# Project\n\nName: One\n", encoding="utf-8")
        settings = Settings(self.home / "settings.json")
        settings.update(projects_dir=str(projects), projects_home=str(copied.parent))
        self.assertEqual(settings.projects_dir(), projects)
        self.server.store = ProjectStore(settings.projects_dir())
        status, inventory, _ = self.request("/api/projects", {})
        self.assertEqual(status, 200)
        self.assertEqual([entry["path"] for entry in inventory["projects"]], [str(real)])
        self.assertEqual(inventory["home"], str(projects))

    def test_mac_icon_launch_finds_user_coding_tools(self):
        local = self.home / ".local/bin"
        minimax = self.home / ".minimax-code/bin"
        for directory, names in ((local, ("codex", "claude", "node", "hermes", "qwen")),
                                 (minimax, ("mcode",))):
            directory.mkdir(parents=True)
            for name in names:
                command = directory / name
                command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                command.chmod(0o755)
        seen = {}

        def inspect_launch(server, **kwargs):
            seen.update({host: hosts.executable(host) for host in ("codex", "claude", "hermes", "qwen", "minimax")})
            seen["node"] = shutil.which("node")
            seen["path"] = os.environ["PATH"]

        argv = ["vibe", "--wrapper", "--settings", str(self.home / "settings.json"),
                "--projects-dir", str(self.home)]
        with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}), \
             mock.patch.object(Path, "home", return_value=self.home), \
             mock.patch.object(app_entry, "sys") as app_sys, \
             mock.patch.object(sys, "argv", argv), \
             mock.patch.object(app_entry, "LocalServer", return_value=mock.Mock(url="http://127.0.0.1:1/#test")), \
             mock.patch.object(app_entry, "serve", side_effect=inspect_launch):
            app_sys.platform = "darwin"
            app_entry.main()
        self.assertEqual(seen["codex"], [str(local / "codex")])
        self.assertEqual(seen["claude"], [str(local / "claude")])
        self.assertEqual(seen["hermes"], [str(local / "hermes")])
        self.assertEqual(seen["qwen"], [str(local / "qwen")])
        self.assertEqual(seen["minimax"], [str(minimax / "mcode")])
        self.assertEqual(seen["node"], str(local / "node"))
        self.assertTrue(seen["path"].startswith("/usr/bin:/bin:/usr/sbin:/sbin:"))

    def test_disposable_install_update_failure_remove_and_selected_host_preservation(self):
        user = self.home / "disposable user 日本語"
        release = self.synthetic_release()
        # A Python older than 3.10 is refused before anything is staged, naming
        # the python.org macOS installer route and the reopen instruction.
        with mock.patch.object(sys, "version_info", (3, 9, 18)):
            with self.assertRaisesRegex(ValueError, r"requires Python 3\.10 or later.*python\.org.*open this setup again"):
                install(source=release, home=user, hosts=("codex",), platform="darwin")
        selected = ("codex", "claude", "zcode", "hermes", "qwen", "minimax")
        credentials = user / ".claude" / "settings.json"
        credentials.parent.mkdir(parents=True)
        credentials.write_text('{"unrelated":"preserve this fake setting"}')
        project = user / "Projects" / "Keep"
        project.mkdir(parents=True)
        (project / "Handoff.md").write_text("previous recoverable handoff")
        result = install(source=release, home=user, hosts=selected, platform="darwin")
        app = Path(result["app"])
        for host in selected:
            directory = ".minimax" if host == "minimax" else f".{host}"
            entry = user / directory / "skills" / "ora-programming"
            self.assertIn(f"adapters/{host}.md", (entry / "SKILL.md").read_text())
            self.assertTrue((user / directory / "skills/programming-loop/SKILL.md").is_file())
        self.assertTrue((Path(result["launcher"]) / "Contents/MacOS/Ora Vibe Coder").stat().st_mode & 0o111)
        unknown = app / "personal note.txt"
        unknown.write_text("keep me")
        before = (app / "ora_vibe_coder/server.py").read_bytes()
        from ora_vibe_coder import installer
        original = installer.os.replace
        count = 0
        def fail_switch(source, target):
            nonlocal count
            count += 1
            if count == 4:
                raise OSError("simulated replacement failure")
            return original(source, target)
        with mock.patch.object(installer.os, "replace", side_effect=fail_switch):
            with self.assertRaises(OSError):
                install(source=release, home=user, hosts=("codex",), platform="darwin")
        self.assertEqual((app / "ora_vibe_coder/server.py").read_bytes(), before)
        self.assertEqual(unknown.read_text(), "keep me")
        self.assertFalse(list(user.rglob(".ora-vibe-install-*")))
        with AppLock(app.parent / "app.lock"):
            with self.assertRaisesRegex(ValueError, "already running"):
                install(source=release, home=user, hosts=(), platform="darwin")

        old_app = (app / "ora_vibe_coder/server.py").read_bytes()
        old_loops = {
            host: (user / (".minimax" if host == "minimax" else f".{host}") / "skills/programming-loop/SKILL.md").read_bytes()
            for host in selected
        }
        (release / "ora_vibe_coder/server.py").write_text("BOUNDARY = 'replacement application'\n")
        loop_script = release / "plugins/ora-vibe-coder/resources/programming-loop/scripts/install.py"
        loop_script.write_text(
            loop_script.read_text().replace("synthetic loop entry", "replacement loop entry")
        )
        original_run = installer.subprocess.run
        loop_installs = 0

        def fail_second_loop(command, **kwargs):
            nonlocal loop_installs
            if command[2] == "install":
                loop_installs += 1
                if loop_installs == 2:
                    return mock.Mock(returncode=1, stdout="", stderr="simulated Loop failure")
            return original_run(command, **kwargs)

        with mock.patch.object(installer.subprocess, "run", side_effect=fail_second_loop):
            with self.assertRaisesRegex(ValueError, "simulated Loop failure"):
                install(source=release, home=user, hosts=("codex", "claude"), platform="darwin")
        self.assertEqual((app / "ora_vibe_coder/server.py").read_bytes(), old_app)
        for host, expected in old_loops.items():
            directory = ".minimax" if host == "minimax" else f".{host}"
            self.assertEqual((user / directory / "skills/programming-loop/SKILL.md").read_bytes(), expected)

        install(source=release, home=user, hosts=("codex",), platform="darwin")

        owned = app / "ora_vibe_coder/server.py"
        installed_bytes = owned.read_bytes()
        owned.unlink()
        selected_roots = (
            app,
            user / ".codex/skills/ora-programming",
            user / ".codex/skills/programming-loop",
            user / "Applications/Ora Vibe Coder.app",
        )
        damaged_snapshot = {
            str(path): path.read_bytes()
            for root in selected_roots for path in root.rglob("*") if path.is_file()
        }
        with self.assertRaisesRegex(ValueError, "changed or are missing"):
            install(source=release, home=user, hosts=("codex",), platform="darwin")
        self.assertEqual({
            str(path): path.read_bytes()
            for root in selected_roots for path in root.rglob("*") if path.is_file()
        }, damaged_snapshot)
        self.assertFalse(owned.exists())
        owned.write_bytes(installed_bytes)
        self.assertFalse(list(user.rglob(".ora-vibe-install-*")))

        owned.write_text("user edit")
        with self.assertRaisesRegex(ValueError, "changed or are missing"):
            remove(source=release, home=user, hosts=selected, platform="darwin")
        self.assertTrue((app / "ora-vibe-install.json").is_file())
        for host in selected:
            directory = ".minimax" if host == "minimax" else f".{host}"
            self.assertTrue((user / directory / "skills/ora-programming/SKILL.md").is_file())
            self.assertTrue((user / directory / "skills/programming-loop/SKILL.md").is_file())
        owned.write_bytes(installed_bytes)

        loop_removals = 0

        def fail_second_loop_removal(command, **kwargs):
            nonlocal loop_removals
            if command[2] == "remove":
                loop_removals += 1
                if loop_removals == 2:
                    return mock.Mock(returncode=1, stdout="", stderr="simulated Loop removal failure")
            return original_run(command, **kwargs)

        with mock.patch.object(installer.subprocess, "run", side_effect=fail_second_loop_removal):
            with self.assertRaisesRegex(ValueError, "simulated Loop removal failure"):
                remove(source=release, home=user, hosts=selected, platform="darwin")
        self.assertEqual(owned.read_bytes(), installed_bytes)
        for host in selected:
            directory = ".minimax" if host == "minimax" else f".{host}"
            self.assertTrue((user / directory / "skills/ora-programming/SKILL.md").is_file())
            self.assertTrue((user / directory / "skills/programming-loop/SKILL.md").is_file())

        removed = remove(source=release, home=user, hosts=selected, platform="darwin")
        self.assertIn(str(unknown), removed["retained"])
        for host in selected:
            directory = ".minimax" if host == "minimax" else f".{host}"
            self.assertFalse((user / directory / "skills/programming-loop").exists())
            self.assertFalse((user / directory / "skills/ora-programming").exists())
        self.assertEqual(unknown.read_text(), "keep me")
        self.assertEqual((project / "Handoff.md").read_text(), "previous recoverable handoff")
        self.assertIn("preserve", credentials.read_text())
        self.assertIn(".cmd", next(iter(launcher_files(app, "win32")))); self.assertIn(".desktop", next(iter(launcher_files(app, "linux"))))

        # Windows desktop shortcut with faked host operations: the shortcut
        # command keeps spaced install paths quoted as data, the icon is a
        # valid container, and the win32 transaction creates and rolls back
        # the shortcut file. No real Windows shell runs here; native Windows
        # qualification remains outstanding.
        import base64
        import os
        import struct
        win_home = user / "disposable win user"
        win_default_app = installer.install_location(win_home, "win32")
        self.assertIn(" ", str(win_default_app))
        launch_argument = win_default_app / "launch.py"
        settings_argument = win_default_app.parent / "settings.json"
        win_target = win_home / "Python" / "pythonw.exe"
        win_link = win_home / "Desktop" / "O'ra Vibe Coder.lnk"
        direct = installer.shortcut_command(
            win_link, win_target, f'"{launch_argument}" --settings "{settings_argument}"',
            win_default_app, win_default_app / "Ora Vibe Coder.ico",
        )
        self.assertIn("$shell = New-Object -ComObject WScript.Shell", direct)
        self.assertIn(f"$shortcut.TargetPath = '{win_target}'", direct)
        self.assertIn(f"$shortcut.Arguments = '\"{launch_argument}\" --settings \"{settings_argument}\"'", direct)
        self.assertIn(f"$shortcut.WorkingDirectory = '{win_default_app}'", direct)
        self.assertIn(f"$shortcut.IconLocation = '{win_default_app / 'Ora Vibe Coder.ico'},0'", direct)
        self.assertIn("CreateShortcut('" + str(win_link).replace("'", "''") + "')", direct)
        payload = b"fake png payload"
        icon = installer.windows_icon_bytes(payload)
        reserved, icon_type, entries = struct.unpack("<HHH", icon[:6])
        self.assertEqual((reserved, icon_type, entries), (0, 1, 1))
        width, height, _, _, planes, depth, size, offset = struct.unpack("<BBBBHHII", icon[6:22])
        self.assertEqual((width, height, planes, depth), (0, 0, 1, 32))
        self.assertEqual((size, offset, icon[22:]), (len(payload), 22, payload))

        class WindowsName:
            name = "nt"

            def __getattr__(self, attribute):
                return getattr(os, attribute)

        desktop_link = user / "Desktop" / "Ora Vibe Coder.lnk"
        win_scripts = []

        def fake_windows_shell(command, **kwargs):
            self.assertEqual(command[:3], ["powershell", "-NoProfile", "-EncodedCommand"])
            win_scripts.append(base64.b64decode(command[3]).decode("utf-16-le"))
            desktop_link.write_bytes(b"faked shortcut v1")
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(installer.subprocess, "run", side_effect=fake_windows_shell):
            with mock.patch.object(installer, "os", WindowsName()):
                win_result = install(source=release, home=user, hosts=(), platform="win32")
        win_app = Path(win_result["app"])
        self.assertEqual(str(win_app), str(installer.install_location(user, "win32")))
        self.assertEqual(len(win_scripts), 1)
        self.assertIn(f"$shortcut.TargetPath = '{sys.executable}'", win_scripts[0])
        win_launch = win_app / "launch.py"
        win_settings = win_app.parent / "settings.json"
        self.assertIn(f"$shortcut.Arguments = '\"{win_launch}\" --settings \"{win_settings}\"'", win_scripts[0])
        self.assertEqual(desktop_link.read_bytes(), b"faked shortcut v1")
        self.assertTrue((user / "Desktop" / "Ora Vibe Coder" / "Ora Vibe Coder.cmd").is_file())
        installed_icon = (win_app / "Ora Vibe Coder.ico").read_bytes()
        reserved, icon_type, entries = struct.unpack("<HHH", installed_icon[:6])
        self.assertEqual((reserved, icon_type, entries), (0, 1, 1))

        def failing_windows_shell(command, **kwargs):
            win_scripts.append(base64.b64decode(command[3]).decode("utf-16-le"))
            desktop_link.write_bytes(b"faked shortcut v2")
            return mock.Mock(returncode=1, stdout="", stderr="simulated shortcut failure")

        server_before = (win_app / "ora_vibe_coder/server.py").read_bytes()
        with mock.patch.object(installer.subprocess, "run", side_effect=failing_windows_shell):
            with mock.patch.object(installer, "os", WindowsName()):
                with self.assertRaisesRegex(ValueError, "desktop shortcut could not be created"):
                    install(source=release, home=user, hosts=(), platform="win32")
        self.assertEqual(len(win_scripts), 2)
        self.assertEqual(desktop_link.read_bytes(), b"faked shortcut v1")
        self.assertEqual((win_app / "ora_vibe_coder/server.py").read_bytes(), server_before)
        self.assertTrue((win_app / "ora-vibe-install.json").is_file())
        self.assertTrue((user / "Desktop" / "Ora Vibe Coder" / "Ora Vibe Coder.cmd").is_file())
        self.assertFalse(list(user.rglob(".ora-vibe-install-*")))

        with mock.patch.object(installer, "os", WindowsName()):
            remove(source=release, home=user, hosts=(), platform="win32")
        self.assertFalse(desktop_link.exists())
        self.assertFalse(win_app.exists())
        self.assertFalse((user / "Desktop" / "Ora Vibe Coder").exists())

    def test_setup_refuses_to_replace_a_newer_app_or_loop(self):
        # Setup never rolls back: a newer installed application or a newer
        # installed Programming Loop is named and nothing is changed.
        from ora_vibe_coder import installer
        user = self.home / "downgrade guard user"
        release = self.synthetic_release()
        install(source=release, home=user, hosts=("codex",), platform="darwin")
        app = Path(installer.install_location(user, "darwin"))
        identity = app / "ora-vibe-install.json"
        original = json.loads(identity.read_text(encoding="utf-8"))
        before = {str(path): path.read_bytes() for path in user.rglob("*") if path.is_file()}
        newer = dict(original, version="9.9.9")
        identity.write_text(json.dumps(newer, indent=2) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError,
                                    r"Vibe application.*records version 9\.9\.9.*Removing Ora Vibe Coder first"):
            install(source=release, home=user, hosts=("codex",), platform="darwin")
        after = {str(path): path.read_bytes() for path in user.rglob("*") if path.is_file()}
        self.assertEqual({k: v for k, v in after.items() if not k.endswith(identity.name)},
                         {k: v for k, v in before.items() if not k.endswith(identity.name)})
        self.assertFalse(list(user.rglob(".ora-vibe-install-*")))

        identity.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")
        loop_source = user / ".codex" / "skills" / "programming-loop" / "SOURCE.json"
        marker = json.loads(loop_source.read_text(encoding="utf-8"))
        marker["version"] = "9.9.9"
        loop_source.write_text(json.dumps(marker), encoding="utf-8")
        with self.assertRaisesRegex(ValueError,
                                    r"Programming Loop for codex records version 9\.9\.9.*Removing Ora Vibe Coder first"):
            install(source=release, home=user, hosts=("codex",), platform="darwin")
        self.assertEqual(json.loads(identity.read_text(encoding="utf-8")), original)
        self.assertEqual((app / "ora_vibe_coder/server.py").read_bytes(),
                         before[str(app / "ora_vibe_coder/server.py")])
        self.assertFalse(list(user.rglob(".ora-vibe-install-*")))

        # Equal versions install normally: the guard blocks only newer copies.
        marker.pop("version")
        loop_source.write_text(json.dumps(marker), encoding="utf-8")
        install(source=release, home=user, hosts=("codex",), platform="darwin")

    def test_fixed_vector_continuations_preserve_exact_saved_markdown(self):
        projects = self.home / "projects"
        projects.mkdir()
        store = ProjectStore(projects)
        project = store.projects[store.create("One", "One", "Purpose", "Goals")]
        packet = "Keep Unicode: café 日本語\n```sh\n$(touch NEVER_RUN); echo `not shell`\n```\n" + "long input\n" * 3000
        project.save_packet(packet)
        fake = self.home / "fake coding tool.py"
        receipt = self.home / "fake received.json"
        fake.write_text(
            "import json, pathlib, sys\n"
            "receipt = pathlib.Path(sys.argv[1])\n"
            "calls = json.loads(receipt.read_text()) if receipt.exists() else []\n"
            "calls.append(sys.argv[2:])\n"
            "receipt.write_text(json.dumps(calls))\n"
            "if '--json' in sys.argv[2:]: print(json.dumps({'sessionId': 'sess_fake_receipt'}))\n",
            encoding="utf-8",
        )
        for host, (name, _) in hosts.HOSTS.items():
            with self.subTest(host=host):
                receipt.unlink(missing_ok=True)
                operations = []

                def launch(args, options):
                    operation = Path(args[-1]).parent
                    operations.append(operation)
                    self.assertEqual((operation / "assignment.md").read_bytes(), packet.encode("utf-8"))
                    call = json.loads((operation / "launch.json").read_text())
                    self.assertEqual(call["cwd"], str(project.root))
                    self.assertNotIn(packet, json.dumps(call))
                    if host == "zcode":
                        self.assertEqual(call["kind"], "zcode")
                        self.assertEqual(call["packet"], str(operation / "assignment.md"))
                    else:
                        self.assertEqual(call["kind"], "direct")
                    self.assertEqual(hosts.run_operation(operation), 0)

                with mock.patch.object(hosts, "executable", return_value=[sys.executable, str(fake), str(receipt)]):
                    result = hosts.continue_in(project, packet, name, launch=launch, platform="darwin")
                    self.assertEqual(result["state"], "launch_requested")
                    self.assertIn("not confirmed", result["message"])
                    received = json.loads(receipt.read_text())
                    if host == "zcode":
                        self.assertEqual(received[0][0:7], [
                            "--cwd", str(project.root), "--mode", "plan",
                            "--max-turns", "1", "--json",
                        ])
                        self.assertEqual(received[0][7:9], ["--attach", str(operations[0] / "assignment.md")])
                        self.assertEqual(received[0][9:], ["--prompt", hosts.ZCODE_BOOTSTRAP])
                        self.assertEqual(received[1], [
                            "tui", "--cwd", str(project.root), "--mode", "build",
                            "--resume", "sess_fake_receipt",
                        ])
                    else:
                        self.assertIn("Read the complete UTF-8 Markdown assignment", received[0][-1])
                    if host == "qwen":
                        self.assertEqual(received[0][0], "--prompt-interactive")
                    if host == "hermes":
                        self.assertEqual(received[0][0:3], ["chat", "--tui", "-q"])
                    self.assertTrue(all(not operation.exists() for operation in operations))
        discovered = {host["id"]: host for host in hosts.discover()}
        self.assertTrue(all(item["continuation"] for item in discovered.values()))
        self.assertIn("receipt turn", discovered["zcode"]["notice"])
        self.assertIn("interactive TUI query", discovered["hermes"]["notice"])
        with mock.patch.object(hosts, "executable", return_value=[sys.executable]):
            with self.assertRaises(OSError):
                hosts.continue_in(
                    project, packet, "Codex",
                    launch=lambda *_: (_ for _ in ()).throw(OSError("terminal could not open")),
                    platform="darwin",
                )
        self.assertEqual(project.handoff_text(), packet)
        with self.assertRaisesRegex(Exception, "saved request changed"):
            hosts.continue_in(project, "unseen changed packet", "Codex")
        self.assertFalse((project.root / "NEVER_RUN").exists())

        # A selected code folder becomes the launch working directory, and a
        # location changed after preparation cannot silently continue a stale
        # saved assignment.
        from ora_vibe_coder.handoff import prepare_request
        code = self.home / "selected repository"
        code.mkdir()
        project.save_brief(project.brief_text(), "One", "Purpose", "Goals", {"Code": str(code)})
        prepared = prepare_request(project, "programming", "Fixed vector with a code folder", "Codex")
        self.assertIn(f"Repository / code folder: {code}\nStartup directory for the coding tool: {code}\n", prepared)
        project.save_packet(prepared, expected=packet)
        code_launches = []
        expected_assignment = prepared

        def code_launch(args, options):
            operation = Path(args[-1]).parent
            code_launches.append(operation)
            self.assertEqual((operation / "assignment.md").read_text(encoding="utf-8"), expected_assignment)
            call = json.loads((operation / "launch.json").read_text())
            self.assertEqual(call["cwd"], str(code))  # Launched in the selected code folder.
            self.assertEqual(hosts.run_operation(operation), 0)

        with mock.patch.object(hosts, "executable", return_value=[sys.executable, str(fake), str(receipt)]):
            result = hosts.continue_in(project, prepared, "Codex", launch=code_launch, platform="darwin")
        self.assertEqual(result["state"], "launch_requested")
        self.assertTrue(all(not operation.exists() for operation in code_launches))

        implementation = prepare_request(project, "implement-plan", "Implement visibly", "Codex")
        project.save_packet(implementation, "implement-plan")
        expected_assignment = implementation
        with mock.patch.object(hosts, "executable", return_value=[sys.executable, str(fake), str(receipt)]):
            result = hosts.continue_in(project, implementation, "Codex", purpose="implement-plan", launch=code_launch, platform="darwin")
        self.assertEqual(result["state"], "launch_requested")
        self.assertEqual(project.handoff_text(), prepared)
        self.assertTrue(all(not operation.exists() for operation in code_launches))

        moved = self.home / "moved repository"
        moved.mkdir()
        project.save_brief(project.brief_text(), "One", "Purpose", "Goals", {"Code": str(moved)})
        _, opened, _ = self.request("/api/open", {"path": str(project.root)})
        code, body, _ = self.request("/api/continue", {"id": opened["id"], "displayed": prepared, "destination": "Codex"})
        self.assertEqual(code, 400)
        self.assertIn("changed after this assignment was prepared", body["error"])

    def test_prepared_request_opens_the_selected_desktop_without_sending_it(self):
        projects = self.home / "projects"
        projects.mkdir()
        store = ProjectStore(projects)
        project = store.projects[store.create("One", "One", "Purpose", "Goals")]
        packet = "Full saved request with details that must not enter a link.\n"
        project.save_packet(packet)
        for host, (name, _) in hosts.HOSTS.items():
            with self.subTest(host=host):
                calls = []
                app = Path("/Applications") / hosts.DESKTOP_APPS[host]
                with mock.patch.object(hosts, "desktop_application", return_value=app):
                    result = hosts.continue_in(project, packet, name, route="desktop",
                                               launch=lambda args, options: calls.append((args, options)),
                                               platform="darwin")
                self.assertEqual(result["state"], "launch_requested")
                self.assertIn("not sent", result["message"])
                self.assertEqual(len(calls), 1)
                args, options = calls[0]
                self.assertEqual(options, {})
                if host in {"codex", "claude"}:
                    self.assertEqual(args[:3], ["open", "-a", str(app)])
                    url = urlsplit(args[3])
                    self.assertEqual(url.scheme, host)
                    values = parse_qs(url.query)
                    prompt = values["prompt" if host == "codex" else "q"][0]
                    self.assertIn(str(project.root / "Handoff.md"), prompt)
                    self.assertNotIn(packet, args[3])
                    self.assertEqual(values["path" if host == "codex" else "folder"], [str(project.root)])
                else:
                    self.assertEqual(args, ["open", "-a", str(app)])
                self.assertEqual(project.handoff_text(), packet)
        with mock.patch.object(hosts, "desktop_application", return_value=None):
            with self.assertRaisesRegex(ValueError, "desktop app was not found"):
                hosts.continue_in(project, packet, "Qwen Code", route="desktop", platform="darwin")

    def test_zcode_receipt_validation_and_resume_failure_preserve_recovery(self):
        projects = self.home / "projects"
        projects.mkdir()
        store = ProjectStore(projects)
        project = store.projects[store.create("One", "One", "Purpose", "Goals")]
        packet = "Exact assignment 日本語\n$(not shell)\n"
        project.save_packet(packet)
        captured = io.StringIO()
        calls = []

        def launch_with_failed_resume(args, options):
            operation = Path(args[-1]).parent
            with mock.patch.object(
                    hosts.subprocess, "run",
                    return_value=mock.Mock(returncode=0, stdout='{"sessionId":"sess_recover_me"}', stderr="")), \
                    mock.patch.object(hosts.subprocess, "call", side_effect=lambda argv, **kwargs: calls.append(argv) or 7), \
                    contextlib.redirect_stdout(captured):
                self.assertEqual(hosts.run_operation(operation), 7)

        with mock.patch.object(hosts, "executable", return_value=["/fixed/zcode", "entry.cjs"]):
            result = hosts.continue_in(
                project, packet, "ZCode", launch=launch_with_failed_resume,
                platform="darwin",
            )
        self.assertEqual(result["state"], "launch_requested")
        self.assertEqual(calls, [[
            "/fixed/zcode", "entry.cjs", "tui", "--cwd", str(project.root),
            "--mode", "build", "--resume", "sess_recover_me",
        ]])
        self.assertIn("implementation has not started", captured.getvalue())
        self.assertIn("/resume \"sess_recover_me\"", captured.getvalue())
        self.assertEqual(project.handoff_text(), packet)

        invalid_output = io.StringIO()
        outcomes = []

        def launch_with_invalid_receipt(args, options):
            operation = Path(args[-1]).parent
            with mock.patch.object(
                    hosts.subprocess, "run",
                    return_value=mock.Mock(returncode=0, stdout='{"sessionId":"wrong"}', stderr="")), \
                    mock.patch.object(hosts.subprocess, "call") as resume, \
                    contextlib.redirect_stdout(invalid_output):
                outcomes.append(hosts.run_operation(operation))
                resume.assert_not_called()

        with mock.patch.object(hosts, "executable", return_value=["/fixed/zcode", "entry.cjs"]):
            hosts.continue_in(
                project, packet, "ZCode", launch=launch_with_invalid_receipt,
                platform="darwin",
            )
        self.assertEqual(outcomes, [1])
        self.assertIn("delivery is unconfirmed", invalid_output.getvalue())
        self.assertIn("Handoff.md", invalid_output.getvalue())
        self.assertEqual(project.handoff_text(), packet)

    def test_browser_open_failure_still_allows_stop_and_joins_owned_server(self):
        self.close()
        server = LocalServer(self.home)
        def failed_browser(url):
            server.shutdown()
            return False
        serve(server, opener=failed_browser)
        self.assertEqual(server.fileno(), -1)


if __name__ == "__main__":
    unittest.main()
