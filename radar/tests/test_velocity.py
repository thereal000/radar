from datetime import datetime, timedelta, timezone

from radar.signals.velocity import classify_trend, compute_velocity


def _snap(hours_ago: float, count: int) -> dict:
    ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {"snapshot_at": ts.isoformat(), "signal_count": count}


def test_compute_velocity_signals_per_hour():
    snaps = [_snap(2, 10), _snap(0, 20)]
    v = compute_velocity(snaps)
    assert abs(v - 5.0) < 0.01  # 10 new signals over ~2 hours


def test_compute_velocity_needs_two_snapshots():
    assert compute_velocity([_snap(0, 5)]) is None


def test_classify_trend_insufficient_data_below_three_points():
    assert classify_trend([_snap(1, 1), _snap(0, 2)]) == "insufficient_data"


def test_classify_trend_simple_heuristic_accelerating():
    snaps = [_snap(3, 1), _snap(2, 2), _snap(1, 3), _snap(0, 8)]
    assert classify_trend(snaps) == "accelerating"


def test_classify_trend_simple_heuristic_saturating():
    snaps = [_snap(3, 1), _snap(2, 10), _snap(1, 18), _snap(0, 19)]
    assert classify_trend(snaps) == "saturating"


def test_classify_trend_ruptures_path_on_longer_series_detects_saturation():
    """Proves the ruptures integration is wired correctly: a clearly
    accelerating-then-flat synthetic series (this radar hasn't been running
    long enough yet to produce 6+ real snapshots for one opportunity)."""
    hours = [7, 6, 5, 4, 3, 2, 1, 0]
    counts = [1, 2, 4, 8, 16, 17, 17, 17]  # steep growth, then flat plateau
    snaps = [_snap(h, c) for h, c in zip(hours, counts)]
    assert classify_trend(snaps) == "saturating"


def test_classify_trend_ruptures_path_detects_acceleration():
    hours = [6, 5, 4, 3, 2, 1, 0]
    counts = [1, 2, 3, 4, 8, 16, 30]  # flat-ish, then steep growth
    snaps = [_snap(h, c) for h, c in zip(hours, counts)]
    assert classify_trend(snaps) == "accelerating"


def test_classify_trend_does_not_crash_on_short_real_world_series():
    """Regression test for a real crash found during live observation:
    ruptures.Binseg's default jump=5 leaves no valid candidate split point
    for series shorter than ~10 points, raising BadSegmentationParameters.
    This hit in production on real opportunity histories (5 snapshots is
    the exact threshold where the ruptures path first activates)."""
    for counts in ([1, 1, 1, 1, 1], [1, 2, 3, 3, 3], [5, 4, 3, 2, 1], [1, 1, 2, 2, 2]):
        snaps = [_snap(4 - i, c) for i, c in enumerate(counts)]
        result = classify_trend(snaps)  # must not raise
        assert result in ("accelerating", "steady", "saturating")
