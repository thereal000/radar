"""AFTER benchmark: same 12 queries as the baseline (real_v3_output2.txt =
BEFORE: 102.63s wall, 852 raw=852 unique, twitter=179 reddit=180 github=126
hackernews=174 youtube=178 rss=15), now with per-source tuned limits
(github 100, hackernews 50, youtube 30; twitter/reddit left at their
empirically-confirmed ceiling of 15).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from radar.signals.pipeline import run_pipeline  # noqa: E402

QUERIES = [
    "free credits", "creator rewards", "referral rewards", "testnet rewards",
    "beta rewards", "hackathon prize", "grant program", "token airdrop",
    "points campaign", "early access rewards", "NFT distribution", "limited giveaway",
]


def main():
    print(f"Running AFTER pipeline (tuned per-source limits), {len(QUERIES)} queries...")
    t0 = time.perf_counter()
    result = run_pipeline(QUERIES)  # uses new DEFAULT_SOURCE_LIMITS
    elapsed = time.perf_counter() - t0

    print(f"\n{'=' * 70}\nAFTER RESULTS\n{'=' * 70}")
    print(f"TOTAL WALL TIME: {elapsed:.2f}s")
    total_raw = 0
    for src, raw in result.raw_by_source.items():
        unique_ids = len({p.get("id") for p in raw})
        print(f"  {src:12s}: raw={len(raw):4d}  unique_ids={unique_ids:4d}")
        total_raw += len(raw)
    print(f"\ntotal raw: {total_raw}")
    print(f"unique signals (post cross-query+cross-source dedup input): {result.unique_signal_count}")
    print(f"clusters: {result.cluster_count}")
    print(f"signals/minute: {result.unique_signal_count / (elapsed/60):.1f}")


if __name__ == "__main__":
    main()
