"""Synthetic football match event generator.

Produces a football-realistic stream of events for two fictional clubs.
All names are invented. Output is JSON with match metadata and an ordered
list of events (pass, shot, tackle, possession_change, pressure).

Usage:
    python src/generator.py --seed 7 --out data/match_001.json
"""
import argparse
import json
import math
import random

PITCH_L, PITCH_W = 105.0, 68.0

CLUBS = {
    "HOME": {"name": "Rivergate United", "short": "RGU"},
    "AWAY": {"name": "Northbridge Athletic", "short": "NBA"},
}

FIRST = ["Luca", "Marco", "Kofi", "Idris", "Tomas", "Ben", "Rahul", "Jonas", "Mateo",
         "Yusuf", "Eli", "Dario", "Niko", "Sami", "Omar", "Felix", "Arjun", "Theo"]
LAST = ["Voss", "Mercer", "Adeyemi", "Haldane", "Okoro", "Brandt", "Castell", "Ibarra",
        "Novak", "Fenwick", "Sorensen", "Delacroix", "Marlow", "Quill", "Rennick",
        "Tamsin", "Ashby", "Kovac"]

# 4-4-2 style roles with a base x position (0 = own goal line, 1 = opposition goal line)
ROLES = [
    ("GK", 0.04), ("RB", 0.22), ("CB", 0.20), ("CB", 0.20), ("LB", 0.22),
    ("RM", 0.50), ("CM", 0.46), ("CM", 0.46), ("LM", 0.50), ("ST", 0.78), ("ST", 0.76),
]


def build_squad(rng, side):
    names = set()
    squad = []
    for i, (role, base_x) in enumerate(ROLES, start=1):
        while True:
            n = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            if n not in names:
                names.add(n)
                break
        squad.append({
            "player_id": f"{side}{i:02d}",
            "name": n,
            "role": role,
            "number": i,
            "base_x": base_x,
            "skill": round(rng.uniform(0.55, 0.9), 2),
        })
    return squad


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def pick_player(rng, squad, bias_x):
    weights = []
    for p in squad:
        w = 1.0 / (0.15 + abs(p["base_x"] - bias_x))
        if p["role"] == "GK":
            w *= 0.3
        weights.append(w)
    return rng.choices(squad, weights=weights, k=1)[0]


def player_pos(rng, p, attacking_dir):
    x = p["base_x"] * PITCH_L + rng.uniform(-8, 8)
    x = min(max(x, 1), PITCH_L - 1)
    y = rng.uniform(4, PITCH_W - 4)
    # attacking_dir = 1: attacks toward x = 105. attacking_dir = -1: mirrored.
    if attacking_dir == -1:
        x = PITCH_L - x
    return (round(x, 1), round(y, 1))


