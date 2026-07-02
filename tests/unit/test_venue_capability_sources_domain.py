from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from tests.unit.capability_freshness_fixtures import rules, venue

from futures_bot.domain.ids import VenueCapabilitySourceRecordId
from futures_bot.domain.venue_capability_sources import (
    VenueCapabilityManualImport,
    VenueCapabilitySourceDescriptor,
    VenueCapabilitySourceFetchMode,
    VenueCapabilitySourceHealthRecord,
    VenueCapabilitySourceHealthStatus,
    VenueCapabilitySourceKind,
    VenueCapabilitySourcePayload,
    VenueCapabilitySourceRecord,
    VenueCapabilitySourceRecordReason,
    VenueCapabilitySourceTrust,
    source_payload_hash,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
HASH = "7" * 64


def _descriptor(
    *,
    venue_id: str = "venue-1",
    source_kind: VenueCapabilitySourceKind = VenueCapabilitySourceKind.OFFICIAL_EXCHANGE_EXPORT,
    trust: VenueCapabilitySourceTrust = VenueCapabilitySourceTrust.OFFICIAL,
    created_at: datetime = NOW,
) -> VenueCapabilitySourceDescriptor:
    return VenueCapabilitySourceDescriptor(
        venue_id=venue_id,
        source_kind=source_kind,
        trust=trust,
        fetch_mode=VenueCapabilitySourceFetchMode.MANUAL,
        reference_name="Official export",
        official_owner="Venue",
        version="2026-01-01",
        created_at=created_at,
        metadata={"scope": "futures"},
    )


def _payload(
    *,
    canonical_payload: object = {"symbols": ["BTCUSDT"], "venue": "venue-1"},
    captured_at: datetime = NOW,
) -> VenueCapabilitySourcePayload:
    return VenueCapabilitySourcePayload(
        canonical_payload=canonical_payload,
        content_type="application/json",
        captured_at=captured_at,
        observed_at=captured_at,
    )


def _record(**overrides: object) -> VenueCapabilitySourceRecord:
    values: dict[str, object] = {
        "descriptor": _descriptor(),
        "payload": _payload(),
        "health_status": VenueCapabilitySourceHealthStatus.HEALTHY,
        "reason": VenueCapabilitySourceRecordReason.ACCEPTED,
        "accepted_for_execution": True,
        "recorded_at": NOW,
        "details": {"review": "manual"},
    }
    values.update(overrides)
    return VenueCapabilitySourceRecord(**values)


def test_source_descriptor_sets_deterministic_id() -> None:
    assert _descriptor().source_id == _descriptor().source_id


def test_source_descriptor_rejects_unknown_as_official() -> None:
    with pytest.raises(ValidationError, match="UNKNOWN source_kind"):
        _descriptor(
            source_kind=VenueCapabilitySourceKind.UNKNOWN,
            trust=VenueCapabilitySourceTrust.OFFICIAL,
        )


def test_source_descriptor_rejects_internal_fixture_unless_test_only() -> None:
    with pytest.raises(ValidationError, match="INTERNAL_TEST_FIXTURE"):
        _descriptor(
            source_kind=VenueCapabilitySourceKind.INTERNAL_TEST_FIXTURE,
            trust=VenueCapabilitySourceTrust.OFFICIAL,
        )

    descriptor = _descriptor(
        source_kind=VenueCapabilitySourceKind.INTERNAL_TEST_FIXTURE,
        trust=VenueCapabilitySourceTrust.TEST_ONLY,
    )
    assert descriptor.trust is VenueCapabilitySourceTrust.TEST_ONLY


def test_source_payload_hash_is_deterministic_from_canonical_json() -> None:
    left = _payload(canonical_payload={"b": 2, "a": [1, True]})
    right = _payload(canonical_payload={"a": [1, True], "b": 2})

    assert left.payload_hash == right.payload_hash
    assert left.payload_hash == source_payload_hash({"a": [1, True], "b": 2})
    assert left.payload_hash_id == right.payload_hash_id


def test_source_payload_rejects_non_json_compatible_payload() -> None:
    with pytest.raises(ValidationError, match="JSON-compatible"):
        _payload(canonical_payload={"bad": object()})
    with pytest.raises(ValidationError, match="object keys"):
        _payload(canonical_payload={1: "bad"})


def test_source_payload_rejects_mismatched_hash() -> None:
    with pytest.raises(ValidationError, match="payload_hash"):
        VenueCapabilitySourcePayload(
            canonical_payload={"venue": "venue-1"},
            payload_hash="0" * 64,
            content_type="application/json",
            captured_at=NOW,
            observed_at=NOW,
        )


def test_source_payload_rejects_observed_before_captured_by_default() -> None:
    with pytest.raises(ValidationError, match="observed_at"):
        VenueCapabilitySourcePayload(
            canonical_payload={"venue": "venue-1"},
            content_type="application/json",
            captured_at=NOW,
            observed_at=NOW - timedelta(seconds=1),
        )


def test_source_record_accepted_requires_official_trust() -> None:
    descriptor = _descriptor(trust=VenueCapabilitySourceTrust.UNTRUSTED)

    with pytest.raises(ValidationError, match="OFFICIAL trust"):
        _record(descriptor=descriptor)


def test_source_record_accepted_requires_healthy_status() -> None:
    with pytest.raises(ValidationError, match="HEALTHY"):
        _record(health_status=VenueCapabilitySourceHealthStatus.DEGRADED)


def test_source_record_rejected_can_use_untrusted_source() -> None:
    descriptor = _descriptor(trust=VenueCapabilitySourceTrust.UNTRUSTED)
    record = _record(
        descriptor=descriptor,
        reason=VenueCapabilitySourceRecordReason.REJECTED_UNTRUSTED,
        accepted_for_execution=False,
    )

    assert record.accepted_for_execution is False


def test_review_119_source_contracts_unknown_untrusted_not_accepted_preserved() -> None:
    with pytest.raises(ValidationError, match="UNKNOWN source_kind"):
        _descriptor(
            source_kind=VenueCapabilitySourceKind.UNKNOWN,
            trust=VenueCapabilitySourceTrust.OFFICIAL,
        )

    with pytest.raises(ValidationError, match="OFFICIAL trust"):
        _record(descriptor=_descriptor(trust=VenueCapabilitySourceTrust.UNTRUSTED))


def test_source_record_rejected_cannot_use_accepted_reason() -> None:
    with pytest.raises(ValidationError, match="reason != ACCEPTED"):
        _record(accepted_for_execution=False)


def test_source_health_record_sets_deterministic_id() -> None:
    descriptor = _descriptor()
    assert descriptor.source_id is not None
    left = VenueCapabilitySourceHealthRecord(
        source_id=descriptor.source_id,
        venue_id="venue-1",
        health_status=VenueCapabilitySourceHealthStatus.HEALTHY,
        checked_at=NOW,
        recorded_at=NOW,
        details={"check": "manual"},
    )
    right = VenueCapabilitySourceHealthRecord(
        source_id=descriptor.source_id,
        venue_id="venue-1",
        health_status=VenueCapabilitySourceHealthStatus.HEALTHY,
        checked_at=NOW,
        recorded_at=NOW,
        details={"check": "manual"},
    )
    assert left.health_record_id == right.health_record_id


def test_manual_import_requires_accepted_source_record() -> None:
    source_record = _record(
        reason=VenueCapabilitySourceRecordReason.REJECTED_UNTRUSTED,
        accepted_for_execution=False,
    )

    with pytest.raises(ValidationError, match="accepted source record"):
        VenueCapabilityManualImport(
            source_record=source_record,
            imported_at=NOW,
            imported_by="operator",
            details={},
        )


def test_manual_import_accepts_matching_snapshot_and_rules() -> None:
    source_record = _record()
    assert source_record.record_id is not None
    assert source_record.payload.payload_hash is not None
    venue_snapshot = venue(
        source_record_id=source_record.record_id,
        source_payload_hash=source_record.payload.payload_hash,
    )
    instrument_rules = rules(
        source_record_id=source_record.record_id,
        source_payload_hash=source_record.payload.payload_hash,
    )

    manual_import = VenueCapabilityManualImport(
        source_record=source_record,
        venue_snapshot=venue_snapshot,
        instrument_rules=(instrument_rules,),
        imported_at=NOW,
        imported_by="operator",
        details={"ticket": "review-1"},
    )

    assert manual_import.import_id is not None


def test_manual_import_rejects_venue_snapshot_with_mismatched_venue() -> None:
    source_record = _record()
    assert source_record.record_id is not None
    assert source_record.payload.payload_hash is not None

    with pytest.raises(ValidationError, match="venue_id"):
        VenueCapabilityManualImport(
            source_record=source_record,
            venue_snapshot=venue(
                venue_id="venue-2",
                source_record_id=source_record.record_id,
                source_payload_hash=source_record.payload.payload_hash,
            ),
            imported_at=NOW,
            imported_by="operator",
            details={},
        )


def test_manual_import_rejects_snapshot_source_record_id_mismatch() -> None:
    source_record = _record()
    assert source_record.payload.payload_hash is not None

    with pytest.raises(ValidationError, match="source_record_id"):
        VenueCapabilityManualImport(
            source_record=source_record,
            venue_snapshot=venue(
                source_record_id=VenueCapabilitySourceRecordId(value="wrong-record"),
                source_payload_hash=source_record.payload.payload_hash,
            ),
            imported_at=NOW,
            imported_by="operator",
            details={},
        )


def test_manual_import_rejects_source_payload_hash_mismatch() -> None:
    source_record = _record()
    assert source_record.record_id is not None

    with pytest.raises(ValidationError, match="source_payload_hash"):
        VenueCapabilityManualImport(
            source_record=source_record,
            venue_snapshot=venue(
                source_record_id=source_record.record_id,
                source_payload_hash=HASH,
            ),
            imported_at=NOW,
            imported_by="operator",
            details={},
        )


def test_snapshot_provenance_fields_require_each_other() -> None:
    with pytest.raises(ValidationError, match="present together"):
        venue(source_payload_hash=HASH)
    with pytest.raises(ValidationError, match="present together"):
        rules(source_record_id=VenueCapabilitySourceRecordId(value="record-1"))
