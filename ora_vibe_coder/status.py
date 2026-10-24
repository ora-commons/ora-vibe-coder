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
    """Read opening scalar fields while leaving unrelated vault YAML alone.

    Nested lists and mappings belong to their own top-level key. This reader
    does not deserialize or rewrite them; only the report's scalar fields are
    interpreted here.
    """
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
            scalar_parent = match[1].casefold() if match[1].casefold() in {"status", "review"} else ""
        # These are scalar/flow syntax checks, not deserialization: unrelated
        # mappings and lists still retain their original bytes and ownership.
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
    fields = frontmatter_fields(text)
    if fields is None:
        return None, ""
    values = _field_values(fields, key)
    if fields.get("__error__"):
        return None, " ".join(fields["__error__"])
    if len(values) > 1:
        return None, f"Duplicate {key} fields in opening YAML."
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
    # Move bare legacy fields to YAML, but keep any explanation attached to
    # their scalar. It may contain a scope or delivery obligation.
    opening = metadata(body)
    for key in updates:
        for label in opening:
            if label.casefold() == key.casefold():
                pattern = r"(?m)^([*`_]*" + re.escape(label) + r"[*`_]*[^\S\r\n]*:[^\S\r\n]*[*`_]*)([^\r\n]*)(?:\r?\n|$)"
                def replace(match):
                    values = VALUES.get("specification", set()) | VALUES.get("planning", set()) if key == "status" else {"PASSED", "NOT PASSED", "INCOMPLETE", "CHANGED"}
                    scalar = re.match("(?:" + "|".join(re.escape(v) for v in sorted(values, key=len, reverse=True)) + r")\b([*`_]*)(.*)", match[2])
                    if scalar and scalar[2].strip():
                        return match[1] + str(updates[key]) + scalar[1] + scalar[2] + newline
                    return "" if scalar else match[0]
                body = re.sub(pattern, replace, body, count=1)
    return "".join(front) + body


def canonical_verdict(value, *, legacy_review=False):
    value = (value or "").upper()
    if value == "COMPLETE":
        return "PASSED"
    if legacy_review and value == "INCOMPLETE":
        return "NOT PASSED"
    if value.startswith(("NOT PASSED — REVIEW INCOMPLETE", "NOT PASSED — REVISION INCOMPLETE")):
        return "INCOMPLETE"
    return value


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
    return (front + _drop_recorded_opening(text[start:], preserve_explanations=True)).strip("\n") + "\n"


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
    yaml_review, yaml_error = yaml_value(text or "", "review")
    yaml_status, status_error = yaml_value(text or "", "status")
    if yaml_status is not None and yaml_status not in VALUES[stage]:
        status_error = "Unknown or empty YAML status value: " + yaml_status
    yaml_error = yaml_error or status_error
    if yaml_error:
        result["present"] = True
        result["issues"].append(yaml_error)
        return result
    if yaml_review not in (None, ""):
        result.update(present=True, verdict=yaml_review, outcome=yaml_review, applies="unconfirmed")
        if yaml_review not in {"PASSED", "NOT PASSED", "INCOMPLETE", "CHANGED"}:
            result["issues"].append("Unknown YAML review value: " + yaml_review)
            return result
        if yaml_review == "CHANGED":
            result.update(applies="earlier", reason="The document changed materially; the retained assessment describes an earlier version.")
    found = [s for s in sections(text or "") if s[0].strip().lower() == REVIEW_HEADING.lower()]
    if not found:
        return result
    result["present"] = True
    if len(found) > 1:
        result["issues"].append("More than one Current review section; resolve the duplicates in the document.")
        return result
    if yaml_review == "CHANGED":
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
    result["verdict"] = yaml_review or conclusion["label"]
    result["outcome"] = yaml_review or canonical_verdict(conclusion["label"], legacy_review=True)
    if yaml_review and conclusion["present"] and not conclusion["label"]:
        result["issues"].append(conclusion["reason"] or "The Current review has no clear current conclusion.")
    if yaml_review and conclusion["label"] and canonical_verdict(conclusion["label"]) != yaml_review:
        result["issues"].append("YAML review and Current review have conflicting current conclusions.")
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
    if result["verdict"].upper() in {"COMPLETE", "PASSED", "NOT PASSED", "INCOMPLETE"}:
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
                    result["applies"] = "current" if meaning_text(matched) == meaning_text(text or "") else "unconfirmed"
                    result["reason"] = ("Compared with the retained reviewed document; " +
                                        ("only recording details changed." if result["applies"] == "current"
                                         else "the document content has changed since this review."))
                elif _field_values(fields, "Basis format") == ["content-v2"]:
                    result["applies"] = "unconfirmed"
                    result["reason"] = "The text differs from the review basis; materiality is not established without the earlier content."
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
    "programming": {"PASSED", "NOT PASSED", "NOT STARTED", "IN PROGRESS", "COMPLETE", "INCOMPLETE", "CLOSED BY USER — UNRESOLVED FINDINGS"},
    "verification": QUALITY | {"INCOMPLETE", "NOT STARTED", "IN PROGRESS", "CLOSED BY USER — UNRESOLVED FINDINGS"},
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


