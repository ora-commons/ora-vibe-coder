"""Ordinary Markdown project files, with explicit selection and narrow writes."""

import os
from pathlib import Path
import re
import secrets
import stat
import tempfile

from .status import metadata, reported_status

READ_LIMIT = 256 * 1024
PACKET_LIMIT = 4 * 1024 * 1024
ROLES = ("Request", "Specification", "Plan", "User Guide", "Technical Documentation",
         "Product Overview", "Programming Result", "Verification Findings", "Report", "Code", "Checks", "Baseline")
DEFAULT_NAMES = {"Request": "01 Request", "Specification": "02 Specification", "Plan": "03 Implementation Plan",
                 "User Guide": "04 User Guide", "Technical Documentation": "05 Technical Documentation",
                 "Product Overview": "06 Product Overview", "Report": "07 Report"}


class ProjectError(ValueError):
    pass


class Conflict(ProjectError):
    def __init__(self, message, current):
        super().__init__(message)
        self.current = current


def read_text(path, limit=READ_LIMIT):
    if not stat.S_ISREG(Path(path).stat().st_mode):
        raise ProjectError("Not an ordinary file; reference only.")
    with Path(path).open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ProjectError(f"Larger than the {limit // 1024} KiB reading ceiling; reference only. Nothing was truncated.")
    if b"\0" in data:
        raise ProjectError("Binary content; reference only.")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProjectError("Not readable UTF-8 text; reference only.") from error


def atomic_write(path, text):
    """A failed staging or replacement preserves the old destination."""
    path = Path(path)
    staging = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=".ora-handoff-", delete=False) as stream:
            staging = Path(stream.name)
            stream.write(text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staging, path)
        staging = None
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)


def sections(text):
    matches = list(re.finditer(r"^## ([^\r\n]+)\r?$", text, re.M))
    return [(m[1], m.start(), m.end(), matches[i + 1].start() if i + 1 < len(matches) else len(text))
            for i, m in enumerate(matches)]


def parse_brief(text, fallback):
    fields = metadata(text)
    result = {"name": fields.get("Name", [fallback])[0], "description": "", "goals": "", "paths": {}}
    for name, start, body, end in sections(text):
        if name in {"Description", "Goals"}:
            result[name.lower()] = text[body:end].strip()
        if name == "Artifact Paths":
            for line in text[body:end].splitlines():
                for role in ROLES:
                    match = re.fullmatch(r"- " + re.escape(role) + r":\s*(.*)", line)
                    if match:
                        if role in result["paths"]:
                            result["paths"][role] = "[Ambiguous: edit duplicate association in Project.md]"
                        else:
                            result["paths"][role] = match[1].strip().strip("`")
    return result


def edit_brief(original, name, description, goals, paths):
    if any(char in name for char in "\r\n") or not name.strip():
        raise ProjectError("Enter a project name on one line.")
    for label, value in (("Description", description), ("Goals", goals)):
        if sections(value.strip()):
            raise ProjectError(f"{label} cannot contain level-two Markdown headings (## ...), which divide Project.md into sections. Use ### ... instead. Your input is retained; nothing was saved.")
    if any("\n" in value or "\r" in value for value in paths.values()):
        raise ProjectError("Each artifact path must be on one line.")
    text = original or "# Project\n\nProgramming: NOT STARTED\nVerification: NOT STARTED\n\n"
    fields = metadata(text)
    if len(fields.get("Name", [])) > 1:
        raise ProjectError("Project.md has duplicate Name fields. Resolve those in the file before saving.")
    if "Name" in fields:
        at = 0
        for line in text.splitlines(keepends=True):
            if "Name" in metadata(line):
                text = text[:at] + f"Name: {name}\n" + text[at + len(line):]
                break
            at += len(line)
    else:
        title = re.match(r"# [^\r\n]*\r?\n", text)
        at = title.end() if title else 0
        text = text[:at] + f"\nName: {name}\n" + text[at:]
    for heading, value in (("Description", description), ("Goals", goals), ("Artifact Paths", paths)):
        found = [s for s in sections(text) if s[0] == heading]
        if len(found) > 1:
            raise ProjectError(f"Project.md has duplicate {heading} sections. Resolve those in the file before saving.")
        if heading == "Artifact Paths":
            old = text[found[0][2]:found[0][3]] if found else ""
            unknown = [line for line in old.splitlines() if line.strip() and not any(re.match(r"- " + re.escape(role) + r":", line) for role in ROLES)]
            value = "\n".join([f"- {role}: {paths[role]}" for role in ROLES if paths.get(role)] + unknown)
        replacement = f"## {heading}\n\n{value.strip()}\n\n"
        if found:
            _, start, _, end = found[0]
            text = text[:start] + replacement + text[end:]
        else:
            text = text.rstrip() + "\n\n" + replacement
    return text


