-- PitchProof schema (SQLite for local dev; the same shape maps to Azure SQL).

DROP VIEW IF EXISTS v_shots;
DROP VIEW IF EXISTS v_passes;
DROP VIEW IF EXISTS v_minute_activity;
DROP VIEW IF EXISTS v_momentum;
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS players;
DROP TABLE IF EXISTS matches;

CREATE TABLE matches (
    match_id    TEXT PRIMARY KEY,
    home_name   TEXT,
    away_name   TEXT,
    home_short  TEXT,
    away_short  TEXT,
    home_goals  INTEGER,
    away_goals  INTEGER,
    duration_min INTEGER
);

CREATE TABLE players (
    player_id TEXT PRIMARY KEY,
    match_id  TEXT,
    team      TEXT,     -- HOME / AWAY
    name      TEXT,
    role      TEXT,
    number    INTEGER
);

CREATE TABLE events (
    seq            INTEGER PRIMARY KEY,
    match_id       TEXT,
    t              REAL,
    minute         INTEGER,
    team           TEXT,      -- team performing the event
    type           TEXT,      -- pass / shot / tackle / pressure / possession_change
    player_id      TEXT,
    other_player_id TEXT,     -- receiver, or the player being pressed / tackled
    x              REAL,
    y              REAL,
    end_x          REAL,
    end_y          REAL,
    length_m       REAL,
    forward        INTEGER,
    under_pressure INTEGER,
    completed      INTEGER,
    outcome        TEXT,      -- shots: goal / saved / blocked / off_target
    won            INTEGER,   -- tackles
    intensity      REAL,      -- pressure events
    ball_speed_kmh REAL,
    shot_speed_kmh REAL,
    reason         TEXT       -- possession_change reason
);

-- Shot quality (an xG-style value) from distance and goal-mouth angle.
-- pp_dist / pp_angle / pp_xg are registered by src/metrics.py.
CREATE VIEW v_shots AS
SELECT
    e.seq, e.minute, e.team, e.player_id, p.name AS player_name,
    e.outcome, e.shot_speed_kmh,
    ROUND(pp_dist(e.x, e.y, e.team), 1)              AS distance_m,
    ROUND(pp_angle(e.x, e.y, e.team), 1)             AS angle_deg,
    ROUND(pp_xg(e.x, e.y, e.team), 3)                AS xg
FROM events e
JOIN players p ON p.player_id = e.player_id
WHERE e.type = 'shot';

-- Pass difficulty 0..1: longer, forward and pressured passes are harder.
CREATE VIEW v_passes AS
SELECT
    e.seq, e.minute, e.team, e.player_id, e.other_player_id AS receiver_id,
    e.length_m, e.forward, e.under_pressure, e.completed,
    ROUND(MIN(1.0,
        0.10
        + 0.012 * e.length_m
        + CASE WHEN e.forward = 1 THEN 0.15 ELSE 0 END
        + CASE WHEN e.under_pressure = 1 THEN 0.25 ELSE 0 END
    ), 2) AS difficulty
FROM events e
WHERE e.type = 'pass';

-- Per-minute, per-team attacking weight. Every term is a count or a computed xG.
CREATE VIEW v_minute_activity AS
SELECT
    m.minute,
    m.team,
    COALESCE(a.fwd_passes, 0)    AS fwd_passes,
    COALESCE(a.shots, 0)         AS shots,
    COALESCE(a.xg, 0)            AS xg,
    COALESCE(a.pressures, 0)     AS pressures,
    COALESCE(a.tackles_won, 0)   AS tackles_won,
    COALESCE(a.turnovers_won, 0) AS turnovers_won,
    ROUND(
        0.5 * COALESCE(a.fwd_passes, 0)
      + 1.0 * COALESCE(a.pressures, 0)
      + 1.0 * COALESCE(a.tackles_won, 0)
      + 1.0 * COALESCE(a.turnovers_won, 0)
      + 3.0 * COALESCE(a.shots, 0)
      + 12.0 * COALESCE(a.xg, 0), 2) AS weight
FROM (
    SELECT mm.minute, tt.team
    FROM (SELECT DISTINCT minute FROM events) mm
    CROSS JOIN (SELECT 'HOME' AS team UNION ALL SELECT 'AWAY') tt
) m
LEFT JOIN (
    SELECT
        e.minute, e.team,
        SUM(CASE WHEN e.type = 'pass' AND e.completed = 1 AND e.forward = 1 THEN 1 ELSE 0 END) AS fwd_passes,
        SUM(CASE WHEN e.type = 'shot' THEN 1 ELSE 0 END)                                      AS shots,
        SUM(CASE WHEN e.type = 'shot' THEN pp_xg(e.x, e.y, e.team) ELSE 0 END)                AS xg,
        SUM(CASE WHEN e.type = 'pressure' THEN 1 ELSE 0 END)                                  AS pressures,
        SUM(CASE WHEN e.type = 'tackle' AND e.won = 1 THEN 1 ELSE 0 END)                      AS tackles_won,
        SUM(CASE WHEN e.type = 'possession_change' THEN 1 ELSE 0 END)                         AS turnovers_won
    FROM events e
    GROUP BY e.minute, e.team
) a ON a.minute = m.minute AND a.team = m.team;

-- Momentum: rolling 5-minute window of each side's weight, expressed as the
-- home share of total weight. 50 = even, >50 = home on top, <50 = away on top.
CREATE VIEW v_momentum AS
WITH roll AS (
    SELECT
        minute, team,
        SUM(weight) OVER (
            PARTITION BY team ORDER BY minute
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        ) AS w5
    FROM v_minute_activity
)
SELECT
    h.minute,
    ROUND(h.w5, 1) AS home_w5,
    ROUND(a.w5, 1) AS away_w5,
    ROUND(100.0 * h.w5 / NULLIF(h.w5 + a.w5, 0), 1) AS home_share
FROM roll h
JOIN roll a ON a.minute = h.minute AND a.team = 'AWAY'
WHERE h.team = 'HOME';
