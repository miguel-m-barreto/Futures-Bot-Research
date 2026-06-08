from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.replay import (
    ReplayTimelineCoverageIssueSeverity,
    ReplayTimelineCoverageReport,
    ReplayTimelineCoverageStatus,
    ReplayTimelineCoverageSummary,
)
from futures_bot.domain.research import TemporalWindow, TemporalWindowKind
from futures_bot.infrastructure.replay.in_memory import (
    InMemoryReplayTimelineCoverageReportStore,
)
from futures_bot.ports.replay import ReplayTimelineCoverageReportStorePort


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _window() -> TemporalWindow:
    return TemporalWindow(
        kind=TemporalWindowKind.TEST,
        start_at=_utc(0),
        end_at=_utc(10),
        window_id="tw-1",
    )


def _summary(
    severity_counts: dict[ReplayTimelineCoverageIssueSeverity, int] | None = None,
) -> ReplayTimelineCoverageSummary:
    return ReplayTimelineCoverageSummary(
        total_events=0,
        event_count_by_kind={},
        event_count_by_instrument={},
        event_count_by_dataset={},
        issue_count_by_severity=severity_counts or {},
    )


def _report(
    report_id: str = "report-1",
    *,
    timeline_id: str = "tl-1",
    replay_plan_id: str = "plan-1",
    status: ReplayTimelineCoverageStatus = ReplayTimelineCoverageStatus.GENERATED,
    generated_at: datetime | None = None,
) -> ReplayTimelineCoverageReport:
    return ReplayTimelineCoverageReport(
        report_id=report_id,
        timeline_id=timeline_id,
        replay_plan_id=replay_plan_id,
        temporal_window=_window(),
        generated_at=generated_at or _utc(0),
        status=status,
        summary=_summary(),
    )


class TestInMemoryReplayTimelineCoverageReportStoreConformance:
    def test_conforms_to_port(self) -> None:
        _: ReplayTimelineCoverageReportStorePort = InMemoryReplayTimelineCoverageReportStore()


class TestInMemoryReplayTimelineCoverageReportStore:
    def test_save_and_load_round_trip(self) -> None:
        store = InMemoryReplayTimelineCoverageReportStore()
        r = _report()
        store.save(r)
        loaded = store.load("report-1")
        assert loaded == r

    def test_load_returns_none_for_missing(self) -> None:
        store = InMemoryReplayTimelineCoverageReportStore()
        assert store.load("nonexistent") is None

    def test_idempotent_save_accepted(self) -> None:
        store = InMemoryReplayTimelineCoverageReportStore()
        r = _report()
        store.save(r)
        store.save(r)
        assert store.load("report-1") == r

    def test_conflict_rejected(self) -> None:
        store = InMemoryReplayTimelineCoverageReportStore()
        r1 = _report("r-1", timeline_id="tl-1")
        r2 = _report("r-1", timeline_id="tl-2")
        store.save(r1)
        with pytest.raises(ValueError, match="conflict"):
            store.save(r2)

    def test_model_copy_invalid_report_rejected(self) -> None:
        store = InMemoryReplayTimelineCoverageReportStore()
        r = _report()
        store.save(r)
        invalid = r.model_copy(update={"report_id": ""})
        with pytest.raises((ValidationError, ValueError)):
            store.save(invalid)

    def test_list_for_timeline_deterministic_order(self) -> None:
        store = InMemoryReplayTimelineCoverageReportStore()
        rb = _report("r-b", timeline_id="tl-1", generated_at=_utc(2))
        ra = _report("r-a", timeline_id="tl-1", generated_at=_utc(1))
        store.save(rb)
        store.save(ra)
        results = store.list_for_timeline("tl-1")
        assert [r.report_id for r in results] == ["r-a", "r-b"]

    def test_list_for_timeline_same_generated_at_sorted_by_id(self) -> None:
        store = InMemoryReplayTimelineCoverageReportStore()
        rz = _report("r-z", timeline_id="tl-1", generated_at=_utc(1))
        ra = _report("r-a", timeline_id="tl-1", generated_at=_utc(1))
        store.save(rz)
        store.save(ra)
        results = store.list_for_timeline("tl-1")
        assert [r.report_id for r in results] == ["r-a", "r-z"]

    def test_list_for_timeline_filters_by_timeline(self) -> None:
        store = InMemoryReplayTimelineCoverageReportStore()
        r1 = _report("r-1", timeline_id="tl-1")
        r2 = _report("r-2", timeline_id="tl-2")
        store.save(r1)
        store.save(r2)
        results = store.list_for_timeline("tl-1")
        assert len(results) == 1
        assert results[0].report_id == "r-1"

    def test_list_for_unknown_timeline_returns_empty(self) -> None:
        store = InMemoryReplayTimelineCoverageReportStore()
        assert store.list_for_timeline("no-such-timeline") == ()

    def test_multiple_reports_same_timeline(self) -> None:
        store = InMemoryReplayTimelineCoverageReportStore()
        for i in range(3):
            store.save(_report(f"r-{i}", timeline_id="tl-1", generated_at=_utc(i)))
        results = store.list_for_timeline("tl-1")
        assert len(results) == 3
        assert [r.report_id for r in results] == ["r-0", "r-1", "r-2"]

    def test_list_for_replay_plan_returns_only_matching(self) -> None:
        store = InMemoryReplayTimelineCoverageReportStore()
        r1 = _report("r-1", replay_plan_id="plan-A")
        r2 = _report("r-2", replay_plan_id="plan-B")
        store.save(r1)
        store.save(r2)
        results = store.list_for_replay_plan("plan-A")
        assert len(results) == 1
        assert results[0].report_id == "r-1"

    def test_list_for_replay_plan_deterministic_order(self) -> None:
        store = InMemoryReplayTimelineCoverageReportStore()
        rb = _report("r-b", replay_plan_id="plan-1", generated_at=_utc(2))
        ra = _report("r-a", replay_plan_id="plan-1", generated_at=_utc(1))
        store.save(rb)
        store.save(ra)
        results = store.list_for_replay_plan("plan-1")
        assert [r.report_id for r in results] == ["r-a", "r-b"]

    def test_list_for_unknown_replay_plan_returns_empty(self) -> None:
        store = InMemoryReplayTimelineCoverageReportStore()
        assert store.list_for_replay_plan("no-such-plan") == ()

    def test_model_copy_inconsistent_summary_rejected(self) -> None:
        store = InMemoryReplayTimelineCoverageReportStore()
        r = _report("r-base")
        store.save(r)
        # Summary claims 99 INFO issues but the report has zero issues;
        # model_copy bypasses validators, store revalidation must catch this.
        lying_summary = ReplayTimelineCoverageSummary(
            total_events=0,
            event_count_by_kind={},
            event_count_by_instrument={},
            event_count_by_dataset={},
            issue_count_by_severity={ReplayTimelineCoverageIssueSeverity.INFO: 99},
        )
        tampered = r.model_copy(update={"report_id": "r-tampered", "summary": lying_summary})
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)
