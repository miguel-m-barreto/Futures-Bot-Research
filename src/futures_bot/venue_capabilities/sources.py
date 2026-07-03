from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from futures_bot.domain.ids import VenueCapabilitySourceRecordId
from futures_bot.domain.venue_capabilities import (
    VenueCapabilitySnapshot,
    VenueInstrumentRuleSnapshot,
)
from futures_bot.domain.venue_capability_sources import (
    VenueCapabilityManualImport,
    VenueCapabilityManualImportDecision,
    VenueCapabilityManualImportDecisionReason,
    VenueCapabilityManualImportRequest,
    VenueCapabilitySourceHealthStatus,
    VenueCapabilitySourceKind,
    VenueCapabilitySourceRecord,
    VenueCapabilitySourceRecordReason,
    VenueCapabilitySourceTrust,
)
from futures_bot.ports.venue_capabilities import (
    VenueCapabilitySnapshotStorePort,
    VenueInstrumentRuleSnapshotStorePort,
)
from futures_bot.ports.venue_capability_sources import (
    VenueCapabilityManualImportStorePort,
    VenueCapabilitySourceRecordStorePort,
)


def ensure_source_record_accepted_for_execution(
    record: VenueCapabilitySourceRecord,
) -> VenueCapabilitySourceRecord:
    """Return an accepted official source record or raise a deterministic error."""
    if not record.accepted_for_execution:
        raise ValueError("source record is not accepted for execution")
    if record.reason is not VenueCapabilitySourceRecordReason.ACCEPTED:
        raise ValueError("source record accepted_for_execution requires ACCEPTED reason")
    if record.descriptor.trust is not VenueCapabilitySourceTrust.OFFICIAL:
        raise ValueError("source record accepted_for_execution requires OFFICIAL trust")
    if record.descriptor.source_kind is VenueCapabilitySourceKind.UNKNOWN:
        raise ValueError("source record accepted_for_execution rejects UNKNOWN source_kind")
    if record.health_status is not VenueCapabilitySourceHealthStatus.HEALTHY:
        raise ValueError("source record accepted_for_execution requires HEALTHY status")
    return record


def validate_manual_official_import(
    manual_import: VenueCapabilityManualImport,
) -> VenueCapabilityManualImport:
    """Return a validated deterministic manual import contract."""
    ensure_source_record_accepted_for_execution(manual_import.source_record)
    return manual_import


