"""Read a document's current conclusion, keeping approval and evidence separate."""

import hashlib
import re

FIELD = r"([*`_]*)([A-Za-z][A-Za-z0-9_ -]*?)[*`_]*\s*:\s*(.*)"
# Opening fields whose recording must not change a document's evidence basis:
# the review/acceptance record itself and the discovery type marker.
RECORDING_FIELDS = {"vibe_document", "status", "accepted by", "accepted basis",
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
    """Fields of a closed opening YAML block, without a YAML dependency.

    Returns None when there is no closed frontmatter; unparseable or unclosed
    blocks read as None so ordinary metadata stays the fallback.
    """
    lines = text.splitlines()
    if not lines or lines[0].rstrip() != "---":
        return None
    fields = {}
    for line in lines[1:]:
        if line.rstrip() in {"---", "..."}:
            return fields
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_ -]*?)\s*:\s*(.*)", line.strip())
        if not match:
            return None
        fields.setdefault(match[1].strip(), []).append(match[2].strip())
    return None


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


def _drop_recorded_opening(text):
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
            continue
        if re.fullmatch(FIELD, line.strip().removesuffix("\\").rstrip()):
            fields_seen = True
            kept.append(line)
        else:
            kept.extend(lines[index:])
            return "\n".join(kept)
    return "\n".join(kept)


def _legacy_basis_text(text):
    """The historical fingerprint algorithm, for reading existing records only."""
    text = normalized(text)
    kept = []
    at = 0
    matches = list(re.finditer(r"^## ([^\r\n]+)\r?$", text, re.M))
    legacy_sections = [(m[1], m.start(), m.end(), matches[i + 1].start() if i + 1 < len(matches) else len(text))
                       for i, m in enumerate(matches)]
    for name, start, _, end in legacy_sections:
        if name.strip().lower() == REVIEW_HEADING.lower():
            kept.append(text[at:start])
            at = end
    kept.append(text[at:])
    text = "".join(kept)
    lines = text.split("\n")
    if lines and lines[0].strip() == "---":
        close = next((i for i in range(1, len(lines)) if lines[i].strip() in {"---", "..."}), None)
        if close is not None:
            inner = [line for line in lines[1:close] if line.strip() and not _recorded(line)]
            if any(line.strip() for line in inner):
                text = "\n".join([lines[0], *inner, *lines[close:]])
            else:
                text = "\n".join(lines[close + 1:])
    return _drop_recorded_opening(text)


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
    return (front + _drop_recorded_opening(text[start:])).strip("\n") + "\n"


def legacy_review_basis(text):
    return hashlib.sha256(_legacy_basis_text(text).encode("utf-8")).hexdigest()


