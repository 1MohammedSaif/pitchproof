"""Load synthetic events into SQL and compute deterministic match metrics.

Every number the agents later narrate comes from the views in sql/schema.sql.
This module loads data, registers the geometry helpers those views use, and
exposes `match_facts()` which returns a JSON-serialisable fact sheet.

Usage:
    python src/metrics.py --events data/match_001.json --db data/pitchproof.db
"""
import argparse
import json
import math
import os
import sqlite3

PITCH_L, PITCH_W = 105.0, 68.0
GOAL_W = 7.32


def _goal_dx_dy(x, y, team):
    # HOME attacks toward x = 105, AWAY toward x = 0.
    dx = (PITCH_L - x) if team == "HOME" else x
    dy = y - PITCH_W / 2
    return dx, dy


def pp_dist(x, y, team):
    dx, dy = _goal_dx_dy(x, y, team)
    return math.hypot(dx, dy)


def pp_angle(x, y, team):
    dx, dy = _goal_dx_dy(x, y, team)
    ang = math.degrees(math.atan2(GOAL_W * dx, dx * dx + dy * dy - (GOAL_W / 2) ** 2))
    return max(ang, 1.0)


def pp_xg(x, y, team):
    """xG-style value from distance and goal-mouth angle (a transparent model)."""
    d = pp_dist(x, y, team)
    a = pp_angle(x, y, team)
    return max(0.01, min(0.6, 0.9 * math.exp(-d / 11.0) * (a / 40.0)))


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.create_function("pp_dist", 3, pp_dist)
    conn.create_function("pp_angle", 3, pp_angle)
    conn.create_function("pp_xg", 3, pp_xg)
    return conn


def load(conn, data, schema_path):
    with open(schema_path, encoding="utf-8") as f:
        conn.executescript(f.read())
    m = data["match"]
    conn.execute(
        "INSERT INTO matches VALUES (?,?,?,?,?,?,?,?)",
        (m["match_id"], m["home"]["name"], m["away"]["name"], m["home"]["short"],
         m["away"]["short"], m["final_score"]["HOME"], m["final_score"]["AWAY"],
         m["duration_min"]),
    )
    for side, key in (("HOME", "home"), ("AWAY", "away")):
        for p in m[key]["squad"]:
            conn.execute(
                "INSERT INTO players VALUES (?,?,?,?,?,?)",
                (p["player_id"], m["match_id"], side, p["name"], p["role"], p["number"]),
            )
    for e in data["events"]:
        conn.execute(
            """INSERT INTO events (seq, match_id, t, minute, team, type, player_id,
                other_player_id, x, y, end_x, end_y, length_m, forward, under_pressure,
                completed, outcome, won, intensity, ball_speed_kmh, shot_speed_kmh, reason)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (e["seq"], m["match_id"], e["t"], e["minute"], e["team"], e["type"],
             e.get("player_id"), e.get("receiver_id") or e.get("on_player_id"),
             e.get("x"), e.get("y"), e.get("end_x"), e.get("end_y"), e.get("length_m"),
             None if "forward" not in e else int(e["forward"]),
             None if "under_pressure" not in e else int(e["under_pressure"]),
             None if "completed" not in e else int(e["completed"]),
             e.get("outcome"),
             None if "won" not in e else int(e["won"]),
             e.get("intensity"), e.get("ball_speed_kmh"), e.get("shot_speed_kmh"),
             e.get("reason")),
        )
    conn.commit()


def _rows(conn, sql, *args):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def match_facts(conn):
    """Deterministic fact sheet. Agents may only cite numbers found in here."""
    match = _rows(conn, "SELECT * FROM matches")[0]
    team_stats = _rows(conn, """
        SELECT s.team,
               COUNT(*) AS shots,
               SUM(CASE WHEN s.outcome = 'goal' THEN 1 ELSE 0 END) AS goals,
               SUM(CASE WHEN s.outcome IN ('goal','saved') THEN 1 ELSE 0 END) AS on_target,
               ROUND(SUM(s.xg), 2) AS xg
        FROM v_shots s GROUP BY s.team""")
    passing = _rows(conn, """
        SELECT team,
               COUNT(*) AS passes,
               ROUND(100.0 * AVG(completed), 1) AS accuracy_pct,
               ROUND(AVG(difficulty), 2) AS avg_difficulty
        FROM v_passes GROUP BY team""")
    goals = _rows(conn, """
        SELECT s.minute, s.team, s.player_name, s.distance_m, s.xg, s.shot_speed_kmh
        FROM v_shots s WHERE s.outcome = 'goal' ORDER BY s.seq""")
    momentum = _rows(conn, "SELECT * FROM v_momentum ORDER BY minute")
    swings = []
    for a, b in zip(momentum, momentum[1:]):
        # Skip the first 5 minutes: the rolling window is not full yet.
        if a["minute"] < 5 or a["home_share"] is None or b["home_share"] is None:
            continue
        delta = round(b["home_share"] - a["home_share"], 1)
        if abs(delta) >= 12:
            swings.append({"minute": b["minute"], "home_share_before": a["home_share"],
                           "home_share_after": b["home_share"], "delta": delta})
    top_players = _rows(conn, """
        SELECT s.player_name, s.team, COUNT(*) AS shots,
               SUM(CASE WHEN s.outcome='goal' THEN 1 ELSE 0 END) AS goals,
               ROUND(SUM(s.xg), 2) AS xg
        FROM v_shots s GROUP BY s.player_id ORDER BY xg DESC LIMIT 3""")
    return {"match": match, "team_shots": team_stats, "passing": passing,
            "goals": goals, "momentum_swings": swings, "top_shooters": top_players}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default="data/match_001.json")
    ap.add_argument("--db", default="data/pitchproof.db")
    ap.add_argument("--schema", default="sql/schema.sql")
    ap.add_argument("--facts-out", default="data/facts.json")
    args = ap.parse_args()
    with open(args.events, encoding="utf-8") as f:
        data = json.load(f)
    if os.path.exists(args.db):
        os.remove(args.db)
    conn = connect(args.db)
    load(conn, data, args.schema)
    facts = match_facts(conn)
    with open(args.facts_out, "w", encoding="utf-8") as f:
        json.dump(facts, f, indent=1)
    print(json.dumps(facts["match"], indent=1))
    print("team_shots:", facts["team_shots"])
    print("passing:", facts["passing"])
    print("goals:", facts["goals"])
    print("momentum swings:", facts["momentum_swings"][:6])
    print("top shooters:", facts["top_shooters"])


if __name__ == "__main__":
    main()
