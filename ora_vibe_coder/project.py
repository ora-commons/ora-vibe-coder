"""Ordinary Markdown project files, with explicit selection and narrow writes."""

import os
from pathlib import Path
import re
import secrets
import stat
import tempfile

from .status import (assessment_facts, body_start, document_type_values, metadata, reported_status,
                     reported_verdict, sections, legacy_review_basis, review_basis)

READ_LIMIT = 256 * 1024
PACKET_LIMIT = 4 * 1024 * 1024
# The five standard working documents come first; the roles after them are the
# recognized legacy vocabulary, retained so older files and saved associations
# keep working without migration.
ROLES = ("Registry", "Specification", "Plan", "Programming Result", "Verification Report",
         "Request", "User Guide", "Technical Documentation", "Product Overview",
         "Verification Findings", "Report", "Code", "Checks", "Baseline")
# Each role's default filename variants: the current plain name, then the older
# numbered form. A project's starter file, its legacy numbered file, and the
# "<Project Name> — <variant>" spelling all identify their own role.
DEFAULT_NAMES = {"Registry": ("Registry",), "Specification": ("Specification", "02 Specification"),
                 "Plan": ("Plan", "03 Implementation Plan"), "Programming Result": ("Programming Result",),
                 "Verification Report": ("Verification Report",), "Request": ("01 Request",),
                 "User Guide": ("04 User Guide",), "Technical Documentation": ("05 Technical Documentation",),
                 "Product Overview": ("06 Product Overview",), "Report": ("07 Report",)}
# Code, Checks and Baseline stay deliberate associations; discovery never guesses them.
DISCOVERABLE = ("Registry", "Specification", "Plan", "Programming Result", "Verification Report",
                "Request", "User Guide", "Technical Documentation", "Product Overview",
                "Verification Findings", "Report")
ROLE_WORDS = {
    "Registry": ("registry",),
    "Specification": ("spec", "specification"),
    "Plan": ("plan", "planning"),
    "User Guide": ("user guide", "guide"),
    "Technical Documentation": ("technical documentation", "technical doc", "documentation"),
    "Product Overview": ("product overview", "overview"),
    "Programming Result": ("programming result", "implementation result"),
    "Verification Report": ("verification report",),
    "Verification Findings": ("verification findings", "findings"),
    "Report": ("report",),
    "Request": ("request",),
}
READER_SUFFIXES = {".md", ".markdown", ".txt"}


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


def not_started(text):
    """An untouched starter template: headings present, every section body empty."""
    found = sections(text or "")
    return bool(found) and all(not (text or "")[body:end].strip() for _name, _start, body, end in found)


def starter_documents(name):
    """Minimal starter templates: project identification and empty headings only."""
    return {
        "Registry.md": (f"# {name} — Registry\n\nNotes, background, decisions, and open questions.\n\n"
                        "## Notes\n\n\n## Decisions\n\n\n## Open questions\n\n\n"),
        "Specification.md": (f"# {name} — Specification\n\nIntended behavior, requirements, and outcomes.\n\n"
                             "## Description\n\n\n## Requirements\n\n\n## Outcomes\n\n\n"),
        "Plan.md": (f"# {name} — Plan\n\nImplementation approach, steps, and checks.\n\n"
                    "## Approach\n\n\n## Steps\n\n\n## Checks\n\n\n"),
    }


def word_roles(text):
    """Whole-word role matches; no unrelated substrings such as specimen."""
    tokens = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    if not tokens:
        return set()
    roles = set()
    for role, words in ROLE_WORDS.items():
        for word in words:
            if re.search(rf"(?:^| ){re.escape(word)}(?: |$)", tokens):
                roles.add(role)
                break
    # The more specific document name wins: "verification report" also contains
    # the Report role's word, but names the Verification Report.
    if "Verification Report" in roles:
        roles.discard("Report")
    return roles


