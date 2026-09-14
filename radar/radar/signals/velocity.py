"""Velocity + saturation state, built on top of `ruptures` (BSD-2-Clause,
2.1k★, mature offline change-point detection library) for trend
segmentation. We reuse ruptures for the actual signal-processing math
(splitting a time series into "regimes") rather than hand-rolling change
detection — but the interpretation of what a regime change MEANS for an
opportunity (accelerating / steady / saturating) is radar-specific and
written here.

With few snapshots (normal in the early life of any opportunity, and of
this radar itself — it only started running today) ruptures has nothing
meaningful to fit, so we fall back to a simple two-point slope comparison.
Both paths are exercised by tests; the ruptures path is proven on a
synthetic longer series (this radar has not been running long enough yet
to accumulate that much real history for a single opportunity).
"""
from __future__ import annotations

from datetime import datetime


def _parse_or_none(ts):
    """Best-effort ISO parsing: never raise on a malformed / non-string
    timestamp (found by fuzzing — fromisoformat raises TypeError, not
    ValueError, on a non-string, which used to escape the ValueError-only
    guards and abort the cycle)."""
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def compute_velocity(snapshots: list[dict]) -> float | None:
    """Signals-per-hour growth rate between the two most recent snapshots."""
    if len(snapshots) < 2:
        return None
    prev, last = snapshots[-2], snapshots[-1]
    prev_at, last_at = _parse_or_none(prev.get("snapshot_at")), _parse_or_none(last.get("snapshot_at"))
    if prev_at is None or last_at is None:
        return None
    dt_hours = (last_at - prev_at).total_seconds() / 3600
    if dt_hours <= 0:
        return None
    return (last["signal_count"] - prev["signal_count"]) / dt_hours


def classify_trend(snapshots: list[dict]) -> str:
    """Returns one of: insufficient_data, accelerating, steady, saturating."""
    counts = [s["signal_count"] for s in snapshots]
    if len(counts) < 3:
        return "insufficient_data"

    if not all(isinstance(c, int) for c in counts):
        return "insufficient_data"

    if len(counts) >= 5:
        return _classify_with_ruptures(counts)
    return _classify_simple(counts)


def _classify_simple(counts: list[int]) -> str:
    delta_recent = counts[-1] - counts[-2]
    delta_prev = counts[-2] - counts[-3]
    if delta_prev <= 0:
        return "accelerating" if delta_recent > 0 else "steady"
    ratio = delta_recent / delta_prev
    if ratio >= 1.2:
        return "accelerating"
    if ratio <= 0.5:
        return "saturating"
    return "steady"


def _classify_with_ruptures(counts: list[int]) -> str:
    import numpy as np
    import ruptures as rpt

    signal = np.array(counts, dtype=float)
    # jump=1 (default is 5): Binseg only considers candidate split points at
    # multiples of `jump`. With short series (this radar's real snapshot
    # histories are currently 5-10 points long) the default leaves NO valid
    # candidate at all, and predict() raises BadSegmentationParameters —
    # hit for real on live data. jump=1 evaluates every possible split,
    # which is fine at our scale (tens of points, not millions).
    algo = rpt.Binseg(model="l2", jump=1).fit(signal)
    try:
        bkps = algo.predict(n_bkps=1)  # [split_index, len(signal)]
    except rpt.exceptions.BadSegmentationParameters:
        return _classify_simple(counts)
    split = bkps[0]
    if split <= 0 or split >= len(counts):
        return _classify_simple(counts)

    before = signal[:split]
    after = signal[split:]
    slope_before = (before[-1] - before[0]) / max(len(before) - 1, 1)
    slope_after = (after[-1] - after[0]) / max(len(after) - 1, 1)

    if slope_before <= 0:
        return "accelerating" if slope_after > 0 else "steady"
    ratio = slope_after / slope_before
    if ratio >= 1.2:
        return "accelerating"
    if ratio <= 0.5:
        return "saturating"
    return "steady"
