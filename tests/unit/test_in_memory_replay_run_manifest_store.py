from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.replay import (
    ReplayReadinessStatus,
    ReplayRunIntentKind,
    ReplayRunManifest,
    ReplayRunManifestStatus,
    ReplayRunReadinessBinding,
)
from futures_bot.infrastructure.replay.in_memory import InMemoryReplayRunManifestStore
from futures_bot.ports.replay import ReplayRunManifestStorePort


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _binding(
    *,
    readiness_status: ReplayReadinessStatus = ReplayReadinessStatus.BLOCKED,
    readiness_replay_plan_id: str = "plan-1",
    verified_fingerprint_ids: tuple[str, ...] = (),
) -> ReplayRunReadinessBinding:
    return ReplayRunReadinessBinding(
        readiness_report_id="rpt-1",
        readiness_replay_plan_id=readiness_replay_plan_id,
        readiness_status=readiness_status,
        readiness_checked_at=_utc(0),
        readiness_total_fingerprints=0,
        verified_fingerprint_ids=verified_fingerprint_ids,
    )


def _blocked_manifest(
    manifest_id: str = "m-1",
    replay_plan_id: str = "plan-1",
    *,
    generated_at: datetime | None = None,
) -> ReplayRunManifest:
    return ReplayRunManifest(
        manifest_id=manifest_id,
        replay_plan_id=replay_plan_id,
        intent_kind=ReplayRunIntentKind.REPLAY_ONLY,
        created_at=generated_at or _utc(0),
        status=ReplayRunManifestStatus.BLOCKED,
        readiness=_binding(),
    )


def _planned_manifest(
    manifest_id: str = "m-1",
    replay_plan_id: str = "plan-1",
    *,
    generated_at: datetime | None = None,
    fingerprint_ids: tuple[str, ...] = ("fp-1",),
) -> ReplayRunManifest:
    b = ReplayRunReadinessBinding(
        readiness_report_id="rpt-1",
        readiness_replay_plan_id=replay_plan_id,
        readiness_status=ReplayReadinessStatus.READY,
        readiness_checked_at=_utc(0),
        readiness_total_fingerprints=len(fingerprint_ids),
        readiness_latest_batch_report_id="batch-1",
        verified_fingerprint_ids=fingerprint_ids,
    )
    return ReplayRunManifest(
        manifest_id=manifest_id,
        replay_plan_id=replay_plan_id,
        intent_kind=ReplayRunIntentKind.REPLAY_ONLY,
        created_at=generated_at or _utc(0),
        status=ReplayRunManifestStatus.PLANNED,
        readiness=b,
        fingerprint_ids=fingerprint_ids,
        verification_batch_report_id="batch-1",
    )


class TestInMemoryReplayRunManifestStoreConformance:
    def test_conforms_to_port(self) -> None:
        _: ReplayRunManifestStorePort = InMemoryReplayRunManifestStore()


