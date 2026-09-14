"""Regression tests for real bugs found by red-teaming the pipeline with
realistic and malformed inputs (not synthetic happy paths).

Each test here maps to a concrete defect that was reproduced first, then
fixed:

  1. diversity_score overflow   - len(platforms)/2 was never updated when
                                  the radar grew from 2 to 6 sources, so a
                                  4-platform cluster scored 2.0 and inflated
                                  composite/opportunity score.
  2. malformed engagement crash - int("1.2K") raised ValueError in
                                  normalize_twitter_post; with no guard in
                                  normalize_by_source, ONE bad post aborted
                                  normalization for every source.
  3. id-less item collapse      - _dedupe_raw_by_id keyed on str(id), so
                                  every item without an id collapsed onto
                                  the literal "None".
  4. non-http fetch candidates  - candidate links are scraped from
                                  third-party text, so a non-web scheme
                                  must never reach the browser bridge.
"""
from __future__ import annotations

from radar.signals.cluster import Cluster, build_clusters
from radar.signals.normalize import _safe_int, normalize_by_source, normalize_twitter_post
from radar.signals.pipeline import _dedupe_raw_by_id
from radar.signals.scoring import score_opportunity
from radar.signals.store import RadarStore
from radar.signals import verify_hackathon as vh


def _tweet_raw(**overrides) -> dict:
    raw = {
        "id": "t",
        "author": "a",
        "text": "ProjectX $500 airdrop free credits signup now eligible limited spots",
        "created_at": "Wed Sep 02 19:33:47 +0000 2026",
        "likes": 1,
        "views": "10",
        "url": "https://x.com/i/status/t",
        "_collector_query": "q",
    }
    raw.update(overrides)
    return raw


# --------------------------------------------------------------------------
# 1. diversity_score
# --------------------------------------------------------------------------

def test_diversity_score_is_capped_at_one_for_many_platforms():
    """A cluster reported on 4 platforms must not score diversity > 1.0."""
    from radar.signals.normalize import (
        normalize_github_repo,
        normalize_hn_story,
        normalize_reddit_post,
    )

    sigs = [
        normalize_twitter_post(_tweet_raw(id="d1")),
        normalize_reddit_post(
            {
                "id": "d2", "title": "ProjectX airdrop", "subreddit": "r/x", "author": "b",
                "score": 1, "comments": 0, "url": "https://www.reddit.com/r/x/comments/d2/",
                "created_utc": 1725000000, "selftext": "ProjectX $500 airdrop free credits",
                "_collector_query": "q",
            }
        ),
        normalize_hn_story(
            {
                "objectID": "d3", "title": "ProjectX airdrop", "url": "https://ex.com/p",
                "author": "c", "points": 1, "num_comments": 0,
                "created_at": "2026-09-02T00:00:00Z", "_collector_query": "q",
            }
        ),
        normalize_github_repo(
            {
                "fullName": "o/p", "description": "ProjectX airdrop free credits",
                "url": "https://github.com/o/p", "stargazersCount": 1,
                "updatedAt": "2026-09-02T00:00:00Z", "owner": {"login": "d"},
                "_collector_query": "q",
            }
        ),
    ]
    cluster = Cluster(cluster_id="c", signals=sigs)
    score = score_opportunity(cluster, "o1", [])

    assert len(cluster.platforms) == 4
    assert score.diversity_score == 1.0  # was 2.0 before the fix
    assert 0.0 <= score.composite_score <= 1.0
    assert 0.0 <= score.opportunity_score <= 1.0
    assert 0.0 <= score.confidence_score <= 1.0


# --------------------------------------------------------------------------
# 2. malformed engagement never crashes
# --------------------------------------------------------------------------

def test_safe_int_parses_real_world_counter_shapes():
    assert _safe_int(1200) == 1200
    assert _safe_int("1200") == 1200
    assert _safe_int("1,234") == 1234
    assert _safe_int("1.2K") == 1200
    assert _safe_int("3M") == 3_000_000
    assert _safe_int("") is None
    assert _safe_int(None) is None
    assert _safe_int("N/A") is None
    assert _safe_int("many") is None


def test_malformed_views_do_not_crash_normalization():
    """`int("1.2K")` used to raise ValueError here."""
    sig = normalize_twitter_post(_tweet_raw(id="m1", views="1.2K"))
    assert sig.engagement["views"] == 1200

    sig = normalize_twitter_post(_tweet_raw(id="m2", views="N/A", likes="lots"))
    assert sig.engagement["views"] is None
    assert sig.engagement["likes"] is None


