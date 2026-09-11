"""Domain-specific text cleaning for RADAR.

Deliberately small and dependency-free: generic HTML/boilerplate stripping
is not needed because OpenCLI already returns structured text fields (no
raw HTML to scrape). This is the "unique to our radar" layer per
CLAUDE.md — not a reimplementation of an existing library's job.
"""
from __future__ import annotations

import html
import re
import unicodedata

_URL_RE = re.compile(r"https?://\S+")
_WHITESPACE_RE = re.compile(r"\s+")
_MENTION_RE = re.compile(r"@\w+")


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = unicodedata.normalize("NFKC", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def normalized_for_dedup(text: str | None) -> str:
    """Aggressively strips volatile tokens (URLs, @mentions, casing, punctuation)
    so near-duplicate comparison focuses on actual content."""
    text = clean_text(text)
    text = _URL_RE.sub(" ", text)
    text = _MENTION_RE.sub(" ", text)
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text
