"""Re-scores the already-collected real opportunities (from the 5 prior
observation cycles, still in radar.db) with the NEW scoring dimensions
(relevance, source_independence, risk, opportunity_score). No new
collection needed — this directly answers "did the named real cases move
in the right direction?" using the exact same real data already gathered.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from radar.signals.clean import normalized_for_dedup  # noqa: E402
from radar.signals.cluster import Cluster  # noqa: E402
from radar.signals.schema import Signal  # noqa: E402
from radar.signals.scoring import score_opportunity  # noqa: E402
from radar.signals.store import DEFAULT_DB_PATH, RadarStore  # noqa: E402

import sqlite3

NAMED_CASES = {
    "de7f250c": "iPhone giveaway (BoroToken-style bot spam)",
    "ceaa042c": "BoroToken SOL wallet-harvesting (self-spam x4)",
    "9cc8c4e7": "Airdrop Address Submission Deadline network",
    "d6a23a8d": "WARDOGS early access (studio+publisher)",
    "92c2ec07": "Conspiracy theorists / social credit (off-topic)",
    "12ba966a": "X Original Content Rewards",
    "04d159fa": "Genspark free credits",
    "88de2674": "GameSir controller giveaway",
    "0909d0fc": "astro_degens crypto flex + wallet ask",
    "b18ce825": "'Good point' (generic short text false merge)",
    "e5b6456a": "Mexico free healthcare (off-topic news)",
    "bd06b5ee": "Talarico/Paxton Senate poll (off-topic news)",
    "9c04383c": "US military historical airdrops (off-topic)",
}


def load_cluster(conn: sqlite3.Connection, opp_prefix: str) -> Cluster | None:
    rows = conn.execute(
        "SELECT source, source_id, url, canonical_url, author, published_at, collected_at, "
        "title, text, engagement_json, subreddit, content_hash FROM signals WHERE opportunity_id LIKE ?",
        (opp_prefix + "%",),
    ).fetchall()
    if not rows:
        return None
    signals = []
    for r in rows:
        source, source_id, url, canonical_url, author, published_at, collected_at, title, text, eng_json, subreddit, content_hash = r
        combined = " ".join(filter(None, [title, text]))
        sig = Signal(
            source=source, source_id=source_id, url=url, author=author or "",
            published_at=published_at, collected_at=collected_at or "", title=title,
            text=text or "", platform=source, engagement=json.loads(eng_json) if eng_json else {},
            subreddit=subreddit, media=[], metadata={},
        )
        sig.canonical_url = canonical_url
        sig.normalized_text = normalized_for_dedup(combined)
        sig.content_hash = content_hash
        signals.append(sig)
    return Cluster(cluster_id=f"retro-{opp_prefix}", signals=signals)


def main():
    conn = sqlite3.connect(str(DEFAULT_DB_PATH))
    store = RadarStore(DEFAULT_DB_PATH)

    print(f"{'case':45s} {'old_comp':>9s} {'new_opp':>8s} {'relev':>6s} {'indep':>6s} {'risk':>10s} {'before_tiktok':>14s}")
    print("-" * 110)
    for prefix, label in NAMED_CASES.items():
        opp_row = conn.execute(
            "SELECT opportunity_id FROM opportunities WHERE opportunity_id LIKE ?", (prefix + "%",)
        ).fetchone()
        if not opp_row:
            print(f"{label:45s} NOT FOUND in DB")
            continue
        opp_id = opp_row[0]
        cluster = load_cluster(conn, prefix)
        if cluster is None:
            print(f"{label:45s} no signals found")
            continue
        snapshots = store.get_snapshots(opp_id)
        score = score_opportunity(cluster, opp_id, snapshots)
        print(
            f"{label:45s} {'?':>9s} {score.opportunity_score:8.3f} {score.relevance_score:6.3f} "
            f"{score.source_independence:6.3f} {score.risk_level + f'({score.risk_score:.2f})':>10s} "
            f"{score.before_tiktok_score:14.3f}"
        )
        if score.risk_reasons:
            print(f"    risk reasons: {score.risk_reasons}")
        if score.relevance_reasons:
            print(f"    relevance reasons: {score.relevance_reasons}")


if __name__ == "__main__":
    main()
