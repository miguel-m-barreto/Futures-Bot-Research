from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.replay import (
    ReplayReadinessIssue,
    ReplayReadinessIssueKind,
    ReplayReadinessIssueSeverity,
    ReplayReadinessReport,
    ReplayReadinessStatus,
    ReplayReadinessSummary,
)
from futures_bot.infrastructure.replay.in_memory import InMemoryReplayReadinessReportStore
from futures_bot.ports.replay import ReplayReadinessReportStorePort


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _summary(  # noqa: PLR0913
    blocking: int = 0,
    warning: int = 0,
    info: int = 0,
    total_fps: int = 0,
    latest_batch_report_id: str | None = None,
    latest_batch_all_valid: bool | None = None,
    latest_batch_total_fingerprints: int | None = None,
    latest_batch_total_issues: int | None = None,
) -> ReplayReadinessSummary:
    return ReplayReadinessSummary(
        total_fingerprints=total_fps,
        latest_batch_report_id=latest_batch_report_id,
        latest_batch_all_valid=latest_batch_all_valid,
        latest_batch_total_fingerprints=latest_batch_total_fingerprints,
        latest_batch_total_issues=latest_batch_total_issues,
        blocking_issue_count=blocking,
        warning_issue_count=warning,
        info_issue_count=info,
    )


def _blocked_report(
    report_id: str = "rpt-1",
    replay_plan_id: str = "plan-1",
    generated_at: datetime | None = None,
) -> ReplayReadinessReport:
    issue = ReplayReadinessIssue(
        issue_id="iss-1",
        kind=ReplayReadinessIssueKind.NO_FINGERPRINTS,
        severity=ReplayReadinessIssueSeverity.ERROR,
        message="no fingerprints",
    )
    return ReplayReadinessReport(
        report_id=report_id,
        replay_plan_id=replay_plan_id,
        checked_at=generated_at or _utc(0),
        status=ReplayReadinessStatus.BLOCKED,
        summary=_summary(blocking=1),
        issues=(issue,),
    )


def _ready_report(
    report_id: str = "rpt-1",
    replay_plan_id: str = "plan-1",
    generated_at: datetime | None = None,
) -> ReplayReadinessReport:
    return ReplayReadinessReport(
        report_id=report_id,
        replay_plan_id=replay_plan_id,
        checked_at=generated_at or _utc(0),
        status=ReplayReadinessStatus.READY,
        summary=_summary(
            total_fps=2,
            latest_batch_report_id="b1",
            latest_batch_all_valid=True,
            latest_batch_total_fingerprints=2,
            latest_batch_total_issues=0,
        ),
    )


class TestInMemoryReplayReadinessReportStoreConformance:
    def test_conforms_to_port(self) -> None:
        _: ReplayReadinessReportStorePort = InMemoryReplayReadinessReportStore()


class TestInMemoryReplayReadinessReportStore:
    def test_save_and_load_round_trip(self) -> None:
        store = InMemoryReplayReadinessReportStore()
        r = _blocked_report()
        store.save(r)
        assert store.load("rpt-1") == r

    def test_load_returns_none_for_missing(self) -> None:
        store = InMemoryReplayReadinessReportStore()
        assert store.load("nonexistent") is None

    def test_idempotent_save_accepted(self) -> None:
        store = InMemoryReplayReadinessReportStore()
        r = _blocked_report()
        store.save(r)
        store.save(r)
        assert store.load("rpt-1") == r

    def test_conflict_rejected(self) -> None:
        store = InMemoryReplayReadinessReportStore()
        r1 = _blocked_report("rpt-1", replay_plan_id="plan-A")
        r2 = _blocked_report("rpt-1", replay_plan_id="plan-B")
        store.save(r1)
        with pytest.raises(ValueError, match="conflict"):
            store.save(r2)

    def test_list_all_empty(self) -> None:
        store = InMemoryReplayReadinessReportStore()
        assert store.list_all() == ()

    def test_list_all_deterministic_order(self) -> None:
        store = InMemoryReplayReadinessReportStore()
        rb = _blocked_report("rpt-b", generated_at=_utc(2))
        ra = _blocked_report("rpt-a", generated_at=_utc(1))
        store.save(rb)
        store.save(ra)
        results = store.list_all()
        assert [r.report_id for r in results] == ["rpt-a", "rpt-b"]

    def test_list_all_same_time_sorted_by_id(self) -> None:
        store = InMemoryReplayReadinessReportStore()
        rz = _blocked_report("rpt-z", generated_at=_utc(1))
        ra = _blocked_report("rpt-a", generated_at=_utc(1))
        store.save(rz)
        store.save(ra)
        results = store.list_all()
        assert [r.report_id for r in results] == ["rpt-a", "rpt-z"]

    def test_list_for_replay_plan_filters(self) -> None:
        store = InMemoryReplayReadinessReportStore()
        ra = _blocked_report("rpt-a", replay_plan_id="plan-A")
        rb = _blocked_report("rpt-b", replay_plan_id="plan-B")
        store.save(ra)
        store.save(rb)
        results = store.list_for_replay_plan("plan-A")
        assert len(results) == 1
        assert results[0].report_id == "rpt-a"

    def test_list_for_replay_plan_multiple_results_ordered(self) -> None:
        store = InMemoryReplayReadinessReportStore()
        rb = _blocked_report("rpt-b", generated_at=_utc(2))
        ra = _blocked_report("rpt-a", generated_at=_utc(1))
        store.save(rb)
        store.save(ra)
        results = store.list_for_replay_plan("plan-1")
        assert [r.report_id for r in results] == ["rpt-a", "rpt-b"]

    def test_model_copy_invalid_report_id_rejected(self) -> None:
        store = InMemoryReplayReadinessReportStore()
        r = _blocked_report()
        store.save(r)
        tampered = r.model_copy(update={"report_id": ""})
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_summary_mismatch_rejected(self) -> None:
        store = InMemoryReplayReadinessReportStore()
        r = _blocked_report()
        store.save(r)
        bad_summary = _summary(blocking=99)
        tampered = r.model_copy(update={"report_id": "rpt-tamper", "summary": bad_summary})
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_duplicate_issue_ids_rejected(self) -> None:
        store = InMemoryReplayReadinessReportStore()
        r = _blocked_report()
        store.save(r)
        dup_issue = ReplayReadinessIssue(
            issue_id="iss-1",
            kind=ReplayReadinessIssueKind.BATCH_HAS_MISMATCHES,
            severity=ReplayReadinessIssueSeverity.ERROR,
            message="another error",
        )
        bad_summary = _summary(blocking=2)
        tampered = r.model_copy(
            update={
                "report_id": "rpt-tamper-dup",
                "issues": (r.issues[0], dup_issue),
                "summary": bad_summary,
            }
        )
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_ready_latest_batch_total_fingerprints_none_rejected(self) -> None:
        store = InMemoryReplayReadinessReportStore()
        r = _ready_report()
        store.save(r)
        bad_summary = r.summary.model_copy(
            update={"latest_batch_total_fingerprints": None}
        )
        tampered = r.model_copy(
            update={"report_id": "rpt-tamper-none", "summary": bad_summary}
        )

        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_ready_latest_batch_total_fingerprints_mismatch_rejected(
        self,
    ) -> None:
        store = InMemoryReplayReadinessReportStore()
        r = _ready_report()
        store.save(r)
        bad_summary = r.summary.model_copy(
            update={"latest_batch_total_fingerprints": 1}
        )
        tampered = r.model_copy(
            update={"report_id": "rpt-tamper-mismatch", "summary": bad_summary}
        )

        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)
