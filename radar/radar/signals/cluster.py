"""Opportunity clustering: N duplicate/related posts -> 1 cluster + associated signals.

This is radar-specific orchestration logic (per CLAUDE.md, ours to write):
union-find over three evidence sources, two of them exact/cheap (same
canonical URL, same exact content hash) and computed directly here, and one
approximate (MinHash LSH + rapidfuzz + shared entities) computed in dedup.py.
No existing OSS project does "combine URL+hash+near-dup+entity evidence into
opportunity clusters for our domain" out of the box, so this glue is coded
from scratch on top of the reused primitives.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .dedup import DupEvidence, find_duplicate_pairs
from .schema import Signal


class _UnionFind:
    def __init__(self, keys: list[str]):
        self.parent = {k: k for k in keys}

    def find(self, k: str) -> str:
        while self.parent[k] != k:
            self.parent[k] = self.parent[self.parent[k]]
            k = self.parent[k]
        return k

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


@dataclass
class Cluster:
    cluster_id: str
    signals: list[Signal]
    evidence: list[DupEvidence] = field(default_factory=list)

    @property
    def representative(self) -> Signal:
        return max(self.signals, key=lambda s: len(s.text or s.title or ""))

    @property
    def platforms(self) -> set[str]:
        return {s.source for s in self.signals}

    @property
    def urls(self) -> set[str]:
        return {s.canonical_url or s.url for s in self.signals}


def build_clusters(signals: list[Signal]) -> list[Cluster]:
    # Deduplicate by (source, source_id) up front: cluster/union-find ids are
    # derived from this key, and a duplicate key would make the union-find
    # and the MinHash index ambiguous (and used to raise inside
    # MinHashLSH.insert). Keep the first occurrence.
    by_key: dict[str, Signal] = {}
    for s in signals:
        by_key.setdefault(f"{s.source}:{s.source_id}", s)
    keys = list(by_key)
    uf = _UnionFind(keys)

    # 1) exact canonical URL match
    by_url: dict[str, list[str]] = defaultdict(list)
    for k, s in by_key.items():
        if s.canonical_url:
            by_url[s.canonical_url].append(k)
    for group in by_url.values():
        for k in group[1:]:
            uf.union(group[0], k)

    # 2) exact content hash match
    by_hash: dict[str, list[str]] = defaultdict(list)
    for k, s in by_key.items():
        if s.content_hash:
            by_hash[s.content_hash].append(k)
    for group in by_hash.values():
        for k in group[1:]:
            uf.union(group[0], k)

    # 3) near-duplicate evidence (MinHash LSH + rapidfuzz + shared entities)
    evidence = find_duplicate_pairs(signals)
    evidence_by_root_pair: dict[tuple[str, str], list[DupEvidence]] = defaultdict(list)
    for ev in evidence:
        if ev.is_duplicate:
            uf.union(ev.a_id, ev.b_id)
        root_pair = tuple(sorted((uf.find(ev.a_id), uf.find(ev.b_id))))
        evidence_by_root_pair[root_pair].append(ev)

    # group signals by final root, assign stable cluster ids
    groups: dict[str, list[str]] = defaultdict(list)
    for k in keys:
        groups[uf.find(k)].append(k)

    clusters: list[Cluster] = []
    for i, (root, member_keys) in enumerate(sorted(groups.items(), key=lambda kv: kv[0])):
        cluster_id = f"cluster-{i:03d}"
        members = [by_key[k] for k in member_keys]
        for m in members:
            m.cluster_id = cluster_id
        cluster_evidence = [
            ev
            for pair, evs in evidence_by_root_pair.items()
            if root in pair
            for ev in evs
        ]
        clusters.append(Cluster(cluster_id=cluster_id, signals=members, evidence=cluster_evidence))

    return clusters
