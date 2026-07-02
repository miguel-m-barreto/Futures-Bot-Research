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
from futures_bot.domain.venue_capability_sources import (
    VenueCapabilitySourceHealthStatus,
    VenueCapabilitySourceRecord,
    VenueCapabilitySourceTrust,
)
from futures_bot.ports.venue_capabilities import (
    VenueCapabilitySnapshotStorePort,
    VenueInstrumentRuleSnapshotStorePort,
)
from futures_bot.ports.venue_capability_sources import (
    VenueCapabilitySourceRecordStorePort,
)
from futures_bot.venue_capabilities.freshness import validate_venue_capability_freshness


class DeterministicVenueCapabilityResolutionGateway:
    """Resolve latest capability snapshots without clocks, network, or defaults."""

    def __init__(
        self,
        *,
        venue_snapshot_store: VenueCapabilitySnapshotStorePort,
        instrument_rule_store: VenueInstrumentRuleSnapshotStorePort,
        source_record_store: VenueCapabilitySourceRecordStorePort | None = None,
    ) -> None:
        self._venue_snapshots = venue_snapshot_store
        self._instrument_rules = instrument_rule_store
        self._source_records = source_record_store

    def resolve(  # noqa: PLR0911
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

        provenance_result = _validate_required_provenance(
            request=request,
            venue_snapshot=venue_snapshot,
            instrument_rules=instrument_rules,
            source_record_store=self._source_records,
        )
        if provenance_result is not None:
            return _decision(
                request,
                ready=False,
                reason=provenance_result.reason,
                venue_snapshot=venue_snapshot,
                instrument_rules=instrument_rules,
                freshness_check=freshness_check,
                freshness_decision=freshness_decision,
                venue_source_record_id=venue_snapshot.source_record_id,
                instrument_source_record_ids=(
                    (instrument_rules.source_record_id,)
                    if instrument_rules.source_record_id is not None
                    else ()
                ),
                provenance_checked=True,
                provenance_reason=provenance_result.reason.value,
                provenance_details=provenance_result.details,
                details={
                    "freshness_reason": freshness_decision.reason.value,
                    "provenance_reason": provenance_result.reason.value,
                    "provenance_details": provenance_result.details,
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
            provenance_checked=request.require_official_source_provenance,
            provenance_reason=(
                "PROVENANCE_OK"
                if request.require_official_source_provenance
                else None
            ),
            provenance_details=(
                {
                    "venue_source_record_id": str(venue_snapshot.source_record_id),
                    "instrument_source_record_ids": [
                        str(instrument_rules.source_record_id)
                    ],
                }
                if request.require_official_source_provenance
                else None
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
    provenance_checked: bool = False,
    provenance_reason: str | None = None,
    provenance_details: Any | None = None,
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
        provenance_checked=provenance_checked,
        provenance_reason=provenance_reason,
        provenance_details=provenance_details,
        checked_at=request.checked_at,
        details=details,
    )


class _ProvenanceFailure:
    def __init__(
        self,
        *,
        reason: VenueCapabilityResolutionReason,
        details: dict[str, Any],
    ) -> None:
        self.reason = reason
        self.details = details


def _validate_required_provenance(
    *,
    request: VenueCapabilityResolutionRequest,
    venue_snapshot: VenueCapabilitySnapshot,
    instrument_rules: VenueInstrumentRuleSnapshot,
    source_record_store: VenueCapabilitySourceRecordStorePort | None,
) -> _ProvenanceFailure | None:
    if not request.require_official_source_provenance:
        return None
    venue_failure = _validate_snapshot_source_record(
        label="venue_snapshot",
        venue_id=venue_snapshot.venue_id,
        source_record_id=venue_snapshot.source_record_id,
        source_payload_hash=venue_snapshot.source_payload_hash,
        source_record_store=source_record_store,
    )
    if venue_failure is not None:
        return venue_failure
    rule_failure = _validate_snapshot_source_record(
        label="instrument_rules",
        venue_id=instrument_rules.venue_id,
        source_record_id=instrument_rules.source_record_id,
        source_payload_hash=instrument_rules.source_payload_hash,
        source_record_store=source_record_store,
    )
    if rule_failure is not None:
        return rule_failure
    return None


def _validate_snapshot_source_record(
    *,
    label: str,
    venue_id: str,
    source_record_id: VenueCapabilitySourceRecordId | None,
    source_payload_hash: str | None,
    source_record_store: VenueCapabilitySourceRecordStorePort | None,
) -> _ProvenanceFailure | None:
    if source_record_id is None or source_payload_hash is None:
        return _provenance_failure(
            reason=VenueCapabilityResolutionReason.SOURCE_PROVENANCE_REQUIRED,
            label=label,
            details={"missing": _missing_provenance_fields(source_record_id, source_payload_hash)},
        )
    if source_record_store is None:
        return _provenance_failure(
            reason=VenueCapabilityResolutionReason.SOURCE_RECORD_MISSING,
            label=label,
            source_record_id=source_record_id,
            details={"message": "source record store is not configured"},
        )
    source_record = source_record_store.get(source_record_id)
    if source_record is None:
        return _provenance_failure(
            reason=VenueCapabilityResolutionReason.SOURCE_RECORD_MISSING,
            label=label,
            source_record_id=source_record_id,
            details={},
        )
    return _validate_source_record_authority(
        label=label,
        venue_id=venue_id,
        source_payload_hash=source_payload_hash,
        source_record=source_record,
    )


def _validate_source_record_authority(  # noqa: PLR0911
    *,
    label: str,
    venue_id: str,
    source_payload_hash: str,
    source_record: VenueCapabilitySourceRecord,
) -> _ProvenanceFailure | None:
    if source_record.record_id is None:
        return _provenance_failure(
            reason=VenueCapabilityResolutionReason.SOURCE_PROVENANCE_INVALID,
            label=label,
            details={"message": "source record has no record_id"},
        )
    if source_record.descriptor.venue_id != venue_id:
        return _provenance_failure(
            reason=VenueCapabilityResolutionReason.SOURCE_VENUE_MISMATCH,
            label=label,
            source_record_id=source_record.record_id,
            details={
                "snapshot_venue_id": venue_id,
                "source_venue_id": source_record.descriptor.venue_id,
            },
        )
    if source_record.descriptor.trust is not VenueCapabilitySourceTrust.OFFICIAL:
        return _provenance_failure(
            reason=VenueCapabilityResolutionReason.SOURCE_RECORD_NOT_OFFICIAL,
            label=label,
            source_record_id=source_record.record_id,
            details={"source_trust": source_record.descriptor.trust.value},
        )
    if source_record.health_status is not VenueCapabilitySourceHealthStatus.HEALTHY:
        return _provenance_failure(
            reason=VenueCapabilityResolutionReason.SOURCE_RECORD_NOT_HEALTHY,
            label=label,
            source_record_id=source_record.record_id,
            details={"source_health_status": source_record.health_status.value},
        )
    if not source_record.accepted_for_execution:
        return _provenance_failure(
            reason=VenueCapabilityResolutionReason.SOURCE_RECORD_NOT_ACCEPTED,
            label=label,
            source_record_id=source_record.record_id,
            details={"source_record_reason": source_record.reason.value},
        )
    if source_payload_hash != source_record.payload.payload_hash:
        return _provenance_failure(
            reason=VenueCapabilityResolutionReason.SOURCE_PAYLOAD_HASH_MISMATCH,
            label=label,
            source_record_id=source_record.record_id,
            details={
                "snapshot_source_payload_hash": source_payload_hash,
                "source_payload_hash": source_record.payload.payload_hash,
            },
        )
    return None


def _provenance_failure(
    *,
    reason: VenueCapabilityResolutionReason,
    label: str,
    details: dict[str, Any],
    source_record_id: VenueCapabilitySourceRecordId | None = None,
) -> _ProvenanceFailure:
    payload: dict[str, Any] = {"snapshot_kind": label}
    if source_record_id is not None:
        payload["source_record_id"] = str(source_record_id)
    payload.update(details)
    return _ProvenanceFailure(reason=reason, details=payload)


def _missing_provenance_fields(
    source_record_id: VenueCapabilitySourceRecordId | None,
    source_payload_hash: str | None,
) -> list[str]:
    missing: list[str] = []
    if source_record_id is None:
        missing.append("source_record_id")
    if source_payload_hash is None:
        missing.append("source_payload_hash")
    return missing


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
