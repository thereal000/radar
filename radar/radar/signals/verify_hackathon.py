"""VERIFY + ENRICH stage — hackathon opportunities only, first pass.

DETECT already tagged an opportunity "hackathon_or_competition" via the
existing keyword lexicon in relevance.py — this module doesn't re-detect,
it goes one step deeper on what DECIDE already flagged as worth acting on
now, and only for those (this is a real network fetch, never run over the
whole cluster batch).

Reuses, doesn't duplicate:
  - collectors._run_opencli — the exact same OpenCLI subprocess bridge
    already used to collect X/Reddit, here used to open a URL and read its
    text instead of searching a timeline.
  - clean._URL_RE — the same URL pattern clean.py already uses (there, to
    strip links out of text; here, to find links a post mentions).
  - RapidFuzz (already a dependency) — to check the hackathon's title
    against the user's own GitHub repos via `gh repo list`.

Scope, deliberately: does a best-effort reading of ONE public page and
reports what it found in plain language ("deadline mentioned: ...", not
"verified fact"). It never logs in, accepts terms, submits anything, or
tries to get past a CAPTCHA/anti-bot check — if a fetch looks blocked, it
says so and stops, exactly like the project's action-safety rule requires:
that's the user's call, not something to automate around.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from .clean import _URL_RE
from .collectors import _run_opencli
from .scoring import OpportunityScore

_SOCIAL_DOMAINS = ("x.com", "twitter.com", "reddit.com", "news.ycombinator.com", "youtube.com", "youtu.be")

_ANTI_BOT_RE = re.compile(
    r"verify you are human|checking your browser|complete the security check|"
    r"enable javascript and cookies|unusual traffic|access denied|"
    r"are you a robot|prove you.re not a robot|attention required",
    re.I,
)

_DEADLINE_WORD_RE = re.compile(r"deadline", re.I)
_DATE_RE = re.compile(r"\d{1,2}\s+[A-Za-z]{3,9}\.?\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}")
_PRIZE_RE = re.compile(r"\$\s?[\d,]+(?:\.\d+)?(?:\s+in prizes?)?", re.I)


@dataclass
class HackathonVerification:
    checked: bool = False
    blocked: bool = False  # a fetch looked like an anti-bot/login wall — user must check by hand
    official_url: str | None = None
    deadline_text: str | None = None
    prize_text: str | None = None
    github_matches: list[dict] = field(default_factory=list)
    note: str = ""


def _is_social_platform_url(url: str) -> bool:
    return any(d in url for d in _SOCIAL_DOMAINS)


def _candidate_urls(score: OpportunityScore) -> list[str]:
    urls: list[str] = []
    if score.representative_url and not _is_social_platform_url(score.representative_url):
        urls.append(score.representative_url)
    for u in _URL_RE.findall(score.representative_text or ""):
        u = u.rstrip(").,!…")
        if u not in urls and not _is_social_platform_url(u):
            urls.append(u)
    return urls


def _fetch_page_text(url: str, session: str = "radar-verify") -> str | None:
    # document.body.innerText (not the "extract" command) — extract's
    # article-focused excerpt reliably missed the deadline/prize banner on
    # a real Devpost page during testing; innerText gets the whole visible
    # page, which is what a human skimming it would actually see.
    try:
        _run_opencli(["browser", session, "open", url], timeout=30)
        text = _run_opencli(["browser", session, "eval", "document.body.innerText"], timeout=30)
    except Exception as e:  # noqa: BLE001 - a failed fetch must not crash notification building
        print(f"[verify_hackathon] fetch failed for {url}: {e}")
        return None
    return text or None


def _looks_blocked(text: str) -> bool:
    # Short + matches an anti-bot phrase = almost certainly a challenge page,
    # not a real page that happens to mention "cloudflare" once in passing.
    return bool(text) and len(text) < 2000 and bool(_ANTI_BOT_RE.search(text))


def _own_github_matches(hackathon_hint: str, min_score: float = 60.0) -> list[dict]:
    """Same `gh` CLI already used for GitHub collection, pointed at the
    user's own repos instead of a search query — "have I already started
    something for this?" via fuzzy title/description match."""
    try:
        result = subprocess.run(
            ["gh", "repo", "list", "--limit", "100", "--json", "name,description,updatedAt,url"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
        )
        if result.returncode != 0:
            return []
        repos = json.loads(result.stdout or "[]")
    except Exception as e:  # noqa: BLE001
        print(f"[verify_hackathon] gh repo list failed: {e}")
        return []

    # token_set_ratio, not partial_ratio: partial_ratio scores a substring
    # match too generously here (e.g. "...project" alone made an unrelated
    # repo score 61 against a hint ending in "...project" — token_set_ratio
    # requires the actual word SET to overlap, not just any substring).
    hint = hackathon_hint.lower()
    matches = []
    for r in repos:
        name_score = fuzz.token_set_ratio(hint, (r.get("name") or "").lower())
        desc_score = fuzz.token_set_ratio(hint, (r.get("description") or "").lower())
        best = max(name_score, desc_score)
        if best >= min_score:
            matches.append({
                "name": r.get("name"), "url": r.get("url"),
                "updated_at": r.get("updatedAt"), "match_score": round(best, 1),
            })
    matches.sort(key=lambda m: m["match_score"], reverse=True)
    return matches


def verify_hackathon(score: OpportunityScore) -> HackathonVerification:
    if "hackathon_or_competition" not in score.relevance_reasons:
        return HackathonVerification(checked=False, note="pas taggé hackathon")

    urls = _candidate_urls(score)
    if not urls:
        return HackathonVerification(checked=True, note="aucun lien vers une page officielle trouvé dans le texte")

    for url in urls[:2]:  # don't hammer more than 2 candidate links per opportunity
        text = _fetch_page_text(url)
        if text is None:
            continue
        if _looks_blocked(text):
            return HackathonVerification(
                checked=True, blocked=True, official_url=url,
                note="page protégée (anti-bot / connexion requise) — à vérifier toi-même",
            )
        return HackathonVerification(
            checked=True,
            official_url=url,
            deadline_text=_extract_deadline(text),
            prize_text=_extract_first(_PRIZE_RE, text),
            github_matches=_own_github_matches(score.representative_text[:80]),
            note="vérifié",
        )

    return HackathonVerification(checked=True, note="lien(s) trouvé(s) mais la page n'a pas pu être chargée")


def _extract_first(pattern: re.Pattern, text: str) -> str | None:
    m = pattern.search(text)
    return m.group(0).strip() if m else None


def _extract_deadline(text: str, window: int = 60) -> str | None:
    """Scans every "deadline" mention for a date shortly after it, and
    returns just "deadline : <date>" — not the raw span in between, which
    on a real page is often nav text ("View schedule") we don't want to
    echo back."""
    for m in _DEADLINE_WORD_RE.finditer(text):
        date_m = _DATE_RE.search(text[m.end(): m.end() + window])
        if date_m:
            return f"deadline : {date_m.group(0)}"
    return None
