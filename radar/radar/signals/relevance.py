"""Domain relevance scoring — answers "why is this here?"

Root-caused by real observation data: search queries like "points", "free",
"airdrop" matched heavily off-topic content (political news, historical
trivia) that the radar then scored as if it were a real opportunity,
because nothing ever checked whether the TEXT actually talks about an
opportunity, only whether a search query happened to match a word.

Deliberately not ML (explicit project constraint) and not a new OSS
dependency — a small, explainable keyword-concept lexicon, in the same
style as the entity extraction already in dedup.py. Concept GROUPS (not
raw keyword counts) are used so a single generic word like "free" can't
carry a whole post; multiple independent facets of opportunity-language
have to show up.
"""
from __future__ import annotations

import re

_POSITIVE_CONCEPTS: dict[str, re.Pattern] = {
    # NB: every noun here needs "s?" — a strict \bword\b regex silently
    # misses plurals ("Rewards" didn't match \breward\b), which is how the
    # real "X Original Content Rewards" case scored as low-relevance as
    # pure noise on the first pass. Found via retroactive re-scoring on
    # real data, not synthetic tests.
    "giveaway": re.compile(r"\bgiveaways?\b", re.I),
    "reward_or_prize": re.compile(r"\b(rewards?|prizes?|bount(?:y|ies)|incentives?|bonus(?:es)?)\b", re.I),
    "credits_or_allocation": re.compile(r"\b(credits?|allocations?|token distribution|airdrop allocation)\b", re.I),
    "free_access": re.compile(r"\bfree (credits?|api|gpu|cloud|trials?|subscriptions?|access)\b", re.I),
    "eligibility_or_registration": re.compile(r"\b(eligible|eligibility|registrations?|register now|sign ?up|apply now|whitelist(?:ed)?|allowlist(?:ed)?|waitlist(?:ed)?)\b", re.I),
    "deadline_or_scarcity": re.compile(r"\b(deadlines?|limited spots|first \d+|first come|only \d+ ?(left|spots|slots)?)\b", re.I),
    "airdrop_or_distribution": re.compile(r"\b(airdrops?|token distributions?|testnet rewards?)\b", re.I),
    "grant_or_funding": re.compile(r"\b(grants?|funding rounds?|bounty programs?)\b", re.I),
    "hackathon_or_competition": re.compile(r"\b(hackathons?|competition prizes?|challenge prizes?|coding challenges?)\b", re.I),
    "early_access_or_beta": re.compile(r"\b(early access|beta testers?|beta rewards?|closed beta)\b", re.I),
    "referral": re.compile(r"\b(referral rewards?|invite rewards?|refer a friend|referral (links?|programs?))\b", re.I),
}

_NEGATIVE_CONCEPTS: dict[str, re.Pattern] = {
    "conspiracy_or_politics": re.compile(r"\b(conspiracy|senate race|election|parliament|president|congress(?:man|woman)?|prime minister)\b", re.I),
    "generic_news": re.compile(r"\b(breaking news|poll shows|according to (police|officials))\b", re.I),
    # Real false positive found live: a viral US-politics/macro-economics
    # tweet with a huge dollar figure ("$95 billion aid package") scored a
    # high opportunity_score purely off engagement + an accidental
    # relevance-keyword hit (e.g. "bonus") — nothing flagged it as noise
    # even though it plainly isn't an opportunity for the user.
    "us_politics_or_macro_news": re.compile(
        r"\b(white house|capitol hill|congress(?:ional)?|the senate|supreme court|federal reserve|"
        r"the fed|national debt|gdp growth|inflation rate|interest rate hike|government shutdown|"
        r"stimulus (?:package|bill)|state of the union|presidential election|midterms?)\b",
        re.I,
    ),
}


def compute_relevance(text: str) -> tuple[float, list[str]]:
    """Returns (relevance_score in [0,1], matched concept names)."""
    if not text:
        return 0.12, []

    pos_hits = [name for name, pat in _POSITIVE_CONCEPTS.items() if pat.search(text)]
    neg_hits = [name for name, pat in _NEGATIVE_CONCEPTS.items() if pat.search(text)]

    raw = 0.12 + 0.20 * min(len(pos_hits), 4) - 0.25 * min(len(neg_hits), 3)
    score = max(0.0, min(1.0, raw))
    return score, pos_hits + [f"OFF-TOPIC:{n}" for n in neg_hits]
