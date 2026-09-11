"""Periodic execution via APScheduler (MIT, 7.6k★) — pinned to the stable
3.x line (v4 is still pre-release upstream and explicitly marked
not-for-production). We do not hand-roll a sleep loop / cron parser: this
is exactly the kind of solved problem CLAUDE.md says not to reinvent.
"""
from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .alerts import AlertDispatcher
from .orchestrator import run_cycle
from .store import RadarStore


def build_scheduler(
    queries: list[str],
    store: RadarStore,
    dispatcher: AlertDispatcher | None,
    interval_minutes: int = 30,
    per_query_limit: int | None = None,
    alert_threshold: float = 0.5,
    on_cycle_done=None,
) -> BackgroundScheduler:
    scheduler = BackgroundScheduler()

    def _job():
        result = run_cycle(
            queries, store, dispatcher,
            per_query_limit=per_query_limit,
            alert_threshold=alert_threshold,
        )
        if on_cycle_done:
            on_cycle_done(result)

    scheduler.add_job(_job, trigger=IntervalTrigger(minutes=interval_minutes))
    return scheduler
