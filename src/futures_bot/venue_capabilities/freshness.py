from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from futures_bot.domain.venue_capability_freshness import (
    CapabilityFreshnessDecisionReason,
    CapabilityFreshnessMode,
    CapabilitySourceHealth,
    VenueCapabilityFreshnessCheck,
    VenueCapabilityFreshnessDecision,
)


def validate_venue_capability_freshness(  # noqa: PLR0911, PLR0912
    check: VenueCapabilityFreshnessCheck,
) -> VenueCapabilityFreshnessDecision:
    """Validate explicit capability snapshots without clocks or external reads."""

    if check.check_id is None:
        raise ValueError("check_id must be set before freshness validation")

    policy = check.policy
    if policy.mode is CapabilityFreshnessMode.DISABLED:
        return _decision(
            check,
            fresh=True,
            reason=CapabilityFreshnessDecisionReason.POLICY_DISABLED,
            details={"message": "venue capability freshness policy disabled"},
        )

    venue = check.venue_snapshot
    rules = check.instrument_rules
    if policy.require_venue_snapshot and venue is None:
        return _decision(
            check,
            fresh=False,
            reason=CapabilityFreshnessDecisionReason.VENUE_SNAPSHOT_MISSING,
            details={"venue_id": check.venue_id},
        )
    if policy.require_instrument_rules and rules is None:
        return _decision(
            check,
            fresh=False,
            reason=CapabilityFreshnessDecisionReason.INSTRUMENT_RULES_MISSING,
            details={"venue_id": check.venue_id, "instrument_id": check.instrument_id},
        )
    if venue is not None and venue.venue_id != check.venue_id:
        return _decision(
            check,
            fresh=False,
            reason=CapabilityFreshnessDecisionReason.VENUE_ID_MISMATCH,
            details={"expected": check.venue_id, "actual": venue.venue_id},
        )
    if rules is not None and rules.venue_id != check.venue_id:
        return _decision(
            check,
            fresh=False,
            reason=CapabilityFreshnessDecisionReason.VENUE_ID_MISMATCH,
            details={"expected": check.venue_id, "actual": rules.venue_id},
        )
    if rules is not None and rules.instrument_id != check.instrument_id:
        return _decision(
            check,
            fresh=False,
            reason=CapabilityFreshnessDecisionReason.INSTRUMENT_ID_MISMATCH,
            details={"expected": check.instrument_id, "actual": rules.instrument_id},
        )
    if check.source_health is CapabilitySourceHealth.UNAVAILABLE:
        return _decision(
            check,
            fresh=False,
            reason=CapabilityFreshnessDecisionReason.SOURCE_HEALTH_UNAVAILABLE,
            details={"source_health": check.source_health.value},
        )
    if (
        check.source_health is CapabilitySourceHealth.UNKNOWN
        and policy.reject_unknown_source
    ):
        return _decision(
            check,
            fresh=False,
            reason=CapabilityFreshnessDecisionReason.SOURCE_HEALTH_UNKNOWN,
            details={"source_health": check.source_health.value},
        )
    if (
        check.source_health is CapabilitySourceHealth.DEGRADED
        and policy.reject_degraded_source
    ):
        return _decision(
            check,
            fresh=False,
            reason=CapabilityFreshnessDecisionReason.SOURCE_HEALTH_DEGRADED,
            details={"source_health": check.source_health.value},
        )

    max_future = check.checked_at + timedelta(milliseconds=policy.max_clock_skew_ms)
    if policy.reject_future_snapshots and venue is not None and venue.captured_at > max_future:
        return _decision(
            check,
            fresh=False,
            reason=CapabilityFreshnessDecisionReason.VENUE_SNAPSHOT_FROM_FUTURE,
            details={
                "captured_at": venue.captured_at.isoformat(),
                "checked_at": check.checked_at.isoformat(),
                "max_clock_skew_ms": policy.max_clock_skew_ms,
            },
        )
    if policy.reject_future_snapshots and rules is not None and rules.captured_at > max_future:
        return _decision(
            check,
            fresh=False,
            reason=CapabilityFreshnessDecisionReason.INSTRUMENT_RULES_FROM_FUTURE,
            details={
                "captured_at": rules.captured_at.isoformat(),
                "checked_at": check.checked_at.isoformat(),
                "max_clock_skew_ms": policy.max_clock_skew_ms,
            },
        )

    venue_age_ms = _age_ms(check, venue.captured_at) if venue is not None else None
    rules_age_ms = _age_ms(check, rules.captured_at) if rules is not None else None
    if venue_age_ms is not None and venue_age_ms > policy.max_venue_snapshot_age_ms:
        return _decision(
            check,
            fresh=False,
            reason=CapabilityFreshnessDecisionReason.VENUE_SNAPSHOT_STALE,
            venue_snapshot_age_ms=venue_age_ms,
            instrument_rules_age_ms=rules_age_ms,
            details={
                "max_venue_snapshot_age_ms": policy.max_venue_snapshot_age_ms,
                "venue_snapshot_age_ms": venue_age_ms,
            },
        )
    if rules_age_ms is not None and rules_age_ms > policy.max_instrument_rules_age_ms:
        return _decision(
            check,
            fresh=False,
            reason=CapabilityFreshnessDecisionReason.INSTRUMENT_RULES_STALE,
            venue_snapshot_age_ms=venue_age_ms,
            instrument_rules_age_ms=rules_age_ms,
            details={
                "max_instrument_rules_age_ms": policy.max_instrument_rules_age_ms,
                "instrument_rules_age_ms": rules_age_ms,
            },
        )

    details: dict[str, Any] = {"source_health": check.source_health.value}
    if venue is not None and rules is not None:
        details["snapshot_capture_delta_ms"] = int(
            (rules.captured_at - venue.captured_at).total_seconds() * 1000
        )
    return _decision(
        check,
        fresh=True,
        reason=CapabilityFreshnessDecisionReason.FRESH,
        venue_snapshot_age_ms=venue_age_ms,
        instrument_rules_age_ms=rules_age_ms,
        details=details,
    )


def _decision(  # noqa: PLR0913
    check: VenueCapabilityFreshnessCheck,
    *,
    fresh: bool,
    reason: CapabilityFreshnessDecisionReason,
    details: Any,
    venue_snapshot_age_ms: int | None = None,
    instrument_rules_age_ms: int | None = None,
) -> VenueCapabilityFreshnessDecision:
    if check.check_id is None:
        raise ValueError("check_id is required")
    return VenueCapabilityFreshnessDecision(
        check_id=check.check_id,
        fresh=fresh,
        reason=reason,
        venue_snapshot_age_ms=venue_snapshot_age_ms,
        instrument_rules_age_ms=instrument_rules_age_ms,
        source_health=check.source_health,
        checked_at=check.checked_at,
        details=details,
    )


def _age_ms(check: VenueCapabilityFreshnessCheck, captured_at: datetime) -> int:
    delta = check.checked_at - captured_at
    return max(0, int(delta.total_seconds() * 1000))
