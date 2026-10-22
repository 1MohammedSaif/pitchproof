"""Build the PitchProof dashboard: one self-contained HTML file (docs/index.html).

All data is embedded, so the page works from a double-click and on GitHub Pages
(Settings -> Pages -> Deploy from branch -> main -> /docs). No server, no build tools.

Usage:
    python src/build_dashboard.py --db data/pitchproof.db \
        --narration data/narration.json --fault-demo data/narration_fault_demo.json \
        --out docs/index.html
"""
import argparse
import json
import os

import metrics

HERE = os.path.dirname(os.path.abspath(__file__))


def momentum_series(conn):
    return [dict(r) for r in conn.execute(
        "SELECT minute, home_share FROM v_momentum ORDER BY minute")]


def shot_points(conn):
    rows = conn.execute("""
        SELECT e.minute, e.team, e.x, e.y, e.outcome, p.name AS player,
               ROUND(pp_xg(e.x, e.y, e.team), 3) AS xg
        FROM events e JOIN players p ON p.player_id = e.player_id
        WHERE e.type = 'shot' ORDER BY e.seq""")
    return [dict(r) for r in rows]


def checker_demo(fault_path, moment_prefix="goal_78"):
    """Steps of one narration that the Checker rejected and the Narrator then repaired."""
    if not os.path.exists(fault_path):
        return None
    with open(fault_path, encoding="utf-8") as f:
        data = json.load(f)
    steps = [t for t in data["trace"]
             if t["moment"].startswith(moment_prefix) and t["mode"] == "analyst"
             and t["lang"] == "en" and t["agent"] == "checker"]
    if not steps:
        return None
    return {"moment": steps[0]["moment"], "mode": "analyst", "lang": "en",
            "steps": [{"attempt": s["attempt"], "status": s["status"],
                       "issues": s["issues"], "text": s["text"]} for s in steps]}


def build(db, narration_path, fault_path, out_path):
    conn = metrics.connect(db)
    with open(narration_path, encoding="utf-8") as f:
        narration = json.load(f)
    data = {
        "match": narration["match"],
        "momentum": momentum_series(conn),
        "shots": shot_points(conn),
        "moments": narration["moments"],
        "spotlights": narration.get("spotlights", []),
        "summary": narration["summary"],
        "demo": checker_demo(fault_path),
    }
    with open(os.path.join(HERE, "dashboard_template.html"), encoding="utf-8") as f:
        html = f.read()
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = html.replace("/*__DATA__*/null", payload)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/pitchproof.db")
    ap.add_argument("--narration", default="data/narration.json")
    ap.add_argument("--fault-demo", default="data/narration_fault_demo.json")
    ap.add_argument("--out", default="docs/index.html")
    args = ap.parse_args()
    path = build(args.db, args.narration, args.fault_demo, args.out)
    print(f"Wrote {path} ({os.path.getsize(path)} bytes)")


if __name__ == "__main__":
    main()
