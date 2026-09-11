# cry4radar

Built for [First Commit — Beginner's Paradise](https://firstcommit.devpost.com/) (Devpost hackathon, Aug 21 – Sep 30, 2026).

## What is RADAR?

RADAR is a personal tool that watches six places on the internet for opportunities worth money or time — free credits, airdrops, hackathon prizes, referral rewards, grant programs — and tells you, on Telegram, when one is actually worth acting on. Not "here are 40 results," but "here are the 1-2 that pass the bar."

## What does it monitor?

X (Twitter), Reddit, GitHub, Hacker News, YouTube, and RSS feeds — searched in parallel on a schedule (or on demand).

## Why does it exist?

These opportunities show up across six different platforms, mixed in with noise, reposts, and outright scams. By the time something's trending, it's usually too late to be early. Checking six feeds by hand all day isn't realistic, and a bot that just forwards every keyword match is worse than nothing — it teaches you to ignore it.

## How it works

```
COLLECT     6 sources in parallel (X/Reddit via OpenCLI, GitHub via gh CLI,
            Hacker News via Algolia, YouTube via yt-dlp, RSS via feedparser)
     |
NORMALIZE   raw platform posts -> one common Signal shape
     |
DEDUP       MinHash near-duplicate text + fuzzy matching + shared-entity
            blocking -> the same real opportunity reported by five people
            becomes one cluster, not five results
     |
PERSIST     SQLite resolves each cluster to a stable opportunity_id across
            runs, so the same real opportunity is tracked over time instead
            of re-created every cycle
     |
SCORE       relevance (is this actually about an opportunity, or did a
            keyword just match) x source independence (genuinely different
            people, or one account reposting itself) x risk (rule-based
            scam signals) x velocity/trend -> opportunity_score
     |
DECIDE      turns a score into one of three tiers: do it now / watch / not
            worth your time — weighing potential reward against apparent
            effort and risk, not just the raw score
     |
NOTIFY      Telegram — only "do it now" gets pushed automatically; anything
            filtered out stays reachable on request instead of arriving as
            noise
```

Everything through SCORE reuses mature, maintained open-source libraries (see [Sources / third-party components](#third-party-components) below) instead of reimplementing collection, dedup, clustering, or change-point detection from scratch — that's a deliberate project rule (`CLAUDE.md`: reuse what's solved, build only what's specific to this radar). DECIDE and NOTIFY are the two stages actually written for this project on top of that, plus the scoring model itself.

## What makes it different

Most alert bots forward every keyword match. RADAR filters before it notifies:

- **Tiered decisions, not a raw feed.** Each opportunity is classified `do_now`, `watch`, or `ignore` from its reward-vs-effort-vs-risk estimate — see `radar/signals/decision.py`. Only `do_now` gets pushed to you unasked.
- **It remembers what you did.** Tap "Ignorer" or "Faire maintenant" on Telegram and that opportunity won't be pushed at you again unless its score moves enough to mean the situation actually changed. No ML — just a remembered decision, the same cooldown logic the alert system already uses.
- **Deduplication that understands "the same thing," not just "the same URL."** MinHash + fuzzy matching + shared entities, tuned against real false positives found while testing (a bare link with no text used to match everything; a short unrelated headline used to match a long tweet).
- **A risk score that isn't a black box.** Every risk/relevance flag is a named, readable reason ("demande une adresse wallet", "urgence artificielle") you can see, not a hidden number.

## Telegram workflow

The bot is `cry4scan`. Every opportunity comes with three buttons:

```
🔥 Faisable maintenant
"Free credits worth $500 for new signups, apply before Friday"
$500 · effort faible · twitter/youtube

Pourquoi:
• récompense annoncée
• places limitées ou deadline

[🔎 Approfondir]  [✅ Faire maintenant]  [🚫 Ignorer]
```

- **Approfondir** — full detail for *that one opportunity*: score breakdown, why it was flagged, risk concerns if any, when it was first detected, the source link. Not the whole list again.
- **Faire maintenant** — marks it as taken care of so it stops being pushed. RADAR never submits forms, connects a wallet, or acts on your behalf — this button is a bookmark, not automation of the actual opportunity.
- **Ignorer** — same idea, the other direction: stop pushing this specific one.

Commands:

| Command | Does |
|---|---|
| `/run` | scan now — short summary: what's actionable, best pick with full detail, a couple more as one-tap buttons |
| `/auto` | scan every 30 minutes automatically — completely silent unless something clears the `do_now` bar |
| `/stop` | turn auto-scan off |
| `/top` | current actionable list (do_now + watch), one button per opportunity |
| `/status` | is a scan running, is auto-scan on, when's the next one |
| `/help` | this list |

## Architecture

```
radar/
  signals/
    schema.py        Signal — the common shape every source normalizes into
    collectors.py     one function per source (X, Reddit, GitHub, HN, YouTube, RSS)
    normalize.py      raw platform post -> Signal
    clean.py          text cleaning
    dedup.py          MinHash + fuzzy + entity duplicate evidence
    cluster.py        union-find clustering into opportunities
    pipeline.py        COLLECT -> NORMALIZE -> DEDUP -> CLUSTER, 6 sources in parallel
    store.py          SQLite: cross-run opportunity identity, alert cooldown, decisions
    velocity.py       change-point trend classification (accelerating/steady/saturating)
    relevance.py      keyword-concept relevance scoring
    independence.py   source/author/timing independence scoring
    risk.py           rule-based scam-risk assessment
    scoring.py        combines the above into opportunity_score
    decision.py       score -> do_now / watch / ignore, with human-readable reasons
    alerts.py         desktop toast + JSONL audit log (Apprise)
    scheduler.py      APScheduler wiring for periodic runs
    orchestrator.py   one full cycle: pipeline -> store -> score -> alert
  tests/              pytest
run.py                 launcher: one cycle, or --loop for continuous
run.bat                double-click launcher (Windows)
telegram_listener.py   the cry4scan Telegram bot (owns all Telegram formatting/delivery)
telegram_listener.bat  double-click launcher (Windows)
```

## Sources / third-party components

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Storage | SQLite (stdlib) |
| Parallelism | `concurrent.futures.ThreadPoolExecutor` |
| X / Reddit collection | [OpenCLI (Agent Reach)](https://github.com/Panniantong/Agent-Reach) — browser-session backend |
| GitHub collection | [GitHub CLI (`gh`)](https://github.com/cli/cli) |
| Hacker News collection | [HN Algolia Search API](https://hn.algolia.com/api) |
| YouTube collection | [yt-dlp](https://github.com/yt-dlp/yt-dlp) |
| RSS collection | [feedparser](https://github.com/kurtmckee/feedparser) |
| URL canonicalization | [courlan](https://github.com/adbar/courlan) |
| Near-duplicate detection | [datasketch](https://github.com/ekzhu/datasketch) (MinHash/LSH) |
| Fuzzy text matching | [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) |
| Trend / change-point detection | [ruptures](https://github.com/deepcharles/ruptures) |
| Desktop notifications | [Apprise](https://github.com/caronc/apprise) (Windows toast) |
| Scheduling | [APScheduler](https://github.com/agronholm/apscheduler) (3.x) |
| Telegram bot | [Telegram Bot API](https://core.telegram.org/bots/api) via `requests` (long polling + inline keyboards) |
| Tests | pytest |

Full license/attribution table: [`NOTICE.md`](NOTICE.md). Nothing is vendored or copied — everything is installed as a normal dependency and used through its public API, per the project's [open-source-first rule](CLAUDE.md).

## Installation

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

RADAR degrades gracefully — you don't need all six sources working.

| Source | Needs | Setup |
|---|---|---|
| GitHub | `gh` CLI, logged in | `gh auth login` |
| X / Reddit | `opencli` (Agent Reach), a real browser session | see below |
| Hacker News, YouTube, RSS | nothing | works out of the box |

For X/Reddit: install [`opencli`](https://github.com/Panniantong/Agent-Reach) (`npm i -g opencli`), then log into x.com / reddit.com once through it — the session persists for later runs:

```
opencli doctor
opencli browser radar open https://x.com/login
opencli browser radar open https://reddit.com/login
```

Without this, `run.py` still works — it just collects from the other four sources.

## Configuration

For the Telegram bot, create `.env.local` in the project root (gitignored — never commit real tokens):

```
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

- Get a bot token from [@BotFather](https://t.me/BotFather) (`/newbot`).
- Get your chat ID: message your new bot once, then visit `https://api.telegram.org/bot<TOKEN>/getUpdates` and read `message.chat.id` from the response.

Without this file, `run.py` still works and alerts via Windows desktop toast only. Query list and the do_now/watch thresholds live in `run.py` (`DEFAULT_QUERIES`, `ALERT_THRESHOLD`) and `radar/signals/decision.py` if you want to tune them.

## Running

**One scan:**
```
.venv\Scripts\python run.py
```
or double-click `run.bat`.

**Continuous, every 30 minutes, no Telegram:**
```
.venv\Scripts\python run.py --loop
```

**Telegram bot** (the actual day-to-day interface):
```
.venv\Scripts\python telegram_listener.py
```
or double-click `telegram_listener.bat`. See [Telegram workflow](#telegram-workflow) above for the commands.

`/run` and the auto-scan share a lock so two scans never write to the SQLite store at the same time.

## Tests

```
.venv\Scripts\python -m pytest
```

## AI usage disclosure

Built with significant assistance from **Claude (Anthropic's Claude Code)**, used as a pair-programming assistant throughout: architecture, implementation, debugging real issues found while testing against live data, and iterating on the scoring model and the Telegram bot. Every feature was directed, reviewed, and tested by the author; the open-source-first approach, the specific scoring/decision heuristics, and what counts as "risky" or "worth pushing" were project decisions made by the author, not left to the AI to invent unsupervised. Chat history available on request per the hackathon rules.

## Known limitations

- Cross-run opportunity matching (telling "the same real opportunity" apart from "a new one") is a heuristic, not perfect — it can occasionally split one opportunity in two, or merge two similar-but-different ones.
- The relevance/risk/decision heuristics are hand-tuned against a limited amount of real data so far, and English-centric — they'll miss things phrased unusually or in other languages.
- RADAR detects and scores; it doesn't yet verify against the opportunity's own source (official rules page, real deadline, eligibility) before notifying — that's the next thing to build, not something it currently claims to do.
- X/Reddit collection depends on a logged-in browser session (`opencli`), the least "zero-setup" part of the stack — the other four sources need no authentication at all.

## License

No license file is included yet — all rights reserved by default. Open an issue if you'd like to use this beyond the hackathon.
