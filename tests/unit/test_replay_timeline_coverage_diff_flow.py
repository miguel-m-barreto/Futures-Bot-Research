from __future__ import annotations

from datetime import UTC, datetime

from futures_bot.domain.replay import (
    ReplayInputKind,
    ReplayTimelineCoverageDiffKind,
    ReplayTimelineCoverageIssue,
    ReplayTimelineCoverageIssueKind,
    ReplayTimelineCoverageIssueSeverity,
    ReplayTimelineCoverageReport,
    ReplayTimelineCoverageStatus,
    ReplayTimelineCoverageSummary,
)
from futures_bot.domain.research import TemporalWindow, TemporalWindowKind
from futures_bot.infrastructure.replay.in_memory import (
    InMemoryReplayTimelineCoverageDiffStore,
    InMemoryReplayTimelineCoverageReportStore,
)
from futures_bot.replay.local import LocalReplayTimelineCoverageDiffer


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _window() -> TemporalWindow:
    return TemporalWindow(
        kind=TemporalWindowKind.TEST,
        start_at=_utc(0),
        end_at=_utc(10),
        window_id="tw-1",
    )


class TestCoverageDiffFlow:
    def test_full_diff_flow(self) -> None:
        baseline_summary = ReplayTimelineCoverageSummary(
            total_events=4,
            first_event_at=_utc(1),
            last_event_at=_utc(4),
            event_count_by_kind={
                ReplayInputKind.OHLCV_BAR: 2,
                ReplayInputKind.MARK_PRICE: 2,
            },
            event_count_by_instrument={"binance:BTCUSDT:USDT": 4},
            event_count_by_dataset={"ds-1": 4},
            issue_count_by_severity={},
        )
        baseline_report = ReplayTimelineCoverageReport(
            report_id="baseline-1",
            timeline_id="tl-baseline",
            replay_plan_id="plan-1",
            temporal_window=_window(),
            generated_at=_utc(0),
            status=ReplayTimelineCoverageStatus.GENERATED,
            summary=baseline_summary,
            issues=(),
        )

        warning_issue = ReplayTimelineCoverageIssue(
            issue_id="i-1",
            kind=ReplayTimelineCoverageIssueKind.END_COVERAGE_GAP,
            severity=ReplayTimelineCoverageIssueSeverity.WARNING,
            message="End coverage gap",
        )
        candidate_summary = ReplayTimelineCoverageSummary(
            total_events=3,
            first_event_at=_utc(1),
            last_event_at=_utc(3),
            event_count_by_kind={
                ReplayInputKind.OHLCV_BAR: 2,
                ReplayInputKind.MARK_PRICE: 1,
            },
            event_count_by_instrument={"binance:BTCUSDT:USDT": 3},
            event_count_by_dataset={"ds-1": 3},
            issue_count_by_severity={ReplayTimelineCoverageIssueSeverity.WARNING: 1},
        )
        candidate_report = ReplayTimelineCoverageReport(
            report_id="candidate-1",
            timeline_id="tl-candidate",
            replay_plan_id="plan-1",
            temporal_window=_window(),
            generated_at=_utc(1),
            status=ReplayTimelineCoverageStatus.GENERATED,
            summary=candidate_summary,
            issues=(warning_issue,),
        )

        report_store = InMemoryReplayTimelineCoverageReportStore()
        diff_store = InMemoryReplayTimelineCoverageDiffStore()
        report_store.save(baseline_report)
        report_store.save(candidate_report)

        differ = LocalReplayTimelineCoverageDiffer(
            report_store=report_store,
            diff_store=diff_store,
            now=lambda: _utc(2),
        )

        diff = differ.generate_diff("diff-flow-1", "baseline-1", "candidate-1")

        total_items = [
            i for i in diff.items
            if i.kind is ReplayTimelineCoverageDiffKind.TOTAL_EVENT_COUNT_CHANGED
        ]
        assert len(total_items) == 1
        assert total_items[0].numeric_delta == -1

        mark_items = [
            i for i in diff.items
            if i.kind is ReplayTimelineCoverageDiffKind.KIND_COUNT_CHANGED
            and i.key == "MARK_PRICE"
        ]
        assert len(mark_items) == 1
        assert mark_items[0].numeric_delta == -1

        instr_items = [
            i for i in diff.items
            if i.kind is ReplayTimelineCoverageDiffKind.INSTRUMENT_COUNT_CHANGED
        ]
        assert len(instr_items) == 1

        ds_items = [
            i for i in diff.items
            if i.kind is ReplayTimelineCoverageDiffKind.DATASET_COUNT_CHANGED
        ]
        assert len(ds_items) == 1

        sev_items = [
            i for i in diff.items
            if i.kind is ReplayTimelineCoverageDiffKind.ISSUE_SEVERITY_COUNT_CHANGED
        ]
        assert len(sev_items) == 1

        assert diff.summary.has_warnings
        assert not diff.summary.has_errors

        persisted = diff_store.load("diff-flow-1")
        assert persisted is not None
        assert persisted.diff_id == "diff-flow-1"

        assert not hasattr(diff, "pnl")
        assert not hasattr(diff, "metric_observations")
        assert not hasattr(diff, "evaluation_result")

        for item in diff.items:
            assert not hasattr(item, "payload")
            assert not hasattr(item, "record")
