# PitchProof

Verifiable match intelligence for football, built for the Microsoft x Premier League
"Inside the Game" developer hackathon.

**Idea:** every statistic is computed deterministically in SQL. AI agents only narrate
from those computed facts, and a Checker agent rejects any claim not backed by the data.

## Pipeline

1. **Ingest** - `src/generator.py` produces synthetic, football-realistic match events (fictional clubs and players).
2. **Interpret** - `src/metrics.py` loads events into SQL and computes momentum, shot quality and pass difficulty.
3. **Explain** - Analyst + Narrator agents (coming next) explain why key moments mattered.
4. **Verify** - Checker agent (coming next) validates every number against the SQL facts.
5. **Render / personalize** - dashboard with analyst and casual-fan modes, English and Hindi (coming next).

## Quick start

```bash
python src/generator.py --seed 7 --out data/match_001.json
python src/metrics.py --events data/match_001.json --db data/pitchproof.db
```

## Data

All data is synthetic. Teams and players are fictional. No real Premier League data is used.

## Status

Work in progress for the hackathon deadline (Oct 27, 2026, 11:59 PM PT).
