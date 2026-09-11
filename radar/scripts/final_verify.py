"""Final regression check requested after the observation phase: one more
real cycle against the SAME persistent radar.db (which already has 3 prior
real cycles' history, including the de7f250c iPhone-giveaway spam cluster
that fired 3 identical alerts before the cooldown fix). If the fix works,
this 4th cycle must NOT re-alert it (same score, no cooldown elapsed).
"""
from __future__ import annotations

import sys
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


def main() -> None:
    store = RadarStore(DEFAULT_DB_PATH)
    dispatcher = AlertDispatcher(log_path=ALERT_LOG, enable_desktop_toast=False)

    n_lines_before = sum(1 for _ in ALERT_LOG.open(encoding="utf-8")) if ALERT_LOG.exists() else 0

    result = run_cycle(QUERIES, store, dispatcher, per_query_limit=15, alert_threshold=0.5)

    n_lines_after = sum(1 for _ in ALERT_LOG.open(encoding="utf-8")) if ALERT_LOG.exists() else 0
    new_alerts = n_lines_after - n_lines_before

    print(f"CYCLE 4 (regression check): run_id={result.run_id} raw={result.raw_count} clusters={result.cluster_count}")
    print(f"alerts_sent this cycle (post-cooldown-filter): {result.alerts_sent}")
    print(f"new alert log lines this cycle: {new_alerts}")

    de7f = next((s for s in result.scores if s.opportunity_id.startswith("de7f250c")), None)
    if de7f:
        print(f"\nde7f250c (previously spammed 3x) this cycle: composite={de7f.composite_score} -- was it re-alerted?")
        import json
        lines = ALERT_LOG.open(encoding="utf-8").readlines()
        de7f_alerts = [json.loads(l) for l in lines if json.loads(l)["opportunity_id"].startswith("de7f250c")]
        print(f"total alerts ever logged for de7f250c: {len(de7f_alerts)} (should still be 3, not 4)")
    else:
        print("\nde7f250c not present in this cycle's results (post churned out of top clusters)")


if __name__ == "__main__":
    main()