def _current_suffix(text, current_round=None):
    # Remove only the historical status phrase, not the rest of its sentence.
    # A later clause can still retract the current success.
    text = re.sub(r"\b(?:earlier|previous|historical)\s+(?:(?:report|result|revision)\s+(?:was|said|recorded)\s+)?(?:NOT PASSED|INCOMPLETE|IN PROGRESS|COMPLETE|PASSED)\b", "earlier", text, flags=re.I)
    text = re.sub(r"\b(?:does not|doesn't) (?:verify|certify) (?:working|unbuilt|running|later) software\b", "", text, flags=re.I)
    # Other-scope references can be ignored only up to an explicit turn back
    # to the current work. Keep "but ..." and later qualifications intact.
    clauses = re.split(r"(?<=[.!?])\s+|;\s*", text)
    kept = []
    for clause in clauses:
        # Remove an earlier round's verdict, keeping its explanation: the
        # explanation may say that its defect still remains unresolved.
        round_record = re.match(r"\s*round\s+(\d+)\b", clause, re.I)
        if current_round is not None and round_record and int(round_record[1]) < current_round:
            clause = re.sub(r"^(\s*round\s+\d+\b(?:\s+(?:returned|recorded|was))?\s*[:—–-]?\s*)(?:NOT PASSED|INCOMPLETE|IN PROGRESS|COMPLETE|PASSED)\b",
                            r"\1", clause, count=1, flags=re.I)
        if current_round is not None and round_record and int(round_record[1]) == current_round:
            clause = re.sub(r"\bresolved\s+(?:the\s+)?(?:one\s+)?(?:remaining|outstanding)\s+evidence\s+gap\b",
                            "resolved evidence", clause, flags=re.I)
        # Acceptance of a live answer is a distinct human checkpoint, not a
        # retraction of the implementation verdict. Keep any later contrast.
        acceptance = re.match(r"\s*(?:it|this verdict|the verdict) does not establish (?:[^;.!?]*?)(?:acceptance of (?:the|a) (?:flagged |live )*answer)\b", clause, re.I)
        if acceptance:
            contrast = re.search(r"\b(?:but|however|except|current|required checks?|failed|failing|failure|incomplete|unfinished|unresolved)\b", clause[acceptance.end():], re.I)
            if contrast:
                kept.append(clause[acceptance.end() + contrast.start():])
            continue
        if "Project.md" in clause and (re.search(r"\b(?:other|different|later|next)\b.*\bscope\b", clause, re.I)
                or re.search(r"\bfor that remaining part\b", clause, re.I)):
            current = re.search(r"\b(?:but|however|current|required checks?)\b", clause, re.I)
            if current:
                kept.append(clause[current.start():])
        else:
            kept.append(clause)
    return "; ".join(kept)


def _qualified_success(text, current_round=None, *, review=False):
    # Ordinary absence-of-findings wording is not a failure qualification.
    text = _current_suffix(text, current_round)
    if review:
        # A document review can disclaim implementation proof without retracting its own verdict.
        subject = r"(?:code|the implementation|implementation|live publication|unbuilt software)"
        text = re.sub(rf"\bnot (?:a |an )?(?:verification|validation|certification|proof) of {subject}(?: or {subject})*", "", text, flags=re.I)
    text = re.sub(r"\bno (?:material |remaining |unresolved )*(?:findings?|failures?|defects?|issues?|gaps?)\b", "", text, flags=re.I)
    text = re.sub(r"\bnone (?:remaining|unresolved)\b", "", text, flags=re.I)
    return bool(re.search(r"\b(?:but|except|however|partially|partial|only|solely|limited|restricted|failed|failing|failure|not|incomplete|unfinished|unresolved|pending|remaining|withdraw|withdrawn|retract|retracted|revoke|revoked|rescind|rescinded|premature|cannot|unconfirmed|unjustified|unsupported|invalid|unwarranted)\b|\b(?:is|was|are|were|has|have|had|ca|could|does|do|did|wo|would|should|must|need)n['’]t\b|\bno\s+longer\b|\b\d+\s+of\s+\d+\b", text, re.I))


