"""Real, live end-to-end test of the signal ingestion pipeline against the
already-working OpenCLI backends (X + Reddit). No mocks, no fixtures.

Run: .venv\\Scripts\\python.exe scripts\\live_test.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from radar.signals.pipeline import run_pipeline  # noqa: E402

QUERIES = [
    "free",
    "giveaway",
    "rewards",
    "airdrop",
    "free credits",
    "grant",
    "hackathon",
    "early access",
    "points",
    "event reward",
]


def main() -> None:
    print(f"Collecting for {len(QUERIES)} queries: {QUERIES}\n")
    result = run_pipeline(QUERIES, per_query_limit=15)

    print("=" * 70)
    print("STAGE 1 — RAW POSTS")
    print("=" * 70)
    print(f"twitter raw: {len(result.raw_twitter)}")
    print(f"reddit  raw: {len(result.raw_reddit)}")
    print(f"TOTAL   raw: {result.raw_count}")

    print("\n" + "=" * 70)
    print("STAGE 2 — NORMALIZED SIGNALS")
    print("=" * 70)
    print(f"total signals: {len(result.signals)}")
    for s in result.signals[:3]:
        print(f"  - [{s.source}] {s.source_id} | {(s.title or s.text)[:70]!r} | url={s.canonical_url}")

    print("\n" + "=" * 70)
    print("STAGE 3 — CLUSTERS (dedup + cluster combined)")
    print("=" * 70)
    print(f"unique signals in : {len(result.signals)}")
    print(f"clusters out      : {len(result.clusters)}")
    dup_clusters = [c for c in result.clusters if len(c.signals) > 1]
    print(f"clusters with >1 member (actual duplicates found): {len(dup_clusters)}")

    print("\n--- Examples of clusters with duplicates ---")
    shown = 0
    for c in sorted(dup_clusters, key=lambda c: -len(c.signals)):
        if shown >= 5:
            break
        shown += 1
        print(f"\n{c.cluster_id} — {len(c.signals)} signals, platforms={c.platforms}")
        for s in c.signals:
            snippet = (s.title or s.text or "")[:90].replace("\n", " ")
            print(f"    [{s.source}:{s.source_id}] {snippet!r}")
        confirming = [ev for ev in c.evidence if ev.is_duplicate]
        for ev in confirming[:3]:
            print(
                f"    evidence: {ev.a_id} <-> {ev.b_id} "
                f"same_url={ev.same_url} same_hash={ev.same_hash} "
                f"jaccard={ev.minhash_jaccard:.2f} fuzzy={ev.fuzzy_ratio:.0f} "
                f"shared_entities={sorted(ev.shared_entities)[:5]}"
            )

    if not dup_clusters:
        print("(none found in this run — live data may not have contained duplicates this time)")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"posts collected (raw)   : {result.raw_count}")
    print(f"unique signals          : {result.unique_signal_count}")
    print(f"clusters                : {result.cluster_count}")
    print(f"clusters w/ duplicates  : {len(dup_clusters)}")
    posts_absorbed = sum(len(c.signals) for c in dup_clusters) - len(dup_clusters)
    print(f"posts collapsed via dedup: {posts_absorbed}")


if __name__ == "__main__":
    main()
