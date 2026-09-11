from datetime import datetime, timedelta, timezone

from radar.signals.cluster import Cluster, build_clusters
from radar.signals.independence import compute_source_independence
from radar.signals.normalize import normalize_twitter_post


def _tweet(id_, author, text, hours_ago=0):
    ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return normalize_twitter_post(
        {
            "id": id_,
            "author": author,
            "text": text,
            "created_at": ts.strftime("%a %b %d %H:%M:%S +0000 %Y"),
            "likes": 1,
            "views": "10",
            "url": f"https://x.com/i/status/{id_}",
            "_collector_query": "test",
        }
    )


def test_single_signal_cluster_is_fully_independent():
    cluster = build_clusters([_tweet("a1", "solo", "Some unique text about a real launch")])[0]
    score, details = compute_source_independence(cluster)
    assert score == 1.0


def test_one_account_posting_same_bait_repeatedly_is_low_independence():
    """Regression test for the real BoroToken case: ONE account posted the
    same wallet-harvesting bait 4 times with only the tracking link
    changed."""
    sigs = [
        _tweet(f"b{i}", "BoroToken", "Submit Your SOL Wallet Address Only First 2k #Airdrop #SOL", hours_ago=i * 0.1)
        for i in range(4)
    ]
    cluster = build_clusters(sigs)[0]
    score, details = compute_source_independence(cluster)
    assert score < 0.3
    assert details["unique_authors"] == 1


def test_many_distinct_authors_with_varied_wording_is_higher_independence():
    """Directly constructs a Cluster (bypassing build_clusters, which is
    tested elsewhere) to exercise independence scoring on a known,
    deliberately-varied-wording group of 3 distinct authors."""
    sigs = [
        _tweet("c1", "alice", "ProjectX airdrop announcement just dropped, wallet claims open now", hours_ago=5),
        _tweet("c2", "bob", "Heard ProjectX is doing an airdrop, claiming worked for me just now", hours_ago=2),
        _tweet("c3", "carol", "Anyone else seeing the ProjectX airdrop claim page up today?", hours_ago=0),
    ]
    cluster = Cluster(cluster_id="test-cluster", signals=sigs)
    score, details = compute_source_independence(cluster)
    assert score > 0.4
    assert details["unique_authors"] == 3
