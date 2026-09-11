from __future__ import annotations

from dataclasses import dataclass

from .alerts import AlertDispatcher
from .pipeline import run_pipeline
from .scoring import OpportunityScore, score_opportunity
from .store import RadarStore


@dataclass
class CycleResult:
    run_id: str
    raw_count: int
    signal_count: int
    cluster_count: int
    scores: list[OpportunityScore]
    alerts_sent: int


def run_cycle(
    queries: list[str],
    store: RadarStore,
    dispatcher: AlertDispatcher | None = None,
    per_query_limit: int | None = None,
    alert_threshold: float = 0.35,
) -> CycleResult:
    """One full COLLECT -> ... -> CLUSTER -> PERSIST -> SCORE -> ALERT cycle."""
    pipeline_result = run_pipeline(queries, per_query_limit=per_query_limit)
    cluster_to_opportunity, run_id, new_opportunity_ids = store.persist_run(pipeline_result.clusters)

    scores: list[OpportunityScore] = []
    scored_for_alerts: list[tuple[OpportunityScore, str]] = []
    for cluster in pipeline_result.clusters:
        opp_id = cluster_to_opportunity[cluster.cluster_id]
        snapshots = store.get_snapshots(opp_id)
        score = score_opportunity(cluster, opp_id, snapshots)
        score.is_new = opp_id in new_opportunity_ids
        scores.append(score)
        scored_for_alerts.append((score, cluster.representative.text or cluster.representative.title or ""))

    alerts_sent = 0
    if dispatcher is not None:
        cooldown_ok = [
            (score, text) for score, text in scored_for_alerts
            if store.should_alert(score.opportunity_id, score.opportunity_score)
        ]
        sent = dispatcher.dispatch_top_opportunities(cooldown_ok, threshold=alert_threshold)
        for score in sent:
            store.mark_alerted(score.opportunity_id, score.opportunity_score)
        alerts_sent = len(sent)

    return CycleResult(
        run_id=run_id,
        raw_count=pipeline_result.raw_count,
        signal_count=pipeline_result.unique_signal_count,
        cluster_count=pipeline_result.cluster_count,
        scores=scores,
        alerts_sent=alerts_sent,
    )