def is_outgoing_packet(text):
    """Recognize our complete packet shape even when its file was renamed."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.startswith("# User request\n\n"):
        return False
    at = 0
    for marker in (
        "\n\n---\n\n# Framework instructions\n\nThe user request above is preserved verbatim. The instruction section starts here.",
        "\n\nCanonical source: Ora Vibe Coder ",
        ", packaged frameworks and shared contract.\n\n",
        "\n\n# Locations, authority, and intended outputs\n\n",
        "\n\n# Current project materials — quoted data\n\n",
        "\n\n# Missing inputs and next action\n\n",
        "This is a prepared snapshot: later source changes require Prepare Again. No model has been called and no text has been delivered by the application.",
    ):
        found = text.find(marker, at)
        if found < 0:
            return False
        at = found + len(marker)
    return True


def parse_brief(text, fallback):
    fields = metadata(text)
    names = fields.get("Name", [])
    parent, archived, meta_notices = brief_facts(fields)
    # An explicitly blank Name line reads like a missing one: folder-name fallback.
    result = {"name": (names[0].strip() or fallback) if names else fallback,
              "description": "", "goals": "", "paths": {},
              "parent": parent, "archived": archived, "meta_notices": meta_notices}
    for name, start, body, end in sections(text):
        if name == "Description":
            result["description"] = text[body:end].strip()
        # "Desired outcome" is the current heading; "Goals" is the legacy one.
        if name in {"Desired outcome", "Goals"}:
            result["goals"] = text[body:end].strip()
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


def brief_facts(fields):
    """Parent lineage, archived state, and reading notices from overview fields.

    Only an unambiguous case-insensitive ARCHIVED value archives a project; any
    other non-empty value means active and is surfaced as a notice. Reading
    never hides a project.
    """
    parents = fields.get("Parent", [])
    states = fields.get("Project state", [])
    notices = []
    if len(parents) > 1:
        notices.append("Project.md has duplicate Parent fields; the first one is shown.")
    for value in states[:1]:
        if value.strip() and value.strip().casefold() not in {"active", "archived"}:
            notices.append(f"Project state {value.strip()!r} is not ACTIVE or ARCHIVED, so the project stays active.")
    if len(states) > 1:
        notices.append("Project.md has duplicate Project state fields; it is treated as active.")
    archived = len(states) == 1 and states[0].strip().casefold() == "archived"
    return (parents[0] if parents else ""), archived, notices


def display_label(parent, name, position=""):
    """The complete displayed lineage; full names are never reduced. An
    optional list position (a "Position:" line such as G1.3) leads it."""
    label = f"{parent.strip()} → {name}" if parent.strip() else name
    return f"{position} · {label}" if position else label


def position_key(position):
    """Natural order for list positions: G1.3 before G1.3.1 before G1.10."""
    return tuple((0, int(part), "") if part.isdecimal() else (1, 0, part.casefold())
                 for part in re.split(r"(\d+)", position) if part)


def inventory_order(item):
    """Positioned projects first, in list order; the rest by their label."""
    path, entry = item
    position = entry.get("position", "")
    return (0 if position else 1, position_key(position), entry["label"].casefold(), entry["label"], path)


def _field_line(label, value):
    return f"{label}: {value}".rstrip() + "\n"


def _place_field(text, label, value, anchors):
    """Replace one overview metadata line, or insert it below the first
    available anchor field (falling back to the opening title)."""
    fields = metadata(text)
    if len(fields.get(label, [])) > 1:
        raise ProjectError(f"Project.md has duplicate {label} fields. Resolve those in the file before saving.")
    if label in fields:
        at = 0
        for line in text.splitlines(keepends=True):
            if label in metadata(line):
                return text[:at] + _field_line(label, value) + text[at + len(line):]
            at += len(line)
    anchor = next((name for name in anchors if name in fields), None)
    if anchor is not None:
        at = 0
        for line in text.splitlines(keepends=True):
            if anchor in metadata(line):
                at += len(line)
                break
            at += len(line)
        return text[:at] + _field_line(label, value) + text[at:]
    title = re.match(r"(?:[ \t]*(?:\r\n|\r|\n))* {0,3}# [^\r\n]*(?:\r\n|\r|\n|$)", text)
    at = title.end() if title else 0
    return text[:at] + "\n" + _field_line(label, value) + text[at:]


def edit_brief(original, name, description, goals, paths, parent=None, state=None):
    if any(char in name for char in "\r\n") or not name.strip():
        raise ProjectError("Enter a project name on one line.")
    if parent is not None and any(char in parent for char in "\r\n"):
        raise ProjectError("Parent must be one line.")
    if state is not None and state.strip().upper() not in {"ACTIVE", "ARCHIVED"}:
        raise ProjectError("Project state accepts ACTIVE or ARCHIVED.")
    for label, value in (("Description", description), ("Desired outcome", goals)):
        if sections(value.strip()):
            raise ProjectError(f"{label} cannot contain level-two Markdown headings (## ...), which divide Project.md into sections. Use ### ... instead. Your input is retained; nothing was saved.")
    if any("\n" in value or "\r" in value for value in paths.values()):
        raise ProjectError("Each artifact path must be on one line.")
    text = original or "# Project\n\nProgramming: NOT STARTED\nVerification: NOT STARTED\n\n"
    start = body_start(text)
    if start is None:
        raise ProjectError("Project.md has unclosed YAML frontmatter. Close it before saving; nothing was changed.")
    fields = metadata(text)
    frontmatter, text = text[:start], text[start:]
    if len(fields.get("Name", [])) > 1:
        raise ProjectError("Project.md has duplicate Name fields. Resolve those in the file before saving.")
    text = _place_field(text, "Name", name, ())
    if parent is not None:
        text = _place_field(text, "Parent", parent, ("Name",))
    if state is not None:
        text = _place_field(text, "Project state", state.strip().upper(), ("Parent", "Name"))
    for heading, value in (("Description", description), ("Desired outcome", goals), ("Artifact Paths", paths)):
        if heading == "Desired outcome":
            # One goals slot: the current "Desired outcome" section or its
            # legacy "Goals" spelling, never both.
            found = [s for s in sections(text) if s[0].strip() in {"Desired outcome", "Goals"}]
            if len(found) > 1:
                raise ProjectError("Project.md has more than one Desired outcome (or legacy Goals) section. Resolve those in the file before saving.")
        else:
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
    return frontmatter + text


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

    def packet_path(self, purpose=None):
        name = self.implementation_request_name() if purpose == "implement-plan" else "Handoff.md"
        return self.write_target(name)

    def implementation_request_name(self):
        return f"{self.root.name} — Implementation Request.md"

    def brief_text(self):
        path = self.write_target("Project.md")
        return read_text(path) if path.exists() else None

    def brief(self):
        return parse_brief(self.brief_text() or "", self.root.name)

    def discover(self):
        """Resolve stage documents from the selected folder's ordinary Markdown.

        Rank: expected default name, then a scalar vibe_document type label in
        closed opening frontmatter or ordinary opening metadata, then whole
        role words in the filename. Within a rank: latest modification time,
        then stable filename order. Programming and Verification results use
        the latest modification time first so a newer numbered result can
        supersede the standard filename. An explicit association still wins.
        Project.md, outgoing packets and conflicting files are never selected.
        """
        from .status import document_type_values  # local alias kept for clarity
        result = {"resolved": {}, "conflicts": [], "candidates": {}}
        try:
            entries = sorted(self.root.iterdir(), key=lambda path: path.name)
        except OSError as error:
            result["conflicts"].append(f"The project folder could not be read: {error}")
            return result
        name = self.brief()["name"]
        expected = {}
        for role, variants in DEFAULT_NAMES.items():
            for variant in variants:
                expected.setdefault(variant, role)
                expected.setdefault(f"{name} — {variant}", role)
        candidates = {role: [] for role in DISCOVERABLE}
        for path in entries:
            if path.name.startswith(".") or not path.is_file() or path.suffix.lower() not in {".md", ".markdown"}:
                continue
            if path.name in {"Project.md", "Handoff.md", self.implementation_request_name()}:
                continue
            try:
                info = path.stat()
            except OSError:
                continue
            if not stat.S_ISREG(info.st_mode):
                continue
            try:
                text = read_text(path)
            except (OSError, ProjectError):
                text = None
            if text is not None and is_outgoing_packet(text):
                continue  # A renamed outgoing snapshot is never a revision target.
            values = document_type_values(text)
            if len(values) > 1:
                result["conflicts"].append(f"{path.name} carries duplicate vibe_document labels; choose the intended document with Choose File or correct the file externally.")
                continue
            name_roles = word_roles(path.stem)
            expected_role = expected.get(path.stem)
            roles, rank = None, None
            if values:
                # An explicit label controls; a disagreeing name or expectation is a conflict.
                label_roles = word_roles(values[0])
                others = set(name_roles) | ({expected_role} if expected_role else set())
                if len(label_roles) != 1 or (others and others != label_roles):
                    result["conflicts"].append(f"{path.name} explicitly identifies conflicting roles; choose the intended document with Choose File or correct the file externally.")
                    continue
                roles, rank = next(iter(label_roles)), 1
            elif expected_role:
                # The expected default name identifies its own role; other words
                # may come from the project's own name.
                roles, rank = expected_role, 0
            elif len(name_roles) == 1:
                roles, rank = next(iter(name_roles)), 2
            elif len(name_roles) > 1:
                result["conflicts"].append(f"{path.name} names more than one document role; choose the intended document with Choose File or correct the file externally.")
                continue
            if roles in candidates:
                candidates[roles].append((rank, info.st_mtime, path.name, path))
        for role, pool in candidates.items():
            if pool:
                result["candidates"][role] = [str(item[3]) for item in pool]
                if role in {"Programming Result", "Verification Report"}:
                    rank, _, _, path = min(pool, key=lambda item: (-item[1], item[0], item[2]))
                else:
                    rank, _, _, path = min(pool, key=lambda item: (item[0], -item[1], item[2]))
                result["resolved"][role] = {"path": str(path), "name": path.name, "rank": rank}
        return result

    def reference(self, role, discovery=None):
        if role not in ROLES:
            raise ProjectError("Unknown artifact role.")
        value = self.brief()["paths"].get(role, "")
        if value:
            if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value):
                return value
            path = Path(value).expanduser()
            path = path if path.is_absolute() else self.root / path
            if path.is_file():
                return path
        if role in DISCOVERABLE:
            found = discovery if discovery is not None else self.discover()
            resolved = found["resolved"].get(role)
            if resolved:
                return Path(resolved["path"])
        return None

    def approve_reference(self, role, displayed_path):
        path = self.reference(role)
        if not isinstance(path, Path) or str(path) != displayed_path:
            raise ProjectError("The association changed. Review its current path before selecting it.")
        self.approved_references.add((role, str(path.resolve())))

    def material(self, role, discovery=None):
        reference = self.reference(role, discovery)
        result = {"role": role, "path": str(reference or ""), "text": None, "reason": "", "needs_selection": False}
        if reference is None:
            result["reason"] = f"No {role} document is associated or discovered."
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

    def code_folder(self, brief=None):
        """The stored repository / code folder when it names an existing directory."""
        value = (brief or self.brief())["paths"].get("Code", "")
        if not value or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value):
            return None
        path = Path(value).expanduser()
        path = path if path.is_absolute() else self.root / path
        return path if path.is_dir() else None

    def _document_assessment(self, stage, role, discovery):
        """Advisory completeness facts read from the resolved stage document."""
        item = self.material(role, discovery=discovery)
        facts = assessment_facts(stage, item["text"] or "")
        if facts["applies"] == "unconfirmed" and facts["basis"] and not facts["issues"]:
            facts = assessment_facts(stage, item["text"] or "",
                                     self._reviewed_snapshots(role, item["path"], facts["basis"]))
        facts["path"] = item["path"]
        conflict = self._selection_conflict(role, discovery)
        if conflict:
            facts["issues"].append(conflict)
            facts["reason"] = conflict
        if item["text"] is None and item["path"]:
            # The document resolved but its content could not be read; that is
            # not the absence of an assessment, so the reason is carried for
            # truthful display.
            facts["unreadable"] = item["reason"]
        if not facts["present"] and item["text"] is not None and not_started(item["text"]):
            facts["untouched"] = True
        return facts

    def _reviewed_snapshots(self, role, path, basis):
        """Recover only exact matching document snapshots from retained requests."""
        digests = re.findall(r"(?<![0-9A-Za-z])[0-9a-f]{64}(?![0-9A-Za-z])", basis)
        if len(digests) != 1:
            return []
        pattern = re.compile(r"^## " + re.escape(role) + r"\n\nSource:\n\n(?P<pf>`{3,})text\n"
                             r"(?P<path>[^\n]+)\n(?P=pf)\n\n(?P<tf>`{3,})text\n"
                             r"(?P<document>.*?)\n(?P=tf)(?:\n|$)", re.M | re.S)
        for retained in sorted((self.root / ".vibe").glob("*/session/messages/*-initiator-to-peer.md"), reverse=True):
            if not retained.resolve().is_relative_to(self.root):
                continue
            try:
                request = read_text(retained, PACKET_LIMIT)
            except (OSError, ProjectError):
                continue
            if "# Review request\n" not in request:
                continue
            for match in pattern.finditer(request):
                if match["path"] != path:
                    continue
                document = match["document"]
                if digests[0] in {legacy_review_basis(document), review_basis(document)}:
                    return [document]
        return []

    def _selection_conflict(self, role, discovery):
        """A newest filename alone cannot settle different saved conclusions."""
        selected = self.reference(role, discovery)
        value = self.brief()["paths"].get(role)
        if value:
            if isinstance(selected, str):
                return ""
            associated = Path(value).expanduser()
            associated = associated if associated.is_absolute() else self.root / associated
            if associated.is_file():
                return ""
        stage = {"Specification": "specification", "Plan": "planning", "Programming Result": "programming",
                 "Verification Report": "verification"}.get(role)
        if stage is None:
            return ""
        conclusions = []
        for candidate in discovery.get("candidates", {}).get(role, []):
            if not Path(candidate).resolve().is_relative_to(self.root):
                continue
            try:
                text = read_text(candidate)
            except (OSError, ProjectError):
                continue
            if stage in {"specification", "planning"}:
                value = assessment_facts(stage, text)["verdict"]
            else:
                value = reported_status(stage, text, candidate, field="Status" if stage == "programming" else "Verdict")["label"]
                if value == "Not reported" or value.startswith("Unknown"):
                    value = ""
            if value:
                conclusions.append((candidate, value))
        if len({value for _, value in conclusions}) > 1:
            return ("Different candidate documents report conflicting current conclusions: " +
                    "; ".join(f"{Path(path).name}: {value}" for path, value in conclusions) +
                    ". The displayed file is selected by discovery; use Choose File to identify the current document.")
        return ""

    def reader_documents(self):
        """The saved text documents belonging to this project, for reading.

        Saved Markdown or plain-text files beneath the project folder, stopping
        at nested project roots, plus retained document associations with their
        existing reading protections. The outgoing handoff — including a
        recognized renamed copy — is never listed.
        """
        entries = []

        def walk(folder):
            try:
                children = sorted(folder.iterdir(), key=lambda path: path.name.casefold())
            except OSError:
                return
            for path in children:
                if path.name.startswith(".") or path.is_symlink():
                    continue
                try:
                    if path.is_dir():
                        # A subdirectory with its own Project.md is a nested
                        # project: a boundary, not part of this project.
                        if not (path / "Project.md").exists():
                            walk(path)
                        continue
                    info = path.stat()
                except OSError:
                    continue
                if not stat.S_ISREG(info.st_mode) or path.suffix.lower() not in READER_SUFFIXES:
                    continue
                if path.name == "Project.md" or path.name == "Handoff.md":
                    continue
                try:
                    text = read_text(path, PACKET_LIMIT if path.name == self.implementation_request_name() and path.parent == self.root else READ_LIMIT)
                except (OSError, ProjectError):
                    text = None
                if text is not None and is_outgoing_packet(text) and path != self.root / self.implementation_request_name():
                    continue
                entries.append({"name": path.name, "path": path.relative_to(self.root).as_posix(),
                                "origin": "folder", "not_started": not_started(text) if text is not None else False,
                                "unreadable": text is None})

        walk(self.root)
        seen = {entry["path"] for entry in entries}
        for role in DISCOVERABLE:
            reference = self.reference(role)
            if not isinstance(reference, Path):
                continue
            resolved = reference.resolve()
            inside = resolved.is_relative_to(self.root)
            key = resolved.relative_to(self.root).as_posix() if inside else str(resolved)
            if key in seen or not resolved.is_file():
                continue
            seen.add(key)
            entries.append({"name": reference.name, "path": key, "origin": "association",
                            "role": role, "not_started": False, "unreadable": False,
                            "needs_selection": not inside and (role, str(resolved)) not in self.approved_references})
        return sorted(entries, key=lambda entry: (entry["path"].casefold(), entry["path"]))

    def read_reader_document(self, path):
        """Read one listed reader document; associations keep their protections."""
        for entry in self.reader_documents():
            if entry["path"] == path:
                result = {"path": path, "name": entry["name"], "text": None,
                          "reason": "", "needs_selection": False, "not_started": entry["not_started"]}
                if entry.get("needs_selection"):
                    result["reason"] = "Outside this project. Explicitly select this path before reading it."
                    result["needs_selection"] = True
                    result["role"] = entry.get("role")
                    return result
                target = Path(path)
                target = target if target.is_absolute() else self.root / target
                try:
                    result["text"] = read_text(target.resolve(), PACKET_LIMIT if target == self.root / self.implementation_request_name() else READ_LIMIT)
                except (OSError, ProjectError) as error:
                    result["reason"] = str(error)
                return result
        raise ProjectError("That document is not part of this project's reading list.")

    def overview_sources(self, discovery=None):
        """Description/mission/goals sections found in resolved project documents."""
        sources = []
        for role in ("Request", "Product Overview"):
            item = self.material(role, discovery=discovery)
            if item["text"] is None:
                continue
            found = {}
            for name, _start, body, end in sections(item["text"]):
                if name.strip() in {"Description", "Mission", "Goals"} and name.strip() not in found:
                    found[name.strip()] = item["text"][body:end].strip()
            if found:
                sources.append({"role": role, "name": Path(item["path"]).name, "sections": found})
        return sources

    def save_brief(self, expected, name, description, goals, paths, parent=None, state=None):
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
        updated = edit_brief(current or "", name, description, goals, normalized, parent=parent, state=state)
        if len(updated.encode("utf-8")) > READ_LIMIT:
            raise ProjectError("The project overview exceeds the reading ceiling; it was not saved.")
        atomic_write(self.write_target("Project.md"), updated)
        return self.snapshot()

    def handoff_text(self, purpose=None):
        path = self.packet_path(purpose)
        return read_text(path, PACKET_LIMIT) if path.exists() else None

    def save_packet(self, text, purpose=None, expected=None):
        target = self.packet_path(purpose)
        discovery = self.discover()
        for role in ROLES:
            reference = self.reference(role, discovery)
            if isinstance(reference, Path) and (reference.resolve() == target.resolve() or (reference.exists() and target.exists() and os.path.samefile(reference, target))):
                raise ProjectError(f"{target.name} collides with the {role} source. No file was changed.")
        brief = self.write_target("Project.md")
        if target.exists() and brief.exists() and os.path.samefile(target, brief):
            raise ProjectError(f"{target.name} aliases Project.md. No file was changed.")
        if len(text.encode("utf-8")) > PACKET_LIMIT:
            raise ProjectError("The complete packet exceeds 4 MiB. Mark some materials reference-only; no content was truncated or saved.")
        current = read_text(target, PACKET_LIMIT) if target.exists() else None
        if current != expected:
            raise Conflict("The saved request changed or already exists. Review it before preparing again. Nothing was overwritten.", current)
        atomic_write(target, text)
        return text

    def copy_snapshot(self, displayed, purpose=None):
        current = self.handoff_text(purpose)
        if current != displayed:
            raise Conflict("The saved request changed. Review the current saved text, then use Copy again. Nothing was overwritten.", current)
        if current is None:
            raise ProjectError("No saved request is available. Prepare again.")
        return current

    def snapshot(self):
        raw = self.brief_text()
        brief = parse_brief(raw or "", self.root.name)
        discovery = self.discover()
        documents = {}
        for role in DISCOVERABLE:
            entry = {"path": None, "name": None, "origin": None, "note": ""}
            value = brief["paths"].get(role, "")
            remote = bool(value) and bool(re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value))
            associated = None
            if value and not remote:
                candidate = Path(value).expanduser()
                associated = candidate if candidate.is_absolute() else self.root / candidate
            if remote:
                entry.update(path=value, name=value, origin="association")
            elif associated is not None and associated.is_file():
                entry.update(path=str(associated), name=associated.name, origin="association")
            elif value:
                entry["note"] = f"The associated {role} file is not available; discovery checked the project folder."
                resolved = discovery["resolved"].get(role)
                if resolved:
                    entry.update(path=resolved["path"], name=resolved["name"], origin="discovered")
            else:
                resolved = discovery["resolved"].get(role)
                if resolved:
                    entry.update(path=resolved["path"], name=resolved["name"], origin="discovered")
            documents[role] = entry
        statuses = {}
        for stage, role in (("specification", "Specification"), ("planning", "Plan")):
            item = self.material(role, discovery=discovery)
            statuses[stage] = reported_status(stage, item["text"] or "", item["path"] or f"No {role} document")
        for stage in ("programming", "verification"):
            statuses[stage] = reported_status(stage, raw or "", str(self.root / "Project.md"))
        # Saved result documents govern the prominent outcome displays; the
        # Project.md fields remain separately reported history.
        result = self.material("Programming Result", discovery=discovery)
        programming_result = {"path": result["path"],
                              "status": {**reported_status("programming", result["text"] or "",
                                                           result["path"] or "No Programming Result document", field="Status"),
                                         "unreadable": result["reason"] if result["path"] and result["text"] is None else ""}}
        report = self.material("Verification Report", discovery=discovery)
        verification = {"path": report["path"], "name": Path(report["path"]).name if report["path"] else None,
                        "verdict": reported_verdict(report["text"] or ""),
                        "status": reported_status("verification", report["text"] or "",
                                                  report["path"] or "No Verification Report document", field="Verdict") |
                                  {"unreadable": report["reason"] if report["path"] and report["text"] is None else ""},
                        "legacy_field": statuses["verification"]["literal"]}
        for role, outcome in (("Programming Result", programming_result), ("Verification Report", verification)):
            conflict = self._selection_conflict(role, discovery)
            if conflict:
                outcome["status"].update(label="Unknown — conflicting candidate documents", kind="neutral", icon="○",
                                         reason=conflict)
                documents[role]["note"] = conflict
                if role == "Verification Report":
                    outcome["verdict"] = ""
        return {**brief, "root": str(self.root), "raw": raw, "statuses": statuses,
                "documents": documents, "discovery_conflicts": discovery["conflicts"],
                "overview_sources": self.overview_sources(discovery),
                "assessments": {stage: self._document_assessment(stage, role, discovery)
                                for stage, role in (("specification", "Specification"), ("planning", "Plan"))},
                "reader": self.reader_documents(), "programming_result": programming_result,
                "verification": verification,
                "code_folder": str(folder) if (folder := self.code_folder(brief)) else None,
                "handoff_exists": (self.root / "Handoff.md").exists(), "handoff_path": str(self.root / "Handoff.md"),
                "implementation_request_path": str(self.root / self.implementation_request_name())}


class ProjectStore:
    def __init__(self, home):
        self.home = Path(home).resolve(strict=True)
        if not self.home.is_dir():
            raise ProjectError("The projects home must be an existing directory.")
        self.projects = {}
        self.inventory = {}
        self.scan_notices = []
        self.scan()

    def open(self, path):
        project = Project(path)
        for key, known in self.projects.items():
            if known.root == project.root:
                return key
        key = secrets.token_urlsafe(12)
        self.projects[key] = project
        return key

    def _read_entry(self, root):
        """One definition's inventory facts, or a notice when it cannot be read."""
        target = root / "Project.md"
        try:
            if target.is_symlink():
                return None, f"{target} is a symbolic link, so it is not read as a project definition."
            if not stat.S_ISREG(target.stat().st_mode):
                return None, f"{target} is not an ordinary file, so it is not read as a project definition."
            text = read_text(target)
        except (OSError, ProjectError) as error:
            return None, f"{target} could not be read: {error}"
        fields = metadata(text)
        names = fields.get("Name", [])
        name = (names[0].strip() or root.name) if names else root.name
        parent, archived, notices = brief_facts(fields)
        positions = fields.get("Position", [])
        position = positions[0].strip() if positions else ""
        entry = {"name": name, "parent": parent, "position": position,
                 "label": display_label(parent, name, position),
                 "archived": archived, "notice": " ".join(notices), "path": str(root)}
        return entry, ""

    def scan(self):
        """Recursive read-only discovery of Project.md beneath the home folder.

        Folder links are not followed, so discovery stays inside the boundary;
        unreadable folders and definitions are noticed per entry and never hide
        the readable ones. Handles are never discarded, so an open session
        keeps its project even after the entry leaves the inventory.
        """
        entries, notices = {}, []

        def unreadable(error):
            notices.append(f"A folder could not be read while searching for projects: {error}")

        for folder, directories, files in os.walk(self.home, followlinks=False, onerror=unreadable):
            # The project's retained conversation records live under the
            # reserved .vibe/ name; it is skipped so retained packets can never
            # create false projects. Other hidden content stays discoverable.
            directories[:] = [name for name in directories if name != ".vibe"]
            if "Project.md" not in files:
                continue
            root = Path(folder)
            entry, notice = self._read_entry(root)
            if notice:
                notices.append(notice)
            if entry is None:
                continue
            try:
                entry["id"] = self.open(root)
            except (OSError, ProjectError) as error:
                notices.append(f"{root / 'Project.md'} could not be opened as a project: {error}")
                continue
            entries[str(root)] = entry
        self.inventory = dict(sorted(entries.items(),
                                     key=inventory_order))
        self.scan_notices = notices

    def refresh_entry(self, root):
        """Update one inventory entry from its saved definition; no rescan."""
        try:
            root = Path(root).resolve(strict=True)
        except OSError:
            return
        if not root.is_relative_to(self.home):
            return  # Outside the discovery boundary; the manual route stays unchanged.
        entry, _ = self._read_entry(root)
        if entry is None:
            self.inventory.pop(str(root), None)
            return
        entry["id"] = self.open(root)
        self.inventory[str(root)] = entry
        self.inventory = dict(sorted(self.inventory.items(),
                                     key=inventory_order))

    def list(self, include_archived=False):
        return [{"id": entry["id"], "name": entry["name"], "label": entry["label"], "parent": entry["parent"],
                 "path": entry["path"], "archived": entry["archived"], "notice": entry["notice"],
                 "position": entry.get("position", ""),
                 # The lineage without the position: what a new subproject's
                 # Parent line copies, so it never freezes a list position.
                 "lineage": display_label(entry["parent"], entry["name"])}
                for entry in self.inventory.values() if include_archived or not entry["archived"]]

    def rescan(self):
        self.scan()
        return self.list(include_archived=True)

    def create(self, directory, name, description, goals, parent="", under=None, code=""):
        if not directory or directory in {".", ".."} or "/" in directory or "\\" in directory or Path(directory).name != directory:
            raise ProjectError("Use one new child directory name, with no slashes or parent traversal.")
        base = self.home if under is None else Path(under).expanduser().resolve(strict=True)
        if base != self.home and not base.is_relative_to(self.home):
            raise ProjectError("Choose the parent folder inside the projects home; destinations outside it are refused.")
        root = base / directory
        root.mkdir()  # An existing directory is never overwritten.
        created = []
        try:
            project = Project(root)
            project.save_brief(None, name, description, goals,
                               {"Code": code} if code else {}, parent=parent, state="ACTIVE")
            created.append(root / "Project.md")
            for filename, text in starter_documents(name).items():
                target = root / filename
                if target.exists():
                    raise ProjectError(f"{filename} already exists; existing files are never replaced.")
                atomic_write(target, text)
                created.append(target)
            key = self.open(root)
            self.refresh_entry(root)
            return key
        except Exception:
            # A failed attempt removes only the files it created, and the folder
            # only when that leaves it empty.
            for target in created:
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                if not any(root.iterdir()):
                    root.rmdir()
            except OSError:
                pass
            raise