def review_basis(*texts):
    """Standard-library SHA-256 over the substantive material, content only."""
    joined = "\n\x1e\n".join(basis_text(text) for text in texts if text)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def assessment_facts(stage, text, reviewed_texts=()):
    """Read one document's saved assessment from its Current review section.

    New assessments record a completeness verdict — COMPLETE or INCOMPLETE —
    with a basis over the assessed document's own substantive content, so a
    later change to that document identifies the assessment as applying to an
    earlier version. Legacy records keep their saved verdict vocabulary
    untranslated; their basis covered several documents and cannot establish
    which one changed, so applicability reads as unconfirmed.
    """
    result = {"present": False, "stage": "", "verdict": "", "basis": "",
              "findings": None, "applies": "", "issues": [], "evidence": [], "reason": ""}
    found = [s for s in sections(text or "") if s[0].strip().lower() == REVIEW_HEADING.lower()]
    if not found:
        return result
    result["present"] = True
    if len(found) > 1:
        result["issues"].append("More than one Current review section; resolve the duplicates in the document.")
        return result
    body = (text or "")[found[0][2]:found[0][3]]
    fields = metadata(body)
    stage_values = list(dict.fromkeys(_field_values(fields, "Stage", "Review stage")))
    conclusion = read_conclusion(stage, body, review=True)
    result["evidence"] = conclusion["evidence"]
    result["reason"] = conclusion["reason"]
    basis_values = list(dict.fromkeys(_field_values(fields, "Basis", "Basis as supplied", "Review basis")))
    if len(stage_values) > 1 or (stage_values and not stage_values[0]):
        result["issues"].append("The Current review has conflicting or empty stage labels.")
    result["stage"] = stage_values[0] if stage_values else {"specification": "Specification", "planning": "Plan"}[stage]
    result["verdict"] = conclusion["label"]
    if not result["verdict"]:
        # Preserve a single legacy verdict, but never convert it to completeness.
        legacy = _status_token(conclusion["literal"], QUALITY)
        if legacy and len(conclusion["evidence"]) == 1 and conclusion["reason"].startswith("Unrecognized"):
            result["verdict"] = legacy
        else:
            result["issues"].append(conclusion["reason"] or "The Current review needs one clear verdict.")
    if len(basis_values) > 1 or (basis_values and not basis_values[0]):
        result["issues"].append("The Current review has conflicting or empty basis labels.")
    result["basis"] = basis_values[0] if basis_values else ""
    if result["issues"]:
        return result
    if result["stage"].lower() not in STAGE_LABELS.get(stage, set()):
        result["issues"].append(f"The Current review section names stage {result['stage']!r}, not this document's stage.")
        return result
    if result["verdict"].upper() in {"COMPLETE", "INCOMPLETE"}:
        digest = result["basis"]
        if digest:
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                # The basis field may explain or quote its one fingerprint.
                # The label supplies its meaning; the AI need not say SHA-256.
                digests = re.findall(r"(?<![0-9A-Za-z])[0-9a-f]{64}(?![0-9A-Za-z])", digest)
                if len(digests) != 1:
                    result["issues"].append("The recorded assessment basis is ambiguous.")
                    return result
                digest = digests[0]
            if digest in {review_basis(text or ""), legacy_review_basis(text or "")}:
                result["applies"] = "current"
            else:
                matched = next((old for old in reviewed_texts
                                if digest in {review_basis(old), legacy_review_basis(old)}), None)
                if matched is not None:
                    result["applies"] = "current" if review_basis(matched) == review_basis(text or "") else "earlier"
                    result["reason"] = ("Compared with the retained reviewed document; " +
                                        ("only recording details changed." if result["applies"] == "current"
                                         else "the document content has changed since this review."))
                elif _field_values(fields, "Basis format") == ["content-v2"]:
                    result["applies"] = "earlier"
                    result["reason"] = "The document content has changed since this review."
                else:
                    result["applies"] = "unconfirmed"
                    result["reason"] = "The saved legacy fingerprint differs; no matching reviewed document is available to establish what changed."
        else:
            result["applies"] = "unconfirmed"
            result["reason"] = "The review states its conclusion but does not identify the reviewed document version."
        if result["verdict"].upper() == "INCOMPLETE":
            # Each noted deficiency is one list bullet; an absent list is an
            # unknown count, never zero.
            bullets = re.findall(r"^[-*] +\S", body, re.M)
            result["findings"] = len(bullets) or None
    else:
        result["applies"] = "unconfirmed"
    return result


def reported_verdict(text):
    """The current report's explicit conclusion, without explanatory prose."""
    status = reported_status("verification", text, "", field="Verdict")
    return status["label"] if status["label"] in VALUES["verification"] else ""


QUALITY = {
    "PASSED", "ONE PASS COMPLETE — REVISED, NOT RE-REVIEWED", "NOT PASSED",
    "NOT PASSED — REVIEW INCOMPLETE", "NOT PASSED — REVISION INCOMPLETE",
    "GEAR 4 UNAVAILABLE — GEAR 3 FALLBACK",
}
VALUES = {
    "specification": {"DRAFT", "IN PROGRESS", "AWAITING APPROVAL", "APPROVED", "Approved product specification"},
    "planning": {"DRAFT", "IN PROGRESS", "AWAITING APPROVAL", "APPROVED", "Approved Implementation Plan"},
    "programming": {"NOT STARTED", "IN PROGRESS", "COMPLETE", "INCOMPLETE", "CLOSED BY USER — UNRESOLVED FINDINGS"},
    "verification": QUALITY | {"NOT STARTED", "IN PROGRESS", "CLOSED BY USER — UNRESOLVED FINDINGS"},
}


def _field_values(fields, *names):
    wanted = {name.casefold() for name in names}
    return [value.strip() for name, values in fields.items() if name.casefold() in wanted for value in values]


# The labels are flexible; their meaning remains specific to the document role.
CONCLUSION_FIELDS = {
    "programming": {"status", "state", "verdict", "programming", "programming result",
                    "implementation", "implementation result", "result", "final status", "current status"},
    "verification": {"status", "state", "verdict", "final verdict", "verification verdict",
                     "verification result", "verification", "result", "final status", "current status"},
}
CURRENT_HEADINGS = {"current review", "current assessment", "result", "current result", "conclusion",
                    "current conclusion", "final verdict", "verdict", "outcome", "current outcome"}


def _plain(text):
    return re.sub(r"[*`_]", "", text).strip().removesuffix("\\").rstrip()


