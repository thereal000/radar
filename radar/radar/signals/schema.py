from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Signal:
    source: str  # "twitter" | "reddit"
    source_id: str
    url: str
    author: str
    published_at: str | None  # ISO 8601
    collected_at: str  # ISO 8601
    title: str | None
    text: str
    platform: str  # duplicate of source, kept distinct per spec (e.g. future sub-platforms)
    engagement: dict[str, int | None] = field(default_factory=dict)
    subreddit: str | None = None
    media: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # filled in by clean/normalize/dedup stages
    canonical_url: str | None = None
    normalized_text: str | None = None
    content_hash: str | None = None
    cluster_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
