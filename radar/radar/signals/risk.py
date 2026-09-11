"""Scam/spam risk assessment — a separate signal, not a penalty buried in
the main score, per project instruction. Rule-based (no ML, no external
API/blocklist — considered CryptoScamDB's blacklist repo but couldn't
confirm license or update freshness quickly enough to justify pulling in
an unmaintained-for-all-we-know dependency; a lightweight heuristic is
"quelques minutes de recherche" territory, not worth more).

Any single weak signal (a wallet address ask, urgency language) is NOT
enough to call something a scam — per instruction, a wallet ask alone is
common in legitimate crypto activity. Risk compounds specifically when a
wallet/crypto solicitation pattern co-occurs with LOW source independence
(the same bait pushed by one account repeatedly, or a templated network).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .cluster import Cluster

_PATTERNS: dict[str, tuple[re.Pattern, float]] = {
    # NB: plurals need explicit "es?"/"s?" — a strict \bword\b regex misses
    # them (e.g. "wallet address" doesn't match "wallet addresses"). Found
    # via retroactive re-scoring on real data: the "Airdrop Address
    # Submission Deadline" network case silently scored risk=0 because the
    # real text said "wallet addresses" (plural).
    "seed_phrase_or_private_key": (re.compile(r"\b(seed phrases?|private keys?)\b", re.I), 0.9),
    "connect_wallet": (re.compile(r"\bconnect (your )?wallets?\b", re.I), 0.2),
    "wallet_address_request": (re.compile(r"\b(wallet address(es)?|submit(ting)? (your )?address(es)?|accepting (your )?(wallet )?address(es)?|drop your .*address(es)?|send.*your address(es)?)\b", re.I), 0.25),
    "urgency_language": (re.compile(r"\b(hurry|act now|limited time|last chance|ends? (today|soon)|before it.?s too late|only \d+\s?(left|spots|slots)?|first \d+)", re.I), 0.15),
    "vague_crypto_giveaway": (re.compile(r"\b(reply with|tag a friend|like\s*&?\s*(rt|retweet))\b.*\$[A-Z]{2,6}|\$[A-Z]{2,6}.*\b(giveaways?|airdrops?)\b", re.I), 0.2),
    "referral_farming": (re.compile(r"\b(refer \d+ friends?|referral links?|invite \d+ friends?)\b", re.I), 0.1),
    "claim_now_unverifiable": (re.compile(r"\bclaim now\b", re.I), 0.1),
    "disproportionate_promise": (re.compile(r"\$\d{2,3},\d{3}\b"), 0.2),  # e.g. $100,000, $187,500 in a casual post
    "shortened_suspicious_link": (re.compile(r"\b(bit\.ly|tinyurl\.com|cutt\.ly|is\.gd)/\S+", re.I), 0.1),
}

_COMPOUND_TRIGGERS = {"connect_wallet", "wallet_address_request", "vague_crypto_giveaway"}
_COMPOUND_BONUS = 0.25
_LOW_INDEPENDENCE_THRESHOLD = 0.3


@dataclass
class RiskAssessment:
    risk_score: float
    risk_level: str  # LOW | MEDIUM | HIGH
    reasons: list[str] = field(default_factory=list)


def assess_risk(cluster: Cluster, source_independence: float) -> RiskAssessment:
    text = " ".join(s.text or s.title or "" for s in cluster.signals)

    hits: list[str] = []
    total = 0.0
    for name, (pattern, weight) in _PATTERNS.items():
        if pattern.search(text):
            hits.append(name)
            total += weight

    compounding = any(h in _COMPOUND_TRIGGERS for h in hits) and source_independence < _LOW_INDEPENDENCE_THRESHOLD
    if compounding:
        total += _COMPOUND_BONUS
        hits.append("compounding:low_source_independence")

    score = max(0.0, min(1.0, total))
    if score >= 0.6:
        level = "HIGH"
    elif score >= 0.3:
        level = "MEDIUM"
    else:
        level = "LOW"

    return RiskAssessment(risk_score=round(score, 3), risk_level=level, reasons=hits)
