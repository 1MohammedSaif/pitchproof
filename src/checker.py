"""Checker agent: verifies a narration against the evidence it was given.

A narration is rejected when it contains
  * a number that is not in the evidence (rounded to the precision shown), or
  * a player or club name that is not in the evidence.

Number words ("three") are not parsed; the Narrator is told to write digits.
"""
import re

_DEVANAGARI = str.maketrans("०१२३४५६७८९", "0123456789")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _walk(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _walk(v)
    else:
        yield obj


def allowed_numbers(evidence):
    out = set()
    for v in _walk(evidence):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        for places in (0, 1, 2):
            out.add(round(float(v), places))
    return out


def evidence_text(evidence):
    return " ".join(v for v in _walk(evidence) if isinstance(v, str))


def check(text, evidence, known_names):
    """Return {"ok": bool, "issues": [str]}."""
    issues = []
    if not text or not text.strip():
        return {"ok": False, "issues": ["empty narration"]}

    allowed = allowed_numbers(evidence)
    for tok in _NUM_RE.findall(text.translate(_DEVANAGARI)):
        if round(float(tok), 2) not in allowed:
            issues.append(f"number {tok} is not in the evidence")

    ev_text = evidence_text(evidence)
    for name in known_names:
        if name in text and name not in ev_text:
            issues.append(f"name '{name}' is not in the evidence")

    return {"ok": not issues, "issues": issues}
