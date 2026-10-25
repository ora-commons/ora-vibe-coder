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
        page.locator("#project").select_option(project_id)

    def test_project_header_keeps_selection_and_details_on_one_row(self):
        try:
            from playwright.sync_api import expect, sync_playwright
        except ImportError:
            self.skipTest("Playwright is not installed for the browser check")
        long_name = "A complete project name describing the full planning and implementation journey for a substantial local software workspace"
        long_parent = "Ora → Personal knowledge systems → Software delivery and verification → Long-running collaborative project portfolio"
        description = "The complete project description, including its purpose and a second line.\nNothing is abbreviated here."
        goals = "A full desired outcome with enough detail to read and revise.\nThe result remains visible in this one screen."
        first = self.request("/api/create", {"directory": "One", "name": long_name, "parent": long_parent,
                                             "description": description, "goals": goals})[1]["id"]
        second = self.request("/api/create", {"directory": "Two", "name": "Two", "description": "", "goals": ""})[1]["id"]
        with sync_playwright() as playwright:
            if not Path(playwright.chromium.executable_path).is_file():
                self.skipTest("Playwright's Chromium is not installed for the browser check")
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 720})
                page.goto(self.server.url)
                expect(page.locator("#project")).to_be_visible()
                self.select_project(page, first)
                page.wait_for_function("() => pollTimer !== null && lastFiles !== null")
                expect(page.locator("#project")).to_have_value(first)
                header_height = page.locator("#top").bounding_box()["height"]
                work_y = page.locator("#work-step").bounding_box()["y"]
                expect(page.locator("#message")).to_be_visible()

                for width, height in ((1280, 720), (800, 560), (375, 667), (320, 568)):
                    page.set_viewport_size({"width": width, "height": height})
                    top_height = page.locator("#top").bounding_box()["height"]
                    # Three compact header rows on a wide window, with no
                    # growing banner stack; narrow wrapping is the accepted
                    # best-effort layout Lawrence's checkpoint approved.
                    if width >= 1200:
                        self.assertLess(top_height, 170)
                    main = page.locator(".main-col").bounding_box()
                    row = page.locator(".project-row").bounding_box()
                    selector = page.locator("#project").bounding_box()
                    new = page.locator("#new").bounding_box()
                    opened = page.locator("#open").bounding_box()
                    details = page.locator("#project-card").bounding_box()
                    self.assertGreaterEqual(selector["width"], 55)
                    self.assertLessEqual(row["x"] + row["width"], main["x"] + main["width"])
                    self.assertLessEqual(details["x"] + details["width"], row["x"] + row["width"])
                    # Row 1 keeps New, Open and the picker on one line; Details
                    # sits on the status row beneath them by design.
                    if width >= 1200:
                        self.assertLess(max(abs(selector["y"] - box["y"]) for box in (new, opened)), 4)
                        self.assertGreaterEqual(details["y"], new["y"] + new["height"] - 2)
                    self.assertFalse(page.locator(".project-row").evaluate("element => element.scrollWidth > element.clientWidth"))
                    expect(page.get_by_role("button", name="New project")).to_be_visible()
                    expect(page.get_by_role("button", name="Open existing project")).to_be_visible()
                    step = page.locator(".first-step").bounding_box()
                    controls = [page.locator(target).bounding_box() for target in
                                (".first-step .step-number", "#destination", "#readiness", "#recheck")]
                    if width >= 1200:
                        self.assertLess(max(box["y"] + box["height"] / 2 for box in controls) -
                                        min(box["y"] + box["height"] / 2 for box in controls), 4)
                    self.assertTrue(all(step["x"] <= box["x"] and box["x"] + box["width"] <= step["x"] + step["width"] + 1
                                        for box in controls))
                    self.assertFalse(page.locator(".first-step").evaluate("element => element.scrollWidth > element.clientWidth"))
                    expect(page.get_by_label("Coding tool")).to_be_visible()
                    expect(page.get_by_role("button", name="Recheck readiness")).to_be_enabled()
                    if width == 320:
                        for target in ("new", "open", "project-card"):
                            page.locator(f"#{target}").focus()
                            self.assertEqual(page.evaluate("document.activeElement.id"), target)
                        page.locator("#destination").focus()
                        self.assertEqual(page.evaluate("document.activeElement.id"), "destination")
                        page.locator("#recheck").focus()
                        self.assertEqual(page.evaluate("document.activeElement.id"), "recheck")
                    page.locator("#project-card").click()
                    expect(page.locator("#editor")).to_be_visible()
                    self.assertEqual(page.locator("#editor").evaluate("element => element.scrollTop"), 0)
                    expect(page.locator("#edit-name")).to_have_value(long_name)
                    expect(page.locator("#edit-parent")).to_have_value(long_parent)
                    expect(page.locator("#edit-description")).to_have_value(description)
                    expect(page.locator("#edit-goals")).to_have_value(goals)
                    for field in ("edit-name", "edit-parent", "edit-description", "edit-goals"):
                        dimensions = page.locator(f"#{field}").evaluate(
                            "element => ({height: element.clientHeight, contentHeight: element.scrollHeight, "
                            "width: element.clientWidth, contentWidth: element.scrollWidth})")
                        self.assertLessEqual(dimensions["contentHeight"], dimensions["height"], f"{field} clips vertically at {width}px")
                        self.assertLessEqual(dimensions["contentWidth"], dimensions["width"], f"{field} clips horizontally at {width}px")
                    if width == 1280:
                        self.assertGreater(page.locator("#edit-name").evaluate("element => element.clientHeight"), 50)
                        self.assertGreater(page.locator("#edit-parent").evaluate("element => element.clientHeight"), 50)
                        page.set_viewport_size({"width": 320, "height": 568})
                        for field in ("edit-name", "edit-parent"):
                            page.wait_for_function(
                                f"() => {{ const element = document.getElementById('{field}'); "
                                "return element.scrollHeight <= element.clientHeight && element.scrollWidth <= element.clientWidth; }")
                            self.assertFalse(page.locator(f"#{field}").evaluate(
                                "element => element.scrollHeight > element.clientHeight || element.scrollWidth > element.clientWidth"),
                                f"{field} clips after resizing with details open")
                        page.set_viewport_size({"width": width, "height": height})
                    self.assertFalse(page.locator("#editor").evaluate("element => element.scrollWidth > element.clientWidth"))
                    self.assertFalse(page.evaluate("editDrafts.get(currentId).dirty"))
                    editor = page.locator("#editor").bounding_box()
                    self.assertGreaterEqual(editor["x"], 0)
                    self.assertLessEqual(editor["x"] + editor["width"], width)
                    self.assertLess(abs(page.locator("#top").bounding_box()["height"] - top_height), 1)
                    page.locator("#edit-close").click()
                    expect(page.locator("#status-bar")).to_be_empty()
                    expect(page.locator("#project-unsaved")).to_be_hidden()
                    if width <= 760 or height <= 560:
                        for rail in page.locator(".rail").all():
                            button = rail.bounding_box()
                            label = rail.locator(".rail-label").bounding_box()
                            self.assertGreaterEqual(label["y"], button["y"])
                            self.assertLessEqual(label["y"] + label["height"], button["y"] + button["height"])

                page.set_viewport_size({"width": 1280, "height": 720})
                self.assertLessEqual(abs(page.locator("#top").bounding_box()["height"] - header_height), 1)
                self.assertLessEqual(abs(page.locator("#work-step").bounding_box()["y"] - work_y), 1)
                self.select_project(page, second)
                expect(page.locator("#project")).to_have_value(second)
                page.wait_for_function("() => project?.name === 'Two'")
                self.select_project(page, first)
                expect(page.locator("#project")).to_have_value(first)
                expect(page.locator("#project-name")).to_have_text(long_name)
                page.locator("#new").click()
                expect(page.locator("#create")).to_be_visible()
                page.locator("#create-close").click()
                page.locator("#open").click()
                expect(page.locator("#open-form")).to_be_visible()
                page.locator("#open-close").click()
                page.locator("#project-card").click()
                page.locator("#edit-name").fill(long_name + "\ncontinued")
                expect(page.locator("#edit-name")).to_have_value(long_name + " continued")
                page.locator("#edit-name").fill(long_name)
                page.locator("#edit-parent").focus()
                page.locator("#edit-parent").press("End")
                page.locator("#edit-parent").press("Enter")
                expect(page.locator("#edit-parent")).to_have_value(long_parent)
                page.locator("#edit-description").fill(description + " Draft")
                self.assertTrue(page.evaluate("editDrafts.get(currentId).dirty"))
                expect(page.locator("#project-unsaved")).to_be_visible()
                page.locator("#edit-description").fill(description)
                self.assertFalse(page.evaluate("editDrafts.get(currentId).dirty"))
                expect(page.locator("#project-unsaved")).to_be_hidden()
                page.locator("#edit-description").fill(description + " Draft")
                page.locator("#edit-close").click()
                expect(page.locator("#status-bar")).to_be_empty()
                self.assertTrue(page.evaluate("editDrafts.get(currentId).dirty"))
                page.locator("#project").evaluate("element => element.blur()")
                third = self.request("/api/create", {"directory": "Three", "name": "Three", "description": "", "goals": ""})[1]["id"]
                page.locator("#project").click()
                expect(page.locator(f'#project option[value="{third}"]')).to_have_count(1)
                expect(page.locator("#project")).to_have_value(first)
                page.keyboard.press("Escape")
                page.locator("#project").evaluate("element => element.blur()")
                fourth = self.request("/api/create", {"directory": "Four", "name": "Four", "description": "", "goals": ""})[1]["id"]
                page.locator("#project").focus()
                expect(page.locator(f'#project option[value="{fourth}"]')).to_have_count(1)
                expect(page.locator("#project")).to_have_value(first)
                self.assertEqual(page.evaluate("""() => {
                    const fetchBefore = window.fetch;
                    let rescans = 0;
                    window.fetch = (...args) => {
                        if (args[0] === '/api/rescan') rescans++;
                        return fetchBefore(...args);
                    };
                    try {
                        for (const key of ['ArrowDown', 'ArrowUp'])
                            document.getElementById('project').dispatchEvent(new KeyboardEvent('keydown', {key}));
                        return rescans;
                    } finally { window.fetch = fetchBefore; }
                }"""), 0)
                page.locator("#project-card").click()
                expect(page.locator("#edit-description")).to_have_value(description + " Draft")
                page.locator("#edit-description").fill(description)
                self.assertFalse(page.evaluate("editDrafts.get(currentId).dirty"))
                page.locator("#edit-state").select_option("ARCHIVED")
                page.locator("#edit-save").click()
                expect(page.locator("#editor")).to_be_hidden()
                saved_brief = (self.home / "One" / "Project.md").read_text(encoding="utf-8")
                self.assertIn(f"Name: {long_name}\n", saved_brief)
                self.assertIn(f"Parent: {long_parent}\n", saved_brief)
                expect(page.locator("#project-unsaved")).to_be_hidden()
                expect(page.locator("#project")).to_have_value(first)
                expect(page.locator("#project option:checked")).to_contain_text("Archived")
                self.select_project(page, second)
                expect(page.locator("#project")).to_have_value(second)
                self.assertEqual(page.locator(f'#project option[value="{first}"]').count(), 0)
                loose = self.home / "Loose folder"
                loose.mkdir()
                (loose / "Request.md").write_text("# Request\n\n## Mission\n\nFull mission text from a loose folder.\n", encoding="utf-8")
                page.evaluate("async path => { const result = await api('open', {path}); await chooseProject(result.id); }", str(loose))
                expect(page.locator("#project option:checked")).to_contain_text("Loose folder — Open folder")
                page.locator("#project-card").click()
                expect(page.locator("#overview-sources")).to_contain_text("Full mission text from a loose folder.")
            finally:
                browser.close()

    def test_completed_turn_status(self):
        # The status bar is the one status surface; technical diagnostics that
        # ask nothing of the user sit under More, and anything needing a reply
        # stays in the bar itself.
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
                page = browser.new_page(viewport={"width": 1600, "height": 1000})
                page.goto(self.server.url)
                self.select_project(page, project_id)
                page.wait_for_function("() => pollTimer !== null && lastFiles !== null")
                page.evaluate("() => stopPolling()")
                bar = page.locator("#status-bar")
                appearance = """element => {
                    const style = getComputedStyle(element), box = element.getBoundingClientRect();
                    const row = element.closest('.status-row').getBoundingClientRect();
                    return {background: style.backgroundColor, border: style.borderTopColor,
                            borderWidth: parseFloat(style.borderTopWidth), color: style.color,
                            font: parseFloat(style.fontSize), weight: Number(style.fontWeight),
                            animation: style.animationName, transition: style.transitionDuration,
                            box: [box.x, box.y, box.width, box.height], row: [row.y, row.height]};
                }"""
                # Both themes keep the same box and row while all work and
                # review states receive a steady, more readable highlight.
                for theme, green in [("dark", "rgb(95, 168, 110)"), ("light", "rgb(63, 125, 77)")]:
                    page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
                    page.evaluate("operation => updateOperation(operation)", {
                        "turn": f"idle-{theme}", "state": "finished", "elapsed_seconds": 1})
                    idle = bar.evaluate(appearance)
                    for stage, state in [("specification", "starting"), ("specification", "running"),
                                         ("review-specification", "running"), ("review-plan", "starting")]:
                        page.evaluate("operation => updateOperation(operation)", {
                            "turn": f"active-{stage}", "stage": stage, "state": state,
                            "elapsed_seconds": 5, "last_contact_seconds": 2})
                        active_style = bar.evaluate(appearance)
                        self.assertNotEqual(active_style["background"], idle["background"])
                        self.assertEqual(active_style["border"], green)
                        self.assertGreater(active_style["borderWidth"], idle["borderWidth"])
                        self.assertGreater(active_style["font"], idle["font"])
                        self.assertGreaterEqual(active_style["weight"], 600)
                        self.assertEqual(active_style["color"], idle["color"])
                        self.assertEqual(active_style["box"], idle["box"])
                        self.assertEqual(active_style["row"], idle["row"])
                        self.assertEqual(active_style["animation"], "none")
                        self.assertEqual(active_style["transition"], "0s")
                    # An action receipt cannot hide activity, and an open
                    # Settings panel keeps the same active colors.
                    page.evaluate("() => status('Review running in Codex.')")
                    self.assertEqual(bar.evaluate(appearance), active_style)
                    page.locator("#settings").click()
                    self.assertEqual(bar.evaluate(appearance)["background"], active_style["background"])
                    page.locator("#settings-close").click()
                    page.evaluate("() => lostContact()")
                    expect(bar).to_contain_text("Lost contact with the local server")
                    self.assertEqual(bar.evaluate(appearance)["background"], idle["background"])
                    self.assertNotEqual(bar.evaluate(appearance)["color"], idle["color"])
                    page.evaluate("() => { contactRestored(); updateOperation(lastOperation); }")
                    self.assertEqual(bar.evaluate(appearance), active_style)
                    page.evaluate("() => status('A warning needs attention.', 'warning')")
                    self.assertEqual(bar.evaluate(appearance)["background"], idle["background"])
                    page.evaluate("() => { updateOperation(lastOperation); updateOperation(null); }")
                    self.assertEqual(bar.evaluate(appearance), idle)
                # A narrow window also keeps its existing row and box height.
                page.set_viewport_size({"width": 700, "height": 900})
                narrow_idle = bar.evaluate(appearance)
                page.evaluate("operation => updateOperation(operation)", {
                    "turn": "narrow-turn", "state": "running", "elapsed_seconds": 5, "last_contact_seconds": 2})
                narrow_active = bar.evaluate(appearance)
                self.assertEqual(narrow_active["box"], narrow_idle["box"])
                self.assertEqual(narrow_active["row"], narrow_idle["row"])
                page.set_viewport_size({"width": 1600, "height": 1000})
                page.evaluate("operation => updateOperation(operation)",
                              {"turn": "finished-turn", "state": "running", "elapsed_seconds": 5,
                               "last_contact_seconds": 2, "phase": "starting"})
                expect(page.locator("#status-bar")).to_have_text("Working — 5s elapsed, last Bridge contact 2s ago.")
                operation = {"turn": "finished-turn", "state": "finished", "elapsed_seconds": 7,
                             "maintenance": "applied", "warnings": ["Connector version is old."],
                             "bridge_diagnostics": ["Connector version is old."], "visible_warnings": []}
                page.evaluate("operation => updateOperation(operation)", operation)
                expect(page.locator("#status-bar")).to_have_text("Reply complete in 7s. Registry updated.")
                self.assertEqual(bar.evaluate(appearance), idle)
                # Repeated terminal polls must also preserve the idle look.
                page.evaluate("operation => updateOperation(operation)", operation)
                self.assertEqual(bar.evaluate(appearance), idle)
                # Diagnostics that ask nothing sit under More, never in the bar.
                expect(page.locator("#status-bar")).not_to_contain_text("Connector version is old.")
                expect(page.locator("#more-turn")).not_to_have_attribute("hidden", "")
                expect(page.locator("#more-diagnostics li")).to_have_text("Connector version is old.")
                expect(page.locator("#more-artifact")).to_be_empty()
                # The conversation cards carry no Technical details expander:
                # More is the single home for those diagnostics, while the
                # underlying record keeps them and the reply stays visible.
                page.evaluate("turns => { conversationTurns = turns; renderConversation(); }", [{
                    "turn": "diag-turn", "stage": "specification", "tool": "codex", "purpose": "work",
                    "text": "The work request.", "images": [], "files": [], "state": "complete",
                    "reply": "The completed reply.", "maintenance": None, "outcome_recorded": True,
                    "artifact": None, "bridge_diagnostics": ["Connector version is old."], "questions": []}])
                expect(page.locator("#conversation")).to_contain_text("The completed reply.")
                expect(page.locator("#conversation .bridge-details")).to_have_count(0)
                expect(page.locator("#conversation")).not_to_contain_text("Technical details")
                expect(page.locator("#more-diagnostics li")).to_have_text("Connector version is old.")

                operation.update({"maintenance": "stale", "maintenance_reason": "The Registry changed, so nothing was applied.",
                                  "warnings": [], "bridge_diagnostics": [], "visible_warnings": []})
                page.evaluate("operation => updateOperation(operation)", operation)
                expect(page.locator("#status-bar")).to_contain_text("Registry update not applied (stale). The Registry changed")

                # Warnings needing attention join the status text itself.
                operation.update({
                                  "warnings": ["Connector version is old.", "The outcome note could not be recorded: disk is full.", "Other warning."],
                                  "bridge_diagnostics": ["Connector version is old."],
                                  "visible_warnings": ["The outcome note could not be recorded: disk is full."]})
                page.evaluate("operation => updateOperation(operation)", operation)
                expect(page.locator("#status-bar")).to_contain_text("Registry update not applied (stale). The Registry changed")
                expect(page.locator("#status-bar")).to_contain_text("outcome note could not be recorded")
                expect(page.locator("#status-bar")).to_contain_text("Other warning.")

                operation.update({"state": "failed", "reason": "The coding tool refused the request."})
                page.evaluate("operation => updateOperation(operation)", operation)
                expect(page.locator("#status-bar")).to_contain_text("The turn failed: The coding tool refused the request.")
                self.assertEqual(bar.evaluate(appearance)["background"], idle["background"])
                self.assertNotEqual(bar.evaluate(appearance)["color"], idle["color"])

                operation.update({"state": "interrupted", "reason": "Stopped by the user. Files already changed remain.",
                                  "warnings": [], "bridge_diagnostics": [],
                                  "artifact": {"role": "Programming Result", "path": "/selected/Programming Result.md",
                                               "outcome": "unchanged", "reason": ""}})
                page.evaluate("operation => updateOperation(operation)", operation)
                expect(page.locator("#status-bar")).to_contain_text("Interrupted: Stopped by the user.")
                self.assertEqual(bar.evaluate(appearance)["font"], idle["font"])
                expect(page.locator("#more-artifact")).to_contain_text("read back unchanged")

                review = {"turn": "review-run", "stage": "review-specification", "state": "finished",
                          "elapsed_seconds": 9, "maintenance": "applied", "warnings": [],
                          "bridge_diagnostics": [], "visible_warnings": []}
                page.evaluate("operation => updateOperation(operation)", review)
                expect(page.locator("#status-bar")).to_have_text("Review completed in 9s. Assessment saved.")
                expect(page.locator("#status-bar")).not_to_contain_text("Registry")

                review.update({"stage": "review-plan", "maintenance": "unsaved",
                               "maintenance_reason": "The document could not be read: permission denied.",
                               "warnings": ["Connector version is old."],
                               "bridge_diagnostics": ["Connector version is old."]})
                page.evaluate("operation => updateOperation(operation)", review)
                expect(page.locator("#status-bar")).to_have_text(
                    "Review completed in 9s. Assessment not saved. The document could not be read: permission denied.")
                expect(page.locator("#more-diagnostics li")).to_have_count(1)
                page.evaluate("() => lostContact()")
                expect(page.locator("#status-bar")).to_contain_text("Lost contact with the local server")
                page.evaluate("() => { contactRestored(); updateOperation(lastOperation); }")
                expect(page.locator("#status-bar")).not_to_contain_text("Lost contact")

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
                bar = page.locator("#status-bar")
                self.assertTrue(bar.evaluate("element => element.scrollHeight > element.clientHeight"))
                self.assertEqual(bar.evaluate("element => getComputedStyle(element).overflowY"), "auto")
                bar.evaluate("element => element.scrollTop = element.scrollHeight")
                self.assertGreater(bar.evaluate("element => element.scrollTop"), 0)
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


    def test_routine_readback_receipts_live_under_more_not_on_the_cards(self):
        # The saved-file readback that merely confirms a routine successful
        # save — and the local file's location — are secondary detail with one
        # home: More, beside the turn they belong to, plus the underlying
        # records. Completed cards keep their substantive replies and their
        # actionable readback failures; the routine receipts and the
        # "Local file" expanders are gone from the cards themselves.
        try:
            from playwright.sync_api import expect, sync_playwright
        except ImportError:
            self.skipTest("Playwright is not installed for the browser check")
        project_id = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
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
                # The replies stay; the unreadable result stays visibly actionable.
                expect(conversation).to_contain_text("The substantive saved reply.")
                expect(conversation).to_contain_text("The reply whose file could not be confirmed.")
                expect(conversation).to_contain_text("The selected Plan could not be read back: permission denied.")
                # The routine successful readback is not repeated on the card.
                expect(conversation).not_to_contain_text("differs from the content captured")
                expect(conversation).not_to_contain_text("Local file:")
                self.assertEqual(conversation.locator(".artifact-readback").count(), 1)
                self.assertEqual(conversation.locator("summary", has_text="Local file").count(), 0)
                # A completed review card behaves the same: its assessment
                # output stays, its routine readback receipt does not appear.
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
                # More is the single home for the routine readback and the path.
                page.evaluate("operation => updateOperation(operation)",
                              {"turn": "saved-turn", "state": "finished", "elapsed_seconds": 4,
                               "maintenance": None, "warnings": [], "bridge_diagnostics": [], "visible_warnings": [],
                               "artifact": routine})
                expect(page.locator("#more-turn")).not_to_have_attribute("hidden", "")
                expect(page.locator("#more-artifact")).to_contain_text("differs from the content captured")
                expect(page.locator("#more-artifact")).to_contain_text("Local file: /selected/Specification.md")
            finally:
                browser.close()


    def test_step7_copy_works_without_a_selected_tool_while_send_still_refuses(self):
        # The step-7 dialog promises "Copy works without one" when no coding
        # tool is selected; the shared delivery path must keep that promise —
        # the request is prepared, saved and copied for an external chat —
        # while Send keeps the step-3 requirement and its existing refusal.
        from playwright.sync_api import expect, sync_playwright
        project_id = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
        folder = self.home / "One"
        def ready(peer, **kwargs):
            return {"peer": peer, "ready": True, "work": "supported", "authentication": "unknown", "warnings": []}
        with mock.patch("ora_vibe_coder.conversation.bridge_check", side_effect=ready), \
                mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
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
                # Step 3 has no coding tool selected.
                expect(page.locator("#destination")).to_have_value("")
                page.locator("#review-step").evaluate("element => element.open = true")
                page.locator("#review").click()
                expect(page.locator("#build-action-dialog")).to_be_visible()
                expect(page.locator("#build-action-title")).to_have_text("Independently verify the implementation")
                expect(page.locator("#build-action-note")).to_contain_text("Copy works without one")
                # With no tool there is nothing to Send to, so only Copy and
                # Cancel are offered.
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
                # A copy starts no conversation turn in the app.
                _status, recorded, _headers = self.request("/api/conversation", {"id": project_id})
                self.assertEqual(recorded["turns"], [])
                # Send on the same shared path keeps the step-3 requirement.
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
    # The bundled installer's own guard: it never replaces a newer entry.
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
        # The release ships the reviewed Bridge runtime exactly as pinned, and
        # the reviewed Boost runtime with its generated counterpart.
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

    def test_project_opening_recovers_from_auxiliary_read_failures_and_clears_status(self):
        try:
            from playwright.sync_api import expect, sync_playwright
        except ImportError:
            self.skipTest("Playwright is not installed for the browser check")

        self.server.settings = Settings(self.home / "opening-settings.json")
        projects = {}
        for name in ("Working", "History", "Status", "Empty", "Destination"):
            projects[name] = self.request("/api/create", {"directory": name, "name": name,
                                                         "description": "", "goals": ""})[1]["id"]
        for name in ("History", "Status"):
            (self.home / name / f"{name} — Plan.md").write_text(
                f"# Plan\n\nStatus: DRAFT\n\nReadable {name} plan.\n", encoding="utf-8")
            messages = self.home / name / ".vibe" / "0001-20261023-120000" / "session" / "messages"
            messages.mkdir(parents=True)
            body = conversation.user_note_body("verification", "codex", f"Retained {name} instruction.", [])
            (messages / "0001-initiator-record.md").write_text(
                f"# Message 0001\nKind: note\n\n## Body\n\n{body}", encoding="utf-8")
        for name, stage in (("Working", "programming"), ("History", "planning"), ("Status", "verification")):
            active = self.server.store.projects[projects[name]]
            handle = conversation.TurnOperation(active.root, "codex", stage, {})
            handle.turn = "0001-20261023-120000"
            handle.state = "running"
            self.server.conversation.by_project[str(active.root)] = handle

        failures, holds, pending, requests, errors = set(), {}, {}, [], []
        evidence = Path(os.environ["VIBE_NAVIGATION_EVIDENCE"]) / "opening" if os.environ.get("VIBE_NAVIGATION_EVIDENCE") else None
        if evidence:
            evidence.mkdir(parents=True, exist_ok=True)

        def ready(peer, **kwargs):
            return {"peer": peer, "ready": True, "work": "supported", "authentication": "confirmed", "warnings": []}

        with mock.patch("ora_vibe_coder.conversation.bridge_check", side_effect=ready), \
                mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), \
                mock.patch("ora_vibe_coder.conversation.start_turn") as dispatch, \
                mock.patch("ora_vibe_coder.conversation.start_assessment") as assess, \
                mock.patch("ora_vibe_coder.conversation.start_aux") as auxiliary, sync_playwright() as playwright:
            if not Path(playwright.chromium.executable_path).is_file():
                self.skipTest("Playwright's Chromium is not installed for the browser check")
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
            try:
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))

                def route_api(route):
                    endpoint = urlsplit(route.request.url).path.rsplit("/", 1)[-1]
                    data = route.request.post_data_json
                    requests.append((endpoint, data))
                    key = (data.get("id"), endpoint)
                    if key in holds:
                        mode = holds.pop(key)
                        pending[key] = (route, route.fetch() if mode == "success" else None)
                    elif key in failures:
                        route.fulfill(status=503, content_type="application/json",
                                      body=json.dumps({"error": f"Fixture: {endpoint} unavailable."}))
                    else:
                        route.continue_()

                page.route("**/api/**", route_api)
                page.goto(self.server.url)
                page.wait_for_function("() => project?.name === 'Destination' && pollTimer !== null && lastFiles !== null")

                def opened(name, stage):
                    self.select_project(page, projects[name])
                    page.wait_for_function("data => project?.name === data.name && workspace === data.stage && pollTimer !== null",
                                           arg={"name": name, "stage": stage})
                    expect(page.locator("#stage-panel")).to_be_visible()
                    expect(page.locator("#rails")).to_be_visible()
                    page.locator("#destination").select_option(label="Codex")
                    page.wait_for_function("() => readinessState.peers?.some(peer => peer.peer === 'codex' && peer.ready)")

                def capture(name):
                    if evidence:
                        page.screenshot(path=str(evidence / f"{name}.png"), full_page=True)

                def release(name, endpoint):
                    route, response = pending.pop((projects[name], endpoint))
                    if response is not None:
                        route.fulfill(response=response)
                    else:
                        route.fulfill(status=503, content_type="application/json",
                                      body=json.dumps({"error": f"Fixture: stale {endpoint} failure."}))

                opened("Working", "build")
                expect(page.locator("#status-bar")).to_contain_text("Working —")
                # Hold the next project's live answer: the old Working text
                # clears immediately, before any new status can replace it.
                holds[(projects["Status"], "turn-state")] = "success"
                self.select_project(page, projects["Status"])
                page.wait_for_function("() => project?.name === 'Status'")
                page.wait_for_function("() => document.getElementById('status-bar').textContent === ''")
                expect(page.locator("#status-bar")).not_to_have_class("active")
                capture("switch-clears-working")
                # Its late successful answer cannot put Working on the idle
                # destination, even though the originating turn is still live.
                opened("Destination", "specification")
                release("Status", "turn-state")
                page.wait_for_function("() => project?.name === 'Destination' && lastFiles !== null")
                expect(page.locator("#status-bar")).not_to_contain_text("Working —")
                self.assertIsNone(page.evaluate("lastOperation"))

                failures.add((projects["History"], "conversation"))
                opened("History", "plan")
                expect(page.locator("#reader")).to_contain_text("Readable History plan.")
                expect(page.locator("#status-bar")).to_contain_text("Conversation history could not be loaded")
                self.assertEqual(page.evaluate("lastOperation.state"), "running")
                expect(page.locator("#send")).to_be_disabled()
                self.assertTrue(any(endpoint == "turn-state" and data.get("id") == projects["History"] for endpoint, data in requests))
                capture("history-failure-documents-and-known-work")
                # No manual retry: the existing timer loads the retained
                # history when it returns, without moving the chosen page.
                failures.remove((projects["History"], "conversation"))
                expect(page.locator("#conversation")).to_contain_text("Retained History instruction.")
                self.assertEqual(page.evaluate("workspace"), "plan")
                expect(page.locator("#send")).to_be_disabled()
                capture("history-recovered-at-chosen-stage")

                failures.add((projects["Status"], "turn-state"))
                opened("Status", "build")
                expect(page.locator("#conversation")).to_contain_text("Retained Status instruction.")
                page.locator("#document").select_option(label="Plan — Status")
                expect(page.locator("#reader")).to_contain_text("Readable Status plan.")
                expect(page.locator("#status-bar")).to_contain_text("turn-state unavailable")
                self.assertTrue(page.evaluate("lastOperation === undefined"))
                expect(page.locator("#send")).to_be_disabled()
                expect(page.locator("#run-completion")).to_be_disabled()
                page.locator("#message").fill("Keep this unsent draft while live status is unknown.")
                picture = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c020000000b4944415478da6364f80f00010501012718e3660000000049454e44ae426082")
                page.locator("#image-input").set_input_files({"name": "opening-draft.png", "mimeType": "image/png", "buffer": picture})
                page.locator("#message").press("Enter")
                expect(page.locator("#status-bar")).to_contain_text("work status is unknown")
                page.evaluate("() => deliverStep('create-plan', 'send')")
                self.assertFalse(any(endpoint in {"converse", "review", "repair", "deliver", "run-start"} for endpoint, _ in requests))
                capture("status-failure-visible-history-and-draft")
                failures.remove((projects["Status"], "turn-state"))
                page.wait_for_function("() => lastOperation?.state === 'running' && !contactLost")
                expect(page.locator("#status-bar")).to_contain_text("Working —")
                expect(page.locator("#send")).to_be_disabled()
                expect(page.locator("#message")).to_have_value("Keep this unsent draft while live status is unknown.")
                expect(page.locator("#attachment-bar img")).to_have_attribute("alt", "opening-draft.png")
                self.assertEqual(page.evaluate("workspace"), "build")
                capture("status-recovered-running-work")

                # With both reads unavailable and no saved progress, opening
                # still shows Specification and never calls the project idle.
                failures.update((projects["Empty"], endpoint) for endpoint in ("conversation", "turn-state"))
                opened("Empty", "specification")
                expect(page.locator("#reader")).to_contain_text("Specification")
                self.assertTrue(page.evaluate("lastOperation === undefined"))
                expect(page.locator("#send")).to_be_disabled()
                expect(page.locator("#status-bar")).not_to_contain_text("nothing is running")
                capture("both-fail-specification-fallback")
                # An early manual rail choice survives the same failures.
                opened("Destination", "specification")
                holds[(projects["Empty"], "conversation")] = "error"
                self.select_project(page, projects["Empty"])
                page.wait_for_function("() => project?.name === 'Empty' && workspace === ''")
                page.locator('.rail[data-stage="plan"]').click()
                release("Empty", "conversation")
                page.wait_for_function("() => workspace === 'plan' && pollTimer !== null")
                expect(page.locator("#reader")).to_contain_text("Plan")
                failures.difference_update((projects["Empty"], endpoint) for endpoint in ("conversation", "turn-state"))
                page.wait_for_function("() => conversationLoaded && lastOperation === null && lastFiles !== null")
                expect(page.locator("#send")).to_be_enabled()
                expect(page.locator("#run-completion")).to_be_enabled()
                self.assertEqual(page.evaluate("workspace"), "plan")
                expect(page.locator("#message")).to_have_value("Keep this unsent draft while live status is unknown.")
                expect(page.locator("#attachment-bar img")).to_have_attribute("alt", "opening-draft.png")
                capture("both-recovered-with-manual-choice-and-draft")

                # A delayed history failure also stays with its origin; the
                # successful destination keeps its page, polling and readiness.
                holds[(projects["History"], "conversation")] = "error"
                self.select_project(page, projects["History"])
                page.wait_for_function("() => project?.name === 'History' && workspace === ''")
                opened("Destination", "specification")
                release("History", "conversation")
                page.wait_for_function("() => project?.name === 'Destination' && lastFiles !== null")
                expect(page.locator("#status-bar")).not_to_contain_text("stale conversation failure")
                expect(page.locator("#status-bar")).not_to_contain_text("Working —")
                self.assertTrue(page.evaluate("conversationLoaded && lastOperation === null && pollTimer !== null"))
                capture("stale-history-error-isolated")
                dispatch.assert_not_called()
                assess.assert_not_called()
                auxiliary.assert_not_called()
                self.assertEqual(errors, [])
                self.assertEqual(pending, {})
            finally:
                context.close()
                browser.close()
                self.server.conversation.by_project.clear()

    def test_projects_open_at_progress_and_rails_slide_without_losing_drafts(self):
        try:
            from playwright.sync_api import expect, sync_playwright
        except ImportError:
            self.skipTest("Playwright is not installed for the browser check")

        settings = Settings(self.home / "navigation-settings.json")
        self.server.settings = settings
        projects = {}
        for name in ("Fresh", "Specification", "Planning", "Approved", "Build", "Verification",
                     "LegacyVerificationPassed", "LegacyVerificationActive",
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
        for name, status in (("LegacyVerificationPassed", "PASSED"), ("LegacyVerificationActive", "IN PROGRESS")):
            definition = self.server.store.projects[projects[name]].root / "Project.md"
            text = definition.read_text(encoding="utf-8")
            self.assertIn("Programming: NOT STARTED", text)
            self.assertIn("Verification: NOT STARTED", text)
            definition.write_text(text.replace("Verification: NOT STARTED", f"Verification: {status}"), encoding="utf-8")
        # An outgoing implementation request must not masquerade as implementation.
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

        evidence = Path(os.environ["VIBE_NAVIGATION_EVIDENCE"]) if os.environ.get("VIBE_NAVIGATION_EVIDENCE") else None
        if evidence:
            evidence.mkdir(parents=True, exist_ok=True)
        measurements = {}

        def ready(peer, **kwargs):
            return {"peer": peer, "ready": True, "work": "supported", "authentication": "confirmed", "warnings": []}

        with mock.patch("ora_vibe_coder.conversation.bridge_check", side_effect=ready), \
                mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), \
                mock.patch("ora_vibe_coder.conversation.start_turn") as dispatch, \
                mock.patch("ora_vibe_coder.conversation.start_assessment") as assess, \
                mock.patch("ora_vibe_coder.conversation.start_aux") as auxiliary, sync_playwright() as playwright:
            if not Path(playwright.chromium.executable_path).is_file():
                self.skipTest("Playwright's Chromium is not installed for the browser check")
            browser = playwright.chromium.launch(headless=True)
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

                def settled():
                    page.wait_for_function("() => workspaceReveal === null && workspaceAnimations.every(animation => animation.playState === 'finished' || animation.playState === 'idle')")
                    self.assertEqual(page.locator(".workspace-snapshot").count(), 0)
                    self.assertNotEqual(page.locator(".main-col").evaluate("element => getComputedStyle(element).pointerEvents"), "none")

                def arrangement(stage):
                    settled()
                    boxes = page.evaluate("""() => ({page: document.querySelector('.main-col').getBoundingClientRect().toJSON(),
                        rails: [...document.querySelectorAll('.rail')].map(rail => ({stage: rail.dataset.stage,
                            expanded: rail.getAttribute('aria-expanded'), box: rail.getBoundingClientRect().toJSON()}))})""")
                    selected = ["specification", "plan", "build"].index(stage)
                    for index, rail in enumerate(boxes["rails"]):
                        self.assertEqual(rail["expanded"], str(index == selected).lower(), f"{stage}: {boxes}")
                        if index <= selected:
                            self.assertLessEqual(rail["box"]["right"], boxes["page"]["left"])
                        else:
                            self.assertGreaterEqual(rail["box"]["left"], boxes["page"]["right"])
                    self.assertEqual([rail["stage"] for rail in sorted(boxes["rails"], key=lambda rail: rail["box"]["left"])],
                                     ["specification", "plan", "build"])
                    return boxes

                def capture(name):
                    if evidence:
                        page.screenshot(path=str(evidence / f"{name}.png"), full_page=True, animations="allow")

                def delay_plan_read():
                    page.evaluate("""() => {
                        window.delayedRead = {originalApi: api, pending: [], captured: false};
                        api = async (path, data) => {
                            const delay = window.delayedRead, result = await delay.originalApi(path, data);
                            if (path === 'read-file' && data.path.endsWith(' — Plan.md') && !delay.captured) {
                                delay.captured = true;
                                await new Promise(resolve => delay.pending.push(resolve));
                            }
                            return result;
                        };
                    }""")

                def release_plan_read():
                    page.evaluate("""() => { const delay = window.delayedRead;
                        api = delay.originalApi; delay.pending.forEach(resolve => resolve()); delete window.delayedRead; }""")

                def motion(name, forward, old_title, new_title):
                    page.wait_for_function("() => workspaceAnimations.some(animation => animation.playState === 'running' && animation.currentTime >= 250 && animation.currentTime < 800)")
                    # Pause a real intermediate frame so geometry, content and
                    # the screenshot all describe precisely the same instant.
                    page.evaluate("() => { for (const animation of workspaceAnimations) { animation.pause(); animation.currentTime = 400; } }")
                    observed = page.evaluate("""forward => {
                        const old = document.querySelector('.workspace-snapshot'), page = document.querySelector('.main-col');
                        const visible = element => {
                            const box = element.getBoundingClientRect(), values = getComputedStyle(element).clipPath.match(/[\\d.]+/g).map(Number);
                            const [top, right = top, bottom = top, left = right] = values;
                            return {left: box.left + left, right: box.right - right};
                        };
                        const rails = workspaceAnimations.map(animation => animation.effect.target).filter(element => element.classList.contains('rail'));
                        const edge = forward ? Math.min(...rails.map(rail => rail.getBoundingClientRect().left))
                            : Math.max(...rails.map(rail => rail.getBoundingClientRect().right));
                        const ids = [...document.querySelectorAll('[id]')].map(element => element.id);
                        return {x: document.querySelector('.rail[data-stage=plan]').getBoundingClientRect().x, edge,
                            old: visible(old), new: visible(page), oldTitle: workspaceReveal.frozen.querySelector('#stage-title').textContent,
                            newTitle: document.getElementById('stage-title').textContent,
                            oldReader: workspaceReveal.frozen.querySelector('#reader').textContent, newReader: document.getElementById('reader').textContent,
                            oldIcons: [...workspaceReveal.frozen.querySelectorAll('.project-action use, #project-card use')].map(icon => icon.getBBox().width),
                            inertSnapshot: old.inert, blockedPage: getComputedStyle(page).pointerEvents === 'none', duplicateLiveIds: ids.length - new Set(ids).size,
                            animations: workspaceAnimations.map(animation => ({time: animation.currentTime, duration: animation.effect.getTiming().duration})),
                            oldOpacity: getComputedStyle(old).opacity, newOpacity: getComputedStyle(document.getElementById('stage-panel')).opacity,
                            pageTransform: getComputedStyle(page).transform};
                    }""", forward)
                    self.assertEqual(observed["oldTitle"], old_title)
                    self.assertEqual(observed["newTitle"], new_title)
                    self.assertNotEqual(observed["oldReader"], observed["newReader"])
                    self.assertEqual(len(observed["oldIcons"]), 3)
                    self.assertTrue(all(width > 0 for width in observed["oldIcons"]))
                    self.assertTrue(observed["inertSnapshot"])
                    self.assertTrue(observed["blockedPage"])
                    self.assertEqual(observed["duplicateLiveIds"], 0)
                    self.assertEqual(observed["oldOpacity"], "1")
                    self.assertEqual(observed["newOpacity"], "1")
                    self.assertEqual(observed["pageTransform"], "none")
                    self.assertTrue(all(item["duration"] == 1000 for item in observed["animations"]))
                    self.assertAlmostEqual(observed["old"]["right" if forward else "left"], observed["edge"], delta=1)
                    self.assertAlmostEqual(observed["new"]["left" if forward else "right"], observed["edge"], delta=1)
                    self.assertGreater(observed["old"]["right"] - observed["old"]["left"], 50)
                    self.assertGreater(observed["new"]["right"] - observed["new"]["left"], 50)
                    capture(name)
                    page.evaluate("() => { for (const animation of workspaceAnimations) animation.play(); }")
                    return observed

                for name, stage in (("Fresh", "specification"), ("Specification", "specification"),
                                    ("Planning", "plan"), ("Approved", "plan"), ("Build", "build"),
                                    ("Verification", "build"), ("LegacyVerificationPassed", "build"),
                                    ("LegacyVerificationActive", "build"), ("Templates", "specification"),
                                    ("RetainedPlan", "plan"), ("RetainedBuild", "build"),
                                    ("ReviewPlan", "plan"), ("ActivePlan", "plan"), ("ActiveBuild", "build"), ("ActiveRun", "build")):
                    opened(name, stage)
                    arrangement(stage)
                    measurements[f"open-{name}"] = stage
                self.assertEqual(driver.state, "paused-question")
                self.assertTrue(all(handle.state == "running" for handle in self.server.conversation.by_project.values()))

                # Delay two overlapping opens of the same project. An early
                # real rail click wins the page, but the latest open must still
                # finish polling/readiness; the older open must not restart them.
                page.evaluate("""id => {
                    window.openingRace = {originalApi: api, pending: [], responses: []};
                    api = async (path, data) => {
                        const race = window.openingRace, result = await race.originalApi(path, data);
                        race.responses.push({path, data});
                        if (path === 'conversation' && data.id === id)
                            await new Promise(resolve => race.pending.push(resolve));
                        return result;
                    };
                    window.firstOpening = chooseProject(id);
                }""", projects["Approved"])
                page.wait_for_function("() => openingRace.pending.length === 1")
                page.evaluate("id => { window.secondOpening = chooseProject(id); }", projects["Approved"])
                page.wait_for_function("() => openingRace.pending.length === 2")
                page.locator('.rail[data-stage="build"]').click()
                expect(page.locator("#stage-title")).to_have_text("Build & Verify")
                page.evaluate("() => { openingRace.pending[1](); return secondOpening; }")
                page.wait_for_function("""() => pollTimer !== null && lastFiles !== null &&
                    openingRace.responses.some(response => response.path === 'readiness' && response.data.recheck)""")
                page.evaluate("() => { openingRace.pending[0](); return firstOpening; }")
                measurements["early-rail-opening"] = page.evaluate("""() => ({stage: workspace, polling: pollTimer !== null,
                    readinessRechecks: openingRace.responses.filter(response => response.path === 'readiness' && response.data.recheck).length,
                    stateResponses: openingRace.responses.filter(response => response.path === 'turn-state').length})""")
                self.assertEqual(measurements["early-rail-opening"]["stage"], "build")
                self.assertTrue(measurements["early-rail-opening"]["polling"])
                self.assertEqual(measurements["early-rail-opening"]["readinessRechecks"], 1)
                self.assertGreaterEqual(measurements["early-rail-opening"]["stateResponses"], 2)
                arrangement("build")
                capture("early-rail-opening")
                page.evaluate("""() => { api = openingRace.originalApi;
                    delete window.openingRace; delete window.firstOpening; delete window.secondOpening; }""")

                opened("Specification", "specification")
                page.locator("#destination").select_option(label="Codex")
                page.evaluate("() => deliverStep('create-plan', 'copy')")
                expect(page.locator("#status-bar")).to_contain_text("Create the Plan request copied and saved")
                self.assertTrue((self.home / "Specification" / "Handoff.md").is_file())
                opened("Fresh", "specification")
                opened("Specification", "specification")
                expect(page.locator("#next-step-title")).to_have_text("Create the Plan")

                # Existing drafts and reading controls survive the moving rail.
                page.locator("#message").fill("Keep this unsent instruction through every stage.")
                picture = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c020000000b4944415478da6364f80f00010501012718e3660000000049454e44ae426082")
                page.locator("#image-input").set_input_files({"name": "draft.png", "mimeType": "image/png", "buffer": picture})
                expect(page.locator("#attachment-bar")).to_contain_text("Remove")
                note = self.home / "material.txt"
                note.write_text("Existing material for the next message.", encoding="utf-8")
                page.locator("#add-message-files").click()
                page.locator("#file-path").fill(str(self.home))
                page.locator("#file-go").click()
                page.locator("#file-list button").filter(has_text="material.txt").click()
                page.locator("#file-cancel").click()
                expect(page.locator("#message-files")).to_contain_text("material.txt")
                page.locator("#spine").focus()
                page.locator("#spine").press("ArrowRight")
                fraction = page.evaluate("splitFraction")
                measurements["desktop-specification"] = arrangement("specification")
                capture("desktop-specification")

                document("Specification", "Plan", "# Plan\n\nStatus: DRAFT\n\nNEW PLAN: use the current note editor and save files locally.\n")
                delay_plan_read()
                page.locator('.rail[data-stage="plan"]').click()
                expect(page.locator("#stage-title")).to_have_text("Plan")
                page.wait_for_function("() => delayedRead.pending.length === 1")
                page.wait_for_timeout(1100)
                measurements["slow-read-waits"] = page.evaluate("""() => ({oldTitle: workspaceReveal.frozen.querySelector('#stage-title').textContent,
                    oldClip: getComputedStyle(workspaceReveal.snapshot).clipPath,
                    animations: workspaceAnimations.map(animation => ({time: animation.currentTime, state: animation.playState})),
                    liveReader: document.getElementById('reader').textContent})""")
                self.assertEqual(measurements["slow-read-waits"]["oldTitle"], "Specification")
                self.assertTrue(all(item["time"] == 0 and item["state"] == "paused" for item in measurements["slow-read-waits"]["animations"]))
                self.assertIn("Loading", measurements["slow-read-waits"]["liveReader"])
                capture("slow-read-old-page")
                release_plan_read()
                measurements["forward-motion"] = motion("forward-motion", True, "Specification", "Plan")
                self.assertIn("NEW PLAN:", measurements["forward-motion"]["newReader"])
                measurements["desktop-plan"] = arrangement("plan")
                capture("desktop-plan")
                self.assertGreater(measurements["forward-motion"]["x"], measurements["desktop-plan"]["rails"][1]["box"]["x"])
                self.assertLess(measurements["forward-motion"]["x"], measurements["desktop-specification"]["rails"][1]["box"]["x"])
                page.locator('.rail[data-stage="build"]').click()
                measurements["desktop-build"] = arrangement("build")
                capture("desktop-build")
                expect(page.locator("#message")).to_have_value("Keep this unsent instruction through every stage.")
                expect(page.locator("#attachment-bar img")).to_have_attribute("alt", "draft.png")
                expect(page.locator("#destination")).to_have_value("Codex")
                self.assertEqual(page.evaluate("splitFraction"), fraction)
                page.locator('.rail[data-stage="specification"]').click()
                measurements["backward-motion"] = motion("backward-motion", False, "Build & Verify", "Specification")
                arrangement("specification")
                self.assertGreater(measurements["backward-motion"]["x"], measurements["desktop-build"]["rails"][1]["box"]["x"])
                self.assertLess(measurements["backward-motion"]["x"], measurements["desktop-specification"]["rails"][1]["box"]["x"])
                expect(page.locator("#message-files")).to_contain_text("material.txt")

                # Real keyboard actions cannot submit a draft to the still
                # covered stage. A fresh activation works after it is visible.
                submitted = []
                page.route("**/api/converse", lambda route: (
                    submitted.append(route.request.post_data_json),
                    route.fulfill(status=400, content_type="application/json", body='{"error":"Keyboard check stopped before dispatch."}')
                ))
                held_message = page.locator("#message").input_value()
                for target, key in (("#message", "Enter"), ("#send", "Space")):
                    delay_plan_read()
                    page.locator('.rail[data-stage="plan"]').click()
                    page.wait_for_function("() => delayedRead.pending.length === 1 && workspaceReveal !== null")
                    page.locator(target).focus()
                    page.keyboard.press(key)
                    arrangement("plan")
                    self.assertEqual(submitted, [])
                    expect(page.locator("#message")).to_have_value(held_message)
                    expect(page.locator("#attachment-bar img")).to_have_attribute("alt", "draft.png")
                    capture(f"keyboard-{key.lower()}-reveals-page")
                    release_plan_read()
                    expect(page.locator("#reader")).to_contain_text("NEW PLAN:")
                    page.locator('.rail[data-stage="specification"]').click()
                    arrangement("specification")

                delay_plan_read()
                page.locator('.rail[data-stage="plan"]').click()
                page.wait_for_function("() => delayedRead.pending.length === 1 && workspaceReveal !== null")
                page.locator("#message").focus()
                page.locator("#message").evaluate("element => element.setSelectionRange(element.value.length, element.value.length)")
                page.keyboard.type(" More typed text.")
                arrangement("plan")
                expect(page.locator("#message")).to_have_value(held_message + " More typed text.")
                self.assertEqual(submitted, [])
                release_plan_read()
                expect(page.locator("#reader")).to_contain_text("NEW PLAN:")
                page.keyboard.press("Enter")
                expect(page.locator("#status-bar")).to_contain_text("Keyboard check stopped before dispatch")
                self.assertEqual(len(submitted), 1)
                self.assertEqual(submitted[0]["stage"], "planning")
                self.assertEqual(submitted[0]["text"], held_message + " More typed text.")
                expect(page.locator("#message")).to_have_value(held_message + " More typed text.")
                expect(page.locator("#attachment-bar img")).to_have_attribute("alt", "draft.png")
                measurements["keyboard-during-old-page"] = {"coveredActivationsSubmitted": 0,
                    "visibleSubmission": submitted[0]["stage"], "preservedText": page.locator("#message").input_value()}
                capture("keyboard-typing-and-visible-send")
                page.unroute("**/api/converse")
                page.locator("#message").fill(held_message)
                page.locator('.rail[data-stage="specification"]').click()
                arrangement("specification")

                # A document change updates the chosen reader without auto-routing.
                document("Specification", "Plan", "# Plan\n\nStatus: DRAFT\n\nPlanning has now begun outside the app.\n")
                page.evaluate("() => refreshChanged([], {silent: true})")
                expect(page.locator("#stage-title")).to_have_text("Specification")
                page.locator("#document").select_option(label="Plan — Specification")
                expect(page.locator("#reader")).to_contain_text("Planning has now begun outside the app.")
                page.evaluate("() => refreshChanged([], {silent: true})")
                expect(page.locator("#document option:checked")).to_have_text("Plan — Specification")
                expect(page.locator("#reader")).to_contain_text("Planning has now begun outside the app.")
                expect(page.locator("#message")).to_have_value("Keep this unsent instruction through every stage.")

                # A slow cancelled read must never reappear after another stage
                # or project takes ownership of the real page.
                delay_plan_read()
                page.locator('.rail[data-stage="plan"]').click()
                page.wait_for_function("() => delayedRead.pending.length === 1")
                page.locator('.rail[data-stage="build"]').click()
                release_plan_read()
                arrangement("build")
                expect(page.locator("#reader")).to_be_empty()
                delay_plan_read()
                page.locator('.rail[data-stage="plan"]').click()
                page.wait_for_function("() => delayedRead.pending.length === 1")
                page.evaluate("id => chooseProject(id)", projects["Fresh"])
                release_plan_read()
                arrangement("specification")
                expect(page.locator("#reader")).not_to_contain_text("Planning has now begun outside the app.")
                measurements["cancelled-read-project"] = page.evaluate("({name: project.name, stage: workspace, snapshots: document.querySelectorAll('.workspace-snapshot').length})")
                opened("Specification", "plan")
                page.locator('.rail[data-stage="specification"]').click()
                arrangement("specification")

                # Quick successive clicks cancel stale animation and stale document reads.
                page.evaluate("""() => { for (const stage of ['plan', 'build', 'plan', 'specification', 'build'])
                    document.querySelector(`.rail[data-stage=${stage}]`).click(); }""")
                arrangement("build")
                expect(page.locator("#stage-title")).to_have_text("Build & Verify")
                expect(page.locator("#reader")).to_be_empty()
                expect(page.locator("#message")).to_have_value("Keep this unsent instruction through every stage.")

                page.emulate_media(reduced_motion="reduce")
                page.locator('.rail[data-stage="plan"]').click()
                arrangement("plan")
                self.assertEqual(page.evaluate("workspaceAnimations.length"), 0)
                page.emulate_media(reduced_motion="no-preference")
                page.locator('.rail[data-stage="specification"]').click()
                page.wait_for_function("() => workspaceAnimations.some(animation => animation.playState === 'running')")
                page.emulate_media(reduced_motion="reduce")
                arrangement("specification")
                self.assertEqual(page.evaluate("workspaceAnimations.length"), 0)
                page.emulate_media(reduced_motion="no-preference")
                page.set_viewport_size({"width": 375, "height": 812})
                for stage in ("specification", "plan", "build"):
                    page.locator(f'.rail[data-stage="{stage}"]').click()
                    boxes = arrangement(stage)
                    for rail in boxes["rails"]:
                        self.assertGreaterEqual(rail["box"]["left"], 0)
                        self.assertLessEqual(rail["box"]["right"], 375)
                    expect(page.locator("#single-toggle")).to_be_visible()
                    page.locator("#single-toggle").click()
                    self.assertEqual(page.locator("#split").get_attribute("data-mode"), "doc")
                    page.locator("#single-toggle").click()
                    self.assertEqual(page.locator("#split").get_attribute("data-mode"), "chat")
                    capture(f"narrow-{stage}")

                # Reopening ignores the last manually viewed page and re-derives progress.
                page.locator("#message").fill("")
                page.locator('#attachment-bar button').click()
                page.locator('.rail[data-stage="specification"]').click()
                arrangement("specification")
                page.reload()
                page.wait_for_function("() => project?.name === 'Specification' && workspace === 'plan' && pollTimer !== null")
                expect(page.locator("#next-step-title")).to_have_text("Implement the Plan")
                page.set_viewport_size({"width": 1440, "height": 1000})
                capture("reopened-at-plan")
                measurements["reopened-stage"] = page.evaluate("workspace")
                dispatch.assert_not_called()
                assess.assert_not_called()
                auxiliary.assert_not_called()
                self.assertEqual(errors, [])
                if evidence:
                    (evidence / "navigation-observations.json").write_text(json.dumps(measurements, indent=2), encoding="utf-8")
            finally:
                context.close()
                browser.close()
                self.server.conversation.by_project.clear()
                self.server.runs.by_project.clear()

    def test_coding_tool_follows_project_across_stages_without_another_readiness_check(self):
        try:
            from playwright.sync_api import expect, sync_playwright
        except ImportError:
            self.skipTest("Playwright is not installed for the browser check")

        first = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
        second = self.request("/api/create", {"directory": "Two", "name": "Two", "description": "", "goals": ""})[1]["id"]
        overview = self.home / "Two" / "Project.md"
        overview.write_text(overview.read_text(encoding="utf-8").replace("Verification: NOT STARTED", "Verification: PASSED"), encoding="utf-8")
        permission_ready = {"full": True}

        def ready(peer, **kwargs):
            if peer == "zcode":
                full = kwargs.get("work_permission") == "full-access"
                return {"peer": peer, "ready": not full or permission_ready["full"], "work": "supported", "authentication": "unknown",
                        "effective_permission": "full-access" if full else "edit",
                        "headless_shell": full, "shell_execution_verified": False, "warnings": []}
            if peer == "codex":
                return {"peer": peer, "ready": True, "work": "supported", "authentication": "confirmed",
                        "executable": "/Applications/Codex.app/Contents/Resources/codex",
                        "version": "codex-cli 0.162.1",
                        "message": "Codex is installed and signed in; model acceptance has not been tested.",
                        "warnings": ["The selected model is checked only when you send a request."]}
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
                context = browser.new_context(permissions=["clipboard-read", "clipboard-write"])
                try:
                    page = context.new_page()
                    page.goto(self.server.url)
                    self.select_project(page, first)
                    expect(page.locator("#stage-title")).to_have_text("Specification")
                    self.assertEqual(page.locator("#project-card .step-number").inner_text(), "2")
                    self.assertEqual(page.locator(".first-step .step-number").inner_text(), "3")
                    self.assertEqual([page.locator(f"#{step} .step-number").inner_text()
                                      for step in ("work-step", "review-step", "next-step")], ["4", "5", "6"])
                    self.assertEqual(page.locator("#split").get_attribute("data-mode"), "split")
                    spine = page.locator("#spine").bounding_box()
                    title_text = page.locator("#stage-title").evaluate(
                        "element => { const range = document.createRange(); range.selectNodeContents(element); return range.getBoundingClientRect().toJSON(); }")
                    tool = page.locator(".first-step").bounding_box()
                    self.assertLess(abs(title_text["x"] + title_text["width"] / 2 - (spine["x"] + spine["width"] / 2)), 8)
                    self.assertLess(tool["x"] + tool["width"], title_text["x"])
                    rail_widths = [rail.bounding_box()["width"] for rail in page.locator(".rail").all()]
                    self.assertLess(max(rail_widths) - min(rail_widths), 1)
                    page.set_viewport_size({"width": 800, "height": 900})
                    expect(page.locator("#single-toggle")).to_be_visible()
                    expect(page.locator("#split")).to_have_attribute("data-mode", "chat")
                    page.locator("#single-toggle").click()
                    expect(page.locator("#split")).to_have_attribute("data-mode", "doc")
                    page.set_viewport_size({"width": 1280, "height": 720})
                    expect(page.locator("#split")).to_have_attribute("data-mode", "split")
                    page.locator("#destination").select_option(label="Codex")
                    expect(page.locator("#readiness")).to_contain_text("Codex: available — model unverified")
                    # Readiness detail opens under More, never as a second panel.
                    page.locator("#readiness").click()
                    expect(page.locator("#more")).to_have_attribute("open", "")
                    expect(page.locator("#readiness-detail")).to_contain_text("Sign-in: confirmed.")
                    expect(page.locator("#readiness-detail")).to_contain_text("/Applications/Codex.app/Contents/Resources/codex")
                    expect(page.locator("#readiness-detail")).to_contain_text("codex-cli 0.162.1")
                    expect(page.locator("#readiness-detail")).to_contain_text("Each request uses Codex's current model and account settings.")
                    checked = probes.call_count
                    page.locator("#more").evaluate("element => element.open = false")

                    # The coding tool belongs to the project across stages, and a
                    # stage switch runs no new readiness probe.
                    page.locator('.rail[data-stage="plan"]').click()
                    expect(page.locator("#stage-title")).to_have_text("Plan")
                    self.assertEqual(page.locator("#destination").input_value(), "Codex")
                    self.assertEqual(probes.call_count, checked)
                    page.locator("#destination").select_option(label="ZCode")
                    expect(page.locator("#readiness")).to_contain_text("Edit · programming: Full access")
                    page.locator('.rail[data-stage="build"]').click()
                    expect(page.locator("#readiness .readiness-short")).to_have_text("Full access")
                    page.locator("#readiness").click()
                    expect(page.locator("#readiness-detail")).to_contain_text("Full access under your account")
                    expect(page.locator("#readiness-detail")).to_contain_text("Git and tests can run without an approval connection")
                    expect(page.locator("#readiness-detail")).to_contain_text("actual execution remains unverified")
                    page.locator("#build-reply-stage").select_option("verification")
                    expect(page.locator("#readiness")).to_contain_text("Edit · programming: Full access")
                    expect(page.locator("#readiness-detail")).to_contain_text("Current stage permission: Edit")
                    page.locator("#build-reply-stage").select_option("programming")
                    expect(page.locator("#readiness .readiness-short")).to_have_text("Full access")
                    permission_ready["full"] = False
                    page.locator("#recheck").click()
                    expect(page.locator("#readiness .readiness-short")).to_have_text("Not ready")
                    expect(page.locator("#readiness-detail")).to_contain_text("Full access requested; readiness not established")
                    expect(page.locator("#readiness-detail")).to_contain_text("Full access readiness has not been established")
                    permission_ready["full"] = True
                    page.locator("#recheck").click()
                    expect(page.locator("#readiness .readiness-short")).to_have_text("Full access")
                    checked = probes.call_count
                    page.locator('.rail[data-stage="plan"]').click()
                    expect(page.locator("#readiness")).to_contain_text("Edit · programming: Full access")
                    self.assertEqual(probes.call_count, checked)
                    page.locator("#more").evaluate("element => element.open = false")
                    page.locator("#destination").select_option(label="Claude Code")
                    page.locator('.rail[data-stage="specification"]').click()
                    self.assertEqual(page.locator("#destination").input_value(), "Claude Code")
                    self.select_project(page, second)
                    expect(page.locator("#project-name")).to_have_text("Two")
                    expect(page.locator("#destination")).to_have_value("")
                    self.select_project(page, first)
                    expect(page.locator("#destination")).to_have_value("Claude Code")

                    # One-click handoffs: step 6 saves the complete request and the
                    # status bar reports it; the path and manual copy stay in More.
                    page.locator(".rail[data-stage=plan]").click()
                    page.locator("#next-step").evaluate("element => element.open = true")
                    expect(page.locator("#transition")).to_have_text("Send to Claude Code")
                    page.locator("#message").fill("Focus the storage layer only.")
                    page.locator("#copy-request").click()
                    expect(page.locator("#implementation-warning")).to_be_visible()
                    page.locator("#implementation-back").click()
                    expect(page.locator("#message")).to_have_value("Focus the storage layer only.")
                    page.locator("#copy-request").click()
                    page.locator("#implementation-proceed").click()
                    implementation = self.home / "One" / "One — Implementation Request.md"
                    expect(page.locator("#status-bar")).to_contain_text("Implement the Plan request copied and saved", timeout=8000)
                    self.assertIn("Focus the storage layer only.", implementation.read_text(encoding="utf-8"))
                    self.assertIn("Framework instructions", implementation.read_text(encoding="utf-8"))
                    # Delivered through the clipboard: the unsent text is consumed once.
                    expect(page.locator("#message")).to_have_value("")
                    expect(page.locator("#more-request")).not_to_have_attribute("hidden", "")
                    expect(page.locator("#prepared-path")).to_have_value(str(implementation))
                    # A Hermes/Qwen selection has no in-app route: the step-6
                    # button names Terminal, and Run to Completion stays off.
                    page.locator("#destination").select_option(label="Qwen Code")
                    expect(page.locator("#transition")).to_have_text("Open Qwen Code in Terminal")
                    expect(page.locator("#run-completion")).to_be_disabled()
                    self.assertIn("cannot exchange turns in-app", page.locator("#run-completion").get_attribute("title") or "")
                    page.locator("#destination").select_option(label="Claude Code")
                    expect(page.locator("#run-completion")).to_be_enabled()
                finally:
                    browser.close()
            self.assertGreater(probes.call_count, 0)


    def test_document_outcomes_and_build_send_copy_agree(self):
        from playwright.sync_api import expect, sync_playwright
        project_name = "Sample — Inspect the map"
        directory = "Stored project folder"
        project_id = self.request("/api/create", {"directory": directory, "name": project_name, "description": "", "goals": ""})[1]["id"]
        folder = self.home / directory
        for role in ("Specification", "Plan"):
            path = folder / f"{project_name} — {role}.md"
            (folder / f"{role}.md").rename(path)
            path.write_text(f"# {role}\n\n## Scope\nThe agreed work.\n\n## Current review\nVerdict: COMPLETE\n", encoding="utf-8")
        result = folder / f"{project_name} — Programming Result current.md"
        report = folder / f"{project_name} — Verification Report current.md"
        result.write_text("# Programming Result\n\nProgramming completed 8 October 2026 under the approved Plan.\n", encoding="utf-8")
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
                mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(permissions=["clipboard-read", "clipboard-write"])
            try:
                page = context.new_page()
                page.goto(self.server.url)
                page.evaluate("() => { window.clipboardText = ''; navigator.clipboard.writeText = text => { window.clipboardText = text; return Promise.resolve(); }; }")
                self.select_project(page, project_id)
                page.locator('.rail[data-stage="specification"]').click()
                # The displayed verdict is binary: a current COMPLETE assessment is PASSED.
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

                for failed_report in (
                        "# Verification Report\n\n**Verdict: PASSED.** But the current candidate failed.\n",
                        passing_report.replace("No material finding remains.", "But the current candidate failed.")):
                    report.write_text(failed_report, encoding="utf-8")
                    page.locator("#refresh").click()
                    expect(page.locator("#assessment")).to_have_text("REPORT ERROR")
                    expect(page.locator("#assessment-note")).to_contain_text("current candidate failed")
                    expect(page.locator("#project-completion")).to_be_hidden()
                report.write_text(passing_report + "\nVerdict: NOT PASSED\n", encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("REPORT ERROR")
                expect(page.locator("#project-completion")).to_be_hidden()
                report.write_text("# Verification Report\n\nStatus: PASSED\n\n## Earlier review\nVerdict: NOT PASSED\n", encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("PASSED")

                # Build's steps share one delivery path: Copy saves the complete
                # request with the selected evidence; Send posts the identical
                # instruction. No conversation turn is started by Copy.
                page.locator("#destination").select_option(label="Codex")
                page.locator("#review-step").evaluate("element => element.open = true")
                page.locator("#verification-verifier").select_option(label="Claude Code")
                page.evaluate("path => material().push({path, name: 'Selected evidence.txt'})", str(evidence))
                deliveries = []

                def deliver(route):
                    body = route.request.post_data_json
                    if body.get("action") == "copy":
                        deliveries.append(body)
                        route.fallback()  # A copy runs on the real server and saves the file.
                        return
                    deliveries.append(body)
                    route.fulfill(json={"turn": f"fake-{len(deliveries)}", "operation": {"turn": f"fake-{len(deliveries)}", "state": "finished", "elapsed_seconds": 0}, "images": []})
                page.route("**/api/deliver", deliver)
                # The delivery assertions read the status bar's own words; the
                # poll's changed-file notice for this test's own writes would
                # overwrite them, so polling pauses for this segment.
                page.evaluate("() => stopPolling()")
                for action, button in (("verify", "#review"), ("correct", "#transition")):
                    if action == "correct":
                        page.locator("#message").fill("Fix the login defect first.")
                        page.locator("#next-step").evaluate("element => element.open = true")
                    else:
                        page.locator("#review-step").evaluate("element => element.open = true")
                    page.locator(button).click()
                    expect(page.locator("#build-action-dialog")).to_be_visible()
                    expect(page.locator("#build-action-send")).to_have_text("Send to Codex")
                    page.locator("#build-action-copy").click()
                    expect(page.locator("#build-action-dialog")).not_to_be_visible()
                    # This project's Specification and Plan carry COMPLETE
                    # reviews, so the advisory warning rightly stays away; its
                    # asking-but-never-blocking behavior is covered where the
                    # reviews are missing.
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
                    # A copy consumes the unsent text once it is delivered.
                    expect(page.locator("#message")).to_have_value("")
                    page.locator(button).click()
                    page.locator("#build-action-send").click()
                    expect(page.locator("#build-action-dialog")).not_to_be_visible()
                    expect(page.locator("#status-bar")).to_contain_text("Sent to Codex as turn")
                self.assertEqual([item["step"] for item in deliveries],
                                 ["verification", "verification", "correction", "correction"])
                self.assertEqual([item["action"] for item in deliveries], ["copy", "send", "copy", "send"])
                self.assertEqual(deliveries[0]["files"], [str(evidence)])
                self.assertIn("Stop there.", (folder / "Handoff.md").read_text(encoding="utf-8"))
                self.assertTrue(all(item["tool"] == "codex" for item in deliveries))
            finally:
                browser.close()


    def test_project_picker_and_details(self):
        # The picker rescans when opened, keeps the last list with a stale
        # notice when the rescan fails, and Details edits every field in one view.
        try:
            from playwright.sync_api import expect, sync_playwright
        except ImportError:
            self.skipTest("Playwright is not installed for the browser check")
        first = self.request("/api/create", {"directory": "One", "name": "One", "description": "Old description", "goals": "Old outcome"})[1]["id"]
        with sync_playwright() as playwright:
            if not Path(playwright.chromium.executable_path).is_file():
                self.skipTest("Playwright's Chromium is not installed for the browser check")
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(self.server.url)
                self.select_project(page, first)
                expect(page.locator("#project")).to_have_value(first)
                # Opening the picker rescans before showing the list.
                second = self.request("/api/create", {"directory": "Two", "name": "Two", "description": "", "goals": ""})[1]["id"]
                page.locator("#project").click()
                expect(page.locator(f'#project option[value="{second}"]')).to_have_count(1)
                expect(page.locator("#project")).to_have_value(first)
                # A failed rescan keeps the last list and says it may be out of date.
                with mock.patch.object(self.server.store, "rescan", side_effect=Exception("scan failed")):
                    page.locator("#project").click()
                expect(page.locator("#status-bar")).to_contain_text("may be out of date")
                expect(page.locator(f'#project option[value="{second}"]')).to_have_count(1)
                expect(page.locator("#project")).to_have_value(first)
                # Details shows and edits every saved field in its one view.
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
        # One-click Send and Copy, the independent Reviewer, binary verdicts,
        # the remembered judgment and sorting, Build's next actions, and
        # Approve the Plan's server-side save.
        try:
            from playwright.sync_api import expect, sync_playwright
        except ImportError:
            self.skipTest("Playwright is not installed for the browser check")
        from ora_vibe_coder.status import review_basis
        project_id = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
        root = self.home / "One"
        specification = root / "Specification.md"
        plan = root / "Plan.md"
        note = root / "Outside note.md"
        note.write_text("Outside context for the Plan.\n", encoding="utf-8")
        def ready(peer, **kwargs):
            return {"peer": peer, "ready": True, "work": "supported", "authentication": "confirmed", "warnings": []}

        def record(number, entries):
            turn = f"{number:04d}-20260101-120000"
            messages = root / ".vibe" / turn / "session" / "messages"
            messages.mkdir(parents=True)
            for sequence, (suffix, headers, body) in enumerate(entries, 1):
                (messages / f"{sequence:04d}-{suffix}.md").write_text(
                    f"# Message {sequence:04d}\n{headers}\n## Body\n\n{body}", encoding="utf-8")
            return turn

        def saved_sorting(number, stage, document, finding, legacy=False):
            key = review_basis(document) if legacy else project_module.findings_key(document, stage)
            findings = document if stage == "verification" else conversation.section_body(document, "Current review") or document
            return record(number, [
                ("initiator-record", "", conversation.aux_note_body("sorting", stage, "codex", {"Key": key},
                    conversation.sorting_request(stage, document, findings))),
                ("initiator-record", "", conversation.aux_outcome_body("sorting", stage, "codex", {"Key": key},
                    "answered", "", {"ai": [finding], "user": ["Choose the example behavior."]})),
            ])

        def accepted_turn(number, updated_document=None):
            def start(_registry, _project, tool, stage, text, images, *args, **kwargs):
                if updated_document is not None:
                    path, document = updated_document
                    path.write_text(document, encoding="utf-8")
                turn = record(number, [
                    ("initiator-record", "", conversation.user_note_body(stage, tool, text, [])),
                    ("initiator-to-peer", "Note-Ref: 0001\n", "Example request."),
                    ("peer-to-initiator", "Answers: 0002\n", "Example reply."),
                    ("initiator-record", "", conversation.outcome_note_body(stage, "finished", "no-change", "", "", "")),
                ])
                handle = mock.Mock(turn=turn, retained_images=[])
                handle.snapshot.return_value = {"project": str(root), "turn": turn, "stage": stage,
                                                "state": "finished", "elapsed_seconds": 0}
                return handle
            return start

        with mock.patch("ora_vibe_coder.conversation.bridge_check", side_effect=ready), \
                mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), \
                mock.patch("ora_vibe_coder.conversation.start_aux", side_effect=ValueError("comparison unavailable in this fixture")), sync_playwright() as playwright:
            if not Path(playwright.chromium.executable_path).is_file():
                self.skipTest("Playwright's Chromium is not installed for the browser check")
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(permissions=["clipboard-read", "clipboard-write"])
            try:
                page = context.new_page()
                page.goto(self.server.url)
                page.evaluate("() => { window.clipboardText = ''; navigator.clipboard.writeText = text => { window.clipboardText = text; return Promise.resolve(); }; }")
                self.select_project(page, project_id)
                page.wait_for_function("() => pollTimer !== null && conversationLoaded")
                page.locator("#destination").select_option(label="Codex")
                # The step-5 Reviewer starts at the step-3 tool and then stays
                # independent: changing either changes only itself.
                expect(page.locator("#readiness")).to_contain_text("Codex", timeout=10000)
                page.locator("#review-step").evaluate("element => element.open = true")
                expect(page.locator("#step-reviewer")).to_have_value("codex")
                page.locator("#destination").select_option(label="Claude Code")
                expect(page.locator("#step-reviewer")).to_have_value("codex")
                page.locator("#step-reviewer").select_option("claude")
                page.locator("#destination").select_option(label="Codex")
                expect(page.locator("#step-reviewer")).to_have_value("claude")

                # No assessment means NOT REVIEWED, never a failure; an
                # untouched template is NOT STARTED, its own distinct state.
                expect(page.locator("#assessment")).to_have_text("NOT STARTED")
                specification.write_text("# One — Specification\n\nRequirements: Preserve all records.\n", encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("NOT REVIEWED")

                # One-click Create Plan: unsent text and files are included once
                # and cleared only after the server confirms the turn.
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
                    route.fulfill(json={"turn": f"turn-{len(sends)}", "operation": {"turn": f"turn-{len(sends)}", "state": "finished", "elapsed_seconds": 0}, "images": [], "path": str(root / "Handoff.md")})
                page.route("**/api/deliver", deliver)
                # The ordinary operation poll can observe an optional meaning
                # comparison. It leaves both the composer and next stage
                # available; the registry safely retires it upon admission.
                page.evaluate("operation => updateOperation(operation)", {
                    "project": str(root), "turn": "meaning-comparison", "stage": "materiality-specification",
                    "state": "running", "elapsed_seconds": 1, "last_contact_seconds": 0})
                expect(page.locator("#send")).to_be_enabled()
                expect(page.locator("#transition")).to_be_enabled()
                page.locator("#transition").click()
                expect(page.locator("#message")).to_have_value("")
                expect(page.locator("#status-bar")).to_contain_text("Sent to Codex as turn turn-1")
                self.assertEqual(sends[0]["step"], "create-plan")
                self.assertEqual(sends[0]["text"], "Plan around the storage layer.")
                self.assertEqual(sends[0]["files"], [str(note)])
                # A failed delivery keeps the input and the previous saved request.
                page.route("**/api/deliver", lambda route: route.fulfill(status=500, content_type="application/json", body='{"error":"save failed"}'))
                page.locator("#message").fill("Second attempt text.")
                page.locator("#transition").click()
                expect(page.locator("#status-bar")).to_contain_text("save failed")
                expect(page.locator("#message")).to_have_value("Second attempt text.")
                page.unroute("**/api/deliver")
                page.route("**/api/deliver", deliver)

                # A copy saves the complete request — the unsent text and files
                # included once — and names pictures it cannot carry.
                page.evaluate("() => attachments.push({name: 'shot.png', data: 'aGk=', url: 'blob:x'})")
                with page.expect_response(lambda response: "/api/deliver" in response.url) as copied_response:
                    page.locator("#copy-request").click()
                self.assertEqual(copied_response.value.status, 200, copied_response.value.text())
                expect(page.locator("#status-bar")).to_contain_text("copied and saved")
                expect(page.locator("#status-bar")).to_contain_text("Pictures are not carried by a copy: shot.png")
                expect(page.locator("#message")).to_have_value("")
                handoff = (root / "Handoff.md").read_text(encoding="utf-8")
                self.assertIn("Second attempt text.", handoff)
                # The saved/copied packet itself names the picture it cannot
                # carry, so the recipient sees the limitation too — not only
                # this app's status bar.
                self.assertIn("Pictures not carried by this request: shot.png.", handoff)
                # The note travelled with the send and was consumed; the copy
                # carries this delivery's own unsent text, not an attachment
                # from the earlier turn.
                self.assertNotIn("Outside context for the Plan.", handoff)
                self.assertEqual(page.evaluate("() => window.clipboardText"), handoff)
                self.assertIn("status: APPROVED", specification.read_text())
                self.assertNotIn("review: PASSED", specification.read_text())

                # PASSED / NOT PASSED from the saved record; an unclear record
                # gets one remembered judgment, and a failed call a reading error.
                reviewed = "# One — Specification\n\n## Description\n\nBehavior.\n\n## Current review\n\nStage: Specification\nVerdict: COMPLETE\nBasis: {basis}\nBasis format: content-v2\n"
                specification.write_text(reviewed.replace("{basis}", review_basis(reviewed)), encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("PASSED")
                specification.write_text(reviewed.replace("Verdict: COMPLETE", "Verdict: INCOMPLETE").replace("{basis}", review_basis(reviewed.replace("Verdict: COMPLETE", "Verdict: INCOMPLETE"))).replace("Behavior.", "Behavior, changed."), encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("NOT PASSED")
                unclear = "# One — Specification\n\n## Description\n\nBehavior.\n\n## Current review\n\nStage: Specification\nVerdict: COMPLETE and also INCOMPLETE in the summary.\nBasis: {basis}\nBasis format: content-v2\n"
                unclear = unclear.replace("{basis}", review_basis(unclear))
                specification.write_text(unclear, encoding="utf-8")
                with mock.patch("ora_vibe_coder.conversation.bridge_call",
                                side_effect=Exception("bridge unavailable")):
                    page.locator("#refresh").click()
                    expect(page.locator("#assessment")).to_have_text("REPORT ERROR")
                    self.assertIn("conclusion", (page.locator("#assessment").get_attribute("title") or "").lower())

                # Approve the Plan is greyed until COMPLETE, then saves
                # Status: APPROVED preserving the rest of the document and review.
                plan.write_text("# One — Plan\n\nStatus: AWAITING APPROVAL\n\n## Approach\n\nSteps.\n\n## Current review\n\nStage: Plan\nVerdict: INCOMPLETE\nBasis: {basis}\nBasis format: content-v2\n", encoding="utf-8")
                plan_text = plan.read_text(encoding="utf-8").replace("{basis}", review_basis(plan.read_text(encoding="utf-8")))
                plan.write_text(plan_text, encoding="utf-8")
                page.locator(".rail[data-stage=plan]").click()
                expect(page.locator("#approve-plan")).to_be_enabled()
                expect(page.locator("#assessment")).to_have_text("NOT PASSED")
                with mock.patch("ora_vibe_coder.project.atomic_write", side_effect=OSError("disk full")):
                    page.locator("#approve-plan").click()
                    expect(page.locator("#status-bar"), "the failed save reports and keeps the prior file").to_contain_text("disk full")
                self.assertIn("Status: AWAITING APPROVAL", plan.read_text(encoding="utf-8"))
                page.locator("#approve-plan").click()
                expect(page.locator("#status-bar")).to_contain_text("status: APPROVED saved")
                saved_plan = plan.read_text(encoding="utf-8")
                self.assertIn("status: APPROVED", saved_plan)
                self.assertIn("## Approach\n\nSteps.", saved_plan)
                self.assertIn("Verdict: INCOMPLETE", saved_plan)
                expect(page.locator("#approve-plan")).to_be_disabled()
                expect(page.locator("#assessment")).to_have_text("NOT PASSED")
                expect(page.locator("#reader")).to_contain_text("status: APPROVED")

                # Build's verdicts and next actions: NOT PASSED offers Request
                # repairs; REVIEW INCOMPLETE offers to finish or rerun; a legacy
                # combined label shows as REVIEW INCOMPLETE.
                page.locator(".rail[data-stage=build]").click()
                expect(page.locator("#assessment")).to_have_text("NOT VERIFIED")
                (root / "One — Programming Result.md").write_text("# Programming Result\n\nSummary: Implemented record export.\n", encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#result-status")).to_have_text("VERDICT MISSING")
                (root / "One — Programming Result.md").write_text("# Programming Result\n\nStatus: COMPLETE\n\nDelivered.\n", encoding="utf-8")
                (root / "One — Verification Report.md").write_text("# Verification Report\n\nVerdict: NOT PASSED\n\n- The login check fails.\n", encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("NOT PASSED")
                expect(page.locator("#next-step-title")).to_have_text("Correct the implementation")
                # A sorting that cannot run shows as a failed sorting with Retry —
                # never as a verdict, a repair or an invented question.
                expect(page.locator("#repairs-box")).to_be_visible()
                expect(page.locator("#repairs-box")).to_contain_text("Findings sorting failed")
                expect(page.locator("#repairs-box button", has_text="Retry sorting")).to_be_enabled()
                # A completed NOT PASSED keeps the correction direction.
                expect(page.locator("#transition")).to_have_text("Request repairs")
                page.locator("#next-step").evaluate("element => element.open = true")
                page.locator("#transition").click()
                expect(page.locator("#build-action-dialog")).to_be_visible()
                expect(page.locator("#build-action-title")).to_have_text("Correct the implementation")
                page.locator("#build-action-cancel").click()
                expect(page.locator("#build-action-dialog")).not_to_be_visible()

                # Reuse the existing sorting record, then preserve the unanswered
                # list on rejection and retire it only after an accepted reply.
                report_path = root / "One — Verification Report.md"
                original_report = report_path.read_text(encoding="utf-8")
                saved_sorting(1, "verification", original_report, "Repair the first example.", legacy=True)
                page.locator("#repairs-box button", has_text="Retry sorting").click()
                expect(page.locator("#repairs-box")).to_contain_text("Repair the first example.")
                expect(page.locator("#repairs-box")).to_contain_text("Needs your input")
                page.evaluate("() => { window.unchangedFinding = document.querySelector('#repairs-box li'); }")
                page.evaluate("() => pollTick()")
                self.assertTrue(page.evaluate("() => unchangedFinding?.isConnected && unchangedFinding === document.querySelector('#repairs-box li')"))
                # Returning to a cached list while another workspace's sorting
                # is pending replaces its loading message with that list.
                page.evaluate("() => { for (const key of sortingState.keys()) if (key.includes(':planning:')) sortingState.delete(key); }")
                pending_sorting = []
                page.route("**/api/sort-findings", lambda route: pending_sorting.append(route))
                try:
                    page.locator(".rail[data-stage=plan]").click()
                    expect(page.locator("#repairs-box")).to_contain_text("Sorting the findings")
                    self.assertTrue(pending_sorting)
                    page.locator(".rail[data-stage=build]").click()
                    expect(page.locator("#repairs-box")).to_contain_text("Repair the first example.")
                finally:
                    for route in pending_sorting:
                        route.fulfill(json={"state": "failed", "reason": "Example sorting unavailable"})
                    page.unroute("**/api/sort-findings")
                operation = {"project": str(root), "turn": "0002-20260101-120000", "stage": "verification",
                             "state": "running", "elapsed_seconds": 1, "last_contact_seconds": 0}
                page.evaluate("operation => updateOperation(operation)", {**operation, "project": str(self.home / "Other")})
                expect(page.locator("#repairs-box")).to_be_visible()
                page.evaluate("operation => updateOperation(operation)", operation)
                expect(page.locator("#repairs-box")).to_be_hidden()
                page.evaluate("operation => updateOperation(operation)", {**operation, "state": "failed", "reason": "Example turn failed"})
                expect(page.locator("#repairs-box")).to_contain_text("Repair the first example.")
                page.locator("#build-reply-stage").select_option("verification")
                page.locator("#message").fill("Use the example behavior and continue.")
                before_images = page.evaluate("() => attachments.map(item => item.name)")
                page.route("**/api/converse", lambda route: route.fulfill(status=409, json={"error": "Example submission rejected"}))
                page.locator("#send").click()
                expect(page.locator("#status-bar")).to_contain_text("Example submission rejected")
                expect(page.locator("#repairs-box")).to_contain_text("Repair the first example.")
                expect(page.locator("#message")).to_have_value("Use the example behavior and continue.")
                self.assertEqual(page.evaluate("() => attachments.map(item => item.name)"), before_images)
                page.unroute("**/api/converse")
                with mock.patch("ora_vibe_coder.conversation.start_turn", side_effect=accepted_turn(2)):
                    page.locator("#send").click()
                    expect(page.locator("#repairs-box")).to_be_hidden()
                    expect(page.locator("#message")).to_have_value("")
                page.locator("#refresh").click()
                page.evaluate("() => pollTick()")
                expect(page.locator("#repairs-box")).to_be_hidden()
                self.assertEqual(report_path.read_text(encoding="utf-8"), original_report)
                expect(page.locator("#assessment")).to_have_text("NOT PASSED")
                page.reload()
                self.select_project(page, project_id)
                page.wait_for_function("() => pollTimer !== null && conversationLoaded")
                page.locator(".rail[data-stage=build]").click()
                page.locator("#destination").select_option(label="Codex")
                page.locator("#next-step").evaluate("element => element.open = true")
                page.wait_for_function("() => [...sortingState.values()].some(result => result.turn === '0001-20260101-120000')")
                expect(page.locator("#repairs-box")).to_be_hidden()

                # The same filename and verdict with fresh findings must show
                # its new list. Sending the verification step retires that list
                # through the same path as an ordinary reply.
                fresh_report = original_report + "\n## Current review\n\n- The next example needs adjustment.\n"
                self.assertEqual(review_basis(original_report), review_basis(fresh_report))
                report_path.write_text(fresh_report, encoding="utf-8")
                saved_sorting(3, "verification", fresh_report, "Repair the next example.")
                page.locator("#refresh").click()
                expect(page.locator("#repairs-box")).to_contain_text("Repair the next example.")
                expect(page.locator("#repairs-box")).not_to_contain_text("Repair the first example.")
                page.unroute("**/api/deliver")
                with mock.patch("ora_vibe_coder.conversation.start_turn", side_effect=accepted_turn(4)) as submitted:
                    page.evaluate("() => deliverStep('verification', 'send')")
                    submitted.assert_called_once()
                expect(page.locator("#repairs-box")).to_be_hidden()
                self.assertEqual(report_path.read_text(encoding="utf-8"), fresh_report)
                expect(page.locator("#assessment")).to_have_text("NOT PASSED")
                (root / "One — Verification Report.md").write_text("# Verification Report\n\nVerdict: NOT PASSED — REVIEW INCOMPLETE\n\n- A finding and an unfinished check.\n", encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("INCOMPLETE")
                # An unfinished review directs no source repairs: step 7 offers
                # finishing or rerunning the verification instead, and no
                # findings sorting runs for it.
                expect(page.locator("#next-step-title")).to_have_text("Finish or rerun the verification")
                expect(page.locator("#transition")).to_have_text("Finish verification")
                expect(page.locator("#repairs-box")).to_be_hidden()
                page.locator("#transition").click()
                expect(page.locator("#build-action-dialog")).to_be_visible()
                expect(page.locator("#build-action-title")).to_have_text("Independently verify the implementation")
                page.locator("#build-action-cancel").click()
                expect(page.locator("#build-action-dialog")).not_to_be_visible()
                (root / "One — Verification Report.md").write_text("# Verification Report\n\nVerdict: PASSED\n\nAll checks passed.\n", encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("PASSED")
                # The canonical states use the same rendered labels and colors
                # as legacy results, with distinct empty/error displays.
                report_path = root / "One — Verification Report.md"
                for contents, label in (
                    ("# Verification Report\n\n## Findings\n", "NOT STARTED"),
                    ("---\nstatus:\n---\n# Verification Report\n\n## Findings\n", "NOT STARTED"),
                    ("---\nstatus: null\n---\n# Verification Report\n\n## Findings\n", "NOT STARTED"),
                    ("# Verification Report\n\nThe evidence could not be assessed.\n", "VERDICT MISSING"),
                    ("# Verification Report\n\nSummary: Checked the record export.\n", "VERDICT MISSING"),
                    ("---\nstatus:\n---\n# Verification Report\n\nRequired evidence is missing.\n", "VERDICT MISSING"),
                    ("---\nstatus: ~\n---\n# Verification Report\n\nRequired evidence is missing.\n", "VERDICT MISSING"),
                    ('---\nstatus: "null"\n---\n# Verification Report\n', "REPORT ERROR"),
                    ("---\nstatus:\nstatus:\n---\n# Verification Report\n", "REPORT ERROR"),
                    ("---\nstatus:\n  verdict: PASSED\n---\n# Verification Report\n", "REPORT ERROR"),
                    ("---\nstatus: UNKNOWN\n---\n# Verification Report\n", "REPORT ERROR"),
                    ("---\nstatus: PASSED\nstatus: PASSED\n---\n# Verification Report\n", "REPORT ERROR"),
                    ("---\nstatus: PASSED\n---\n# Verification Report\n\n## Current outcome\nVerdict: NOT PASSED\n", "REPORT ERROR"),
                    ("---\nstatus: PASSED\n---\n# Verification Report\n\n## Current outcome\nVerdict: PASSED — but the required checks failed.\n", "REPORT ERROR"),
                    ("---\nstatus: INCOMPLETE\n---\n# Verification Report\n\nRequired evidence is unavailable.\n", "INCOMPLETE"),
                ):
                    report_path.write_text(contents, encoding="utf-8")
                    page.locator("#refresh").click()
                    expect(page.locator("#assessment")).to_have_text(label)
                    if label != "NOT STARTED":
                        expect(page.locator("#assessment")).to_have_class("assessment working")
                report_path.write_bytes(b"\x00unreadable")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("COULD NOT READ")
                expect(page.locator("#assessment-note")).to_contain_text("Binary content")
                report_path.write_text("---\nstatus: INCOMPLETE\n---\n# Verification Report\n\nRequired evidence is unavailable.\n", encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("INCOMPLETE")

                # Specification and Plan repair buttons share the same retirement
                # rule. A changed review alone supplies fresh findings even when
                # the assessed document's substantive basis stays the same.
                for offset, (stage, rail, path, title) in enumerate((
                    ("specification", "specification", specification, "Specification"),
                    ("planning", "plan", plan, "Plan"),
                )):
                    document = f"# One — {title}\n\n## Content\n\nExample behavior.\n\n## Current review\n\nStage: {title}\nVerdict: INCOMPLETE\nBasis: {{basis}}\nBasis format: content-v2\n\n- Repair the example.\n"
                    document = document.replace("{basis}", review_basis(document))
                    path.write_text(document, encoding="utf-8")
                    number = 5 + offset * 3
                    saved_sorting(number, stage, document, f"Repair the {title} example.", legacy=True)
                    page.locator(f".rail[data-stage={rail}]").click()
                    page.locator("#refresh").click()
                    expect(page.locator("#repairs-box")).to_contain_text(f"Repair the {title} example.")
                    document = document.replace("Example behavior.", "Adjusted example behavior.")
                    with mock.patch("ora_vibe_coder.conversation.start_turn", side_effect=accepted_turn(number + 1, (path, document))):
                        page.locator("#repairs-box button", has_text="Request repairs").click()
                        expect(page.locator("#repairs-box")).to_be_hidden()
                    page.locator("#refresh").click()
                    expect(page.locator("#repairs-box")).to_be_hidden()
                    self.assertEqual(path.read_text(encoding="utf-8"), document)
                    page.reload()
                    self.select_project(page, project_id)
                    page.wait_for_function("() => pollTimer !== null && conversationLoaded")
                    page.locator(f".rail[data-stage={rail}]").click()
                    page.locator("#destination").select_option(label="Codex")
                    page.wait_for_function("turn => [...sortingState.values()].some(result => result.turn === turn)",
                                           arg=f"{number:04d}-20260101-120000")
                    expect(page.locator("#repairs-box")).to_be_hidden()
                    changed = document.replace("- Repair the example.", "- Repair the later example.")
                    self.assertEqual(review_basis(document), review_basis(changed))
                    path.write_text(changed, encoding="utf-8")
                    saved_sorting(number + 2, stage, changed, f"Repair the later {title} example.")
                    page.locator("#refresh").click()
                    expect(page.locator("#repairs-box")).to_contain_text(f"Repair the later {title} example.")
            finally:
                browser.close()

    def test_saved_role_defaults_restore_and_survive_a_warning_only_save(self):
        from playwright.sync_api import expect, sync_playwright
        settings = Settings(self.home / "role-settings.json")
        server = LocalServer(self.home, settings=settings)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01})
        thread.start()
        def close():
            server.shutdown(); thread.join(timeout=2); server.server_close()
        self.addCleanup(close)
        def request(path, body):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            connection.request("POST", path, json.dumps(body), headers={"Content-Type": "application/json", "X-Ora-Token": server.token})
            response = connection.getresponse(); data = json.loads(response.read()); connection.close()
            self.assertEqual(response.status, 200, data)
            return data
        created = request("/api/create", {"directory": "SampleOne", "name": "Sample One", "description": "A sample tool", "goals": "A working sample"})
        other = request("/api/create", {"directory": "SampleTwo", "name": "Sample Two", "description": "Another sample", "goals": "A working sample"})
        request("/api/settings", {"role_defaults": {
            "specification": {"tool": "codex", "model": "configured-model", "effort": "high"},
            "planning": {"tool": "claude", "model": "saved-unavailable-model", "effort": "high"},
            "implementation": {"tool": "codex", "model": "configured-model", "effort": "high"},
            "specification_review": {"tool": "claude", "model": "review-model", "effort": "low"},
            "planning_review": {"tool": "codex", "model": "review-model", "effort": "high"},
            "review": {"tool": "hermes", "model": "", "effort": ""},
            "verification": {"tool": "claude", "model": "verification-model", "effort": "low"}}})
        native = {"models": [{"id": "configured-model", "label": "Configured model", "efforts": ["low", "high"], "default_effort": "low"},
                              {"id": "other-model", "label": "Other model", "efforts": ["low"], "default_effort": "low"}],
                  "configured_model": "configured-model", "configured_effort": "xhigh"}
        native_reasons = {
            "codex": "Choices come from Codex native metadata. Use harness default follows its effective configuration; a recommended model is not treated as your configured model.",
            "claude": "Models and effort levels come from Claude Code native initialization, without a model call. It does not report the effective configured model or effort; Use harness default follows those settings.",
            "hermes": "This harness’s headless route cannot accept named model or effort choices through Bridge. Use harness default keeps its own configured choices; saved named choices are preserved.",
        }
        def ready(peer, **kwargs):
            return {"peer": peer, "ready": True, "work": "supported", "authentication": "confirmed", "warnings": []}
        with mock.patch("ora_vibe_coder.conversation.bridge_check", side_effect=ready), \
                mock.patch("ora_vibe_coder.server.model_inventory", side_effect=lambda tool: {**native, "reason": native_reasons[tool]}), \
                mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 1100})
                errors = []; page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(server.url)
                self.select_project(page, created["id"])
                page.wait_for_function("() => pollTimer !== null && lastFiles !== null")
                page.locator("#settings").click()
                expect(page.locator("#settings-panel")).to_be_visible()
                expect(page.locator("#settings-roles .role-row[data-role]")).to_have_count(10)
                self.assertEqual(page.locator('#settings-panel input:not([type="checkbox"])').count(), 0)
                self.assertEqual(page.locator("#interview-panel, #configure-panel, #settings-spending").count(), 0)
                planning = page.locator('#settings-roles .role-row[data-role="planning"]')
                expect(planning.locator(".role-tool")).to_have_value("claude")
                expect(planning.locator(".role-model")).to_have_value("saved-unavailable-model")
                expect(planning.locator(".role-effort")).to_have_value("high")
                expect(page.locator('#settings-roles [data-role="review"] .role-tool')).to_have_value("hermes")
                expect(page.locator('#settings-roles [data-role="specification_second_opinion"] .role-tool')).to_have_value("")
                specification = page.locator('#settings-roles .role-row[data-role="specification"]')
                expect(specification.locator(".role-model option[value='other-model']")).to_have_count(1)
                specification.locator(".role-model").select_option("other-model")
                expect(specification.locator(".role-effort")).to_have_value("")
                self.assertEqual(specification.locator(".role-effort option").all_text_contents(), ["Use harness default (xhigh)", "low — model recommendation"])
                # Every option lives on this first screen, and one save persists them all.
                self.assertEqual(page.locator("#settings-warn").count(), 0)
                page.locator("#settings-best-guess").check()
                page.locator("#settings-hide-advisory").check()
                evidence = os.environ.get("VIBE_CONFIGURATION_EVIDENCE")
                if evidence:
                    Path(evidence).mkdir(parents=True, exist_ok=True)
                # Populate even the optional rows for the layout proof, using the
                # complete native explanations rather than a short placeholder.
                layout_choices = page.locator("#settings-roles .role-row[data-role]").evaluate_all("rows => rows.map(row => ({role: row.dataset.role, tool: row.querySelector('.role-tool').value}))")
                for choice in layout_choices:
                    row = page.locator(f'#settings-roles [data-role="{choice["role"]}"]')
                    if not choice["tool"]:
                        row.locator(".role-tool").select_option("claude" if choice["role"].endswith("second_opinion") else "codex")
                    expect(row.locator(".role-origin")).to_have_text(native_reasons[row.locator(".role-tool").input_value()])
                    row.locator(".role-model").select_option("")
                    row.locator(".role-effort").select_option("")
                layout_evidence = []
                for theme, width, height in (("light", 1440, 1100), ("dark", 1440, 1100),
                                             ("light", 1868, 1200), ("dark", 1868, 1200),
                                             ("light", 420, 900), ("dark", 420, 900)):
                    page.set_viewport_size({"width": width, "height": height})
                    page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
                    panel = page.locator("#settings-panel")
                    panel.evaluate("element => element.scrollTop = 0")
                    metrics = panel.evaluate("""element => {
                        const rect = element.getBoundingClientRect();
                        const rows = [...element.querySelectorAll('.role-row[data-role]')];
                        const first = rows[0], role = first.querySelector('label').getBoundingClientRect();
                        const effort = first.querySelector('.role-effort').getBoundingClientRect();
                        const canvas = document.createElement('canvas'), context = canvas.getContext('2d');
                        return {width: innerWidth, height: innerHeight, scrollHeight: element.scrollHeight,
                            clientHeight: element.clientHeight, scrollWidth: element.scrollWidth, clientWidth: element.clientWidth,
                            top: rect.top, bottom: rect.bottom, roleWidth: role.width, effortWidth: effort.width,
                            allRowsInside: rows.every(row => row.getBoundingClientRect().top >= rect.top && row.getBoundingClientRect().bottom <= rect.bottom),
                            actionsInside: [...element.querySelectorAll('.editor-actions button')].every(button => button.getBoundingClientRect().bottom <= rect.bottom),
                            defaultLabelsFit: [...element.querySelectorAll('.role-model, .role-effort')].every(select => {
                                const style = getComputedStyle(select); context.font = style.font;
                                return context.measureText(select.selectedOptions[0].text).width + parseFloat(style.paddingLeft) + parseFloat(style.paddingRight) + 24 <= select.clientWidth;
                            }),
                            optionsSingleLine: [...element.querySelectorAll('.configuration-option')].every(option => {
                                const spans = [...option.querySelectorAll('span')];
                                return spans.every(span => span.getBoundingClientRect().height <= parseFloat(getComputedStyle(span).lineHeight) + 1)
                                    && Math.abs(spans[0].getBoundingClientRect().bottom - spans[1].getBoundingClientRect().bottom) < 5;
                            }),
                            dividers: rows.filter(row => parseFloat(getComputedStyle(row).borderBottomWidth) > 0).map(row => ({role: row.dataset.role, width: getComputedStyle(row).borderBottomWidth, style: getComputedStyle(row).borderBottomStyle})),
                            descriptions: rows.map(row => row.querySelector('.role-origin').textContent)};
                    }""")
                    layout_evidence.append({"theme": theme, **metrics})
                    if evidence:
                        (Path(evidence) / "configuration-layout.json").write_text(json.dumps(layout_evidence, indent=2), encoding="utf-8")
                        page.screenshot(path=str(Path(evidence) / f"configuration-{theme}-{width}-top.png"))
                    self.assertLessEqual(metrics["scrollWidth"], metrics["clientWidth"], metrics)
                    self.assertGreaterEqual(metrics["top"], 0, metrics)
                    self.assertLessEqual(metrics["bottom"], height, metrics)
                    self.assertEqual(metrics["dividers"], [{"role": "specification_second_opinion", "width": "1px", "style": "solid"}, {"role": "planning_second_opinion", "width": "1px", "style": "solid"}])
                    if width > 980:
                        self.assertLessEqual(metrics["scrollHeight"], metrics["clientHeight"], metrics)
                        self.assertTrue(metrics["allRowsInside"] and metrics["actionsInside"], metrics)
                        self.assertLessEqual(metrics["roleWidth"], 200, metrics)
                        self.assertGreaterEqual(metrics["effortWidth"], 245, metrics)
                        self.assertTrue(metrics["defaultLabelsFit"], metrics)
                        self.assertTrue(metrics["optionsSingleLine"], metrics)
                    else:
                        expect(page.get_by_label("Specification harness", exact=True)).to_be_visible()
                        page.locator("#settings-close").scroll_into_view_if_needed()
                        page.locator("#settings-close").focus()
                        expect(page.locator("#settings-close")).to_be_focused()
                        if evidence: page.screenshot(path=str(Path(evidence) / f"configuration-{theme}-{width}-options.png"))
                # Discard the unsaved layout fixture, then make the original
                # changes for the persistence and run-only behavior checks.
                page.locator("#settings-close").click()
                page.set_viewport_size({"width": 1440, "height": 1100})
                page.locator("#settings").click()
                specification.locator(".role-model").select_option("other-model")
                page.locator("#settings-best-guess").check()
                page.locator("#settings-hide-advisory").check()
                page.locator("#settings-save").click()
                expect(page.locator("#settings-panel")).to_be_hidden()
                saved = request("/api/settings", {})
                self.assertFalse(saved["warn_skip_review"])
                self.assertTrue(saved["best_guess"])
                self.assertTrue(saved["hide_advisory"])
                self.assertEqual(saved["role_defaults"]["specification"], {"tool": "codex", "model": "other-model", "effort": ""})
                handle = mock.Mock(turn="native-default", retained_images=[])
                handle.snapshot.return_value = {"state": "running"}
                with mock.patch("ora_vibe_coder.conversation.start_turn", return_value=handle) as turn:
                    request("/api/converse", {"id": created["id"], "tool": "codex", "stage": "specification", "text": "Work on the sample.", "images": []})
                    self.assertEqual(turn.call_args.kwargs["model"], "other-model")
                    self.assertEqual(turn.call_args.kwargs["effort"], "")
                self.assertEqual(saved["role_defaults"]["planning"], {"tool": "claude", "model": "saved-unavailable-model", "effort": "high"})
                # Recreate the settings reader, reload the app, then open another project.
                server.settings = Settings(settings.path)
                page.reload()
                self.select_project(page, other["id"])
                page.wait_for_function("() => project !== null && workspace !== ''")
                expect(page.locator("#destination")).to_have_value("Codex")
                expect(page.locator("#step-reviewer")).to_have_value("claude")
                expect(page.locator("#transition")).to_have_text("Send to Claude Code")
                page.locator('[data-stage="plan"]').click()
                expect(page.locator("#destination")).to_have_value("Claude Code")
                expect(page.locator("#step-reviewer")).to_have_value("codex")
                expect(page.locator("#transition")).to_have_text("Send to Codex")
                page.locator('[data-stage="build"]').click()
                page.locator("#build-reply-stage").select_option("verification")
                expect(page.locator("#destination")).to_have_value("Claude Code")
                page.locator("#destination").select_option("Codex")
                expect(page.locator("#destination")).to_have_value("Codex")
                page.locator("#configure-path").click()
                expect(page.locator("#settings-best-guess")).to_be_checked()
                verification = page.locator('#settings-roles [data-role="verification"]')
                verification.locator(".role-tool").select_option("codex")
                expect(verification.locator(".role-model")).to_have_value("")
                expect(verification.locator(".role-effort")).to_have_value("")
                page.locator("#configure-save").click()
                page.wait_for_function("() => pendingRunConfig?.roles?.verification?.tool === 'codex'")
                expect(page.locator("#destination")).to_have_value("Codex")
                page.locator('[data-stage="plan"]').click()
                page.locator('[data-stage="build"]').click()
                page.locator("#build-reply-stage").select_option("verification")
                expect(page.locator("#destination")).to_have_value("Codex")
                self.assertEqual(request("/api/settings", {})["role_defaults"]["verification"]["tool"], "claude")
                page.locator("#configure-path").click()
                page.locator("#configure-clear").click()
                page.wait_for_function("() => pendingRunConfig && Object.keys(pendingRunConfig.roles).length === 0")
                self.assertEqual(request("/api/settings", {})["role_defaults"], saved["role_defaults"])
                page.locator("#configure-path").click()
                page.locator('#settings-roles [data-role="verification"] .role-tool').select_option("codex")
                page.locator("#configure-save").click()
                self.select_project(page, created["id"])
                page.wait_for_function("() => project !== null && workspace !== '' && pendingRunConfig === null")
                # A run captures its defaults; later global saves must not
                # repaint that run as though its future assignments changed.
                from ora_vibe_coder.run import RunDriver
                active_project = server.store.projects[created["id"]]
                driver = RunDriver(server.conversation, active_project, "build", "Build the sample.",
                                   {"roles": {}, "best_guess": False, "hide_advisory": False},
                                   settings.read()["role_defaults"], "codex")
                driver.run = "0001-20261021-000000"
                driver.state = "paused-failure"
                server.runs.by_project[str(active_project.root)] = driver
                page.evaluate("() => stopPolling()")
                page.evaluate("() => pollTick()")
                page.wait_for_function("() => runActive?.run === '0001-20261021-000000'")
                page.locator("#settings").click()
                page.locator('#settings-roles [data-role="verification"] .role-tool').select_option("codex")
                page.locator("#settings-hide-advisory").uncheck()
                page.locator("#settings-save").click()
                expect(page.locator("#settings-panel")).to_be_hidden()
                globals_after = request("/api/settings", {})
                self.assertEqual(globals_after["role_defaults"]["verification"]["tool"], "codex")
                self.assertEqual(driver.assignment("verification")[:3], ("claude", "verification-model", "low"))
                page.locator("#configure-path").click()
                expect(page.locator('#settings-roles [data-role="verification"] .role-tool')).to_have_value("claude")
                expect(page.locator('#settings-roles [data-role="verification"] .role-model')).to_have_value("verification-model")
                page.locator("#settings-best-guess").check()
                with mock.patch("ora_vibe_coder.run._record_run_note"):
                    page.locator("#configure-save").click()
                    expect(page.locator("#settings-panel")).to_be_hidden()
                self.assertEqual(driver.assignment("verification")[:3], ("claude", "verification-model", "low"))
                self.assertTrue(driver.config["best_guess"])
                self.assertEqual(request("/api/settings", {}), globals_after)
                page.locator("#settings").click()
                expect(page.locator('#settings-roles [data-role="verification"] .role-tool')).to_have_value("codex")
                page.locator("#settings-close").click()
                server.runs.by_project.pop(str(active_project.root))
                page.evaluate("() => updateRunState({active: null})")
                # The single warning checkbox is a real run-only override.
                # Global warnings stay enabled while this run suppresses them.
                page.locator("#configure-path").click()
                expect(page.locator("#settings-hide-advisory")).not_to_be_checked()
                page.locator("#settings-hide-advisory").check()
                page.locator("#configure-save").click()
                expect(page.locator("#settings-panel")).to_be_hidden()
                page.locator("#message").fill("Build the sample.")
                with mock.patch.object(server.runs, "start", return_value=driver) as start:
                    page.locator("#run-completion").click()
                    page.wait_for_function("() => runActive?.run === '0001-20261021-000000'")
                    self.assertTrue(start.call_args.args[4]["hide_advisory"])
                    expect(page.locator("#run-warning")).not_to_be_visible()
                self.assertEqual(request("/api/settings", {}), globals_after)
                # A legacy saved 'do not warn' choice remains effective, and
                # a deliberate one-run unchecked choice can still show it.
                request("/api/settings", {"warn_skip_review": False})
                page.evaluate("() => { updateRunState({active: null}); pendingRunConfig = null; }")
                page.reload()
                self.select_project(page, created["id"])
                page.wait_for_function("() => pollTimer !== null && lastFiles !== null")
                page.locator("#configure-path").click()
                expect(page.locator("#settings-hide-advisory")).to_be_checked()
                page.locator("#settings-hide-advisory").uncheck()
                page.locator("#configure-save").click()
                page.locator("#message").fill("Build the sample.")
                page.locator("#run-completion").click()
                expect(page.locator("#run-warning")).to_be_visible()
                page.locator("#run-warning-back").click()
                self.assertFalse(request("/api/settings", {})["warn_skip_review"])
                self.assertFalse(request("/api/settings", {})["hide_advisory"])
                self.assertEqual(errors, [])
            finally:
                browser.close()

    def test_header_stop_run_uses_the_run_stop_operation(self):
        # While a run is active the header's own button reads Stop Run and
        # uses the same stop operation as the banner's: the active step is
        # cancelled and the run is recorded unfinished, never left running.
        try:
            from playwright.sync_api import expect, sync_playwright
        except ImportError:
            self.skipTest("Playwright is not installed for the browser check")
        project_id = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
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
                bar = page.locator("#status-bar")
                appearance = """element => {
                    const style = getComputedStyle(element);
                    return [style.backgroundColor, style.borderTopColor, style.borderTopWidth,
                            style.fontSize, style.fontWeight, element.getBoundingClientRect().height,
                            element.closest('.status-row').getBoundingClientRect().height];
                }"""
                idle = bar.evaluate(appearance)
                active = {"run": "0001-20261017-000000", "state": "running", "step": "specification",
                          "entry": "specification", "reason": "", "questions": [], "observation": "",
                          "no_progress": 0, "best_verified": False, "verdicts": [], "model": "",
                          "reported_model": "", "elapsed_seconds": 4, "last_contact_seconds": 1, "config": {}}
                page.evaluate("report => updateRunState(report)", {"active": active, "last": None})
                expect(page.locator("#run-completion")).to_have_text("Stop Run")
                page.evaluate("() => status('Run to Completion started.')")
                active_style = bar.evaluate(appearance)
                self.assertNotEqual(active_style[0], idle[0])
                self.assertEqual(active_style[-2:], idle[-2:])
                # The run stays highlighted between steps, including when
                # repeated polls still carry the previous completed turn.
                completed = {"turn": "run-turn", "state": "finished", "elapsed_seconds": 4}
                page.evaluate("operation => updateOperation(operation)", completed)
                self.assertEqual(bar.evaluate(appearance), active_style)
                page.evaluate("operation => updateOperation(operation)", completed)
                self.assertEqual(bar.evaluate(appearance), active_style)
                page.evaluate("() => updateOperation(null)")
                self.assertEqual(bar.evaluate(appearance), active_style)
                for state in ["paused-question", "paused-failure"]:
                    page.evaluate("report => updateRunState(report)", {"active": dict(active, state=state)})
                    self.assertEqual(bar.evaluate(appearance), idle)
                    if state == "paused-failure":
                        page.route("**/api/run-resume", lambda route: route.fulfill(json={"run": active}))
                        page.locator("#run-banner").get_by_role("button", name="Resume run").click()
                        expect(bar).to_have_text("Run resumed.")
                    else:
                        # Start/answer acknowledgements use a direct snapshot;
                        # polls use the report containing active and last.
                        page.evaluate("report => updateRunState(report)", active)
                    self.assertEqual(bar.evaluate(appearance), active_style)
                page.evaluate("operation => updateOperation(operation)", {
                    "turn": "run-turn", "state": "failed", "reason": "The tool refused the step."})
                self.assertEqual(bar.evaluate(appearance)[0], idle[0])
                expect(bar).to_contain_text("The turn failed")
                page.evaluate("report => updateRunState(report)", {"active": None,
                    "last": {"run": active["run"], "state": "complete", "steps": [{"turn": "run-turn"}]}})
                page.evaluate("operation => updateOperation(operation)", completed)
                self.assertEqual(bar.evaluate(appearance), idle)
                page.evaluate("report => updateRunState(report)", {"active": active})
                page.evaluate("operation => updateOperation(operation)", {
                    "turn": "run-turn", "state": "running", "elapsed_seconds": 4, "last_contact_seconds": 1})
                self.assertEqual(bar.evaluate(appearance), active_style)
                page.evaluate("() => lostContact()")
                self.assertEqual(bar.evaluate(appearance)[0], idle[0])
                page.evaluate("() => { contactRestored(); updateOperation(lastOperation); }")
                self.assertEqual(bar.evaluate(appearance), active_style)
                stopped = []

                def run_stop(route):
                    stopped.append(route.request.post_data_json)
                    route.fulfill(json={"run": {"active": None,
                                                "last": {"run": "0001-20261017-000000", "state": "unfinished",
                                                         "reason": "Stopped by the user.", "steps": [{"turn": "run-turn"}]}}})

                page.route("**/api/run-stop", run_stop)
                page.locator("#run-completion").click()
                self.assertEqual(stopped, [{"id": project_id}])
                expect(page.locator("#status-bar")).to_contain_text(
                    "Run stopped: recorded unfinished. Files already changed remain; nothing replays by itself.")
                expect(page.locator("#run-banner")).to_be_hidden()
                expect(page.locator("#run-completion")).to_have_text("Run to Completion")
                self.assertEqual(bar.evaluate(appearance), idle)
                # A fresh ordinary turn after a stopped run is active again.
                page.evaluate("operation => updateOperation(operation)", {
                    "turn": "new-turn", "state": "starting", "elapsed_seconds": 0, "last_contact_seconds": 0})
                self.assertEqual(bar.evaluate(appearance), active_style)
                page.evaluate("() => { stopped = true; status('Vibe stopped.'); }")
                self.assertEqual(bar.evaluate(appearance), idle)
            finally:
                browser.close()

    def test_completed_review_polling_settles_without_repainting(self):
        from playwright.sync_api import expect, sync_playwright
        project_id = self.request("/api/create", {"directory": "Settled", "name": "Settled",
                                                  "description": "", "goals": ""})[1]["id"]
        folder = self.home / "Settled"
        document = folder / "Specification.md"
        original = "# Specification\n\n" + "\n\n".join(f"Paragraph {i}: preserve the reader's place." for i in range(90))
        document.write_text(original, encoding="utf-8")
        # Same terminal shape as the observed completed second-opinion review,
        # with disposable names and text rather than private project material.
        operation = {"project": str(folder), "tool": "codex", "stage": "review-plan",
                     "turn": "completed-review", "state": "finished", "phase": "done",
                     "started": "2000-01-01T00:00:00Z", "elapsed_seconds": 335.387,
                     "last_contact_seconds": 678.77, "reason": "", "maintenance": "applied",
                     "warnings": ["Connector version evidence."], "bridge_diagnostics": ["Connector version evidence."],
                     "visible_warnings": [], "maintenance_reason": "", "outcome_recorded": True,
                     "artifact": {"role": "Plan", "path": str(folder / "Plan.md"), "outcome": "changed",
                                  "reason": "The selected Plan changed.", "label": "PASSED", "applies": "current"}}
        review = {"run": operation["turn"], "stage": "review-plan", "tool": "codex", "reviewer": "claude",
                  "iterate": True, "same_lab": False, "author_provider": "openai", "reviewer_provider": "anthropic",
                  "passes": [], "state": "complete", "rounds": 2, "agreement": "pass", "assessment": "applied",
                  "notice": "", "output": "Verdict: COMPLETE\nThe document is sufficient.", "changes": None,
                  "evaluation": "No material findings.", "verdict": "PASSED", "artifact": operation["artifact"],
                  "bridge_diagnostics": operation["bridge_diagnostics"]}
        records = {"turns": [], "runs": [review]}
        conversations, reads, errors = [], [], []
        unreadable, held_reads = False, []
        delay_read = False

        def ready(peer, **kwargs):
            return {"peer": peer, "ready": True, "work": "supported", "authentication": "unknown", "warnings": []}

        with mock.patch.object(conversation, "bridge_check", side_effect=ready), sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(self.server.url)
                self.select_project(page, project_id)
                page.wait_for_function("() => pollTimer !== null && lastFiles !== null")
                page.evaluate("() => stopPolling()")
                page.locator("#document").select_option("Specification.md")
                expect(page.locator("#reader")).to_contain_text("Paragraph 89")
                page.locator("#message").fill("Keep this unsent instruction.")

                def state(route):
                    files = self.request("/api/turn-state", {"id": project_id})[1]["files"]
                    route.fulfill(json={"operation": operation, "files": files, "run": {"active": None, "last": None}})

                def history(route):
                    conversations.append(1)
                    route.fulfill(json=records)

                def read(route):
                    reads.append(route.request.post_data_json["path"])
                    if delay_read and reads[-1] == "Specification.md":
                        held_reads.append(route)
                    elif unreadable and reads[-1] == "Specification.md":
                        route.fulfill(json={"path": "Specification.md", "name": "Specification.md", "text": None,
                                            "reason": "The document is unreadable.", "needs_selection": False, "not_started": False})
                    else:
                        route.fallback()

                page.route("**/api/turn-state", state)
                page.route("**/api/conversation", history)
                page.route("**/api/read-file", read)
                page.evaluate("() => loadConversation()")
                page.evaluate("() => pollTick()")  # Establish the watched-file baseline.
                page.evaluate("""() => {
                    window.readerMutations = 0;
                    new MutationObserver(events => { readerMutations += events.length; })
                        .observe($('reader'), {childList: true, characterData: true, subtree: true});
                    window.heldNode = $('reader').lastElementChild;
                    document.querySelector('.result-body').scrollTop = 280;
                    $('message').setSelectionRange(5, 9);
                }""")
                position = page.locator(".result-body").evaluate("element => element.scrollTop")
                self.assertGreater(position, 0)
                baseline = (len(conversations), len(reads))
                for _ in range(3):
                    page.evaluate("() => pollTick()")
                self.assertEqual((len(conversations), len(reads)), baseline)
                expect(page.locator("#status-bar")).to_have_text("Review completed in 335s. Assessment saved.")

                # Real mtime-only touches, then another file changing: no flash,
                # node replacement, reading-position loss or input consumption.
                for touched in (document, document, folder / "Plan.md"):
                    stamp = touched.stat()
                    os.utime(touched, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1_000_000_000))
                    page.evaluate("() => pollTick()")
                self.assertEqual(document.read_text(encoding="utf-8"), original)
                self.assertEqual(page.evaluate("readerMutations"), 0)
                self.assertTrue(page.evaluate("heldNode === $('reader').lastElementChild"))
                self.assertEqual(page.locator(".result-body").evaluate("element => element.scrollTop"), position)
                self.assertEqual(page.locator("#message").evaluate("element => [element.selectionStart, element.selectionEnd]"), [5, 9])
                expect(page.locator("#message")).to_have_value("Keep this unsent instruction.")
                expect(page.locator("#status-bar")).to_have_text("Review completed in 335s. Assessment saved.")
                evidence = os.environ.get("ORA_VIBE_TEST_EVIDENCE")
                if evidence:
                    Path(evidence).mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(Path(evidence) / "settled-reader.png"))

                # A genuine edit renders once; subsequent idle polls settle.
                document.write_text(original + "\n\nA genuinely new paragraph.\n", encoding="utf-8")
                page.evaluate("() => pollTick()")
                expect(page.locator("#reader")).to_contain_text("A genuinely new paragraph.")
                self.assertFalse(page.evaluate("heldNode === $('reader').lastElementChild"))
                changed_mutations = page.evaluate("readerMutations")
                self.assertGreater(changed_mutations, 0)
                for _ in range(3):
                    page.evaluate("() => pollTick()")
                self.assertEqual(page.evaluate("readerMutations"), changed_mutations)
                self.assertEqual(page.locator(".result-body").evaluate("element => element.scrollTop"), position)

                # Auxiliary outcomes are intentionally absent from both readers.
                # Each transition refreshes once; the terminal operation settles.
                for purpose in ("judgment", "sorting", "materiality"):
                    operation.update(turn=f"aux-{purpose}", stage=f"{purpose}-planning", state="running", maintenance=purpose)
                    page.evaluate("() => pollTick()")
                    stamp = document.stat()
                    os.utime(document, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1_000_000_000))
                    page.evaluate("() => pollTick()")
                    expect(page.locator("#status-bar")).to_contain_text("Working —")
                    operation.update(state="finished")
                    before = len(conversations)
                    page.evaluate("() => pollTick()")
                    self.assertEqual(len(conversations), before + 1)
                    expect(page.locator("#status-bar")).to_have_text("Read-only check completed in 335s.")
                    expect(page.locator("#status-bar")).not_to_have_class("warning")
                    for _ in range(3):
                        page.evaluate("() => pollTick()")
                    self.assertEqual(len(conversations), before + 1)
                operation.update(warnings=["The outcome note could not be recorded."],
                                 visible_warnings=["The outcome note could not be recorded."], outcome_recorded=False)
                page.evaluate("() => pollTick()")
                stamp = document.stat()
                os.utime(document, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1_000_000_000))
                page.evaluate("() => pollTick()")
                expect(page.locator("#status-bar")).to_contain_text("The outcome note could not be recorded.")
                expect(page.locator("#status-bar")).to_have_class("warning")
                operation.update(state="failed", reason="The read-only check failed.")
                page.evaluate("() => pollTick()")
                expect(page.locator("#status-bar")).to_contain_text("The read-only check failed.")
                expect(page.locator("#status-bar")).to_have_class("warning")

                # Ordinary and review results can appear after terminal status.
                # Missing records and late maintenance still catch up normally.
                operation.update(turn="late-work", stage="specification", state="finished", maintenance="no-change",
                                 warnings=[], visible_warnings=[], outcome_recorded=True, reason="")
                late = {"turn": "late-work", "stage": "specification", "tool": "codex", "purpose": "work",
                        "text": "The saved request.", "images": [], "files": [], "state": "complete",
                        "reply": "The late saved answer.", "maintenance": None, "outcome_recorded": False,
                        "artifact": None, "bridge_diagnostics": [], "questions": []}
                records["turns"] = [late]
                page.evaluate("() => pollTick()")
                expect(page.locator("#conversation")).to_contain_text("The late saved answer.")
                late.update(outcome_recorded=True, maintenance={"outcome": "no-change", "notice": "", "unsaved": False})
                page.evaluate("() => pollTick()")
                expect(page.locator("#conversation")).to_contain_text("Registry: no change needed")
                before = len(conversations)
                page.evaluate("() => pollTick()")
                self.assertEqual(len(conversations), before)
                operation.update(turn=review["run"], stage="review-plan")
                page.evaluate("() => { reviewRuns[0].state = 'open'; }")
                page.evaluate("() => pollTick()")
                self.assertEqual(len(conversations), before + 1)
                page.evaluate("() => pollTick()")
                self.assertEqual(len(conversations), before + 1)
                operation.update(turn="unrecordable", outcome_recorded=False, state="failed", reason="Could not save the outcome.")
                page.evaluate("() => pollTick()")
                before = len(conversations)
                page.evaluate("() => pollTick()")
                self.assertEqual(len(conversations), before)
                expect(page.locator("#status-bar")).to_contain_text("Could not save the outcome.")

                # Unreadable states replace old content honestly and settle too.
                unreadable = True
                stamp = document.stat()
                os.utime(document, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1_000_000_000))
                page.evaluate("() => pollTick()")
                expect(page.locator("#reader")).to_contain_text("The document is unreadable.")
                unreadable = False
                stamp = document.stat()
                os.utime(document, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1_000_000_000))
                page.evaluate("() => pollTick()")
                expect(page.locator("#reader")).to_contain_text("A genuinely new paragraph.")

                # A newer reader choice owns the pane even if the automatic
                # read of the old document finishes afterward.
                delay_read = True
                document.write_text(original + "\n\nStale pending read.\n", encoding="utf-8")
                with page.expect_request("**/api/read-file"):
                    page.evaluate("() => { window.pendingRefresh = pollTick(); }")
                page.locator("#document").select_option("Plan.md")
                expect(page.locator("#reader .reader-caption")).to_have_text("File: Plan.md — Not started")
                held_reads.pop().fulfill(json={"path": "Specification.md", "name": "Specification.md",
                                               "text": "Stale pending read.", "reason": "", "needs_selection": False, "not_started": False})
                page.evaluate("() => pendingRefresh")
                expect(page.locator("#reader .reader-caption")).to_have_text("File: Plan.md — Not started")
                expect(page.locator("#reader")).not_to_contain_text("Stale pending read.")
                delay_read = False
                page.locator("#document").select_option("Specification.md")
                expect(page.locator("#reader")).to_contain_text("Stale pending read.")
                document.unlink()
                page.evaluate("() => pollTick()")
                expect(page.locator("#reader")).to_contain_text("is no longer present in this project")
                expect(page.locator("#reader")).not_to_contain_text("Stale pending read.")
                expect(page.locator("#message")).to_have_value("Keep this unsent instruction.")
                self.assertEqual(errors, [])
            finally:
                browser.close()

    def test_conversation_reloads_across_a_runs_step_transitions(self):
        # A run's driver starts the next step's turn as soon as the previous
        # one finishes, so a poll may never observe a terminal operation.
        # When the observed run, step or running turn changes, the poll
        # reloads the conversation from the retained records; unsent drafts
        # survive and an unchanged run refetches nothing.
        try:
            from playwright.sync_api import expect, sync_playwright
        except ImportError:
            self.skipTest("Playwright is not installed for the browser check")
        project_id = self.request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})[1]["id"]
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
                # The driver has moved to the Plan step with a new running
                # turn: the next poll reloads the records, so the completed
                # step's reply appears while the run continues.
                observed.update(step="planning", turn="0003-20261017-000000")
                page.evaluate("() => pollTick()")
                expect(page.locator("#conversation")).to_contain_text("Specification saved from the run's first step.")
                expect(page.locator("#message")).to_have_value("An unsent draft that must survive the run.")
                # An unchanged run, step and turn refetch nothing.
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
        from playwright.sync_api import expect, sync_playwright
        first = self.request("/api/create", {"directory": "ScrollOne", "name": "Scroll One", "description": "", "goals": ""})[1]["id"]
        second = self.request("/api/create", {"directory": "ScrollTwo", "name": "Scroll Two", "description": "", "goals": ""})[1]["id"]
        turns = [{"turn": f"{index:04}", "tool": "codex", "stage": "planning", "state": "finished",
                  "text": f"Message {index}", "reply": (f"Answer {index}. " * 100)} for index in range(25)]
        def ready(peer, **kwargs):
            return {"peer": peer, "ready": True, "work": "supported", "authentication": "unknown", "warnings": []}
        with mock.patch.object(conversation, "bridge_check", side_effect=ready), sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
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
                evidence = os.environ.get("VIBE_CONFIGURATION_EVIDENCE")
                if evidence:
                    Path(evidence).mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(Path(evidence) / "conversation-latest-narrow.png"))
                    (Path(evidence) / "conversation-scroll.json").write_text(json.dumps({"older_reading_top_before": top,
                        "older_reading_top_after": top, "latest": page.locator("#conversation").evaluate("e => ({top:e.scrollTop, height:e.clientHeight, content:e.scrollHeight})")}, indent=2))
                self.assertEqual(errors, [])
            finally:
                browser.close()

    def test_close_warning_only_protects_unsaved_user_content(self):
        from playwright.sync_api import expect, sync_playwright
        project_id = self.request("/api/create", {"directory": "Close", "name": "Close", "description": "", "goals": ""})[1]["id"]
        def ready(peer, **kwargs):
            return {"peer": peer, "ready": True, "work": "supported", "authentication": "unknown", "warnings": []}
        with mock.patch.object(conversation, "bridge_check", side_effect=ready), sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
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
                page.locator("#destination").select_option("Codex")
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
                evidence = os.environ.get("VIBE_CONFIGURATION_EVIDENCE")
                if evidence:
                    Path(evidence).mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(Path(evidence) / "close-unsaved-project.png"))
                page.locator("#edit-description").fill("")
                page.locator("#edit-close").click()
                results["cleared"] = warns()
                page.locator("#new").click()
                page.locator("#new-name").fill("Uncreated project")
                results["unsaved_new_project"] = warns()
                self.assertEqual(results, {"fresh": False, "tool_selected": False, "stale_prepared_packet": False,
                    "unsent_text": True, "unsent_image": True, "selected_message_file": True,
                    "selected_project_material": True, "unsaved_project_edit": True, "cleared": False, "unsaved_new_project": True})
                if evidence: (Path(evidence) / "close-warning-results.json").write_text(json.dumps(results, indent=2))
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
        self.assertIn("Enter sends. Shift+Enter adds a new line. Input-method composition is respected.", page)
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

        # The one status bar floats above open modals so its answer-needing
        # text is never hidden behind a dialog.
        base_bar = declarations("#status-bar")
        floating_bar = declarations("body:has(.modal:not([hidden])) #status-bar")
        modal = declarations(".modal")
        picker = declarations("#folder-picker, #file-picker")
        self.assertEqual(floating_bar["position"], "fixed")
        self.assertEqual(base_bar["overflow"], "hidden")
        self.assertGreater(
            int(floating_bar["z-index"]),
            int(picker["z-index"]),
        )
        self.assertGreater(int(picker["z-index"]), int(modal["z-index"]))
        modal_top = (
            int(modal["inset"].split()[0].removesuffix("vh"))
            / 100
            * 720
        )
        self.assertLess(8, modal_top)
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

    def test_composer_default_size_and_divider_keep_message_accessible(self):
        from playwright.sync_api import expect, sync_playwright

        project_id = self.request("/api/create", {"directory": "Composer", "name": "Composer", "description": "", "goals": ""})[1]["id"]
        evidence = Path(os.environ["VIBE_COMPOSER_EVIDENCE"]) if os.environ.get("VIBE_COMPOSER_EVIDENCE") else None
        if evidence:
            evidence.mkdir(parents=True, exist_ok=True)
        measurements, errors = {}, []
        questions = ["Which code folder should I use for these corrections?"]
        repairs = ["Keep the corrections within the selected stage."]
        with mock.patch("ora_vibe_coder.conversation.bridge_check", side_effect=lambda peer, **kwargs: {
                "peer": peer, "ready": True, "work": "supported", "authentication": "confirmed", "warnings": []}), \
                mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 1100}, reduced_motion="reduce")
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(self.server.url)
                self.select_project(page, project_id)
                page.wait_for_function("() => pollTimer !== null && lastFiles !== null")
                page.evaluate("() => stopPolling()")
                page.locator("#destination").select_option(label="Codex")
                page.locator("#message").fill("Keep my unsent message through every stage.")

                def content(question_list, repair_list):
                    # Use the real renderers with local stand-in answers. A
                    # long history must not squeeze the response controls.
                    page.evaluate(r"""data => {
                        conversationTurns = [{turn: '0001', state: 'complete', tool: 'codex', stage: 'specification',
                            text: 'Please review this project.', reply: ('A complete paragraph from the previous conversation.\n\n').repeat(40), questions: data.questions}];
                        reviewRuns = [];
                        renderConversation(); renderQuestions();
                        if (data.repairs.length) renderRepairsResult({stage: 'specification', key: 'composer-fixture'},
                            {state: 'answered', answer: {ai: data.repairs, user: []}});
                        else { document.getElementById('repairs-box').hidden = true; document.getElementById('repairs-box').replaceChildren(); }
                        document.querySelector('.compose-message').scrollTop = 0;
                    }""", {"questions": question_list, "repairs": repair_list})

                def capture(name):
                    result = page.evaluate("""() => {
                        const box = id => document.getElementById(id).getBoundingClientRect().toJSON();
                        const compose = document.querySelector('.compose-message');
                        return {pane: box('work-step-body'), conversation: box('conversation'),
                            compose: {...compose.getBoundingClientRect().toJSON(), clientHeight: compose.clientHeight,
                                scrollHeight: compose.scrollHeight, clientWidth: compose.clientWidth, scrollWidth: compose.scrollWidth},
                            message: box('message'), send: box('send'), scrollTop: compose.scrollTop,
                            viewport: {width: innerWidth, height: innerHeight},
                            pageWidth: document.documentElement.scrollWidth};
                    }""")
                    measurements[name] = result
                    if evidence:
                        page.screenshot(path=str(evidence / f"{name}.png"), full_page=True)
                    self.assertLessEqual(result["pageWidth"], result["viewport"]["width"])
                    self.assertLessEqual(result["compose"]["scrollWidth"], result["compose"]["clientWidth"] + 1)
                    return result

                for width, height in ((1440, 1100), (1280, 720), (420, 900)):
                    page.set_viewport_size({"width": width, "height": height})
                    for name, question_list, repair_list in (("plain", [], []), ("questions-repairs", questions, repairs)):
                        content(question_list, repair_list)
                        metrics = capture(f"{width}-{height}-{name}")
                        self.assertGreaterEqual(metrics["conversation"]["height"], min(150, metrics["pane"]["height"] * .24))
                        if width >= 1280:
                            self.assertGreater(metrics["compose"]["height"], 120)
                            # Fit everything together when the content leaves
                            # reading room; wrapped controls on a short window
                            # may need the same honest scroll as long content.
                            if metrics["compose"]["scrollHeight"] <= metrics["pane"]["height"] - 150:
                                self.assertGreaterEqual(metrics["message"]["top"], metrics["compose"]["top"])
                                self.assertLessEqual(metrics["send"]["bottom"], metrics["compose"]["bottom"] + 1)
                                self.assertLessEqual(metrics["compose"]["scrollHeight"], metrics["compose"]["clientHeight"] + 1)
                        page.locator("#message").scroll_into_view_if_needed()
                        expect(page.locator("#message")).to_be_in_viewport()
                        page.locator("#send").scroll_into_view_if_needed()
                        expect(page.locator("#send")).to_be_in_viewport()

                # Content is retained whole; scroll to both ends on a short
                # desktop and on the narrow layout, then reach the controls.
                long_questions = [f"Question {index}: " + "Which correction should be made first? " * 4 for index in range(20)]
                long_repairs = [f"Finding {index}: " + "Preserve the complete existing behavior. " * 4 for index in range(20)]
                for width, height in ((1280, 720), (420, 900)):
                    page.set_viewport_size({"width": width, "height": height})
                    content(long_questions, long_repairs)
                    capture(f"{width}-{height}-long-top")
                    self.assertEqual(page.locator("#questions-box li").all_text_contents(), long_questions)
                    self.assertEqual(page.locator("#repairs-box li").all_text_contents(), long_repairs)
                    page.locator("#send").scroll_into_view_if_needed()
                    expect(page.locator("#send")).to_be_in_viewport()
                    capture(f"{width}-{height}-long-send")
                    page.locator("#message").scroll_into_view_if_needed()
                    expect(page.locator("#message")).to_be_in_viewport()

                # The user's pointer and keyboard choices still size the
                # pane, and adding questions does not reset that choice.
                page.set_viewport_size({"width": 1440, "height": 1100})
                content(questions, repairs)
                before = capture("divider-default")
                divider = page.locator("#conversation-divider").bounding_box()
                pane = before["pane"]
                page.mouse.move(divider["x"] + divider["width"] / 2, divider["y"] + divider["height"] / 2)
                page.mouse.down()
                page.mouse.move(divider["x"] + divider["width"] / 2, pane["top"] + pane["height"] * .4)
                page.mouse.up()
                dragged = capture("divider-pointer")
                self.assertAlmostEqual(dragged["conversation"]["height"] / pane["height"], .4, delta=.02)
                page.locator("#conversation-divider").press("ArrowDown")
                keyed = capture("divider-keyboard")
                self.assertAlmostEqual(keyed["conversation"]["height"] / pane["height"], .45, delta=.02)
                content(long_questions, long_repairs)
                retained = capture("divider-long-content")
                self.assertAlmostEqual(retained["conversation"]["height"], keyed["conversation"]["height"], delta=1)

                picture = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c020000000b4944415478da6364f80f00010501012718e3660000000049454e44ae426082")
                page.locator("#image-input").set_input_files({"name": "draft.png", "mimeType": "image/png", "buffer": picture})
                for stage in ("plan", "build", "specification"):
                    page.locator(f'.rail[data-stage="{stage}"]').click()
                    page.wait_for_function("stage => workspace === stage && workspaceReveal === null", arg=stage)
                    expect(page.locator("#message")).to_have_value("Keep my unsent message through every stage.")
                    expect(page.locator("#attachment-bar img")).to_have_count(1)
                    self.assertAlmostEqual(page.locator("#conversation").bounding_box()["height"], keyed["conversation"]["height"], delta=1)
                page.evaluate("() => updateOperation({turn: 'stand-in-active', state: 'running', elapsed_seconds: 1, last_contact_seconds: 0})")
                expect(page.locator("#send")).to_be_disabled()
                page.evaluate("() => updateOperation(null)")
                expect(page.locator("#send")).to_be_enabled()
                self.assertEqual(errors, [])
            finally:
                if evidence:
                    (evidence / "composer-metrics.json").write_text(json.dumps(measurements, indent=2) + "\n", encoding="utf-8")
                browser.close()

    def test_check_updates_answers_and_failure_path_use_a_stand_in_lookup(self):
        from playwright.sync_api import expect, sync_playwright

        # The deliberate check answers one of four ways through a stand-in
        # release record: no request leaves the machine in this test.
        running = (Path(__file__).resolve().parents[1] / "plugins" / "ora-vibe-coder" / "VERSION").read_text(encoding="utf-8").strip()
        major, minor, patch = (int(part) for part in running.split("."))
        release_page = lambda tag: f"https://github.com/ora-commons/ora-vibe-coder/releases/tag/v{tag}"
        def stand_in(tag):
            return lambda: {"tag_name": f"v{tag}", "html_url": release_page(tag)}
        evidence = Path(os.environ["VIBE_COMPOSER_EVIDENCE"]) if os.environ.get("VIBE_COMPOSER_EVIDENCE") else None
        if evidence:
            evidence.mkdir(parents=True, exist_ok=True)
        errors = []
        with mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
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
                    if evidence:
                        page.screenshot(path=str(evidence / f"updates-{name}.png"), full_page=True)

                # The final newer result repeats a check after every other
                # answer, proving the button and release link can be reused.
                for tag, expected in ((f"{major}.{minor + 1}.0", "newer"), (f"{major}.{minor}.{patch}", "same"), ("0.0.1", "ahead")):
                    with self.subTest(answer=expected):
                        self.server.update_lookup = stand_in(tag)
                        status, result, _ = self.request("/api/check-updates", {})
                        self.assertEqual(status, 200)
                        self.assertEqual(result["answer"], expected)
                        if expected == "newer":
                            self.assertIn(f"{major}.{minor + 1}.0", result["label"])
                            self.assertEqual(result["url"], release_page(f"{major}.{minor + 1}.0"))
                            self.assertRegex(result["note"], r"Stop Vibe.*Install or update")
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
        shared = user / "Applications"
        # The documented disposable inspection route confines every setup
        # effect under the supplied home: the entry derives the shared
        # launcher's Applications root there, the install and remove API pass
        # that root through, and the production route (no --install-home)
        # keeps the real shared folder.
        from ora_vibe_coder import installer
        argv = ["vibe", "--install", "--install-home", str(user), "--no-browser",
                "--settings", str(user / "settings.json")]
        with mock.patch.object(Path, "home", return_value=self.home), \
             mock.patch.object(sys, "argv", argv), \
             mock.patch.object(app_entry, "LocalServer", return_value=mock.Mock(url="http://127.0.0.1:1/#test")) as constructed, \
             mock.patch.object(app_entry, "serve"):
            app_entry.main()
        self.assertEqual(constructed.call_args.kwargs["install_home"], str(user))
        self.assertEqual(constructed.call_args.kwargs["install_applications"], shared)
        argv = ["vibe", "--install", "--no-browser", "--settings", str(user / "settings.json")]
        with mock.patch.object(Path, "home", return_value=self.home), \
             mock.patch.object(sys, "argv", argv), \
             mock.patch.object(app_entry, "LocalServer", return_value=mock.Mock(url="http://127.0.0.1:1/#test")) as constructed, \
             mock.patch.object(app_entry, "serve"):
            app_entry.main()
        self.assertEqual(constructed.call_args.kwargs["install_home"], self.home)
        self.assertIsNone(constructed.call_args.kwargs["install_applications"])
        # The installer CLI's documented disposable --home holds the same
        # promise: the shared Applications root is derived under that home,
        # an explicit --applications still overrides, and the default route
        # (the real home) keeps the real shared folder.
        argv = ["vibe-installer", "install", "--home", str(user)]
        with mock.patch.object(Path, "home", return_value=self.home), \
             mock.patch.object(sys, "argv", argv), \
             mock.patch.object(installer, "install", return_value={}) as cli_install, \
             mock.patch("builtins.print"):
            installer.main()
        self.assertEqual(cli_install.call_args.kwargs["home"], user)
        self.assertEqual(cli_install.call_args.kwargs["applications"], shared)
        argv = ["vibe-installer", "install", "--home", str(user), "--applications", str(user / "Explicit Applications")]
        with mock.patch.object(Path, "home", return_value=self.home), \
             mock.patch.object(sys, "argv", argv), \
             mock.patch.object(installer, "install", return_value={}) as cli_install, \
             mock.patch("builtins.print"):
            installer.main()
        self.assertEqual(cli_install.call_args.kwargs["applications"], user / "Explicit Applications")
        argv = ["vibe-installer", "remove"]
        with mock.patch.object(Path, "home", return_value=self.home), \
             mock.patch.object(sys, "argv", argv), \
             mock.patch.object(installer, "remove", return_value={"retained": [], "notes": []}) as cli_remove, \
             mock.patch("builtins.print"):
            installer.main()
        self.assertEqual(cli_remove.call_args.kwargs["home"], self.home)
        self.assertIsNone(cli_remove.call_args.kwargs["applications"])
        route = LocalServer(install_home=user, install_applications=shared)
        route_thread = threading.Thread(target=route.serve_forever, kwargs={"poll_interval": .01})
        route_thread.start()

        def close_route():
            route.shutdown()
            route_thread.join(timeout=2)
            route.server_close()

        self.addCleanup(close_route)

        def route_request(path, body):
            connection = http.client.HTTPConnection("127.0.0.1", route.server_port, timeout=2)
            connection.request("POST", path, json.dumps(body),
                               headers={"Content-Type": "application/json", "X-Ora-Token": route.token})
            response = connection.getresponse()
            data = json.loads(response.read())
            connection.close()
            return response.status, data

        with mock.patch.object(installer, "install", return_value={"app": "sentinel"}) as route_install, \
             mock.patch.object(installer, "remove", return_value={"app": "sentinel"}) as route_remove:
            self.assertEqual(route_request("/api/install", {"hosts": ["codex"]})[0], 200)
            self.assertEqual(route_request("/api/remove", {"hosts": []})[0], 200)
        self.assertEqual(route_install.call_args.kwargs["home"], user)
        self.assertEqual(route_install.call_args.kwargs["applications"], shared)
        self.assertEqual(route_remove.call_args.kwargs["home"], user)
        self.assertEqual(route_remove.call_args.kwargs["applications"], shared)
        # A Python older than 3.10 is refused before anything is staged, naming
        # the python.org macOS installer route and the reopen instruction.
        with mock.patch.object(sys, "version_info", (3, 9, 18)):
            with self.assertRaisesRegex(ValueError, r"requires Python 3\.10 or later.*python\.org.*open this setup again"):
                install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)
        selected = ("codex", "claude", "zcode", "hermes", "qwen", "minimax")
        credentials = user / ".claude" / "settings.json"
        credentials.parent.mkdir(parents=True)
        credentials.write_text('{"unrelated":"preserve this fake setting"}')
        project = user / "Projects" / "Keep"
        project.mkdir(parents=True)
        (project / "Handoff.md").write_text("previous recoverable handoff")
        result = install(source=release, home=user, hosts=selected, platform="darwin", applications=shared)
        app = Path(result["app"])
        for host in selected:
            directory = ".minimax" if host == "minimax" else f".{host}"
            entry = user / directory / "skills" / "ora-programming"
            self.assertIn(f"adapters/{host}.md", (entry / "SKILL.md").read_text())
            self.assertTrue((user / directory / "skills/ora-programming-loop/SKILL.md").is_file())
        self.assertTrue((Path(result["launcher"]) / "Contents/MacOS/Ora Vibe Coder").stat().st_mode & 0o111)
        # The launcher is the common shared app with a sealed, signed interior
        # identity; it embeds no private paths and resolves the launching
        # user's own installation at runtime.
        import os
        from ora_vibe_coder import installer
        launcher = Path(result["launcher"])
        self.assertEqual(launcher, shared / "Ora Vibe Coder.app")
        self.assertFalse((launcher / "ora-vibe-install.json").exists())
        record = installer.identity(launcher, installer.LAUNCHER_IDENTITY)
        self.assertEqual(record["version"], result["version"])
        applet = (launcher / "Contents/Resources/Scripts/main.scpt").read_bytes()
        self.assertIn(b"NSHomeDirectory", applet)
        # The home directory must be unwrapped to a JS string before any
        # concatenation; NSString + string yields an unusable path.
        self.assertIn(b"ObjC.unwrap($.NSHomeDirectory())", applet)
        self.assertIn(b"ora-vibe-install.json", applet)
        self.assertNotIn(b"/Users/", applet)
        self.assertNotIn(str(user).encode(), applet)
        # The per-user installation record carries the interpreter; the owned
        # Desktop link points at the common app.
        self.assertEqual(json.loads((app / "ora-vibe-install.json").read_text())["python"], sys.executable)
        link = user / "Desktop" / "Ora Vibe Coder"
        self.assertTrue(link.is_symlink() and os.readlink(link) == str(launcher))
        # The bundled Boost runtime sits beside the application with offline
        # entries for its three existing CLI functions.
        boost = Path(result["boost"])
        self.assertTrue((boost / "ora_review/__init__.py").is_file())
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
        with AppLock(app.parent / "app.lock"):
            with self.assertRaisesRegex(ValueError, "already running"):
                install(source=release, home=user, hosts=(), platform="darwin", applications=shared)

        old_app = (app / "ora_vibe_coder/server.py").read_bytes()
        old_loops = {
            host: (user / (".minimax" if host == "minimax" else f".{host}") / "skills/ora-programming-loop/SKILL.md").read_bytes()
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
                install(source=release, home=user, hosts=("codex", "claude"), platform="darwin", applications=shared)
        self.assertEqual((app / "ora_vibe_coder/server.py").read_bytes(), old_app)
        for host, expected in old_loops.items():
            directory = ".minimax" if host == "minimax" else f".{host}"
            self.assertEqual((user / directory / "skills/ora-programming-loop/SKILL.md").read_bytes(), expected)

        install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)

        owned = app / "ora_vibe_coder/server.py"
        installed_bytes = owned.read_bytes()
        owned.unlink()
        selected_roots = (
            app,
            user / ".codex/skills/ora-programming",
            user / ".codex/skills/ora-programming-loop",
            user / "Applications/Ora Vibe Coder.app",
        )
        damaged_snapshot = {
            str(path): path.read_bytes()
            for root in selected_roots for path in root.rglob("*") if path.is_file()
        }
        with self.assertRaisesRegex(ValueError, "changed or are missing"):
            install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)
        self.assertEqual({
            str(path): path.read_bytes()
            for root in selected_roots for path in root.rglob("*") if path.is_file()
        }, damaged_snapshot)
        self.assertFalse(owned.exists())
        owned.write_bytes(installed_bytes)
        self.assertFalse(list(user.rglob(".ora-vibe-install-*")))

        owned.write_text("user edit")
        with self.assertRaisesRegex(ValueError, "changed or are missing"):
            remove(source=release, home=user, hosts=selected, platform="darwin", applications=shared)
        self.assertTrue((app / "ora-vibe-install.json").is_file())
        for host in selected:
            directory = ".minimax" if host == "minimax" else f".{host}"
            self.assertTrue((user / directory / "skills/ora-programming/SKILL.md").is_file())
            self.assertTrue((user / directory / "skills/ora-programming-loop/SKILL.md").is_file())
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
                remove(source=release, home=user, hosts=selected, platform="darwin", applications=shared)
        self.assertEqual(owned.read_bytes(), installed_bytes)
        for host in selected:
            directory = ".minimax" if host == "minimax" else f".{host}"
            self.assertTrue((user / directory / "skills/ora-programming/SKILL.md").is_file())
            self.assertTrue((user / directory / "skills/ora-programming-loop/SKILL.md").is_file())

        removed = remove(source=release, home=user, hosts=selected, platform="darwin", applications=shared)
        self.assertIn(str(unknown), removed["retained"])
        for host in selected:
            directory = ".minimax" if host == "minimax" else f".{host}"
            self.assertFalse((user / directory / "skills/ora-programming-loop").exists())
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

        # A newer installed bundle-owned Programming Loop entry is never
        # replaced by this bundle: the bundled Loop installer owns the
        # never-newer rule now, refuses the replacement itself with its own
        # message, and setup changes nothing (every installed item is kept
        # byte-for-byte).
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

        # Equal versions install normally: the bundled installer's guard
        # blocks only newer copies, so a same-version reinstall refreshes
        # the entry.
        install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)

        # A newer shared Mac launcher alone is refused with truthful guidance:
        # removal preserves the shared launcher (another account may use it),
        # so removing Vibe first would not clear it, and setup does not say so.
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

        # A standalone renamed entry naming the public Loop release, at the
        # bundle's version (1.2.1) and again at a newer version, is preserved
        # exactly: setup succeeds, leaves that entry byte-identical with its
        # provenance, creates no old-named entry beside it, and says so; the
        # Loop installer never runs for that host. Removal afterwards removes
        # the bundle's own entries and still leaves the standalone entry.
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
            self.assertEqual(handoff.loop_component_facts(standalone_user)["installed"]["codex"],
                             {"ora-programming-loop": version})
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

        # A marker with the right version but the wrong component, source, or
        # public repository is not a preserved standalone copy: each fails the
        # provenance requirement, so setup never skips the bundled Loop
        # installer for that host on its word alone.
        plugin = release / "plugins" / "ora-vibe-coder"
        correct_marker = {
            "component": "ora-programming-loop", "source": "ora-programming-loop",
            "version": "1.2.1", "source_kind": "public-release",
            "public_release_repository": "https://github.com/ora-commons/ora-programming-loop",
            "files": {"SKILL.md": "0" * 64}}
        for field, wrong in (("component", "programming-loop"),
                             ("source", "programming-loop"),
                             ("public_release_repository", "https://github.com/example/other-loop")):
            with self.subTest(wrong_provenance=field):
                (standalone / "SOURCE.json").write_text(
                    json.dumps(dict(correct_marker, **{field: wrong})), encoding="utf-8")
                self.assertFalse(installer.standalone_loop_preserved(standalone_user, "codex", plugin))
        # End to end, the wrong-provenance entry is not preserved-and-skipped:
        # the bundled Loop installer runs for the host and installs through
        # it, and the setup note claims no preservation.
        result = install(source=release, home=standalone_user, hosts=("codex",), platform="darwin",
                         applications=standalone_user / "Applications")
        self.assertNotIn("standalone Ora Programming Loop entry", result["note"])
        self.assertEqual((standalone / "SKILL.md").read_text(encoding="utf-8"), "synthetic loop entry")
        self.assertEqual(json.loads((standalone / "SOURCE.json").read_text(encoding="utf-8"))["source_kind"],
                         "vendored-snapshot")
        remove(source=release, home=standalone_user, hosts=("codex",), platform="darwin",
               applications=standalone_user / "Applications")
        self.assertFalse((standalone_user / ".codex/skills/ora-programming").exists())
        self.assertFalse(installer.install_location(standalone_user, "darwin").exists())
        self.assertFalse(list(standalone_user.rglob(".ora-vibe-install-*")))

    def test_legacy_loop_entry_removal_refuses_symbolic_link_paths(self):
        # The bundled Loop installer refuses symbolic-link installation paths
        # for its own removals; Vibe's removal of a pre-rename bundle-installed
        # entry holds the same rule for the entry folder, its parents, the
        # removed tree, and the shared reviewer profile, so deletion can never
        # follow a link to files outside the owned entry.
        import hashlib
        from ora_vibe_coder import installer
        release = self.synthetic_release()
        profile_body = b"legacy reviewer profile\n"

        def legacy_entry(folder):
            folder.mkdir(parents=True)
            (folder / "SKILL.md").write_bytes(b"legacy loop entry\n")
            (folder / "VERSION").write_bytes(b"1.0.0\n")
            (folder / "SOURCE.json").write_text(json.dumps({
                "component": "programming-loop", "source": "programming-loop",
                "source_kind": "vendored-snapshot", "version": "1.0.0",
                "files": {"SKILL.md": hashlib.sha256(b"legacy loop entry\n").hexdigest(),
                          "VERSION": hashlib.sha256(b"1.0.0\n").hexdigest()},
                "reviewer_sha256": hashlib.sha256(profile_body).hexdigest(),
            }), encoding="utf-8")

        def reviewer_profile(agents_folder):
            agents_folder.mkdir(parents=True)
            (agents_folder / installer.LOOP_PROFILE).write_bytes(profile_body)

        # A linked entry folder: the real entry lives elsewhere and the old
        # entry path is a link to it.
        linked_folder_user = self.home / "linked legacy folder user"
        real_entry = linked_folder_user / "entry storage"
        legacy_entry(real_entry)
        reviewer_profile(linked_folder_user / ".codex" / "agents")
        skills = linked_folder_user / ".codex" / "skills"
        skills.mkdir(parents=True)
        os.symlink(real_entry, skills / "programming-loop")
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            remove(source=release, home=linked_folder_user, hosts=("codex",),
                   platform="darwin", applications=linked_folder_user / "Applications")
        self.assertEqual((real_entry / "SKILL.md").read_bytes(), b"legacy loop entry\n")
        self.assertTrue((skills / "programming-loop").is_symlink())

        # A linked parent folder above the entry.
        linked_parent_user = self.home / "linked legacy parent user"
        skills_storage = linked_parent_user / "skills storage"
        legacy_entry(skills_storage / "programming-loop")
        reviewer_profile(linked_parent_user / ".codex" / "agents")
        (linked_parent_user / ".codex").mkdir(parents=True, exist_ok=True)
        os.symlink(skills_storage, linked_parent_user / ".codex" / "skills")
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            remove(source=release, home=linked_parent_user, hosts=("codex",),
                   platform="darwin", applications=linked_parent_user / "Applications")
        self.assertTrue((skills_storage / "programming-loop" / "SOURCE.json").is_file())

        # A symlink inside the removed tree, added beside the owned files.
        outside = self.home / "outside the linked tree"
        outside.mkdir()
        (outside / "personal.txt").write_text("outside content")
        linked_inside_user = self.home / "linked legacy inside user"
        legacy_entry(linked_inside_user / ".codex" / "skills" / "programming-loop")
        reviewer_profile(linked_inside_user / ".codex" / "agents")
        os.symlink(outside / "personal.txt",
                   linked_inside_user / ".codex" / "skills" / "programming-loop" / "added link.md")
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            remove(source=release, home=linked_inside_user, hosts=("codex",),
                   platform="darwin", applications=linked_inside_user / "Applications")
        self.assertTrue(
            (linked_inside_user / ".codex" / "skills" / "programming-loop" / "SKILL.md").is_file())
        self.assertEqual((outside / "personal.txt").read_text(), "outside content")

        # The reviewer-profile path behind a linked agents folder: the entry
        # itself is plain, but the profile deletion would traverse a link.
        linked_profile_user = self.home / "linked legacy profile user"
        legacy_entry(linked_profile_user / ".codex" / "skills" / "programming-loop")
        agents_storage = linked_profile_user / "agents storage"
        reviewer_profile(agents_storage)
        os.symlink(agents_storage, linked_profile_user / ".codex" / "agents")
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            remove(source=release, home=linked_profile_user, hosts=("codex",),
                   platform="darwin", applications=linked_profile_user / "Applications")
        self.assertTrue((linked_profile_user / ".codex" / "skills" / "programming-loop"
                         / "SOURCE.json").is_file())
        self.assertEqual((agents_storage / installer.LOOP_PROFILE).read_bytes(), profile_body)

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
        # A personal item at the Desktop link's path is never replaced.
        link.unlink()
        link.write_text("a personal item")
        (release / "ora_vibe_coder/server.py").write_text("BOUNDARY = 'replacement application'\n")
        second = install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)
        self.assertEqual(second["desktop_link"], "kept an existing personal item")
        self.assertEqual(link.read_text(), "a personal item")
        self.assertFalse(link.is_symlink())
        assert_launcher_icon()
        # A missing owned link is restored on update.
        link.unlink()
        third = install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)
        self.assertEqual(third["desktop_link"], "created")
        self.assertTrue(link.is_symlink() and os.readlink(link) == str(launcher))
        assert_launcher_icon()
        # Removal deletes only the owned link; the shared launcher stays for
        # another account, and the result reports exactly that.
        removed = remove(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)
        self.assertFalse(link.exists())
        self.assertFalse(Path(result["app"]).exists())
        self.assertTrue(launcher.is_dir())
        self.assertTrue(any("shared launcher" in note and "was kept" in note for note in removed["notes"]))
        # Reinstallation uses the same bundled artwork without a custom Finder icon.
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
        # A shared folder this account cannot write is refused before anything
        # changes, naming the permission the shared launcher actually needs.
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
        # A signing-command failure is a transaction failure, never ignored.
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
        # A strict final-location verification failure rolls the whole
        # transaction back to the previous usable installation.
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
        # The installed entries bind to the Bridge bundled beside them, and
        # that bundled Bridge copy is exactly where they point.
        self.assertTrue((boost.parent / "agent-bridge" / "ora_agent_bridge" / "__main__.py").is_file())
        for name in installer.BOOST_ENTRIES:
            wrapper = boost / name
            self.assertTrue(wrapper.stat().st_mode & 0o111, name)
            self.assertIn(
                'os.environ["AGENT_BRIDGE_HOME"] = str(root.parent / "agent-bridge")',
                wrapper.read_text(encoding="utf-8"),
            )
        # The bundled package imports offline and reports its released facts.
        completed = subprocess.run(
            [sys.executable, "-c",
             "import json, sys; sys.path.insert(0, sys.argv[1]); import ora_review; "
             "print(json.dumps(ora_review.COMPONENT_FACTS))", str(boost)],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        facts = json.loads(completed.stdout)
        self.assertEqual(facts["component"], "ora-adversarial-review")
        self.assertEqual(facts["version"], "0.5.0")
        self.assertEqual(sorted(facts["analytical_roles"]), ["peer", "primary"])
        # An installed entry answers its own command surface offline; no
        # network, pip, or model call is involved in running --help.
        helped = subprocess.run([sys.executable, str(boost / "ora-gear-3"), "--help"],
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(helped.returncode, 0, helped.stderr)
        self.assertIn("ora-gear-3", helped.stdout)
        # The bundled Gear accepts this turn's exact user words: the option is
        # part of the bundled command surface. A blank turn-instructions file
        # proves acceptance offline and safely — the bundled engine recognizes
        # the option, reads its file, and refuses before any engine is built,
        # while a bundle regressed to an engine without the option fails to
        # parse instead ("unrecognized arguments", exit code 2).
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
            # A bounded test wait ensures a regression cannot strand the harness.
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
            browser = None
            playwright = None
            try:
                # The normal launcher reached serve while the configured root
                # itself was blocked; setup and HTTP remain responsive.
                wait_for(lambda: (projects / ".entered-folder").exists())
                self.assertEqual(self.request("/", {}, method="GET")[0], 200)
                setup = self.request("/api/setup", {})[1]
                self.assertEqual(setup["home"], str(projects))
                pending = self.request("/api/projects", {})[1]
                self.assertTrue(pending["scanning"])
                self.assertFalse(pending["complete"])
                self.assertIn(str(projects), " ".join(pending["notices"]))
                controller = server.store._scan_thread
                for _ in range(4):
                    self.assertEqual(self.request("/api/rescan", {})[0], 200)
                    self.assertIs(server.store._scan_thread, controller)
                wait_for(lambda: not server.store.report()["scanning"])
                self.assertFalse(server.store.report()["complete"])
                (projects / ".stall-folder").unlink()
                (projects / ".stall-after-entries").touch()
                self.request("/api/rescan", {})
                wait_for(lambda: not server.store.report()["scanning"])
                inventory = self.request("/api/projects", {})[1]
                self.assertEqual({entry["name"] for entry in inventory["projects"]}, {"Readable", "Nested"})
                notices = " ".join(inventory["notices"])
                self.assertIn(str(unavailable), notices)
                self.assertIn(f"{projects} could not be read", notices)
                self.assertTrue((projects / ".entered-partial").exists())
                self.assertIn(str(definition / "Project.md"), notices)
                self.assertTrue((unavailable / ".entered-folder").exists())
                self.assertTrue((definition / ".entered-file").exists())
                self.assertEqual(self.request("/api/quit-state", {})[0], 200)

                # Inspect the same UI surfaces used by the normal launcher.
                # Browser availability is also covered by the separately named
                # project-picker check; API hard-hang proof runs regardless.
                try:
                    from playwright.sync_api import expect, sync_playwright
                except ImportError:
                    sync_playwright = None
                if sync_playwright is not None:
                    playwright = sync_playwright().start()
                    if Path(playwright.chromium.executable_path).is_file():
                        browser = playwright.chromium.launch(headless=True)
                        page = browser.new_page()
                        opened = []
                        page.on("request", lambda request: opened.append(request.url) if request.url.endswith("/api/open") else None)
                        page.goto(server.url)
                        expect(page.locator("#project")).to_be_visible()
                        expect(page.locator("#project option")).to_have_count(3)
                        self.assertEqual(opened, [])  # Unreadable last_project is never auto-opened.
                        page.locator("#open").click()
                        expect(page.locator("#scan-notices")).to_contain_text(str(definition / "Project.md"))
                        expect(page.locator("#scan-notices")).to_contain_text(str(unavailable))
                        expect(page.locator("#project-list")).not_to_contain_text("No projects")
                        defaults = page.evaluate("({home: browseHome, fallback: browseFallback})")
                        page.evaluate("paths => { browseHome = paths.missing; browseFallback = paths.home; }",
                                      {"missing": str(self.home / "Missing Documents"), "home": str(self.home)})
                        page.locator("#open-browse").click()
                        expect(page.locator("#folder-picker")).to_be_visible()
                        expect(page.locator("#folder-path")).to_have_value(str(self.home))
                        self.assertEqual(server.store.home, projects)
                        page.locator("#folder-cancel").click()
                        page.evaluate("paths => { browseHome = paths.home; browseFallback = paths.fallback; }", defaults)
                        page.locator("#open-close").click()
                        entry = next(item for item in inventory["projects"] if item["name"] == "Readable")
                        self.select_project(page, entry["id"])
                        page.locator('[data-stage="build"]').click()
                        page.locator("#message").fill("Keep this unsent message")

                (projects / ".stall-after-entries").unlink()
                (unavailable / ".stall-folder").unlink()
                (definition / ".stall-file").unlink()
                if browser is not None:
                    page.locator("#open").click()
                    page.locator("#refresh-projects").click()
                    expect(page.locator("#project option")).to_have_count(4)
                    expect(page.locator("#project")).to_have_value(entry["id"])
                    expect(page.locator("#message")).to_have_value("Keep this unsent message")
                    self.assertEqual(page.evaluate("workspace"), "build")
                    page.locator("#open-close").click()
                else:
                    self.request("/api/rescan", {})
                wait_for(lambda: not server.store.report()["scanning"])
                recovered = self.request("/api/projects", {})[1]
                self.assertTrue(recovered["complete"])
                self.assertEqual({item["name"] for item in recovered["projects"]}, {"Definition", "Readable", "Nested"})
                self.assertFalse(recovered["notices"])

                # A later unavailable definition keeps its last-known identity,
                # honestly disabled; Stop reaps the actually blocked helper.
                (definition / ".entered-file").unlink()
                (definition / ".stall-file").touch()
                self.request("/api/rescan", {})
                wait_for(lambda: (definition / ".entered-file").exists())
                current = self.request("/api/projects", {})[1]
                known = next(item for item in current["projects"] if item["name"] == "Definition")
                self.assertFalse(known["available"])
                self.assertEqual(self.request("/api/stop", {})[0], 200)
                self.thread.join(3)
                self.assertFalse(self.thread.is_alive())
                server.shutdown_thread.join(3)
                self.assertFalse(server.shutdown_thread.is_alive())
                self.assertFalse(server.store._scan_thread.is_alive())
                self.assertTrue(all(child.poll() is not None for child in owned_readers))
                self.assertFalse([thread for thread in threading.enumerate() if thread.name == "Vibe discovery responses"])
            finally:
                if browser is not None:
                    browser.close()
                if playwright is not None:
                    playwright.stop()
                self.close()

        argv = ["vibe", "--no-browser", "--settings", str(settings.path)]
        with mock.patch.object(project_module.subprocess, "Popen", side_effect=start_reader), \
                mock.patch.object(project_module, "DISCOVERY_READ_SECONDS", .75), \
                mock.patch.object(sys, "argv", argv), \
                mock.patch.object(app_entry, "serve", side_effect=exercise):
            app_entry.main()
        self.assertFalse(settings.path.with_name("running.json").exists())
        self.assertTrue(all(child.poll() is not None for child in owned_readers))

        # Failure to save or protect the launch record must close the already
        # constructed server and reap its blocked reader before releasing the
        # lock that prevents another launch or update from taking ownership.
        running = settings.path.with_name("running.json")
        original_write = app_entry.atomic_write
        original_chmod = Path.chmod
        original_close = LocalServer.server_close
        for failure in ("write", "permissions"):
            with self.subTest(launch_record_failure=failure):
                (projects / ".entered-folder").unlink(missing_ok=True)
                (projects / ".stall-folder").touch()
                constructed, closed = [], []

                def construct(*args, **kwargs):
                    server = LocalServer(*args, **kwargs)
                    constructed.append(server)
                    return server

                def save_record(path, text):
                    if failure == "write":
                        wait_for(lambda: (projects / ".entered-folder").exists())
                        raise OSError("launch record write failed")
                    return original_write(path, text)

                def protect_record(path, *args, **kwargs):
                    if path == running:
                        wait_for(lambda: (projects / ".entered-folder").exists())
                        raise OSError("launch record permissions failed")
                    return original_chmod(path, *args, **kwargs)

                def close_while_locked(server):
                    with self.assertRaisesRegex(ValueError, "already running"):
                        with AppLock(settings.path.with_name("app.lock")):
                            pass
                    original_close(server)
                    closed.append(server)

                try:
                    with mock.patch.object(project_module.subprocess, "Popen", side_effect=start_reader), \
                            mock.patch.object(app_entry, "LocalServer", side_effect=construct), \
                            mock.patch.object(LocalServer, "server_close", new=close_while_locked), \
                            mock.patch.object(app_entry, "atomic_write", side_effect=save_record), \
                            mock.patch.object(Path, "chmod", new=protect_record), \
                            mock.patch.object(sys, "argv", argv), \
                            mock.patch.object(app_entry, "serve") as serve_failed, \
                            contextlib.redirect_stdout(io.StringIO()) as message:
                        app_entry.main()
                    serve_failed.assert_not_called()
                    self.assertIn("could not start", message.getvalue())
                    self.assertEqual(closed, constructed)
                    self.assertEqual(len(closed), 1)
                    self.assertEqual(closed[0].fileno(), -1)
                    self.assertFalse(closed[0].store._scan_thread.is_alive())
                    self.assertTrue(all(child.poll() is not None for child in owned_readers))
                    self.assertFalse(running.exists())
                    with AppLock(settings.path.with_name("app.lock")):
                        pass
                finally:
                    for server in constructed:
                        original_close(server)

        # A genuinely missing configured root is reported at that boundary;
        # startup must neither abort nor silently search another folder.
        missing = self.home / "Missing configured root"
        settings.update(projects_dir=str(missing))
        seen = []
        def unavailable_root(server, **kwargs):
            try:
                server.store._scan_thread.join()
                seen.append(server.store.report())
            finally:
                server.server_close()
        with mock.patch.object(sys, "argv", argv), mock.patch.object(app_entry, "serve", side_effect=unavailable_root):
            app_entry.main()
        self.assertEqual(seen[0]["home"], str(missing))
        self.assertFalse(seen[0]["complete"])
        self.assertIn(str(missing), " ".join(seen[0]["notices"]))

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