def _status_token(literal, values, *, current_round=None, review=False):
    """Read a complete conclusion and preserve qualifications outside bold text."""
    literal = re.sub(r"^[🟢✅🔴❌🟡⚠][\ufe0f ]*", "", _plain(literal))
    for value in sorted(values, key=len, reverse=True):
        if literal.upper() == value:
            return value
        boundary = re.match(re.escape(value) + r"(?:\s*[—–;:]\s*|\s+\(|\s+-\s+|[.!?](?:\s+|$))", literal, re.I)
        if boundary:
            suffix = _current_suffix(literal[boundary.end():], current_round)
            if value == "COMPLETE":
                suffix = re.sub(r"\bverification\s+PASSED\b", "", suffix, flags=re.I)
            alternatives = "|".join(re.escape(item) for item in sorted(values, key=len, reverse=True))
            competing = re.findall(rf"(?<![A-Z])(?:{alternatives})(?![A-Z])", suffix.upper())
            if any(canonical_verdict(item) != canonical_verdict(value) for item in competing) or (value in {"COMPLETE", "PASSED"} and _qualified_success(suffix, current_round, review=review)):
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
            current = []
            if not stripped.startswith(">"):
                active = False
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
                      and (heading[2].strip().casefold() in CURRENT_HEADINGS or bool(re.search(r"\bcurrent report\b", heading[2], re.I))))
            ancestors.append((level, active))
            continue
        if active:
            current.append(line)
    if current:
        regions.append(current)
    return regions


def _explanatory_conclusion(sentence, allowed, review=False):
    # A noun phrase describes evidence; definition verbs explain the label.
    # Judge each sentence separately so an ordinary explanation can continue.
    noun_word = r"[a-z][a-z'’\-]*"
    return bool(re.fullmatch(
        rf"(?:Complete\s+{noun_word}(?:\s+{noun_word})*\s+"
        r"(?:is|are|was|were|has|have|[a-z]+s)|(?i:PASSED\s+(?:means|establishes|denotes|indicates)))"
        r"\s+[^.!?;:—–]+[.!?]?", sentence)
        and not _qualified_success(sentence, review=review)
        and not any(re.search(r"\b" + re.escape(value) + r"\b", sentence.split(None, 1)[1], re.I)
                    for value in allowed))


