# cry4radar

**A radar that watches X, Reddit, GitHub, Hacker News, YouTube and RSS at once, and tells you which "free credits / airdrop / rewards" post is worth your time before it's everywhere.**

Built for [First Commit — Beginner's Paradise](https://firstcommit.devpost.com/) (Devpost hackathon, Aug 21 – Sep 30, 2026).

---

## The problem

"Free credits", airdrops, hackathon prizes, referral rewards, grant programs — these opportunities get posted across six different platforms, mixed in with noise, reposts, and outright scams. By the time something trends, it's usually too late to be "early." Manually checking X, Reddit, GitHub, Hacker News, YouTube and RSS feeds all day isn't realistic.

**cry4radar** collects from all six sources in parallel, merges duplicate reports of the same real-world opportunity into one, scores each one for relevance / scam risk / how corroborated it is / how early it still is, and pushes the best ones to a Telegram bot you can also use to trigger scans remotely.

## How it works

```
COLLECT   (6 sources in parallel, ThreadPoolExecutor)
    X / Reddit        -> OpenCLI (Agent Reach) browser-session collection
    GitHub             -> gh CLI repo search
    Hacker News        -> Algolia Search API
    YouTube            -> yt-dlp flat search (no API key)
    RSS                -> feedparser (Product Hunt by default)
       |
NORMALIZE   raw posts -> a single Signal shape (courlan URL canonicalization)
       |
DEDUP       datasketch MinHash/LSH + RapidFuzz fuzzy match + shared-entity blocking
       |
CLUSTER     union-find: signals about the same real opportunity -> one cluster
       |
PERSIST     SQLite — resolves each cluster to a stable opportunity_id across
            runs, so the same opportunity is tracked over time instead of
            re-created every cycle
       |
SCORE       relevance (keyword-concept lexicon) x source independence
            (author/text/timing diversity) x risk (rule-based scam signals)
            x velocity/trend (ruptures change-point detection) -> one
            opportunity_score, plus a "Before-TikTok" earliness score
       |
ALERT       Apprise -> Windows desktop toast + Telegram, with a cooldown so
            the same still-live opportunity doesn't spam you every cycle
       |
SCHEDULE    APScheduler — run automatically every N minutes, or trigger a
            scan on demand from Telegram
```

Everything above the SCORE stage reuses mature, maintained open-source libraries (see [Third-party components](#third-party-components) / `NOTICE.md`) rather than reimplementing collection, dedup, clustering, change-point detection, or alert delivery from scratch — that's a deliberate project rule, see `CLAUDE.md`. The scoring model, the risk/relevance/independence heuristics, the cross-run identity resolution, and the Telegram bot are the actually radar-specific logic written for this project.

## What's original vs. what's reused

| Reused (open source) | Written for this project |
|---|---|
| Collection, dedup primitives, change-point detection, scheduling, alert delivery | Scoring model (relevance × independence × risk × velocity) |
| | Cross-run opportunity identity (same real-world thing tracked over days, not re-created every cycle) |
| | Scam-risk heuristics (urgency language, wallet-address requests, low source independence) |
| | The Telegram bot (`cry4scan`): commands, auto-scan scheduling, message formatting |
| | Per-source rate/limit tuning and the parallel collection pipeline itself |

## Features

- **6 sources collected in parallel** — a full cycle (14 search queries × 6 sources) finishes in ~4–7 minutes instead of running each source sequentially.
- **Real deduplication**, not just "same URL": MinHash near-duplicate text detection + fuzzy matching + shared named-entity blocking, tuned against real false positives found during testing (e.g. a bare link with no text used to falsely match everything; a short unrelated title used to falsely match a long tweet).
- **Opportunity scoring**, not just engagement counts:
  - `relevance_score` — is this actually about credits/rewards/airdrops, via a keyword-concept lexicon (plural-aware)
  - `source_independence` — is this corroborated by genuinely different people, or does it look like one account/bot ring reposting itself
  - `risk_score` / `risk_level` — rule-based scam signals (urgency language, "send your wallet address", compounds when independence is low)
  - `before_tiktok_score` — earliness × relevance, so being early only counts if it's actually on-topic
- **Cross-run identity**: the same real opportunity keeps the same internal ID across cycles, so the radar can tell you it's a 🆕 brand-new find vs. something already reported on an earlier scan — instead of the same still-live post looking like repeated spam every 30 minutes.
- **Telegram bot ("cry4scan")**: trigger scans, turn on a 30-minute auto-scan, and get results with real post content (not just bare numbers) — remotely, from anywhere.
- **Alert cooldown**: won't re-alert the same unchanged opportunity for 24h unless its score moves meaningfully.

## Tech stack

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
| Alert delivery | [Apprise](https://github.com/caronc/apprise) (desktop toast + Telegram, 100+ services supported) |
| Scheduling | [APScheduler](https://github.com/agronholm/apscheduler) (3.x) |
| Remote control | [Telegram Bot API](https://core.telegram.org/bots/api) via `requests` (long polling) |
| Tests | pytest (50 tests, synthetic/deterministic fixtures) |

Full license/attribution table: [`NOTICE.md`](NOTICE.md).

## Project structure

```
radar/
  signals/
    schema.py        Signal dataclass — the common shape every source normalizes into
    collectors.py     one function per source (X, Reddit, GitHub, HN, YouTube, RSS)
    normalize.py      raw platform post -> Signal
    clean.py          text cleaning
    dedup.py          MinHash + fuzzy + entity duplicate evidence
    cluster.py        union-find clustering into opportunities
    pipeline.py        COLLECT -> NORMALIZE -> DEDUP -> CLUSTER, 6 sources in parallel
    store.py          SQLite persistence + cross-run opportunity identity
    velocity.py       change-point trend classification (accelerating/steady/saturating)
    relevance.py      keyword-concept relevance scoring
    independence.py   source/author/timing independence scoring
    risk.py           rule-based scam-risk assessment
    scoring.py        combines all of the above into opportunity_score
    alerts.py         Apprise dispatch (desktop + Telegram)
    scheduler.py      APScheduler wiring for periodic runs
    orchestrator.py   one full cycle: pipeline -> store -> score -> alert
  tests/              pytest, 50 tests
  scripts/            benchmark/observation scripts used during development
run.py                 launcher: one cycle, or --loop for continuous
run.bat                double-click launcher (Windows)
telegram_listener.py   the cry4scan Telegram bot
telegram_listener.bat  double-click launcher (Windows)
```

## Setup

### 1. Requirements

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

### 2. Sources that need authentication

The radar degrades gracefully — you don't need all six sources working to run it.

| Source | Needs | Setup |
|---|---|---|
| GitHub | `gh` CLI, logged in | `gh auth login` |
| X / Reddit | `opencli` (Agent Reach), a real browser session | see below |
| Hacker News, YouTube, RSS | nothing | works out of the box |

For X/Reddit: install [`opencli`](https://github.com/Panniantong/Agent-Reach) (`npm i -g opencli`), then open a browser session and log into x.com / reddit.com once — the session persists for later runs:

```
opencli doctor                       # checks the browser bridge is connected
opencli browser radar open https://x.com/login
opencli browser radar open https://reddit.com/login
```

If these aren't set up, `run.py` still works — it just collects from the other four sources.

### 3. (Optional) Telegram bot

Create `.env.local` in the project root (already gitignored — never commit real tokens):

```
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

- Get a bot token from [@BotFather](https://t.me/BotFather) on Telegram (`/newbot`).
- Get your chat ID: message your new bot once, then visit
  `https://api.telegram.org/bot<TOKEN>/getUpdates` and read `message.chat.id`
  from the JSON response.

Without this file, `run.py` still works and alerts via Windows desktop toast only.

## Running

**One scan:**
```
.venv\Scripts\python run.py
```
or double-click `run.bat`.

**Continuous, every 30 minutes:**
```
.venv\Scripts\python run.py --loop
```

**Telegram bot** (lets you trigger/monitor scans remotely, from your phone):
```
.venv\Scripts\python telegram_listener.py
```
or double-click `telegram_listener.bat`. Message your bot `/help` for the full command list:

| Command | Does |
|---|---|
| `/run` | scan now |
| `/auto` | turn on a scan every 30 minutes |
| `/stop` | turn auto-scan off |
| `/top` | resend the last result instantly (no new scan) |
| `/status` | is a scan running right now, and when's the next auto-scan |
| `/help` | this list |

`/run` and the auto-scan share a lock so two scans never write to the SQLite store at the same time — you'll get a clear "a scan is already running" message instead of silent corruption.

**Tests:**
```
.venv\Scripts\python -m pytest
```

## Reading the results

Each opportunity in a Telegram report shows:

```
✅ 1. 0.40 · twitter/youtube · 12 sig · risque LOW 🆕
    "Big airdrop campaign launching next week for early testers..."
    https://x.com/example/status/123
```

- **✅ / ❔** — validated (low scam risk + clearly on-topic) vs. worth double-checking yourself
- **🆕** — the first time the radar has seen this specific opportunity
- **score** — `opportunity_score`: composite engagement/velocity/diversity/recency, discounted for off-topic content and for scam risk
- **sig** — how many independent posts across platforms are talking about this
- **risque** — `LOW` / `MEDIUM` / `HIGH`, from the rule-based risk assessment

## Third-party components

See [`NOTICE.md`](NOTICE.md) for the full list with licenses. Nothing is vendored or copied — everything is installed as a normal dependency (pip, npm, or an external CLI) and used through its public API, with attribution preserved as required by each license.

## AI usage disclosure

This project was built with significant assistance from **Claude (Anthropic's Claude Code)**, used as a pair-programming assistant throughout: architecture decisions, implementation, debugging real issues found while testing against live data, and iterating on the scoring model and the Telegram bot. Every feature was directed, reviewed, and tested by the author; the open-source-first approach, the specific scoring heuristics, and what counts as "risky" or "relevant" were project decisions made by the author, not left to the AI to invent unsupervised. Chat history is available on request per the hackathon rules.

## Known limitations

- Cross-run opportunity matching (telling "the same real opportunity" apart from "a new one") is a heuristic, not perfect — it can occasionally split one opportunity in two, or merge two similar-but-different ones.
- The relevance/risk keyword lexicons are hand-built and English-centric; they'll miss things phrased unusually or in other languages.
- X/Reddit collection depends on a logged-in browser session (`opencli`), which is the least "zero-setup" part of the stack — the other four sources need no authentication at all.

## License

No license file is included yet — all rights reserved by default. Open an issue if you'd like to use this beyond the hackathon.