class TestInMemoryReplayRunManifestStore:
    def test_save_and_load_round_trip(self) -> None:
        store = InMemoryReplayRunManifestStore()
        m = _blocked_manifest()
        store.save(m)
        assert store.load("m-1") == m

    def test_load_returns_none_for_missing(self) -> None:
        store = InMemoryReplayRunManifestStore()
        assert store.load("nonexistent") is None

    def test_idempotent_save_accepted(self) -> None:
        store = InMemoryReplayRunManifestStore()
        m = _blocked_manifest()
        store.save(m)
        store.save(m)
        assert store.load("m-1") == m

    def test_conflict_rejected(self) -> None:
        store = InMemoryReplayRunManifestStore()
        m1 = _blocked_manifest("m-1", replay_plan_id="plan-A")
        m2 = _blocked_manifest("m-1", replay_plan_id="plan-B")
        store.save(m1)
        with pytest.raises(ValueError, match="conflict"):
            store.save(m2)

    def test_list_all_empty(self) -> None:
        store = InMemoryReplayRunManifestStore()
        assert store.list_all() == ()

    def test_list_all_deterministic_order(self) -> None:
        store = InMemoryReplayRunManifestStore()
        mb = _blocked_manifest("m-b", generated_at=_utc(2))
        ma = _blocked_manifest("m-a", generated_at=_utc(1))
        store.save(mb)
        store.save(ma)
        results = store.list_all()
        assert [m.manifest_id for m in results] == ["m-a", "m-b"]

    def test_list_all_same_time_sorted_by_id(self) -> None:
        store = InMemoryReplayRunManifestStore()
        mz = _blocked_manifest("m-z", generated_at=_utc(1))
        ma = _blocked_manifest("m-a", generated_at=_utc(1))
        store.save(mz)
        store.save(ma)
        results = store.list_all()
        assert [m.manifest_id for m in results] == ["m-a", "m-z"]

    def test_list_for_replay_plan_filters(self) -> None:
        store = InMemoryReplayRunManifestStore()
        ma = _blocked_manifest("m-a", replay_plan_id="plan-A")
        mb = _blocked_manifest("m-b", replay_plan_id="plan-B")
        store.save(ma)
        store.save(mb)
        results = store.list_for_replay_plan("plan-A")
        assert len(results) == 1
        assert results[0].manifest_id == "m-a"

    def test_list_for_replay_plan_multiple_ordered(self) -> None:
        store = InMemoryReplayRunManifestStore()
        mb = _blocked_manifest("m-b", generated_at=_utc(2))
        ma = _blocked_manifest("m-a", generated_at=_utc(1))
        store.save(mb)
        store.save(ma)
        results = store.list_for_replay_plan("plan-1")
        assert [m.manifest_id for m in results] == ["m-a", "m-b"]

    def test_model_copy_invalid_manifest_id_rejected(self) -> None:
        store = InMemoryReplayRunManifestStore()
        m = _blocked_manifest()
        store.save(m)
        tampered = m.model_copy(update={"manifest_id": ""})
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_duplicate_fingerprint_ids_rejected(self) -> None:
        store = InMemoryReplayRunManifestStore()
        m = _planned_manifest()
        store.save(m)
        tampered = m.model_copy(
            update={"manifest_id": "m-tamper", "fingerprint_ids": ("fp-1", "fp-1")}
        )
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_planned_with_non_ready_readiness_rejected(self) -> None:
        store = InMemoryReplayRunManifestStore()
        m = _planned_manifest()
        store.save(m)
        bad_binding = _binding(readiness_status=ReplayReadinessStatus.BLOCKED)
        tampered = m.model_copy(update={"manifest_id": "m-tamper", "readiness": bad_binding})
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_count_mismatch_rejected(self) -> None:
        store = InMemoryReplayRunManifestStore()
        m = _planned_manifest(fingerprint_ids=("fp-1", "fp-2"))
        store.save(m)
        mismatched_binding = ReplayRunReadinessBinding(
            readiness_report_id="rpt-1",
            readiness_replay_plan_id="plan-1",
            readiness_status=ReplayReadinessStatus.READY,
            readiness_checked_at=_utc(0),
            readiness_total_fingerprints=1,
            readiness_latest_batch_report_id="batch-1",
            verified_fingerprint_ids=("fp-1",),
        )
        tampered = m.model_copy(
            update={"manifest_id": "m-tamper", "readiness": mismatched_binding}
        )
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_readiness_replay_plan_id_tampering_rejected(self) -> None:
        store = InMemoryReplayRunManifestStore()
        m = _planned_manifest()
        store.save(m)
        tampered_binding = m.readiness.model_copy(
            update={"readiness_replay_plan_id": "plan-other"}
        )
        tampered = m.model_copy(
            update={"manifest_id": "m-tamper", "readiness": tampered_binding}
        )

        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_verified_fingerprint_ids_tampering_rejected(self) -> None:
        store = InMemoryReplayRunManifestStore()
        m = _planned_manifest()
        store.save(m)
        tampered_binding = m.readiness.model_copy(
            update={"verified_fingerprint_ids": ("fp-verified",)}
        )
        tampered = m.model_copy(
            update={"manifest_id": "m-tamper", "readiness": tampered_binding}
        )

        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_manifest_fingerprint_ids_tampering_rejected(self) -> None:
        store = InMemoryReplayRunManifestStore()
        m = _planned_manifest()
        store.save(m)
        tampered = m.model_copy(
            update={"manifest_id": "m-tamper", "fingerprint_ids": ("fp-current",)}
        )

        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_planned_created_before_readiness_rejected(self) -> None:
        store = InMemoryReplayRunManifestStore()
        m = _planned_manifest(generated_at=_utc(2))
        store.save(m)
        tampered_binding = m.readiness.model_copy(
            update={"readiness_checked_at": _utc(3)}
        )
        tampered = m.model_copy(
            update={"manifest_id": "m-tamper", "readiness": tampered_binding}
        )

        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)
