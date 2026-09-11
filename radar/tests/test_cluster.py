from radar.signals.cluster import build_clusters
from radar.signals.normalize import normalize_reddit_post, normalize_twitter_post


def _tweet(id_, text, url=None):
    return normalize_twitter_post(
        {
            "id": id_,
            "author": f"user{id_}",
            "text": text,
            "created_at": "Wed Sep 02 19:33:47 +0000 2026",
            "likes": 1,
            "views": "10",
            "url": url or f"https://x.com/i/status/{id_}",
            "_collector_query": "test",
        }
    )


def _reddit(id_, title, selftext, url=None):
    return normalize_reddit_post(
        {
            "id": id_,
            "title": title,
            "subreddit": "r/x",
            "author": f"user{id_}",
            "score": 1,
            "comments": 0,
            "url": url or f"https://www.reddit.com/r/x/comments/{id_}/{id_}/",
            "created_utc": 1725000000,
            "selftext": selftext,
            "_collector_query": "test",
        }
    )


def test_many_posts_about_same_opportunity_collapse_into_one_cluster():
    """30 posts about the same opportunity -> 1 cluster, not 30 opportunities."""
    variants = [
        "ProjectX just launched a $500 USDC airdrop for early users, claim now",
        "ProjectX launched a $500 USDC airdrop for early users, claim it now",
        "Heads up: ProjectX airdrop of $500 USDC is live for early users",
        "ProjectX $500 USDC airdrop for early users is now live, go claim",
        "Just saw ProjectX dropped a $500 USDC airdrop for early adopters",
    ]
    tweets = [_tweet(f"t{i}", txt) for i, txt in enumerate(variants)]
    reddit_posts = [
        _reddit(f"r{i}", "ProjectX airdrop live", txt) for i, txt in enumerate(variants)
    ]
    unrelated = [
        _tweet("u1", "My cat just knocked a plant off the table lol"),
        _reddit("u2", "Best pizza dough recipe", "2 cups flour, 1 tsp yeast, water, salt"),
    ]

    signals = tweets + reddit_posts + unrelated
    clusters = build_clusters(signals)

    opportunity_clusters = [c for c in clusters if len(c.signals) >= 5]
    assert len(opportunity_clusters) == 1
    big = opportunity_clusters[0]
    assert len(big.signals) == 10  # 5 tweets + 5 reddit posts, same opportunity
    assert big.platforms == {"twitter", "reddit"}

    # unrelated posts must NOT be absorbed into the big cluster
    unrelated_ids = {s.cluster_id for s in signals if s.source_id in ("u1", "u2")}
    assert big.cluster_id not in unrelated_ids


def test_exact_same_url_always_clusters_together_even_with_different_text():
    a = _tweet("a1", "check this out", url="https://example.com/offer?ref=1")
    b = _tweet("a2", "totally different caption, unrelated words here", url="https://example.com/offer?ref=2")
    clusters = build_clusters([a, b])
    assert len(clusters) == 1
    assert len(clusters[0].signals) == 2
