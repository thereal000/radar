from types import SimpleNamespace

from radar.signals import verify_hackathon as vh
from radar.signals.scoring import OpportunityScore


def _score(**overrides) -> OpportunityScore:
    base = dict(
        opportunity_id="opp1",
        cluster_id="c1",
        signal_count=1,
        platforms={"twitter"},
        total_engagement=10,
        velocity=None,
        trend="steady",
        engagement_score=0.1,
        velocity_score=0.1,
        diversity_score=0.5,
        corroboration_score=0.1,
        recency_score=0.8,
        composite_score=0.3,
        before_tiktok_score=0.1,
        saturating=False,
        relevance_score=0.9,
        relevance_reasons=["hackathon_or_competition"],
        representative_text="Join the FirstCommit hackathon! Details: https://firstcommit.devpost.com",
        representative_url="https://x.com/i/status/123",
    )
    base.update(overrides)
    return OpportunityScore(**base)


def test_not_tagged_hackathon_is_not_checked():
    score = _score(relevance_reasons=[])
    result = vh.verify_hackathon(score)
    assert result.checked is False


def test_no_candidate_url_reports_nothing_found(monkeypatch):
    score = _score(representative_text="Hackathon starting soon, no link included", representative_url="https://x.com/i/status/123")
    result = vh.verify_hackathon(score)
    assert result.checked is True
    assert result.official_url is None


def test_social_platform_url_excluded_from_candidates():
    score = _score(representative_url="https://x.com/i/status/123", representative_text="see https://reddit.com/r/x/1 too")
    urls = vh._candidate_urls(score)
    assert urls == []


def test_successful_fetch_extracts_deadline_and_prize(monkeypatch):
    page_text = "Beginner's Paradise hackathon. Deadline: 30 Sept 2026. $1,024 in prizes for winners."

    monkeypatch.setattr(vh, "_run_opencli", lambda args, timeout=30: '{"content": ""}')
    monkeypatch.setattr(vh, "_fetch_page_text", lambda url, session="radar-verify": page_text)
    monkeypatch.setattr(vh, "_own_github_matches", lambda hint, min_score=60.0: [{"name": "cry4radar", "match_score": 80.0}])

    score = _score()
    result = vh.verify_hackathon(score)

    assert result.checked is True
    assert result.blocked is False
    assert "2026" in result.deadline_text
    assert "1,024" in result.prize_text
    assert result.github_matches[0]["name"] == "cry4radar"


def test_anti_bot_page_is_reported_as_blocked_not_solved(monkeypatch):
    monkeypatch.setattr(vh, "_fetch_page_text", lambda url, session="radar-verify": "Please verify you are human to continue.")

    score = _score()
    result = vh.verify_hackathon(score)

    assert result.checked is True
    assert result.blocked is True
    assert result.official_url is not None
    assert "vérifier toi-même" in result.note


def test_fetch_failure_does_not_crash_and_reports_note(monkeypatch):
    monkeypatch.setattr(vh, "_fetch_page_text", lambda url, session="radar-verify": None)

    score = _score()
    result = vh.verify_hackathon(score)

    assert result.checked is True
    assert result.blocked is False
    assert result.official_url is None


def test_own_github_matches_uses_gh_cli_and_fuzzy_matches(monkeypatch):
    fake_repos = [
        {"name": "cry4radar", "description": "opportunity radar", "updatedAt": "2026-09-01T00:00:00Z", "url": "https://github.com/x/cry4radar"},
        {"name": "unrelated-project", "description": "a totally different thing", "updatedAt": "2026-01-01T00:00:00Z", "url": "https://github.com/x/unrelated-project"},
    ]

    def fake_run(*args, **kwargs):
        import json
        return SimpleNamespace(returncode=0, stdout=json.dumps(fake_repos), stderr="")

    monkeypatch.setattr(vh.subprocess, "run", fake_run)

    matches = vh._own_github_matches("cry4radar hackathon project")
    names = {m["name"] for m in matches}
    assert "cry4radar" in names
    assert "unrelated-project" not in names
