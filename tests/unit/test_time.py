from datetime import UTC, datetime, timedelta

import pytest

from futures_bot.domain.time import FixedClock, ReplayClock, SystemClock


def test_fixed_clock_returns_fixed_timestamp() -> None:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    clock = FixedClock(timestamp)

    assert clock.now() == timestamp
    assert clock.now().tzinfo is UTC


def test_replay_clock_can_advance() -> None:
    clock = ReplayClock(datetime(2026, 1, 1, tzinfo=UTC))

    assert clock.advance(timedelta(seconds=5)) == datetime(2026, 1, 1, 0, 0, 5, tzinfo=UTC)


def test_clocks_reject_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FixedClock(datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="timezone-aware"):
        ReplayClock(datetime(2026, 1, 1))


def test_system_clock_returns_timezone_aware_timestamp() -> None:
    assert SystemClock().now().tzinfo is UTC
