from __future__ import annotations

from datetime import UTC, datetime

from tests.unit.capability_freshness_fixtures import rules, venue

from futures_bot.domain.ids import VenueInstrumentRuleSnapshotId
from futures_bot.domain.venue_capability_sources import (
    VenueCapabilityManualImport,
    VenueCapabilityManualImportDecisionReason,
    VenueCapabilityManualImportRequest,
    VenueCapabilitySourceDescriptor,
    VenueCapabilitySourceFetchMode,
    VenueCapabilitySourceHealthStatus,
    VenueCapabilitySourceKind,
    VenueCapabilitySourcePayload,
    VenueCapabilitySourceRecord,
    VenueCapabilitySourceRecordReason,
    VenueCapabilitySourceTrust,
)
from futures_bot.venue_capabilities.in_memory import (
    InMemoryVenueCapabilityManualImportStore,
    InMemoryVenueCapabilitySnapshotStore,
    InMemoryVenueCapabilitySourceRecordStore,
    InMemoryVenueInstrumentRuleSnapshotStore,
)
from futures_bot.venue_capabilities.sources import (
    DeterministicVenueCapabilityManualImportGateway,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _descriptor(
    *,
    venue_id: str = "venue-1",
    trust: VenueCapabilitySourceTrust = VenueCapabilitySourceTrust.OFFICIAL,
) -> VenueCapabilitySourceDescriptor:
    return VenueCapabilitySourceDescriptor(
        venue_id=venue_id,
        source_kind=VenueCapabilitySourceKind.OFFICIAL_EXCHANGE_EXPORT,
        trust=trust,
        fetch_mode=VenueCapabilitySourceFetchMode.MANUAL,
        reference_name="Official export",
        official_owner="Venue",
        version="2026-01-01",
        created_at=NOW,
        metadata={},
    )


def _payload(version: int = 1) -> VenueCapabilitySourcePayload:
    return VenueCapabilitySourcePayload(
        canonical_payload={"venue": "venue-1", "version": version},
        content_type="application/json",
        captured_at=NOW,
        observed_at=NOW,
    )


def _record(
    *,
    descriptor: VenueCapabilitySourceDescriptor | None = None,
    health_status: VenueCapabilitySourceHealthStatus = (
        VenueCapabilitySourceHealthStatus.HEALTHY
    ),
    accepted_for_execution: bool = True,
) -> VenueCapabilitySourceRecord:
    return VenueCapabilitySourceRecord(
        descriptor=descriptor or _descriptor(),
        payload=_payload(),
        health_status=health_status,
        reason=(
            VenueCapabilitySourceRecordReason.ACCEPTED
            if accepted_for_execution
            else VenueCapabilitySourceRecordReason.REJECTED_UNTRUSTED
        ),
        accepted_for_execution=accepted_for_execution,
        recorded_at=NOW,
        details={},
    )


def _stores() -> tuple[
    InMemoryVenueCapabilitySourceRecordStore,
    InMemoryVenueCapabilitySnapshotStore,
    InMemoryVenueInstrumentRuleSnapshotStore,
    InMemoryVenueCapabilityManualImportStore,
]:
    return (
        InMemoryVenueCapabilitySourceRecordStore(),
        InMemoryVenueCapabilitySnapshotStore(),
        InMemoryVenueInstrumentRuleSnapshotStore(),
        InMemoryVenueCapabilityManualImportStore(),
    )


def _gateway(
    source_store: InMemoryVenueCapabilitySourceRecordStore,
    venue_store: InMemoryVenueCapabilitySnapshotStore,
    rule_store: InMemoryVenueInstrumentRuleSnapshotStore,
    import_store: InMemoryVenueCapabilityManualImportStore,
) -> DeterministicVenueCapabilityManualImportGateway:
    return DeterministicVenueCapabilityManualImportGateway(
        source_record_store=source_store,
        venue_snapshot_store=venue_store,
        instrument_rule_store=rule_store,
        manual_import_store=import_store,
    )


def _request(
    *,
    source_record: VenueCapabilitySourceRecord | None = None,
    venue_payload_hash: str | None = None,
    rule_payload_hash: str | None = None,
    venue_id: str = "venue-1",
    rule_id: VenueInstrumentRuleSnapshotId | None = None,
) -> VenueCapabilityManualImportRequest:
    record = source_record or _record()
    assert record.record_id is not None
    assert record.payload.payload_hash is not None
    payload_hash = record.payload.payload_hash
    return VenueCapabilityManualImportRequest(
        source_record=record,
        venue_snapshot=venue(
            venue_id=venue_id,
            source_record_id=record.record_id,
            source_payload_hash=venue_payload_hash or payload_hash,
        ),
        instrument_rules=(
            rules(
                snapshot_id=rule_id or VenueInstrumentRuleSnapshotId(value="rules-1"),
                venue_id=venue_id,
                source_record_id=record.record_id,
                source_payload_hash=rule_payload_hash or payload_hash,
            ),
        ),
        imported_at=NOW,
        imported_by="operator",
        details={"ticket": "review-1"},
    )


def _manual_import_from_request(
    request: VenueCapabilityManualImportRequest,
) -> VenueCapabilityManualImport:
    return VenueCapabilityManualImport(
        source_record=request.source_record,
        venue_snapshot=request.venue_snapshot,
        instrument_rules=request.instrument_rules,
        imported_at=request.imported_at,
        imported_by=request.imported_by,
        details=request.details,
    )


def _assert_empty(
    source_store: InMemoryVenueCapabilitySourceRecordStore,
    venue_store: InMemoryVenueCapabilitySnapshotStore,
    rule_store: InMemoryVenueInstrumentRuleSnapshotStore,
    import_store: InMemoryVenueCapabilityManualImportStore,
    request: VenueCapabilityManualImportRequest,
) -> None:
    assert request.source_record.record_id is not None
    assert source_store.get(request.source_record.record_id) is None
    assert request.venue_snapshot is not None
    assert venue_store.get(request.venue_snapshot.snapshot_id) is None
    assert rule_store.get(request.instrument_rules[0].snapshot_id) is None
    assert import_store.list_by_venue_id(request.source_record.descriptor.venue_id) == ()


def test_accepted_official_import_writes_all_stores() -> None:
    source_store, venue_store, rule_store, import_store = _stores()
    request = _request()

    decision = _gateway(source_store, venue_store, rule_store, import_store).import_capabilities(
        request
    )

    assert decision.accepted is True
    assert decision.reason is VenueCapabilityManualImportDecisionReason.ACCEPTED
    assert decision.manual_import_id is not None
    assert request.source_record.record_id is not None
    assert source_store.get(request.source_record.record_id) == request.source_record
    assert request.venue_snapshot is not None
    assert venue_store.get(request.venue_snapshot.snapshot_id) == request.venue_snapshot
    assert rule_store.get(request.instrument_rules[0].snapshot_id) == request.instrument_rules[0]
    assert len(import_store.list_by_venue_id("venue-1")) == 1


def test_same_import_repeated_is_idempotent() -> None:
    source_store, venue_store, rule_store, import_store = _stores()
    gateway = _gateway(source_store, venue_store, rule_store, import_store)
    request = _request()

    first = gateway.import_capabilities(request)
    second = gateway.import_capabilities(request)

    assert first.accepted is True
    assert second.accepted is True
    assert first.manual_import_id == second.manual_import_id
    assert len(import_store.list_by_venue_id("venue-1")) == 1


def test_source_not_accepted_rejects_and_writes_nothing() -> None:
    source_store, venue_store, rule_store, import_store = _stores()
    request = _request(source_record=_record(accepted_for_execution=False))

    decision = _gateway(source_store, venue_store, rule_store, import_store).import_capabilities(
        request
    )

    assert decision.reason is (
        VenueCapabilityManualImportDecisionReason.SOURCE_RECORD_NOT_ACCEPTED
    )
    _assert_empty(source_store, venue_store, rule_store, import_store, request)


def test_source_not_official_rejects_and_writes_nothing() -> None:
    source_store, venue_store, rule_store, import_store = _stores()
    request = _request(
        source_record=_record(
            descriptor=_descriptor(trust=VenueCapabilitySourceTrust.UNTRUSTED),
            accepted_for_execution=False,
        )
    )

    decision = _gateway(source_store, venue_store, rule_store, import_store).import_capabilities(
        request
    )

    assert decision.reason is VenueCapabilityManualImportDecisionReason.SOURCE_RECORD_NOT_OFFICIAL
    _assert_empty(source_store, venue_store, rule_store, import_store, request)


def test_source_unhealthy_rejects_and_writes_nothing() -> None:
    source_store, venue_store, rule_store, import_store = _stores()
    request = _request(
        source_record=_record(
            health_status=VenueCapabilitySourceHealthStatus.DEGRADED,
            accepted_for_execution=False,
        )
    )

    decision = _gateway(source_store, venue_store, rule_store, import_store).import_capabilities(
        request
    )

    assert decision.reason is VenueCapabilityManualImportDecisionReason.SOURCE_RECORD_NOT_HEALTHY
    _assert_empty(source_store, venue_store, rule_store, import_store, request)


def test_venue_snapshot_provenance_mismatch_rejects_and_writes_nothing() -> None:
    source_store, venue_store, rule_store, import_store = _stores()
    request = _request(venue_payload_hash="0" * 64)

    decision = _gateway(source_store, venue_store, rule_store, import_store).import_capabilities(
        request
    )

    assert decision.reason is (
        VenueCapabilityManualImportDecisionReason.VENUE_SNAPSHOT_PROVENANCE_MISMATCH
    )
    _assert_empty(source_store, venue_store, rule_store, import_store, request)


def test_instrument_rule_provenance_mismatch_rejects_and_writes_nothing() -> None:
    source_store, venue_store, rule_store, import_store = _stores()
    request = _request(rule_payload_hash="0" * 64)

    decision = _gateway(source_store, venue_store, rule_store, import_store).import_capabilities(
        request
    )

    assert decision.reason is (
        VenueCapabilityManualImportDecisionReason.INSTRUMENT_RULE_PROVENANCE_MISMATCH
    )
    _assert_empty(source_store, venue_store, rule_store, import_store, request)


def test_venue_id_mismatch_rejects_and_writes_nothing() -> None:
    source_store, venue_store, rule_store, import_store = _stores()
    request = _request(venue_id="venue-2")

    decision = _gateway(source_store, venue_store, rule_store, import_store).import_capabilities(
        request
    )

    assert decision.reason is VenueCapabilityManualImportDecisionReason.VENUE_ID_MISMATCH
    _assert_empty(source_store, venue_store, rule_store, import_store, request)


def test_source_record_store_conflict_rejects_and_writes_nothing_else() -> None:
    source_store, venue_store, rule_store, import_store = _stores()
    request = _request()
    source_store.put(request.source_record.model_copy(update={"details": {"changed": True}}))

    decision = _gateway(source_store, venue_store, rule_store, import_store).import_capabilities(
        request
    )

    assert decision.reason is (
        VenueCapabilityManualImportDecisionReason.SOURCE_RECORD_STORE_CONFLICT
    )
    assert request.venue_snapshot is not None
    assert venue_store.get(request.venue_snapshot.snapshot_id) is None
    assert rule_store.get(request.instrument_rules[0].snapshot_id) is None
    assert import_store.list_by_venue_id("venue-1") == ()


def test_venue_snapshot_store_conflict_rejects_and_writes_nothing_else() -> None:
    source_store, venue_store, rule_store, import_store = _stores()
    request = _request()
    assert request.venue_snapshot is not None
    venue_store.put(
        request.venue_snapshot.model_copy(update={"api_trading_enabled": False})
    )

    decision = _gateway(source_store, venue_store, rule_store, import_store).import_capabilities(
        request
    )

    assert decision.reason is (
        VenueCapabilityManualImportDecisionReason.VENUE_SNAPSHOT_STORE_CONFLICT
    )
    assert request.source_record.record_id is not None
    assert source_store.get(request.source_record.record_id) is None
    assert rule_store.get(request.instrument_rules[0].snapshot_id) is None
    assert import_store.list_by_venue_id("venue-1") == ()


def test_instrument_rule_store_conflict_rejects_and_writes_nothing_else() -> None:
    source_store, venue_store, rule_store, import_store = _stores()
    request = _request()
    rule_store.put(request.instrument_rules[0].model_copy(update={"symbol": "ETHUSDT"}))

    decision = _gateway(source_store, venue_store, rule_store, import_store).import_capabilities(
        request
    )

    assert decision.reason is (
        VenueCapabilityManualImportDecisionReason.INSTRUMENT_RULE_STORE_CONFLICT
    )
    assert request.source_record.record_id is not None
    assert source_store.get(request.source_record.record_id) is None
    assert request.venue_snapshot is not None
    assert venue_store.get(request.venue_snapshot.snapshot_id) is None
    assert import_store.list_by_venue_id("venue-1") == ()


def test_manual_import_store_conflict_rejects_and_writes_nothing_else() -> None:
    source_store, venue_store, rule_store, import_store = _stores()
    request = _request()
    manual_import = _manual_import_from_request(request)
    import_store.put(manual_import.model_copy(update={"details": {"changed": True}}))

    decision = _gateway(source_store, venue_store, rule_store, import_store).import_capabilities(
        request
    )

    assert decision.reason is (
        VenueCapabilityManualImportDecisionReason.MANUAL_IMPORT_STORE_CONFLICT
    )
    assert request.source_record.record_id is not None
    assert source_store.get(request.source_record.record_id) is None
    assert request.venue_snapshot is not None
    assert venue_store.get(request.venue_snapshot.snapshot_id) is None
    assert rule_store.get(request.instrument_rules[0].snapshot_id) is None


def test_gateway_preserves_deterministic_instrument_rule_order() -> None:
    source_store, venue_store, rule_store, import_store = _stores()
    record = _record()
    assert record.record_id is not None
    assert record.payload.payload_hash is not None
    first = rules(
        snapshot_id=VenueInstrumentRuleSnapshotId(value="rules-a"),
        source_record_id=record.record_id,
        source_payload_hash=record.payload.payload_hash,
    )
    second = rules(
        snapshot_id=VenueInstrumentRuleSnapshotId(value="rules-b"),
        instrument_id="ETH-PERP",
        symbol="ETHUSDT",
        source_record_id=record.record_id,
        source_payload_hash=record.payload.payload_hash,
    )
    request = VenueCapabilityManualImportRequest(
        source_record=record,
        instrument_rules=(second, first),
        imported_at=NOW,
        imported_by="operator",
        details={},
    )

    decision = _gateway(source_store, venue_store, rule_store, import_store).import_capabilities(
        request
    )

    assert decision.accepted is True
    assert decision.instrument_rule_snapshot_ids == (second.snapshot_id, first.snapshot_id)
    stored = import_store.list_by_venue_id("venue-1")[0]
    assert stored.instrument_rules == (second, first)
