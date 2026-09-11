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

import re
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

# Real, "not actually a giveaway" language: entering a raffle/sweepstakes
# isn't claiming a reward, it's buying a lottery ticket — cool find, but not
# the guaranteed-if-you-do-X opportunity the do_now tier promises. Found
# live: a giveaway that was legitimate but effectively unwinnable (one
# winner picked from a huge pool) was surfacing as do_now.
_SELECTIVE_RE = re.compile(
    r"\b(chance to win|sweepstakes|raffle|lucky winner|winners? will be (?:selected|chosen|announced|picked)|"
    r"one (?:lucky )?winner|enter to win|drawing will be held|randomly selected)\b",
    re.I,
)

# Thresholds on value_score (see _value_score) for each tier.
_DO_NOW_MIN_VALUE = 0.10
_WATCH_MIN_VALUE = 0.04
_MIN_RELEVANCE_FOR_DO_NOW = 0.5
_MIN_POSITIVE_CONCEPTS_FOR_DO_NOW = 2  # one accidental keyword match must never be enough on its own


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
    positive_reasons = [r for r in score.relevance_reasons if not r.startswith("OFF-TOPIC")]
    off_topic_hits = [r for r in score.relevance_reasons if r.startswith("OFF-TOPIC:")]
    why = [_RELEVANCE_LABELS.get(r, r) for r in positive_reasons]
    concerns = [_RISK_LABELS.get(r, r) for r in score.risk_reasons]
    value = _value_score(score)

    selective = bool(_SELECTIVE_RE.search(score.representative_text or ""))
    if selective:
        concerns.append("tirage au sort / sélection — pas garanti même en participant")
        value = round(value * 0.4, 4)

    if off_topic_hits:
        # relevance.py already flagged this as noise (politics/news/etc.) —
        # a coincidental keyword match or a big number in the text must
        # never override that. This signal was being computed and silently
        # thrown away before; a viral US-politics tweet with a huge dollar
        # figure was reaching do_now purely off engagement + one accidental
        # keyword hit.
        concerns.append("probablement hors-sujet (actualité/politique) malgré des mots-clés qui matchent")
        tier = IGNORE
    elif score.risk_level == "HIGH" or score.relevance_score < 0.4:
        tier = IGNORE
    elif (
        score.risk_level == "LOW"
        and value >= _DO_NOW_MIN_VALUE
        and score.relevance_score >= _MIN_RELEVANCE_FOR_DO_NOW
        and len(positive_reasons) >= _MIN_POSITIVE_CONCEPTS_FOR_DO_NOW
        and not selective
    ):
        tier = DO_NOW
    elif value >= _WATCH_MIN_VALUE:
        tier = WATCH
    else:
        tier = IGNORE

    return Decision(tier=tier, value_score=value, why=why, concerns=concerns)
