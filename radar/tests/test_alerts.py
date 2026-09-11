import json
import tempfile
from pathlib import Path

from radar.signals.alerts import AlertDispatcher
from radar.signals.scoring import OpportunityScore


def _score(composite=0.8, before_tiktok=0.1, opportunity_score=None):
    return OpportunityScore(
        opportunity_id="opp1",
        cluster_id="cluster-000",
        signal_count=5,
        platforms={"twitter", "reddit"},
        total_engagement=100,
        velocity=3.0,
        trend="accelerating",
        engagement_score=0.5,
        velocity_score=0.5,
        diversity_score=1.0,
        corroboration_score=0.4,
        recency_score=0.9,
        composite_score=composite,
        before_tiktok_score=before_tiktok,
        saturating=False,
        relevance_score=0.8,
        opportunity_score=opportunity_score if opportunity_score is not None else composite,
        risk_level="LOW",
    )


def test_notify_opportunity_writes_jsonl_record():
    log_path = Path(tempfile.mkdtemp()) / "alerts.jsonl"
    dispatcher = AlertDispatcher(log_path=log_path, enable_desktop_toast=False)

    dispatcher.notify_opportunity(_score(), "ProjectX $500 airdrop live now")

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["opportunity_id"] == "opp1"
    assert record["composite_score"] == 0.8


def test_dispatch_top_opportunities_respects_threshold_and_limit():
    log_path = Path(tempfile.mkdtemp()) / "alerts.jsonl"
    dispatcher = AlertDispatcher(log_path=log_path, enable_desktop_toast=False)

    scored = [
        (_score(composite=0.9), "high score opportunity"),
        (_score(composite=0.2, before_tiktok=0.05), "low score opportunity"),
        (_score(composite=0.6), "medium score opportunity"),
    ]
    sent = dispatcher.dispatch_top_opportunities(scored, threshold=0.5, limit=5)

    assert len(sent) == 2  # only the two >= 0.5 pass the threshold
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
