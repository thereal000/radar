"""AUDIT ONLY — measures the current pipeline's real timing/resource
profile, stage by stage. Does not modify radar/signals/* at all; it only
imports and times the existing functions, and calls find_duplicate_pairs()
once extra (on top of what build_clusters does internally) purely to get a
dedup-vs-clustering split for this report — that redundant call exists
only here, not in production code.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psutil  # noqa: E402

from radar.signals.cluster import build_clusters  # noqa: E402
from radar.signals.collectors import collect_reddit, collect_twitter  # noqa: E402
from radar.signals.dedup import find_duplicate_pairs  # noqa: E402
from radar.signals.normalize import normalize_batch  # noqa: E402
from radar.signals.pipeline import _dedupe_raw_by_id  # noqa: E402
from radar.signals.scoring import score_opportunity  # noqa: E402
from radar.signals.store import DEFAULT_DB_PATH, RadarStore  # noqa: E402

QUERIES = [
    "free credits", "creator rewards", "referral rewards", "testnet rewards",
    "beta rewards", "hackathon prize", "grant program", "token airdrop",
    "points campaign", "early access rewards", "NFT distribution", "limited giveaway",
]
PER_QUERY_LIMIT = 15
DB_PATH = DEFAULT_DB_PATH  # real accumulated DB — reflects true current-state cost

proc = psutil.Process()


def stage(label, fn, *args, **kwargs):
    cpu0 = proc.cpu_times()
    rss0 = proc.memory_info().rss
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    t1 = time.perf_counter()
    cpu1 = proc.cpu_times()
    rss1 = proc.memory_info().rss
    wall = t1 - t0
    cpu = (cpu1.user - cpu0.user) + (cpu1.system - cpu0.system)
    print(f"{label:38s} wall={wall:7.2f}s  cpu={cpu:7.2f}s  rss_delta={(rss1-rss0)/1e6:+7.1f}MB")
    return result, wall


def main():
    print(f"queries: {len(QUERIES)}  per_query_limit: {PER_QUERY_LIMIT}")
    print(f"DB: {DB_PATH} (real accumulated DB, not reset)")
    print(f"process baseline RSS: {proc.memory_info().rss/1e6:.1f}MB\n")

    timings = {}

    # --- collection, per source, sequential (as production currently does) ---
    raw_twitter = []
    t0 = time.perf_counter()
    for q in QUERIES:
        r, w = stage(f"  twitter collect [{q!r}]", collect_twitter, q, limit=PER_QUERY_LIMIT)
        raw_twitter += r
    timings["twitter_total"] = time.perf_counter() - t0

    raw_reddit = []
    t0 = time.perf_counter()
    for q in QUERIES:
        r, w = stage(f"  reddit collect [{q!r}]", collect_reddit, q, limit=PER_QUERY_LIMIT)
        raw_reddit += r
    timings["reddit_total"] = time.perf_counter() - t0

    print(f"\nraw twitter posts: {len(raw_twitter)}  raw reddit posts: {len(raw_reddit)}")

    raw_twitter, t = stage("dedupe_raw_by_id (twitter)", _dedupe_raw_by_id, raw_twitter)
    raw_reddit, t = stage("dedupe_raw_by_id (reddit)", _dedupe_raw_by_id, raw_reddit)

    signals, timings["normalize"] = stage("normalize_batch", normalize_batch, raw_twitter, raw_reddit)
    print(f"unique signals: {len(signals)}")

    _, timings["dedup_only"] = stage("find_duplicate_pairs (dedup only)", find_duplicate_pairs, signals)
    clusters, timings["dedup_plus_cluster"] = stage("build_clusters (dedup+cluster, as used in prod)", build_clusters, signals)
    print(f"clusters: {len(clusters)}")

    store = RadarStore(DB_PATH)
    mapping_and_id, timings["persist"] = stage("persist_run (DB writes)", store.persist_run, clusters)
    cluster_to_opportunity, run_id = mapping_and_id

    def score_all():
        scores = []
        for c in clusters:
            opp_id = cluster_to_opportunity[c.cluster_id]
            snaps = store.get_snapshots(opp_id)
            scores.append(score_opportunity(c, opp_id, snaps))
        return scores

    scores, timings["scoring_incl_snapshot_reads"] = stage("scoring loop (incl. per-cluster snapshot reads)", score_all)

    total_time = timings["twitter_total"] + timings["reddit_total"] + timings["normalize"] + timings["dedup_plus_cluster"] + timings["persist"] + timings["scoring_incl_snapshot_reads"]

    print(f"\n{'=' * 70}\nSUMMARY\n{'=' * 70}")
    print(f"twitter collection   : {timings['twitter_total']:7.2f}s")
    print(f"reddit collection    : {timings['reddit_total']:7.2f}s")
    print(f"normalize            : {timings['normalize']:7.2f}s")
    print(f"dedup only (measured separately): {timings['dedup_only']:7.2f}s")
    print(f"dedup+cluster (as used in prod) : {timings['dedup_plus_cluster']:7.2f}s")
    print(f"persist (DB writes)  : {timings['persist']:7.2f}s")
    print(f"scoring (incl DB reads): {timings['scoring_incl_snapshot_reads']:7.2f}s")
    print(f"TOTAL (sum of above) : {total_time:7.2f}s")
    print(f"\nraw posts: {len(raw_twitter)+len(raw_reddit)}  signals: {len(signals)}  clusters: {len(clusters)}")
    print(f"signals/minute: {len(signals) / (total_time/60):.1f}")
    print(f"peak RSS: {proc.memory_info().rss/1e6:.1f}MB")
    print(f"num CPUs available: {psutil.cpu_count()}  logical")


if __name__ == "__main__":
    main()
