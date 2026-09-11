"""Regression tests for a real bug found via live testing: collect_github
and collect_hackernews didn't set an "id" key on their raw dicts (GitHub's
natural key is "fullName", HN's is "objectID"). pipeline._dedupe_raw_by_id
keys on "id" for every source uniformly, so without this, ALL results
across ALL queries for a source collapsed into a single "post" (id=None
for every one of them) — GitHub and Hacker News silently returned 1 result
total instead of up to ~180 in a real 12-query cycle.

These tests monkeypatch the subprocess/HTTP calls with real-shaped
responses (captured from actual `gh search repos` / HN Algolia calls
during development) rather than hitting the network, so they run fast and
deterministically in CI.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from radar.signals import collectors
from radar.signals.pipeline import _dedupe_raw_by_id


def test_collect_github_sets_distinct_id_per_repo(monkeypatch):
    fake_repos = [
        {"fullName": "acme/repo-a", "description": "d1", "url": "https://github.com/acme/repo-a", "stargazersCount": 1, "updatedAt": "2026-01-01T00:00:00Z", "owner": {"login": "acme"}},
        {"fullName": "acme/repo-b", "description": "d2", "url": "https://github.com/acme/repo-b", "stargazersCount": 2, "updatedAt": "2026-01-02T00:00:00Z", "owner": {"login": "acme"}},
    ]

    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps(fake_repos), stderr="")

    monkeypatch.setattr(collectors.subprocess, "run", fake_run)

    repos = collectors.collect_github("test query")
    ids = {r["id"] for r in repos}
    assert ids == {"acme/repo-a", "acme/repo-b"}

    deduped = _dedupe_raw_by_id(repos)
    assert len(deduped) == 2  # must NOT collapse to 1


def test_collect_hackernews_sets_distinct_id_per_story(monkeypatch):
    fake_hits = [
        {"objectID": "111", "title": "t1", "url": "https://a.com", "author": "u1", "points": 1, "num_comments": 0, "created_at": "2026-01-01T00:00:00.000Z"},
        {"objectID": "222", "title": "t2", "url": "https://b.com", "author": "u2", "points": 2, "num_comments": 1, "created_at": "2026-01-02T00:00:00.000Z"},
    ]

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"hits": fake_hits}

    monkeypatch.setattr(collectors.requests, "get", lambda *a, **k: FakeResponse())

    hits = collectors.collect_hackernews("test query")
    ids = {h["id"] for h in hits}
    assert ids == {"111", "222"}

    deduped = _dedupe_raw_by_id(hits)
    assert len(deduped) == 2  # must NOT collapse to 1
