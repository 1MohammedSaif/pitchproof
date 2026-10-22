"""Analyst agent: picks the key moments of a match and attaches numeric evidence.

Selection is deterministic and runs on SQL results, so the same match always yields
the same moments. Each moment carries an `evidence` dict. The Narrator may only use
numbers and names that appear in it, and the Checker enforces that.
"""


def _rows(conn, sql, *args):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def _situation(before, after, team, other, total_before):
    if total_before == 0:
        return "opening goal"
    if after[team] == after[other]:
        return "equaliser"
    if before[team] == before[other]:
        return "goal that puts the team ahead"
    if before[team] < before[other]:
        return "goal that cuts the deficit"
    return "goal that extends the lead"


def key_moments(conn, facts, max_moments=5):
    m = facts["match"]
    names = {"HOME": m["home_name"], "AWAY": m["away_name"]}
    share = {r["minute"]: r["home_share"]
             for r in _rows(conn, "SELECT minute, home_share FROM v_momentum")}
    goals = _rows(conn, """SELECT seq, minute, team, player_name, distance_m, xg, shot_speed_kmh
                           FROM v_shots WHERE outcome = 'goal' ORDER BY seq""")

    moments = []
    score = {"HOME": 0, "AWAY": 0}
    for g in goals:
        team = g["team"]
        other = "AWAY" if team == "HOME" else "HOME"
        before = dict(score)
        score[team] += 1
        situation = _situation(before, score, team, other, sum(before.values()))
        hs = share.get(g["minute"] - 1, share.get(g["minute"]))
        team_share = None
        if hs is not None:
            team_share = round(hs if team == "HOME" else 100 - hs, 1)
        evidence = {
            "minute": g["minute"], "team": names[team], "player": g["player_name"],
            "situation": situation, "distance_m": g["distance_m"], "xg": g["xg"],
            "shot_speed_kmh": g["shot_speed_kmh"],
            "home_goals": score["HOME"], "away_goals": score["AWAY"],
            "home_team": names["HOME"], "away_team": names["AWAY"],
        }
        if team_share is not None:
            evidence["momentum_share_pct"] = team_share
            evidence["window_minutes"] = 5
        importance = 50
        if situation != "goal that extends the lead":
            importance += 20
        if g["minute"] >= 75:
            importance += 15
        if situation == "opening goal":
            importance += 10
        moments.append({"id": f"goal_{g['minute']}_{g['seq']}", "kind": "goal",
                        "minute": g["minute"], "importance": importance, "evidence": evidence})

    swings = sorted(facts["momentum_swings"], key=lambda s: -abs(s["delta"]))
    for s in swings[:2]:
        gaining = "HOME" if s["delta"] > 0 else "AWAY"
        before = s["home_share_before"] if gaining == "HOME" else round(100 - s["home_share_before"], 1)
        after = s["home_share_after"] if gaining == "HOME" else round(100 - s["home_share_after"], 1)
        moments.append({
            "id": f"swing_{s['minute']}", "kind": "swing", "minute": s["minute"],
            "importance": 40 + abs(s["delta"]) / 2,
            "evidence": {"minute": s["minute"], "team": names[gaining],
                         "share_before_pct": before, "share_after_pct": after,
                         "window_minutes": 5}})

    top = sorted(moments, key=lambda x: -x["importance"])[:max_moments]
    top.sort(key=lambda x: x["minute"])

    ts = {r["team"]: r for r in facts["team_shots"]}
    ps = {r["team"]: r for r in facts["passing"]}
    recap = {
        "id": "recap", "kind": "recap", "minute": m["duration_min"], "importance": 100,
        "evidence": {
            "home_team": names["HOME"], "away_team": names["AWAY"],
            "home_goals": m["home_goals"], "away_goals": m["away_goals"],
            "home_shots": ts["HOME"]["shots"], "away_shots": ts["AWAY"]["shots"],
            "home_xg": ts["HOME"]["xg"], "away_xg": ts["AWAY"]["xg"],
            "home_pass_accuracy_pct": ps["HOME"]["accuracy_pct"],
            "away_pass_accuracy_pct": ps["AWAY"]["accuracy_pct"],
        }}
    return top + [recap]


def player_spotlights(conn, facts, max_players=6):
    """One spotlight per notable player: every scorer, then the highest-xG shooters.

    Evidence comes straight from the v_player_stats SQL view.
    """
    m = facts["match"]
    names = {"HOME": m["home_name"], "AWAY": m["away_name"]}
    rows = _rows(conn, "SELECT * FROM v_player_stats")
    scorers = sorted((r for r in rows if r["goals"] > 0), key=lambda r: (-r["goals"], -r["xg"]))
    others = sorted((r for r in rows if r["goals"] == 0 and r["shots"] > 0), key=lambda r: -r["xg"])
    picked = (scorers + others)[:max(max_players, len(scorers))]
    out = []
    for r in picked:
        ev = {"player": r["name"], "team": names[r["team"]], "role": r["role"],
              "shots": r["shots"], "goals": r["goals"], "xg": r["xg"],
              "passes": r["passes"], "tackles_won": r["tackles_won"],
              "pressures": r["pressures"]}
        if r["pass_accuracy_pct"] is not None:
            ev["pass_accuracy_pct"] = r["pass_accuracy_pct"]
        out.append({"id": f"player_{r['player_id']}", "kind": "player",
                    "minute": m["duration_min"], "importance": 0, "evidence": ev})
    return out
