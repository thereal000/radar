from radar.signals.decision import DO_NOW, IGNORE, WATCH, decide
from radar.signals.scoring import OpportunityScore


def _score(**overrides) -> OpportunityScore:
    base = dict(
        opportunity_id="opp1",
        cluster_id="c1",
        signal_count=3,
        platforms={"twitter"},
        total_engagement=100,
        velocity=1.0,
        trend="steady",
        engagement_score=0.3,
        velocity_score=0.3,
        diversity_score=0.5,
        corroboration_score=0.3,
        recency_score=0.8,
        composite_score=0.4,
        before_tiktok_score=0.2,
        saturating=False,
        relevance_score=0.9,
        relevance_reasons=["reward_or_prize", "deadline_or_scarcity"],
        risk_score=0.05,
        risk_level="LOW",
        risk_reasons=[],
        effort_score=0.2,
        money_score=0.6,
        opportunity_score=0.45,
    )
    base.update(overrides)
    return OpportunityScore(**base)


def test_clear_low_effort_high_relevance_low_risk_is_do_now():
    score = _score()
    d = decide(score)
    assert d.tier == DO_NOW
    assert "récompense annoncée" in d.why


def test_high_risk_is_always_ignored_regardless_of_relevance():
    score = _score(
        risk_level="HIGH", risk_score=0.7,
        risk_reasons=["seed_phrase_or_private_key"],
    )
    d = decide(score)
    assert d.tier == IGNORE
    assert "demande une seed phrase / clé privée" in d.concerns


def test_off_topic_low_relevance_is_ignored():
    score = _score(relevance_score=0.2, relevance_reasons=[], opportunity_score=0.15)
    d = decide(score)
    assert d.tier == IGNORE


def test_middling_value_falls_to_watch_not_do_now():
    # decent relevance, but heavy effort and no money mention — not
    # actionable-now, but not noise either
    score = _score(effort_score=0.9, money_score=0.0, opportunity_score=0.25)
    d = decide(score)
    assert d.tier == WATCH


def test_value_score_penalizes_high_effort_and_rewards_money_mention():
    low_effort = _score(effort_score=0.1, money_score=1.0)
    high_effort = _score(effort_score=0.9, money_score=0.0)
    assert decide(low_effort).value_score > decide(high_effort).value_score


def test_off_topic_hit_forces_ignore_even_with_a_great_score():
    """Regression test for a real bug found live: a viral US-politics
    tweet with a huge dollar figure reached do_now purely off engagement
    plus one accidental relevance keyword — the OFF-TOPIC signal
    relevance.py already computes was being silently discarded instead of
    ever blocking a decision."""
    score = _score(
        relevance_reasons=["reward_or_prize", "OFF-TOPIC:us_politics_or_macro_news"],
        opportunity_score=0.9,  # deliberately huge — must not matter
        money_score=1.0,
    )
    d = decide(score)
    assert d.tier == IGNORE
    assert any("hors-sujet" in c for c in d.concerns)


def test_single_accidental_keyword_is_not_enough_for_do_now():
    """One relevance concept alone (the kind of thing a coincidental
    keyword match produces) must not clear do_now — real opportunities
    usually carry more than one opportunity-language signal at once."""
    score = _score(relevance_reasons=["reward_or_prize"], opportunity_score=0.45)
    d = decide(score)
    assert d.tier != DO_NOW


def test_lottery_style_giveaway_is_discounted_and_not_do_now():
    """A giveaway that's real but effectively a raffle (one winner picked
    from a pool) is not the guaranteed-if-you-act opportunity do_now
    promises — found live: 'ClawWar'-style selective giveaways were
    surfacing as do_now."""
    score = _score(
        representative_text="Enter to win big prizes! Winners will be randomly selected next week.",
    )
    d = decide(score)
    assert d.tier != DO_NOW
    assert any("tirage" in c or "sélection" in c for c in d.concerns)
