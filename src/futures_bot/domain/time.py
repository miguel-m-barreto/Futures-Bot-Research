from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current clock timestamp."""
        ...


def ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    def __init__(self, fixed_at: datetime) -> None:
        self._fixed_at = ensure_aware_utc(fixed_at)

    def now(self) -> datetime:
        return self._fixed_at


class ReplayClock:
    def __init__(self, starting_at: datetime) -> None:
        self._current = ensure_aware_utc(starting_at)

    def now(self) -> datetime:
        return self._current

    def advance(self, delta: timedelta) -> datetime:
        self._current = ensure_aware_utc(self._current + delta)
        return self._current
