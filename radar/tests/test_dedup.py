from radar.signals.dedup import build_minhash, extract_entities, find_duplicate_pairs
from radar.signals.clean import normalized_for_dedup
from radar.signals.normalize import normalize_reddit_post, normalize_twitter_post


def _tweet(id_, text, url=None):
    return normalize_twitter_post(
        {
            "id": id_,
            "author": f"user{id_}",
            "text": text,
            "created_at": "Wed Sep 02 19:33:47 +0000 2026",
            "likes": 1,
            "views": "10",
            "url": url or f"https://x.com/i/status/{id_}",
            "_collector_query": "test",
        }
    )


def _reddit(id_, title, selftext, url="https://www.reddit.com/r/x/comments/x/x/"):
    return normalize_reddit_post(
        {
            "id": id_,
            "title": title,
            "subreddit": "r/x",
            "author": "u",
            "score": 1,
            "comments": 0,
            "url": url,
            "created_utc": 1725000000,
            "selftext": selftext,
            "_collector_query": "test",
        }
    )


def test_extract_entities_finds_money_and_capitalized_phrases():
    ents = extract_entities("Join the ProjectX Hackathon for a $500 USDC reward")
    assert any("500" in e for e in ents)
    assert any("hackathon" in e or "projectx" in e for e in ents)


def test_minhash_jaccard_high_for_near_identical_text():
    a = normalized_for_dedup("Huge airdrop from ProjectX, claim your free 500 USDC now")
    b = normalized_for_dedup("Huge airdrop from ProjectX claim your free 500 USDC today")
    mh_a, mh_b = build_minhash(a), build_minhash(b)
    assert mh_a.jaccard(mh_b) > 0.3


def test_find_duplicate_pairs_flags_near_duplicate_reddit_posts():
    s1 = _reddit("p1", "ProjectX airdrop live now", "Claim your free 500 USDC from ProjectX before it ends")
    s2 = _reddit(
        "p2",
        "ProjectX airdrop is live",
        "Claim your free 500 USDC from ProjectX before it's gone",
        url="https://www.reddit.com/r/y/comments/y/y/",
    )
    s3 = _reddit("p3", "Best pizza recipe", "Here is how to make a great pizza at home", url="https://www.reddit.com/r/food/comments/z/z/")

    evidence = find_duplicate_pairs([s1, s2, s3])
    dup_pairs = {(e.a_id, e.b_id) for e in evidence if e.is_duplicate}

    assert ("reddit:p1", "reddit:p2") in dup_pairs or ("reddit:p2", "reddit:p1") in dup_pairs
    assert not any("p3" in a or "p3" in b for a, b in dup_pairs)


def test_bare_link_tweets_are_not_falsely_clustered_as_duplicates():
    """Regression test: two DIFFERENT tweets whose entire body is just a
    link (no caption) both normalize to empty dedup-text. An un-updated
    MinHash trivially reports jaccard=1.0 against another un-updated
    MinHash, which used to cause every link-only tweet in a batch to be
    treated as a duplicate of every other one, regardless of content."""
    a = _tweet("l1", "https://t.co/aaaaaaaaaa")
    b = _tweet("l2", "https://t.co/bbbbbbbbbb")
    c = _tweet("l3", "https://t.co/cccccccccc")

    evidence = find_duplicate_pairs([a, b, c])
    assert not any(e.is_duplicate for e in evidence)


def test_short_generic_text_not_falsely_matched_to_unrelated_long_text():
    """Regression test for a real bug found during live observation:
    rapidfuzz's token_set_ratio scored a 6-word Reddit title ("What is left
    at this point?") as 89% similar to two completely unrelated long tweets
    (400+ words each), purely because the short text's common words
    ("what", "is", "at") happen to appear somewhere in the long text. This
    caused 3 unrelated real posts to be merged into one fake "opportunity"
    in production. minhash_jaccard correctly showed ~0 similarity; the fix
    requires fuzzy_ratio to be corroborated by comparable text length."""
    short = _reddit("short1", "What is left at this point?", "")
    long_unrelated_a = _reddit(
        "long1",
        "x",
        "codex users do this for astra or gpt six just point at it before its too late "
        * 20,
    )
    long_unrelated_b = _reddit(
        "long2",
        "y",
        "a creator strategist dropped the full roadmap on how one person built a "
        * 20,
    )

    evidence = find_duplicate_pairs([short, long_unrelated_a, long_unrelated_b])
    assert not any(e.is_duplicate for e in evidence)
