"""Real observation phase: run several real collection cycles against the
persistent radar.db (default DB, so history accumulates across runs) and
report on what actually happened — no new architecture, just running what
already exists and recording real behavior for manual review.

Desktop toast is disabled here (would fire repeatedly across cycles); the
JSONL alert log is kept so alert repetition can be measured.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from radar.signals.alerts import AlertDispatcher  # noqa: E402
from radar.signals.orchestrator import run_cycle  # noqa: E402
from radar.signals.store import DEFAULT_DB_PATH, RadarStore  # noqa: E402

QUERIES = [
    "free", "giveaway", "rewards", "airdrop", "free credits",
    "grant", "hackathon", "early access", "points", "event reward",
]
ALERT_LOG = Path(__file__).resolve().parent.parent / "observe_alerts.jsonl"
N_CYCLES = 3
GAP_SECONDS = 240  # 4 min between cycles


def print_result(label: str, result) -> None:
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    print(f"run_id={result.run_id} raw={result.raw_count} signals={result.signal_count} clusters={result.cluster_count} alerts_sent={result.alerts_sent}")
    top = sorted(result.scores, key=lambda s: max(s.composite_score, s.before_tiktok_score), reverse=True)[:8]
    for s in top:
        print(
            f"  opp={s.opportunity_id[:8]} cluster={s.cluster_id} signals={s.signal_count} "
            f"platforms={sorted(s.platforms)} trend={s.trend} velocity={s.velocity} "
            f"composite={s.composite_score} before_tiktok={s.before_tiktok_score}"
        )


def main() -> None:
    print(f"DB (persistent, existing history kept): {DEFAULT_DB_PATH}")
    store = RadarStore(DEFAULT_DB_PATH)
    dispatcher = AlertDispatcher(log_path=ALERT_LOG, enable_desktop_toast=False)

    results = []
    for i in range(N_CYCLES):
        result = run_cycle(QUERIES, store, dispatcher, per_query_limit=15, alert_threshold=0.5)
        print_result(f"CYCLE {i + 1}/{N_CYCLES}", result)
        results.append(result)
        if i < N_CYCLES - 1:
            print(f"\nWaiting {GAP_SECONDS}s before next cycle...")
            time.sleep(GAP_SECONDS)

    print(f"\n{'=' * 70}\nALL TRACKED OPPORTUNITIES (sorted by max score)\n{'=' * 70}")
    all_ids = {s.opportunity_id for r in results for s in r.scores}
    print(f"total distinct opportunities touched this session: {len(all_ids)}")

    # opportunities seen with >=2 snapshots (real velocity possible)
    multi_snap = []
    for opp_id in all_ids:
        snaps = store.get_snapshots(opp_id)
        if len(snaps) >= 2:
            multi_snap.append((opp_id, snaps))
    print(f"opportunities with >=2 real snapshots: {len(multi_snap)}")
    for opp_id, snaps in sorted(multi_snap, key=lambda x: -x[1][-1]["signal_count"])[:15]:
        series = [(s["snapshot_at"][11:19], s["signal_count"]) for s in snaps]
        print(f"  opp={opp_id[:8]} series={series}")

    n_alert_lines = sum(1 for _ in ALERT_LOG.open(encoding="utf-8")) if ALERT_LOG.exists() else 0
    print(f"\nalert log lines this session: {n_alert_lines} (log: {ALERT_LOG})")


if __name__ == "__main__":
    main()