def test_one_bad_post_does_not_sink_normalization_for_the_whole_batch():
    batch = {
        "twitter": [
            _tweet_raw(id="good", views="10"),
            "not-a-dict",  # a malformed item still raises inside the normalizer
            _tweet_raw(id="good2", views="5"),
        ]
    }
    signals = normalize_by_source(batch)
    assert {s.source_id for s in signals} == {"good", "good2"}


def test_non_numeric_engagement_does_not_crash_scoring():
    """_total_engagement sums counters directly — a leftover non-numeric
    value would raise TypeError there."""
    cluster = Cluster(
        cluster_id="c",
        signals=[normalize_twitter_post(_tweet_raw(id="e1", likes="many", views="N/A"))],
    )
    score = score_opportunity(cluster, "o1", [])  # must not raise
    assert score.total_engagement == 0


# --------------------------------------------------------------------------
# 3. raw dedup must not collapse distinct id-less items
# --------------------------------------------------------------------------

def test_dedupe_raw_keeps_distinct_items_that_have_no_id():
    posts = [
        {"title": "a", "link": "https://ex.com/a"},
        {"title": "b", "link": "https://ex.com/b"},
        {"title": "c", "link": "https://ex.com/c"},
    ]
    assert len(_dedupe_raw_by_id(posts)) == 3  # was 1 before the fix


def test_dedupe_raw_still_collapses_the_same_item_across_queries():
    """The fix must not break the original purpose: one post seen under two
    queries is still one item, with both queries recorded."""
    posts = [
        {"id": "dup", "title": "same", "_collector_query": "q1"},
        {"id": "dup", "title": "same", "_collector_query": "q2"},
    ]
    out = _dedupe_raw_by_id(posts)
    assert len(out) == 1
    assert set(out[0]["_matched_queries"]) == {"q1", "q2"}


# --------------------------------------------------------------------------
# 4. only http(s) candidate URLs are ever fetched
# --------------------------------------------------------------------------

def test_non_http_candidate_urls_are_never_fetched():
    class _Score:
        representative_url = "javascript:alert(1)"
        representative_text = (
            "hackathon! see file:///etc/passwd or https://ok.example.com/x"
        )

    urls = vh._candidate_urls(_Score())
    assert urls == ["https://ok.example.com/x"]


# --------------------------------------------------------------------------
# 5. duplicate (source, source_id) keys never crash clustering
# --------------------------------------------------------------------------

def test_duplicate_signal_keys_do_not_crash_clustering():
    """datasketch's MinHashLSH.insert raises "The given key already exists"
    on a duplicate key, which aborted the whole cycle. Two signals can
    legitimately share a (source, source_id) key when the upstream id was
    missing (both end up "None") — build_clusters must de-duplicate instead
    of raising."""
    a = normalize_twitter_post(_tweet_raw(id="dup", url="https://x.com/i/status/1"))
    b = normalize_twitter_post(_tweet_raw(id="dup", url="https://x.com/i/status/2"))
    clusters = build_clusters([a, b])  # must not raise
    assert sum(len(c.signals) for c in clusters) == 1  # duplicate key collapsed, first kept


# --------------------------------------------------------------------------
# 6. non-string fields never reach SQLite
# --------------------------------------------------------------------------

def test_non_string_title_is_coerced_and_persists_cleanly():
    """A non-string GitHub fullName used to reach store.persist_run as-is
    and raise sqlite3.ProgrammingError ("Error binding parameter: type
    'list' is not supported")."""
    from radar.signals.normalize import normalize_github_repo
    import tempfile
    from pathlib import Path as _P

    sig = normalize_github_repo(
        {
            "fullName": ["weird"],  # non-string
            "description": "a real description",
            "url": "https://github.com/o/p",
            "stargazersCount": 3,
            "updatedAt": ["2026-01-01"],  # non-string
            "owner": "not-a-dict",  # non-dict
            "_collector_query": "q",
        }
    )
    assert sig.title is None
    assert sig.published_at is None
    assert sig.author == ""

    clusters = build_clusters([sig])
    store = RadarStore(_P(tempfile.mkdtemp()) / "t.db")
    mapping, run_id, new_ids = store.persist_run(clusters)  # must not raise
    assert len(mapping) == 1


def test_non_string_published_at_does_not_crash_scoring():
    sig = normalize_twitter_post(_tweet_raw(id="p1"))
    sig.published_at = 12345  # type: ignore[assignment]
    cluster = Cluster(cluster_id="c", signals=[sig])
    score = score_opportunity(cluster, "o1", [])  # must not raise
    assert score.recency_score == 0.0
