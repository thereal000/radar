from datetime import datetime, timedelta, timezone

from radar.signals.cluster import build_clusters
from radar.signals.normalize import normalize_twitter_post
from radar.signals.scoring import score_opportunity


def _tweet(id_, text, likes=1, hours_ago=0):
    ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return normalize_twitter_post(
        {
            "id": id_,
            "author": f"user{id_}",
            "text": text,
            "created_at": ts.strftime("%a %b %d %H:%M:%S +0000 %Y"),
            "likes": likes,
            "views": "100",
            "url": f"https://x.com/i/status/{id_}",
            "_collector_query": "test",
        }
    )


def _snap(hours_ago: float, count: int) -> dict:
    ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {"snapshot_at": ts.isoformat(), "signal_count": count}


def test_fresh_high_engagement_growing_opportunity_scores_high():
    cluster = build_clusters([_tweet("a1", "ProjectX $500 USDC airdrop", likes=5000, hours_ago=0.5)])[0]
    snaps = [_snap(2, 5), _snap(1, 20), _snap(0, 60)]
    score = score_opportunity(cluster, "opp1", snaps)
    assert score.composite_score > 0.5
    assert score.trend in ("accelerating", "insufficient_data")


def test_old_stale_low_engagement_opportunity_scores_low():
    cluster = build_clusters([_tweet("a2", "some old low-engagement post", likes=0, hours_ago=200)])[0]
    score = score_opportunity(cluster, "opp2", [])
    assert score.composite_score < 0.3
    assert score.recency_score == 0.0


def test_before_tiktok_score_favors_small_fast_growing_over_large_established():
    small_fast = build_clusters([_tweet("a3", "tiny new thing", likes=10, hours_ago=0.2)])[0]
    small_fast_snaps = [_snap(2, 2), _snap(1, 6), _snap(0, 15)]
    small_fast_score = score_opportunity(small_fast, "opp3", small_fast_snaps)

    large_established = build_clusters(
        [_tweet(f"b{i}", "huge already-viral thing", likes=1000, hours_ago=1) for i in range(40)]
    )[0]
    large_snaps = [_snap(2, 38), _snap(1, 39), _snap(0, 40)]
    large_score = score_opportunity(large_established, "opp4", large_snaps)

    assert small_fast_score.before_tiktok_score > large_score.before_tiktok_score


def test_before_tiktok_is_gated_by_relevance_not_earliness_alone():
    """Regression test for the real false positive found in observation:
    off-topic political content had the HIGHEST before_tiktok score in the
    whole session (0.322) purely because it was small+accelerating, with no
    check that it was actually about an opportunity. BEFORE_TIKTOK must now
    be EARLYNESS x RELEVANCE."""
    off_topic = build_clusters(
        [_tweet("p1", "THE CONSPIRACY THEORISTS WERE RIGHT! Citizens will need 100 social credit score points from their digital ID", hours_ago=0.2)]
    )[0]
    off_topic_snaps = [_snap(2, 1), _snap(1, 1), _snap(0, 2)]
    off_topic_score = score_opportunity(off_topic, "opp5", off_topic_snaps)

    real_opportunity = build_clusters(
        [_tweet("p2", "ProjectX airdrop is live, eligible users can claim free credits now", hours_ago=0.2)]
    )[0]
    real_snaps = [_snap(2, 1), _snap(1, 1), _snap(0, 2)]
    real_score = score_opportunity(real_opportunity, "opp6", real_snaps)

    assert off_topic_score.relevance_score < 0.15
    assert real_score.relevance_score > off_topic_score.relevance_score
    assert real_score.before_tiktok_score > off_topic_score.before_tiktok_score
    # same velocity/trend/earliness inputs, so the gap must come from relevance
    assert off_topic_score.before_tiktok_score < 0.05


def test_opportunity_score_discounts_high_risk_clusters():
    scammy = build_clusters(
        [_tweet(f"s{i}", "Submit your wallet address, seed phrase required to claim, only first 100!", hours_ago=0.1) for i in range(3)]
    )[0]
    scammy_score = score_opportunity(scammy, "opp7", [])

    assert scammy_score.risk_level == "HIGH"
    assert scammy_score.opportunity_score < scammy_score.composite_score
