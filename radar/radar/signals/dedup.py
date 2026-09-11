"""Multi-method duplicate signal detection.

We reuse mature OSS primitives for the actual similarity math (this is the
"70%+ already exists" part per CLAUDE.md):
  - datasketch.MinHash / MinHashLSH -> near-duplicate text detection at scale
  - rapidfuzz -> fast fuzzy string ratio for small-scale confirmation
  - courlan (in normalize.py) -> URL canonicalization for exact URL match

What we build ourselves (the radar-specific orchestration, not available
off-the-shelf): lightweight opportunity-entity extraction (reward amounts,
project names, event/hackathon names) and the decision logic that combines
all of the above signals into a single "are these the same opportunity?"
verdict. This combination step is exactly the kind of glue logic CLAUDE.md
says is ours to write, not something to source off GitHub.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from datasketch import MinHash, MinHashLSH
from rapidfuzz import fuzz

from .schema import Signal

_SHINGLE_SIZE = 3
_NUM_PERM = 128

_MONEY_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s?(?:usd|usdc|usdt|eth|sol|btc|pts?|points)\b", re.I)
_CAPWORDS_RE = re.compile(r"\b(?:[A-Z][a-zA-Z0-9]{2,}(?:\s+[A-Z][a-zA-Z0-9]{2,}){0,2})\b")
_HASHTAG_RE = re.compile(r"#\w+")


def extract_entities(raw_text: str) -> set[str]:
    """Cheap, radar-specific entity extraction: reward amounts, capitalized
    project/company-looking phrases, hashtags. Not NER — a fast heuristic
    tuned to the airdrop/giveaway/hackathon domain, deliberately avoiding a
    heavy spaCy/transformer dependency for what is, for now, a foundation
    layer."""
    if not raw_text:
        return set()
    ents = set()
    ents |= {m.group(0).lower().replace(" ", "") for m in _MONEY_RE.finditer(raw_text)}
    ents |= {m.group(0).strip().lower() for m in _CAPWORDS_RE.finditer(raw_text) if len(m.group(0)) > 3}
    ents |= {m.group(0).lower() for m in _HASHTAG_RE.finditer(raw_text)}
    return ents


def _shingles(text: str, k: int = _SHINGLE_SIZE) -> set[str]:
    tokens = text.split()
    if len(tokens) < k:
        return {text} if text else set()
    return {" ".join(tokens[i : i + k]) for i in range(len(tokens) - k + 1)}


def build_minhash(normalized_text: str) -> MinHash:
    mh = MinHash(num_perm=_NUM_PERM)
    for shingle in _shingles(normalized_text):
        mh.update(shingle.encode("utf-8"))
    return mh


def _has_shingle_content(normalized_text: str) -> bool:
    """An un-updated MinHash (built from zero shingles, e.g. a tweet that is
    just a bare link with no caption) trivially reports jaccard=1.0 against
    any other un-updated MinHash — a false positive, not real similarity.
    Any near-dup verdict built on such a MinHash must be discarded."""
    return len(_shingles(normalized_text)) > 0


@dataclass
class DupEvidence:
    a_id: str
    b_id: str
    same_url: bool
    same_hash: bool
    minhash_jaccard: float
    fuzzy_ratio: float
    shared_entities: set[str]
    a_word_count: int = 0
    b_word_count: int = 0

    @property
    def _length_ratio(self) -> float:
        hi = max(self.a_word_count, self.b_word_count)
        if hi == 0:
            return 0.0
        return min(self.a_word_count, self.b_word_count) / hi

    @property
    def is_duplicate(self) -> bool:
        if self.same_url or self.same_hash:
            return True
        if self.minhash_jaccard >= 0.5:
            return True
        # rapidfuzz's token_set_ratio only checks whether the SHORTER text's
        # words appear somewhere in the longer one — for a short generic
        # sentence vs. a long essay, that's true by chance, not because
        # they're related (real bug found via live data: a 6-word Reddit
        # title scored 89% "similar" to two unrelated long tweets purely
        # because common words like "what"/"is"/"at" appear somewhere in
        # both). Only trust the fuzzy score when the two texts are within
        # roughly the same order of magnitude in length.
        if self.fuzzy_ratio >= 85 and self._length_ratio >= 0.35:
            return True
        if self.minhash_jaccard >= 0.3 and len(self.shared_entities) >= 2:
            return True
        return False


def build_lsh_index(signals: list[Signal], threshold: float = 0.2) -> tuple[MinHashLSH, dict[str, MinHash]]:
    lsh = MinHashLSH(threshold=threshold, num_perm=_NUM_PERM)
    minhashes: dict[str, MinHash] = {}
    for sig in signals:
        key = f"{sig.source}:{sig.source_id}"
        mh = build_minhash(sig.normalized_text or "")
        minhashes[key] = mh
        lsh.insert(key, mh)
    return lsh, minhashes


_MAX_ENTITY_BUCKET = 50  # avoid O(n^2) blowup on generic/very-common entities


def _entity_candidate_pairs(entities_cache: dict[str, set[str]]) -> set[tuple[str, str]]:
    """Blocking by shared entity: two signals mentioning the same reward
    amount / project name / hashtag are worth comparing even if their
    MinHash similarity falls below the LSH threshold (e.g. very short
    posts, or a title+body vs. body-only mismatch in shingle overlap)."""
    inverted: dict[str, list[str]] = defaultdict(list)
    for key, ents in entities_cache.items():
        for e in ents:
            inverted[e].append(key)

    pairs: set[tuple[str, str]] = set()
    for members in inverted.values():
        if len(members) < 2 or len(members) > _MAX_ENTITY_BUCKET:
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                pairs.add(tuple(sorted((members[i], members[j]))))
    return pairs


def find_duplicate_pairs(signals: list[Signal]) -> list[DupEvidence]:
    """Returns pairwise evidence for every candidate pair surfaced by either
    the MinHash LSH index (sub-linear vs. brute force O(n^2) at scale) or
    shared-entity blocking, confirmed with exact-hash, exact-URL, MinHash
    jaccard and rapidfuzz checks. Two independent candidate sources are used
    because LSH alone can miss pairs whose overall shingle overlap is low
    but which share the one entity (reward amount, project name) that
    actually identifies them as the same opportunity."""
    lsh, minhashes = build_lsh_index(signals)
    by_key = {f"{s.source}:{s.source_id}": s for s in signals}
    entities_cache = {k: extract_entities(s.text or s.title or "") for k, s in by_key.items()}

    candidate_pairs: set[tuple[str, str]] = set()
    for key in by_key:
        for cand_key in lsh.query(minhashes[key]):
            if cand_key != key:
                candidate_pairs.add(tuple(sorted((key, cand_key))))
    candidate_pairs |= _entity_candidate_pairs(entities_cache)

    has_content = {k: _has_shingle_content(s.normalized_text or "") for k, s in by_key.items()}

    evidence: list[DupEvidence] = []
    for pair in candidate_pairs:
        a, b = by_key[pair[0]], by_key[pair[1]]
        if has_content[pair[0]] and has_content[pair[1]]:
            jaccard = minhashes[pair[0]].jaccard(minhashes[pair[1]])
        else:
            jaccard = 0.0  # trivial MinHash equality on empty/near-empty text is not real similarity
        fratio = fuzz.token_set_ratio(a.normalized_text or "", b.normalized_text or "")
        shared_ents = entities_cache[pair[0]] & entities_cache[pair[1]]

        evidence.append(
            DupEvidence(
                a_id=pair[0],
                b_id=pair[1],
                same_url=bool(a.canonical_url) and a.canonical_url == b.canonical_url,
                same_hash=a.content_hash == b.content_hash,
                minhash_jaccard=jaccard,
                fuzzy_ratio=fratio,
                shared_entities=shared_ents,
                a_word_count=len((a.normalized_text or "").split()),
                b_word_count=len((b.normalized_text or "").split()),
            )
        )
    return evidence