def _prose_conclusion(stage, paragraph, review=False):
    paragraph = _plain(paragraph)
    if review:
        subject = r"(?:(?:the|this|current)\s+)?(?:specification|spec|plan|planning|assessment|review)(?:\s+(?:review|assessment))?"
        outcomes = ((r"(?:has\s+|is\s+|was\s+)?(?:not\s+passed|failed)", "NOT PASSED"),
                    (r"(?:has\s+|is\s+|was\s+)?(?:passed|succeeded)", "PASSED"),
                    (r"(?:is\s+|was\s+)?(?:incomplete|not\s+complete)", "INCOMPLETE"),
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
    allowed = {"COMPLETE", "PASSED", "NOT PASSED", "INCOMPLETE"} if review else VALUES[stage]
    target = r"(?:(?:this|that|the|my|our)\s+(?:current\s+)?(?:verdict|conclusion|assessment)|it)"
    withdrawn = r"(?:withdrawn|retracted|revoked|rescinded)"
    values = []
    offset = 0
    for sentence in re.split(r"(?<=[.!?])\s+|;\s*", paragraph):
        position = paragraph.find(sentence, offset)
        offset = position + len(sentence)
        if _explanatory_conclusion(sentence, allowed, review):
            continue
        # Only a present assertion about this conclusion retracts it. Quoted,
        # historical and future/conditional instructions do not match these subjects.
        current = re.sub(r"^(?:but|however|except)[, ]+", "", sentence, flags=re.I)
        if re.match(rf"^(?:{target}\s+(?:is|was|has been)\s+{withdrawn}|(?:I|we)\s+(?:(?:now|hereby)\s+)?(?:withdraw|retract|revoke|rescind|have\s+{withdrawn})\s+{target})\b", current, re.I):
            return "", True
        token = _status_token(sentence, allowed, review=review)
        if token or any(re.match(re.escape(value) + r"(?:[.!?—–;:]|\s|$)", sentence, re.I) for value in allowed):
            values.append(token)
            continue
        for phrase, value in outcomes:
            match = re.match(rf"^{subject}\s+{phrase}\b", sentence, re.I)
            if match:
                values.append("" if value in {"COMPLETE", "PASSED"} and _qualified_success(paragraph[position + match.end():], review=review) else value)
                break
        if any(value in {"COMPLETE", "PASSED"} for value in values) and re.match(r"^(?:but|however|except)\b", sentence, re.I):
            return "", True
    return (values[0] if values and all(values) and len({canonical_verdict(value) for value in values}) == 1 else ""), bool(values)


def read_conclusion(stage, text, *, review=False):
    """One shared save/display interpretation; no current verdict from history."""
    allowed = {"COMPLETE", "PASSED", "NOT PASSED", "INCOMPLETE"} if review else VALUES[stage]
    candidates, declarations = [], []
    if not review:
        yaml_status, error = yaml_value(text, "status")
        if error or (yaml_status not in (None, "") and yaml_status not in allowed):
            return {"label": "", "literal": yaml_status or "", "evidence": [],
                    "present": True, "reason": error or "Unknown YAML status value."}
        if yaml_status not in (None, ""):
            candidates.append((yaml_status, yaml_status, f"status: {yaml_status}"))
    names = ({"status", "state", "verdict", "review verdict", "assessment", "current assessment", "result"}
             if review else CONCLUSION_FIELDS[stage])
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
                current_field = re.fullmatch(r"Current verdict(?:\s*\(([^)]*)\))?\s*:\s*(.*)", plain, re.I)
                if current_field and not review:
                    declarations.append("current verdict")
                    literal = current_field[2].strip()
                    round_match = re.search(r"\bround\s+(\d+)\b", current_field[1] or "", re.I)
                    current_round = int(round_match[1]) if round_match else None
                    candidates.append((_status_token(literal, allowed, current_round=current_round, review=review), literal, stripped))
                    continue
                token = _status_token(plain, allowed, review=review)
                first_sentence = re.split(r"(?<=[.!?])\s+|;\s*", plain)[0]
                explanatory = _explanatory_conclusion(first_sentence, allowed, review)
                starts_outcome = not explanatory and any(
                    re.match(re.escape(value) + r"(?:[.!?—–;:]|\s|$)", plain, re.I)
                    for value in allowed)
                field = re.fullmatch(FIELD, plain)
                if field and not starts_outcome:
                    if (field[2].strip().casefold() in names or (not review and re.fullmatch(r"current verdict(?: \(.*\))?", field[2].strip(), re.I))):
                        declarations.append(field[2].strip().casefold())
                        literal = field[3].strip()
                        candidates.append((_status_token(literal, allowed, review=review), literal, stripped))
                    continue
                if token or starts_outcome:
                    candidates.append((token, plain, stripped))
                    continue
                narrative.append(stripped)
            if narrative:
                paragraph = " ".join(narrative)
                token, identified = _prose_conclusion(stage, paragraph, review)
                if identified:
                    candidates.append((token, _plain(paragraph), paragraph))
                elif candidates and (not review or any(item[0] in {"COMPLETE", "PASSED"} for item in candidates)) and re.search(
                        r"(?:^|[.!?;]\s+)(?:but|however|except)\b", _plain(paragraph), re.I):
                    candidates.append(("", _plain(paragraph), paragraph))
    evidence = [item[2] for item in candidates]
    result = {"label": "", "literal": candidates[0][1] if candidates else "", "evidence": evidence,
              "reason": "", "present": bool(candidates)}
    if len(declarations) != len(set(declarations)):
        result["reason"] = "Duplicate current conclusion fields; keep one authoritative current field."
    elif not candidates:
        result["reason"] = "No clear current conclusion was found in the opening or a current outcome section."
    elif any(not item[0] for item in candidates):
        result["reason"] = "Unrecognized or qualified current conclusion: " + "; ".join(item[2] for item in candidates if not item[0])
    elif len({canonical_verdict(item[0]) for item in candidates}) != 1:
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
        yaml_status, yaml_error = yaml_value(text, "status")
        values = [yaml_status] if yaml_status is not None else _field_values(fields, key)
        if yaml_error:
            values = [yaml_error]
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
