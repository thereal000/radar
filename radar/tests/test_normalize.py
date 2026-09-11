from radar.signals.normalize import normalize_reddit_post, normalize_twitter_post


def test_normalize_twitter_post_maps_all_fields():
    raw = {
        "id": "123",
        "author": "alice",
        "text": "Huge $500 USDC airdrop for early users! https://t.co/abc",
        "created_at": "Wed Sep 02 19:33:47 +0000 2026",
        "likes": 100,
        "views": "5000",
        "url": "https://x.com/i/status/123?s=20&t=abc",
        "has_media": True,
        "media_urls": ["https://video.twimg.com/x.mp4"],
        "media_posters": [],
        "card": None,
        "quoted_tweet": None,
        "_collector_query": "airdrop",
    }
    sig = normalize_twitter_post(raw)

    assert sig.source == "twitter"
    assert sig.source_id == "123"
    assert sig.author == "alice"
    assert sig.engagement["likes"] == 100
    assert sig.engagement["views"] == 5000
    assert sig.published_at is not None and sig.published_at.startswith("2026-09-02")
    assert sig.canonical_url is not None
    assert sig.canonical_url.startswith("https://x.com/i/status/123")
    assert "500" in sig.normalized_text
    assert sig.content_hash


def test_normalize_reddit_post_maps_all_fields():
    raw = {
        "id": "abc123",
        "title": "Free credits giveaway for new signups",
        "subreddit": "r/deals",
        "author": "bob",
        "score": 42,
        "comments": 7,
        "url": "https://www.reddit.com/r/deals/comments/abc123/free_credits/",
        "created_utc": 1725000000,
        "selftext": "Sign up here for 500 free credits.",
        "post_hint": "self",
        "url_overridden_by_dest": None,
        "preview_image_url": None,
        "gallery_urls": [],
        "_collector_query": "free credits",
    }
    sig = normalize_reddit_post(raw)

    assert sig.source == "reddit"
    assert sig.subreddit == "r/deals"
    assert sig.title == "Free credits giveaway for new signups"
    assert sig.engagement["score"] == 42
    assert sig.engagement["comments"] == 7
    assert sig.published_at is not None
    assert sig.canonical_url == raw["url"]
    assert sig.content_hash
