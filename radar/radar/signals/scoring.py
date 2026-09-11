"""Opportunity scoring + "Before-TikTok" early detection.

Fully radar-specific: no OSS project scores "is this the same kind of
opportunity our radar cares about, and is it still early" for our domain.
Built entirely on top of the reused primitives from earlier bricks
(cluster size/platforms from Brick 1, velocity/trend from Brick 3/4,
relevance/independence/risk from the observation-phase fixes).

v1 heuristic — deliberately simple and documented so it's easy to retune
once real historical data accumulates over the following days/weeks.

The original composite_score/before_tiktok_score fields and formulas are
kept exactly as they were (nothing here breaks them) — this adds
explanatory dimensions on top, per instruction, plus one real formula
change explicitly requested: before_tiktok must now be gated by relevance
(EARLYNESS x RELEVANCE, not earliness alone — see real false-positive
found in observation: off-topic political content scored the single
highest before_tiktok in the whole session).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .cluster import Cluster
from .independence import compute_source_independence
from .relevance import compute_relevance
from .risk import assess_risk
from .velocity import classify_trend, compute_velocity


def _hours_since(iso_ts: str | None) -> float:
    if not iso_ts:
        return 999.0
    try:
        ts = datetime.fromisoformat(iso_ts)
    except ValueError:
        return 999.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds() / 3600)


def _total_engagement(cluster: Cluster) -> int:
    return sum(
        (s.engagement.get("likes") or 0)
        + (s.engagement.get("comments") or 0)
        + (s.engagement.get("score") or 0)
        for s in cluster.signals
    )


def _squash(value: float, saturate_at: float) -> float:
    """0..1, log-scaled, saturating at `saturate_at`."""
    if value <= 0:
        return 0.0
    return min(1.0, math.log1p(value) / math.log1p(saturate_at))


_HIGH_EFFORT_RE = re.compile(
    r"\b(steps?|complete|tasks?|verify|verification|kyc|wait \d+ days?|apply|review|multiple)\b", re.I
)
_LOW_EFFORT_RE = re.compile(
    r"\b(just|simply|one click|sign up|click here|visit)\b", re.I
)
_MONEY_MENTION_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*\s?(?:usd|usdc|usdt|eth|sol|btc|pts?|points|credits)\b", re.I
)


def _compute_effort(text: str) -> float:
    """Rough heuristic, low confidence by design — a 0..1 friction estimate,
    not a validated metric. 0 = trivial to claim, 1 = high effort."""
    if not text:
        return 0.3
    high = len(_HIGH_EFFORT_RE.findall(text))
    low = len(_LOW_EFFORT_RE.findall(text))
    return max(0.0, min(1.0, 0.3 + 0.15 * min(high, 4) - 0.15 * min(low, 3)))


def _compute_money_score(text: str) -> float:
    if not text:
        return 0.0
    hits = len(_MONEY_MENTION_RE.findall(text))
    return _squash(hits, saturate_at=5)


@dataclass
class OpportunityScore:
    opportunity_id: str
    cluster_id: str
    signal_count: int
    platforms: set[str]
    total_engagement: int
    velocity: float | None
    trend: str
    engagement_score: float
    velocity_score: float
    diversity_score: float
    corroboration_score: float
    recency_score: float
    composite_score: float
    before_tiktok_score: float
    saturating: bool

    # added for explainability (see docstring)
    relevance_score: float = 0.0
    relevance_reasons: list[str] = field(default_factory=list)
    early_score: float = 0.0
    money_score: float = 0.0
    effort_score: float = 0.0
    source_independence: float = 1.0
    independence_details: dict = field(default_factory=dict)
    risk_score: float = 0.0
    risk_level: str = "LOW"
    risk_reasons: list[str] = field(default_factory=list)
    confidence_score: float = 0.0
    opportunity_score: float = 0.0

    # display-only, not used in any scoring math — lets callers (e.g. the
    # Telegram bot) show what the opportunity actually is without a second
    # DB lookup
    representative_text: str = ""
    representative_url: str = ""

    # set by the orchestrator after persist_run, since score_opportunity()
    # itself has no notion of "new vs already stored" — lets callers tell a
    # genuinely new find apart from the same still-live opportunity showing
    # up again on a later cycle
    is_new: bool = False


def score_opportunity(cluster: Cluster, opportunity_id: str, snapshots: list[dict]) -> OpportunityScore:
    signal_count = len(cluster.signals)
    platforms = cluster.platforms
    total_engagement = _total_engagement(cluster)
    velocity = compute_velocity(snapshots)
    trend = classify_trend(snapshots)

    most_recent_published = max(
        (s.published_at for s in cluster.signals if s.published_at), default=None
    )
    recency_hours = _hours_since(most_recent_published)

    engagement_score = _squash(total_engagement, saturate_at=10_000)
    velocity_score = min(1.0, max(0.0, velocity or 0.0) / 20)
    diversity_score = len(platforms) / 2  # 2 platforms tracked today (X, Reddit)
    corroboration_score = _squash(signal_count, saturate_at=50)
    recency_score = max(0.0, 1 - recency_hours / 72)  # decays over 3 days

    composite_score = (
        0.20 * engagement_score
        + 0.25 * velocity_score
        + 0.15 * diversity_score
        + 0.20 * corroboration_score
        + 0.20 * recency_score
    )

    combined_text = " ".join(s.text or s.title or "" for s in cluster.signals)
    relevance_score, relevance_reasons = compute_relevance(combined_text)
    source_independence, independence_details = compute_source_independence(cluster)
    risk = assess_risk(cluster, source_independence)
    effort_score = _compute_effort(combined_text)
    money_score = _compute_money_score(combined_text)

    # Before-TikTok = EARLYNESS x RELEVANCE, not earliness alone (real bug:
    # off-topic political content had the highest before_tiktok in the
    # whole observation session, purely because it was recent+small).
    early_score = 1 - corroboration_score
    trend_boost = 1.0 if trend == "accelerating" else (0.5 if trend == "insufficient_data" else 0.15)
    earliness = velocity_score * trend_boost * early_score
    before_tiktok_score = earliness * relevance_score

    confidence_score = 0.4 * source_independence + 0.3 * diversity_score + 0.3 * engagement_score

    # Headline recommended ranking score: composite, discounted for
    # off-topic content (floor so an imperfect keyword lexicon can't fully
    # zero out a real opportunity worded unusually) and for scam risk.
    relevance_multiplier = 0.15 + 0.85 * relevance_score
    risk_discount = 1 - 0.6 * risk.risk_score
    opportunity_score = composite_score * relevance_multiplier * risk_discount

    return OpportunityScore(
        opportunity_id=opportunity_id,
        cluster_id=cluster.cluster_id,
        signal_count=signal_count,
        platforms=platforms,
        total_engagement=total_engagement,
        velocity=velocity,
        trend=trend,
        engagement_score=round(engagement_score, 3),
        velocity_score=round(velocity_score, 3),
        diversity_score=round(diversity_score, 3),
        corroboration_score=round(corroboration_score, 3),
        recency_score=round(recency_score, 3),
        composite_score=round(composite_score, 3),
        before_tiktok_score=round(before_tiktok_score, 3),
        saturating=(trend == "saturating"),
        relevance_score=round(relevance_score, 3),
        relevance_reasons=relevance_reasons,
        early_score=round(early_score, 3),
        money_score=round(money_score, 3),
        effort_score=round(effort_score, 3),
        source_independence=source_independence,
        independence_details=independence_details,
        risk_score=risk.risk_score,
        risk_level=risk.risk_level,
        risk_reasons=risk.reasons,
        confidence_score=round(confidence_score, 3),
        opportunity_score=round(opportunity_score, 3),
        representative_text=(cluster.representative.text or cluster.representative.title or "")[:300],
        representative_url=cluster.representative.canonical_url or cluster.representative.url or "",
    )
