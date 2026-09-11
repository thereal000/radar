"""Simple launcher for RADAR.

Usage:
    run.py                 one cycle, prints results, sends alerts (desktop + Telegram if configured)
    run.py --loop          runs continuously every 30 min (Ctrl+C to stop)
    run.py --loop 10       runs continuously every 10 min

Telegram: put TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.local
(gitignored, never committed) to receive alerts there too. Without it,
only the Windows desktop toast fires.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from radar.signals.alerts import AlertDispatcher
from radar.signals.orchestrator import run_cycle
from radar.signals.store import RadarStore

DEFAULT_QUERIES = [
    "free credits", "creator rewards", "referral rewards", "testnet rewards",
    "beta rewards", "hackathon prize", "grant program", "token airdrop",
    "points campaign", "early access rewards", "NFT distribution", "limited giveaway",
]


def load_env_local() -> dict[str, str]:
    env_path = Path(__file__).resolve().parent / ".env.local"
    values: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def build_dispatcher() -> AlertDispatcher:
    env = load_env_local()
    extra_urls = []
    token = env.get("TELEGRAM_BOT_TOKEN")
    chat_id = env.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        extra_urls.append(f"tgram://{token}/{chat_id}")
        print("[run] Telegram alerts: enabled")
    else:
        print("[run] Telegram alerts: not configured (.env.local missing TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID)")
    return AlertDispatcher(enable_desktop_toast=True, extra_apprise_urls=extra_urls)


def run_once() -> None:
    store = RadarStore()
    dispatcher = build_dispatcher()

    print(f"[run] starting cycle — {len(DEFAULT_QUERIES)} queries, 6 sources...")
    t0 = time.perf_counter()
    result = run_cycle(DEFAULT_QUERIES, store, dispatcher)
    elapsed = time.perf_counter() - t0

    print(f"\n{'=' * 70}")
    print(f"raw={result.raw_count}  signals={result.signal_count}  clusters={result.cluster_count}  alerts_sent={result.alerts_sent}  time={elapsed:.1f}s")
    print(f"{'=' * 70}")

    top = sorted(result.scores, key=lambda s: s.opportunity_score, reverse=True)[:10]
    print("\nTop 10 opportunities:")
    for s in top:
        print(
            f"  score={s.opportunity_score:.3f}  relevance={s.relevance_score:.2f}  risk={s.risk_level:6s}  "
            f"signals={s.signal_count:3d}  platforms={sorted(s.platforms)}  trend={s.trend}"
        )


def run_loop(interval_minutes: float) -> None:
    store = RadarStore()
    dispatcher = build_dispatcher()

    def on_done(result):
        top = sorted(result.scores, key=lambda s: s.opportunity_score, reverse=True)[:5]
        print(f"\n[cycle done] raw={result.raw_count} signals={result.signal_count} clusters={result.cluster_count} alerts={result.alerts_sent}")
        for s in top:
            print(f"  score={s.opportunity_score:.3f} risk={s.risk_level} platforms={sorted(s.platforms)}")

    from radar.signals.scheduler import build_scheduler
    scheduler = build_scheduler(
        DEFAULT_QUERIES, store, dispatcher,
        interval_minutes=interval_minutes,
        on_cycle_done=on_done,
    )
    print(f"[run] scheduler started — one cycle every {interval_minutes} min. Ctrl+C to stop.")
    scheduler.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[run] stopping...")
        scheduler.shutdown(wait=True)


if __name__ == "__main__":
    if "--loop" in sys.argv:
        idx = sys.argv.index("--loop")
        interval = float(sys.argv[idx + 1]) if len(sys.argv) > idx + 1 and sys.argv[idx + 1].replace(".", "", 1).isdigit() else 30
        run_loop(interval)
    else:
        run_once()