def _qualified_success(text):
    # Ordinary absence-of-findings wording is not a failure qualification.
    text = re.sub(r"\bno (?:material |remaining |unresolved )*(?:findings?|failures?|defects?|issues?|gaps?)\b", "", text, flags=re.I)
    text = re.sub(r"\bnone (?:remaining|unresolved)\b", "", text, flags=re.I)
    return bool(re.search(r"\b(?:but|except|however|partially|partial|failed|failure|not|incomplete|unfinished|unresolved|pending|remaining)\b|\b\d+\s+of\s+\d+\b", text, re.I))


def _status_token(literal, values):
    """Read a complete conclusion and preserve qualifications outside bold text."""
    literal = _plain(literal)
    for value in sorted(values, key=len, reverse=True):
        if literal.upper() == value:
            return value
        boundary = re.match(re.escape(value) + r"(?:\s*[—–;:]\s*|\s+\(|\s+-\s+|[.!?](?:\s+|$))", literal, re.I)
        if boundary:
            suffix = literal[boundary.end():]
            alternatives = "|".join(re.escape(item) for item in sorted(values, key=len, reverse=True))
            competing = re.findall(rf"(?<![A-Z])(?:{alternatives})(?![A-Z])", suffix.upper())
            if any(item != value for item in competing) or (value in {"COMPLETE", "PASSED"} and _qualified_success(suffix)):
                return ""
            return value
    return ""


def _current_regions(text):
    """Opening and expressly current outcome sections, excluding examples/code."""
    start = body_start(normalized(text))
    if start is None:
        return []
    regions, current, ancestors = [], [], []
    active, title_seen, fence = True, False, None
    for line in normalized(text)[start:].splitlines():
        stripped = line.strip()
        marker = re.match(r"^(`{3,}|~{3,})", stripped)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = None
            continue
        if marker:
            fence = marker[1]
            if current:
                regions.append(current)
            current, active = [], False
            continue
        if stripped.startswith(">") or re.match(r"(?: {4}| {0,3}\t)", line):
            if current:
                regions.append(current)
            current, active = [], False
            continue
        heading = re.match(r"^(#+) +(.+)$", stripped)
        if heading:
            if len(heading[1]) == 1 and not title_seen and not any(item.strip() for item in current):
                title_seen = True
                continue
            if current:
                regions.append(current)
            current = []
            level = len(heading[1])
            while ancestors and ancestors[-1][0] >= level:
                ancestors.pop()
            active = (all(parent_active for _, parent_active in ancestors)
                      and heading[2].strip().casefold() in CURRENT_HEADINGS)
            ancestors.append((level, active))
            continue
        if active:
            current.append(line)
    if current:
        regions.append(current)
    return regions


def _prose_conclusion(stage, paragraph, review=False):
    sentence = _plain(paragraph)
    if review:
        subject = r"(?:(?:the|this|current)\s+)?(?:specification|spec|plan|planning|assessment|review)(?:\s+(?:review|assessment))?"
        outcomes = ((r"(?:is\s+|was\s+)?(?:incomplete|not\s+complete)", "INCOMPLETE"),
                    (r"(?:is\s+|was\s+)?(?:complete|sufficient)", "COMPLETE"))
    elif stage == "programming":
        subject = r"(?:(?:the|this|current)\s+)?(?:programming|implementation)(?:\s+work)?"
        outcomes = ((r"(?:has\s+been\s+|was\s+|is\s+)?(?:not\s+completed?|incomplete|unfinished|stopped|blocked)", "INCOMPLETE"),
                    (r"(?:has\s+been\s+|was\s+|is\s+)?(?:completed|complete|finished|done)", "COMPLETE"),
                    (r"(?:is\s+|was\s+)?(?:in\s+progress|underway)", "IN PROGRESS"))
    else:
        subject = r"(?:(?:the|this)\s+)?(?:(?:independent|current|final)\s+)?verification"
        outcomes = ((r"(?:has\s+|was\s+|is\s+)?(?:not\s+passed|failed|incomplete)", "NOT PASSED"),
                    (r"(?:has\s+|was\s+|is\s+)?(?:passed|succeeded)", "PASSED"))
    for phrase, value in outcomes:
        match = re.match(rf"^{subject}\s+{phrase}\b", sentence, re.I)
        if match:
            # Check the whole paragraph: a second sentence can retract a pass.
            return ("" if value in {"COMPLETE", "PASSED"} and _qualified_success(sentence[match.end():]) else value), True
    return "", False


