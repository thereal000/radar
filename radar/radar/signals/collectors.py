"""Thin wrappers around already-installed OSS tools — one function per
source, each just invoking a CLI/API and returning plain dicts. No scraping
is reimplemented anywhere in this file (Open Source First, per CLAUDE.md):

  - twitter/reddit -> OpenCLI (browser-session backend, already authenticated)
  - github         -> `gh` CLI (official, already authenticated on this machine)
  - hackernews     -> HN Algolia Search API (official, public, no auth)
  - youtube        -> yt-dlp (flat search extraction, no API key needed)
  - rss            -> feedparser (any Atom/RSS feed)

All normalization happens downstream in normalize.py.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone

import feedparser
import requests
import yaml
import yt_dlp

_NPM_BIN = os.path.expandvars(r"%APPDATA%\npm")


def _run_opencli(args: list[str], timeout: int = 60) -> str:
    env = dict(os.environ)
    env["Path"] = _NPM_BIN + os.pathsep + env.get("Path", env.get("PATH", ""))

    cmd = ["cmd", "/c", "opencli", *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"opencli {' '.join(args)} failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout


def collect_twitter(query: str, limit: int | None = None) -> list[dict]:
    args = ["twitter", "search", query, "-f", "yaml"]
    raw = _run_opencli(args)
    posts = yaml.safe_load(raw) or []
    if limit:
        posts = posts[:limit]
    for p in posts:
        p["_collector_source"] = "twitter"
        p["_collector_query"] = query
    return posts


def collect_reddit(query: str, limit: int | None = None) -> list[dict]:
    args = ["reddit", "search", query, "-f", "yaml"]
    raw = _run_opencli(args)
    posts = yaml.safe_load(raw) or []
    if limit:
        posts = posts[:limit]
    for p in posts:
        p["_collector_source"] = "reddit"
        p["_collector_query"] = query
    return posts


def opencli_available() -> bool:
    return shutil.which("opencli") is not None or os.path.exists(
        os.path.join(_NPM_BIN, "opencli.cmd")
    )


def collect_github(query: str, limit: int | None = None) -> list[dict]:
    """Uses the official `gh` CLI (already authenticated on this machine),
    not the GitHub REST API directly — no new auth/token handling needed."""
    n = limit or 15
    args = [
        "gh", "search", "repos", query, "--limit", str(n),
        "--json", "fullName,description,url,stargazersCount,updatedAt,owner",
    ]
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"gh search repos {query!r} failed (exit {result.returncode}): {result.stderr.strip()}")
    repos = json.loads(result.stdout or "[]")
    for r in repos:
        r["id"] = r["fullName"]  # _dedupe_raw_by_id keys on "id" — github's natural key is fullName
        r["_collector_source"] = "github"
        r["_collector_query"] = query
    return repos


def collect_hackernews(query: str, limit: int | None = None) -> list[dict]:
    """HN Algolia Search API (official, public, no auth). Uses
    search_by_date (not the relevance-ranked default endpoint) — a radar
    hunting for early/fresh signals should not surface 2014 stories just
    because they're historically popular matches for the query."""
    n = limit or 15
    resp = requests.get(
        "https://hn.algolia.com/api/v1/search_by_date",
        params={"query": query, "tags": "story", "hitsPerPage": n},
        timeout=15,
    )
    resp.raise_for_status()
    hits = resp.json().get("hits", [])
    for h in hits:
        h["id"] = h["objectID"]  # _dedupe_raw_by_id keys on "id" — HN's natural key is objectID
        h["_collector_source"] = "hackernews"
        h["_collector_query"] = query
    return hits


def collect_youtube(query: str, limit: int | None = None) -> list[dict]:
    """yt-dlp flat search extraction — no YouTube Data API key/quota needed."""
    n = limit or 10
    opts = {
        "quiet": True, "skip_download": True, "extract_flat": True, "no_warnings": True,
        "socket_timeout": 20,  # no timeout was set before — a stalled connection could hang this thread forever
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
    entries = info.get("entries") or []
    videos = []
    for e in entries:
        e["_collector_source"] = "youtube"
        e["_collector_query"] = query
        videos.append(e)
    return videos


DEFAULT_RSS_FEEDS = [
    "https://www.producthunt.com/feed",
]


def collect_rss(feed_urls: list[str] | None = None, limit: int | None = None) -> list[dict]:
    """feedparser over a small, explicit list of feeds — RSS has no search
    query, it's subscription-based, so this ignores the per-cycle query
    list entirely and just pulls the latest N entries per feed."""
    n = limit or 15
    entries = []
    for feed_url in feed_urls or DEFAULT_RSS_FEEDS:
        # feedparser.parse(url) has no timeout of its own and can hang on a
        # slow/dead feed — fetch with an explicit timeout first, then hand
        # feedparser the bytes.
        resp = requests.get(feed_url, timeout=15)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        for e in parsed.entries[:n]:
            entry = dict(e)
            entry["_collector_source"] = "rss"
            entry["_collector_query"] = feed_url
            entries.append(entry)
    return entries
