from radar.signals.relevance import compute_relevance


def test_real_opportunity_language_scores_meaningfully_higher_than_baseline():
    score, reasons = compute_relevance(
        "10,000 CREDITS fully free, create a new account and get 1 month of free subscription"
    )
    assert score > 0.3
    assert "credits_or_allocation" in reasons or "free_access" in reasons


def test_airdrop_language_is_relevant_regardless_of_trustworthiness():
    """Relevance measures TOPICAL fit, not trustworthiness — that's risk's
    job. A scammy-looking airdrop post is still, textually, about an
    airdrop."""
    score, reasons = compute_relevance("Submit Your SOL Wallet Address, Only First 2k #Airdrop #SOL")
    assert score > 0.3
    assert "airdrop_or_distribution" in reasons


def test_political_content_scores_low_not_high():
    """Regression test for the real false positive found in observation:
    off-topic political content had the HIGHEST before_tiktok score
    (0.322) in the whole session, because nothing checked relevance."""
    score, reasons = compute_relevance(
        "THE CONSPIRACY THEORISTS WERE RIGHT! Australian citizens will need 100 social "
        "credit score points from their digital ID to access social media"
    )
    assert score < 0.15
    assert any(r.startswith("OFF-TOPIC:") for r in reasons)


def test_us_macro_politics_with_big_dollar_figure_scores_low_not_high():
    """Real false positive found live: a viral US-politics tweet with a
    huge dollar figure and an accidental keyword match ("bonus") reached
    do_now purely off engagement + that one accidental hit. The content
    itself has to be flagged as noise regardless of what numbers are in it."""
    score, reasons = compute_relevance(
        "BREAKING: Congress passes $95 billion stimulus package, includes a one-time bonus for federal workers"
    )
    assert score < 0.3
    assert any(r.startswith("OFF-TOPIC:") for r in reasons)


def test_generic_short_comment_scores_low():
    score, reasons = compute_relevance("Good point.")
    assert score < 0.2
    assert reasons == []


def test_empty_text_scores_low():
    score, reasons = compute_relevance("")
    assert score < 0.2
