import tempfile
from pathlib import Path

from radar.signals.cluster import build_clusters
from radar.signals.normalize import normalize_twitter_post
from radar.signals.store import RadarStore


def _tweet(id_, text):
    return normalize_twitter_post(
        {
            "id": id_,
            "author": f"user{id_}",
            "text": text,
            "created_at": "Wed Sep 02 19:33:47 +0000 2026",
            "likes": 5,
            "views": "50",
            "url": f"https://x.com/i/status/{id_}",
            "_collector_query": "test",
        }
    )


def _tmp_store() -> RadarStore:
    tmp = Path(tempfile.mkdtemp()) / "test_radar.db"
    return RadarStore(tmp)


def test_new_opportunity_gets_persisted_with_one_snapshot():
    store = _tmp_store()
    clusters = build_clusters([_tweet("a1", "ProjectX airdrop of $500 USDC is live now")])
    mapping, run_id = store.persist_run(clusters)

    assert len(mapping) == 1
    opp_id = next(iter(mapping.values()))
    snaps = store.get_snapshots(opp_id)
    assert len(snaps) == 1
    assert snaps[0]["signal_count"] == 1


def test_same_opportunity_across_two_runs_resolves_to_same_id():
    """Two separate pipeline runs, days apart in theory, mentioning the same
    opportunity in near-identical wording must resolve to the SAME
    opportunity_id so velocity can be tracked over time."""
    store = _tmp_store()

    run1 = build_clusters([_tweet("a1", "ProjectX airdrop of $500 USDC is live now, claim it")])
    mapping1, _ = store.persist_run(run1)
    opp_id_1 = next(iter(mapping1.values()))

    run2 = build_clusters([_tweet("a2", "ProjectX airdrop of $500 USDC is live, go claim it now")])
    mapping2, _ = store.persist_run(run2)
    opp_id_2 = next(iter(mapping2.values()))

    assert opp_id_1 == opp_id_2
    snaps = store.get_snapshots(opp_id_1)
    assert len(snaps) == 2
    assert snaps[-1]["signal_count"] == 2  # a1 + a2 both attributed to the same opportunity


def test_unrelated_opportunity_gets_a_different_id():
    store = _tmp_store()
    run1 = build_clusters([_tweet("a1", "ProjectX airdrop of $500 USDC is live now")])
    mapping1, _ = store.persist_run(run1)

    run2 = build_clusters([_tweet("b1", "Best pizza dough recipe ever, 2 cups flour 1 tsp yeast")])
    mapping2, _ = store.persist_run(run2)

    assert set(mapping1.values()) != set(mapping2.values())


def test_should_alert_false_right_after_marking_with_unchanged_score():
    """Regression test for a real bug found during live observation: a
    static spam cluster (unchanged score, zero velocity) fired 3 identical
    alerts across 3 cycles because nothing remembered it had already been
    alerted."""
    store = _tmp_store()
    assert store.should_alert("opp1", 0.514) is True
    store.mark_alerted("opp1", 0.514)
    assert store.should_alert("opp1", 0.514) is False  # same score, no cooldown elapsed


def test_should_alert_true_when_score_jumps_significantly():
    store = _tmp_store()
    store.mark_alerted("opp1", 0.5)
    assert store.should_alert("opp1", 0.5) is False
    assert store.should_alert("opp1", 0.7) is True  # +0.2 delta clears the min_score_delta bar
