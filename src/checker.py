"""Checker agent: verifies a narration against the evidence it was given.

A narration is rejected when it contains
  * a number that is not anywhere in the evidence (rounded to the precision shown),
  * a number attached to a unit that does not match that unit's evidence
    (for example "4 goals" when goals = 1, even if 4 appears elsewhere, say as tackles),
  * a score, shots, xG or pass-accuracy pair that does not match home/away order, or
  * a player or club name that is not in the evidence.

Known limits (be honest about them): number words ("three") are not parsed, so the
Narrator is told to write digits; and a number in free phrasing with no recognised unit
(for example the second figure in "had 15 shots to 10") is only checked against the whole
evidence, so a swap there is not caught.
"""
import re

_DEVANAGARI = str.maketrans("०१२३४५६७८९", "0123456789")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_NUM = r"(\d+(?:\.\d+)?)"
_EN = r"(?![A-Za-z])"  # an English unit word must end here (so "m" does not match "minutes")

# (label, regex with one number group, evidence keys that number may legitimately come from)
UNIT_RULES = [
    ("shots", _NUM + r"\s*(?:shots?" + _EN + r"|शॉट)", ["shots", "home_shots", "away_shots"]),
    ("goals", _NUM + r"\s*(?:goals?" + _EN + r"|गोल)", ["goals", "home_goals", "away_goals"]),
    ("xG", _NUM + r"\s*xG", ["xg", "home_xg", "away_xg"]),
    ("xG", r"xG\s*" + _NUM, ["xg", "home_xg", "away_xg"]),
    ("tackles", _NUM + r"\s*(?:tackles?" + _EN + r"|टैकल)", ["tackles_won"]),
    ("pressures", _NUM + r"\s*(?:pressures?" + _EN + r"|दबाव)", ["pressures"]),
    ("passes", _NUM + r"\s*(?:passes|pass" + _EN + r"|पास)", ["passes"]),
    ("speed", _NUM + r"\s*(?:km/h|किमी/घंटा)", ["shot_speed_kmh"]),
    ("distance", _NUM + r"\s*(?:m" + _EN + r"|मीटर)", ["distance_m"]),
    ("minute", r"(\d+)'", ["minute"]),
    ("minute", r"minute\s+(\d+)", ["minute"]),
    ("minute", r"(\d+)\s*मिनट", ["minute", "window_minutes"]),
    ("window length", r"(\d+)-minute", ["window_minutes"]),
]

# Pairs that must appear in home, away order: (label, regex with two groups, (home key, away key))
PAIR_RULES = [
    ("shots", r"(?:Shots|शॉट)\s+(\d+)-(\d+)", ("home_shots", "away_shots")),
    ("xG", r"xG\s+" + _NUM + "-" + _NUM, ("home_xg", "away_xg")),
    ("pass accuracy", _NUM + r"%\s*(?:vs|बनाम)\s*" + _NUM + "%",
     ("home_pass_accuracy_pct", "away_pass_accuracy_pct")),
]
# Not part of a decimal: no digit (or digit + dot) before, no digit (or dot + digit) after.
SCORE_RE = re.compile(r"(?<!\d)(?<!\d\.)(\d+)-(\d+)(?!\.?\d)")


def _walk(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _walk(v)
    else:
        yield obj


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _variants(v):
    """Values a narrator may legitimately print for v: as is, or rounded to 0/1/2 places.

    Rounding to a whole number is only allowed for values of 1 or more, so an xG of
    0.16 can never be passed off as 0.
    """
    out = {round(float(v), 1), round(float(v), 2)}
    if abs(float(v)) >= 1:
        out.add(round(float(v), 0))
    if float(v) == int(float(v)):
        out.add(float(int(v)))
    return out


def allowed_numbers(evidence):
    out = set()
    for v in _walk(evidence):
        if _is_num(v):
            out |= _variants(v)
    return out


def evidence_text(evidence):
    return " ".join(v for v in _walk(evidence) if isinstance(v, str))


def _values(evidence, keys):
    out = set()
    for k in keys:
        if _is_num(evidence.get(k)):
            out |= _variants(evidence[k])
    return out


def _pct_keys(text, start, end, evidence):
    """Choose which percentage fields a number may come from, from the words around it."""
    around = text[max(0, start - 40):end + 30].lower()
    if "accuracy" in around or "सटीकता" in around:
        word = "accuracy"
    elif any(w in around for w in ("momentum", "share", "मोमेंटम", "हिस्सा")):
        word = "share"
    else:
        word = ""
    return [k for k, v in evidence.items() if k.endswith("_pct") and _is_num(v) and word in k]


def _bound_issues(text, evidence):
    issues = []
    used = []  # spans consumed by pair rules, so the score rule skips them

    for label, rx, (hk, ak) in PAIR_RULES:
        for m in re.finditer(rx, text):
            used.append(m.span())
            if _is_num(evidence.get(hk)) and _is_num(evidence.get(ak)):
                a, b = round(float(m.group(1)), 2), round(float(m.group(2)), 2)
                if a not in _variants(evidence[hk]) or b not in _variants(evidence[ak]):
                    issues.append(f"{label} {m.group(1)}-{m.group(2)} does not match the evidence")

    if _is_num(evidence.get("home_goals")) and _is_num(evidence.get("away_goals")):
        for m in SCORE_RE.finditer(text):
            if any(s <= m.start() < e for s, e in used):
                continue
            if (int(m.group(1)), int(m.group(2))) != (evidence["home_goals"], evidence["away_goals"]):
                issues.append(f"score {m.group(1)}-{m.group(2)} does not match the evidence")

    for label, rx, keys in UNIT_RULES:
        ok = _values(evidence, keys)
        if not ok:
            continue
        for m in re.finditer(rx, text):
            if round(float(m.group(1)), 2) not in ok:
                issues.append(f"{m.group(1)} is not a valid {label} value")

    for m in re.finditer(_NUM + r"\s*%", text):
        keys = _pct_keys(text, m.start(), m.end(), evidence)
        ok = _values(evidence, keys)
        if ok and round(float(m.group(1)), 2) not in ok:
            issues.append(f"{m.group(1)}% is not a valid percentage here")
    return issues


def check(text, evidence, known_names):
    """Return {"ok": bool, "issues": [str]}."""
    if not text or not text.strip():
        return {"ok": False, "issues": ["empty narration"]}
    text = text.translate(_DEVANAGARI)
    issues = []

    allowed = allowed_numbers(evidence)
    for tok in _NUM_RE.findall(text):
        if round(float(tok), 2) not in allowed:
            issues.append(f"number {tok} is not in the evidence")
    for issue in _bound_issues(text, evidence):
        if issue not in issues:
            issues.append(issue)

    ev_text = evidence_text(evidence)
    for name in known_names:
        if name in text and name not in ev_text:
            issues.append(f"name '{name}' is not in the evidence")

    return {"ok": not issues, "issues": issues}
