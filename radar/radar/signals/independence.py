"""Source independence — corroboration ≠ copy.

Root-caused by real observation data: a single spam account (BoroToken)
posting the same bait 4 times, and a 2-account bot network posting a
near-identical templated message, both inflated the radar's
`corroboration_score` exactly like a real event independently reported by
several people would.

Per project instruction, this reuses the fuzzy-matching primitives already
built in Brick 1 (rapidfuzz, already a dependency) instead of adding
anything new — it applies the SAME `token_set_ratio` used for dedup, just
pairwise within an already-formed cluster, plus two cheap signals dedup
doesn't need: how many distinct authors posted, and how spread out in time
they did it. A real limitation, disclosed rather than hidden: text-only
heuristics cannot reliably tell "official studio + publisher cross-post"
apart from "coordinated bot network" — both produce near-identical text
from a handful of distinct accounts. See the observation report.
"""
from __future__ import annotations

from datetime import datetime

from rapidfuzz import fuzz

from .cluster import Cluster


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def compute_source_independence(cluster: Cluster) -> tuple[float, dict]:
    signals = cluster.signals
    n = len(signals)
    if n <= 1:
        return 1.0, {"reason": "single signal, nothing to double-count"}

    authors = [s.author for s in signals]
    author_diversity = len(set(authors)) / n

    pair_ratios = []
    for i in range(n):
        for j in range(i + 1, n):
            a, b = signals[i].normalized_text or "", signals[j].normalized_text or ""
            pair_ratios.append(fuzz.token_set_ratio(a, b))
    avg_fuzzy = sum(pair_ratios) / len(pair_ratios) if pair_ratios else 0.0
    text_uniqueness = 1 - avg_fuzzy / 100

    times = [t for t in (_parse(s.published_at) for s in signals) if t is not None]
    if len(times) >= 2:
        spread_hours = (max(times) - min(times)).total_seconds() / 3600
        timing_spread = min(1.0, spread_hours / 6)  # 6+ hours spread = fully independent-looking
    else:
        timing_spread = 0.5  # unknown, neutral

    score = 0.4 * author_diversity + 0.4 * text_uniqueness + 0.2 * timing_spread
    details = {
        "author_diversity": round(author_diversity, 3),
        "text_uniqueness": round(text_uniqueness, 3),
        "avg_pairwise_fuzzy": round(avg_fuzzy, 1),
        "timing_spread": round(timing_spread, 3),
        "unique_authors": len(set(authors)),
        "signal_count": n,
    }
    return round(max(0.0, min(1.0, score)), 3), details
