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
import time
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest import mock

from playwright.sync_api import expect, sync_playwright

from ora_vibe_coder import __main__ as app_entry, conversation, hosts, project as project_module
from ora_vibe_coder.installer import install, launcher_files, remove
from ora_vibe_coder.launcher import AppLock, Settings, request_quit, serve
from ora_vibe_coder.project import ProjectStore
from ora_vibe_coder.server import LocalServer, REQUEST_LIMIT

def stalled_inventory_reader():
    """Run genuine non-returning calls inside the owned discovery process."""
    original_scandir = project_module.os.scandir
    original_read = project_module.read_text

    @contextlib.contextmanager
    def scan(path):
        root = Path(path)
        if (root / ".stall-folder").exists():
            (root / ".entered-folder").touch()
            threading.Event().wait()  # Only terminating the owned process can cancel this.
        with original_scandir(path) as items:
            if (root / ".stall-after-entries").exists():
                def partial():
                    yield from items
                    (root / ".entered-partial").touch()
                    threading.Event().wait()
                yield partial()
            else:
                yield items

    def read(path, *args, **kwargs):
        root = Path(path).parent
        if (root / ".stall-file").exists():
            (root / ".entered-file").touch()
            threading.Event().wait()
        return original_read(path, *args, **kwargs)

    with mock.patch.object(project_module.os, "scandir", side_effect=scan), \
            mock.patch.object(project_module, "read_text", side_effect=read):
        project_module._inventory_reader()

