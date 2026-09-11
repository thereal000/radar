"""Diagnostic only: for each source, one query at the current limit vs a
higher candidate limit, to see whether raising the limit actually returns
more DISTINCT real results (vs plateauing / erroring / just costing more
time for nothing). Not the full before/after benchmark — that reuses the
already-measured 12-query baseline.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from radar.signals.collectors import (  # noqa: E402
    collect_github,
    collect_hackernews,
    collect_reddit,
    collect_twitter,
    collect_youtube,
)

PROBES = [
    ("twitter", collect_twitter, "free credits", [15, 40]),
    ("reddit", collect_reddit, "free credits", [15, 40]),
    ("github", collect_github, "free credits", [30, 100]),
    ("hackernews", collect_hackernews, "free credits", [15, 50]),
    ("youtube", collect_youtube, "free credits", [10, 30]),
]


def main():
    for name, fn, query, limits in PROBES:
        print(f"\n=== {name} ===")
        for limit in limits:
            t0 = time.perf_counter()
            try:
                results = fn(query, limit=limit)
                elapsed = time.perf_counter() - t0
                ids = {r.get("id") or r.get("objectID") or r.get("fullName") for r in results}
                print(f"  limit={limit:4d}  got={len(results):4d}  distinct_ids={len(ids):4d}  time={elapsed:6.2f}s")
            except Exception as e:
                elapsed = time.perf_counter() - t0
                print(f"  limit={limit:4d}  ERROR after {elapsed:.2f}s: {e}")


if __name__ == "__main__":
    main()
