# Changelog

## 2026-09-14 — reliability + correctness pass

Findings and fixes from a full ownership pass (explore → probe → fuzz →
fix → verify). Every fix below has a regression test in `tests/`.

### Fixed — real bugs, reproduced before fixing

- **Scoring: `diversity_score` could exceed 1.0.** It was hard-coded as
  `len(platforms) / 2` back when only X + Reddit existed. After the radar
  grew to six sources, a cluster seen on 4 platforms scored `diversity = 2.0`,
  inflating `composite_score` (and therefore `opportunity_score`) by up to
  +0.15 in the wrong direction. Now normalized against a named constant
  (`_DIVERSITY_FULL_AT = 3`) and capped at 1.0; `confidence_score`, which
  depends on it, is bounded too. (`radar/signals/scoring.py`)

- **Pipeline: one malformed post aborted the whole cycle.** A Twitter
  `views` value like `"1.2K"` or `"N/A"` (both real shapes from third-party
  CLIs/APIs) raised `ValueError: invalid literal for int()` inside
  `normalize_twitter_post`. Because `normalize_by_source` had no guard,
  that single item aborted normalization for **every source** in the run.
  Engagement counters now go through a lenient `_safe_int` (handles ints,
  `"1,234"`, `"1.2K"`, `"3M"`, junk → `None`), and `normalize_by_source`
  normalizes each item in isolation, skipping (with a warning) only the bad
  one. (`radar/signals/normalize.py`, `radar/signals/pipeline.py`)

- **Dedup: distinct id-less items collapsed into one.** `_dedupe_raw_by_id`
  keyed on `str(p.get("id"))`, so every raw item without an `id` — e.g. an
  RSS entry with no `<guid>` — became the literal key `"None"` and merged
  into a single signal. Now keyed on a per-source natural key
  (`id`/`fullName`/`objectID`/`guid`/`link`/`url`, else a content
  fingerprint). (`radar/signals/pipeline.py`)

- **Clustering: duplicate `(source, source_id)` key crashed the cycle.**
  `datasketch`'s `MinHashLSH.insert` raises `ValueError: The given key
  already exists` on a duplicate key. Two signals can share a key when the
  upstream id was missing (both `"None"`), which took down the whole run.
  Both `build_clusters` and `build_lsh_index` now de-duplicate keys, keeping
  the first occurrence. (`radar/signals/cluster.py`, `radar/signals/dedup.py`)

- **Persistence: non-string fields reached SQLite.** `author`, `url`,
  `subreddit`, `published_at`/`updatedAt`/`created_at`, GitHub `fullName`
  (used as `title`) and `owner` were written straight into SQLite. A
  non-string value raised `sqlite3.ProgrammingError: Error binding
  parameter: type 'dict' is not supported` and aborted the persist step.
  All externally-sourced text fields are now coerced via `_as_str`
  (str, or int/float, else `None`); a non-dict `owner` degrades to `{}`.
  (`radar/signals/normalize.py`)

- **Counter overflow.** Engagement counters are now clamped to ±10^15, so a
  sum can never overflow SQLite's int64. (`radar/signals/normalize.py`)

- **Timestamp parsing crashed on non-strings.** `datetime.fromisoformat`
  raises `TypeError` (not `ValueError`) on a non-string, which escaped
  `ValueError`-only guards in `velocity.py`, `independence.py` and
  `scoring._hours_since`. All three now guard on type as well.
  (`radar/signals/velocity.py`, `radar/signals/independence.py`,
  `radar/signals/scoring.py`)

### Hardened

- **VERIFY only ever fetches http(s).** Candidate links are scraped out of
  third-party post text; a non-web scheme (`javascript:`, `file:`, `data:`,
  …) is now rejected before it can reach the browser bridge.
  (`radar/signals/verify_hackathon.py`)

- **`extract_entities` is type-safe.** It returns early on a non-string
  instead of raising inside a regex. (`radar/signals/dedup.py`)

### Performance

- **Deterministic `text → MinHash` cache.** `build_minhash` results are
  cached by text (they are deterministic and only ever read). Cross-run
  matching rebuilds the MinHash of every previously stored opportunity on
  every run; the cache removes that repeated work for any representative
  text seen before (~1.8× on a 400-stored × 120-new micro-benchmark).
  (`radar/signals/dedup.py`)

### Project hygiene

- Added the missing **`LICENSE`** (MIT) — required for the First Commit
  hackathon and implied by the project's open-source-first rule.
- Added **`.env.local.example`** so setup doesn't require guessing the
  config keys.
- Added `tests/test_robustness.py` (11 regression tests) covering every
  fix above.

### Verification

- `pytest`: **80 passed** (was 69).
- Fuzz harness (1 500 random/malformed batches through
  normalize → cluster → persist → score → decide): **0 unhandled
  exceptions** (was 25 distinct).
- Live run against real network sources (GitHub, HN, YouTube, RSS):
  175 signals → 166 clusters persisted; second run resolved 10 clusters
  to existing ids with **0** spurious new opportunities.