def generate(seed=7, minutes=90, rate_per_min=5.5):
    rng = random.Random(seed)
    squads = {"HOME": build_squad(rng, "H"), "AWAY": build_squad(rng, "A")}
    dirs = {"HOME": 1, "AWAY": -1}
    # Fixed team strength gives matches a plausible, uneven shape.
    strength = {"HOME": rng.uniform(0.95, 1.1), "AWAY": rng.uniform(0.9, 1.05)}

    events = []
    score = {"HOME": 0, "AWAY": 0}
    possession = rng.choice(["HOME", "AWAY"])
    # Momentum drifts over time so there are real spells of pressure.
    pressure_bias = {"HOME": 0.0, "AWAY": 0.0}
    total_ticks = int(minutes * rate_per_min)
    seq = 0

    for tick in range(total_ticks):
        t_sec = tick * (60.0 / rate_per_min) + rng.uniform(0, 4)
        minute = int(t_sec // 60)
        if minute >= minutes:
            break
        if tick % 40 == 0:
            pressure_bias["HOME"] = rng.uniform(-0.12, 0.12)
            pressure_bias["AWAY"] = rng.uniform(-0.12, 0.12)

        team = possession
        opp = "AWAY" if team == "HOME" else "HOME"
        d = dirs[team]
        squad = squads[team]
        p = pick_player(rng, squad, 0.5)
        pos = player_pos(rng, p, d)
        # progress of the ball toward goal, 0..1
        prog = pos[0] / PITCH_L if d == 1 else (PITCH_L - pos[0]) / PITCH_L

        seq += 1
        base = {"seq": seq, "t": round(t_sec, 1), "minute": minute, "team": team}

        # Pressure events (defending side applying pressure)
        if rng.random() < 0.12 + max(0, pressure_bias[opp]):
            defender = pick_player(rng, squads[opp], 1 - prog)
            events.append({**base, "type": "pressure", "team": opp,
                           "player_id": defender["player_id"],
                           "on_player_id": p["player_id"],
                           "x": pos[0], "y": pos[1],
                           "intensity": round(rng.uniform(0.3, 1.0), 2)})
            seq += 1
            base = {"seq": seq, "t": round(t_sec + 0.4, 1), "minute": minute, "team": team}

        r = rng.random()
        shot_p = 0.01 + 0.16 * prog ** 2 * strength[team]
        if r < shot_p:
            # Re-place the shooter in a realistic shooting position
            # (most shots come from 8-25 m, skewed toward the centre).
            dx = rng.triangular(5.0, 30.0, 12.0)
            dy = max(-24.0, min(24.0, rng.gauss(0, 8.5)))
            sx = PITCH_L - dx if d == 1 else dx
            pos = (round(sx, 1), round(PITCH_W / 2 + dy, 1))
            distance = math.hypot(dx, dy)
            angle = math.degrees(math.atan2(7.32 * dx, dx * dx + dy * dy - (7.32 / 2) ** 2))
            angle = max(angle, 1.0)
            # Synthetic "true" shot quality used to decide the outcome; metrics
            # recompute their own xG-style value later from distance and angle.
            true_q = max(0.01, min(0.6, 0.9 * math.exp(-distance / 11.0) * (angle / 40.0)))
            true_q = min(0.65, true_q * p["skill"] * 1.2)
            u = rng.random()
            if u < true_q:
                outcome = "goal"
            elif u < true_q + 0.30:
                outcome = "saved"
            elif u < true_q + 0.55:
                outcome = "blocked"
            else:
                outcome = "off_target"
            speed = round(rng.uniform(70, 125) * (0.9 + 0.2 * p["skill"] / 0.9), 1)
            events.append({**base, "type": "shot", "player_id": p["player_id"],
                           "x": pos[0], "y": pos[1], "outcome": outcome,
                           "shot_speed_kmh": speed})
            if outcome == "goal":
                score[team] += 1
                events[-1]["score_after"] = dict(score)
                possession = opp
            else:
                possession = opp if rng.random() < 0.6 else team
            continue

        r2 = rng.random()
        if r2 < 0.74:
            # Pass
            target = pick_player(rng, squad, min(1.0, prog + rng.uniform(-0.1, 0.2)))
            tpos = player_pos(rng, target, d)
            plen = dist(pos, tpos)
            long_ball = plen > 28
            forward = (tpos[0] - pos[0]) * d > 6
            base_acc = 0.93 - 0.006 * plen - (0.05 if forward else 0.0)
            under_pressure = events and events[-1]["type"] == "pressure" and events[-1]["on_player_id"] == p["player_id"]
            if under_pressure:
                base_acc -= 0.12
            acc = max(0.25, min(0.97, base_acc * (0.85 + 0.2 * p["skill"] * strength[team])))
            complete = rng.random() < acc
            events.append({**base, "type": "pass", "player_id": p["player_id"],
                           "receiver_id": target["player_id"],
                           "x": pos[0], "y": pos[1], "end_x": tpos[0], "end_y": tpos[1],
                           "length_m": round(plen, 1), "forward": forward,
                           "under_pressure": bool(under_pressure),
                           "completed": complete,
                           "ball_speed_kmh": round(rng.uniform(35, 90) if long_ball else rng.uniform(25, 60), 1)})
            if not complete:
                possession = opp
                seq += 1
                events.append({"seq": seq, "t": round(t_sec + 0.8, 1), "minute": minute,
                               "team": opp, "type": "possession_change",
                               "reason": "pass_intercepted", "x": tpos[0], "y": tpos[1]})
        elif r2 < 0.90:
            # Tackle by the opposing side
            defender = pick_player(rng, squads[opp], 1 - prog)
            won = rng.random() < 0.5
            events.append({**base, "type": "tackle", "team": opp,
                           "player_id": defender["player_id"],
                           "on_player_id": p["player_id"],
                           "x": pos[0], "y": pos[1], "won": won})
            if won:
                possession = opp
                seq += 1
                events.append({"seq": seq, "t": round(t_sec + 0.6, 1), "minute": minute,
                               "team": opp, "type": "possession_change",
                               "reason": "tackle_won", "x": pos[0], "y": pos[1]})
        else:
            # Carry / dribble, treated as a short pass-like action with no receiver
            possession = team

    match = {
        "match_id": f"SYN-{seed:04d}",
        "synthetic": True,
        "competition": "Synthetic League",
        "home": {**CLUBS["HOME"], "squad": squads["HOME"]},
        "away": {**CLUBS["AWAY"], "squad": squads["AWAY"]},
        "final_score": score,
        "duration_min": minutes,
    }
    return {"match": match, "events": events}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--minutes", type=int, default=90)
    ap.add_argument("--out", default="data/match_001.json")
    args = ap.parse_args()
    data = generate(args.seed, args.minutes)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    ev = data["events"]
    counts = {}
    for e in ev:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    print(f"Wrote {len(ev)} events to {args.out}")
    print("Score:", data["match"]["final_score"])
    print("Counts:", counts)


if __name__ == "__main__":
    main()
