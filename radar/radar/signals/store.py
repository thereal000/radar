"""Historical storage + cross-run opportunity identity resolution.

SQLite (Python stdlib) is used directly here — a database engine is
infrastructure, not a "big feature" to research per CLAUDE.md (same
reasoning as PyYAML earlier: no OSS search needed for something this
generic and already built into the language).

The one genuinely radar-specific problem this module solves: a cluster's
`cluster_id` (e.g. "cluster-014") is only stable WITHIN a single pipeline
run — indices are reassigned every run. To track velocity/saturation over
time we need a persistent `opportunity_id` that identifies "the same
real-world opportunity" across separate runs, days apart. We solve this by
reusing our own dedup evidence functions (already built in dedup.py) to
match each new run's cluster representative against previously stored
opportunity representatives — no new algorithm, just applying what Brick 1
already built to a new axis (time instead of within-batch).
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .cluster import Cluster
from .dedup import DupEvidence, build_minhash, extract_entities
from rapidfuzz import fuzz

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "radar.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    opportunity_id TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    representative_text TEXT,
    representative_url TEXT,
    entity_fingerprint TEXT
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    url TEXT,
    canonical_url TEXT,
    author TEXT,
    published_at TEXT,
    collected_at TEXT,
    title TEXT,
    text TEXT,
    engagement_json TEXT,
    subreddit TEXT,
    content_hash TEXT,
    UNIQUE(source, source_id)
);

CREATE TABLE IF NOT EXISTS opportunity_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    snapshot_at TEXT NOT NULL,
    signal_count INTEGER NOT NULL,
    new_signal_count INTEGER NOT NULL,
    unique_authors INTEGER NOT NULL,
    platforms TEXT NOT NULL,
    total_engagement INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS alert_history (
    opportunity_id TEXT PRIMARY KEY,
    last_alerted_at TEXT NOT NULL,
    last_alerted_score REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snapshots_opportunity ON opportunity_snapshots(opportunity_id, snapshot_at);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StoredOpportunity:
    opportunity_id: str
    representative_text: str
    representative_url: str | None
    entities: set[str]
    minhash: object = None  # MinHash, precomputed once — see _match_existing_opportunity


class RadarStore:
    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = str(db_path)
        with closing(self._connect()) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _existing_opportunities(self, conn: sqlite3.Connection) -> list[StoredOpportunity]:
        rows = conn.execute(
            "SELECT opportunity_id, representative_text, representative_url, entity_fingerprint FROM opportunities"
        ).fetchall()
        return [
            StoredOpportunity(
                opportunity_id=r[0],
                representative_text=r[1] or "",
                representative_url=r[2],
                entities=set(json.loads(r[3])) if r[3] else set(),
                minhash=build_minhash(r[1] or ""),
            )
            for r in rows
        ]

    def _match_existing_opportunity(
        self, cluster: Cluster, existing: list[StoredOpportunity]
    ) -> str | None:
        rep = cluster.representative
        rep_norm = rep.normalized_text or ""
        rep_url = rep.canonical_url
        rep_entities = extract_entities(rep.text or rep.title or "")
        rep_mh = build_minhash(rep_norm)

        for opp in existing:
            same_url = bool(rep_url) and rep_url == opp.representative_url
            same_hash = False  # cross-run text is rarely byte-identical; rely on url/jaccard/fuzzy/entities
            # opp.minhash is precomputed once per persist_run (see
            # _existing_opportunities) — real perf bug found at scale: this
            # used to rebuild it here, i.e. once per (new_cluster x
            # existing_opportunity) pair. After ~10 real cycles with a few
            # thousand accumulated opportunities and a few hundred new
            # clusters per run, that was hundreds of thousands of redundant
            # shingle+hash builds per persist_run call, and the radar
            # visibly ground to a crawl (500+ CPU-seconds, still running
            # after 30 min wall clock for what should take ~15 min).
            jaccard = rep_mh.jaccard(opp.minhash) if rep_norm and opp.representative_text else 0.0
            fratio = fuzz.token_set_ratio(rep_norm, opp.representative_text)
            shared = rep_entities & opp.entities

            ev = DupEvidence(
                a_id="new",
                b_id=opp.opportunity_id,
                same_url=same_url,
                same_hash=same_hash,
                minhash_jaccard=jaccard,
                fuzzy_ratio=fratio,
                shared_entities=shared,
                a_word_count=len(rep_norm.split()),
                b_word_count=len(opp.representative_text.split()),
            )
            if ev.is_duplicate:
                return opp.opportunity_id
        return None

    def persist_run(
        self, clusters: list[Cluster], run_id: str | None = None
    ) -> tuple[dict[str, str], str, set[str]]:
        """Persists one pipeline run's clusters. Returns ({cluster_id: opportunity_id}, run_id, new_opportunity_ids).

        new_opportunity_ids is the set of opportunity_ids that did NOT exist
        before this run — lets callers (e.g. the Telegram bot) tell a genuinely
        new opportunity apart from one we've already reported on a previous
        cycle, instead of the same still-live content looking like repeated
        noise every 30 minutes.
        """
        run_id = run_id or uuid.uuid4().hex[:12]
        now = _now_iso()
        cluster_to_opportunity: dict[str, str] = {}
        new_opportunity_ids: set[str] = set()

        with closing(self._connect()) as conn:
            existing = self._existing_opportunities(conn)

            for cluster in clusters:
                opp_id = self._match_existing_opportunity(cluster, existing)
                is_new = opp_id is None
                if is_new:
                    opp_id = uuid.uuid4().hex[:16]
                    new_opportunity_ids.add(opp_id)

                rep = cluster.representative
                rep_entities = extract_entities(rep.text or rep.title or "")

                if is_new:
                    conn.execute(
                        "INSERT INTO opportunities (opportunity_id, first_seen, last_seen, representative_text, representative_url, entity_fingerprint) VALUES (?,?,?,?,?,?)",
                        (opp_id, now, now, rep.normalized_text, rep.canonical_url, json.dumps(sorted(rep_entities))),
                    )
                    existing.append(
                        StoredOpportunity(
                            opp_id, rep.normalized_text or "", rep.canonical_url, rep_entities,
                            minhash=build_minhash(rep.normalized_text or ""),
                        )
                    )
                else:
                    conn.execute(
                        "UPDATE opportunities SET last_seen=? WHERE opportunity_id=?", (now, opp_id)
                    )

                new_signal_count = 0
                for sig in cluster.signals:
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO signals (opportunity_id, run_id, source, source_id, url, canonical_url, author, published_at, collected_at, title, text, engagement_json, subreddit, content_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            opp_id, run_id, sig.source, sig.source_id, sig.url, sig.canonical_url,
                            sig.author, sig.published_at, sig.collected_at, sig.title, sig.text,
                            json.dumps(sig.engagement), sig.subreddit, sig.content_hash,
                        ),
                    )
                    if cur.rowcount > 0:
                        new_signal_count += 1

                total_signal_count = conn.execute(
                    "SELECT COUNT(*) FROM signals WHERE opportunity_id=?", (opp_id,)
                ).fetchone()[0]
                unique_authors = conn.execute(
                    "SELECT COUNT(DISTINCT author) FROM signals WHERE opportunity_id=?", (opp_id,)
                ).fetchone()[0]
                platforms = sorted({s.source for s in cluster.signals})
                total_engagement = sum(
                    (sig.engagement.get("likes") or 0)
                    + (sig.engagement.get("comments") or 0)
                    + (sig.engagement.get("score") or 0)
                    for sig in cluster.signals
                )

                conn.execute(
                    "INSERT INTO opportunity_snapshots (opportunity_id, run_id, snapshot_at, signal_count, new_signal_count, unique_authors, platforms, total_engagement) VALUES (?,?,?,?,?,?,?,?)",
                    (opp_id, run_id, now, total_signal_count, new_signal_count, unique_authors, json.dumps(platforms), total_engagement),
                )

                cluster_to_opportunity[cluster.cluster_id] = opp_id

            conn.commit()

        return cluster_to_opportunity, run_id, new_opportunity_ids

    def get_snapshots(self, opportunity_id: str) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT snapshot_at, signal_count, new_signal_count, unique_authors, platforms, total_engagement "
                "FROM opportunity_snapshots WHERE opportunity_id=? ORDER BY snapshot_at ASC",
                (opportunity_id,),
            ).fetchall()
        return [
            {
                "snapshot_at": r[0],
                "signal_count": r[1],
                "new_signal_count": r[2],
                "unique_authors": r[3],
                "platforms": json.loads(r[4]),
                "total_engagement": r[5],
            }
            for r in rows
        ]

    def list_opportunities(self) -> list[str]:
        with closing(self._connect()) as conn:
            return [r[0] for r in conn.execute("SELECT opportunity_id FROM opportunities")]

    def should_alert(
        self, opportunity_id: str, score: float, cooldown_hours: float = 24.0, min_score_delta: float = 0.05
    ) -> bool:
        """False if this opportunity was already alerted recently AND its
        score hasn't moved meaningfully since. Found via real observation:
        with no memory of past alerts, a static spam cluster fired 3
        identical alerts (same score, zero velocity) across 3 cycles."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT last_alerted_at, last_alerted_score FROM alert_history WHERE opportunity_id=?",
                (opportunity_id,),
            ).fetchone()
        if row is None:
            return True
        last_at, last_score = row
        hours_since = (datetime.fromisoformat(_now_iso()) - datetime.fromisoformat(last_at)).total_seconds() / 3600
        if hours_since >= cooldown_hours:
            return True
        return abs(score - last_score) >= min_score_delta

    def mark_alerted(self, opportunity_id: str, score: float) -> None:
        now = _now_iso()
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO alert_history (opportunity_id, last_alerted_at, last_alerted_score) VALUES (?,?,?) "
                "ON CONFLICT(opportunity_id) DO UPDATE SET last_alerted_at=excluded.last_alerted_at, last_alerted_score=excluded.last_alerted_score",
                (opportunity_id, now, score),
            )
            conn.commit()
