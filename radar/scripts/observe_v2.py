"""Mandatory real test after the relevance/independence/risk overhaul: 3
real cycles with the NEW opportunity-intent queries, against the SAME
persistent radar.db (keeps all prior history — cross-run opportunity
matching will recognize genuinely recurring real opportunities).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from radar.signals.alerts import AlertDispatcher  # noqa: E402
from radar.signals.orchestrator import run_cycle  # noqa: E402
from radar.signals.store import DEFAULT_DB_PATH, RadarStore  # noqa: E402

NEW_QUERIES = [
    "free credits", "creator rewards", "referral rewards", "testnet rewards",
    "beta rewards", "hackathon prize", "grant program", "token airdrop",
    "points campaign", "early access rewards", "NFT distribution", "limited giveaway",
]
ALERT_LOG = Path(__file__).resolve().parent.parent / "observe_v2_alerts.jsonl"
N_CYCLES = 3
GAP_SECONDS = 240


def print_result(label: str, result) -> None:
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    print(f"run_id={result.run_id} raw={result.raw_count} signals={result.signal_count} clusters={result.cluster_count} alerts_sent={result.alerts_sent}")
    top = sorted(result.scores, key=lambda s: s.opportunity_score, reverse=True)[:10]
    for s in top:
        print(
            f"  opp={s.opportunity_id[:8]} opp_score={s.opportunity_score:.3f} relevance={s.relevance_score:.2f} "
            f"risk={s.risk_level} indep={s.source_independence:.2f} signals={s.signal_count} "
            f"platforms={sorted(s.platforms)} trend={s.trend}"
        )


def main() -> None:
    store = RadarStore(DEFAULT_DB_PATH)
    dispatcher = AlertDispatcher(log_path=ALERT_LOG, enable_desktop_toast=False)

    results = []
    for i in range(N_CYCLES):
        result = run_cycle(NEW_QUERIES, store, dispatcher, per_query_limit=15, alert_threshold=0.35)
        print_result(f"CYCLE {i + 1}/{N_CYCLES} (new queries)", result)
        results.append(result)
        if i < N_CYCLES - 1:
            print(f"\nWaiting {GAP_SECONDS}s before next cycle...")
            time.sleep(GAP_SECONDS)

    print(f"\n{'=' * 70}\nTOP OPPORTUNITIES ACROSS ALL 3 NEW-QUERY CYCLES\n{'=' * 70}")
    best_per_opp = {}
    for r in results:
        for s in r.scores:
            if s.opportunity_id not in best_per_opp or s.opportunity_score > best_per_opp[s.opportunity_id].opportunity_score:
                best_per_opp[s.opportunity_id] = s
    top20 = sorted(best_per_opp.values(), key=lambda s: s.opportunity_score, reverse=True)[:20]
    for s in top20:
        print(
            f"opp={s.opportunity_id[:8]} opp_score={s.opportunity_score:.3f} relevance={s.relevance_score:.2f} "
            f"risk={s.risk_level}({s.risk_score:.2f}) indep={s.source_independence:.2f} signals={s.signal_count} "
            f"platforms={sorted(s.platforms)}"
        )


if __name__ == "__main__":
    main()
