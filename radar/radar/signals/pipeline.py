from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .cluster import Cluster, build_clusters
from .collectors import (
    DEFAULT_RSS_FEEDS,
    collect_github,
    collect_hackernews,
    collect_reddit,
    collect_rss,
    collect_twitter,
    collect_youtube,
)
from .normalize import normalize_by_source
from .schema import Signal


@dataclass
class PipelineResult:
    raw_by_source: dict[str, list[dict]]
    signals: list[Signal]
    clusters: list[Cluster]

    @property
    def raw_count(self) -> int:
        return sum(len(v) for v in self.raw_by_source.values())

    @property
    def unique_signal_count(self) -> int:
        return len(self.signals)

    @property
    def cluster_count(self) -> int:
        return len(self.clusters)

    # backwards compatibility with older scripts/tests
    @property
    def raw_twitter(self) -> list[dict]:
        return self.raw_by_source.get("twitter", [])

    @property
    def raw_reddit(self) -> list[dict]:
        return self.raw_by_source.get("reddit", [])


def _raw_key(p: dict) -> str:
    """Stable natural key for a raw item, so multi-query dedup never
    collapses distinct items onto one key. Different sources name this
    differently (X/Reddit: "id", GitHub: "fullName", HN: "objectID", RSS
    often only a "link"/"guid"), and some feeds have no id at all.

    Real bug found by probing: the previous version keyed solely on
    `str(p.get("id"))`, so three distinct id-less RSS entries all became
    the literal key "None" and collapsed into a single signal.
    """
    for key in ("id", "fullName", "objectID", "guid", "link", "url"):
        value = p.get(key)
        if value:
            return str(value)
    # No usable identifier at all: fall back to a content fingerprint so
    # genuinely different items stay distinct instead of merging on "None".
    return hashlib.sha1(
        json.dumps(p, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _dedupe_raw_by_id(posts: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for p in posts:
        pid = _raw_key(p)
        if pid in by_id:
            existing_queries = by_id[pid].setdefault("_matched_queries", [by_id[pid].get("_collector_query")])
            q = p.get("_collector_query")
            if q not in existing_queries:
                existing_queries.append(q)
        else:
            p["_matched_queries"] = [p.get("_collector_query")]
            by_id[pid] = p
    return list(by_id.values())


def _collect_all_queries(collector_fn, queries: list[str], limit: int | None, source_name: str) -> list[dict]:
    """Runs one collector across all queries, sequentially WITHIN the
    source (a single OpenCLI/gh/yt-dlp session isn't known to handle
    concurrent calls safely) — but this whole function runs in its own
    thread, in parallel with the other sources' equivalent loops."""
    raw: list[dict] = []
    for q in queries:
        try:
            raw += collector_fn(q, limit=limit)
        except Exception as e:  # noqa: BLE001 - keep one bad query/source from sinking the cycle
            print(f"[warn] {source_name} collect failed for {q!r}: {e}")
    return raw


def _collect_rss_job(limit: int | None) -> list[dict]:
    try:
        return collect_rss(DEFAULT_RSS_FEEDS, limit=limit)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] rss collect failed: {e}")
        return []


# One entry per independently-collectible source. Query-based sources take
# (collector_fn, queries, limit); rss ignores queries (feed-based, not search).
_QUERY_BASED_SOURCES = {
    "twitter": collect_twitter,
    "reddit": collect_reddit,
    "github": collect_github,
    "hackernews": collect_hackernews,
    "youtube": collect_youtube,
}

# Measured for real (scripts/scale_probe.py) before tuning these: twitter
# and reddit return the exact same 15 results, in the exact same time,
# whether asked for 15 or 40 — OpenCLI's own --limit doesn't fetch beyond
# one page/scroll for these two, so raising it further wastes nothing but
# also gains nothing. github/hackernews/youtube scale close to linearly in
# time for real additional distinct results, so those are raised; twitter
# and reddit are left at their empirically-confirmed ceiling.
DEFAULT_SOURCE_LIMITS = {
    "twitter": 15,      # hard ceiling in OpenCLI — confirmed empirically, not a guess
    "reddit": 15,       # same
    "github": 100,      # gh CLI paginates natively; 100 cost 4.76s vs 30's 1.59s for real new results
    "hackernews": 50,   # Algolia hitsPerPage scales almost for free (0.97s vs 0.86s for 15)
    "youtube": 30,      # yt-dlp flat search scales cheaply (1.51s vs 1.18s for 10)
}


def run_pipeline(
    queries: list[str],
    per_query_limit: int | None = None,
    sources: list[str] | None = None,
    source_limits: dict[str, int] | None = None,
) -> PipelineResult:
    """COLLECT (parallel, one thread per source) -> NORMALIZE -> CLEAN ->
    CANONICALIZE -> DEDUP -> CLUSTER.

    `sources` defaults to all 6 available; pass a subset (e.g. ["twitter",
    "reddit"]) to keep the old behavior exactly, or add "rss"/"github"/
    "hackernews"/"youtube" as needed. Independent sources run concurrently
    via ThreadPoolExecutor — they're separate services (browser subprocess,
    gh CLI, HTTP APIs), so there's no shared rate limit to worry about.

    `per_query_limit`, if given, overrides ALL sources uniformly (kept for
    backwards compatibility with existing scripts/tests). Otherwise each
    source uses its own empirically-tuned default from
    DEFAULT_SOURCE_LIMITS, optionally overridden per-source via
    `source_limits`.
    """
    active_sources = sources or list(_QUERY_BASED_SOURCES) + ["rss"]
    limits = dict(DEFAULT_SOURCE_LIMITS)
    if source_limits:
        limits.update(source_limits)
    if per_query_limit is not None:
        limits = {src: per_query_limit for src in limits}

    raw_by_source: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=max(len(active_sources), 1)) as executor:
        futures = {}
        for src in active_sources:
            if src == "rss":
                futures[src] = executor.submit(_collect_rss_job, limits.get("rss"))
            elif src in _QUERY_BASED_SOURCES:
                futures[src] = executor.submit(
                    _collect_all_queries, _QUERY_BASED_SOURCES[src], queries, limits.get(src), src
                )
        for src, future in futures.items():
            try:
                raw_by_source[src] = future.result()
            except Exception as e:  # noqa: BLE001 - a dead source must not kill the whole cycle
                print(f"[warn] source {src} produced no results this cycle: {e}")
                raw_by_source[src] = []

    # Same post surfacing under multiple queries within one source is a
    # literal duplicate (same id) — collapse before normalization.
    for src in raw_by_source:
        raw_by_source[src] = _dedupe_raw_by_id(raw_by_source[src])

    # NORMALIZE + CLEAN + CANONICALIZE happen inside normalize_by_source
    # (courlan canonicalization, text cleaning, content hashing all applied there)
    signals = normalize_by_source(raw_by_source)

    # DEDUP + CLUSTER (unchanged — cross-source near-dup/URL matching
    # already worked before this refactor and still does; it operates on
    # normalized Signal objects, not on which source they came from)
    clusters = build_clusters(signals)

    return PipelineResult(
        raw_by_source=raw_by_source,
        signals=signals,
        clusters=clusters,
    )
