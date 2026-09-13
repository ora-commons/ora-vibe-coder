"""Read reported labels, never infer approval from document prose."""

import re


def metadata(text):
    fields = {}
    title_seen = False
    for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
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
        match = re.fullmatch(r"([*`_]*)([A-Za-z][A-Za-z ]*?)[*`_]*\s*:\s*(.*)", line)
        if not match:
            break
        name = match[2].strip()
        value = match[3].strip().strip("*`_").strip()
        fields.setdefault(name, []).append(value)
    return fields


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


def reported_status(stage, text, source):
    key = {"programming": "Programming", "verification": "Verification"}.get(stage, "Status")
    values = metadata(text).get(key, [])
    literal = values[0] if len(values) == 1 else ""
    kind = "neutral"
    if not values:
        label = "Not reported"
    elif len(values) != 1 or literal not in VALUES[stage]:
        label = "Unknown" + (f" — {literal}" if literal else " — duplicate or empty fields")
    else:
        label = literal
        if literal in {"APPROVED", "Approved product specification", "Approved Implementation Plan", "COMPLETE", "PASSED"}:
            kind = "positive"
        elif literal in {"DRAFT", "IN PROGRESS", "AWAITING APPROVAL"}:
            kind = "working"
        elif literal != "NOT STARTED":
            kind = "attention"
    return {"label": label, "kind": kind, "source": source, "literal": literal,
            "icon": {"neutral": "○", "working": "◷", "positive": "✓", "attention": "!"}[kind]}
