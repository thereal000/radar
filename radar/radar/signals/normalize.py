from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from courlan import clean_url

from .clean import clean_text, normalized_for_dedup
from .schema import Signal


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _twitter_created_at_to_iso(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def _reddit_created_utc_to_iso(raw) -> str | None:
    if raw is None:
        return None
    try:
        return datetime.fromtimestamp(float(raw), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _content_hash(canonical_url: str | None, normalized_text: str) -> str:
    basis = (canonical_url or "") + "|" + normalized_text
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def normalize_twitter_post(raw: dict) -> Signal:
    url = raw.get("url", "")
    canonical = clean_url(url) if url else None
    text = clean_text(raw.get("text"))
    norm_text = normalized_for_dedup(raw.get("text"))

    engagement = {
        "likes": raw.get("likes"),
        "comments": None,
        "views": int(raw["views"]) if raw.get("views") not in (None, "") else None,
        "score": None,
    }

    signal = Signal(
        source="twitter",
        source_id=str(raw.get("id")),
        url=url,
        author=raw.get("author", ""),
        published_at=_twitter_created_at_to_iso(raw.get("created_at")),
        collected_at=_now_iso(),
        title=None,
        text=text,
        platform="twitter",
        engagement=engagement,
        subreddit=None,
        media=list(raw.get("media_urls") or []),
        metadata={
            "bio": raw.get("bio"),
            "has_media": raw.get("has_media"),
            "card": raw.get("card"),
            "quoted_tweet": raw.get("quoted_tweet"),
            "matched_queries": raw.get("_matched_queries") or [raw.get("_collector_query")],
        },
    )
    signal.canonical_url = canonical
    signal.normalized_text = norm_text
    signal.content_hash = _content_hash(canonical, norm_text)
    return signal


def normalize_reddit_post(raw: dict) -> Signal:
    url = raw.get("url", "")
    canonical = clean_url(url) if url else None
    combined_text = " ".join(
        filter(None, [raw.get("title"), raw.get("selftext")])
    )
    text = clean_text(raw.get("selftext"))
    norm_text = normalized_for_dedup(combined_text)

    engagement = {
        "likes": None,
        "comments": raw.get("comments"),
        "views": None,
        "score": raw.get("score"),
    }

    signal = Signal(
        source="reddit",
        source_id=str(raw.get("id")),
        url=url,
        author=raw.get("author", ""),
        published_at=_reddit_created_utc_to_iso(raw.get("created_utc")),
        collected_at=_now_iso(),
        title=clean_text(raw.get("title")),
        text=text,
        platform="reddit",
        engagement=engagement,
        subreddit=raw.get("subreddit"),
        media=[u for u in [raw.get("url_overridden_by_dest")] if u]
        + list(raw.get("gallery_urls") or []),
        metadata={
            "post_hint": raw.get("post_hint"),
            "preview_image_url": raw.get("preview_image_url"),
            "matched_queries": raw.get("_matched_queries") or [raw.get("_collector_query")],
        },
    )
    signal.canonical_url = canonical
    signal.normalized_text = norm_text
    signal.content_hash = _content_hash(canonical, norm_text)
    return signal


def normalize_github_repo(raw: dict) -> Signal:
    url = raw.get("url", "")
    canonical = clean_url(url) if url else None
    text = clean_text(raw.get("description"))
    norm_text = normalized_for_dedup(raw.get("description"))
    owner = raw.get("owner") or {}

    signal = Signal(
        source="github",
        source_id=raw.get("fullName", url),
        url=url,
        author=owner.get("login", ""),
        published_at=raw.get("updatedAt"),  # already ISO 8601 from gh CLI
        collected_at=_now_iso(),
        title=raw.get("fullName"),
        text=text,
        platform="github",
        engagement={"likes": None, "comments": None, "views": None, "score": raw.get("stargazersCount")},
        subreddit=None,
        media=[],
        metadata={"matched_queries": raw.get("_matched_queries") or [raw.get("_collector_query")]},
    )
    signal.canonical_url = canonical
    signal.normalized_text = norm_text
    signal.content_hash = _content_hash(canonical, norm_text)
    return signal


def normalize_hn_story(raw: dict) -> Signal:
    url = raw.get("url") or f"https://news.ycombinator.com/item?id={raw.get('objectID')}"
    canonical = clean_url(url) if url else None
    combined_text = " ".join(filter(None, [raw.get("title"), raw.get("story_text")]))
    text = clean_text(raw.get("story_text"))
    norm_text = normalized_for_dedup(combined_text)

    signal = Signal(
        source="hackernews",
        source_id=str(raw.get("objectID")),
        url=url,
        author=raw.get("author", ""),
        published_at=raw.get("created_at"),  # already ISO 8601 from Algolia
        collected_at=_now_iso(),
        title=clean_text(raw.get("title")),
        text=text,
        platform="hackernews",
        engagement={"likes": None, "comments": raw.get("num_comments"), "views": None, "score": raw.get("points")},
        subreddit=None,
        media=[],
        metadata={"matched_queries": raw.get("_matched_queries") or [raw.get("_collector_query")]},
    )
    signal.canonical_url = canonical
    signal.normalized_text = norm_text
    signal.content_hash = _content_hash(canonical, norm_text)
    return signal


def normalize_youtube_video(raw: dict) -> Signal:
    url = raw.get("url") or raw.get("webpage_url") or ""
    canonical = clean_url(url) if url else None
    text = clean_text(raw.get("title"))  # flat search extraction has no description
    norm_text = normalized_for_dedup(raw.get("title"))

    signal = Signal(
        source="youtube",
        source_id=str(raw.get("id")),
        url=url,
        author=raw.get("channel", "") or "",
        published_at=None,  # not available in flat-extraction mode
        collected_at=_now_iso(),
        title=clean_text(raw.get("title")),
        text=text,
        platform="youtube",
        engagement={"likes": None, "comments": None, "views": raw.get("view_count"), "score": None},
        subreddit=None,
        media=[],
        metadata={
            "duration_seconds": raw.get("duration"),
            "matched_queries": raw.get("_matched_queries") or [raw.get("_collector_query")],
        },
    )
    signal.canonical_url = canonical
    signal.normalized_text = norm_text
    signal.content_hash = _content_hash(canonical, norm_text)
    return signal


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str | None) -> str:
    if not html:
        return ""
    return _HTML_TAG_RE.sub(" ", html)


def _rss_published_to_iso(entry: dict) -> str | None:
    parsed = entry.get("published_parsed")
    if not parsed:
        return None
    try:
        return datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def normalize_rss_entry(raw: dict) -> Signal:
    url = raw.get("link", "")
    canonical = clean_url(url) if url else None
    summary = _strip_html(raw.get("summary"))
    text = clean_text(summary)
    combined_text = " ".join(filter(None, [raw.get("title"), summary]))
    norm_text = normalized_for_dedup(combined_text)

    signal = Signal(
        source="rss",
        source_id=raw.get("id") or url,
        url=url,
        author=raw.get("author", "") or "",
        published_at=_rss_published_to_iso(raw),
        collected_at=_now_iso(),
        title=clean_text(raw.get("title")),
        text=text,
        platform="rss",
        engagement={},
        subreddit=None,
        media=[],
        metadata={"feed_url": raw.get("_collector_query")},
    )
    signal.canonical_url = canonical
    signal.normalized_text = norm_text
    signal.content_hash = _content_hash(canonical, norm_text)
    return signal


_NORMALIZERS = {
    "twitter": normalize_twitter_post,
    "reddit": normalize_reddit_post,
    "github": normalize_github_repo,
    "hackernews": normalize_hn_story,
    "youtube": normalize_youtube_video,
    "rss": normalize_rss_entry,
}


def normalize_batch(twitter_raw: list[dict], reddit_raw: list[dict]) -> list[Signal]:
    """Kept for backwards compatibility with existing callers/tests."""
    signals = [normalize_twitter_post(p) for p in twitter_raw]
    signals += [normalize_reddit_post(p) for p in reddit_raw]
    return signals


def normalize_by_source(raw_by_source: dict[str, list[dict]]) -> list[Signal]:
    """General entry point used by the parallel pipeline — one normalizer
    per source, keyed by the same source name used in collectors.py."""
    signals: list[Signal] = []
    for source, raw_posts in raw_by_source.items():
        normalizer = _NORMALIZERS.get(source)
        if normalizer is None:
            continue
        for p in raw_posts:
            signals.append(normalizer(p))
    return signals
