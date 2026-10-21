"""Orchestrator: Analyst -> Narrator -> Checker, with retry and a safe fallback.

Shared state is the SQL fact sheet plus per-moment evidence. Handoffs:
  1. Analyst picks key moments and attaches evidence (moments.py).
  2. Narrator writes each moment for an audience and language (narrator.py).
  3. Checker verifies every number and name against the evidence (checker.py).
     On rejection the issues go back to the Narrator as feedback (up to MAX_ATTEMPTS).
     If it still fails, the deterministic template is used, so nothing unverified ships.

Usage:
    python src/pipeline.py --db data/pitchproof.db --out data/narration.json
    PITCHPROOF_DEMO_FAULT=1 python src/pipeline.py   # inject one hallucination per narration
"""
import argparse
import json

import checker
import llm
import metrics
import moments
import narrator

MAX_ATTEMPTS = 3
MODES = ("analyst", "casual")
LANGS = ("en", "hi")


def known_names(conn):
    names = [r[0] for r in conn.execute("SELECT name FROM players")]
    row = conn.execute("SELECT home_name, away_name FROM matches").fetchone()
    return names + [row[0], row[1]]


def run_one(moment, mode, lang, names, trace):
    feedback = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            text, source = narrator.narrate(moment, mode, lang, attempt, feedback)
        except llm.LLMError as e:
            trace.append({"moment": moment["id"], "mode": mode, "lang": lang,
                          "attempt": attempt, "agent": "narrator", "status": "error", "detail": str(e)})
            feedback = None
            continue
        verdict = checker.check(text, moment["evidence"], names)
        trace.append({"moment": moment["id"], "mode": mode, "lang": lang, "attempt": attempt,
                      "agent": "checker", "status": "accepted" if verdict["ok"] else "rejected",
                      "issues": verdict["issues"], "text": text})
        if verdict["ok"]:
            return {"text": text, "source": source, "attempts": attempt + 1, "fallback": False}
        feedback = verdict["issues"]
    text = narrator.template(moment, mode, lang)
    verdict = checker.check(text, moment["evidence"], names)
    trace.append({"moment": moment["id"], "mode": mode, "lang": lang, "attempt": MAX_ATTEMPTS,
                  "agent": "fallback", "status": "accepted" if verdict["ok"] else "rejected",
                  "issues": verdict["issues"], "text": text})
    return {"text": text, "source": "template-fallback", "attempts": MAX_ATTEMPTS, "fallback": True}


def run(db_path):
    conn = metrics.connect(db_path)
    facts = metrics.match_facts(conn)
    names = known_names(conn)
    key = moments.key_moments(conn, facts)
    trace, results = [], []
    for mo in key:
        narrations = {}
        for mode in MODES:
            for lang in LANGS:
                narrations[f"{mode}_{lang}"] = run_one(mo, mode, lang, names, trace)
        results.append({"id": mo["id"], "kind": mo["kind"], "minute": mo["minute"],
                        "evidence": mo["evidence"], "narrations": narrations})
    rejected = sum(1 for t in trace if t["agent"] == "checker" and t["status"] == "rejected")
    total = sum(len(r["narrations"]) for r in results)
    fallbacks = sum(1 for r in results for n in r["narrations"].values() if n["fallback"])
    repaired = sum(1 for r in results for n in r["narrations"].values()
                   if n["attempts"] > 1 and not n["fallback"])
    model_errors = sum(1 for t in trace if t["status"] == "error")
    summary = {"provider": llm.provider(), "narrations": total,
               "checker_rejections": rejected, "repaired_after_retry": repaired,
               "template_fallbacks": fallbacks, "model_errors": model_errors}
    return {"match": facts["match"], "moments": results, "summary": summary, "trace": trace}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/pitchproof.db")
    ap.add_argument("--out", default="data/narration.json")
    args = ap.parse_args()
    out = run(args.db)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print("Summary:", out["summary"])
    for r in out["moments"]:
        n = r["narrations"]
        print(f"\n[{r['id']}]")
        print("  analyst/en:", n["analyst_en"]["text"])
        print("  casual/en :", n["casual_en"]["text"])
        print("  casual/hi :", n["casual_hi"]["text"])
    rej = [t for t in out["trace"] if t["status"] == "rejected" and t["agent"] == "checker"]
    if rej:
        print("\nFirst rejections caught by the Checker:")
        for t in rej[:3]:
            print(f"  {t['moment']} {t['mode']}/{t['lang']} attempt {t['attempt']}: {t['issues']}")


if __name__ == "__main__":
    main()
