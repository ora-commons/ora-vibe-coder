"""Read a document's verdict from its opening YAML alone, keeping approval
and evidence separate.

A verdict is the document's opening YAML `status` (or `review`) field matched
exactly against one allowed list. Report prose never decides, changes or
overrides a verdict; the body keeps only explanations, evidence bases and
per-finding lines."""

import hashlib
import re

FIELD = r"([*`_]*)([A-Za-z][A-Za-z0-9_ -]*?)[*`_]*\s*:\s*(.*)"
# Opening fields whose recording must not change a document's evidence basis.
RECORDING_FIELDS = {"vibe_document", "status", "disposition", "accepted by", "accepted basis",
                    "review", "review stage", "review verdict", "review basis", "review findings",
                    "basis format"}
REVIEW_HEADING = "Current review"
STAGE_LABELS = {"specification": {"specification", "spec"},
                "planning": {"plan", "planning", "implementation plan"}}


def body_start(text):
    """Locate the body after leading YAML; None means the block is unclosed."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip() != "---":
        return 0
    at = len(lines[0])
    for line in lines[1:]:
        at += len(line)
        if line.rstrip() in {"---", "..."}:
            return at
    return None


def sections(text):
    headings, fence, at = [], None, 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = None
        elif marker:
            fence = marker[1]
        elif line.startswith("## "):
            headings.append((stripped[3:], at, at + len(line.rstrip("\n\r"))))
        at += len(line)
    return [(name, start, end, headings[i + 1][1] if i + 1 < len(headings) else len(text))
            for i, (name, start, end) in enumerate(headings)]


def metadata(text):
    fields = {}
    start = body_start(text)
    if start is None:
        return fields
    title_seen = False
    for line in text[start:].replace("\r\n", "\n").replace("\r", "\n").splitlines():
        # Four spaces (or a tab to that column) starts Markdown code, not metadata.
        if line.strip() and re.match(r"(?: {4}| {0,3}\t)", line):
            break
        line = line.strip().removesuffix("\\").rstrip()
        if line.startswith(("```", "~~~")):
            break
        if not line:
            continue
        if line.startswith("# ") and not fields and not title_seen:
            title_seen = True
            continue
        match = re.fullmatch(FIELD, line)
        if not match:
            break
        name = match[2].strip()
        value = match[3].strip()
        # When the whole field is bold, an explanation after its closing
        # marker is prose, not part of the recorded value.
        if match[1] == "**" and line.startswith(f"**{name}:") and not line.startswith(f"**{name}:**"):
            value = re.split(r"\*\*(?=\s|$)", value, maxsplit=1)[0]
        value = value.strip("*`_").strip()
        fields.setdefault(name, []).append(value)
    return fields


def frontmatter_fields(text):
    """Read opening scalar fields while leaving unrelated vault YAML alone:
    nested collections stay unread, only scalar fields are interpreted."""
    lines = normalized(text).splitlines()
    if not lines or lines[0] != "---":
        return None
    fields, flow = {}, []
    scalar_parent = ""
    for line in lines[1:]:
        if line in {"---", "..."}:
            if flow:
                fields.setdefault("__error__", []).append("An opening YAML flow collection is not closed.")
            return fields
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1].isspace() and not flow:
            if scalar_parent:
                fields.setdefault("__error__", []).append(f"YAML {scalar_parent} must be one scalar value, without nested content.")
            continue
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_ -]*?)\s*:\s*(.*)", line)
        if flow:
            value = line.strip()
        elif not match:
            fields.setdefault("__error__", []).append("Malformed opening YAML: " + line)
            continue
        else:
            value = match[2].strip()
            scalar_parent = match[1].casefold() if match[1].casefold() in {"status", "review", "disposition"} else ""
        # Scalar/flow syntax checks only; unrelated collections keep their bytes.
        if flow or value.startswith(("[", "{")):
            tokens = re.findall(r'''"(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|\s+#.*|[\[\]{}]''', value)
            for token in tokens:
                if token.startswith(("'", '"')) or token.lstrip().startswith("#"):
                    continue
                if token in {"[", "{"}:
                    flow.append(token)
                elif not flow or flow.pop() != {"]": "[", "}": "{"}[token]:
                    fields.setdefault("__error__", []).append("Mismatched YAML flow collection delimiters.")
            if not match:
                continue
        if not match:
            fields.setdefault("__error__", []).append("Malformed opening YAML: " + line)
            continue
        if value.startswith(('"', "'")):
            quoted = re.fullmatch(r'''("(?:[^"\\]|\\.)*"|'(?:[^']|'')*')(?:\s+#.*)?''', value)
            if quoted:
                value = quoted[1][1:-1]
            else:
                fields.setdefault("__error__", []).append("Malformed quoted YAML scalar: " + line)
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
            if not value.startswith(("[", "{")) and re.search(r":(?:\s|$)", value):
                fields.setdefault("__error__", []).append("Malformed plain YAML scalar: " + line)
            if match[1].casefold() in {"status", "review"} and value.casefold() in {"null", "~"}:
                value = ""
        fields.setdefault(match[1].strip(), []).append(value)
    return {"__error__": ["The opening YAML block is not closed."]}


def yaml_value(text, key):
    """One opening YAML field's exact scalar value. A quoted scalar's content
    is compared exactly as written, never trimmed to fit an allowed list."""
    fields = frontmatter_fields(text)
    if fields is None:
        return None, ""
    values = [value for name, items in fields.items()
              if name.casefold() == key.casefold() for value in items]
    if fields.get("__error__"):
        return None, " ".join(fields["__error__"])
    if len(values) > 1:
        return None, f"Duplicate {key} fields in opening YAML: " + ", ".join(values) + "."
    return (values[0] if values else None), ""


def set_yaml_fields(text, **updates):
    """Change only owned scalar fields; preserve all other YAML verbatim."""
    start = body_start(text)
    if start is None:
        raise ValueError("The opening YAML block is not closed.")
    newline = "\r\n" if "\r\n" in text else "\n"
    front = text[:start].splitlines(keepends=True) if start else ["---" + newline, "---" + newline]
    for key, value in updates.items():
        matches = [i for i, line in enumerate(front[1:-1], 1)
                   if re.match(re.escape(key) + r"\s*:", line, re.I)]
        if len(matches) > 1:
            raise ValueError(f"Duplicate {key} fields in opening YAML.")
        replacement = f"{key}: {value}" + newline
        if matches:
            front[matches[0]] = replacement
        else:
            front.insert(len(front) - 1, replacement)
    body = text[start:]
    # A bare body field of the same name would contradict the new YAML value
    # for a human reader, so re-label it while keeping any explanation attached
    # to its scalar. It may carry a scope or delivery obligation.
    opening = metadata(body)
    for key in updates:
        for label in opening:
            if label.casefold() == key.casefold():
                pattern = r"(?m)^([*`_]*" + re.escape(label) + r"[*`_]*[^\S\r\n]*:[^\S\r\n]*[*`_]*)([^\r\n]*)(?:\r?\n|$)"
                def replace(match):
                    values = VALUES["specification"] if key == "status" else REVIEW_VALUES
                    scalar = re.match("(?:" + "|".join(re.escape(v) for v in sorted(values, key=len, reverse=True)) + r")\b([*`_]*)(.*)", match[2])
                    if scalar and scalar[2].strip():
                        return match[1] + str(updates[key]) + scalar[1] + scalar[2] + newline
                    return "" if scalar else match[0]
                body = re.sub(pattern, replace, body, count=1)
    return "".join(front) + body


def meaning_text(text):
    """Deterministic equivalence only: recording details and Markdown layout.

    Keep code, case, punctuation and link destinations. Other word changes need
    an actual comparison of meaning, never a hash-based materiality guess.
    """
    content = basis_text(text)
    fence, lines = None, []
    for line in content.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            if fence and marker[1][0] == fence[0]:
                fence = None
            elif not fence:
                fence = marker[1]
            lines.append(line)
        elif fence or re.match(r"^(?: {4}|\t)", line):
            lines.append(line)
        else:
            heading = re.match(r"^\s*#{1,6}\s+", line)
            line = re.sub(r"^\s*#{1,6}\s+", "", line)
            line = re.sub(r"^\s*[-*+]\s+", "", line)
            # Only this unambiguous heading decoration is equivalent without
            # judgment. Preserve code, links, escapes and literal punctuation.
            if heading and not any(char in line for char in "`[]\\"):
                emphasis = re.fullmatch(r"(\*\*|__)(\S(?:.*\S)?)\1\s*", line)
                if emphasis:
                    line = emphasis[2]
            if line.strip():
                lines.append(line if any(char in line for char in "`[]\\") else " ".join(line.split()))
    return "\n".join(lines)


def document_type_values(text):
    """Scalar vibe_document marker from closed frontmatter or opening metadata."""
    if not text:
        return []
    values = []
    front = frontmatter_fields(text)
    if front is not None:
        values.extend(front.get("vibe_document", []))
    values.extend(metadata(text).get("vibe_document", []))
    return values


def normalized(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _recorded(line):
    match = re.fullmatch(FIELD, line.strip().removesuffix("\\").rstrip())
    return bool(match) and match[2].strip().lower() in RECORDING_FIELDS


def _drop_recorded_opening(text, preserve_explanations=False):
    """Remove review/acceptance/marker fields from the opening metadata only."""
    lines = text.split("\n")
    kept = []
    title_seen = False
    fields_seen = False
    for index, line in enumerate(lines):
        # Mirror metadata(): the opening region runs to the first code/indent
        # block, fence, or non-field line; a title may open it.
        if line.strip() and re.match(r"(?: {4}| {0,3}\t)", line):
            kept.extend(lines[index:])
            return "\n".join(kept)
        if line.strip().startswith(("```", "~~~")):
            kept.extend(lines[index:])
            return "\n".join(kept)
        if not line.strip():
            kept.append(line)
            continue
        if line.startswith("# ") and not fields_seen and not title_seen:
            title_seen = True
            kept.append(line)
            continue
        if _recorded(line):
            if preserve_explanations:
                match = re.fullmatch(FIELD, line.strip())
                if match[2].strip().casefold() == "status":
                    scalar = re.match(r"[*`_]*(?:" + "|".join(re.escape(value) for value in sorted(VALUES["specification"] | VALUES["planning"], key=len, reverse=True)) + r")\b[*`_]*(.*)", match[3])
                    if scalar and scalar[1].strip():
                        kept.append(scalar[1].strip())
            continue
        if re.fullmatch(FIELD, line.strip().removesuffix("\\").rstrip()):
            fields_seen = True
            kept.append(line)
        else:
            kept.extend(lines[index:])
            return "\n".join(kept)
    return "\n".join(kept)


def basis_text(text):
    """Exclude managed dates and recording fields, including below frontmatter."""
    text = normalized(text)
    kept, at = [], 0
    for name, start, _, end in sections(text):
        if name.strip().casefold() == REVIEW_HEADING.casefold():
            kept.append(text[at:start])
            at = end
    kept.append(text[at:])
    text = "".join(kept)
    start = body_start(text)
    if start is None:
        return text
    front = ""
    if start:
        lines = text[:start].splitlines()
        inner = [line for line in lines[1:-1]
                 if line.strip() and not _recorded(line)
                 and not re.match(r"\s*date (?:created|modified)\s*:", line, re.I)]
        if inner:
            front = "\n".join(["---", *inner, "---"]) + "\n"
    return (front + _drop_recorded_opening(text[start:], preserve_explanations=True)).strip("\n") + "\n"


def review_basis(*texts):
    """Standard-library SHA-256 over the substantive material, content only."""
    joined = "\n\x1e\n".join(basis_text(text) for text in texts if text)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def assessment_facts(stage, text, reviewed_texts=()):
    """Read one document's saved assessment: its YAML review value, with the
    Current review section supplying the explanation, stage and evidence basis.

    The verdict comes only from the opening YAML `review` field. A document
    without it is unreviewed, whatever its retained review text says; that text
    stays visible in the document and the conversation."""
    result = {"present": False, "stage": "", "verdict": "", "basis": "",
              "findings": None, "applies": "", "issues": [], "reason": ""}
    text = text or ""
    yaml_review, review_error = yaml_value(text, "review")
    yaml_status, status_error = yaml_value(text, "status")
    if not status_error and yaml_status is not None and yaml_status not in VALUES[stage]:
        status_error = "Unknown YAML status value: " + (yaml_status or "(blank)")
    error = review_error or status_error
    if not error and yaml_review not in (None, "") and yaml_review not in REVIEW_VALUES:
        error = "Unknown YAML review value: " + yaml_review
    if error:
        result["present"] = True
        result["issues"].append(error)
        return result
    if yaml_review in (None, ""):
        return result  # No recorded verdict: NOT REVIEWED, whatever the body says.
    result.update(present=True, verdict=yaml_review, applies="unconfirmed")
    if yaml_review == "CHANGED":
        result.update(applies="earlier",
                      reason="The document changed materially; the retained assessment describes an earlier version.")
        return result
    found = [s for s in sections(text) if s[0].strip().lower() == REVIEW_HEADING.lower()]
    if not found:
        return result
    # The body facts below decide only whether the saved assessment applies to
    # this document version; they never change or override the YAML verdict.
    if len(found) > 1:
        result["reason"] = "More than one Current review section; which saved assessment applies is unconfirmed."
        return result
    body = text[found[0][2]:found[0][3]]
    fields = metadata(body)
    stage_values = list(dict.fromkeys(_field_values(fields, "Stage", "Review stage")))
    basis_values = list(dict.fromkeys(_field_values(fields, "Basis", "Basis as supplied", "Review basis")))
    if len(stage_values) > 1 or (stage_values and not stage_values[0]):
        result["reason"] = "The Current review has conflicting or empty stage labels; applicability is unconfirmed."
        return result
    result["stage"] = stage_values[0] if stage_values else {"specification": "Specification", "planning": "Plan"}[stage]
    if len(basis_values) > 1 or (basis_values and not basis_values[0]):
        result["reason"] = "The Current review has conflicting or empty basis labels; applicability is unconfirmed."
        return result
    result["basis"] = basis_values[0] if basis_values else ""
    if result["stage"].lower() not in STAGE_LABELS.get(stage, set()):
        result["reason"] = (f"The Current review section names stage {result['stage']!r}, not this document's "
                            "stage; applicability is unconfirmed.")
        return result
    digest = result["basis"]
    if digest:
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            # The basis field may explain or quote its one fingerprint.
            # The label supplies its meaning; the AI need not say SHA-256.
            digests = re.findall(r"(?<![0-9A-Za-z])[0-9a-f]{64}(?![0-9A-Za-z])", digest)
            if len(digests) != 1:
                result["reason"] = "The recorded assessment basis is ambiguous; applicability is unconfirmed."
                return result
            digest = digests[0]
        if digest == review_basis(text):
            result["applies"] = "current"
        else:
            matched = next((old for old in reviewed_texts
                            if digest == review_basis(old)), None)
            if matched is not None:
                result["applies"] = "current" if meaning_text(matched) == meaning_text(text) else "unconfirmed"
                result["reason"] = ("Compared with the retained reviewed document; " +
                                    ("only recording details changed." if result["applies"] == "current"
                                     else "the document content has changed since this review."))
            elif _field_values(fields, "Basis format") == ["content-v2"]:
                result["reason"] = "The text differs from the recorded review basis, so the assessment applies to an earlier version."
            else:
                result["reason"] = "The saved legacy fingerprint differs; no matching reviewed document is available to establish what changed."
    else:
        result["reason"] = "The review states its conclusion but does not identify the reviewed document version."
    if result["verdict"] in {"NOT PASSED", "INCOMPLETE"}:
        # Each noted deficiency is one list bullet; an absent list is an
        # unknown count, never zero.
        bullets = re.findall(r"^[-*] +\S", body, re.M)
        result["findings"] = len(bullets) or None
    return result


#: The one allowed routing decision on review reports and correction results.
DISPOSITION_VALUES = ("SETTLED", "CORRECTION", "SEVERE", "INCOMPLETE", "ASK USER")


def review_disposition(text):
    """The document's opening YAML ``disposition`` field, or '' when missing,
    duplicate, malformed or off-list. Missing never means settled."""
    value, error = yaml_value(text or "", "disposition")
    return value if not error and value in DISPOSITION_VALUES else ""


def _live_lines(text):
    """Yield lines outside fenced code blocks and quotations, in order:
    quoted examples are not live content for the per-finding readers below."""
    fence = None
    for line in (text or "").splitlines():
        stripped = line.strip()
        if fence is not None:
            if stripped.startswith(fence):
                fence = None
            continue
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            fence = marker[1]
            continue
        if stripped.startswith(">"):
            continue
        yield line


#: One recorded builder decision in a correction result: the finding it
#: settles, the decision, and a nonempty reason — `- R1 — FIXED — evidence`.
_CORRECTION_DISPOSITION = re.compile(r"^[-*] +(\S+) — (FIXED|REJECTED) — (\S.*)$")


def correction_dispositions(text):
    """The recorded per-finding decisions in a correction result: each entry
    ``(label, decision, reason)`` from one live line. A severe finding only
    settles through a FIXED entry with its evidence."""
    entries = []
    for line in _live_lines(text):
        match = _CORRECTION_DISPOSITION.match(line)
        if match is not None:
            entries.append((match.group(1), match.group(2), match.group(3).strip()))
    return entries


#: One enumerated finding in a Verification Report: the stable label the
#: correction cites back — `- R1 — <finding>`, and `S1` for severe findings.
_FINDING_ENTRY = re.compile(r"^[-*] +([RS]\d+)\b")


def verification_finding_labels(text):
    """The distinct R/S finding labels a Verification Report enumerated, each
    on its own line; a severe (S) label settles only through its own FIXED
    entry."""
    labels = []
    for line in _live_lines(text):
        match = _FINDING_ENTRY.match(line)
        if match is not None and match.group(1) not in labels:
            labels.append(match.group(1))
    return labels


#: The allowed `review` values on a Specification or Plan.
REVIEW_VALUES = {"PASSED", "NOT PASSED", "INCOMPLETE", "CHANGED"}
VALUES = {
    "specification": {"DRAFT", "IN PROGRESS", "AWAITING APPROVAL", "APPROVED"},
    "planning": {"DRAFT", "IN PROGRESS", "AWAITING APPROVAL", "APPROVED"},
    "programming": {"PASSED", "NOT PASSED", "INCOMPLETE", "CLOSED BY USER — UNRESOLVED FINDINGS"},
    "verification": {"PASSED", "NOT PASSED", "INCOMPLETE", "CLOSED BY USER — UNRESOLVED FINDINGS"},
}


def _field_values(fields, *names):
    wanted = {name.casefold() for name in names}
    return [value.strip() for name, values in fields.items() if name.casefold() in wanted for value in values]


def reported_status(stage, text, source):
    """The document's verdict: its opening YAML ``status`` field, matched
    exactly against the stage's allowed values."""
    value, error = yaml_value(text or "", "status")
    kind = "neutral"
    if error:
        label = "Unknown — " + error
    elif value is None:
        label = "Not reported"
    elif value not in VALUES[stage]:
        label = "Unknown — YAML status value: " + (value or "(blank)")
    else:
        label = value
        kind = {"APPROVED": "positive", "PASSED": "positive",
                "DRAFT": "working", "IN PROGRESS": "working", "AWAITING APPROVAL": "working"}.get(label, "attention")
    return {"label": label, "kind": kind, "source": source, "literal": value or "",
            "icon": {"neutral": "○", "working": "◷", "positive": "✓", "attention": "!"}[kind],
            "reason": label if label.startswith("Unknown") else ""}


def overview_status(stage, text, source):
    """Project.md's own ``Programming``/``Verification`` overview field, read
    literally. It is reported history for navigation and the project badge;
    it never decides a document's verdict."""
    key = {"programming": "Programming", "verification": "Verification"}[stage]
    values = _field_values(metadata(text or ""), key)
    literal = values[0] if len(values) == 1 else ""
    label = literal or ("Unknown — duplicate or conflicting conclusions" if values else "Not reported")
    return {"label": label, "kind": "neutral", "source": source, "literal": literal,
            "icon": "○", "reason": ""}
