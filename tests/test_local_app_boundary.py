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
        project_name = "ORA-147 — Require diagrams from three analysis modes"
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
        report.write_text("# Verification Report\n\nStatus: PASSED\n\n## Result\nThe corrected delivery meets its requirements.\n", encoding="utf-8")
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
                # The displayed verdict is binary: a current COMPLETE assessment is PASSED.
                expect(page.locator("#assessment")).to_have_text("PASSED")
                expect(page.locator("#assessment-note")).to_contain_text("does not identify which document version")
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
                expect(page.locator("#result-status")).to_have_text("COMPLETE")
                expect(page.locator("#assessment")).to_have_text("PASSED")
                expect(page.locator("#assessment-note summary")).to_contain_text(report.name)
                expect(page.locator("#reader")).to_contain_text("Status: PASSED")
                expect(page.locator("#project-completion .completion-wide")).to_have_text("REPORTED COMPLETE")

                report.write_text("# Verification Report\n\n**Verdict: PASSED.** But the current candidate failed.\n", encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("CONCLUSION UNCLEAR")
                expect(page.locator("#assessment-note")).to_contain_text("current candidate failed")
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
        with mock.patch("ora_vibe_coder.conversation.bridge_check", side_effect=ready), \
                mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), sync_playwright() as playwright:
            if not Path(playwright.chromium.executable_path).is_file():
                self.skipTest("Playwright's Chromium is not installed for the browser check")
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(permissions=["clipboard-read", "clipboard-write"])
            try:
                page = context.new_page()
                page.goto(self.server.url)
                page.evaluate("() => { window.clipboardText = ''; navigator.clipboard.writeText = text => { window.clipboardText = text; return Promise.resolve(); }; }")
                self.select_project(page, project_id)
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
                specification.write_text("# One — Specification\n\n## Description\n\nBehavior to build.\n", encoding="utf-8")
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
                page.locator("#copy-request").click()
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

                # PASSED / NOT PASSED from the saved record; an unclear record
                # gets one remembered judgment, and a failed call a reading error.
                reviewed = "# One — Specification\n\n## Description\n\nBehavior.\n\n## Current review\n\nStage: Specification\nVerdict: COMPLETE\nBasis: {basis}\nBasis format: content-v2\n"
                specification.write_text(reviewed.replace("{basis}", review_basis(reviewed)), encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("PASSED")
                specification.write_text(reviewed.replace("Verdict: COMPLETE", "Verdict: INCOMPLETE").replace("{basis}", review_basis(reviewed.replace("Verdict: COMPLETE", "Verdict: INCOMPLETE"))).replace("Behavior.", "Behavior, changed."), encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("NOT PASSED — earlier version")
                unclear = "# One — Specification\n\n## Description\n\nBehavior.\n\n## Current review\n\nStage: Specification\nVerdict: COMPLETE and also INCOMPLETE in the summary.\nBasis: {basis}\nBasis format: content-v2\n"
                unclear = unclear.replace("{basis}", review_basis(unclear))
                specification.write_text(unclear, encoding="utf-8")
                with mock.patch("ora_vibe_coder.conversation.bridge_call",
                                side_effect=Exception("bridge unavailable")):
                    page.locator("#refresh").click()
                    page.wait_for_function("() => document.getElementById('assessment').textContent === 'READING ERROR'")
                    self.assertIn("bridge unavailable", page.locator("#assessment").get_attribute("title") or "")

                # Approve the Plan is greyed until COMPLETE, then saves
                # Status: APPROVED preserving the rest of the document and review.
                plan.write_text("# One — Plan\n\nStatus: AWAITING APPROVAL\n\n## Approach\n\nSteps.\n\n## Current review\n\nStage: Plan\nVerdict: INCOMPLETE\nBasis: {basis}\nBasis format: content-v2\n", encoding="utf-8")
                plan_text = plan.read_text(encoding="utf-8").replace("{basis}", review_basis(plan.read_text(encoding="utf-8")))
                plan.write_text(plan_text, encoding="utf-8")
                page.locator(".rail[data-stage=plan]").click()
                expect(page.locator("#approve-plan")).to_be_disabled()
                approved = plan_text.replace("Verdict: INCOMPLETE", "Verdict: COMPLETE")
                approved = approved.replace(review_basis(plan_text), review_basis(approved))
                plan.write_text(approved, encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#approve-plan")).to_be_enabled()
                with mock.patch("ora_vibe_coder.server.atomic_write", side_effect=OSError("disk full")):
                    page.locator("#approve-plan").click()
                    expect(page.locator("#status-bar"), "the failed save reports and keeps the prior file").to_contain_text("disk full")
                self.assertIn("Status: AWAITING APPROVAL", plan.read_text(encoding="utf-8"))
                page.locator("#approve-plan").click()
                expect(page.locator("#status-bar")).to_contain_text("Status: APPROVED saved")
                saved_plan = plan.read_text(encoding="utf-8")
                self.assertIn("Status: APPROVED", saved_plan)
                self.assertIn("## Approach\n\nSteps.", saved_plan)
                self.assertIn("Verdict: COMPLETE", saved_plan)
                expect(page.locator("#approve-plan")).to_be_disabled()
                expect(page.locator("#assessment")).to_have_text("PASSED")
                expect(page.locator("#reader")).to_contain_text("Status: APPROVED")

                # Build's verdicts and next actions: NOT PASSED offers Request
                # repairs; REVIEW INCOMPLETE offers to finish or rerun; a legacy
                # combined label shows as REVIEW INCOMPLETE.
                page.locator(".rail[data-stage=build]").click()
                expect(page.locator("#assessment")).to_have_text("NOT VERIFIED")
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
                (root / "One — Verification Report.md").write_text("# Verification Report\n\nVerdict: NOT PASSED — REVIEW INCOMPLETE\n\n- A finding and an unfinished check.\n", encoding="utf-8")
                page.locator("#refresh").click()
                expect(page.locator("#assessment")).to_have_text("REVIEW INCOMPLETE")
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
            finally:
                browser.close()

    def test_saved_role_defaults_restore_and_survive_a_warning_only_save(self):
        # A saved role reopens accurately in Settings, and saving an unrelated
        # setting preserves every role — through the shared renderer that
        # Settings, the setup interview and Configure Path all use.
        try:
            from playwright.sync_api import expect, sync_playwright
        except ImportError:
            self.skipTest("Playwright is not installed for the browser check")
        settings = Settings(self.home / "role-settings.json")
        server = LocalServer(self.home, settings=settings)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01})
        thread.start()

        def close():
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.addCleanup(close)

        def request(path, body):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
            connection.request("POST", path, json.dumps(body),
                               headers={"Content-Type": "application/json", "X-Ora-Token": server.token})
            response = connection.getresponse()
            data = json.loads(response.read())
            connection.close()
            return response.status, data

        _status, created = request("/api/create", {"directory": "One", "name": "One", "description": "", "goals": ""})
        _status, _saved = request("/api/settings", {"role_defaults": {
            "planning": {"tool": "claude", "model": "claude-test-model", "effort": "high"},
            "verification": {"tool": "zcode", "model": "", "effort": ""}}})

        def ready(peer, **kwargs):
            return {"peer": peer, "ready": True, "work": "supported", "authentication": "confirmed", "warnings": []}

        with mock.patch("ora_vibe_coder.conversation.bridge_check", side_effect=ready), \
                mock.patch.object(hosts, "executable", return_value=["/fake/tool"]), sync_playwright() as playwright:
            if not Path(playwright.chromium.executable_path).is_file():
                self.skipTest("Playwright's Chromium is not installed for the browser check")
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(server.url)
                self.select_project(page, created["id"])
                page.wait_for_function("() => pollTimer !== null && lastFiles !== null")
                page.locator("#settings").click()
                expect(page.locator("#settings-panel")).to_be_visible()
                planning = page.locator('#settings-roles .role-row[data-role="planning"]')
                expect(planning.locator("select")).to_have_value("claude")
                expect(planning.locator("input").first).to_have_value("claude-test-model")
                expect(planning.locator("input").nth(1)).to_have_value("high")
                verification = page.locator('#settings-roles .role-row[data-role="verification"]')
                expect(verification.locator("select")).to_have_value("zcode")
                # A warning-only save preserves every saved role.
                page.locator("#settings-warn").uncheck()
                page.locator("#settings-save").click()
                expect(page.locator("#settings-panel")).to_be_hidden()
                _status, readback = request("/api/settings", {})
                self.assertIs(readback["warn_skip_review"], False)
                self.assertEqual(readback["role_defaults"]["planning"],
                                 {"tool": "claude", "model": "claude-test-model", "effort": "high"})
                self.assertEqual(readback["role_defaults"]["verification"],
                                 {"tool": "zcode", "model": "", "effort": ""})
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
            self.assertTrue((user / directory / "skills/programming-loop/SKILL.md").is_file())
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
                install(source=release, home=user, hosts=("codex", "claude"), platform="darwin", applications=shared)
        self.assertEqual((app / "ora_vibe_coder/server.py").read_bytes(), old_app)
        for host, expected in old_loops.items():
            directory = ".minimax" if host == "minimax" else f".{host}"
            self.assertEqual((user / directory / "skills/programming-loop/SKILL.md").read_bytes(), expected)

        install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)

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
                remove(source=release, home=user, hosts=selected, platform="darwin", applications=shared)
        self.assertEqual(owned.read_bytes(), installed_bytes)
        for host in selected:
            directory = ".minimax" if host == "minimax" else f".{host}"
            self.assertTrue((user / directory / "skills/ora-programming/SKILL.md").is_file())
            self.assertTrue((user / directory / "skills/programming-loop/SKILL.md").is_file())

        removed = remove(source=release, home=user, hosts=selected, platform="darwin", applications=shared)
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
        loop_source = user / ".codex" / "skills" / "programming-loop" / "SOURCE.json"
        marker = json.loads(loop_source.read_text(encoding="utf-8"))
        marker["version"] = "9.9.9"
        loop_source.write_text(json.dumps(marker), encoding="utf-8")
        with self.assertRaisesRegex(ValueError,
                                    r"Programming Loop for codex at .*skills/programming-loop records version 9\.9\.9.*Removing Ora Vibe Coder first"):
            install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)
        self.assertEqual(json.loads(identity.read_text(encoding="utf-8")), original)
        self.assertEqual((app / "ora_vibe_coder/server.py").read_bytes(),
                         before[str(app / "ora_vibe_coder/server.py")])
        self.assertFalse(list(user.rglob(".ora-vibe-install-*")))

        # Equal versions install normally: the guard blocks only newer copies.
        marker.pop("version")
        loop_source.write_text(json.dumps(marker), encoding="utf-8")
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

        # A renamed shared entry alone (ora-programming-loop, as newer
        # Programming Loop releases install it; no old-name entry) is
        # recognized, reported under its own name, and preserved: setup
        # changes nothing and does not recreate the older pre-rename entry.
        from ora_vibe_coder import handoff
        renamed_user = self.home / "renamed loop user"
        renamed = renamed_user / ".codex" / "skills" / "ora-programming-loop"
        renamed.mkdir(parents=True)
        (renamed / "SOURCE.json").write_text(json.dumps(
            {"component": "programming-loop", "source": "programming-loop", "version": "1.2.1"}),
            encoding="utf-8")
        self.assertEqual(handoff.loop_component_facts(renamed_user)["installed"]["codex"],
                         {"ora-programming-loop": "1.2.1"})
        with self.assertRaisesRegex(ValueError,
                                    r"Programming Loop for codex at .*ora-programming-loop records version 1\.2\.1"
                                    r".*That entry belongs to a newer installation this setup preserves; "
                                    r"install the Ora Vibe Coder release that bundles that newer Programming Loop\."):
            install(source=release, home=renamed_user, hosts=("codex",), platform="darwin",
                    applications=renamed_user / "Applications")
        self.assertEqual(json.loads((renamed / "SOURCE.json").read_text(encoding="utf-8"))["version"], "1.2.1")
        self.assertFalse((renamed_user / ".codex/skills/programming-loop").exists())
        self.assertFalse((renamed_user / ".codex/skills/ora-programming").exists())
        self.assertFalse(installer.install_location(renamed_user, "darwin").exists())
        self.assertFalse(list(renamed_user.rglob(".ora-vibe-install-*")))
        # An equal renamed copy is preserved the same way: installing this
        # bundle's same-version entry under the older name would duplicate it.
        (renamed / "SOURCE.json").write_text(json.dumps(
            {"component": "programming-loop", "source": "programming-loop", "version": "1.0.0"}),
            encoding="utf-8")
        self.assertEqual(handoff.loop_component_facts(renamed_user)["installed"]["codex"],
                         {"ora-programming-loop": "1.0.0"})
        with self.assertRaisesRegex(ValueError,
                                    r"ora-programming-loop records version 1\.0\.0"
                                    r".*That entry belongs to a newer installation this setup preserves; "
                                    r"install the Ora Vibe Coder release that bundles that newer Programming Loop\."):
            install(source=release, home=renamed_user, hosts=("codex",), platform="darwin",
                    applications=renamed_user / "Applications")
        self.assertFalse((renamed_user / ".codex/skills/programming-loop").exists())
        self.assertFalse(list(renamed_user.rglob(".ora-vibe-install-*")))

    def test_common_launcher_and_desktop_link_are_maintained_and_removal_reports_shared_items(self):
        from ora_vibe_coder import installer
        user = self.home / "shared launcher user"
        release = self.synthetic_release()
        shared = user / "Applications"
        result = install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)
        launcher = Path(result["launcher"])
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
        # A missing owned link is restored on update.
        link.unlink()
        third = install(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)
        self.assertEqual(third["desktop_link"], "created")
        self.assertTrue(link.is_symlink() and os.readlink(link) == str(launcher))
        # Removal deletes only the owned link; the shared launcher stays for
        # another account, and the result reports exactly that.
        removed = remove(source=release, home=user, hosts=("codex",), platform="darwin", applications=shared)
        self.assertFalse(link.exists())
        self.assertFalse(Path(result["app"]).exists())
        self.assertTrue(launcher.is_dir())
        self.assertTrue(any("shared launcher" in note and "was kept" in note for note in removed["notes"]))
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
        self.assertTrue((boost.parent / "agent-bridge" / "bridge" / "__main__.py").is_file())
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
        self.assertEqual(facts["version"], "0.3.0")
        self.assertEqual(sorted(facts["analytical_roles"]), ["peer", "primary"])
        # An installed entry answers its own command surface offline; no
        # network, pip, or model call is involved in running --help.
        helped = subprocess.run([sys.executable, str(boost / "ora-gear-3"), "--help"],
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(helped.returncode, 0, helped.stderr)
        self.assertIn("ora-gear-3", helped.stdout)

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
