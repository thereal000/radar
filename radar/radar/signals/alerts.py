"""Alert dispatch via Apprise (BSD-2-Clause, 17.3k★) — "one notification
library to rule them all": Slack, Discord, Telegram, WhatsApp, email,
generic webhooks, Windows/macOS/Linux desktop notifications, 100+ services,
all behind one URL-based API. We do not write per-service integrations
ourselves; adding a new channel later (e.g. WhatsApp, once you have a
Business API token) is a one-line config change, not new code.

Two sinks are always active:
  - a local JSONL audit log (zero external dependency, always works, gives
    every alert a durable, inspectable record)
  - Windows toast notification (`windows://`), proven working in this
    environment — a real, visible test, not a mock

WhatsApp/Slack/etc. are NOT configured here: they need your account
credentials (a Business API token, a webhook URL, ...). Add them by
passing their Apprise URL — see https://github.com/caronc/apprise#popular-notification-services
— nothing else in this module needs to change.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import apprise

from .scoring import OpportunityScore

DEFAULT_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "alerts.jsonl"


class AlertDispatcher:
    def __init__(
        self,
        log_path: Path | str = DEFAULT_LOG_PATH,
        extra_apprise_urls: list[str] | None = None,
        enable_desktop_toast: bool = True,
    ):
        self.log_path = Path(log_path)
        self.apprise = apprise.Apprise()
        if enable_desktop_toast:
            self.apprise.add("windows://")
        for url in extra_apprise_urls or []:
            self.apprise.add(url)

    def notify_opportunity(self, score: OpportunityScore, representative_text: str) -> None:
        # risk_level is always surfaced in the title — never a silent risk (see WHY THIS IS SAFE/UNSAFE requirement)
        title = f"RADAR opportunity ({score.trend}, opp_score={score.opportunity_score}, risk={score.risk_level})"
        body = representative_text[:180]

        record = {
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "title": title,
            "body": body,
            **asdict(score),
            "platforms": sorted(score.platforms),
        }
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        if self.apprise.urls():
            self.apprise.notify(title=title, body=body)

    def dispatch_top_opportunities(
        self, scored: list[tuple[OpportunityScore, str]], threshold: float = 0.35, limit: int = 5
    ) -> list[OpportunityScore]:
        """scored: list of (OpportunityScore, representative_text), already
        filtered by the caller for alert-cooldown (see RadarStore.should_alert
        — this class has no memory of past alerts). Ranked by
        opportunity_score (composite already discounted for off-topic
        content and scam risk), not the raw composite_score — a HIGH-risk
        or off-topic cluster should not out-rank a real one just because it
        has more engagement. Threshold is lower than before (was 0.5 on
        composite_score) because opportunity_score is a discounted metric
        by construction. Returns the scores that were actually notified."""
        eligible = [s for s in scored if s[0].opportunity_score >= threshold or s[0].before_tiktok_score >= threshold]
        eligible.sort(key=lambda s: max(s[0].opportunity_score, s[0].before_tiktok_score), reverse=True)
        sent = []
        for score, text in eligible[:limit]:
            self.notify_opportunity(score, text)
            sent.append(score)
        return sent