def read_conclusion(stage, text, *, review=False):
    """One shared save/display interpretation; no current verdict from history."""
    allowed = {"COMPLETE", "INCOMPLETE"} if review else VALUES[stage]
    names = ({"status", "state", "verdict", "review verdict", "assessment", "current assessment", "result"}
             if review else CONCLUSION_FIELDS[stage])
    candidates = []
    for lines in _current_regions(text):
        for block in re.split(r"\n\s*\n", "\n".join(lines)):
            narrative = []
            for line in block.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith(("- ", "* ", "+ ")):
                    break
                plain = _plain(stripped)
                field = re.fullmatch(FIELD, plain)
                if field and not narrative:
                    if field[2].strip().casefold() in names:
                        literal = field[3].strip()
                        candidates.append((_status_token(literal, allowed), literal, stripped))
                    continue
                token = _status_token(plain, allowed)
                starts_outcome = any(re.match(re.escape(value) + r"(?:[.!?—–;:]|\s|$)", plain, re.I)
                                     for value in allowed)
                if (token or starts_outcome) and not narrative:
                    candidates.append((token, plain, stripped))
                    continue
                narrative.append(stripped)
            if narrative:
                paragraph = " ".join(narrative)
                token, identified = _prose_conclusion(stage, paragraph, review)
                if identified:
                    candidates.append((token, _plain(paragraph), paragraph))
                elif candidates and re.match(r"^(?:but|however|except)\b", _plain(paragraph), re.I):
                    candidates.append(("", _plain(paragraph), paragraph))
    evidence = [item[2] for item in candidates]
    result = {"label": "", "literal": candidates[0][1] if candidates else "", "evidence": evidence,
              "reason": "", "present": bool(candidates)}
    if not candidates:
        result["reason"] = "No clear current conclusion was found in the opening or a current outcome section."
    elif any(not item[0] for item in candidates):
        result["reason"] = "Unrecognized or qualified current conclusion: " + "; ".join(item[2] for item in candidates if not item[0])
    elif len({item[0] for item in candidates}) != 1:
        result["reason"] = "Conflicting current conclusions: " + "; ".join(evidence)
    else:
        result["label"] = candidates[0][0]
    return result


def report_basis_note(text):
    """Show a report's own revision limit without asserting today's code passed."""
    plain = _plain(text)
    patterns = (r"(?:current independent verdict for revision|verdict for revision)\s+([0-9a-f]{7,40})\b",
                r"(?:inspected|reviewed|merged)\s+(?:source|revision|commit)\s+(?:at\s+)?([0-9a-f]{7,40})\b")
    for pattern in patterns:
        match = re.search(pattern, plain, re.I)
        if match:
            return f"This report names inspected revision {match[1]}; it does not establish that later changes passed."
    return "This is the saved report's conclusion about its inspected delivery; later changes are not automatically verified."


def reported_status(stage, text, source, field=None):
    key = field or {"programming": "Programming", "verification": "Verification"}.get(stage, "Status")
    conclusion = None
    if field in {"Status", "Verdict"} and stage in CONCLUSION_FIELDS:
        conclusion = read_conclusion(stage, text)
        literal, recognized = conclusion["literal"], conclusion["label"]
        values = [literal] if conclusion["present"] else []
    else:
        fields = metadata(text)
        values = _field_values(fields, key)
        literal = values[0] if len(values) == 1 else ""
        recognized = _status_token(literal, VALUES[stage]) if stage in {"programming", "verification"} else literal
    kind = "neutral"
    if conclusion and conclusion["present"] and not recognized:
        label = "Unknown — " + conclusion["reason"]
    elif len(values) > 1:
        label = "Unknown — duplicate or conflicting conclusions"
    elif not values:
        label = "Not reported"
    elif recognized not in VALUES[stage]:
        label = "Unknown" + (f" — {literal}" if literal else " — duplicate or empty fields")
    else:
        label = recognized
        if recognized in {"APPROVED", "Approved product specification", "Approved Implementation Plan", "COMPLETE", "PASSED"}:
            kind = "positive"
        elif recognized in {"DRAFT", "IN PROGRESS", "AWAITING APPROVAL"}:
            kind = "working"
        elif recognized != "NOT STARTED":
            kind = "attention"
    return {"label": label, "kind": kind, "source": source, "literal": literal,
            "icon": {"neutral": "○", "working": "◷", "positive": "✓", "attention": "!"}[kind],
            "evidence": conclusion["evidence"] if conclusion else [],
            "reason": conclusion["reason"] if conclusion else "",
            "basis_note": report_basis_note(text) if conclusion and stage == "verification" else ""}