class DeterministicVenueCapabilityManualImportGateway:
    """All-or-nothing gateway for manual official source-backed imports."""

    def __init__(
        self,
        *,
        source_record_store: VenueCapabilitySourceRecordStorePort,
        venue_snapshot_store: VenueCapabilitySnapshotStorePort,
        instrument_rule_store: VenueInstrumentRuleSnapshotStorePort,
        manual_import_store: VenueCapabilityManualImportStorePort,
    ) -> None:
        self._source_records = source_record_store
        self._venue_snapshots = venue_snapshot_store
        self._instrument_rules = instrument_rule_store
        self._manual_imports = manual_import_store

    def import_capabilities(
        self,
        request: VenueCapabilityManualImportRequest,
    ) -> VenueCapabilityManualImportDecision:
        if request.request_id is None:
            raise ValueError("request_id must be set before importing capabilities")
        if request.venue_snapshot is None and not request.instrument_rules:
            return _decision(
                request,
                accepted=False,
                reason=VenueCapabilityManualImportDecisionReason.NO_SNAPSHOTS_PROVIDED,
                details={"message": "at least one snapshot is required"},
            )

        source_failure = _validate_source_record(request.source_record)
        if source_failure is not None:
            return _decision(
                request,
                accepted=False,
                reason=source_failure,
                details={"source_record_id": _source_record_id_value(request.source_record)},
            )

        provenance_failure = _validate_request_provenance(request)
        if provenance_failure is not None:
            return _decision(
                request,
                accepted=False,
                reason=provenance_failure.reason,
                details=provenance_failure.details,
            )

        try:
            manual_import = VenueCapabilityManualImport(
                source_record=request.source_record,
                venue_snapshot=request.venue_snapshot,
                instrument_rules=request.instrument_rules,
                imported_at=request.imported_at,
                imported_by=request.imported_by,
                details=request.details,
            )
        except ValidationError as exc:
            return _decision(
                request,
                accepted=False,
                reason=VenueCapabilityManualImportDecisionReason.VALIDATION_FAILED,
                details={"errors": _jsonable_errors(exc)},
            )

        conflict = self._preflight_conflicts(request, manual_import)
        if conflict is not None:
            return _decision(
                request,
                accepted=False,
                reason=conflict.reason,
                details=conflict.details,
            )

        self._source_records.put(request.source_record)
        if request.venue_snapshot is not None:
            self._venue_snapshots.put(request.venue_snapshot)
        for rule in request.instrument_rules:
            self._instrument_rules.put(rule)
        self._manual_imports.put(manual_import)

        return _decision(
            request,
            accepted=True,
            reason=VenueCapabilityManualImportDecisionReason.ACCEPTED,
            manual_import=manual_import,
            details={
                "source_record_id": _source_record_id_value(request.source_record),
                "venue_snapshot_id": (
                    str(request.venue_snapshot.snapshot_id)
                    if request.venue_snapshot is not None
                    else None
                ),
                "instrument_rule_snapshot_ids": [
                    str(rule.snapshot_id) for rule in request.instrument_rules
                ],
            },
        )

    def _preflight_conflicts(  # noqa: PLR0911
        self,
        request: VenueCapabilityManualImportRequest,
        manual_import: VenueCapabilityManualImport,
    ) -> _ImportFailure | None:
        if request.source_record.record_id is None:
            return _failure(
                VenueCapabilityManualImportDecisionReason.VALIDATION_FAILED,
                message="source record has no record_id",
            )
        existing_source = self._source_records.get(request.source_record.record_id)
        if existing_source is not None and existing_source != request.source_record:
            return _failure(
                VenueCapabilityManualImportDecisionReason.SOURCE_RECORD_STORE_CONFLICT,
                source_record_id=str(request.source_record.record_id),
            )

        if request.venue_snapshot is not None:
            existing_venue = self._venue_snapshots.get(request.venue_snapshot.snapshot_id)
            if existing_venue is not None and existing_venue != request.venue_snapshot:
                return _failure(
                    VenueCapabilityManualImportDecisionReason.VENUE_SNAPSHOT_STORE_CONFLICT,
                    venue_snapshot_id=str(request.venue_snapshot.snapshot_id),
                )

        for rule in request.instrument_rules:
            existing_rule = self._instrument_rules.get(rule.snapshot_id)
            if existing_rule is not None and existing_rule != rule:
                return _failure(
                    VenueCapabilityManualImportDecisionReason.INSTRUMENT_RULE_STORE_CONFLICT,
                    instrument_rule_snapshot_id=str(rule.snapshot_id),
                )

        if manual_import.import_id is None:
            return _failure(
                VenueCapabilityManualImportDecisionReason.VALIDATION_FAILED,
                message="manual import has no import_id",
            )
        existing_import = self._manual_imports.get(manual_import.import_id)
        if existing_import is not None and existing_import != manual_import:
            return _failure(
                VenueCapabilityManualImportDecisionReason.MANUAL_IMPORT_STORE_CONFLICT,
                manual_import_id=str(manual_import.import_id),
            )
        return None


class _ImportFailure:
    def __init__(
        self,
        reason: VenueCapabilityManualImportDecisionReason,
        details: dict[str, Any],
    ) -> None:
        self.reason = reason
        self.details = details


def _validate_source_record(
    source_record: VenueCapabilitySourceRecord,
) -> VenueCapabilityManualImportDecisionReason | None:
    if (
        source_record.descriptor.trust is not VenueCapabilitySourceTrust.OFFICIAL
        or source_record.descriptor.source_kind is VenueCapabilitySourceKind.UNKNOWN
    ):
        return VenueCapabilityManualImportDecisionReason.SOURCE_RECORD_NOT_OFFICIAL
    if source_record.health_status is not VenueCapabilitySourceHealthStatus.HEALTHY:
        return VenueCapabilityManualImportDecisionReason.SOURCE_RECORD_NOT_HEALTHY
    if not source_record.accepted_for_execution:
        return VenueCapabilityManualImportDecisionReason.SOURCE_RECORD_NOT_ACCEPTED
    return None


