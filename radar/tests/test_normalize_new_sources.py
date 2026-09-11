from radar.signals.normalize import (
    normalize_by_source,
    normalize_github_repo,
    normalize_hn_story,
    normalize_rss_entry,
    normalize_youtube_video,
)


def test_normalize_github_repo_maps_fields():
    raw = {
        "fullName": "acme/free-credits-bot",
        "description": "Bot that tracks free API credits and grants",
        "url": "https://github.com/acme/free-credits-bot",
        "stargazersCount": 42,
        "updatedAt": "2026-09-10T12:00:00Z",
        "owner": {"login": "acme"},
        "_collector_query": "free credits",
    }
    sig = normalize_github_repo(raw)
    assert sig.source == "github"
    assert sig.source_id == "acme/free-credits-bot"
    assert sig.author == "acme"
    assert sig.engagement["score"] == 42
    assert sig.published_at == "2026-09-10T12:00:00Z"
    assert sig.canonical_url is not None


def test_normalize_hn_story_maps_fields():
    raw = {
        "objectID": "123456",
        "title": "Show HN: free GPU credits for open source",
        "url": "https://example.com/free-gpu",
        "author": "someuser",
        "points": 150,
        "num_comments": 30,
        "created_at": "2026-09-10T08:00:00.000Z",
        "story_text": None,
        "_collector_query": "free credits",
    }
    sig = normalize_hn_story(raw)
    assert sig.source == "hackernews"
    assert sig.source_id == "123456"
    assert sig.engagement["score"] == 150
    assert sig.engagement["comments"] == 30
    assert sig.title == "Show HN: free GPU credits for open source"


def test_normalize_hn_story_falls_back_to_hn_url_when_no_external_url():
    raw = {"objectID": "999", "title": "Ask HN: best hackathons?", "url": None, "author": "x", "points": 5, "num_comments": 1, "created_at": "2026-01-01T00:00:00.000Z"}
    sig = normalize_hn_story(raw)
    assert "news.ycombinator.com/item?id=999" in sig.url


def test_normalize_youtube_video_maps_fields():
    raw = {
        "id": "abc123",
        "title": "5 free AI credit programs for creators",
        "channel": "TechChannel",
        "view_count": 5000,
        "url": "https://www.youtube.com/watch?v=abc123",
        "duration": 300,
        "_collector_query": "free credits",
    }
    sig = normalize_youtube_video(raw)
    assert sig.source == "youtube"
    assert sig.author == "TechChannel"
    assert sig.engagement["views"] == 5000
    assert sig.published_at is None  # not available in flat extraction


def test_normalize_rss_entry_strips_html_and_maps_fields():
    raw = {
        "id": "tag:producthunt,1",
        "title": "Modeinspect",
        "link": "https://www.producthunt.com/products/modeinspect",
        "author": "Alex",
        "summary": "<p>99 Days Free AI Credits - Design product UI</p><p><a href='x'>Discussion</a></p>",
        "published_parsed": (2026, 9, 10, 3, 31, 49, 3, 253, 0),
        "_collector_query": "https://www.producthunt.com/feed",
    }
    sig = normalize_rss_entry(raw)
    assert sig.source == "rss"
    assert "Free AI Credits" in sig.text
    assert "<p>" not in sig.text
    assert sig.published_at is not None
    assert sig.published_at.startswith("2026-09-10")


def test_normalize_by_source_dispatches_correctly():
    raw_by_source = {
        "github": [{"fullName": "a/b", "description": "d", "url": "https://github.com/a/b", "stargazersCount": 1, "updatedAt": "2026-01-01T00:00:00Z", "owner": {"login": "a"}}],
        "hackernews": [{"objectID": "1", "title": "t", "url": "https://x.com", "author": "u", "points": 1, "num_comments": 0, "created_at": "2026-01-01T00:00:00.000Z"}],
        "unknown_source": [{"foo": "bar"}],  # must be silently skipped, not crash
    }
    signals = normalize_by_source(raw_by_source)
    assert {s.source for s in signals} == {"github", "hackernews"}
    assert len(signals) == 2
