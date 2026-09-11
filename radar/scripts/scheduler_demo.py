"""Real proof that APScheduler fires the radar cycle automatically on an
interval, with no manual invocation. Uses a short interval (fractional
minutes) and a low per_query_limit / narrow query list purely to keep this
DEMO fast — a real deployment would use interval_minutes=30 or similar and
the full query list.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from radar.signals.alerts import AlertDispatcher  # noqa: E402
from radar.signals.scheduler import build_scheduler  # noqa: E402
from radar.signals.store import RadarStore  # noqa: E402

DB_PATH = Path(__file__).resolve().parent.parent / "scheduler_demo.db"
ALERT_LOG = Path(__file__).resolve().parent.parent / "scheduler_demo_alerts.jsonl"

fired = []


def on_done(result):
    fired.append(result)
    print(f"[scheduler fired] run_id={result.run_id} raw={result.raw_count} clusters={result.cluster_count}")


def main():
    if DB_PATH.exists():
        DB_PATH.unlink()

    store = RadarStore(DB_PATH)
    dispatcher = AlertDispatcher(log_path=ALERT_LOG, enable_desktop_toast=False)

    scheduler = build_scheduler(
        queries=["airdrop"],
        store=store,
        dispatcher=dispatcher,
        interval_minutes=0.5,  # 30s, DEMO ONLY
        per_query_limit=10,
        on_cycle_done=on_done,
    )
    print("Starting scheduler (interval=30s, demo)...")
    scheduler.start()

    demo_duration_s = 75
    print(f"Letting it run for {demo_duration_s}s to prove >=2 automatic firings...")
    time.sleep(demo_duration_s)

    scheduler.shutdown(wait=True)
    print(f"\nScheduler stopped. Automatic firings observed: {len(fired)}")
    assert len(fired) >= 2, "expected at least 2 automatic firings in the demo window"
    print("PASS: scheduler fired automatically multiple times with no manual invocation.")


if __name__ == "__main__":
    main()
