# PitchProof

Verifiable match intelligence for football, built for the Microsoft x Premier League
"Inside the Game" developer hackathon.

**Idea:** every statistic is computed deterministically in SQL. Agents only narrate from
those computed facts, and a Checker agent rejects any number or name that is not backed by
the data. Nothing unverified reaches the viewer.

## Pipeline

| Stage | Component | What it does |
|---|---|---|
| Ingest | `src/generator.py` | Synthetic, football-realistic match events (fictional clubs and players) |
| Interpret | `sql/schema.sql`, `src/metrics.py` | xG-style shot quality, pass difficulty and rolling momentum, computed in SQL |
| Explain | `src/moments.py` (Analyst) | Picks key moments (goals, momentum swings, recap) and attaches numeric evidence |
| Explain | `src/narrator.py` (Narrator) | Writes each moment and each player spotlight for an audience (analyst / casual fan) in English and Hindi |
| Verify | `src/checker.py` (Checker) | Rejects numbers or names not in the evidence, and numbers attached to the wrong unit ("4 goals" when goals = 1); the Narrator retries with feedback |
| Orchestrate | `src/pipeline.py` | Handoffs, retry (3 attempts), safe template fallback, full trace log |
| Render | `src/build_dashboard.py`, `docs/index.html` | Single-file dashboard: match clock with play, momentum chart, shot map, analyst / casual modes, English / Hindi, favourite club and favourite player, per-moment evidence, Checker demo |

## Quick start (Python 3, no installs)

```bash
python src/generator.py --seed 26 --out data/match_001.json
python src/metrics.py --events data/match_001.json --db data/pitchproof.db
python src/pipeline.py --db data/pitchproof.db --out data/narration.json
PITCHPROOF_DEMO_FAULT=1 python src/pipeline.py --db data/pitchproof.db --out data/narration_fault_demo.json
python src/build_dashboard.py          # writes docs/index.html
python -m unittest discover -s tests -v
```

On Windows PowerShell, set the fault flag with `$env:PITCHPROOF_DEMO_FAULT=1` before the command
(and `Remove-Item Env:PITCHPROOF_DEMO_FAULT` afterwards).

## Dashboard

Open `docs/index.html` in any browser (no server needed). To publish it for free on GitHub Pages:
repository **Settings -> Pages -> Build and deployment -> Deploy from a branch -> `main` -> `/docs`**.
Press Play to run the match clock, or drag it. Each narration has a "Verified against SQL facts"
section that shows the evidence it was checked against and what produced the text.

## Models

By default the Narrator runs **offline** with deterministic templates (provider `mock`), so
the whole pipeline and the Checker can be tested without a model. In this mode no language
model is involved in the narration text.

To use a real model, set environment variables (never commit keys; `.env` is git-ignored):

- **Azure OpenAI / Microsoft Foundry:** `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`,
  optionally `AZURE_OPENAI_DEPLOYMENT` (default `gpt-4o-mini`)
- **GitHub Models (opt-in):** `PITCHPROOF_PROVIDER=github` and `GITHUB_MODELS_TOKEN`

## How well does the Checker work?

Measured on the synthetic demo match (offline templates, 20 automated tests in `tests/`):

- **Injected faults:** `PITCHPROOF_DEMO_FAULT=1 python src/pipeline.py` makes the Narrator print one
  wrong number per narration on its first attempt. The Checker rejects all 48 and the retry passes.
- **Mutation test:** every number in every narration is changed one at a time (642 mutations).
  The Checker rejects 99.1%. The rest are whole-number roundings (72.1% as 72.0%), tolerated on
  purpose so a model that writes "72%" is not wrongly rejected.
- **False alarms:** none on the 48 clean narrations.

Why unit binding matters: an early version only checked that a number appeared *somewhere* in the
evidence, so "scored 4 goals" passed when the player had 1 goal but 4 tackles. The Checker now ties
each number to its unit (goals, shots, xG, %, minutes, score order, and so on).

Known limits: number words ("three") are not parsed (the Narrator is told to write digits), and a
figure in free phrasing with no recognised unit is only checked against the whole evidence, so a
swap there would not be caught. These results come from simulated faults on templates. They are
not a measurement of how often a real language model makes mistakes; that is untested.

## Data

All data is synthetic. Teams and players are fictional. No real Premier League data is used.

## Status

Work in progress for the hackathon deadline (Oct 27, 2026, 11:59 PM PT).