def _validate_request_provenance(
    request: VenueCapabilityManualImportRequest,
) -> _ImportFailure | None:
    source_record = request.source_record
    if source_record.record_id is None or source_record.payload.payload_hash is None:
        return _failure(
            VenueCapabilityManualImportDecisionReason.VALIDATION_FAILED,
            message="source record must be finalized",
        )
    expected = _SnapshotExpectedProvenance(
        venue_id=source_record.descriptor.venue_id,
        source_record_id=source_record.record_id,
        source_payload_hash=source_record.payload.payload_hash,
    )
    if request.venue_snapshot is not None:
        failure = _validate_snapshot_provenance(
            label="venue_snapshot",
            snapshot=request.venue_snapshot,
            expected=expected,
            mismatch_reason=(
                VenueCapabilityManualImportDecisionReason.VENUE_SNAPSHOT_PROVENANCE_MISMATCH
            ),
        )
        if failure is not None:
            return failure
    for rule in request.instrument_rules:
        failure = _validate_snapshot_provenance(
            label="instrument_rule",
            snapshot=rule,
            expected=expected,
            mismatch_reason=(
                VenueCapabilityManualImportDecisionReason.INSTRUMENT_RULE_PROVENANCE_MISMATCH
            ),
        )
        if failure is not None:
            return failure
    return None


class _SnapshotExpectedProvenance:
    def __init__(
        self,
        *,
        venue_id: str,
        source_record_id: VenueCapabilitySourceRecordId,
        source_payload_hash: str,
    ) -> None:
        self.venue_id = venue_id
        self.source_record_id = source_record_id
        self.source_payload_hash = source_payload_hash


def _validate_snapshot_provenance(
    *,
    label: str,
    snapshot: VenueCapabilitySnapshot | VenueInstrumentRuleSnapshot,
    expected: _SnapshotExpectedProvenance,
    mismatch_reason: VenueCapabilityManualImportDecisionReason,
) -> _ImportFailure | None:
    if snapshot.venue_id != expected.venue_id:
        return _failure(
            VenueCapabilityManualImportDecisionReason.VENUE_ID_MISMATCH,
            snapshot_kind=label,
            snapshot_venue_id=snapshot.venue_id,
            source_venue_id=expected.venue_id,
        )
    if snapshot.source_record_id != expected.source_record_id:
        return _failure(
            mismatch_reason,
            snapshot_kind=label,
            snapshot_source_record_id=(
                str(snapshot.source_record_id)
                if snapshot.source_record_id is not None
                else None
            ),
            source_record_id=str(expected.source_record_id),
        )
    if snapshot.source_payload_hash != expected.source_payload_hash:
        return _failure(
            mismatch_reason,
            snapshot_kind=label,
            snapshot_source_payload_hash=snapshot.source_payload_hash,
            source_payload_hash=expected.source_payload_hash,
        )
    return None


def _decision(
    request: VenueCapabilityManualImportRequest,
    *,
    accepted: bool,
    reason: VenueCapabilityManualImportDecisionReason,
    details: Any,
    manual_import: VenueCapabilityManualImport | None = None,
) -> VenueCapabilityManualImportDecision:
    if request.request_id is None:
        raise ValueError("request_id is required")
    return VenueCapabilityManualImportDecision(
        request_id=request.request_id,
        accepted=accepted,
        reason=reason,
        source_record_id=request.source_record.record_id,
        venue_snapshot_id=(
            request.venue_snapshot.snapshot_id
            if request.venue_snapshot is not None
            else None
        ),
        instrument_rule_snapshot_ids=tuple(
            rule.snapshot_id for rule in request.instrument_rules
        ),
        manual_import_id=manual_import.import_id if manual_import is not None else None,
        imported_at=request.imported_at,
        details=details,
    )


def _failure(
    reason: VenueCapabilityManualImportDecisionReason,
    **details: Any,
) -> _ImportFailure:
    return _ImportFailure(reason, dict(details))


def _source_record_id_value(source_record: VenueCapabilitySourceRecord) -> str | None:
    return str(source_record.record_id) if source_record.record_id is not None else None


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
