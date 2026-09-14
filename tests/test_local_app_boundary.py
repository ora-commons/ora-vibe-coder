import http.client
import contextlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest
from unittest import mock

from ora_vibe_coder import hosts
from ora_vibe_coder.installer import install, launcher_files, remove
from ora_vibe_coder.launcher import AppLock, Settings, serve
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
        return source

    def test_wrong_host_origin_token_and_unselected_or_arbitrary_paths(self):
        status, page, headers = self.request("/", {}, method="GET")
        self.assertEqual(status, 200)
        page = page.decode("utf-8")
        self.assertIn("Enter adds a new line. Control+Enter or Command+Enter prepares the request.", page)
        self.assertEqual(page.count('class="rail" data-stage='), 4)
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
        self.assertEqual((status, body), (200, {"stopped": True}))
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())
        self.assertIn("img-src 'none'", headers["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertTrue(external.exists())

    def test_first_use_requires_selected_folder_and_preserves_preferences(self):
        self.server.store = None
        preferences = Settings(self.home / "settings.json")
        preferences.update(unrelated="keep")
        self.server.settings = preferences
        before = set(self.home.iterdir())
        self.assertIsNone(self.request("/api/setup", {})[1]["home"])
        self.assertEqual(self.request("/api/projects", {})[0], 400)
        self.assertEqual(set(self.home.iterdir()), before)
        self.assertEqual(self.request("/api/select-home", {"path": str(self.home / "missing")})[0], 400)
        self.assertNotIn("projects_home", preferences.read())
        self.assertEqual(self.request("/api/select-home", {"path": str(self.home)})[0], 200)
        self.assertEqual(preferences.read(), {"unrelated": "keep", "projects_home": str(self.home)})
        self.assertEqual(self.request("/api/folders", {"path": str(self.home)}, {"Origin": "https://unrelated.invalid"})[0], 403)

    def test_disposable_install_update_failure_remove_and_selected_host_preservation(self):
        user = self.home / "disposable user 日本語"
        release = self.synthetic_release()
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

    def test_fixed_vector_continuations_preserve_exact_saved_markdown(self):
        projects = self.home / "projects"
        projects.mkdir()
        store = ProjectStore(projects)
        project = store.projects[store.create("One", "One", "Purpose", "Goals")]
        packet = "Keep Unicode: café 日本語\n```sh\n$(touch NEVER_RUN); echo `not shell`\n```\n" + "long input\n" * 3000
        project.save_packet(packet, None, False)
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
        with self.assertRaisesRegex(Exception, "saved handoff changed"):
            hosts.continue_in(project, "unseen changed packet", "Codex")
        self.assertFalse((project.root / "NEVER_RUN").exists())

    def test_zcode_receipt_validation_and_resume_failure_preserve_recovery(self):
        projects = self.home / "projects"
        projects.mkdir()
        store = ProjectStore(projects)
        project = store.projects[store.create("One", "One", "Purpose", "Goals")]
        packet = "Exact assignment 日本語\n$(not shell)\n"
        project.save_packet(packet, None, False)
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