class Project:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ProjectError("Select an existing project directory.")
        self.approved_references = set()

    def write_target(self, name):
        target = self.root / name
        if target.is_symlink() or target.resolve().parent != self.root:
            raise ProjectError(f"{name} cannot be a link or cross the project boundary.")
        if target.exists() and not target.is_file():
            raise ProjectError(f"{name} is not an ordinary file.")
        return target

    def brief_text(self):
        path = self.write_target("Project.md")
        return read_text(path) if path.exists() else None

    def brief(self):
        return parse_brief(self.brief_text() or "", self.root.name)

    def reference(self, role):
        if role not in ROLES:
            raise ProjectError("Unknown artifact role.")
        value = self.brief()["paths"].get(role, "")
        if not value:
            return None
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value):
            return value
        path = Path(value).expanduser()
        return path if path.is_absolute() else self.root / path

    def approve_reference(self, role, displayed_path):
        path = self.reference(role)
        if not isinstance(path, Path) or str(path) != displayed_path:
            raise ProjectError("The association changed. Review its current path before selecting it.")
        self.approved_references.add((role, str(path.resolve())))

    def material(self, role, sensitive=False):
        reference = self.reference(role)
        result = {"role": role, "path": str(reference or ""), "text": None, "reason": "", "needs_selection": False}
        if reference is None:
            result["reason"] = "Not associated. Use Edit Project to select an existing file."
            return result
        if sensitive:
            result["reason"] = "Marked sensitive by the user; reference only."
            return result
        if isinstance(reference, str):
            result["reason"] = "Remote reference; not fetched. Supply access separately to the recipient."
            return result
        resolved = reference.resolve()
        if resolved == (self.root / "Handoff.md").resolve() or resolved == (self.root / "Project.md").resolve():
            result["reason"] = "The overview and old handoff cannot be source artifacts."
            return result
        if not resolved.is_relative_to(self.root) and (role, str(resolved)) not in self.approved_references:
            result["reason"] = "Outside this project. Explicitly select this path before reading it."
            result["needs_selection"] = True
            return result
        if role == "Code":
            result["reason"] = "Code location only; this application is not a code browser."
            return result
        if reference.suffix.lower() not in {".md", ".markdown", ".txt"}:
            result["reason"] = "Not a Markdown or plain-text document; reference only."
            return result
        try:
            result["text"] = read_text(resolved)
        except (OSError, ProjectError) as error:
            result["reason"] = str(error)
        return result

    def save_brief(self, expected, name, description, goals, paths):
        current = self.brief_text()
        if current != expected:
            raise Conflict("Project.md changed since this form opened. Your input is retained. Review the current saved file before trying again.", current)
        if set(paths) - set(ROLES):
            raise ProjectError("Unknown artifact association.")
        # Canonicalize in-project paths for portability; external paths remain explicit.
        normalized = {}
        for role, value in paths.items():
            value = value.strip()
            if not value:
                continue
            if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value):
                path = Path(value).expanduser()
                resolved = (path if path.is_absolute() else self.root / path).resolve()
                if not path.is_absolute() and not resolved.is_relative_to(self.root):
                    raise ProjectError(f"{role} crosses the project boundary. Select its explicit absolute path instead.")
                value = str(resolved.relative_to(self.root)) if resolved.is_relative_to(self.root) else str(resolved)
                if resolved in {(self.root / "Project.md").resolve(), (self.root / "Handoff.md").resolve()}:
                    raise ProjectError("Project.md and Handoff.md cannot be selected as source artifacts.")
            normalized[role] = value
        updated = edit_brief(current or "", name, description, goals, normalized)
        if len(updated.encode("utf-8")) > READ_LIMIT:
            raise ProjectError("The project overview exceeds the reading ceiling; it was not saved.")
        atomic_write(self.write_target("Project.md"), updated)
        return self.snapshot()

    def handoff_text(self):
        path = self.write_target("Handoff.md")
        return read_text(path, PACKET_LIMIT) if path.exists() else None

    def save_packet(self, text, expected, selected_existing):
        target = self.write_target("Handoff.md")
        for role in ROLES:
            reference = self.reference(role)
            if isinstance(reference, Path) and (reference.resolve() == target.resolve() or (reference.exists() and target.exists() and os.path.samefile(reference, target))):
                raise ProjectError(f"Handoff.md collides with the {role} source. No file was changed.")
        brief = self.write_target("Project.md")
        if target.exists() and brief.exists() and os.path.samefile(target, brief):
            raise ProjectError("Handoff.md aliases Project.md. No file was changed.")
        current = self.handoff_text()
        if current is not None and not selected_existing:
            raise Conflict("Select the existing Handoff.md explicitly as the outgoing destination before replacing it.", current)
        if current != expected:
            raise Conflict("Handoff.md changed. Review the current file before preparing again.", current)
        if len(text.encode("utf-8")) > PACKET_LIMIT:
            raise ProjectError("The complete packet exceeds 4 MiB. Mark some materials reference-only; no content was truncated or saved.")
        atomic_write(target, text)
        return text

    def copy_snapshot(self, displayed):
        current = self.handoff_text()
        if current != displayed:
            raise Conflict("The saved handoff changed. Review the current saved text, then use Copy again. Nothing was overwritten.", current)
        if current is None:
            raise ProjectError("No saved handoff is available. Prepare again.")
        return current

    def snapshot(self):
        raw = self.brief_text()
        brief = parse_brief(raw or "", self.root.name)
        statuses = {}
        for stage, role in (("specification", "Specification"), ("planning", "Plan")):
            material = self.material(role)
            statuses[stage] = reported_status(stage, material["text"] or "", material["path"] or f"No {role} associated")
        for stage in ("programming", "verification"):
            statuses[stage] = reported_status(stage, raw or "", str(self.root / "Project.md"))
        return {**brief, "root": str(self.root), "raw": raw, "statuses": statuses,
                "handoff_exists": (self.root / "Handoff.md").exists(), "handoff_path": str(self.root / "Handoff.md")}


class ProjectStore:
    def __init__(self, home):
        self.home = Path(home).resolve(strict=True)
        if not self.home.is_dir():
            raise ProjectError("The projects home must be an existing directory.")
        self.projects = {}

    def open(self, path):
        project = Project(path)
        for key, known in self.projects.items():
            if known.root == project.root:
                return key
        key = secrets.token_urlsafe(12)
        self.projects[key] = project
        return key

    def list(self):
        for child in sorted(self.home.iterdir()):
            if child.is_dir() and child.resolve().parent == self.home:
                self.open(child)
        return [{"id": key, "name": project.root.name, "path": str(project.root)} for key, project in self.projects.items()]

    def create(self, directory, name, description, goals):
        if not directory or directory in {".", ".."} or "/" in directory or "\\" in directory or Path(directory).name != directory:
            raise ProjectError("Use one new child directory name, with no slashes or parent traversal.")
        root = self.home / directory
        root.mkdir()  # An existing directory is never overwritten.
        try:
            project = Project(root)
            project.save_brief(None, name, description, goals, {})
            return self.open(root)
        except Exception:
            # Only the empty operation-owned directory may be removed on failure.
            if not any(root.iterdir()):
                root.rmdir()
            raise
