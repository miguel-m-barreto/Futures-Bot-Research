from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from futures_bot.domain.replay import (
    ReplayInputKind,
    ReplayTimelineCoverageDiffKind,
    ReplayTimelineCoverageDiffSeverity,
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

if TYPE_CHECKING:
    from futures_bot.domain.replay import ReplayTimelineCoverageDiff


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _window() -> TemporalWindow:
    return TemporalWindow(
        kind=TemporalWindowKind.TEST,
        start_at=_utc(0),
        end_at=_utc(10),
        window_id="tw-1",
    )


def _empty_summary(
    severity_counts: dict[ReplayTimelineCoverageIssueSeverity, int] | None = None,
) -> ReplayTimelineCoverageSummary:
    return ReplayTimelineCoverageSummary(
        total_events=0,
        event_count_by_kind={},
        event_count_by_instrument={},
        event_count_by_dataset={},
        issue_count_by_severity=severity_counts or {},
    )


def _simple_summary(n: int) -> ReplayTimelineCoverageSummary:
    if n == 0:
        return _empty_summary()
    return ReplayTimelineCoverageSummary(
        total_events=n,
        first_event_at=_utc(1),
        last_event_at=_utc(2),
        event_count_by_kind={ReplayInputKind.MARK_PRICE: n},
        event_count_by_instrument={"k:S:U": n},
        event_count_by_dataset={"ds": n},
        issue_count_by_severity={},
    )


def _summary(  # noqa: PLR0913
    total_events: int,
    *,
    kind_counts: dict[ReplayInputKind, int] | None = None,
    instrument_counts: dict[str, int] | None = None,
    dataset_counts: dict[str, int] | None = None,
    severity_counts: dict[ReplayTimelineCoverageIssueSeverity, int] | None = None,
    first_event_at: datetime | None = None,
    last_event_at: datetime | None = None,
) -> ReplayTimelineCoverageSummary:
    return ReplayTimelineCoverageSummary(
        total_events=total_events,
        first_event_at=first_event_at or (_utc(1) if total_events > 0 else None),
        last_event_at=last_event_at or (_utc(2) if total_events > 0 else None),
        event_count_by_kind=kind_counts or {},
        event_count_by_instrument=instrument_counts or {},
        event_count_by_dataset=dataset_counts or {},
        issue_count_by_severity=severity_counts or {},
    )


def _report(  # noqa: PLR0913
    report_id: str = "report-1",
    *,
    timeline_id: str = "tl-1",
    replay_plan_id: str = "plan-1",
    summary: ReplayTimelineCoverageSummary | None = None,
    issues: tuple[ReplayTimelineCoverageIssue, ...] = (),
    status: ReplayTimelineCoverageStatus = ReplayTimelineCoverageStatus.GENERATED,
    expected_input_kinds: tuple[ReplayInputKind, ...] = (),
    expected_instrument_keys: tuple[str, ...] = (),
) -> ReplayTimelineCoverageReport:
    return ReplayTimelineCoverageReport(
        report_id=report_id,
        timeline_id=timeline_id,
        replay_plan_id=replay_plan_id,
        temporal_window=_window(),
        generated_at=_utc(0),
        status=status,
        summary=summary or _empty_summary(),
        issues=issues,
        expected_input_kinds=expected_input_kinds,
        expected_instrument_keys=expected_instrument_keys,
    )


def _setup(
    baseline: ReplayTimelineCoverageReport,
    candidate: ReplayTimelineCoverageReport,
) -> tuple[
    InMemoryReplayTimelineCoverageReportStore,
    InMemoryReplayTimelineCoverageDiffStore,
    LocalReplayTimelineCoverageDiffer,
]:
    report_store = InMemoryReplayTimelineCoverageReportStore()
    diff_store = InMemoryReplayTimelineCoverageDiffStore()
    report_store.save(baseline)
    report_store.save(candidate)
    differ = LocalReplayTimelineCoverageDiffer(
        report_store=report_store,
        diff_store=diff_store,
        now=lambda: _utc(0),
    )
    return report_store, diff_store, differ


def _items_of_kind(
    diff: ReplayTimelineCoverageDiff,
    kind: ReplayTimelineCoverageDiffKind,
) -> list[object]:
    return [i for i in diff.items if i.kind is kind]


class TestLocalReplayTimelineCoverageDifferBasic:
    def test_diff_no_changes_has_zero_items(self) -> None:
        base = _report("base-1")
        cand = _report("cand-1")
        _, _, differ = _setup(base, cand)
        diff = differ.generate_diff("d-1", "base-1", "cand-1")
        assert diff.summary.total_items == 0
        assert diff.items == ()
        assert not diff.summary.has_errors
        assert not diff.summary.has_warnings

    def test_diff_saved_to_store(self) -> None:
        base = _report("base-1")
        cand = _report("cand-1")
        _, diff_store, differ = _setup(base, cand)
        differ.generate_diff("d-1", "base-1", "cand-1")
        assert diff_store.load("d-1") is not None

    def test_load_diff_returns_saved(self) -> None:
        base = _report("base-1")
        cand = _report("cand-1")
        _, _, differ = _setup(base, cand)
        differ.generate_diff("d-1", "base-1", "cand-1")
        loaded = differ.load_diff("d-1")
        assert loaded is not None
        assert loaded.diff_id == "d-1"

    def test_load_diff_returns_none_for_missing(self) -> None:
        base = _report("base-1")
        cand = _report("cand-1")
        _, _, differ = _setup(base, cand)
        assert differ.load_diff("no-such-diff") is None

    def test_missing_baseline_raises(self) -> None:
        report_store = InMemoryReplayTimelineCoverageReportStore()
        diff_store = InMemoryReplayTimelineCoverageDiffStore()
        report_store.save(_report("cand-1"))
        differ = LocalReplayTimelineCoverageDiffer(
            report_store=report_store,
            diff_store=diff_store,
            now=lambda: _utc(0),
        )
        with pytest.raises(ValueError, match="baseline report not found"):
            differ.generate_diff("d-1", "no-such-base", "cand-1")

    def test_missing_candidate_raises(self) -> None:
        report_store = InMemoryReplayTimelineCoverageReportStore()
        diff_store = InMemoryReplayTimelineCoverageDiffStore()
        report_store.save(_report("base-1"))
        differ = LocalReplayTimelineCoverageDiffer(
            report_store=report_store,
            diff_store=diff_store,
            now=lambda: _utc(0),
        )
        with pytest.raises(ValueError, match="candidate report not found"):
            differ.generate_diff("d-1", "base-1", "no-such-cand")

    def test_same_report_id_rejected(self) -> None:
        base = _report("rep-1")
        report_store = InMemoryReplayTimelineCoverageReportStore()
        diff_store = InMemoryReplayTimelineCoverageDiffStore()
        report_store.save(base)
        differ = LocalReplayTimelineCoverageDiffer(
            report_store=report_store,
            diff_store=diff_store,
            now=lambda: _utc(0),
        )
        with pytest.raises(ValueError, match="must differ"):
            differ.generate_diff("d-1", "rep-1", "rep-1")

    def test_diffs_for_report_returns_tuple(self) -> None:
        base = _report("base-1")
        cand = _report("cand-1")
        _, _, differ = _setup(base, cand)
        differ.generate_diff("d-1", "base-1", "cand-1")
        results = differ.diffs_for_report("base-1")
        assert isinstance(results, tuple)
        assert len(results) == 1

    def test_diffs_for_replay_plan_returns_tuple(self) -> None:
        base = _report("base-1", replay_plan_id="plan-A")
        cand = _report("cand-1", replay_plan_id="plan-A")
        _, _, differ = _setup(base, cand)
        differ.generate_diff("d-1", "base-1", "cand-1")
        results = differ.diffs_for_replay_plan("plan-A")
        assert isinstance(results, tuple)
        assert len(results) == 1

    def test_no_replay_execution_attributes(self) -> None:
        base = _report("base-1")
        cand = _report("cand-1")
        _, _, differ = _setup(base, cand)
        diff = differ.generate_diff("d-1", "base-1", "cand-1")
        assert not hasattr(diff, "pnl")
        assert not hasattr(diff, "evaluation_result")
        assert not hasattr(diff, "metric_observations")
        assert not hasattr(differ, "run_replay")
        assert not hasattr(differ, "execute_strategy")


class TestLocalReplayTimelineCoverageDifferTotalEvents:
    def test_detects_total_event_count_increase(self) -> None:
        base = _report("base-1", summary=_simple_summary(2))
        cand = _report("cand-1", summary=_simple_summary(4))
        _, _, differ = _setup(base, cand)
        diff = differ.generate_diff("d-1", "base-1", "cand-1")
        total_items = _items_of_kind(diff, ReplayTimelineCoverageDiffKind.TOTAL_EVENT_COUNT_CHANGED)
        assert len(total_items) == 1
        item = total_items[0]
        assert item.numeric_delta == 2
        assert item.severity is ReplayTimelineCoverageDiffSeverity.INFO

    def test_detects_total_event_count_decrease_creates_warning(self) -> None:
        base = _report("base-1", summary=_simple_summary(4))
        cand = _report("cand-1", summary=_simple_summary(2))
        _, _, differ = _setup(base, cand)
        diff = differ.generate_diff("d-1", "base-1", "cand-1")
        total_items = _items_of_kind(diff, ReplayTimelineCoverageDiffKind.TOTAL_EVENT_COUNT_CHANGED)
        assert len(total_items) == 1
        item = total_items[0]
        assert item.severity is ReplayTimelineCoverageDiffSeverity.WARNING
        assert item.numeric_delta == -2

    def test_candidate_zero_from_nonzero_baseline_creates_error(self) -> None:
        base = _report("base-1", summary=_simple_summary(2))
        cand = _report("cand-1", summary=_empty_summary())
        _, _, differ = _setup(base, cand)
        diff = differ.generate_diff("d-1", "base-1", "cand-1")
        total_items = _items_of_kind(diff, ReplayTimelineCoverageDiffKind.TOTAL_EVENT_COUNT_CHANGED)
        assert len(total_items) == 1
        assert total_items[0].severity is ReplayTimelineCoverageDiffSeverity.ERROR
        assert diff.summary.has_errors


class TestLocalReplayTimelineCoverageDifferKindCounts:
    def test_detects_kind_count_change(self) -> None:
        b_sum = _summary(
            3,
            kind_counts={ReplayInputKind.MARK_PRICE: 2, ReplayInputKind.OHLCV_BAR: 1},
            instrument_counts={"k:S:U": 3},
            dataset_counts={"ds": 3},
        )
        c_sum = _summary(
            3,
            kind_counts={ReplayInputKind.MARK_PRICE: 1, ReplayInputKind.OHLCV_BAR: 2},
            instrument_counts={"k:S:U": 3},
            dataset_counts={"ds": 3},
        )
        base = _report("base-1", summary=b_sum)
        cand = _report("cand-1", summary=c_sum)
        _, _, differ = _setup(base, cand)
        diff = differ.generate_diff("d-1", "base-1", "cand-1")
        kind_items = _items_of_kind(diff, ReplayTimelineCoverageDiffKind.KIND_COUNT_CHANGED)
        assert len(kind_items) == 2

    def test_kind_count_decrease_creates_warning(self) -> None:
        base = _report("base-1", summary=_simple_summary(2))
        cand = _report("cand-1", summary=_simple_summary(1))
        _, _, differ = _setup(base, cand)
        diff = differ.generate_diff("d-1", "base-1", "cand-1")
        kind_items = _items_of_kind(diff, ReplayTimelineCoverageDiffKind.KIND_COUNT_CHANGED)
        assert any(i.severity is ReplayTimelineCoverageDiffSeverity.WARNING for i in kind_items)

    def test_deterministic_kind_item_ids(self) -> None:
        base = _report("base-1", summary=_simple_summary(2))
        cand = _report("cand-1", summary=_simple_summary(1))
        _, _, differ = _setup(base, cand)
        diff = differ.generate_diff("d-1", "base-1", "cand-1")
        kind_items = _items_of_kind(diff, ReplayTimelineCoverageDiffKind.KIND_COUNT_CHANGED)
        assert any(i.item_id == "d-1:kind:MARK_PRICE" for i in kind_items)


class TestLocalReplayTimelineCoverageDifferInstrumentCounts:
    def test_detects_instrument_count_change(self) -> None:
        b_sum = _summary(
            4,
            kind_counts={ReplayInputKind.MARK_PRICE: 4},
            instrument_counts={"binance:BTC:USDT": 4},
            dataset_counts={"ds": 4},
        )
        c_sum = _summary(
            3,
            kind_counts={ReplayInputKind.MARK_PRICE: 3},
            instrument_counts={"binance:BTC:USDT": 3},
            dataset_counts={"ds": 3},
        )
        base = _report("base-1", summary=b_sum)
        cand = _report("cand-1", summary=c_sum)
        _, _, differ = _setup(base, cand)
        diff = differ.generate_diff("d-1", "base-1", "cand-1")
        instr_items = _items_of_kind(diff, ReplayTimelineCoverageDiffKind.INSTRUMENT_COUNT_CHANGED)
        assert len(instr_items) == 1
        assert instr_items[0].item_id == "d-1:instrument:binance:BTC:USDT"
        assert instr_items[0].severity is ReplayTimelineCoverageDiffSeverity.WARNING

    def test_instrument_count_increase_creates_info(self) -> None:
        base = _report("base-1", summary=_simple_summary(2))
        cand = _report("cand-1", summary=_simple_summary(4))
        _, _, differ = _setup(base, cand)
        diff = differ.generate_diff("d-1", "base-1", "cand-1")
        instr_items = _items_of_kind(diff, ReplayTimelineCoverageDiffKind.INSTRUMENT_COUNT_CHANGED)
        assert all(i.severity is ReplayTimelineCoverageDiffSeverity.INFO for i in instr_items)


class TestLocalReplayTimelineCoverageDifferDatasetCounts:
    def test_detects_dataset_count_change(self) -> None:
        b_sum = _summary(
            3,
            kind_counts={ReplayInputKind.MARK_PRICE: 3},
            instrument_counts={"k:S:U": 3},
            dataset_counts={"ds-1": 3},
        )
        c_sum = _summary(
            3,
            kind_counts={ReplayInputKind.MARK_PRICE: 3},
            instrument_counts={"k:S:U": 3},
            dataset_counts={"ds-1": 2, "ds-2": 1},
        )
        base = _report("base-1", summary=b_sum)
        cand = _report("cand-1", summary=c_sum)
        _, _, differ = _setup(base, cand)
        diff = differ.generate_diff("d-1", "base-1", "cand-1")
        ds_items = _items_of_kind(diff, ReplayTimelineCoverageDiffKind.DATASET_COUNT_CHANGED)
        assert len(ds_items) == 2
        assert any(i.item_id == "d-1:dataset:ds-1" for i in ds_items)
        assert any(i.item_id == "d-1:dataset:ds-2" for i in ds_items)


class TestLocalReplayTimelineCoverageDifferIssueSeverityCounts:
    def test_detects_issue_severity_count_change(self) -> None:
        base = _report("base-1")
        candidate_issue = ReplayTimelineCoverageIssue(
            issue_id="i-1",
            kind=ReplayTimelineCoverageIssueKind.OTHER,
            severity=ReplayTimelineCoverageIssueSeverity.WARNING,
            message="a warning",
        )
        cand = _report(
            "cand-1",
            summary=_empty_summary({ReplayTimelineCoverageIssueSeverity.WARNING: 1}),
            issues=(candidate_issue,),
        )
        _, _, differ = _setup(base, cand)
        diff = differ.generate_diff("d-1", "base-1", "cand-1")
        sev_kind = ReplayTimelineCoverageDiffKind.ISSUE_SEVERITY_COUNT_CHANGED
        sev_items = _items_of_kind(diff, sev_kind)
        assert len(sev_items) == 1
        assert sev_items[0].item_id == "d-1:issue-severity:WARNING"
        assert sev_items[0].severity is ReplayTimelineCoverageDiffSeverity.WARNING

    def test_error_issue_count_increase_creates_error(self) -> None:
        base = _report("base-1")
        candidate_issue = ReplayTimelineCoverageIssue(
            issue_id="i-1",
            kind=ReplayTimelineCoverageIssueKind.OTHER,
            severity=ReplayTimelineCoverageIssueSeverity.ERROR,
            message="an error",
        )
        cand = _report(
            "cand-1",
            summary=_empty_summary({ReplayTimelineCoverageIssueSeverity.ERROR: 1}),
            issues=(candidate_issue,),
        )
        _, _, differ = _setup(base, cand)
        diff = differ.generate_diff("d-1", "base-1", "cand-1")
        sev_kind = ReplayTimelineCoverageDiffKind.ISSUE_SEVERITY_COUNT_CHANGED
        sev_items = _items_of_kind(diff, sev_kind)
        assert any(i.severity is ReplayTimelineCoverageDiffSeverity.ERROR for i in sev_items)
        assert diff.summary.has_errors


class TestLocalReplayTimelineCoverageDifferExpectedSets:
    def test_detects_expected_kind_set_change(self) -> None:
        base = _report("base-1", expected_input_kinds=(ReplayInputKind.MARK_PRICE,))
        cand = _report("cand-1", expected_input_kinds=(ReplayInputKind.OHLCV_BAR,))
        _, _, differ = _setup(base, cand)
        diff = differ.generate_diff("d-1", "base-1", "cand-1")
        eks_kind = ReplayTimelineCoverageDiffKind.EXPECTED_KIND_SET_CHANGED
        kind_set_items = _items_of_kind(diff, eks_kind)
        assert len(kind_set_items) == 2
        item_ids = {i.item_id for i in kind_set_items}
        assert "d-1:expected-kind:MARK_PRICE" in item_ids
        assert "d-1:expected-kind:OHLCV_BAR" in item_ids

    def test_no_expected_kind_change_when_sets_equal(self) -> None:
        expected = (ReplayInputKind.MARK_PRICE,)
        base = _report("base-1", expected_input_kinds=expected)
        cand = _report("cand-1", expected_input_kinds=expected)
        _, _, differ = _setup(base, cand)
        diff = differ.generate_diff("d-1", "base-1", "cand-1")
        eks_kind = ReplayTimelineCoverageDiffKind.EXPECTED_KIND_SET_CHANGED
        kind_set_items = _items_of_kind(diff, eks_kind)
        assert len(kind_set_items) == 0

    def test_detects_expected_instrument_set_change(self) -> None:
        base = _report("base-1", expected_instrument_keys=("binance:BTC:USDT",))
        cand = _report("cand-1", expected_instrument_keys=("binance:ETH:USDT",))
        _, _, differ = _setup(base, cand)
        diff = differ.generate_diff("d-1", "base-1", "cand-1")
        instr_set_items = _items_of_kind(
            diff, ReplayTimelineCoverageDiffKind.EXPECTED_INSTRUMENT_SET_CHANGED
        )
        assert len(instr_set_items) == 2
        item_ids = {i.item_id for i in instr_set_items}
        assert "d-1:expected-instrument:binance:BTC:USDT" in item_ids
        assert "d-1:expected-instrument:binance:ETH:USDT" in item_ids


class TestLocalReplayTimelineCoverageDifferEventTimes:
    def test_detects_first_event_time_change(self) -> None:
        b_sum = _summary(
            1,
            kind_counts={ReplayInputKind.MARK_PRICE: 1},
            instrument_counts={"k:S:U": 1},
            dataset_counts={"ds": 1},
            first_event_at=_utc(1),
            last_event_at=_utc(5),
        )
        c_sum = _summary(
            1,
            kind_counts={ReplayInputKind.MARK_PRICE: 1},
            instrument_counts={"k:S:U": 1},
            dataset_counts={"ds": 1},
            first_event_at=_utc(2),
            last_event_at=_utc(5),
        )
        base = _report("base-1", summary=b_sum)
        cand = _report("cand-1", summary=c_sum)
        _, _, differ = _setup(base, cand)
        diff = differ.generate_diff("d-1", "base-1", "cand-1")
        time_items = _items_of_kind(diff, ReplayTimelineCoverageDiffKind.FIRST_EVENT_TIME_CHANGED)
        assert len(time_items) == 1
        assert time_items[0].item_id == "d-1:first-event-at"

    def test_detects_last_event_time_change(self) -> None:
        b_sum = _summary(
            1,
            kind_counts={ReplayInputKind.MARK_PRICE: 1},
            instrument_counts={"k:S:U": 1},
            dataset_counts={"ds": 1},
            first_event_at=_utc(1),
            last_event_at=_utc(5),
        )
        c_sum = _summary(
            1,
            kind_counts={ReplayInputKind.MARK_PRICE: 1},
            instrument_counts={"k:S:U": 1},
            dataset_counts={"ds": 1},
            first_event_at=_utc(1),
            last_event_at=_utc(6),
        )
        base = _report("base-1", summary=b_sum)
        cand = _report("cand-1", summary=c_sum)
        _, _, differ = _setup(base, cand)
        diff = differ.generate_diff("d-1", "base-1", "cand-1")
        time_items = _items_of_kind(diff, ReplayTimelineCoverageDiffKind.LAST_EVENT_TIME_CHANGED)
        assert len(time_items) == 1
        assert time_items[0].item_id == "d-1:last-event-at"

    def test_no_time_items_when_times_match(self) -> None:
        s = _summary(
            1,
            kind_counts={ReplayInputKind.MARK_PRICE: 1},
            instrument_counts={"k:S:U": 1},
            dataset_counts={"ds": 1},
            first_event_at=_utc(1),
            last_event_at=_utc(5),
        )
        base = _report("base-1", summary=s)
        cand = _report("cand-1", summary=s)
        _, _, differ = _setup(base, cand)
        diff = differ.generate_diff("d-1", "base-1", "cand-1")
        time_kinds = {
            ReplayTimelineCoverageDiffKind.FIRST_EVENT_TIME_CHANGED,
            ReplayTimelineCoverageDiffKind.LAST_EVENT_TIME_CHANGED,
        }
        time_items = [i for i in diff.items if i.kind in time_kinds]
        assert len(time_items) == 0


class TestLocalReplayTimelineCoverageDifferStatus:
    def test_detects_report_status_change(self) -> None:
        base = _report("base-1", status=ReplayTimelineCoverageStatus.GENERATED)
        cand = _report("cand-1", status=ReplayTimelineCoverageStatus.INVALIDATED)
        _, _, differ = _setup(base, cand)
        diff = differ.generate_diff("d-1", "base-1", "cand-1")
        status_items = _items_of_kind(diff, ReplayTimelineCoverageDiffKind.REPORT_STATUS_CHANGED)
        assert len(status_items) == 1
        assert status_items[0].item_id == "d-1:status"
        assert status_items[0].baseline_value == "GENERATED"
        assert status_items[0].candidate_value == "INVALIDATED"

    def test_no_status_item_when_status_equal(self) -> None:
        base = _report("base-1", status=ReplayTimelineCoverageStatus.GENERATED)
        cand = _report("cand-1", status=ReplayTimelineCoverageStatus.GENERATED)
        _, _, differ = _setup(base, cand)
        diff = differ.generate_diff("d-1", "base-1", "cand-1")
        status_items = _items_of_kind(diff, ReplayTimelineCoverageDiffKind.REPORT_STATUS_CHANGED)
        assert len(status_items) == 0


class TestLocalReplayTimelineCoverageDifferOrdering:
    def test_item_ordering_status_before_total_events(self) -> None:
        base = _report("base-1", status=ReplayTimelineCoverageStatus.GENERATED)
        cand_summary = _simple_summary(2)
        cand = _report(
            "cand-1",
            status=ReplayTimelineCoverageStatus.INVALIDATED,
            summary=cand_summary,
        )
        _, _, differ = _setup(base, cand)
        diff = differ.generate_diff("d-1", "base-1", "cand-1")
        ids = [i.item_id for i in diff.items]
        status_idx = next(i for i, iid in enumerate(ids) if iid == "d-1:status")
        total_idx = next(i for i, iid in enumerate(ids) if iid == "d-1:total-events")
        assert status_idx < total_idx
