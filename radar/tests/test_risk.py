from radar.signals.cluster import Cluster
from radar.signals.normalize import normalize_twitter_post
from radar.signals.risk import assess_risk


def _tweet(id_, author, text):
    return normalize_twitter_post(
        {
            "id": id_,
            "author": author,
            "text": text,
            "created_at": "Wed Sep 02 19:33:47 +0000 2026",
            "likes": 1,
            "views": "10",
            "url": f"https://x.com/i/status/{id_}",
            "_collector_query": "test",
        }
    )


def test_wallet_request_alone_is_not_automatically_high_risk():
    """Per instruction: a wallet address ask alone is not automatically a
    scam (a public wallet can be legitimate)."""
    cluster = Cluster(
        cluster_id="c1",
        signals=[_tweet("a1", "alice", "Submit your wallet address to be added to the ProjectX whitelist")],
    )
    result = assess_risk(cluster, source_independence=1.0)
    assert result.risk_level in ("LOW", "MEDIUM")
    assert result.risk_score < 0.6


def test_seed_phrase_request_is_always_high_risk():
    cluster = Cluster(cluster_id="c2", signals=[_tweet("a2", "scammer", "Enter your seed phrase to claim your reward")])
    result = assess_risk(cluster, source_independence=1.0)
    assert result.risk_level == "HIGH"


def test_wallet_request_plus_urgency_plus_low_independence_compounds_to_high():
    """Regression test for the real BoroToken pattern: wallet ask + scarcity
    language + one account spamming the same bait repeatedly."""
    cluster = Cluster(
        cluster_id="c3",
        signals=[_tweet(f"b{i}", "BoroToken", "Submit Your SOL Wallet Address Only First 2k #Airdrop") for i in range(4)],
    )
    result = assess_risk(cluster, source_independence=0.15)  # low, as BoroToken's self-spam would compute
    assert result.risk_level == "HIGH"
    assert any("compounding" in r for r in result.reasons)


def test_wallet_address_request_matches_plural_form():
    """Regression test for a real bug found via retroactive re-scoring: the
    real 'Airdrop Address Submission Deadline' network case used the plural
    'wallet addresses', which the original singular-only regex silently
    missed, scoring risk=0 for an obvious wallet-harvesting pattern."""
    cluster = Cluster(
        cluster_id="c5",
        signals=[_tweet("e1", "zandyor", "Airdrop Address Submission Deadline. I am accepting wallet addresses for the airdrop until 22:00 UTC.")],
    )
    result = assess_risk(cluster, source_independence=1.0)
    assert "wallet_address_request" in result.reasons


def test_legitimate_launch_announcement_is_low_risk():
    cluster = Cluster(
        cluster_id="c4",
        signals=[
            _tweet("d1", "WARDOGS", "WARDOGS EARLY ACCESS IS NOW LIVE!"),
            _tweet("d2", "Team17", "WARDOGS EARLY ACCESS IS NOW LIVE!"),
        ],
    )
    result = assess_risk(cluster, source_independence=0.4)
    assert result.risk_level == "LOW"
    assert result.risk_score < 0.3
