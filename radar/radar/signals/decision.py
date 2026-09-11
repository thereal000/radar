"""DECIDE stage: turns a scored opportunity into one of three action tiers a
human can act on at a glance, instead of a bare number. Adds no new
measurement — it only combines fields scoring.py/relevance.py/risk.py
already compute (opportunity_score, money_score, effort_score, risk_level,
relevance_score, their reason lists) into a decision and a short "why".

Thresholds below are a first-pass heuristic, not tuned against a large
labeled dataset — same honest caveat as effort_score in scoring.py. They
should be revisited once more real cycles accumulate.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .scoring import OpportunityScore

DO_NOW = "do_now"
WATCH = "watch"
IGNORE = "ignore"

_RELEVANCE_LABELS = {
    "giveaway": "cadeau/giveaway explicite",
    "reward_or_prize": "récompense annoncée",
    "credits_or_allocation": "crédits/allocation mentionnés",
    "free_access": "accès gratuit",
    "eligibility_or_registration": "inscription ouverte",
    "deadline_or_scarcity": "places limitées ou deadline",
    "airdrop_or_distribution": "airdrop / distribution",
    "grant_or_funding": "grant ou financement",
    "hackathon_or_competition": "hackathon / compétition",
    "early_access_or_beta": "accès anticipé",
    "referral": "programme de parrainage",
}

_RISK_LABELS = {
    "seed_phrase_or_private_key": "demande une seed phrase / clé privée",
    "connect_wallet": "demande de connecter un wallet",
    "wallet_address_request": "demande une adresse wallet",
    "urgency_language": "urgence artificielle",
    "vague_crypto_giveaway": "pattern giveaway crypto vague",
    "referral_farming": "farming de parrainage",
    "claim_now_unverifiable": "\"claim now\" invérifiable",
    "disproportionate_promise": "montant promis disproportionné",
    "shortened_suspicious_link": "lien raccourci suspect",
    "compounding:low_source_independence": "peu de sources indépendantes",
}

# Thresholds on value_score (see _value_score) for each tier.
_DO_NOW_MIN_VALUE = 0.10
_WATCH_MIN_VALUE = 0.04
_MIN_RELEVANCE_FOR_DO_NOW = 0.5


@dataclass
class Decision:
    tier: str  # do_now | watch | ignore
    value_score: float
    why: list[str] = field(default_factory=list)      # positive, human-readable
    concerns: list[str] = field(default_factory=list)  # negative, human-readable


def _value_score(score: OpportunityScore) -> float:
    """Reward-vs-effort estimate for RANKING within a cycle — reuses the
    existing opportunity_score (already relevance/risk-discounted) and
    additionally discounts for apparent effort, and boosts for an explicit
    money mention. Not a new scoring dimension, a different combination of
    ones that already exist."""
    effort_discount = 1.0 - 0.5 * score.effort_score  # high effort roughly halves value at most
    risk_discount = 1.0 - 0.6 * score.risk_score
    money_boost = 0.5 + 0.5 * score.money_score
    return round(score.opportunity_score * money_boost * effort_discount * risk_discount, 4)


def decide(score: OpportunityScore) -> Decision:
    why = [_RELEVANCE_LABELS.get(r, r) for r in score.relevance_reasons if not r.startswith("OFF-TOPIC")]
    concerns = [_RISK_LABELS.get(r, r) for r in score.risk_reasons]
    value = _value_score(score)

    if score.risk_level == "HIGH" or score.relevance_score < 0.4:
        tier = IGNORE
    elif score.risk_level == "LOW" and value >= _DO_NOW_MIN_VALUE and score.relevance_score >= _MIN_RELEVANCE_FOR_DO_NOW:
        tier = DO_NOW
    elif value >= _WATCH_MIN_VALUE:
        tier = WATCH
    else:
        tier = IGNORE

    return Decision(tier=tier, value_score=value, why=why, concerns=concerns)
