"""Narrator agent: turns a moment's evidence into text for one audience.

Modes:     analyst (numbers, tactics) | casual (simple story)
Languages: en | hi

With a real model (Azure / GitHub Models) the model writes the text from the evidence.
With the offline "mock" provider, deterministic templates are used instead. Templates
are also the safe fallback when a model keeps failing the Checker.
"""
import json
import os
import re

import llm

SITUATION_HI = {
    "opening goal": "पहला गोल",
    "equaliser": "बराबरी का गोल",
    "goal that puts the team ahead": "बढ़त दिलाने वाला गोल",
    "goal that cuts the deficit": "अंतर कम करने वाला गोल",
    "goal that extends the lead": "बढ़त बढ़ाने वाला गोल",
}

TEMPLATES = {
    ("goal", "casual", "en"):
        "{minute}' GOAL! {player} scores for {team}, {situation_a}. "
        "It's now {home_team} {home_goals}-{away_goals} {away_team}.",
    ("goal", "casual", "hi"):
        "{minute} मिनट: गोल! {team} के लिए {player} ने स्कोर किया, {situation_hi}। "
        "अब स्कोर {home_team} {home_goals}-{away_goals} {away_team} है।",
    ("goal", "analyst", "en"):
        "{minute}' {team}: {player} scores {situation_a} from {distance_m} m "
        "(xG {xg}, shot speed {shot_speed_kmh} km/h). Score {home_goals}-{away_goals}.{momentum_en}",
    ("goal", "analyst", "hi"):
        "{minute} मिनट, {team}: {player} ने {distance_m} मीटर से {situation_hi} किया "
        "(xG {xg}, शॉट की गति {shot_speed_kmh} किमी/घंटा)। स्कोर {home_goals}-{away_goals}।{momentum_hi}",
    ("swing", "casual", "en"):
        "Around minute {minute}, {team} took control of the match.",
    ("swing", "casual", "hi"):
        "{minute} मिनट के आसपास {team} ने मैच पर पकड़ बना ली।",
    ("swing", "analyst", "en"):
        "{minute}': momentum swing. {team}'s share of the {window_minutes}-minute rolling "
        "momentum rose from {share_before_pct}% to {share_after_pct}%.",
    ("swing", "analyst", "hi"):
        "{minute} मिनट: मोमेंटम में बदलाव। {window_minutes} मिनट की रोलिंग विंडो में {team} का हिस्सा "
        "{share_before_pct}% से बढ़कर {share_after_pct}% हो गया।",
    ("recap", "casual", "en"):
        "Full time: {home_team} {home_goals}-{away_goals} {away_team}. "
        "{home_team} had {home_shots} shots to {away_shots} for {away_team}.",
    ("recap", "casual", "hi"):
        "फुल टाइम: {home_team} {home_goals}-{away_goals} {away_team}। "
        "{home_team} ने {home_shots} शॉट लिए, {away_team} ने {away_shots}।",
    ("recap", "analyst", "en"):
        "Full time: {home_team} {home_goals}-{away_goals} {away_team}. Shots {home_shots}-{away_shots}, "
        "xG {home_xg}-{away_xg}, pass accuracy {home_pass_accuracy_pct}% vs {away_pass_accuracy_pct}%.",
    ("recap", "analyst", "hi"):
        "फुल टाइम: {home_team} {home_goals}-{away_goals} {away_team}। शॉट {home_shots}-{away_shots}, "
        "xG {home_xg}-{away_xg}, पास सटीकता {home_pass_accuracy_pct}% बनाम {away_pass_accuracy_pct}%।",
}


def _fmt(ev):
    """Pre-format numbers to the precision the templates show."""
    out = dict(ev)
    for k in ("xg", "home_xg", "away_xg"):
        if k in out:
            out[k] = f"{out[k]:.2f}"
    for k in ("distance_m", "shot_speed_kmh", "momentum_share_pct", "share_before_pct",
              "share_after_pct", "home_pass_accuracy_pct", "away_pass_accuracy_pct"):
        if k in out:
            out[k] = f"{out[k]:.1f}"
    sit = ev.get("situation", "")
    out["situation_hi"] = SITUATION_HI.get(sit, "")
    out["situation_a"] = ("an " if sit[:1] in "aeiou" else "a ") + sit if sit else ""
    share = out.get("momentum_share_pct")
    out["momentum_en"] = (f" {ev['team']} held {share}% of the {ev['window_minutes']}-minute momentum going in."
                          if share is not None else "")
    out["momentum_hi"] = (f" गोल से पहले {ev['window_minutes']} मिनट के मोमेंटम में {ev['team']} का हिस्सा {share}% था।"
                          if share is not None else "")
    return out


def template(moment, mode, lang):
    """Deterministic narration. Safe by construction: it only prints evidence values."""
    return TEMPLATES[(moment["kind"], mode, lang)].format(**_fmt(moment["evidence"]))


def _corrupt(text):
    """Demo helper: simulate a model hallucinating one wrong number."""
    matches = list(re.finditer(r"\d+(?:\.\d+)?", text))
    if not matches:
        return text
    m = matches[min(1, len(matches) - 1)]
    tok = m.group(0)
    if "." in tok:
        wrong = f"{float(tok) * 1.5 + 0.07:.{len(tok.split('.')[1])}f}"
    else:
        wrong = str(int(tok) + 3)
    return text[:m.start()] + wrong + text[m.end():]


SYSTEM = """You are a football match narrator for a broadcast graphics team.
Rules you must follow:
- Use ONLY the facts and numbers in the JSON evidence. Never invent players, clubs, numbers or events.
- Write numbers as digits (never as words). Do not do arithmetic or add numbers that are not in the evidence.
- Output only the narration text, nothing else.
Audience: {audience}
Language: {language}"""

AUDIENCE = {
    "analyst": "a data-hungry analyst. 2 to 3 sentences. Include the key numbers and explain why the moment mattered.",
    "casual": "a casual fan. 1 to 2 short, vivid sentences. Minimal numbers (minute and score only).",
}
LANGUAGE = {
    "en": "English",
    "hi": "Hindi in Devanagari script. Keep player and club names in English letters. Use ASCII digits 0-9.",
}


def narrate(moment, mode, lang, attempt=0, feedback=None):
    """Return (text, source). Raises llm.LLMError if a real model call fails."""
    if llm.provider() == "mock":
        text = template(moment, mode, lang)
        if os.environ.get("PITCHPROOF_DEMO_FAULT") == "1" and attempt == 0:
            text = _corrupt(text)
        return text, "mock-template"
    system = SYSTEM.format(audience=AUDIENCE[mode], language=LANGUAGE[lang])
    user = "Evidence:\n" + json.dumps(moment["evidence"], ensure_ascii=False, indent=1)
    if feedback:
        user += ("\n\nYour previous attempt was rejected by the fact checker:\n- "
                 + "\n- ".join(feedback) + "\nRewrite it using only the evidence.")
    return llm.complete(system, user), llm.provider()
