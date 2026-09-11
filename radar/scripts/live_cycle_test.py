"""Real end-to-end test of the full orchestrated cycle:
COLLECT -> NORMALIZE -> DEDUP -> CLUSTER -> PERSIST -> VELOCITY -> SCORE -> ALERT

Runs twice against live X/Reddit (via OpenCLI) with a short gap so real
velocity data emerges for opportunities seen in both runs.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from radar.signals.alerts import AlertDispatcher  # noqa: E402
from radar.signals.orchestrator import run_cycle  # noqa: E402
from radar.signals.store import RadarStore  # noqa: E402

QUERIES = ["airdrop", "giveaway", "free credits", "hackathon", "early access"]
DB_PATH = Path(__file__).resolve().parent.parent / "live_cycle_test.db"
ALERT_LOG = Path(__file__).resolve().parent.parent / "live_cycle_alerts.jsonl"


def print_result(label: str, result) -> None:
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    print(f"run_id={result.run_id} raw={result.raw_count} signals={result.signal_count} clusters={result.cluster_count} alerts_sent={result.alerts_sent}")
    top = sorted(result.scores, key=lambda s: max(s.composite_score, s.before_tiktok_score), reverse=True)[:5]
    for s in top:
        print(
            f"  opp={s.opportunity_id[:8]} cluster={s.cluster_id} signals={s.signal_count} "
            f"platforms={sorted(s.platforms)} trend={s.trend} velocity={s.velocity} "
            f"composite={s.composite_score} before_tiktok={s.before_tiktok_score}"
        )


def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    if ALERT_LOG.exists():
        ALERT_LOG.unlink()

    store = RadarStore(DB_PATH)
    dispatcher = AlertDispatcher(log_path=ALERT_LOG, enable_desktop_toast=True)

    result1 = run_cycle(QUERIES, store, dispatcher, per_query_limit=15, alert_threshold=0.5)
    print_result("CYCLE 1", result1)

    wait_s = 60
    print(f"\nWaiting {wait_s}s before cycle 2 (need a real time delta for velocity)...")
    time.sleep(wait_s)

    result2 = run_cycle(QUERIES, store, dispatcher, per_query_limit=15, alert_threshold=0.5)
    print_result("CYCLE 2", result2)

    print(f"\n{'=' * 70}\nOPPORTUNITIES SEEN IN BOTH RUNS (real velocity)\n{'=' * 70}")
    ids1 = {s.opportunity_id for s in result1.scores}
    ids2 = {s.opportunity_id for s in result2.scores}
    for opp_id in ids1 & ids2:
        snaps = store.get_snapshots(opp_id)
        print(f"opp={opp_id[:8]} snapshots={[(s['snapshot_at'][11:19], s['signal_count']) for s in snaps]}")

    n_alert_lines = sum(1 for _ in ALERT_LOG.open(encoding="utf-8")) if ALERT_LOG.exists() else 0
    print(f"\nalerts log: {ALERT_LOG} (lines: {n_alert_lines})")
    print(f"db: {DB_PATH}")


if __name__ == "__main__":
    main()
