from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.replay import (
    ReplayArtifactFingerprintVerificationBatchItem,
    ReplayArtifactFingerprintVerificationBatchReport,
    ReplayArtifactFingerprintVerificationBatchReportStatus,
    ReplayArtifactFingerprintVerificationBatchScopeKind,
    ReplayArtifactFingerprintVerificationBatchSummary,
    ReplayArtifactFingerprintVerificationStatus,
    ReplayArtifactKind,
)
from futures_bot.infrastructure.replay.in_memory import (
    InMemoryReplayArtifactFingerprintVerificationBatchReportStore,
)
from futures_bot.ports.replay import ReplayArtifactFingerprintVerificationBatchReportStorePort


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _item(
    item_id: str = "item-1",
    fingerprint_id: str = "fp-1",
    verification_id: str = "ver-1",
    *,
    verification_status: ReplayArtifactFingerprintVerificationStatus = (
        ReplayArtifactFingerprintVerificationStatus.VALID
    ),
) -> ReplayArtifactFingerprintVerificationBatchItem:
    return ReplayArtifactFingerprintVerificationBatchItem(
        item_id=item_id,
        fingerprint_id=fingerprint_id,
        verification_id=verification_id,
        artifact_kind=ReplayArtifactKind.TIMELINE,
        artifact_id="tl-1",
        replay_plan_id="plan-1",
        verification_status=verification_status,
    )


def _summary(
    total_fingerprints: int = 1,
) -> ReplayArtifactFingerprintVerificationBatchSummary:
    count_by_status: dict[ReplayArtifactFingerprintVerificationStatus, int] = {}
    if total_fingerprints > 0:
        count_by_status = {
            ReplayArtifactFingerprintVerificationStatus.VALID: total_fingerprints
        }
    return ReplayArtifactFingerprintVerificationBatchSummary(
        total_fingerprints=total_fingerprints,
        count_by_status=count_by_status,
        total_issues=0,
        all_valid=total_fingerprints > 0,
        has_mismatches=False,
        has_missing=False,
    )


def _report(
    report_id: str = "rpt-1",
    *,
    generated_at: datetime | None = None,
    replay_plan_id: str | None = "plan-1",
    items: tuple[ReplayArtifactFingerprintVerificationBatchItem, ...] | None = None,
    smry: ReplayArtifactFingerprintVerificationBatchSummary | None = None,
) -> ReplayArtifactFingerprintVerificationBatchReport:
    if items is None:
        items = (_item(),)
    if smry is None:
        smry = _summary()
    return ReplayArtifactFingerprintVerificationBatchReport(
        report_id=report_id,
        scope_kind=ReplayArtifactFingerprintVerificationBatchScopeKind.EXPLICIT_FINGERPRINT_SET,
        replay_plan_id=replay_plan_id,
        generated_at=generated_at or _utc(0),
        status=ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED,
        items=items,
        summary=smry,
        requested_fingerprint_ids=tuple(i.fingerprint_id for i in items),
    )


class TestInMemoryReplayArtifactFingerprintVerificationBatchReportStoreConformance:
    def test_conforms_to_port(self) -> None:
        _: ReplayArtifactFingerprintVerificationBatchReportStorePort = (
            InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        )


class TestInMemoryReplayArtifactFingerprintVerificationBatchReportStore:
    def test_save_and_load_round_trip(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        r = _report()
        store.save(r)
        assert store.load("rpt-1") == r

    def test_load_returns_none_for_missing(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        assert store.load("nonexistent") is None

    def test_idempotent_save_accepted(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        r = _report()
        store.save(r)
        store.save(r)
        assert store.load("rpt-1") == r

    def test_conflict_rejected(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        r1 = _report("rpt-1", replay_plan_id="plan-A")
        r2 = _report("rpt-1", replay_plan_id="plan-B")
        store.save(r1)
        with pytest.raises(ValueError, match="conflict"):
            store.save(r2)

    def test_list_all_empty(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        assert store.list_all() == ()

    def test_list_all_deterministic_order(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        rb = _report("rpt-b", generated_at=_utc(2), replay_plan_id="plan-b")
        ra = _report("rpt-a", generated_at=_utc(1), replay_plan_id="plan-a")
        store.save(rb)
        store.save(ra)
        results = store.list_all()
        assert [r.report_id for r in results] == ["rpt-a", "rpt-b"]

    def test_list_all_same_time_sorted_by_id(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        rz = _report("rpt-z", generated_at=_utc(1), replay_plan_id="plan-z")
        ra = _report("rpt-a", generated_at=_utc(1), replay_plan_id="plan-a")
        store.save(rz)
        store.save(ra)
        results = store.list_all()
        assert [r.report_id for r in results] == ["rpt-a", "rpt-z"]

    def test_list_for_replay_plan_filters(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        ra = _report("rpt-a", replay_plan_id="plan-A")
        rb = _report("rpt-b", replay_plan_id="plan-B")
        store.save(ra)
        store.save(rb)
        results = store.list_for_replay_plan("plan-A")
        assert len(results) == 1
        assert results[0].report_id == "rpt-a"

    def test_list_for_replay_plan_excludes_none(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        r = _report("rpt-1", replay_plan_id=None)
        store.save(r)
        assert store.list_for_replay_plan("plan-1") == ()

    def test_list_for_replay_plan_multiple_results_ordered(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        rb = _report("rpt-b", generated_at=_utc(2), replay_plan_id="plan-X")
        ra = _report("rpt-a", generated_at=_utc(1), replay_plan_id="plan-X")
        store.save(rb)
        store.save(ra)
        results = store.list_for_replay_plan("plan-X")
        assert [r.report_id for r in results] == ["rpt-a", "rpt-b"]

    def test_model_copy_invalid_report_id_rejected(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        r = _report()
        store.save(r)
        tampered = r.model_copy(update={"report_id": ""})
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_summary_mismatch_rejected(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        r = _report()
        store.save(r)
        bad_summary = _summary(total_fingerprints=5)
        tampered = r.model_copy(update={"report_id": "rpt-tamper", "summary": bad_summary})
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_issue_count_string_rejected(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        r = _report()
        store.save(r)
        tampered_item = r.items[0].model_copy(update={"issue_count": "1"})
        tampered = r.model_copy(
            update={"report_id": "rpt-tamper-ic", "items": (tampered_item,)}
        )
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_total_fingerprints_string_rejected(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        r = _report()
        store.save(r)
        tampered_summary = r.summary.model_copy(update={"total_fingerprints": "1"})
        tampered = r.model_copy(
            update={"report_id": "rpt-tamper-tf", "summary": tampered_summary}
        )
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_count_by_status_string_value_rejected(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        r = _report()
        store.save(r)
        tampered_summary = r.summary.model_copy(
            update={"count_by_status": {ReplayArtifactFingerprintVerificationStatus.VALID: "1"}}
        )
        tampered = r.model_copy(
            update={"report_id": "rpt-tamper-cbs", "summary": tampered_summary}
        )
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_wrong_order_requested_fp_ids_rejected(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        items = (
            _item("item-1", "fp-1", "ver-1"),
            _item("item-2", "fp-2", "ver-2"),
        )
        r = _report("rpt-order", items=items, smry=_summary(total_fingerprints=2))
        store.save(r)
        tampered = r.model_copy(
            update={
                "report_id": "rpt-tamper-order",
                "requested_fingerprint_ids": ("fp-2", "fp-1"),
            }
        )
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)
