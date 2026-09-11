"""Small real benchmark: OLD generic single-word queries vs NEW
opportunity-intent queries. One real cycle each, against separate
throwaway DBs (kept out of the main radar.db so this comparison doesn't
pollute real opportunity history). Compares volume, clusters, relevance,
risk, duplicates, average scores — not just "fewer/more results".
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from radar.signals.orchestrator import run_cycle  # noqa: E402
from radar.signals.store import RadarStore  # noqa: E402

OLD_QUERIES = [
    "free", "giveaway", "rewards", "airdrop", "free credits",
    "grant", "hackathon", "early access", "points", "event reward",
]

NEW_QUERIES = [
    "free credits", "creator rewards", "referral rewards", "testnet rewards",
    "beta rewards", "hackathon prize", "grant program", "token airdrop",
    "points campaign", "early access rewards", "NFT distribution", "limited giveaway",
]


def summarize(label: str, queries: list[str], db_path: Path):
    if db_path.exists():
        db_path.unlink()
    store = RadarStore(db_path)
    result = run_cycle(queries, store, dispatcher=None, per_query_limit=15)

    scores = result.scores
    n = len(scores) or 1
    avg_relevance = sum(s.relevance_score for s in scores) / n
    avg_opportunity = sum(s.opportunity_score for s in scores) / n
    avg_composite = sum(s.composite_score for s in scores) / n
    n_high_relevance = sum(1 for s in scores if s.relevance_score >= 0.3)
    n_noise_tier = sum(1 for s in scores if s.relevance_score <= 0.15)
    n_high_risk = sum(1 for s in scores if s.risk_level == "HIGH")
    n_medium_risk = sum(1 for s in scores if s.risk_level == "MEDIUM")
    n_duplicates_found = sum(1 for s in scores if s.signal_count > 1)

    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    print(f"queries: {queries}")
    print(f"raw posts collected : {result.raw_count}")
    print(f"unique signals       : {result.signal_count}")
    print(f"clusters (opportunities): {result.cluster_count}")
    print(f"clusters w/ >1 signal (real duplicates found): {n_duplicates_found}")
    print(f"avg relevance_score  : {avg_relevance:.3f}")
    print(f"avg opportunity_score: {avg_opportunity:.3f}")
    print(f"avg composite_score  : {avg_composite:.3f}")
    print(f"high-relevance clusters (>=0.3): {n_high_relevance} ({100*n_high_relevance/n:.0f}%)")
    print(f"noise-tier clusters (<=0.15)   : {n_noise_tier} ({100*n_noise_tier/n:.0f}%)")
    print(f"HIGH risk clusters   : {n_high_risk}")
    print(f"MEDIUM risk clusters : {n_medium_risk}")

    top5 = sorted(scores, key=lambda s: s.opportunity_score, reverse=True)[:5]
    print("\ntop 5 by opportunity_score:")
    for s in top5:
        print(f"  opp_score={s.opportunity_score:.3f} relevance={s.relevance_score:.3f} risk={s.risk_level} platforms={sorted(s.platforms)} signals={s.signal_count}")

    return {
        "raw": result.raw_count, "clusters": result.cluster_count,
        "avg_relevance": avg_relevance, "avg_opportunity": avg_opportunity,
        "high_relevance_pct": 100 * n_high_relevance / n, "noise_pct": 100 * n_noise_tier / n,
    }


def main():
    base = Path(__file__).resolve().parent.parent
    old_stats = summarize("OLD QUERIES (generic single words)", OLD_QUERIES, base / "bench_old.db")
    new_stats = summarize("NEW QUERIES (opportunity-intent phrases)", NEW_QUERIES, base / "bench_new.db")

    print(f"\n{'=' * 70}\nCOMPARISON\n{'=' * 70}")
    for key in ["raw", "clusters", "avg_relevance", "avg_opportunity", "high_relevance_pct", "noise_pct"]:
        print(f"{key:22s} old={old_stats[key]:.2f}  new={new_stats[key]:.2f}  delta={new_stats[key]-old_stats[key]:+.2f}")


if __name__ == "__main__":
    main()
