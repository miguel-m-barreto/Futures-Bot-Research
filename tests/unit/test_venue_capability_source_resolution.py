from __future__ import annotations

from tests.unit.capability_freshness_fixtures import NOW, order, rules, venue

from futures_bot.domain.ids import (
    VenueCapabilityFreshnessPolicyId,
    VenueCapabilitySourceRecordId,
)
from futures_bot.domain.venue_capability_freshness import (
    CapabilitySourceHealth,
    VenueCapabilityFreshnessPolicy,
)
from futures_bot.domain.venue_capability_resolution import (
    VenueCapabilityResolutionReason,
    VenueCapabilityResolutionRequest,
)
from futures_bot.domain.venue_capability_sources import (
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
from futures_bot.venue_capabilities.resolution import (
    DeterministicVenueCapabilityResolutionGateway,
)
from futures_bot.venue_capabilities.sources import (
    DeterministicVenueCapabilityManualImportGateway,
)

PAYLOAD_HASH = "1" * 64


def _policy() -> VenueCapabilityFreshnessPolicy:
    return VenueCapabilityFreshnessPolicy.strict(
        policy_id=VenueCapabilityFreshnessPolicyId(value="source-resolution-policy"),
        max_venue_snapshot_age_ms=60_000,
        max_instrument_rules_age_ms=60_000,
    )


def _request(
    *,
    require_official_source_provenance: bool = False,
) -> VenueCapabilityResolutionRequest:
    return VenueCapabilityResolutionRequest(
        order_intent=order(),
        checked_at=NOW,
        freshness_policy=_policy(),
        source_health=CapabilitySourceHealth.HEALTHY,
        require_official_source_provenance=require_official_source_provenance,
    )


def _gateway(
    venue_store: InMemoryVenueCapabilitySnapshotStore,
    rule_store: InMemoryVenueInstrumentRuleSnapshotStore,
    source_record_store: InMemoryVenueCapabilitySourceRecordStore | None = None,
) -> DeterministicVenueCapabilityResolutionGateway:
    return DeterministicVenueCapabilityResolutionGateway(
        venue_snapshot_store=venue_store,
        instrument_rule_store=rule_store,
        source_record_store=source_record_store,
    )


def _descriptor(
    *,
    venue_id: str = "venue-1",
    source_kind: VenueCapabilitySourceKind = VenueCapabilitySourceKind.OFFICIAL_EXCHANGE_EXPORT,
    trust: VenueCapabilitySourceTrust = VenueCapabilitySourceTrust.OFFICIAL,
) -> VenueCapabilitySourceDescriptor:
    return VenueCapabilitySourceDescriptor(
        venue_id=venue_id,
        source_kind=source_kind,
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
    payload: VenueCapabilitySourcePayload | None = None,
    health_status: VenueCapabilitySourceHealthStatus = (
        VenueCapabilitySourceHealthStatus.HEALTHY
    ),
    accepted_for_execution: bool = True,
) -> VenueCapabilitySourceRecord:
    return VenueCapabilitySourceRecord(
        descriptor=descriptor or _descriptor(),
        payload=payload or _payload(),
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


def _strict_stores(
    *,
    source_record: VenueCapabilitySourceRecord | None = None,
    venue_payload_hash: str | None = None,
    instrument_payload_hash: str | None = None,
) -> tuple[
    InMemoryVenueCapabilitySnapshotStore,
    InMemoryVenueInstrumentRuleSnapshotStore,
    InMemoryVenueCapabilitySourceRecordStore,
]:
    record = source_record or _record()
    assert record.record_id is not None
    assert record.payload.payload_hash is not None
    venue_store = InMemoryVenueCapabilitySnapshotStore()
    rule_store = InMemoryVenueInstrumentRuleSnapshotStore()
    source_store = InMemoryVenueCapabilitySourceRecordStore()
    source_store.put(record)
    venue_store.put(
        venue(
            source_record_id=record.record_id,
            source_payload_hash=venue_payload_hash or record.payload.payload_hash,
        )
    )
    rule_store.put(
        rules(
            source_record_id=record.record_id,
            source_payload_hash=instrument_payload_hash or record.payload.payload_hash,
        )
    )
    return venue_store, rule_store, source_store


def test_ready_resolution_preserves_snapshot_source_provenance() -> None:
    source_record_id = VenueCapabilitySourceRecordId(value="record-1")
    venue_snapshot = venue(
        source_record_id=source_record_id,
        source_payload_hash=PAYLOAD_HASH,
    )
    instrument_rules = rules(
        source_record_id=source_record_id,
        source_payload_hash=PAYLOAD_HASH,
    )
    venue_store = InMemoryVenueCapabilitySnapshotStore()
    rule_store = InMemoryVenueInstrumentRuleSnapshotStore()
    venue_store.put(venue_snapshot)
    rule_store.put(instrument_rules)

    decision = _gateway(venue_store, rule_store).resolve(_request())

    assert decision.ready is True
    assert decision.reason is VenueCapabilityResolutionReason.READY
    assert decision.venue_source_record_id == source_record_id
    assert decision.instrument_source_record_ids == (source_record_id,)
    assert decision.venue_snapshot == venue_snapshot
    assert decision.instrument_rules == instrument_rules


def test_resolution_remains_backward_compatible_when_provenance_absent() -> None:
    venue_store = InMemoryVenueCapabilitySnapshotStore()
    rule_store = InMemoryVenueInstrumentRuleSnapshotStore()
    venue_store.put(venue())
    rule_store.put(rules())

    decision = _gateway(venue_store, rule_store).resolve(_request())

    assert decision.ready is True
    assert decision.reason is VenueCapabilityResolutionReason.READY
    assert decision.venue_source_record_id is None
    assert decision.instrument_source_record_ids == ()
    assert decision.provenance_checked is False


def test_required_provenance_rejects_missing_snapshot_source_fields() -> None:
    venue_store = InMemoryVenueCapabilitySnapshotStore()
    rule_store = InMemoryVenueInstrumentRuleSnapshotStore()
    venue_store.put(venue())
    rule_store.put(rules())

    decision = _gateway(venue_store, rule_store).resolve(
        _request(require_official_source_provenance=True)
    )

    assert decision.ready is False
    assert decision.reason is VenueCapabilityResolutionReason.SOURCE_PROVENANCE_REQUIRED
    assert decision.provenance_checked is True
    assert decision.venue_validation_context is None


def test_required_provenance_rejects_missing_source_store() -> None:
    record = _record()
    assert record.record_id is not None
    assert record.payload.payload_hash is not None
    venue_store = InMemoryVenueCapabilitySnapshotStore()
    rule_store = InMemoryVenueInstrumentRuleSnapshotStore()
    venue_store.put(
        venue(
            source_record_id=record.record_id,
            source_payload_hash=record.payload.payload_hash,
        )
    )
    rule_store.put(
        rules(
            source_record_id=record.record_id,
            source_payload_hash=record.payload.payload_hash,
        )
    )

    decision = _gateway(venue_store, rule_store).resolve(
        _request(require_official_source_provenance=True)
    )

    assert decision.reason is VenueCapabilityResolutionReason.SOURCE_RECORD_MISSING
    assert decision.provenance_checked is True


def test_required_provenance_rejects_missing_source_record() -> None:
    record = _record()
    assert record.record_id is not None
    assert record.payload.payload_hash is not None
    venue_store = InMemoryVenueCapabilitySnapshotStore()
    rule_store = InMemoryVenueInstrumentRuleSnapshotStore()
    venue_store.put(
        venue(
            source_record_id=record.record_id,
            source_payload_hash=record.payload.payload_hash,
        )
    )
    rule_store.put(
        rules(
            source_record_id=record.record_id,
            source_payload_hash=record.payload.payload_hash,
        )
    )

    decision = _gateway(
        venue_store,
        rule_store,
        InMemoryVenueCapabilitySourceRecordStore(),
    ).resolve(_request(require_official_source_provenance=True))

    assert decision.reason is VenueCapabilityResolutionReason.SOURCE_RECORD_MISSING


def test_required_provenance_rejects_unaccepted_source_record() -> None:
    venue_store, rule_store, source_store = _strict_stores(
        source_record=_record(accepted_for_execution=False)
    )

    decision = _gateway(venue_store, rule_store, source_store).resolve(
        _request(require_official_source_provenance=True)
    )

    assert decision.reason is VenueCapabilityResolutionReason.SOURCE_RECORD_NOT_ACCEPTED
    assert decision.provenance_reason == "SOURCE_RECORD_NOT_ACCEPTED"


def test_required_provenance_rejects_non_official_source_trust() -> None:
    for trust in (
        VenueCapabilitySourceTrust.MANUAL_REVIEW_REQUIRED,
        VenueCapabilitySourceTrust.TEST_ONLY,
        VenueCapabilitySourceTrust.UNKNOWN,
        VenueCapabilitySourceTrust.UNTRUSTED,
    ):
        source_kind = (
            VenueCapabilitySourceKind.INTERNAL_TEST_FIXTURE
            if trust is VenueCapabilitySourceTrust.TEST_ONLY
            else VenueCapabilitySourceKind.OFFICIAL_EXCHANGE_EXPORT
        )
        venue_store, rule_store, source_store = _strict_stores(
            source_record=_record(
                descriptor=_descriptor(source_kind=source_kind, trust=trust),
                accepted_for_execution=False,
            )
        )

        decision = _gateway(venue_store, rule_store, source_store).resolve(
            _request(require_official_source_provenance=True)
        )

        assert decision.reason is VenueCapabilityResolutionReason.SOURCE_RECORD_NOT_OFFICIAL


def test_required_provenance_rejects_unhealthy_source_record() -> None:
    for health_status in (
        VenueCapabilitySourceHealthStatus.DEGRADED,
        VenueCapabilitySourceHealthStatus.UNAVAILABLE,
        VenueCapabilitySourceHealthStatus.UNKNOWN,
    ):
        venue_store, rule_store, source_store = _strict_stores(
            source_record=_record(
                health_status=health_status,
                accepted_for_execution=False,
            )
        )

        decision = _gateway(venue_store, rule_store, source_store).resolve(
            _request(require_official_source_provenance=True)
        )

        assert decision.reason is VenueCapabilityResolutionReason.SOURCE_RECORD_NOT_HEALTHY


def test_required_provenance_rejects_venue_payload_hash_mismatch() -> None:
    venue_store, rule_store, source_store = _strict_stores(
        venue_payload_hash="0" * 64
    )

    decision = _gateway(venue_store, rule_store, source_store).resolve(
        _request(require_official_source_provenance=True)
    )

    assert decision.reason is VenueCapabilityResolutionReason.SOURCE_PAYLOAD_HASH_MISMATCH
    assert decision.provenance_details is not None
    assert decision.provenance_details["snapshot_kind"] == "venue_snapshot"


def test_required_provenance_rejects_instrument_payload_hash_mismatch() -> None:
    venue_store, rule_store, source_store = _strict_stores(
        instrument_payload_hash="0" * 64
    )

    decision = _gateway(venue_store, rule_store, source_store).resolve(
        _request(require_official_source_provenance=True)
    )

    assert decision.reason is VenueCapabilityResolutionReason.SOURCE_PAYLOAD_HASH_MISMATCH
    assert decision.provenance_details is not None
    assert decision.provenance_details["snapshot_kind"] == "instrument_rules"


def test_required_provenance_rejects_source_venue_mismatch() -> None:
    venue_store, rule_store, source_store = _strict_stores(
        source_record=_record(descriptor=_descriptor(venue_id="venue-2"))
    )

    decision = _gateway(venue_store, rule_store, source_store).resolve(
        _request(require_official_source_provenance=True)
    )

    assert decision.reason is VenueCapabilityResolutionReason.SOURCE_VENUE_MISMATCH


def test_required_provenance_accepts_valid_venue_and_instrument_sources() -> None:
    venue_store, rule_store, source_store = _strict_stores()

    decision = _gateway(venue_store, rule_store, source_store).resolve(
        _request(require_official_source_provenance=True)
    )

    assert decision.ready is True
    assert decision.reason is VenueCapabilityResolutionReason.READY
    assert decision.provenance_checked is True
    assert decision.provenance_reason == "PROVENANCE_OK"
    assert decision.freshness_check is not None
    assert decision.venue_validation_context is not None


def test_review_121_strict_provenance_resolution_preserved() -> None:
    venue_store, rule_store, source_store = _strict_stores()

    decision = _gateway(venue_store, rule_store, source_store).resolve(
        _request(require_official_source_provenance=True)
    )

    assert decision.ready is True
    assert decision.reason is VenueCapabilityResolutionReason.READY
    assert decision.provenance_reason == "PROVENANCE_OK"


def test_manual_import_then_strict_provenance_resolution_ready() -> None:
    record = _record()
    assert record.record_id is not None
    assert record.payload.payload_hash is not None
    venue_store = InMemoryVenueCapabilitySnapshotStore()
    rule_store = InMemoryVenueInstrumentRuleSnapshotStore()
    source_store = InMemoryVenueCapabilitySourceRecordStore()
    import_store = InMemoryVenueCapabilityManualImportStore()
    venue_snapshot = venue(
        source_record_id=record.record_id,
        source_payload_hash=record.payload.payload_hash,
    )
    instrument_rules = rules(
        source_record_id=record.record_id,
        source_payload_hash=record.payload.payload_hash,
    )
    import_request = VenueCapabilityManualImportRequest(
        source_record=record,
        venue_snapshot=venue_snapshot,
        instrument_rules=(instrument_rules,),
        imported_at=NOW,
        imported_by="operator",
        details={},
    )

    import_decision = DeterministicVenueCapabilityManualImportGateway(
        source_record_store=source_store,
        venue_snapshot_store=venue_store,
        instrument_rule_store=rule_store,
        manual_import_store=import_store,
    ).import_capabilities(import_request)
    resolution = _gateway(venue_store, rule_store, source_store).resolve(
        _request(require_official_source_provenance=True)
    )

    assert import_decision.accepted is True
    assert resolution.ready is True
    assert resolution.reason is VenueCapabilityResolutionReason.READY


def test_invalid_manual_import_does_not_allow_strict_provenance_resolution_ready() -> None:
    record = _record()
    assert record.record_id is not None
    assert record.payload.payload_hash is not None
    venue_store = InMemoryVenueCapabilitySnapshotStore()
    rule_store = InMemoryVenueInstrumentRuleSnapshotStore()
    source_store = InMemoryVenueCapabilitySourceRecordStore()
    import_store = InMemoryVenueCapabilityManualImportStore()
    venue_snapshot = venue(
        source_record_id=record.record_id,
        source_payload_hash=record.payload.payload_hash,
    )
    bad_rules = rules(
        source_record_id=record.record_id,
        source_payload_hash="0" * 64,
    )
    import_request = VenueCapabilityManualImportRequest(
        source_record=record,
        venue_snapshot=venue_snapshot,
        instrument_rules=(bad_rules,),
        imported_at=NOW,
        imported_by="operator",
        details={},
    )

    import_decision = DeterministicVenueCapabilityManualImportGateway(
        source_record_store=source_store,
        venue_snapshot_store=venue_store,
        instrument_rule_store=rule_store,
        manual_import_store=import_store,
    ).import_capabilities(import_request)
    resolution = _gateway(venue_store, rule_store, source_store).resolve(
        _request(require_official_source_provenance=True)
    )

    assert import_decision.reason is (
        VenueCapabilityManualImportDecisionReason.INSTRUMENT_RULE_PROVENANCE_MISMATCH
    )
    assert source_store.get(record.record_id) is None
    assert venue_store.get(venue_snapshot.snapshot_id) is None
    assert rule_store.get(bad_rules.snapshot_id) is None
    assert import_store.list_by_venue_id("venue-1") == ()
    assert resolution.ready is False
    assert resolution.reason is VenueCapabilityResolutionReason.VENUE_SNAPSHOT_MISSING
