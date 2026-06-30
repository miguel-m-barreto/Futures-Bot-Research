from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from futures_bot.domain.ids import VenueCapabilitySourceRecordId
from futures_bot.domain.venue_capabilities import (
    VenueCapabilitySnapshot,
    VenueInstrumentRuleSnapshot,
    VenueOrderValidationContext,
)
from futures_bot.domain.venue_capability_freshness import (
    VenueCapabilityFreshnessCheck,
    VenueCapabilityFreshnessDecision,
)
from futures_bot.domain.venue_capability_resolution import (
    VenueCapabilityResolutionDecision,
    VenueCapabilityResolutionReason,
    VenueCapabilityResolutionRequest,
)
from futures_bot.ports.venue_capabilities import (
    VenueCapabilitySnapshotStorePort,
    VenueInstrumentRuleSnapshotStorePort,
)
from futures_bot.venue_capabilities.freshness import validate_venue_capability_freshness


class DeterministicVenueCapabilityResolutionGateway:
    """Resolve latest capability snapshots without clocks, network, or defaults."""

    def __init__(
        self,
        *,
        venue_snapshot_store: VenueCapabilitySnapshotStorePort,
        instrument_rule_store: VenueInstrumentRuleSnapshotStorePort,
    ) -> None:
        self._venue_snapshots = venue_snapshot_store
        self._instrument_rules = instrument_rule_store

    def resolve(
        self,
        request: VenueCapabilityResolutionRequest,
    ) -> VenueCapabilityResolutionDecision:
        if request.request_id is None:
            raise ValueError("request_id must be set before resolving capabilities")
        order = request.order_intent
        venue_snapshot = self._venue_snapshots.get_latest(order.venue_id)
        if venue_snapshot is None:
            return _decision(
                request,
                ready=False,
                reason=VenueCapabilityResolutionReason.VENUE_SNAPSHOT_MISSING,
                details={"venue_id": order.venue_id},
            )
        instrument_rules = self._instrument_rules.get_latest(
            order.venue_id,
            order.instrument_id,
        )
        if instrument_rules is None:
            return _decision(
                request,
                ready=False,
                reason=VenueCapabilityResolutionReason.INSTRUMENT_RULES_MISSING,
                venue_snapshot=venue_snapshot,
                details={
                    "venue_id": order.venue_id,
                    "instrument_id": order.instrument_id,
                },
            )

        try:
            freshness_check = VenueCapabilityFreshnessCheck(
                venue_id=order.venue_id,
                instrument_id=order.instrument_id,
                venue_snapshot=venue_snapshot,
                instrument_rules=instrument_rules,
                policy=request.freshness_policy,
                source_health=request.source_health,
                checked_at=request.checked_at,
                correlation_id=request.correlation_id,
            )
        except ValidationError as exc:
            return _decision(
                request,
                ready=False,
                reason=VenueCapabilityResolutionReason.REQUEST_VENUE_INSTRUMENT_MISMATCH,
                venue_snapshot=venue_snapshot,
                instrument_rules=instrument_rules,
                details={
                    "message": "freshness check context invalid",
                    "errors": _jsonable_errors(exc),
                },
            )
        freshness_decision = validate_venue_capability_freshness(freshness_check)
        if not freshness_decision.fresh:
            return _decision(
                request,
                ready=False,
                reason=VenueCapabilityResolutionReason.FRESHNESS_REJECTED,
                venue_snapshot=venue_snapshot,
                instrument_rules=instrument_rules,
                freshness_check=freshness_check,
                freshness_decision=freshness_decision,
                details={
                    "freshness_reason": freshness_decision.reason.value,
                    "freshness_details": freshness_decision.details,
                },
            )

        try:
            venue_validation_context = VenueOrderValidationContext(
                order_intent=order,
                venue_snapshot=venue_snapshot,
                instrument_rules=instrument_rules,
                requested_at=request.checked_at,
            )
        except ValidationError as exc:
            return _decision(
                request,
                ready=False,
                reason=VenueCapabilityResolutionReason.VENUE_VALIDATION_CONTEXT_INVALID,
                venue_snapshot=venue_snapshot,
                instrument_rules=instrument_rules,
                freshness_check=freshness_check,
                freshness_decision=freshness_decision,
                details={
                    "message": "venue validation context invalid",
                    "errors": _jsonable_errors(exc),
                },
            )

        return _decision(
            request,
            ready=True,
            reason=VenueCapabilityResolutionReason.READY,
            venue_snapshot=venue_snapshot,
            instrument_rules=instrument_rules,
            freshness_check=freshness_check,
            freshness_decision=freshness_decision,
            venue_validation_context=venue_validation_context,
            venue_source_record_id=venue_snapshot.source_record_id,
            instrument_source_record_ids=(
                (instrument_rules.source_record_id,)
                if instrument_rules.source_record_id is not None
                else ()
            ),
            details={
                "venue_snapshot_id": str(venue_snapshot.snapshot_id),
                "instrument_rule_snapshot_id": str(instrument_rules.snapshot_id),
                "freshness_reason": freshness_decision.reason.value,
            },
        )


def _decision(  # noqa: PLR0913
    request: VenueCapabilityResolutionRequest,
    *,
    ready: bool,
    reason: VenueCapabilityResolutionReason,
    details: Any,
    venue_snapshot: VenueCapabilitySnapshot | None = None,
    instrument_rules: VenueInstrumentRuleSnapshot | None = None,
    freshness_check: VenueCapabilityFreshnessCheck | None = None,
    freshness_decision: VenueCapabilityFreshnessDecision | None = None,
    venue_validation_context: VenueOrderValidationContext | None = None,
    venue_source_record_id: VenueCapabilitySourceRecordId | None = None,
    instrument_source_record_ids: tuple[VenueCapabilitySourceRecordId, ...] = (),
) -> VenueCapabilityResolutionDecision:
    if request.request_id is None:
        raise ValueError("request_id is required")
    return VenueCapabilityResolutionDecision(
        request_id=request.request_id,
        ready=ready,
        reason=reason,
        venue_snapshot=venue_snapshot,
        instrument_rules=instrument_rules,
        freshness_check=freshness_check,
        freshness_decision=freshness_decision,
        venue_validation_context=venue_validation_context,
        venue_source_record_id=venue_source_record_id,
        instrument_source_record_ids=instrument_source_record_ids,
        checked_at=request.checked_at,
        details=details,
    )


def _jsonable_errors(exc: ValidationError) -> list[dict[str, Any]]:
    return [
        {
            "type": str(error.get("type")),
            "loc": [str(item) for item in error.get("loc", ())],
            "msg": str(error.get("msg")),
        }
        for error in exc.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        )
    ]
