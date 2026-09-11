"""Real test of the parallelized 6-source pipeline. Measures wall-clock
time to compare directly against the sequential 2-source benchmark
(307s total, 88.6s twitter + 201.5s reddit sequential = 290s collection).
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
    print(f"Running parallel pipeline across 6 sources, {len(QUERIES)} queries...")
    t0 = time.perf_counter()
    result = run_pipeline(QUERIES, per_query_limit=15)
    elapsed = time.perf_counter() - t0

    print(f"\n{'=' * 70}\nRESULTS\n{'=' * 70}")
    print(f"TOTAL WALL TIME: {elapsed:.2f}s")
    for src, raw in result.raw_by_source.items():
        print(f"  {src:12s}: {len(raw)} raw posts")
    print(f"\ntotal raw: {result.raw_count}")
    print(f"unique signals: {result.unique_signal_count}")
    print(f"clusters: {result.cluster_count}")
    print(f"signals/minute: {result.unique_signal_count / (elapsed/60):.1f}")

    print("\nsample signals per new source:")
    for src in ["github", "hackernews", "youtube", "rss"]:
        matches = [s for s in result.signals if s.source == src]
        print(f"\n--- {src} ({len(matches)} signals) ---")
        for s in matches[:3]:
            print(f"  [{s.author}] {(s.title or s.text or '')[:100]!r}")


if __name__ == "__main__":
    main()