def compact_value(tool, model=""):
    return json.dumps([tool, model], separators=(",", ":")) if tool else ""

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

    @contextlib.contextmanager
    def browser_session(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                yield browser
            finally:
                browser.close()

    def select_project(self, page, project_id):
        page.locator("#project").select_option(project_id)

    def choose_primary(self, page, label):
        tool = next(key for key, value in hosts.HOSTS.items() if value[0] == label)
        page.locator("#primary-choice .role-model-choice").select_option(compact_value(tool))

    def test_mid_run_message_targets_origin_and_preserves_failed_draft(self):
        first = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
        second = self.request("/api/create", {"directory": "Two", "name": "Two", "description": "", "goals": ""})[1]["id"]
        project = self.server.store.projects[first]
        handle = conversation.TurnOperation(project.root, "codex", "specification", {})
        handle.turn, handle.run, handle.state = "0001-20261028-120000", "original-run", "running"
        handle.input_target = {"thread_id": "owned-thread", "turn_id": "owned-turn"}
        sent, delivered = [], threading.Event()
        pipe = io.StringIO()
        def write(line):
            sent.append(json.loads(line))
            delivered.set()
        pipe.write = write
        handle.input_process = mock.Mock(stdin=pipe)
        self.server.conversation.by_project[str(project.root)] = handle
        ready = {"ready": True, "work": "supported", "authentication": "confirmed", "warnings": []}
        with mock.patch.object(conversation, "bridge_check", side_effect=lambda peer, **kwargs: {"peer": peer, **ready}), \
                mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), self.browser_session() as browser:
            try:
                page = browser.new_page()
                page.goto(self.server.url)
                self.select_project(page, first)
                expect(page.locator("#send")).to_have_text("Send message to working Codex")
                expect(page.locator("#send")).to_be_enabled()
                page.locator("#message").fill("Exact originating correction.")
                page.locator("#send").click()
                page.wait_for_function("() => document.querySelector('#send').disabled")
                self.select_project(page, second)
                page.wait_for_function("() => pollTimer !== null && lastOperation === null")
                page.locator("#message").fill("Keep this other project's draft.")
                self.assertTrue(delivered.wait(5), "The originating agent did not receive the message.")
                self.assertEqual((sent[0]["thread_id"], sent[0]["turn_id"], sent[0]["text"]),
                                 ("owned-thread", "owned-turn", "Exact originating correction."))
                handle.observe({"event": "work_input", **sent[0], "status": "accepted"})
                expect(page.locator("#status-bar")).to_contain_text("accepted the message")
                expect(page.locator("#message")).to_have_value("Keep this other project's draft.")
                self.select_project(page, first)
                expect(page.locator("#send")).to_have_text("Send message to working Codex")
                delivered.clear()
                page.locator("#message").fill("Preserve this refused correction.")
                page.locator("#send").click()
                self.assertTrue(delivered.wait(5), "The refusal request did not reach the agent.")
                handle.observe({"event": "work_input", **sent[1], "status": "refused", "reason": "active turn changed"})
                expect(page.locator("#status-bar")).to_contain_text("active turn changed")
                expect(page.locator("#message")).to_have_value("Preserve this refused correction.")
                old = {"id": first, "turn": handle.turn, "run": handle.run, "target": dict(handle.input_target), "text": "stale"}
                handle.turn = "0002-20261028-120001"
                self.assertEqual(self.request("/api/turn-input", old)[0], 400)
                handle.tool, handle.input_target = "zcode", None
                page.evaluate("async () => {const data = await api('turn-state', {id: currentId}); updateOperation(data.operation);}")
                expect(page.locator("#send")).to_be_disabled()
                page.locator("#message").press("Enter")
                expect(page.locator("#status-bar")).to_contain_text("cannot receive a live message")
                expect(page.locator("#message")).to_have_value("Preserve this refused correction.")
                self.assertEqual(len(sent), 2)
            finally:
                handle.close_input()
                browser.close()

    def test_project_header_keeps_selection_and_details_on_one_row(self):
        name = "Project with a long descriptive name"
        description = "Complete description.\nA second line."
        first = self.request("/api/create", {"directory": "One", "name": name, "parent": "Ora → Projects",
                                             "description": description, "goals": "Save notes"})[1]["id"]
        with self.browser_session() as browser:
            page = browser.new_page()
            page.goto(self.server.url)
            self.select_project(page, first)
            page.wait_for_function("() => pollTimer !== null && lastFiles !== null")
            page.locator("#project-card").click()
            for field, text in (("name", name), ("parent", "Ora → Projects"),
                                ("description", description), ("goals", "Save notes")):
                expect(page.locator(f"#edit-{field}")).to_have_value(text)
            page.locator("#edit-description").fill(description + " Revised")
            expect(page.locator("#project-unsaved")).to_be_visible()
            page.locator("#edit-close").click()
            page.locator("#project-card").click()
            expect(page.locator("#edit-description")).to_have_value(description + " Revised")
            page.locator("#edit-save").click()
            expect(page.locator("#project-unsaved")).to_be_hidden()
            self.assertIn(description + " Revised", (self.home / "One/Project.md").read_text())
            page.locator("#project").evaluate("element => element.blur()")
            second = self.request("/api/create", {"directory": "Two", "name": "Two", "description": "", "goals": ""})[1]["id"]
            page.locator("#project").focus()
            expect(page.locator(f'#project option[value="{second}"]')).to_have_count(1)
            expect(page.locator("#project")).to_have_value(first)
            page.keyboard.press("Escape")
            loose = self.home / "Loose"
            loose.mkdir()
            (loose / "Notes.md").write_text("# Notes\n\nA loose document.\n")
            page.evaluate("async path => { const result = await api('open', {path}); await chooseProject(result.id); }", str(loose))
            page.locator("#document").select_option("Notes.md")
            expect(page.locator("#reader")).to_contain_text("A loose document.")

    def test_completed_turn_status(self):
        project_id = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
        with self.browser_session() as browser:
            try:
                page = browser.new_page(viewport={"width": 1600, "height": 1000})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(self.server.url)
                self.select_project(page, project_id)
                page.wait_for_function("() => pollTimer !== null && lastFiles !== null")
                page.evaluate("() => stopPolling()")
                bar = page.locator("#status-bar")
                expect(page).to_have_title("One — Vibe Coder")
                state = {"project": str(self.home / "One"), "turn": "dispatch", "stage": "specification",
                         "activity": "Updating", "state": "running", "elapsed_seconds": 330,
                         "last_contact_seconds": 2, "bridge_diagnostics": ["Connector version is old."]}
                page.evaluate("op => updateOperation(op)", state)
                expect(bar).to_have_text("Specification · Updating · 5:30")
                expect(bar).to_have_class("active")
                expect(page).to_have_title("\U0001F7E2 Working — One")
                page.evaluate("op => updateOperation(op)", dict(state, state="finished", elapsed_seconds=331))
                expect(bar).to_have_text("Specification · Finished · 5:31")
                expect(page).to_have_title("One — Vibe Coder")
                warning = dict(state, state="finished", maintenance="stale",
                               maintenance_reason="The Registry changed, so nothing was applied.",
                               warnings=["Connector version is old.", "The outcome note could not be recorded: disk is full."],
                               visible_warnings=["The outcome note could not be recorded: disk is full."])
                page.evaluate("op => updateOperation(op)", warning)
                expect(bar).to_have_class("waiting")
                for notice in ("Registry changed", "outcome note could not be recorded"):
                    expect(bar).to_contain_text(notice)
                expect(bar).not_to_contain_text("Connector version is old.")
                active = dict(state, stage="programming", activity="Coding", elapsed_seconds=1508)
                page.evaluate("op => updateOperation(op)", active)
                expect(bar).to_have_text("Implementation · Coding · 25:08")
                waiting = dict(active, state="failed", reason="Sign in to the selected tool, then inspect saved work.")
                page.evaluate("op => updateOperation(op)", waiting)
                expect(bar).to_have_class("waiting")
                expect(bar).to_contain_text("Implementation · Waiting · 25:08")
                stopped = dict(active, state="interrupted", reason="Stopped by the user.")
                page.evaluate("op => updateOperation(op)", stopped)
                expect(bar).to_have_text("Implementation · Stopped · 25:08")
                expect(bar).not_to_have_class("active")
                expect(bar).not_to_have_class("waiting")
                self.assertEqual(errors, [])
            finally:
                browser.close()

    def test_tab_activity_updates_while_hidden_and_stays_with_its_project(self):
        projects = {name: self.request("/api/create", {"directory": name, "name": name,
                    "description": "", "goals": ""})[1]["id"] for name in ("Background One", "Background Two")}
        first, second = projects.values()
        states = {id: self.request("/api/turn-state", {"id": id})[1] for id in projects.values()}
        records = {id: {"turns": [], "runs": []} for id in projects.values()}
        requests, errors = [], []
        disconnected = set()

        def ready(peer, **kwargs):
            return {"peer": peer, "ready": True, "work": "supported", "authentication": "confirmed", "warnings": []}

        with mock.patch.object(conversation, "bridge_check", side_effect=ready), \
                mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), self.browser_session() as browser:
            context = browser.new_context(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
            context.add_init_script("""window.tabVisibility = 'visible';
                Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => tabVisibility});""")
            try:
                def route_api(route):
                    endpoint = urlsplit(route.request.url).path.rsplit("/", 1)[-1]
                    id = route.request.post_data_json.get("id")
                    requests.append((endpoint, id))
                    if endpoint == "turn-state" and id in disconnected:
                        route.abort("connectionrefused")
                        return
                    data = states.get(id) if endpoint == "turn-state" else records.get(id) if endpoint == "conversation" else None
                    if data is None:
                        route.continue_()
                        return
                    body = json.dumps(data)
                    route.fulfill(content_type="application/json", body=body)

                context.route("**/api/**", route_api)
                pages = []
                for id in (first, second):
                    page = context.new_page()
                    pages.append(page)
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(self.server.url)
                    if id == first:
                        page.evaluate("() => { tabVisibility = 'hidden'; document.dispatchEvent(new Event('visibilitychange')); }")
                    self.select_project(page, id)
                    page.wait_for_function("id => currentId === id && conversationLoaded && pollTimer !== null && lastFiles !== null", arg=id)
                    if id == second:
                        page.evaluate("() => stopPolling()")
                background, other = pages
                background.locator("#message").fill("Keep this background draft.")
                other.locator("#message").fill("Keep the other tab's draft.")
                expect(background).to_have_title("Background One — Vibe Coder")
                expect(other).to_have_title("Background Two — Vibe Coder")
                background.evaluate("() => { tabVisibility = 'hidden'; document.dispatchEvent(new Event('visibilitychange')); }")
                reads_before = [item for item in requests if item[0] in ("project", "read-file")]

                operation = {"project": str(self.home / "Background One"), "turn": "background-turn",
                             "tool": "codex", "stage": "specification", "state": "running", "activity": "Discussing",
                             "elapsed_seconds": 4, "outcome_recorded": True, "warnings": [], "visible_warnings": []}
                states[first]["operation"] = operation
                background.evaluate("() => pollTick()")
                expect(background).to_have_title("🟢 Working — Background One")
                expect(other).to_have_title("Background Two — Vibe Coder")
                document = self.home / "Background One" / "Specification.md"
                document.write_text("# Specification\n\nA document changed while the tab was hidden.\n", encoding="utf-8")
                states[first]["files"] = self.request("/api/turn-state", {"id": first})[1]["files"]
                records[first]["turns"] = [{"turn": operation["turn"], "tool": "codex", "stage": "specification",
                    "purpose": "work", "state": "complete", "text": "A saved request.", "images": [], "files": [],
                    "reply": "Questions for you\n- Which option should I use?", "questions": ["Which option should I use?"],
                    "outcome_recorded": True, "maintenance": None, "artifact": None, "bridge_diagnostics": []}]
                operation["state"] = "finished"
                expect(background).to_have_title("🟡 Waiting — Background One")
                background.evaluate("() => { clearInterval(pollTimer); pollTimer = null; }")
                expect(background.locator("#status-bar")).to_contain_text("Answer the questions")
                self.assertEqual([item for item in requests if item[0] in ("project", "read-file")], reads_before)
                expect(background.locator("#message")).to_have_value("Keep this background draft.")

                states[second]["operation"] = dict(operation, project=str(self.home / "Background Two"),
                                                   turn="other-turn", state="running")
                other.evaluate("() => pollTick()")
                expect(other).to_have_title("🟢 Working — Background Two")
                expect(background).to_have_title("🟡 Waiting — Background One")
                expect(other.locator("#message")).to_have_value("Keep the other tab's draft.")

                background.evaluate("async () => { tabVisibility = 'visible'; await pollTick(); }")
                expect(background.locator("#reader")).to_contain_text("A document changed while the tab was hidden.")
                expect(background).to_have_title("🟡 Waiting — Background One")
                self.assertEqual([item for item in requests if item[0] in ("project", "read-file")][len(reads_before):],
                                 [("project", first), ("read-file", first)])
                background.evaluate("() => { tabVisibility = 'hidden'; document.dispatchEvent(new Event('visibilitychange')); }")
                operation.update(state="failed", reason="The selected tool needs attention.")
                background.evaluate("() => pollTick()")
                expect(background).to_have_title("🟡 Waiting — Background One")
                disconnected.add(first)
                background.evaluate("() => pollTick()")
                expect(background).to_have_title("🔴 Problem — Background One")
                expect(background.locator("#status-bar")).to_contain_text("Lost contact")
                disconnected.remove(first)
                background.evaluate("() => pollTick()")
                expect(background).to_have_title("🟡 Waiting — Background One")
                states[first]["operation"] = None
                background.evaluate("() => pollTick()")
                expect(background).to_have_title("Background One — Vibe Coder")

                expect(other.locator("#message")).to_have_value("Keep the other tab's draft.")
                self.assertEqual(errors, [])
            finally:
                browser.close()

    def test_routine_readback_receipts_stay_in_records_not_on_the_cards(self):
        project_id = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
        with self.browser_session() as browser:
            try:
                page = browser.new_page()
                page.goto(self.server.url)
                self.select_project(page, project_id)
                page.wait_for_function("() => pollTimer !== null && lastFiles !== null")
                page.evaluate("() => stopPolling()")
                routine = {"role": "Specification", "path": "/selected/Specification.md", "outcome": "changed",
                           "reason": "The selected Specification is readable and differs from the content captured when this turn began."}
                unreadable = {"role": "Plan", "path": "/selected/Plan.md", "outcome": "unreadable",
                              "reason": "The selected Plan could not be read back: permission denied."}
                page.evaluate("turns => { conversationTurns = turns; renderConversation(); }", [
                    {"turn": "saved-turn", "stage": "specification", "tool": "codex", "purpose": "work",
                     "text": "The work request.", "images": [], "files": [], "state": "complete",
                     "reply": "The substantive saved reply.", "maintenance": None, "outcome_recorded": True,
                     "artifact": routine, "bridge_diagnostics": [], "questions": []},
                    {"turn": "unreadable-turn", "stage": "plan", "tool": "codex", "purpose": "work",
                     "text": "Another request.", "images": [], "files": [], "state": "complete",
                     "reply": "The reply whose file could not be confirmed.", "maintenance": None,
                     "outcome_recorded": True, "artifact": unreadable, "bridge_diagnostics": [], "questions": []}])
                conversation = page.locator("#conversation")
                expect(conversation).to_contain_text("The substantive saved reply.")
                expect(conversation).to_contain_text("The reply whose file could not be confirmed.")
                expect(conversation).to_contain_text("The selected Plan could not be read back: permission denied.")
                expect(conversation).not_to_contain_text("differs from the content captured")
                expect(conversation).not_to_contain_text("Local file:")
                self.assertEqual(conversation.locator(".artifact-readback").count(), 1)
                self.assertEqual(conversation.locator("summary", has_text="Local file").count(), 0)
                page.evaluate("runs => { reviewRuns = runs; renderConversation(); }", [
                    {"run": "review-run", "stage": "review-specification", "state": "finished", "tool": "codex",
                     "output": "Verdict: COMPLETE — the Specification meets its requirements.",
                     "assessment": "applied",
                     "artifact": {"role": "Specification", "path": "/selected/Specification.md", "outcome": "unchanged",
                                  "reason": "The selected Specification is readable and unchanged since this turn began."},
                     "questions": []}])
                expect(conversation).to_contain_text("Verdict: COMPLETE — the Specification meets its requirements.")
                expect(conversation).not_to_contain_text("unchanged since this turn began")
                expect(conversation).not_to_contain_text("Local file:")
                self.assertEqual(conversation.locator(".artifact-readback").count(), 1)
                page.evaluate("operation => updateOperation(operation)",
                              {"turn": "saved-turn", "state": "finished", "elapsed_seconds": 4,
                               "maintenance": None, "warnings": [], "bridge_diagnostics": [], "visible_warnings": [],
                               "artifact": routine})
                expect(page.locator("#more")).to_have_count(0)
                expect(page.locator("#status-bar")).not_to_contain_text("differs from the content captured")
                expect(page.locator("#status-bar")).not_to_contain_text("Local file:")
            finally:
                browser.close()

    def test_step7_copy_works_without_a_selected_tool_while_send_still_refuses(self):
        project_id = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
        folder = self.home / "One"
        def ready(peer, **kwargs):
            return {"peer": peer, "ready": True, "work": "supported", "authentication": "unknown", "warnings": []}
        with mock.patch("ora_vibe_coder.conversation.bridge_check", side_effect=ready), \
                mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), self.browser_session() as browser:
            context = browser.new_context(permissions=["clipboard-read", "clipboard-write"])
            try:
                page = context.new_page()
                page.goto(self.server.url)
                page.evaluate("() => { window.clipboardText = ''; navigator.clipboard.writeText = text => { window.clipboardText = text; return Promise.resolve(); }; }")
                self.select_project(page, project_id)
                page.wait_for_function("() => pollTimer !== null && lastFiles !== null")
                page.evaluate("() => stopPolling()")
                page.locator('.rail[data-stage="build"]').click()
                page.wait_for_function("() => workspace === 'build'")
                self.assertEqual(page.evaluate("destinationName"), "")
                page.locator("#review-step").evaluate("element => element.open = true")
                page.locator("#review").click()
                expect(page.locator("#build-action-dialog")).to_be_visible()
                expect(page.locator("#build-action-title")).to_have_text("Independently verify the implementation")
                expect(page.locator("#build-action-note")).to_contain_text("Copy works without one")
                expect(page.locator("#build-action-send")).to_be_hidden()
                page.locator("#build-action-copy").click()
                expect(page.locator("#build-action-dialog")).not_to_be_visible()
                try:
                    expect(page.locator("#status-bar")).to_contain_text(
                        "Independently verify the implementation request copied and saved", timeout=8000)
                except AssertionError:
                    raise AssertionError(f"copy status: {page.locator('#status-bar').inner_text()[:400]} / handoff exists: {(folder / 'Handoff.md').exists()}") from None
                saved = (folder / "Handoff.md").read_text(encoding="utf-8")
                self.assertIn("Coordinate a fresh, independent Ora Verification review", saved)
                self.assertEqual(page.evaluate("() => window.clipboardText"), saved)
                _status, recorded, _headers = self.request("/api/conversation", {"id": project_id})
                self.assertEqual(recorded["turns"], [])
                page.evaluate("() => deliverStep('verification', 'send')")
                expect(page.locator("#status-bar")).to_contain_text(
                    "Choose the coding tool in step 3 first; Copy works only from a prepared request.")
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
        files["plugins/ora-vibe-coder/resources/programming-loop/VERSION"] = "1.2.1\n"
        files["plugins/ora-vibe-coder/resources/programming-loop/scripts/install.py"] = '''
import argparse, hashlib, json, shutil, sys
from pathlib import Path

HOSTS = {"codex": ".codex", "claude": ".claude", "zcode": ".zcode", "hermes": ".hermes", "qwen": ".qwen", "minimax": ".minimax"}
parser = argparse.ArgumentParser()
parser.add_argument("action", choices=("install", "remove", "install-check", "remove-check"))
parser.add_argument("--host", choices=HOSTS, required=True)
parser.add_argument("--home", type=Path, required=True)
args = parser.parse_args()
skill = args.home / HOSTS[args.host] / "skills/ora-programming-loop"
if args.action in ("install", "install-check"):
    installed = None
    if (skill / "SOURCE.json").is_file():
        try:
            installed = json.loads((skill / "SOURCE.json").read_text(encoding="utf-8")).get("version")
        except ValueError:
            installed = None
    try:
        newer = isinstance(installed, str) and tuple(int(part) for part in installed.split(".")) > (1, 2, 1)
    except ValueError:
        newer = False
    if newer:
        print("Ora Programming Loop: The installed Ora Programming Loop version "
              + installed + " is newer than the supplied version 1.2.1; the newer "
              "installation was kept and nothing was changed.", file=sys.stderr)
        raise SystemExit(1)
if args.action == "install-check" or args.action == "remove-check":
    raise SystemExit(0)
if args.action == "install":
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text("synthetic loop entry")
    (skill / "SOURCE.json").write_text(json.dumps({
        "component": "ora-programming-loop", "source": "ora-programming-loop",
        "version": "1.2.1", "source_kind": "vendored-snapshot",
        "files": {"SKILL.md": hashlib.sha256(b"synthetic loop entry").hexdigest()}}))
elif skill.exists():
    shutil.rmtree(skill)
'''
        for name, text in files.items():
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        shutil.copytree(
            Path(__file__).resolve().parents[1] / "components/agent-bridge",
            source / "components/agent-bridge",
        )
        shutil.copytree(
            Path(__file__).resolve().parents[1] / "components/ora-ai-boost",
            source / "components/ora-ai-boost",
        )
        return source

    def test_first_specification_suggestion_and_message_file_selection(self):
        project_id = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
        other_id = self.request("/api/create", {"directory": "Two", "name": "Two", "description": "", "goals": ""})[1]["id"]
        shared = self.home / "Other notes"
        shared.mkdir()
        note = shared / "Outside context.md"
        note.write_text("A note from another folder.\n", encoding="utf-8")
        submitted = []
        with self.browser_session() as browser:
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
                self.choose_primary(page, "Codex")
                page.locator("#message").press("Enter")
                expect(page.locator("#status-bar")).to_contain_text("Test stopped before dispatch")
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

    def test_projects_open_at_progress_and_rails_slide_without_losing_drafts(self):

        settings = Settings(self.home / "navigation-settings.json")
        self.server.settings = settings
        projects = {}
        for name in ("Fresh", "Specification", "Planning", "Approved", "Build", "Verification",
                     "Templates", "RetainedPlan", "RetainedBuild", "ReviewPlan", "ActivePlan", "ActiveBuild", "ActiveRun"):
            projects[name] = self.request("/api/create", {"directory": name, "name": name,
                                                         "description": "", "goals": ""})[1]["id"]

        def document(name, role, text):
            root = self.server.store.projects[projects[name]].root
            target = root / (f"{name} — {role}.md" if role in {"Specification", "Plan"} else f"{role}.md")
            target.write_text(text, encoding="utf-8")
            return target

        document("Specification", "Specification", "# Specification\n\nStatus: COMPLETE\n\nA small app that saves a user's notes.\n")
        document("Planning", "Plan", "# Plan\n\nStatus: DRAFT\n\nUse the current note editor and save files locally.\n")
        document("Approved", "Plan", "# Plan\n\nStatus: APPROVED\n\nUse the current note editor and save files locally.\n")
        document("Build", "Programming Result", "# Programming Result\n\nStatus: IN PROGRESS\n\nThe note editor now saves local files.\n")
        document("Verification", "Verification Report", "# Verification Report\n\nVerdict: INCOMPLETE\n\nThe saved file was checked; reopening still needs inspection.\n")
        document("Templates", "Programming Result", "# Programming Result\n\nStatus: NOT STARTED\n\n## Changes\n\n## Checks\n")
        document("Templates", "Verification Report", "# Verification Report\n\n## Verdict\n\n## Findings\n")
        (self.home / "Specification" / "Specification — Implementation Request.md").write_text(
            "# Implementation Request\n\nImplement the Plan when I send this.\n", encoding="utf-8")

        def retain(name, stage, purpose=conversation.PURPOSE_WORK):
            root = self.server.store.projects[projects[name]].root
            messages = root / ".vibe" / "0001-20261023-120000" / "session" / "messages"
            messages.mkdir(parents=True)
            body = conversation.user_note_body(stage, "codex", "Work already submitted on this stage.", [])
            body = body.replace(f"Vibe-Purpose: {conversation.PURPOSE_WORK}", f"Vibe-Purpose: {purpose}")
            (messages / "0001-initiator-record.md").write_text(f"# Message 0001\nKind: note\n\n## Body\n\n{body}", encoding="utf-8")

        retain("RetainedPlan", "planning")
        retain("RetainedBuild", "programming-result")
        retain("ReviewPlan", "review-plan", conversation.PURPOSE_AUTHOR)
        for name, stage in (("ActivePlan", "planning"), ("ActiveBuild", "verification")):
            active = self.server.store.projects[projects[name]]
            handle = conversation.TurnOperation(active.root, "codex", stage, {})
            handle.turn = f"live-{name}"
            handle.state = "running"
            self.server.conversation.by_project[str(active.root)] = handle
        from ora_vibe_coder.run import RunDriver
        active = self.server.store.projects[projects["ActiveRun"]]
        driver = RunDriver(self.server.conversation, active, "build", "An existing automatic run.", {}, {}, "codex")
        driver.run = "0001-20261023-120001"
        driver.state = "paused-question"
        self.server.runs.by_project[str(active.root)] = driver

        def ready(peer, **kwargs):
            return {"peer": peer, "ready": True, "work": "supported", "authentication": "confirmed", "warnings": []}

        with mock.patch("ora_vibe_coder.conversation.bridge_check", side_effect=ready), \
                mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), \
                mock.patch("ora_vibe_coder.conversation.start_turn") as dispatch, \
                mock.patch("ora_vibe_coder.conversation.start_assessment") as assess, \
                mock.patch("ora_vibe_coder.conversation.start_aux") as auxiliary, self.browser_session() as browser:
            context = browser.new_context(viewport={"width": 1440, "height": 1000},
                                          permissions=["clipboard-read", "clipboard-write"], reduced_motion="no-preference")
            try:
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(self.server.url)
                page.wait_for_function("() => project?.name === 'ActiveRun' && workspace === 'build' && pollTimer !== null && lastFiles !== null")

                def opened(name, stage):
                    self.select_project(page, projects[name])
                    page.wait_for_function("data => currentId === data.id && project?.name === data.name && workspace === data.stage && pollTimer !== null && lastFiles !== null",
                                           arg={"id": projects[name], "name": name, "stage": stage})
                    expect(page.locator("#stage-title")).to_have_text({"specification": "Specification", "plan": "Plan", "build": "Build & Verify"}[stage])

                def settled(stage):
                    page.wait_for_function("() => workspaceReveal === null && workspaceAnimations.every(animation => animation.playState === 'finished' || animation.playState === 'idle')")
                    expect(page.locator(f'.rail[data-stage="{stage}"]')).to_have_attribute("aria-expanded", "true")

                for name, stage in (("Fresh", "specification"), ("Specification", "specification"),
                                    ("Planning", "plan"), ("Approved", "plan"), ("Build", "build"),
                                    ("Verification", "build"), ("Templates", "specification"),
                                    ("RetainedPlan", "plan"), ("RetainedBuild", "build"),
                                    ("ReviewPlan", "plan"), ("ActivePlan", "plan"), ("ActiveBuild", "build"),
                                    ("ActiveRun", "build")):
                    opened(name, stage)
                    settled(stage)
                self.assertEqual(driver.state, "paused-question")
                self.assertTrue(all(handle.state == "running" for handle in self.server.conversation.by_project.values()))

                opened("Specification", "specification")
                self.choose_primary(page, "Codex")
                page.evaluate("() => deliverStep('create-plan', 'copy')")
                expect(page.locator("#status-bar")).to_contain_text("Create the Plan request copied and saved")
                self.assertTrue((self.home / "Specification" / "Handoff.md").is_file())
                opened("Fresh", "specification")
                opened("Specification", "specification")
                expect(page.locator("#next-step-title")).to_have_text("Create the Plan")

                page.locator("#message").fill("Keep this unsent instruction.")
                picture = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c020000000b4944415478da6364f80f00010501012718e3660000000049454e44ae426082")
                page.locator("#image-input").set_input_files({"name": "draft.png", "mimeType": "image/png", "buffer": picture})
                expect(page.locator("#attachment-bar img")).to_have_attribute("alt", "draft.png")
                note = self.home / "material.txt"
                note.write_text("Existing material.")
                page.evaluate("path => messageFilesFor(currentId, 'specification').push({path, name: 'material.txt'})", str(note))
                document("Specification", "Plan", "# Plan\n\nStatus: DRAFT\n\nNEW PLAN: save notes locally.\n")
                page.locator('.rail[data-stage="plan"]').click()
                page.wait_for_function("() => workspaceReveal !== null && workspaceAnimations.some(animation => animation.playState === 'running' && animation.effect.target.classList.contains('rail'))")
                settled("plan")
                expect(page.locator("#reader")).to_contain_text("NEW PLAN:")
                for stage in ("build", "specification"):
                    page.locator(f'.rail[data-stage="{stage}"]').click()
                    settled(stage)
                    expect(page.locator("#message")).to_have_value("Keep this unsent instruction.")
                    expect(page.locator("#attachment-bar img")).to_have_attribute("alt", "draft.png")
                expect(page.locator("#message-files")).to_contain_text("material.txt")

                page.locator("#message").fill("")
                page.locator('#attachment-bar button').click()
                page.locator('.rail[data-stage="specification"]').click()
                settled("specification")
                page.reload()
                page.wait_for_function("() => project?.name === 'Specification' && workspace === 'plan' && pollTimer !== null")
                expect(page.locator("#next-step-title")).to_have_text("Implement the Plan")
                page.set_viewport_size({"width": 1440, "height": 1000})
                dispatch.assert_not_called()
                assess.assert_not_called()
                auxiliary.assert_not_called()
                self.assertEqual(errors, [])
            finally:
                context.close()
                browser.close()
                self.server.conversation.by_project.clear()
                self.server.runs.by_project.clear()

    def test_coding_tool_follows_project_across_stages_without_another_readiness_check(self):
        first = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
        second = self.request("/api/create", {"directory": "Two", "name": "Two", "description": "", "goals": ""})[1]["id"]
        def ready(peer, **kwargs):
            return {"peer": peer, "ready": True, "work": "supported", "authentication": "confirmed", "warnings": []}
        with mock.patch.object(conversation, "bridge_check", side_effect=ready) as probes, \
                mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), \
                mock.patch("ora_vibe_coder.server.model_inventory", return_value={"models": []}), \
                self.browser_session() as browser:
            page = browser.new_page()
            page.goto(self.server.url)
            self.select_project(page, first)
            self.choose_primary(page, "Codex")
            page.wait_for_function("() => peerFacts('codex')?.authentication === 'confirmed'")
            expect(page.locator("#tool-problem")).to_contain_text("Gear (optional): primary analytical role available.")
            checked = probes.call_count
            for stage in ("plan", "build", "specification"):
                page.locator(f'.rail[data-stage="{stage}"]').click()
                self.assertEqual(page.evaluate("destinationName"), "Codex")
            self.assertEqual(probes.call_count, checked)
            self.select_project(page, second)
            page.wait_for_function("() => project?.name === 'Two' && destinationName === ''")
            self.select_project(page, first)
            page.wait_for_function("() => project?.name === 'One' && destinationName === 'Codex'")

    def test_document_outcomes_and_build_send_copy_agree(self):
        project_name = "Sample — Inspect the map"
        directory = "Stored project folder"
        project_id = self.request("/api/create", {"directory": directory, "name": project_name, "description": "", "goals": ""})[1]["id"]
        folder = self.home / directory
        for role in ("Specification", "Plan"):
            path = folder / f"{project_name} — {role}.md"
            (folder / f"{role}.md").rename(path)
            path.write_text(f"---\nreview: PASSED\n---\n# {role}\n\n## Scope\nThe agreed work.\n\n## Current review\nThe agreed scope sufficiently guides the work.\n", encoding="utf-8")
        result = folder / f"{project_name} — Programming Result current.md"
        report = folder / f"{project_name} — Verification Report current.md"
        result.write_text("---\nstatus: PASSED\n---\n# Programming Result\n\nProgramming completed 8 October 2026 under the approved Plan.\n", encoding="utf-8")
        passing_report = ("---\nstatus: PASSED\n---\n# Verification Report\n\n**PASSED.** "
                          "The map meets the approved check by direct static inspection. No material finding remains. "
                          "This verifies the map only; it does not implement or accept anything. The user owns acceptance.\n")
        report.write_text(passing_report, encoding="utf-8")
        (folder / f"{project_name} — Implementation Request.md").write_text("EXACT_IMPLEMENTATION_REQUEST", encoding="utf-8")
        (folder / f"{directory} — Working notes v2.1.MARKDOWN").write_text("EXACT_WORKING_NOTES", encoding="utf-8")
        evidence = folder / "Selected evidence.txt"
        evidence.write_text("EXACT_SELECTED_EVIDENCE", encoding="utf-8")
        original_files = {path.name: path.read_bytes() for path in folder.iterdir() if path.is_file()}
        def ready(peer, **kwargs):
            return {"peer": peer, "ready": True, "work": "supported", "authentication": "unknown", "warnings": []}
        with mock.patch("ora_vibe_coder.conversation.bridge_check", side_effect=ready), \
                mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), \
                mock.patch("ora_vibe_coder.server.model_inventory", return_value={"models": []}), self.browser_session() as browser:
            context = browser.new_context(permissions=["clipboard-read", "clipboard-write"])
            try:
                page = context.new_page()
                page.goto(self.server.url)
                page.evaluate("() => { window.clipboardText = ''; navigator.clipboard.writeText = text => { window.clipboardText = text; return Promise.resolve(); }; }")
                self.select_project(page, project_id)
                page.locator('.rail[data-stage="specification"]').click()
                expect(page.locator("#assessment")).to_have_text("PASSED")
                expect(page.locator("#assessment-note")).to_contain_text("applicability to the current document version is unconfirmed")
                expected_labels = {
                    f"{project_name} — Specification.md": f"Specification — {project_name}",
                    f"{project_name} — Plan.md": f"Plan — {project_name}",
                    "Registry.md": f"Registry — Not started — {project_name}",
                    result.name: f"Programming Result current — {project_name}",
                    report.name: f"Verification Report current — {project_name}",
                    f"{project_name} — Implementation Request.md": f"Implementation Request — {project_name}",
                    f"{directory} — Working notes v2.1.MARKDOWN": f"Working notes v2.1 — {project_name}",
                    evidence.name: f"Selected evidence — {project_name}",
                }
                self.assertEqual(page.locator("#document option").evaluate_all(
                    "options => Object.fromEntries(options.map(option => [option.value, option.textContent]))"), expected_labels)
                page.locator('.rail[data-stage="plan"]').click()
                expect(page.locator("#assessment")).to_have_text("PASSED")
                plan_name = f"{project_name} — Plan.md"
                expect(page.locator("#document")).to_have_value(plan_name)
                expect(page.locator("#document option:checked")).to_have_text(f"Plan — {project_name}")
                page.set_viewport_size({"width": 320, "height": 568})
                page.get_by_role("button", name="Show document", exact=True).click()
                expect(page.locator("#document")).to_be_visible()
                page.locator("#refresh").click()
                expect(page.locator("#document")).to_have_value(plan_name)
                expect(page.locator("#document option:checked")).to_have_text(f"Plan — {project_name}")
                expect(page.locator("#reader .reader-caption")).to_have_text(f"File: {plan_name}")
                expect(page.locator("#reader")).to_contain_text("The agreed work.")
                page.set_viewport_size({"width": 1280, "height": 720})
                page.locator("#document").select_option(evidence.name)
                expect(page.locator("#reader")).to_contain_text("EXACT_SELECTED_EVIDENCE")
                page.locator("#refresh").click()
                expect(page.locator("#document")).to_have_value(evidence.name)
                expect(page.locator("#document option:checked")).to_have_text(f"Selected evidence — {project_name}")
                self.assertEqual({path.name: path.read_bytes() for path in folder.iterdir() if path.is_file()}, original_files)
                page.locator('.rail[data-stage="build"]').click()
                expect(page.locator("#result-status")).to_have_text("PASSED")
                expect(page.locator("#assessment")).to_have_text("PASSED")
                expect(page.locator("#assessment-note summary")).to_contain_text(report.name)
                expect(page.locator("#reader")).to_contain_text("This verifies the map only")
                expect(page.locator("#project-completion .completion-wide")).to_have_text("REPORTED COMPLETE")
                definition = folder / "Project.md"
                definition.write_text(definition.read_text(encoding="utf-8").replace("Programming: NOT STARTED", "Programming: IN PROGRESS"), encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#project-completion")).to_be_hidden()
                definition.write_text(definition.read_text(encoding="utf-8").replace("Programming: IN PROGRESS", "Programming: NOT STARTED"), encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#project-completion .completion-wide")).to_have_text("REPORTED COMPLETE")

                # A contradictory body never changes a valid YAML verdict.
                report.write_text(passing_report.replace("No material finding remains.", "But the current candidate failed."), encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("PASSED")
                for failed_report in (
                        passing_report.replace("status: PASSED", "status: PASSED today"),
                        passing_report.replace("status: PASSED", "status: PASSED\nstatus: PASSED")):
                    report.write_text(failed_report, encoding="utf-8")
                    page.locator("#refresh").click()
                    expect(page.locator("#assessment")).to_have_text("REPORT ERROR")
                    expect(page.locator("#assessment-note")).to_contain_text("PASSED today" if "today" in failed_report else "Duplicate")
                    expect(page.locator("#project-completion")).to_be_hidden()
                report.write_text("---\nstatus: PASSED\n---\n# Verification Report\n\n## Earlier review\nVerdict: NOT PASSED\n", encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("PASSED")

                failed_report = ("---\nstatus: NOT PASSED\ndisposition: CORRECTION\n---\n# Verification Report\n"
                                 "- R1 — login accepts an empty password.\n"
                                 "- R2 — export omits the summary row.\n")
                correction = ("---\nstatus: PASSED\ndisposition: SETTLED\n---\n# Programming Result\n"
                              "- R1 — FIXED — the empty-password check now rejects login.\n"
                              "- R2 — REJECTED — the approved scope excludes a summary row.\n")
                report.write_text(failed_report, encoding="utf-8")
                result.write_text(correction.replace("- R2 — REJECTED — the approved scope excludes a summary row.\n", ""), encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("NOT PASSED")
                expect(page.locator("#project-completion")).to_be_hidden()
                result.write_text(correction, encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("CORRECTED")
                expect(page.locator("#assessment")).to_have_class("assessment complete")
                expect(page.locator("#result-status")).to_have_class("assessment complete")
                expect(page.locator("#project-completion")).to_be_visible()
                expect(page.locator("#next-step-title")).to_have_text("Correction completed")
                page.reload()
                self.select_project(page, project_id)
                page.locator('.rail[data-stage="build"]').click()
                expect(page.locator("#assessment")).to_have_text("CORRECTED")
                expect(page.locator("#assessment")).to_have_class("assessment complete")
                expect(page.locator("#project-completion")).to_be_visible()
                page.locator("#assessment").click()
                expect(page.locator("#reader")).to_contain_text("status: NOT PASSED")
                self.assertEqual(report.read_text(encoding="utf-8"), failed_report)
                report.write_text(failed_report.replace("login accepts", "login still accepts"), encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("NOT PASSED")
                expect(page.locator("#project-completion")).to_be_hidden()
                report.write_text(passing_report, encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("PASSED")
                page.evaluate("() => { window.clipboardText = ''; navigator.clipboard.writeText = text => { window.clipboardText = text; return Promise.resolve(); }; }")

                self.choose_primary(page, "Codex")
                page.locator("#review-step").evaluate("element => element.open = true")
                page.locator("#verifier-choice .role-model-choice").select_option(compact_value("claude"))
                page.evaluate("path => material().push({path, name: 'Selected evidence.txt'})", str(evidence))
                deliveries = []

                def deliver(route):
                    body = route.request.post_data_json
                    if body.get("action") == "copy":
                        deliveries.append(body)
                        route.fallback()  # A copy runs on the real server and saves the file.
                        return
                    deliveries.append(body)
                    route.fulfill(json={"turn": f"fake-{len(deliveries)}", "operation": {"turn": f"fake-{len(deliveries)}", "state": "finished", "stage": "verification" if body["step"] == "verification" else "programming", "elapsed_seconds": 0}, "images": []})
                page.route("**/api/deliver", deliver)
                page.evaluate("() => stopPolling()")
                for action, button in (("verify", "#review"), ("correct", "#transition")):
                    if action == "correct":
                        page.locator("#message").fill("Fix the login defect first.")
                        page.locator("#next-step").evaluate("element => element.open = true")
                    else:
                        page.locator("#review-step").evaluate("element => element.open = true")
                    page.locator(button).click()
                    expect(page.locator("#build-action-dialog")).to_be_visible()
                    expect(page.locator("#build-action-send")).to_have_text("Send to Claude Code" if action == "verify" else "Send to Codex")
                    page.locator("#build-action-copy").click()
                    expect(page.locator("#build-action-dialog")).not_to_be_visible()
                    expect(page.locator("#implementation-warning")).to_be_hidden()
                    try:
                        expect(page.locator("#status-bar")).to_contain_text("copied and saved", timeout=5000)
                    except AssertionError:
                        raise AssertionError(f"copy status: {page.locator('#status-bar').inner_text()[:400]} / handoff exists: {(folder / 'Handoff.md').exists()}") from None
                    saved = (folder / "Handoff.md").read_text(encoding="utf-8")
                    self.assertIn("EXACT_SELECTED_EVIDENCE", saved)
                    self.assertEqual(page.evaluate("() => window.clipboardText"), saved)
                    if action == "verify":
                        self.assertIn("selected Claude Code as the independent verifier", saved)
                    else:
                        self.assertIn("Stop there.", saved)
                        self.assertIn("Do not run or commission a new Ora Verification", saved)
                        self.assertIn("Fix the login defect first.", saved)
                    expect(page.locator("#message")).to_have_value("")
                    page.locator(button).click()
                    with page.expect_response("**/api/deliver"):
                        page.locator("#build-action-send").click()
                    expect(page.locator("#build-action-dialog")).not_to_be_visible()
                    page.wait_for_function("turn => lastOperation?.turn === turn", arg=f"fake-{len(deliveries)}")
                    expect(page.locator("#status-bar")).to_contain_text("Verification · Finished" if action == "verify" else "Implementation · Finished")
                self.assertEqual([item["step"] for item in deliveries],
                                 ["verification", "verification", "correction", "correction"])
                self.assertEqual([item["action"] for item in deliveries], ["copy", "send", "copy", "send"])
                self.assertEqual(deliveries[0]["files"], [str(evidence)])
                self.assertIn("Stop there.", (folder / "Handoff.md").read_text(encoding="utf-8"))
                self.assertEqual([item["tool"] for item in deliveries], ["claude", "claude", "codex", "codex"])
            finally:
                browser.close()

    def test_project_picker_and_details(self):
        first = self.request("/api/create", {"directory": "One", "name": "One", "description": "Old description", "goals": "Old outcome"})[1]["id"]
        with self.browser_session() as browser:
            try:
                page = browser.new_page()
                page.goto(self.server.url)
                self.select_project(page, first)
                expect(page.locator("#project")).to_have_value(first)
                second = self.request("/api/create", {"directory": "Two", "name": "Two", "description": "", "goals": ""})[1]["id"]
                page.locator("#project").click()
                expect(page.locator(f'#project option[value="{second}"]')).to_have_count(1)
                expect(page.locator("#project")).to_have_value(first)
                scanned = threading.Event()

                def fail_scan():
                    scanned.set()
                    raise Exception("scan failed")

                with mock.patch.object(self.server.store, "rescan", side_effect=fail_scan):
                    page.locator("#project").click()
                    self.assertTrue(scanned.wait(5), "the picker click did not trigger a rescan")
                expect(page.locator("#status-bar")).to_contain_text("may be out of date")
                expect(page.locator(f'#project option[value="{second}"]')).to_have_count(1)
                expect(page.locator("#project")).to_have_value(first)
                page.locator("#project-card").click()
                expect(page.locator("#editor")).to_be_visible()
                expect(page.locator("#edit-name")).to_have_value("One")
                expect(page.locator("#edit-description")).to_have_value("Old description")
                expect(page.locator("#edit-goals")).to_have_value("Old outcome")
                code = self.home / "code-folder"
                code.mkdir()
                page.locator("#edit-code-browse").click()
                page.locator("#folder-path").fill(str(code))
                page.locator("#folder-go").click()
                page.locator("#folder-select").click()
                page.locator("#edit-name").fill("Renamed")
                page.locator("#edit-parent").fill("Parent lineage")
                page.locator("#edit-description").fill("A much fuller description.\nWith a second line.")
                page.locator("#edit-goals").fill("A fuller desired outcome.")
                page.locator("#edit-save").click()
                expect(page.locator("#editor")).to_be_hidden()
                saved = self.home / "One" / "Project.md"
                saved_text = saved.read_text(encoding="utf-8")
                for expected in ("Name: Renamed", "Parent: Parent lineage", "A much fuller description.",
                                 "A fuller desired outcome.", f"Code: {code}"):
                    self.assertIn(expected, saved_text)
                expect(page.locator("#status-bar")).to_contain_text("Project.md saved")
                expect(page.locator("#project")).to_have_value(first)
            finally:
                browser.close()

    def test_handoffs_reviews_verdicts_and_approve_plan(self):
        from ora_vibe_coder.status import review_basis
        project_id = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
        root = self.home / "One"
        specification = root / "Specification.md"
        plan = root / "Plan.md"
        note = root / "Outside note.md"
        note.write_text("Outside context for the Plan.\n", encoding="utf-8")
        def ready(peer, **kwargs):
            return {"peer": peer, "ready": True, "work": "supported", "authentication": "confirmed", "warnings": []}

        with mock.patch("ora_vibe_coder.conversation.bridge_check", side_effect=ready), \
                mock.patch("ora_vibe_coder.server.markup_installed", return_value=False) as markup, \
                mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), \
                mock.patch("ora_vibe_coder.server.model_inventory", return_value={"models": []}), \
                mock.patch("ora_vibe_coder.conversation.start_aux", side_effect=ValueError("comparison unavailable in this fixture")) as auxiliary, self.browser_session() as browser:
            context = browser.new_context(permissions=["clipboard-read", "clipboard-write"])
            try:
                page = context.new_page()
                page.goto(self.server.url)
                page.evaluate("() => { window.clipboardText = ''; navigator.clipboard.writeText = text => { window.clipboardText = text; return Promise.resolve(); }; }")
                self.select_project(page, project_id)
                page.wait_for_function("() => pollTimer !== null && conversationLoaded")
                self.choose_primary(page, "Codex")
                page.wait_for_function("() => readinessState.peers?.some(peer => peer.peer === 'codex')")
                expect(page.locator("#capture")).to_be_hidden()  # No markup tool on this machine.
                markup.return_value = True
                page.evaluate("refreshReadiness(true)")
                expect(page.locator("#capture")).to_be_visible()
                page.locator("#review-step").evaluate("element => element.open = true")
                self.assertEqual(page.evaluate("chosenReviewerTool()"), "codex")
                page.locator("#document-review-choice .role-model-choice").select_option(compact_value("codex"))
                self.choose_primary(page, "Claude Code")
                self.assertEqual(page.evaluate("chosenReviewerTool()"), "codex")
                page.locator("#document-review-choice .role-model-choice").select_option(compact_value("claude"))
                self.choose_primary(page, "Codex")
                self.assertEqual(page.evaluate("chosenReviewerTool()"), "claude")

                expect(page.locator("#assessment")).to_have_text("NOT STARTED")
                specification.write_text("# One — Specification\n\nRequirements: Preserve all records.\n", encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("NOT REVIEWED")

                page.locator("#next-step").evaluate("element => element.open = true")
                page.locator("#message").fill("Plan around the storage layer.")
                page.evaluate("path => messageFilesFor(currentId, 'specification').push({path, name: 'Outside note.md'})", str(note))
                sends = []

                def deliver(route):
                    body = route.request.post_data_json
                    sends.append(body)
                    if body.get("action") == "copy":
                        route.fallback()  # A copy runs on the real server and saves the file.
                        return
                    route.fulfill(json={"turn": f"turn-{len(sends)}", "operation": {"turn": f"turn-{len(sends)}", "state": "finished", "elapsed_seconds": 0}, "images": [], "path": str(root / "Handoff.md"), "text": "Synthetic prepared request"})
                page.route("**/api/deliver", deliver)
                page.locator("#transition").click()
                expect(page.locator("#message")).to_have_value("")
                expect(page.locator("#prepared-path")).to_have_value(str(root / "Handoff.md"))
                expect(page.locator("#saved-request")).to_be_visible()
                self.assertEqual(sends[0]["step"], "create-plan")
                self.assertEqual(sends[0]["text"], "Plan around the storage layer.")
                self.assertEqual(sends[0]["files"], [str(note)])
                page.route("**/api/deliver", lambda route: route.fulfill(status=500, content_type="application/json", body='{"error":"save failed"}'))
                page.locator("#message").fill("Second attempt text.")
                page.locator("#transition").click()
                expect(page.locator("#status-bar")).to_contain_text("save failed")
                expect(page.locator("#message")).to_have_value("Second attempt text.")
                page.unroute("**/api/deliver")
                page.route("**/api/deliver", deliver)

                page.evaluate("() => attachments.push({name: 'shot.png', data: 'aGk=', url: 'blob:x'})")
                with page.expect_response(lambda response: "/api/deliver" in response.url) as copied_response:
                    page.locator("#copy-request").click()
                self.assertEqual(copied_response.value.status, 200, copied_response.value.text())
                expect(page.locator("#prepared-status")).to_contain_text("copied and saved")
                expect(page.locator("#prepared-status")).to_contain_text("Pictures are not carried by a copy: shot.png")
                expect(page.locator("#message")).to_have_value("")
                handoff = (root / "Handoff.md").read_text(encoding="utf-8")
                self.assertIn("Second attempt text.", handoff)
                self.assertIn("Pictures not carried by this request: shot.png.", handoff)
                self.assertNotIn("Outside context for the Plan.", handoff)
                self.assertEqual(page.evaluate("() => window.clipboardText"), handoff)
                page.evaluate("() => { stopPolling(); updateOperation({turn: 'ended-copy', stage: 'planning', state: 'finished', elapsed_seconds: 2}); }")
                changed_handoff = handoff + "\nAn external saved change.\n"
                (root / "Handoff.md").write_text(changed_handoff, encoding="utf-8")
                page.locator("#copy").click()
                expect(page.locator("#status-bar")).to_contain_text("The saved request changed")
                expect(page.locator("#status-bar")).to_contain_text("Review the current saved text, then use Copy again. Nothing was overwritten.")
                expect(page.locator("#status-bar")).to_contain_text("Plan · Finished · 0:02")
                self.assertEqual((root / "Handoff.md").read_text(encoding="utf-8"), changed_handoff)
                page.evaluate("() => updateOperation(null)")
                expect(page.locator("#status-bar")).to_contain_text("Review the current saved text, then use Copy again. Nothing was overwritten.")
                page.evaluate("() => startPolling()")
                self.assertIn("status: APPROVED", specification.read_text())
                self.assertNotIn("review: PASSED", specification.read_text())
                specification.write_text(specification.read_text().replace("Preserve all records.", "Retain selected records."))
                page.locator("#refresh").click()
                expect(page.locator("#assessment-note")).to_contain_text("The text changed")
                auxiliary.assert_not_called()

                reviewed = "---\nreview: PASSED\n---\n# One — Specification\n\n## Description\n\nBehavior.\n\n## Current review\n\nStage: Specification\nBasis: {basis}\nBasis format: content-v2\n"
                specification.write_text(reviewed.replace("{basis}", review_basis(reviewed)), encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("PASSED")
                specification.write_text(reviewed.replace("review: PASSED", "review: NOT PASSED").replace("{basis}", review_basis(reviewed)).replace("Behavior.", "Behavior, changed."), encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("NOT PASSED")
                expect(page.locator("#approve-plan")).to_be_enabled()
                specification.write_text("---\nstatus: DRAFT\nreview: INCOMPLETE\n---\n# One — Specification\n\nRequirements: Preserve all records.\n", encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("REVIEW INCOMPLETE")
                off_list = reviewed.replace("review: PASSED", "review: PASSED and NOT PASSED")
                specification.write_text(off_list, encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("REPORT ERROR")
                self.assertIn("review", (page.locator("#assessment").get_attribute("title") or "").lower())

                plan.write_text("---\nstatus: AWAITING APPROVAL\nreview: INCOMPLETE\n---\n# One — Plan\n\n## Approach\n\nSteps.\n\n## Current review\n\nStage: Plan\nBasis: {basis}\nBasis format: content-v2\n", encoding="utf-8")
                plan_text = plan.read_text(encoding="utf-8").replace("{basis}", review_basis(plan.read_text(encoding="utf-8")))
                plan.write_text(plan_text, encoding="utf-8")
                page.locator(".rail[data-stage=plan]").click()
                page.locator("#refresh").click()
                expect(page.locator("#saved-request")).to_be_hidden()
                expect(page.locator("#copy-request")).to_have_text("Copy request for any AI")
                expect(page.locator("#assessment")).to_have_text("REVIEW INCOMPLETE")
                expect(page.locator("#approve-plan")).to_be_disabled()  # Greyed until the review is PASSED.
                completed = plan_text.replace("review: INCOMPLETE", "review: PASSED")
                plan.write_text(completed, encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#approve-plan")).to_be_enabled()
                expect(page.locator("#assessment")).to_have_text("PASSED")
                with mock.patch("ora_vibe_coder.project.atomic_write", side_effect=OSError("disk full")):
                    page.locator("#approve-plan").click()
                    expect(page.locator("#status-bar"), "the failed save reports and keeps the prior file").to_contain_text("disk full")
                self.assertIn("status: AWAITING APPROVAL", plan.read_text(encoding="utf-8"))
                page.locator("#approve-plan").click()
                expect(page.locator("#status-bar")).to_contain_text("status: APPROVED saved")
                saved_plan = plan.read_text(encoding="utf-8")
                self.assertIn("status: APPROVED", saved_plan)
                self.assertIn("## Approach\n\nSteps.", saved_plan)
                self.assertIn("Stage: Plan", saved_plan)
                expect(page.locator("#approve-plan")).to_be_disabled()
                expect(page.locator("#assessment")).to_have_text("PASSED")
                expect(page.locator("#reader")).to_contain_text("status: APPROVED")

                page.locator("#next-step").evaluate("element => element.open = true")
                page.locator("#implementation-choice .role-model-choice").select_option(compact_value("zcode"))
                expect(page.locator("#transition")).to_have_text("Send to ZCode")
                page.locator("#message").fill("Implement with the receiving AI's own tools.")
                page.evaluate("path => messageFilesFor(currentId, 'plan').push({path, name: 'Outside note.md'})", str(note))
                page.locator("#copy-request").click()
                page.locator("#implementation-proceed").click()
                expect(page.locator("#status-bar")).to_contain_text("copied and saved")
                expect(page.locator("#saved-request")).to_be_hidden()
                implementation_request = self.server.store.projects[project_id].packet_path("implement-plan").read_text(encoding="utf-8")
                self.assertEqual(page.evaluate("() => window.clipboardText"), implementation_request)
                for content in ("This assignment is for you, the AI receiving this request.",
                                "Implement with the receiving AI's own tools.", "Outside context for the Plan.",
                                specification.read_text(encoding="utf-8"), saved_plan):
                    self.assertTrue(content in implementation_request, "The copied request must preserve its instruction and current source material.")
                self.assertNotIn("Selected receiving harness", implementation_request)
                self.assertNotIn("Requested harness choices", implementation_request)
                self.assertEqual(sends[-1]["action"], "copy")
                page.locator(".rail[data-stage=specification]").click()
                page.locator(".rail[data-stage=plan]").click()
                expect(page.locator("#saved-request")).to_be_hidden()
                expect(page.locator("#delivery-note")).not_to_contain_text("Desktop")
                expect(page.locator("#delivery-note")).not_to_contain_text("Terminal")
                page.locator("#message").fill("Send this implementation to the chosen AI.")
                page.locator("#transition").click()
                page.locator("#implementation-proceed").click()
                expect(page.locator("#message")).to_have_value("")
                self.assertEqual((sends[-1]["action"], sends[-1]["tool"]), ("send", "zcode"))
                expect(page.locator("#saved-request")).to_be_hidden()

                page.locator(".rail[data-stage=build]").click()
                expect(page.locator("#assessment")).to_have_text("NOT VERIFIED")
                (root / "One — Programming Result.md").write_text("# Programming Result\n\nSummary: Implemented record export.\n", encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#result-status")).to_have_text("VERDICT MISSING")
                (root / "One — Programming Result.md").write_text("---\nstatus: PASSED\n---\n# Programming Result\n\nDelivered.\n", encoding="utf-8")
                (root / "One — Verification Report.md").write_text("---\nstatus: NOT PASSED\n---\n# Verification Report\n\n- The login check fails.\n", encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("NOT PASSED")
                expect(page.locator("#next-step-title")).to_have_text("Correct the implementation")
                expect(page.locator("#repairs-box")).to_be_visible()
                expect(page.locator("#repairs-box")).to_contain_text("Findings sorting failed")
                expect(page.locator("#repairs-box button", has_text="Retry sorting")).to_be_enabled()
                expect(page.locator("#transition")).to_have_text("Request repairs")
                page.locator("#next-step").evaluate("element => element.open = true")
                page.locator("#transition").click()
                expect(page.locator("#build-action-dialog")).to_be_visible()
                expect(page.locator("#build-action-title")).to_have_text("Correct the implementation")
                page.locator("#build-action-cancel").click()
                expect(page.locator("#build-action-dialog")).not_to_be_visible()

                (root / "One — Verification Report.md").write_text("---\nstatus: INCOMPLETE\n---\n# Verification Report\n\n- A finding and an unfinished check.\n", encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("REVIEW INCOMPLETE")
                expect(page.locator("#next-step-title")).to_have_text("Finish or rerun the verification")
                expect(page.locator("#transition")).to_have_text("Finish verification")
                expect(page.locator("#repairs-box")).to_be_hidden()
                (root / "One — Verification Report.md").write_text("---\nstatus: PASSED\n---\n# Verification Report\n\nAll checks passed.\n", encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("PASSED")
            finally:
                browser.close()

    def test_correction_replies_keep_recipient_and_choices_after_reopen(self):
        from tests.test_conversation import FAKE_BRIDGE, no_change_block
        bridge = self.home / "fake-bridge"
        (bridge / "ora_agent_bridge").mkdir(parents=True)
        (bridge / "ora_agent_bridge" / "__init__.py").write_text('VERSION = "1.7.0"\n')
        (bridge / "ora_agent_bridge" / "__main__.py").write_text(FAKE_BRIDGE)
        reply = self.home / "reply.md"
        reply.write_text("I need your decision.\n\n## Questions for you\n- Which correction should I make next?\n\n" + no_change_block())
        self.server.settings = Settings(self.home / "reply-settings.json")
        defaults = {"implementation": {"tool": "zcode", "model": "build-model", "effort": "low"},
                    "correction": {"tool": "codex", "model": "correction-model", "effort": "high"},
                    "verification": {"tool": "claude", "model": "verify-model", "effort": "low"}}
        self.server.settings.update(role_defaults=defaults, hide_advisory=True)
        first = self.request("/api/create", {"directory": "Replies", "name": "Replies", "description": "", "goals": ""})[1]["id"]
        other = self.request("/api/create", {"directory": "Other", "name": "Other", "description": "", "goals": ""})[1]["id"]
        for role in ("Specification", "Plan"):
            (self.home / "Replies" / f"{role}.md").write_text(f"---\nreview: PASSED\n---\n# {role}\n\nThe approved work.\n")
        inventory = {"models": [{"id": model, "efforts": ["low", "high"]}
                                for model in ("build-model", "correction-model", "verify-model")]}
        ready = lambda peer, **kwargs: {"peer": peer, "ready": True, "work": "supported", "authentication": "confirmed", "warnings": []}
        with mock.patch.object(conversation, "BRIDGE_HOME", bridge), \
                mock.patch.dict(os.environ, {"VIBE_FAKE_REPLY_FILE": str(reply)}), \
                mock.patch.object(conversation, "bridge_check", side_effect=ready), \
                mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), \
                mock.patch("ora_vibe_coder.server.model_inventory", return_value=inventory), \
                mock.patch.object(conversation, "start_turn", wraps=conversation.start_turn) as starts, \
                self.browser_session() as browser:
            page = browser.new_page(reduced_motion="reduce")
            errors = []; page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(self.server.url); self.select_project(page, first)
            page.locator('[data-stage="build"]').click()
            primary = page.locator("#primary-choice .role-model-choice")
            expect(primary).to_have_value(compact_value("zcode", "build-model"))
            page.locator("#next-step").evaluate("element => element.open = true")
            page.locator("#transition").click()
            page.locator("#build-action-send").click()

            def completed(tool, model, effort):
                expect(page.locator("#send")).to_have_text(f"Reply to {hosts.HOSTS[tool][0]}")
                expect(page.locator("#send")).to_be_enabled()
                expect(primary).to_have_value(compact_value(tool, model))
                expect(page.locator("#primary-choice .role-effort")).to_have_value(effort)
                self.assertEqual(starts.call_args.args[2], tool)
                self.assertEqual((starts.call_args.kwargs["model"], starts.call_args.kwargs["effort"]), (model, effort))

            completed("codex", "correction-model", "high")
            expect(page.locator("#questions-box")).to_contain_text("Which correction should I make next?")
            page.locator("#message").fill("Correct the reply routing first.")
            page.locator("#send").click()
            page.wait_for_function("() => conversationTurns.length === 2 && conversationTurns.at(-1).state === 'complete'")
            completed("codex", "correction-model", "high")
            defaults["implementation"]["model"] = "changed-default"
            self.server.settings.update(role_defaults=defaults)
            page.reload()
            completed("codex", "correction-model", "high")
            page.locator("#build-reply-stage").select_option("verification")
            expect(primary).to_have_value(compact_value("claude", "verify-model"))
            expect(page.locator("#questions-box")).to_be_hidden()
            page.locator("#build-reply-stage").select_option("programming")
            expect(page.locator("#send")).to_have_text("Reply to Codex")
            self.select_project(page, other)
            page.locator('[data-stage="build"]').click()
            expect(primary).to_have_value(compact_value("zcode", "changed-default"))
            self.select_project(page, first)
            expect(page.locator("#send")).to_have_text("Reply to Codex")
            # A new implementation still uses its role default, and then owns
            # the following reply. Future-step pickers do not redirect Codex.
            page.locator("#result-step").evaluate("element => element.open = true")
            page.locator("#build-implementation-choice .role-model-choice").select_option(compact_value("zcode", "build-model"))
            expect(page.locator("#send")).to_have_text("Reply to Codex")
            page.locator("#implement-review").click()
            page.wait_for_function("() => conversationTurns.length === 3 && conversationTurns.at(-1).state === 'complete'")
            completed("zcode", "build-model", "")
            primary.select_option(compact_value("codex", "correction-model"))
            page.locator("#primary-choice .role-effort").select_option("high")
            page.locator("#message").fill("Continue with Codex again.")
            page.locator("#send").click()
            page.wait_for_function("() => conversationTurns.length === 4 && conversationTurns.at(-1).state === 'complete'")
            completed("codex", "correction-model", "high")
            self.assertEqual(self.server.settings.read()["role_defaults"], defaults)
            self.assertEqual(errors, [])

    def test_compact_choices_follow_native_defaults_across_stages(self):
        self.server.settings = Settings(self.home / "compact-settings.json")
        defaults = {role: {"tool": "codex", "model": "", "effort": ""}
                    for role in ("specification", "planning", "implementation")}
        self.server.settings.update(role_defaults=defaults, hide_advisory=True)
        project_id = self.request("/api/create", {"directory": "Compact", "name": "Compact", "description": "A compact sample", "goals": "A working sample"})[1]["id"]
        other = self.request("/api/create", {"directory": "Other", "name": "Other", "description": "", "goals": ""})[1]["id"]
        native = {"configured_model": "native-before", "configured_effort": "high"}
        calls, assessments, effective_models = [], [], []
        def inventory(tool):
            return {**(native if tool == "codex" else {}), "models": [
                {"id": "named", "label": "Named model", "efforts": ["low", "high"], "default_effort": "low"},
                {"id": "native-before", "efforts": ["low", "high"]},
                {"id": "native-after", "efforts": ["low", "high"]}]}
        def handle(tool, stage):
            operation = mock.Mock(turn=f"fake-{len(calls) + len(assessments)}", retained_images=[])
            operation.snapshot.return_value = {"turn": operation.turn, "state": "finished", "tool": tool, "stage": stage}
            return operation
        def start(_registry, project, tool, stage, text, images, *args, **kwargs):
            calls.append({"tool": tool, "stage": stage, "text": text, **kwargs})
            effective_models.append(kwargs.get("model") or native["configured_model"])
            if stage == "programming" and "Implement the current Plan" in text:
                (project.root / "Programming Result.md").write_text("# Programming Result\n\nStatus: COMPLETE\n\nFake implementation and separate review completed.\n")
            return handle(tool, stage)
        def assess(_registry, project, tool, stage, reviewer, iterate, **kwargs):
            assessments.append({"tool": tool, "stage": stage, "reviewer": reviewer, **kwargs})
            return handle(tool, stage)
        ready = lambda peer, **kwargs: {"peer": peer, "ready": True, "work": "supported", "authentication": "confirmed", "warnings": []}
        with mock.patch.object(conversation, "bridge_check", side_effect=ready), \
                mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), \
                mock.patch("ora_vibe_coder.server.model_inventory", side_effect=inventory) as inventories, \
                mock.patch.object(conversation, "start_turn", side_effect=start), \
                mock.patch.object(conversation, "start_assessment", side_effect=assess), self.browser_session() as browser:
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 1050}, reduced_motion="reduce")
                errors = []; page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(self.server.url); self.select_project(page, project_id)
                page.wait_for_function("() => pollTimer !== null && lastFiles !== null")
                page.evaluate("() => stopPolling()")
                primary = page.locator("#primary-choice .role-model-choice")
                expect(primary).to_have_value(compact_value("codex"))
                expect(primary.locator("option:checked")).to_contain_text("native-before")
                self.assertEqual(page.locator("#primary-choice select:visible").count(), 2)
                page.locator("#message").fill("Before defaults change")
                page.locator("#send").click()
                page.wait_for_function("() => !document.querySelector('#send').disabled")
                self.assertEqual((calls[-1]["model"], calls[-1]["effort"]), ("", ""))
                self.assertEqual(effective_models[-1], "native-before")
                page.locator("#message").fill("Preserve this draft while metadata changes")
                native.update(configured_model="native-after", configured_effort="low")
                page.evaluate("() => window.dispatchEvent(new Event('focus'))")
                expect(primary.locator("option:checked")).to_contain_text("native-after")
                expect(page.locator("#message")).to_have_value("Preserve this draft while metadata changes")
                expect(primary).to_have_value(compact_value("codex"))
                page.locator("#send").click()
                page.wait_for_function("() => !document.querySelector('#send').disabled")
                self.assertEqual((calls[-1]["model"], calls[-1]["effort"]), ("", ""))
                self.assertEqual(effective_models[-1], "native-after")
                for workspace, role in (("specification", "specification"), ("plan", "planning")):
                    page.locator(f'[data-stage="{workspace}"]').click()
                    primary.select_option(compact_value("codex", "named"))
                    page.locator("#primary-choice .role-effort").select_option("high")
                    page.locator("#review-step").evaluate("element => element.open = true")
                    page.locator("#document-review-choice .role-model-choice").select_option(compact_value("claude", "named"))
                    page.locator("#document-review-choice .role-effort").select_option("low")
                    page.locator("#opinion-toggle").check()
                    expect(page.locator("#peer-choice .role-label")).to_have_text("Second opinion")
                    page.locator("#peer-choice .role-model-choice").select_option(compact_value("codex", "named"))
                    page.locator("#peer-choice .role-effort").select_option("high")
                    page.locator("#review").click()
                    page.wait_for_function("() => !document.querySelector('#review').disabled")
                    self.assertEqual(assessments[-1], {"tool": "claude", "stage": role, "reviewer": "codex", "model": "named", "effort": "low", "reviewer_model": "named", "reviewer_effort": "high"})
                    page.locator("#message").fill(f"Work on {workspace}"); page.locator("#send").click()
                    page.wait_for_function("() => !document.querySelector('#send').disabled")
                    self.assertEqual((calls[-1]["stage"], calls[-1]["model"], calls[-1]["effort"]), (role, "named", "high"))
                page.locator('[data-stage="build"]').click()
                page.locator("#result-step").evaluate("element => element.open = true")
                page.locator("#build-implementation-choice .role-model-choice").select_option(compact_value("codex", "named"))
                page.locator("#build-implementation-choice .role-effort").select_option("high")
                expect(primary).to_have_value(compact_value("codex", "named"))
                loop = page.locator("#loop-review-choice .role-model-choice")
                expect(loop.locator("option:checked")).to_contain_text("Same as implementation")
                expect(page.locator("#loop-review-choice .role-effort option:checked")).to_have_text("Same (high)")
                with page.expect_response("**/api/deliver"):
                    page.locator("#implement-review").click()
                    page.locator("#implementation-proceed").click()
                self.assertIn("separate fresh reviewer choice as Codex, model named (requested), effort high (requested)", calls[-1]["text"])
                self.assertIn("save the one current Programming Result", calls[-1]["text"])
                self.assertTrue((self.home / "Compact" / "Programming Result.md").is_file())
                loop.select_option(compact_value("claude", "named"))
                page.locator("#loop-review-choice .role-effort").select_option("low")
                with page.expect_response("**/api/deliver"):
                    page.locator("#implement-review").click()
                    page.locator("#implementation-proceed").click()
                self.assertIn("separate fresh reviewer choice as Claude Code, model named (requested), effort low (requested)", calls[-1]["text"])
                page.locator("#message").fill("Keep this Build draft")
                page.locator("#result-step").scroll_into_view_if_needed()
                self.assertTrue(page.evaluate("() => document.documentElement.scrollWidth <= innerWidth"))
                page.set_viewport_size({"width": 1440, "height": 1050})
                self.select_project(page, other)
                expect(primary).to_have_value(compact_value("codex"))
                self.select_project(page, project_id)
                expect(page.locator("#message")).to_have_value("Keep this Build draft")
                self.assertGreater(inventories.call_count, 0)
                self.assertEqual(self.server.settings.read()["role_defaults"], defaults)
                self.assertEqual(errors, [])
            finally:
                browser.close()

    def test_saved_role_defaults_restore_and_survive_a_warning_only_save(self):
        settings = Settings(self.home / "role-settings.json")
        self.server.settings = settings
        choices = {"specification": {"tool": "codex", "model": "configured-model", "effort": "high"},
                   "planning": {"tool": "claude", "model": "unavailable-model", "effort": "unavailable-effort"}}
        settings.update(role_defaults=choices)
        project_id = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
        native = {"models": [{"id": "configured-model", "label": "Configured", "efforts": ["low", "high"]}],
                  "configured_model": "configured-model", "configured_effort": "high"}
        def ready(peer, **kwargs):
            return {"peer": peer, "ready": True, "work": "supported", "authentication": "confirmed", "warnings": []}
        with mock.patch.object(conversation, "bridge_check", side_effect=ready), \
                mock.patch("ora_vibe_coder.server.model_inventory", return_value=native), \
                mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), self.browser_session() as browser:
            page = browser.new_page()
            page.goto(self.server.url)
            self.select_project(page, project_id)
            page.wait_for_function("() => pollTimer !== null && lastFiles !== null")
            page.locator("#settings").click()
            planning = page.locator('#settings-roles .role-row[data-role="planning"]')
            expect(planning.locator(".role-model-choice")).to_have_value(compact_value("claude", "unavailable-model"))
            expect(planning.locator(".role-effort")).to_have_value("unavailable-effort")
            page.locator("#settings-hide-advisory").check()
            page.locator("#settings-save").click()
            expect(page.locator("#settings-panel")).to_be_hidden()
            saved = Settings(settings.path).read()
            self.assertEqual({role: saved["role_defaults"][role] for role in choices}, choices)
            self.assertTrue(saved["hide_advisory"])
            page.reload()
            self.select_project(page, project_id)
            page.wait_for_function("() => destinationName === 'Codex'")
            expect(page.locator("#primary-choice .role-model-choice")).to_have_value(compact_value("codex", "configured-model"))
            legacy = dict(saved)
            legacy.pop("hide_advisory")
            legacy["warn_skip_review"] = False
            Path(settings.path).write_text(json.dumps(legacy))
            self.assertTrue(self.request("/api/settings", {})[1]["hide_advisory"])

    def test_run_approval_confirmation(self):
        from base64 import b64decode
        from tests.test_run import FAKE_BRIDGE, report
        bridge = self.home / "fake-bridge"
        (bridge / "ora_agent_bridge").mkdir(parents=True)
        (bridge / "ora_agent_bridge/__init__.py").write_text('VERSION = "1.7.0"\n')
        (bridge / "ora_agent_bridge/__main__.py").write_text(FAKE_BRIDGE)
        scenario = self.home / "scenario"
        scenario.mkdir()
        self.server.settings = Settings(self.home / "settings.json")
        self.server.settings.update(hide_advisory=True, best_guess=True)
        ready = {"ready": True, "work": "supported", "authentication": "confirmed", "warnings": []}
        with mock.patch.object(conversation, "BRIDGE_HOME", bridge), \
                mock.patch.dict(os.environ, {"VIBE_FAKE_SCENARIO_DIR": str(scenario)}), \
                mock.patch.object(conversation, "bridge_check", side_effect=lambda peer, **kwargs: {"peer": peer, **ready}), \
                mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), self.browser_session() as browser:
            try:
                project_id = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
                project = self.server.store.projects[project_id]
                for stage, role in (("specification", "Specification"), ("planning", "Plan")):
                    path = project.root / f"{role}.md"
                    path.write_text(f"---\nstatus: AWAITING APPROVAL\n---\n# {role}\n\nKeep records for 30 days.\n")
                    project.approve_document(stage, path.read_text(), str(path))
                    path.write_text(path.read_text().replace("30 days", "90 days"))
                selected = self.home / "selected.txt"
                selected.write_text("Keep the attached exact detail.\n")
                page = browser.new_page(viewport={"width": 1280, "height": 1000})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(self.server.url)
                self.select_project(page, project_id)
                page.wait_for_function("() => pollTimer !== null && lastFiles !== null")
                page.locator('.rail[data-stage="plan"]').click()
                self.choose_primary(page, "Codex")
                page.wait_for_function("() => !readinessState.checking")
                page.locator("#message").fill("Preserve this exact run brief.")
                page.evaluate("path => { messageFiles().push({path, name: 'selected.txt'}); renderMaterialChosen(); }", str(selected))
                page.locator("#image-input").set_input_files({"name": "sketch.png", "mimeType": "image/png", "buffer": b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jA3sAAAAASUVORK5CYII=")})
                expect(page.locator("#attachment-bar img")).to_have_attribute("alt", "sketch.png")
                notes = set((project.root / ".vibe").glob("*/session/messages/*"))
                page.locator("#run-completion").click()
                expect(page.locator("#run-approval")).to_be_visible()
                expect(page.locator("#run-warning")).to_be_hidden()
                expect(page.locator("#run-approval-explanation")).to_contain_text("Plan may need updating")
                expect(page.locator("#run-approval-documents")).to_contain_text("-Keep records for 30 days.")
                expect(page.locator("#run-approval-documents")).to_contain_text("+Keep records for 90 days.")
                self.assertEqual(page.locator("#run-approval-documents section").count(), 2)
                self.assertEqual(set((project.root / ".vibe").glob("*/session/messages/*")), notes)
                self.assertIsNone(self.server.runs.find(project))
                page.locator("#run-approval-revisit").click()
                expect(page.locator('.rail[data-stage="specification"]')).to_have_attribute("aria-expanded", "true")
                self.assertIsNone(self.server.runs.find(project))
                page.locator('.rail[data-stage="plan"]').click()
                expect(page.locator("#message")).to_have_value("Preserve this exact run brief.")
                expect(page.locator("#message-files")).to_contain_text("selected.txt")
                expect(page.locator("#attachment-bar img")).to_have_attribute("alt", "sketch.png")
                page.locator("#run-completion").click()
                expect(page.locator("#run-approval")).to_be_visible()
                plan = project.root / "Plan.md"
                plan.write_text(plan.read_text().replace("90 days", "120 days"))
                page.locator("#run-approval-proceed").click()
                expect(page.locator("#run-approval-explanation")).to_contain_text("changed while this choice was open")
                expect(page.locator("#run-approval-documents")).to_contain_text("+Keep records for 120 days.")
                self.assertEqual(set((project.root / ".vibe").glob("*/session/messages/*")), notes)
                self.assertIsNone(self.server.runs.find(project))
                result = project.root / "One — Programming Result.md"
                verification = project.root / "One — Verification Report.md"
                (scenario / "0.json").write_text(json.dumps({"writes": {str(result): "# Programming Result\n\nStatus: COMPLETE\n\nDelivered.\n"}}))
                (scenario / "1.json").write_text(json.dumps({"writes": {str(verification): report("PASSED")}}))
                with page.expect_response(lambda response: "/api/run-start" in response.url):
                    page.locator("#run-approval-proceed").click()
                expect(page.locator("#run-approval")).to_be_hidden()
                expect(page.locator("#message")).to_have_value("")
                expect(page.locator("#attachment-bar")).to_be_hidden()
                expect(page.locator("#message-files")).to_be_hidden()
                page.wait_for_function("() => runLast?.state === 'complete'")
                turns = [conversation.read_turn(folder) for folder in conversation.turn_folders(project)]
                work = [turn for turn in turns if turn["purpose"] == conversation.PURPOSE_WORK]
                self.assertEqual([turn["fields"]["Run-Step"] for turn in work], ["build", "verification"])
                for role in ("Specification", "Plan"):
                    self.assertEqual(project._approved_document(role, str(project.root / f"{role}.md"), fresh=True)["text"],
                                     (project.root / f"{role}.md").read_text())
                self.assertEqual(errors, [])
            finally:
                self.server.runs.drain()

    def test_header_stop_run_uses_the_run_stop_operation(self):
        project_id = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
        other_id = self.request("/api/create", {"directory": "Two", "name": "Two", "description": "", "goals": ""})[1]["id"]
        with self.browser_session() as browser:
            try:
                page = browser.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(self.server.url)
                self.select_project(page, project_id)
                page.wait_for_function("() => pollTimer !== null && lastFiles !== null")
                page.evaluate("() => stopPolling()")
                self.choose_primary(page, "Codex")
                page.evaluate("() => { readinessChain += 1; readinessState = {checking: false, peers: [{peer: 'codex', ready: true, work: 'supported', authentication: 'confirmed', warnings: []}]}; renderReadiness(); pendingRunConfig = {hide_advisory: true}; updateOperation({turn: 'ended-run-start', stage: 'programming', state: 'finished', elapsed_seconds: 12}); }")
                active = {"run": "0001-20261017-000000", "state": "running", "step": "build",
                          "entry": "specification", "elapsed_seconds": 264, "activity": "Coding", "config": {}}
                page.evaluate("report => updateRunState(report)", {"active": active})
                expect(page.locator("#status-bar")).to_have_text("Run to Completion · Implementation · Coding · 4:24")
                expect(page.get_by_role("button", name="Stop Action", exact=True)).to_have_count(1)
                expect(page.get_by_role("button", name="Stop Run", exact=True)).to_have_count(0)
                expect(page.locator("#run-completion")).to_be_disabled()
                paused = dict(active, state="paused-failure", reason="Sign in, then Continue.")
                page.evaluate("report => updateRunState(report)", {"active": paused})
                expect(page.locator("#status-bar")).to_have_class("waiting")
                page.route("**/api/run-resume", lambda route: route.fulfill(json={"run": active}))
                page.locator("#waiting-actions").get_by_role("button", name="Continue", exact=True).click()
                expect(page.locator("#status-bar")).to_have_class("active")
                paused["operation"] = {"dispatched": True}
                page.evaluate("report => updateRunState(report)", {"active": paused})
                expect(page.locator("#waiting-actions").get_by_role("button", name="Inspect saved work")).to_be_visible()
                page.locator("#waiting-actions").get_by_role("button", name="Inspect saved work").click()
                expect(page.locator("#conversation")).to_be_visible()
                packet = {"text": "# Paused implementation request\n\nPictures not included: sketch.png.\n",
                          "path": str(self.home / "One" / "One — Implementation Request.md"),
                          "purpose": "implement-plan", "destination": "Codex", "pictures": ["sketch.png"]}
                page.route("**/api/run-copy", lambda route: route.fulfill(json=packet))
                page.evaluate("() => { navigator.clipboard.writeText = () => Promise.reject(new Error('clipboard denied')); }")
                page.locator("#waiting-actions").get_by_role("button", name="Copy request", exact=True).click()
                expect(page.locator("#saved-request")).to_be_visible()
                expect(page.locator("#prepared-path")).to_have_value(packet["path"])
                expect(page.locator("#raw")).to_be_visible()
                expect(page.locator("#raw")).to_have_value(packet["text"])
                expect(page.locator("#delivery-note")).to_contain_text("Clipboard access was unavailable")
                expect(page.locator("#delivery-note")).to_contain_text("sketch.png")
                self.assertEqual(page.evaluate("() => draft().packetPurpose"), "implement-plan")
                self.assertEqual(page.locator("#raw").evaluate("el => el.selectionEnd - el.selectionStart"), len(packet["text"]))
                copied = []
                def copy_saved(route):
                    copied.append(route.request.post_data_json)
                    route.fulfill(json={"text": packet["text"]})
                page.route("**/api/copy", copy_saved)
                page.locator("#copy").click()
                with page.expect_response(lambda response: "/api/copy" in response.url):
                    page.locator("#implementation-proceed").click()
                expect(page.locator("#delivery-note")).to_contain_text("sketch.png")
                self.assertEqual(copied, [{"id": project_id, "displayed": packet["text"], "purpose": "implement-plan"}])
                page.evaluate("report => updateRunState(report)", {"active": paused})
                stopped = []
                def stop_run(route):
                    stopped.append(route.request.post_data_json)
                    route.fulfill(json={"run": {"active": None, "last": dict(active, state="unfinished", stopped=True,
                        reason="Stopped by the user.", steps=[{"turn": "dispatch"}])}})
                page.route("**/api/run-stop", stop_run)
                page.evaluate("op => updateOperation(op)", {"turn": "dispatch", "stage": "programming", "state": "running"})
                page.locator("#stop-action").click()
                self.assertEqual(stopped, [{"id": project_id}])
                expect(page.locator("#status-bar")).to_have_text("Run to Completion · Implementation · Stopped · 4:24")
                expect(page.locator("#status-bar")).not_to_have_class("active")
                expect(page.locator("#stop-action")).to_be_hidden()
                expect(page.locator("#waiting-actions")).to_be_hidden()
                page.locator("#settings").click()
                expect(page.get_by_role("button", name="Quit Vibe", exact=True)).to_be_visible()
                expect(page.locator(".footer").get_by_role("button", name="Quit Vibe")).to_have_count(0)
                self.assertEqual(errors, [])
            finally:
                browser.close()

    def test_stop_action_preserves_other_projects(self):
        from tests.test_run import FAKE_BRIDGE
        bridge = self.home / "fake-bridge"
        (bridge / "ora_agent_bridge").mkdir(parents=True)
        (bridge / "ora_agent_bridge" / "__init__.py").write_text("")
        (bridge / "ora_agent_bridge" / "__main__.py").write_text(FAKE_BRIDGE)
        scenario = self.home / "scenario"
        scenario.mkdir()
        first = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
        other = self.request("/api/create", {"directory": "Two", "name": "Two", "description": "", "goals": ""})[1]["id"]
        first_project = self.server.store.projects[first]
        other_project = self.server.store.projects[other]
        partial = first_project.root / "partial.txt"
        other_file = other_project.root / "partial.txt"
        (scenario / "0.json").write_text(json.dumps({"delay": 10, "writes": {str(partial): "Saved partial work"}}))
        (scenario / "1.json").write_text(json.dumps({"delay": 10, "writes": {str(other_file): "Other saved work"}}))
        with mock.patch.object(conversation, "BRIDGE_HOME", bridge), mock.patch.dict(os.environ, {"VIBE_FAKE_SCENARIO_DIR": str(scenario)}):
            selected = conversation.start_turn(self.server.conversation, first_project, "codex", "specification", "First", [])
            self.addCleanup(self.server.conversation.drain)
            
            for _ in range(100):
                if partial.exists(): break
                time.sleep(.05)
            self.assertTrue(partial.exists())
            concurrent = conversation.start_turn(self.server.conversation, other_project, "codex", "specification", "Other", [])
            
            for _ in range(100):
                if other_file.exists(): break
                time.sleep(.05)
            self.assertTrue(other_file.exists())
            self.assertTrue(concurrent.live_children())
            code, result, _headers = self.request("/api/action-stop", {"id": first})
            self.assertEqual(code, 200)
            self.assertEqual(result["operation"]["state"], "interrupted")
            self.assertTrue(selected.done.is_set())
            self.assertFalse(selected.live_children())
            self.assertFalse(concurrent.is_cancelled())
            self.assertTrue(concurrent.live_children())
            self.assertEqual(partial.read_text(), "Saved partial work")
            self.assertEqual(other_file.read_text(), "Other saved work")
            self.assertEqual((scenario / "directive.count").read_text(), "2")
            self.server.conversation.drain([concurrent])
            self.assertFalse(concurrent.live_children())

    def test_conversation_reloads_across_a_runs_step_transitions(self):
        project_id = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
        with self.browser_session() as browser:
            try:
                page = browser.new_page()
                page.goto(self.server.url)
                self.select_project(page, project_id)
                page.wait_for_function("() => pollTimer !== null && lastFiles !== null")
                page.evaluate("() => stopPolling()")
                page.locator("#message").fill("An unsent draft that must survive the run.")
                observed = {"step": "specification", "turn": "0002-20261017-000000"}
                conversations = []

                def turn_state(route):
                    route.fulfill(json={
                        "operation": {"project": "p", "tool": "codex", "stage": observed["step"],
                                      "turn": observed["turn"], "state": "running", "phase": "run",
                                      "started": "", "elapsed_seconds": 3, "last_contact_seconds": 1,
                                      "reason": "", "warnings": [], "bridge_diagnostics": [],
                                      "visible_warnings": []},
                        "files": [],
                        "run": {"active": {"run": "0001-20261017-000000", "state": "running",
                                           "step": observed["step"], "entry": "specification", "reason": "",
                                           "questions": [], "observation": "", "no_progress": 0,
                                           "best_verified": False, "verdicts": [], "model": "",
                                           "reported_model": "", "elapsed_seconds": 3,
                                           "last_contact_seconds": 1, "config": {}},
                                "last": None}})

                def conversation(route):
                    conversations.append(1)
                    completed = observed["step"] != "specification"
                    route.fulfill(json={"turns": [{
                        "turn": "0002-20261017-000000", "stage": "specification", "tool": "codex",
                        "purpose": "work", "text": "The run brief: build the small tool.", "images": [],
                        "files": [], "state": "complete" if completed else "open",
                        "reply": "Specification saved from the run's first step." if completed else None,
                        "maintenance": None, "outcome_recorded": completed, "artifact": None,
                        "bridge_diagnostics": [], "questions": []}], "runs": []})

                page.route("**/api/turn-state", turn_state)
                page.route("**/api/conversation", conversation)
                page.evaluate("() => pollTick()")
                expect(page.locator("#conversation")).to_contain_text("The run brief: build the small tool.")
                expect(page.locator("#conversation")).not_to_contain_text("Specification saved from the run's first step.")
                observed.update(step="planning", turn="0003-20261017-000000")
                page.evaluate("() => pollTick()")
                expect(page.locator("#conversation")).to_contain_text("Specification saved from the run's first step.")
                expect(page.locator("#message")).to_have_value("An unsent draft that must survive the run.")
                self.assertEqual(len(conversations), 2)
                page.evaluate("() => pollTick()")
                self.assertEqual(len(conversations), 2)
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

    def test_conversation_opens_at_latest_and_keeps_reading_position(self):
        first = self.request("/api/create", {"directory": "ScrollOne", "name": "Scroll One", "description": "", "goals": ""})[1]["id"]
        second = self.request("/api/create", {"directory": "ScrollTwo", "name": "Scroll Two", "description": "", "goals": ""})[1]["id"]
        turns = [{"turn": f"{index:04}", "tool": "codex", "stage": "planning", "state": "finished",
                  "text": f"Message {index}", "reply": (f"Answer {index}. " * 100)} for index in range(25)]
        def ready(peer, **kwargs):
            return {"peer": peer, "ready": True, "work": "supported", "authentication": "unknown", "warnings": []}
        with mock.patch.object(conversation, "bridge_check", side_effect=ready), self.browser_session() as browser:
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 720}, reduced_motion="reduce")
                errors = []; page.on("pageerror", lambda error: errors.append(str(error)))
                page.route("**/api/conversation", lambda route: route.fulfill(json={"turns": turns, "runs": []}))
                page.goto(self.server.url)
                self.select_project(page, first)
                page.wait_for_function("() => workspace !== '' && conversationLoaded")
                at_bottom = "() => { const e = document.getElementById('conversation'); return e.clientHeight > 0 && e.scrollHeight - e.scrollTop - e.clientHeight < 3; }"
                page.wait_for_function(at_bottom)
                page.evaluate("() => stopPolling()")
                turns.append({"turn": "0025", "tool": "codex", "stage": "planning", "state": "finished",
                              "text": "Newly completed exchange", "reply": "The newest answer. " * 100})
                page.evaluate("() => loadConversation()")
                page.wait_for_function(at_bottom)
                page.evaluate("() => { stopPolling(); document.getElementById('conversation').scrollTop = 180; }")
                top = page.locator("#conversation").evaluate("e => e.scrollTop")
                page.evaluate("() => loadConversation()")
                self.assertEqual(page.locator("#conversation").evaluate("e => e.scrollTop"), top)
                page.locator('[data-stage="plan"]').click()
                page.wait_for_function(at_bottom)
                page.locator("#conversation").evaluate("e => e.scrollTop = 200")
                page.locator('[data-stage="build"]').click()
                page.wait_for_function(at_bottom)
                self.select_project(page, second)
                page.wait_for_function("() => project?.name === 'Scroll Two' && conversationLoaded")
                page.wait_for_function(at_bottom)
                page.set_viewport_size({"width": 420, "height": 720})
                page.get_by_role("button", name="Show document", exact=True).click()
                page.evaluate("() => loadConversation()")
                page.get_by_role("button", name="Show conversation", exact=True).click()
                page.wait_for_function(at_bottom)
                self.assertEqual(errors, [])
            finally:
                browser.close()

    def test_close_warning_only_protects_unsaved_user_content(self):
        project_id = self.request("/api/create", {"directory": "Close", "name": "Close", "description": "", "goals": ""})[1]["id"]
        def ready(peer, **kwargs):
            return {"peer": peer, "ready": True, "work": "supported", "authentication": "unknown", "warnings": []}
        with mock.patch.object(conversation, "bridge_check", side_effect=ready), self.browser_session() as browser:
            try:
                page = browser.new_page()
                errors = []; page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(self.server.url)
                self.select_project(page, project_id)
                page.wait_for_function("() => workspace !== '' && lastFiles !== null")
                page.evaluate("() => stopPolling()")
                def warns():
                    return page.evaluate("() => { const event = new Event('beforeunload', {cancelable:true}); window.dispatchEvent(event); return event.defaultPrevented; }")
                results = {"fresh": warns()}
                self.choose_primary(page, "Codex")
                results["tool_selected"] = warns()
                page.evaluate("() => { draft().packet = 'saved snapshot'; draft().packetDestination = 'Claude Code'; }")
                results["stale_prepared_packet"] = warns()
                page.locator("#message").fill("Do not lose this unsent text.")
                results["unsent_text"] = warns()
                page.locator("#message").fill("")
                page.evaluate("() => attachments.push({name:'unsent.png', data:'data:image/png;base64,AA=='})")
                results["unsent_image"] = warns()
                page.evaluate("() => { attachments = []; messageFiles().push({name:'evidence.txt', path:'/disposable/evidence.txt'}); }")
                results["selected_message_file"] = warns()
                page.evaluate("() => { messageFiles().splice(0); material().push({name:'material.txt', path:'/disposable/material.txt'}); }")
                results["selected_project_material"] = warns()
                page.evaluate("() => material().splice(0)")
                page.locator("#project-card").click()
                page.locator("#edit-description").fill("An unsaved project change.")
                results["unsaved_project_edit"] = warns()
                page.locator("#edit-description").fill("")
                page.locator("#edit-close").click()
                results["cleared"] = warns()
                page.locator("#new").click()
                page.locator("#new-name").fill("Uncreated project")
                results["unsaved_new_project"] = warns()
                self.assertEqual(results, {"fresh": False, "tool_selected": False, "stale_prepared_packet": False,
                    "unsent_text": True, "unsent_image": True, "selected_message_file": True,
                    "selected_project_material": True, "unsaved_project_edit": True, "cleared": False, "unsaved_new_project": True})
                self.assertEqual(errors, [])
            finally:
                browser.close()

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

    def test_composer_default_size_and_divider_keep_message_accessible(self):

        project_id = self.request("/api/create", {"directory": "Composer", "name": "Composer", "description": "", "goals": ""})[1]["id"]
        errors = []
        questions = ["Which code folder should I use for these corrections?"]
        repairs = ["Keep the corrections within the selected stage."]
        with mock.patch("ora_vibe_coder.conversation.bridge_check", side_effect=lambda peer, **kwargs: {
                "peer": peer, "ready": True, "work": "supported", "authentication": "confirmed", "warnings": []}), \
                mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), self.browser_session() as browser:
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 1100}, reduced_motion="reduce")
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(self.server.url)
                self.select_project(page, project_id)
                page.wait_for_function("() => pollTimer !== null && lastFiles !== null")
                page.evaluate("() => stopPolling()")
                self.choose_primary(page, "Codex")
                page.locator("#message").fill("Keep my unsent message through every stage.")

                def content(question_list, repair_list):
                    page.evaluate(r"""data => {
                        conversationTurns = [{turn: '0001', state: 'complete', tool: 'codex', stage: 'specification',
                            text: 'Please review this project.', reply: ('A complete paragraph from the previous conversation.\n\n').repeat(40), questions: data.questions}];
                        reviewRuns = [];
                        project.assessments = {specification: {verdict: 'NOT PASSED', issues: [], applies: 'current',
                            path: 'Specification.md', findings_key: 'composer-fixture'}};
                        renderConversation(); renderQuestions();
                        if (data.repairs.length) renderRepairsResult(sortingTrigger(),
                            {state: 'answered', answer: {ai: data.repairs, user: []}});
                        else { document.getElementById('repairs-box').hidden = true; document.getElementById('repairs-box').replaceChildren(); }
                        document.querySelector('.compose-message').scrollTop = 0;
                    }""", {"questions": question_list, "repairs": repair_list})

                def reachable():
                    page.locator("#message").scroll_into_view_if_needed()
                    expect(page.locator("#message")).to_be_in_viewport()
                    page.locator("#send").scroll_into_view_if_needed()
                    expect(page.locator("#send")).to_be_in_viewport()

                long_questions = [f"Question {index}: " + "Which correction should be made first? " * 4 for index in range(20)]
                long_repairs = [f"Finding {index}: " + "Preserve the complete existing behavior. " * 4 for index in range(20)]
                for width, height in ((1280, 720), (420, 900)):
                    page.set_viewport_size({"width": width, "height": height})
                    content(long_questions, long_repairs)
                    self.assertEqual(page.locator("#questions-box li").all_text_contents(), long_questions)
                    self.assertEqual(page.locator("#repairs-box li").all_text_contents(), long_repairs)
                    reachable()

                page.set_viewport_size({"width": 1440, "height": 1100})
                content(questions, repairs)
                divider = page.locator("#conversation-divider")
                divider.scroll_into_view_if_needed()
                pane = page.locator("#work-step-body").bounding_box()
                conversation = page.locator("#conversation")
                handle = divider.bounding_box()
                page.mouse.move(handle["x"] + handle["width"] / 2, handle["y"] + handle["height"] / 2)
                page.mouse.down()
                page.mouse.move(handle["x"] + handle["width"] / 2, pane["y"] + pane["height"] * .4)
                page.mouse.up()
                expect(divider).to_have_attribute("aria-valuenow", "40")
                dragged = conversation.bounding_box()["height"]
                divider.press("ArrowDown")
                expect(divider).to_have_attribute("aria-valuenow", "45")
                self.assertGreater(conversation.bounding_box()["height"], dragged)
                content(long_questions, long_repairs)
                expect(divider).to_have_attribute("aria-valuenow", "45")

                page.evaluate("() => updateOperation({turn: 'stand-in-active', state: 'running', elapsed_seconds: 1, last_contact_seconds: 0})")
                expect(page.locator("#send")).to_be_disabled()
                page.evaluate("() => updateOperation(null)")
                expect(page.locator("#send")).to_be_enabled()
                self.assertEqual(errors, [])
            finally:
                browser.close()

    def test_check_updates_answers_and_failure_path_use_a_stand_in_lookup(self):

        running = (Path(__file__).resolve().parents[1] / "plugins" / "ora-vibe-coder" / "VERSION").read_text(encoding="utf-8").strip()
        major, minor, patch = (int(part) for part in running.split("."))
        release_page = lambda tag: f"https://github.com/ora-commons/ora-vibe-coder/releases/tag/v{tag}"
        def stand_in(tag):
            return lambda: {"tag_name": f"v{tag}", "html_url": release_page(tag)}
        errors = []
        with mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), self.browser_session() as browser:
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 1100})
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(self.server.url)
                expect(page.locator("#check-updates")).to_be_visible()

                def browser_check(result, name):
                    with page.expect_response("**/api/check-updates") as response:
                        page.locator("#check-updates").click()
                    self.assertEqual(response.value.json(), result)
                    expect(page.locator("#update-status")).to_contain_text(result["label"])
                    expect(page.locator("#status-bar")).to_have_text(result["note"])
                    expect(page.locator("#check-updates")).to_be_enabled()
                    link = page.locator("#update-status a")
                    if result["url"]:
                        expect(link).to_have_count(1)
                        expect(link).to_have_attribute("href", result["url"])
                        expect(link).to_have_text("Release page")
                    else:
                        expect(link).to_have_count(0)
                    self.assertEqual(errors, [])

                for tag, expected in ((f"{major}.{minor + 1}.0", "newer"), (f"{major}.{minor}.{patch}", "same"), ("0.0.1", "ahead")):
                    with self.subTest(answer=expected):
                        self.server.update_lookup = stand_in(tag)
                        status, result, _ = self.request("/api/check-updates", {})
                        self.assertEqual(status, 200)
                        self.assertEqual(result["answer"], expected)
                        if expected == "newer":
                            self.assertIn(f"{major}.{minor + 1}.0", result["label"])
                            self.assertEqual(result["url"], release_page(f"{major}.{minor + 1}.0"))
                            self.assertRegex(result["note"], r"Quit Vibe.*Settings.*Install or update")
                        elif expected == "same":
                            self.assertIn("up to date", result["label"])
                            self.assertIsNone(result["url"])
                        else:
                            self.assertIn("newer than the newest public release", result["label"])
                            self.assertIsNone(result["url"])
                        browser_check(result, expected)
                for name, stand in (("transport-failure", lambda: (_ for _ in ()).throw(OSError("rate limited"))),
                                    ("unreadable-record", lambda: {"message": "API rate limit exceeded"})):
                    with self.subTest(failure=name):
                        self.server.update_lookup = stand
                        status, result, _ = self.request("/api/check-updates", {})
                        self.assertEqual((status, result["answer"]), (200, "cant_tell"))
                        self.assertIn("Couldn't check for updates.", result["label"])
                        self.assertNotIn("up to date", result["label"])
                        self.assertIsNone(result["url"])
                        browser_check(result, name)
                self.server.update_lookup = stand_in(f"{major}.{minor + 1}.0")
                browser_check(self.request("/api/check-updates", {})[1], "repeated-newer")
            finally:
                browser.close()

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
        _, snapshot, _ = self.request("/api/project", {"id": key})
        associated = {entry["path"]: entry for entry in snapshot["reader"]}[str(external)]
        self.assertTrue(associated["needs_selection"])  # The saved brief alone never grants the read.
        _, document, _ = self.request("/api/read-file", {"id": key, "path": str(external)})
        self.assertIsNone(document["text"])
        self.assertTrue(document["needs_selection"])
        self.assertEqual(self.request("/api/approve-reference", {"id": key, "role": "Specification", "path": "/wrong/path"})[0], 400)
        self.assertEqual(self.request("/api/approve-reference", {"id": key, "role": "Specification", "path": str(external)})[0], 200)
        self.assertEqual(self.request("/api/read-file", {"id": key, "path": str(external)})[1]["text"], external.read_text())
        status, body, headers = self.request("/api/stop", {})
        self.assertEqual((status, body), (200, {"stopped": True, "interrupted": 0, "note": ""}))
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())
        self.assertIn("img-src 'self'", headers["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertTrue(external.exists())
        self.server.server_close()

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
        self.assertIn("status: APPROVED", specification_text())  # Preparing records the upstream approval.
        self.assertIn("Programming: NOT STARTED", (root / "Project.md").read_text(encoding="utf-8"))
        self.assertFalse((root / "One — Plan.md").exists())  # Preparing creates no Plan.

        status, body, _ = prepare("review-specification")
        self.assertEqual(status, 200)
        review_packet = (root / "Handoff.md").read_text(encoding="utf-8")
        self.assertIn("Saving the assessment", review_packet)
        for stage in ("specification", "planning", "create-plan", "implement-plan", "programming"):
            self.assertEqual(prepare(stage)[0], 200)
        state = snapshot()
        self.assertEqual(state["assessments"]["planning"]["untouched"], True)
        self.assertFalse(state["assessments"]["planning"]["present"])
        loop_packet = (root / "Handoff.md").read_text(encoding="utf-8")
        self.assertIn("Programming Loop", loop_packet)
        self.assertIn("Repository / code folder", loop_packet)
        self.assertIn("No code folder selected", loop_packet)
        self.assertIn("Programming: NOT STARTED", (root / "Project.md").read_text(encoding="utf-8"))
        self.assertEqual(sorted(path.name for path in root.iterdir()),
                         [".vibe", "Handoff.md", "One — Implementation Request.md", "Plan.md", "Project.md", "Registry.md", "Request.md", "Specification.md"])
        self.assertIn("One — Implementation Request.md", [entry["name"] for entry in snapshot()["reader"]])
        self.assertNotEqual(forward, implementation)

    def test_documents_inventory_startup_and_preferences(self):
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

        self.assertEqual(self.request("/api/open", {"path": str(archived)})[0], 200)
        _, refreshed, _ = self.request("/api/projects", {})
        entry = next(item for item in refreshed["projects"] if item["path"] == str(archived))
        self.assertTrue(entry["archived"])
        self.assertEqual(preferences.read()["last_project"], str(archived))
        self.assertNotEqual(preferences.read().get("projects_home"), str(self.home))
        self.assertEqual(preferences.read()["unrelated"], "keep")
        self.assertEqual(self.request("/api/select-home", {"path": str(self.home)})[0], 400)

        newcomer = self.home / "newcomer"
        newcomer.mkdir()
        (newcomer / "Project.md").write_text("# Project\n\nName: Newcomer\n", encoding="utf-8")
        outside = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, outside)
        os.rename(active, outside / "moved away")
        status, rescanned, _ = self.request("/api/rescan", {})
        self.assertEqual(status, 200)
        self.assertEqual([entry["label"] for entry in rescanned["projects"]], ["Archived", "Newcomer"])

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
        shared = user / "Applications"
        from ora_vibe_coder import installer
        selected = ("codex", "claude", "zcode", "hermes", "qwen", "minimax")
        credentials = user / ".claude" / "settings.json"
        credentials.parent.mkdir(parents=True)
        credentials.write_text('{"unrelated":"preserve this fake setting"}')
        project = user / "Projects" / "Keep"
        project.mkdir(parents=True)
        (project / "Handoff.md").write_text("previous recoverable handoff")
        # A synthetic markup component: one ad hoc-signed bundle zipped like
        # the real release archive, with the pin's checksum pointed at it.
        import hashlib
        import subprocess
        pin = installer.loop_integrity.SCREEN_MARKUP_AUTHORITY
        markup_component = release / pin["vendored_path"]
        markup_component.mkdir(parents=True)
        with tempfile.TemporaryDirectory(dir=self.home) as build:
            staged_app = Path(build) / "Ora Screen Markup.app"
            (staged_app / "Contents/MacOS").mkdir(parents=True)
            executable = staged_app / "Contents/MacOS/Ora Screen Markup"
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
            (staged_app / "Contents/Info.plist").write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>'
                '<key>CFBundleShortVersionString</key><string>0.1.0</string></dict></plist>\n')
            subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(staged_app)],
                           check=True, capture_output=True)
            subprocess.run(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                            str(staged_app), str(markup_component / pin["archive_name"])],
                           check=True, capture_output=True)
        markup_pin = mock.patch.object(
            installer.loop_integrity, "SCREEN_MARKUP_AUTHORITY",
            dict(pin, archive_sha256=hashlib.sha256(
                (markup_component / pin["archive_name"]).read_bytes()).hexdigest()))
        markup_pin.start()
        self.addCleanup(markup_pin.stop)
        result = install(source=release, home=user, hosts=selected, platform="darwin", applications=shared)
        app = Path(result["app"])
        launcher = Path(result["launcher"])
        for host in selected:
            directory = ".minimax" if host == "minimax" else f".{host}"
            entry = user / directory / "skills" / "ora-programming"
            self.assertIn(f"adapters/{host}.md", (entry / "SKILL.md").read_text())
            self.assertTrue((user / directory / "skills/ora-programming-loop/SKILL.md").is_file())
        self.assertEqual(launcher, shared / "Ora Vibe Coder.app")
        record = installer.identity(launcher, installer.LAUNCHER_IDENTITY)
        self.assertEqual(record["version"], result["version"])
        self.assertEqual(json.loads((app / "ora-vibe-install.json").read_text())["python"], sys.executable)
        link = user / "Desktop" / "Ora Vibe Coder"
        self.assertTrue(link.is_symlink() and os.readlink(link) == str(launcher))
        markup_app = shared / "Ora Screen Markup.app"
        self.assertTrue((markup_app / "Contents/Info.plist").is_file())
        boost = Path(result["boost"])
        for name in installer.BOOST_ENTRIES:
            self.assertTrue((boost / name).stat().st_mode & 0o111)
        unknown = app / "personal note.txt"
        unknown.write_text("keep me")
        before = (app / "ora_vibe_coder/server.py").read_bytes()
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
                install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)
        self.assertEqual((app / "ora_vibe_coder/server.py").read_bytes(), before)
        self.assertEqual(unknown.read_text(), "keep me")
        self.assertFalse(list(user.rglob(".ora-vibe-install-*")))
        (release / "ora_vibe_coder/server.py").write_text("BOUNDARY = 'replacement application'\n")
        install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)
        owned = app / "ora_vibe_coder/server.py"
        installed_bytes = owned.read_bytes()
        owned.write_text("user edit")
        with self.assertRaisesRegex(ValueError, "changed or are missing"):
            install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)
        with self.assertRaisesRegex(ValueError, "changed or are missing"):
            remove(source=release, home=user, hosts=selected, platform="darwin", applications=shared)
        self.assertTrue((app / "ora-vibe-install.json").is_file())
        owned.write_bytes(installed_bytes)
        removed = remove(source=release, home=user, hosts=selected, platform="darwin", applications=shared)
        self.assertIn(str(unknown), removed["retained"])
        for host in selected:
            directory = ".minimax" if host == "minimax" else f".{host}"
            self.assertFalse((user / directory / "skills/ora-programming-loop").exists())
            self.assertFalse((user / directory / "skills/ora-programming").exists())
        self.assertEqual(unknown.read_text(), "keep me")
        self.assertEqual((project / "Handoff.md").read_text(), "previous recoverable handoff")
        self.assertIn("preserve", credentials.read_text())
        self.assertTrue(markup_app.is_dir())  # Removal leaves the markup app in place.
        self.assertIn(".cmd", next(iter(launcher_files(app, "win32")))); self.assertIn(".desktop", next(iter(launcher_files(app, "linux"))))
        # An unsupported Mac skips the markup app silently; a differing archive
        # refuses installation naming Ora Screen Markup and the remedy; a user
        # who already keeps a personal copy in their own Applications folder
        # gets no second copy in the shared one.
        unsupported = self.home / "unsupported mac user"
        unsupported_shared = unsupported / "Applications"
        with mock.patch.object(installer, "screen_markup_supported", return_value=False):
            install(source=release, home=unsupported, hosts=(), platform="darwin", applications=unsupported_shared)
        self.assertTrue((unsupported_shared / "Ora Vibe Coder.app").is_dir())
        self.assertFalse((unsupported_shared / "Ora Screen Markup.app").exists())
        diverged = self.home / "diverged archive user"
        diverged_shared = diverged / "Applications"
        with mock.patch.object(installer.loop_integrity, "SCREEN_MARKUP_AUTHORITY",
                               dict(pin, archive_sha256="f" * 64)):
            with self.assertRaisesRegex(ValueError, r"Ora Screen Markup.*Download a fresh Ora Vibe Coder and run setup again"):
                install(source=release, home=diverged, hosts=(), platform="darwin", applications=diverged_shared)
        self.assertFalse((diverged_shared / "Ora Vibe Coder.app").exists())
        self.assertFalse((diverged_shared / "Ora Screen Markup.app").exists())
        personal = self.home / "personal markup user"
        personal_shared = self.home / "personal markup shared"
        (personal / "Applications" / "Ora Screen Markup.app").mkdir(parents=True)
        install(source=release, home=personal, hosts=(), platform="darwin", applications=personal_shared)
        self.assertTrue((personal_shared / "Ora Vibe Coder.app").is_dir())
        self.assertFalse((personal_shared / "Ora Screen Markup.app").exists())

        class WindowsName:
            name = "nt"

            def __getattr__(self, attribute):
                return getattr(os, attribute)

        desktop_link = user / "Desktop" / "Ora Vibe Coder.lnk"

        def fake_windows_shell(command, **kwargs):
            desktop_link.write_bytes(b"faked shortcut v1")
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(installer.subprocess, "run", side_effect=fake_windows_shell):
            with mock.patch.object(installer, "os", WindowsName()):
                win_result = install(source=release, home=user, hosts=(), platform="win32")
        win_app = Path(win_result["app"])
        self.assertTrue((user / "Desktop" / "Ora Vibe Coder" / "Ora Vibe Coder.cmd").is_file())

        with mock.patch.object(installer, "os", WindowsName()):
            remove(source=release, home=user, hosts=(), platform="win32")
        self.assertFalse(desktop_link.exists())
        self.assertFalse(win_app.exists())
        self.assertFalse((user / "Desktop" / "Ora Vibe Coder").exists())

    def test_setup_refuses_to_replace_a_newer_app_or_loop(self):
        from ora_vibe_coder import installer
        user = self.home / "downgrade guard user"
        release = self.synthetic_release()
        shared = user / "Applications"
        install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)
        app = Path(installer.install_location(user, "darwin"))
        identity = app / "ora-vibe-install.json"
        original = json.loads(identity.read_text(encoding="utf-8"))
        before = {str(path): path.read_bytes() for path in user.rglob("*") if path.is_file()}
        newer = dict(original, version="9.9.9")
        identity.write_text(json.dumps(newer, indent=2) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError,
                                    r"Vibe application.*records version 9\.9\.9.*Removing Ora Vibe Coder first"):
            install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)
        after = {str(path): path.read_bytes() for path in user.rglob("*") if path.is_file()}
        self.assertEqual({k: v for k, v in after.items() if not k.endswith(identity.name)},
                         {k: v for k, v in before.items() if not k.endswith(identity.name)})
        self.assertFalse(list(user.rglob(".ora-vibe-install-*")))

        identity.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")

        loop_source = user / ".codex" / "skills" / "ora-programming-loop" / "SOURCE.json"
        marker = json.loads(loop_source.read_text(encoding="utf-8"))
        original_marker = dict(marker)
        marker["version"] = "9.9.9"
        loop_source.write_text(json.dumps(marker), encoding="utf-8")
        loop_guard_before = {str(path): path.read_bytes() for path in user.rglob("*") if path.is_file()}
        with self.assertRaisesRegex(ValueError,
                                    r"Programming Loop install-check did not finish for codex"
                                    r".*version 9\.9\.9 is newer than the supplied version 1\.2\.1"
                                    r".*newer installation was kept and nothing was changed"):
            install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)
        loop_guard_after = {str(path): path.read_bytes() for path in user.rglob("*") if path.is_file()}
        self.assertEqual(loop_guard_after, loop_guard_before)
        self.assertFalse(list(user.rglob(".ora-vibe-install-*")))
        loop_source.write_text(json.dumps(original_marker), encoding="utf-8")

        install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)

        launcher_record = shared / "Ora Vibe Coder.app" / "Contents/Resources/ora-vibe-install.json"
        launcher_original = launcher_record.read_text(encoding="utf-8")
        launcher_record.write_text(json.dumps(
            dict(json.loads(launcher_original), version="9.9.9"), indent=2) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError,
                                    r"Vibe launcher at .*Ora Vibe Coder\.app records version 9\.9\.9"
                                    r".*That launcher is shared with other accounts on this Mac, and removing "
                                    r"Ora Vibe Coder preserves it; install the Ora Vibe Coder release matching "
                                    r"that newer launcher\.") as refused:
            install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)
        self.assertNotIn("Removing Ora Vibe Coder first", str(refused.exception))
        self.assertEqual(json.loads(identity.read_text(encoding="utf-8")), original)
        self.assertFalse(list(user.rglob(".ora-vibe-install-*")))
        launcher_record.write_text(launcher_original, encoding="utf-8")

        from ora_vibe_coder import handoff
        standalone_user = self.home / "standalone loop user"
        standalone = standalone_user / ".codex" / "skills" / "ora-programming-loop"
        for version in ("1.2.1", "9.9.9"):
            standalone.mkdir(parents=True, exist_ok=True)
            (standalone / "SKILL.md").write_text(f"standalone {version} skill body\n")
            (standalone / "SOURCE.json").write_text(json.dumps({
                "component": "ora-programming-loop", "source": "ora-programming-loop",
                "version": version, "source_kind": "public-release",
                "public_release_repository": "https://github.com/ora-commons/ora-programming-loop",
                "files": {"SKILL.md": "0" * 64}}), encoding="utf-8")
            before_standalone = {p.name: p.read_bytes() for p in standalone.rglob("*") if p.is_file()}
            result = install(source=release, home=standalone_user, hosts=("codex",), platform="darwin",
                             applications=standalone_user / "Applications")
            self.assertEqual({p.name: p.read_bytes() for p in standalone.rglob("*") if p.is_file()},
                             before_standalone, version)
            self.assertFalse((standalone_user / ".codex/skills/programming-loop").exists())
            self.assertTrue((standalone_user / ".codex/skills/ora-programming/SKILL.md").is_file())
            self.assertTrue(installer.install_location(standalone_user, "darwin").is_dir())
            self.assertIn("standalone Ora Programming Loop entry", result["note"])
            remove(source=release, home=standalone_user, hosts=("codex",), platform="darwin",
                   applications=standalone_user / "Applications")
            self.assertEqual({p.name: p.read_bytes() for p in standalone.rglob("*") if p.is_file()},
                             before_standalone, version)
            self.assertFalse((standalone_user / ".codex/skills/ora-programming").exists())
            self.assertFalse(installer.install_location(standalone_user, "darwin").exists())
            self.assertFalse(list(standalone_user.rglob(".ora-vibe-install-*")))

    def test_common_launcher_and_desktop_link_are_maintained_and_removal_reports_shared_items(self):
        import plistlib
        from ora_vibe_coder import installer
        user = self.home / "shared launcher user"
        release = self.synthetic_release()
        shared = user / "Applications"
        result = install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)
        launcher = Path(result["launcher"])
        approved_icon = (installer.ROOT / "ora_vibe_coder/static/ora-vibe-coder.icns").read_bytes()

        def assert_launcher_icon():
            plist = plistlib.loads((launcher / "Contents/Info.plist").read_bytes())
            self.assertEqual(plist["CFBundleIconFile"], "applet.icns")
            self.assertNotIn("CFBundleIconName", plist)
            self.assertEqual((launcher / "Contents/Resources/applet.icns").read_bytes(), approved_icon)

        assert_launcher_icon()
        link = user / "Desktop" / "Ora Vibe Coder"
        self.assertTrue(link.is_symlink() and os.readlink(link) == str(launcher))
        link.unlink()
        link.write_text("a personal item")
        (release / "ora_vibe_coder/server.py").write_text("BOUNDARY = 'replacement application'\n")
        second = install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)
        self.assertEqual(second["desktop_link"], "kept an existing personal item")
        self.assertEqual(link.read_text(), "a personal item")
        self.assertFalse(link.is_symlink())
        assert_launcher_icon()
        link.unlink()
        third = install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)
        self.assertEqual(third["desktop_link"], "created")
        self.assertTrue(link.is_symlink() and os.readlink(link) == str(launcher))
        assert_launcher_icon()
        removed = remove(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)
        self.assertFalse(link.exists())
        self.assertFalse(Path(result["app"]).exists())
        self.assertTrue(launcher.is_dir())
        self.assertTrue(any("shared launcher" in note and "was kept" in note for note in removed["notes"]))
        install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)
        assert_launcher_icon()
        self.assertFalse(list(user.rglob(".ora-vibe-install-*")))

    def test_permission_refusal_and_signing_failures_preserve_the_previous_installation(self):
        from ora_vibe_coder import installer
        user = self.home / "permission and signing user"
        release = self.synthetic_release()
        shared = user / "Applications"
        result = install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)
        app = Path(result["app"])
        launcher = Path(result["launcher"])
        previous_launcher = {p.relative_to(launcher): p.read_bytes() for p in launcher.rglob("*") if p.is_file()}
        previous_app = (app / "ora_vibe_coder/server.py").read_bytes()
        locked = user / "Locked Applications"
        locked.mkdir()
        locked.chmod(0o500)
        try:
            with self.assertRaisesRegex(ValueError, r"needs permission to write.*previous installation\s+and your work were preserved"):
                install(source=release, home=user, hosts=("codex",), platform="darwin", applications=locked)
        finally:
            locked.chmod(0o700)
        self.assertEqual((app / "ora_vibe_coder/server.py").read_bytes(), previous_app)
        self.assertFalse(list(locked.iterdir()))
        original_run = installer.subprocess.run

        def failing_codesign(command, **kwargs):
            if command[:1] == ["/usr/bin/codesign"]:
                return mock.Mock(returncode=1, stdout=b"", stderr=b"simulated codesign failure")
            return original_run(command, **kwargs)

        (release / "ora_vibe_coder/server.py").write_text("BOUNDARY = 'unreached replacement'\n")
        with mock.patch.object(installer.subprocess, "run", side_effect=failing_codesign):
            with self.assertRaisesRegex(ValueError, "Signing the Ora Vibe Coder launcher failed.*previous installation was preserved"):
                install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)
        self.assertEqual((app / "ora_vibe_coder/server.py").read_bytes(), previous_app)
        def failing_verify(command, **kwargs):
            if command[:4] == ["/usr/bin/codesign", "--verify", "--deep", "--strict"]:
                return mock.Mock(returncode=1, stdout="", stderr="simulated verification failure")
            return original_run(command, **kwargs)

        with mock.patch.object(installer.subprocess, "run", side_effect=failing_verify):
            with self.assertRaisesRegex(ValueError, "did not pass strict signature verification.*previous installation was preserved"):
                install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)
        self.assertEqual((app / "ora_vibe_coder/server.py").read_bytes(), previous_app)
        self.assertEqual(
            {p.relative_to(launcher): p.read_bytes() for p in launcher.rglob("*") if p.is_file()},
            previous_launcher,
        )
        self.assertFalse(list(user.rglob(".ora-vibe-install-*")))

    def test_offline_boost_runs_from_the_bundled_installation(self):
        from ora_vibe_coder import installer
        import subprocess
        user = self.home / "boost user"
        release = self.synthetic_release()
        shared = user / "Applications"
        result = install(source=release, home=user, hosts=(), platform="darwin", applications=shared)
        boost = Path(result["boost"])
        self.assertTrue((boost.parent / "agent-bridge" / "ora_agent_bridge" / "__main__.py").is_file())
        for name in installer.BOOST_ENTRIES:
            wrapper = boost / name
            self.assertTrue(wrapper.stat().st_mode & 0o111, name)
            self.assertIn(
                'os.environ["AGENT_BRIDGE_HOME"] = str(root.parent / "agent-bridge")',
                wrapper.read_text(encoding="utf-8"),
            )
        completed = subprocess.run(
            [sys.executable, "-c",
             "import json, sys; sys.path.insert(0, sys.argv[1]); import ora_review; "
             "print(json.dumps(ora_review.COMPONENT_FACTS))", str(boost)],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        facts = json.loads(completed.stdout)
        self.assertEqual(facts["component"], "ora-adversarial-review")
        self.assertEqual(facts["version"], "0.6.0")
        self.assertEqual(sorted(facts["analytical_roles"]), ["peer", "primary"])
        helped = subprocess.run([sys.executable, str(boost / "ora-gear-3"), "--help"],
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(helped.returncode, 0, helped.stderr)
        self.assertIn("ora-gear-3", helped.stdout)
        self.assertIn("--turn-instructions-file", helped.stdout)
        blank = self.home / "blank turn instructions.md"
        blank.write_text("   \n", encoding="utf-8")
        refused = subprocess.run(
            [sys.executable, str(boost / "ora-gear-3"),
             "--turn-instructions-file", str(blank)],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(refused.returncode, 1, refused.stderr)
        self.assertIn("The turn-instructions file contains no user words.", refused.stderr)

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
                        self.assertIn(str(operations[0] / "assignment.md"), received[0])
                        self.assertEqual(received[1][-2:], ["--resume", "sess_fake_receipt"])
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
                    return_value=mock.Mock(returncode=0, stdout='{"sessionId":"sess_recover_me"}', stderr="")) as receipt_run, \
                    mock.patch.object(hosts.subprocess, "call", side_effect=lambda argv, **kwargs: calls.append(argv) or 7), \
                    contextlib.redirect_stdout(captured):
                self.assertEqual(hosts.run_operation(operation), 7)
                self.assertNotIn("timeout", receipt_run.call_args.kwargs)

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

    def test_stalled_discovery_keeps_interface_and_readable_projects_available(self):
        self.close()
        projects = self.home / "Projects"
        projects.mkdir()
        unavailable = projects / "Unavailable folder"
        definition = projects / "Unavailable definition"
        readable = projects / "Readable sibling"
        nested = definition / "Nested project"
        for folder in (unavailable, definition, readable, nested):
            folder.mkdir(parents=True, exist_ok=True)
        for folder, name in ((definition, "Definition"), (readable, "Readable"), (nested, "Nested")):
            (folder / "Project.md").write_text(f"# Project\n\nName: {name}\n", encoding="utf-8")
        (projects / ".stall-folder").touch()
        (unavailable / ".stall-folder").touch()
        (definition / ".stall-file").touch()
        settings = Settings(self.home / "settings.json")
        settings.update(projects_dir=str(projects), last_project=str(definition), last_workspace="build")
        owned_readers = []
        original_popen = project_module.subprocess.Popen
        def start_reader(args, **kwargs):
            if args[1:] == ["-m", "ora_vibe_coder.project_discovery"]:
                args = [args[0], "-c", "from tests.test_local_app_boundary import stalled_inventory_reader; stalled_inventory_reader()"]
                process = original_popen(args, **kwargs)
                owned_readers.append(process)
                return process
            return original_popen(args, **kwargs)

        def wait_for(check):
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                value = check()
                if value:
                    return value
                threading.Event().wait(.02)
            self.fail("The expected discovery state did not arrive.")

        def exercise(server, **kwargs):
            self.server = server
            self.thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01})
            self.thread.start()
            try:
                wait_for(lambda: (projects / ".entered-folder").exists())
                self.assertEqual(self.request("/", {}, method="GET")[0], 200)
                self.assertTrue(self.request("/api/projects", {})[1]["scanning"])
                wait_for(lambda: not server.store.report()["scanning"])
                self.assertFalse(server.store.report()["complete"])
                (projects / ".stall-folder").unlink()
                self.request("/api/rescan", {})
                wait_for(lambda: not server.store.report()["scanning"])
                inventory = self.request("/api/projects", {})[1]
                self.assertEqual({entry["name"] for entry in inventory["projects"]}, {"Readable", "Nested"})
                self.assertIn(str(unavailable), " ".join(inventory["notices"]))
                self.assertIn(str(definition / "Project.md"), " ".join(inventory["notices"]))
                with self.browser_session() as browser:
                    page = browser.new_page()
                    page.goto(server.url)
                    expect(page.locator("#project option")).to_have_count(3)
                    page.locator("#open").click()
                    expect(page.locator("#scan-notices")).to_contain_text(str(unavailable))
                    page.locator("#open-close").click()
                    entry = next(item for item in inventory["projects"] if item["name"] == "Readable")
                    self.select_project(page, entry["id"])
                    page.locator("#message").fill("Keep this unsent message")
                    (unavailable / ".stall-folder").unlink()
                    (definition / ".stall-file").unlink()
                    page.locator("#open").click()
                    page.locator("#refresh-projects").click()
                    expect(page.locator("#project option")).to_have_count(4)
                    expect(page.locator("#project")).to_have_value(entry["id"])
                    expect(page.locator("#message")).to_have_value("Keep this unsent message")
                    wait_for(lambda: not server.store.report()["scanning"])
                    self.assertTrue(server.store.report()["complete"])
                self.assertEqual(self.request("/api/stop", {})[0], 200)
                self.thread.join(3)
                server.shutdown_thread.join(3)
                self.assertFalse(self.thread.is_alive())
                self.assertTrue(all(child.poll() is not None for child in owned_readers))
            finally:
                self.close()

        argv = ["vibe", "--no-browser", "--settings", str(settings.path)]
        with mock.patch.object(project_module.subprocess, "Popen", side_effect=start_reader), \
                mock.patch.object(project_module, "DISCOVERY_READ_SECONDS", .75), \
                mock.patch.object(sys, "argv", argv), \
                mock.patch.object(app_entry, "serve", side_effect=exercise):
            app_entry.main()
        self.assertFalse(settings.path.with_name("running.json").exists())
        self.assertTrue(all(child.poll() is not None for child in owned_readers))

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
