# RADAR

Opportunity radar: collects X/Reddit signals, deduplicates them into real-world
opportunity clusters, tracks them over time, scores them, and alerts on the
interesting ones. Built per the Open Source First rule in `CLAUDE.md`: reuse
mature OSS for solved problems, write only the radar-specific glue and
domain logic ourselves.

## Pipeline

```
COLLECT (OpenCLI: X + Reddit)
  -> NORMALIZE (Signal schema, courlan URL canonicalization)
  -> CLEAN (text normalization)
  -> DEDUP (datasketch MinHash/LSH + RapidFuzz + entity blocking)
  -> CLUSTER (union-find -> opportunity clusters)
  -> PERSIST (SQLite, cross-run opportunity identity resolution)
  -> VELOCITY (ruptures change-point detection -> accelerating/steady/saturating)
  -> SCORE (composite score + "Before-TikTok" early-detection score)
  -> ALERT (Apprise -> desktop toast now, WhatsApp/Slack/email/webhook later)
  -> SCHEDULE (APScheduler, periodic runs)
```

## Layout

```
radar/signals/
  schema.py        Signal dataclass
  collectors.py     OpenCLI subprocess wrappers (X + Reddit)
  clean.py          text cleaning
  normalize.py      RawPost -> Signal
  dedup.py          multi-method duplicate evidence
  cluster.py        union-find clustering
  pipeline.py       COLLECT -> ... -> CLUSTER
  store.py          SQLite persistence + cross-run opportunity matching
  velocity.py       velocity + trend classification (ruptures)
  scoring.py        composite score + before_tiktok_score
  alerts.py         Apprise dispatch + JSONL audit log
  scheduler.py      APScheduler wiring
  orchestrator.py   full cycle: pipeline -> store -> score -> alert
tests/              pytest, synthetic/deterministic
scripts/
  live_test.py         real Brick-1-only test (collect -> cluster)
  live_cycle_test.py   real full-cycle test (2 runs, real velocity)
```

## Setup

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Requires `opencli` (Agent Reach) already installed and authenticated for X
and Reddit (see project history — already done).

## Running

```
.venv\Scripts\python scripts\live_cycle_test.py   # one-shot real test, 2 cycles
```

To run continuously, use `radar.signals.scheduler.build_scheduler(...)` and
call `.start()` — see `scheduler.py` docstring-level usage in `orchestrator.py`.
Not started automatically by default: a persistent background process is a
choice to make deliberately (resource use, when to stop it), not something
to leave running silently.

## Explicitly out of scope (needs your input, not a technical gap)

- **WhatsApp delivery**: `alerts.py` is Apprise-based, so adding WhatsApp is
  one Apprise URL away — but it needs a WhatsApp Business API token from
  your Meta account, which only you can obtain/authorize.
- **Dashboard/frontend**: a product decision (framework, hosting, who's the
  audience) rather than a technical brick — not built here to avoid
  guessing requirements and producing throwaway UI.

## Third-party components

See `NOTICE.md`.
