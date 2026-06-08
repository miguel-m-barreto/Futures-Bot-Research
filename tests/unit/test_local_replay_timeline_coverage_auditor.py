from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from futures_bot.domain.replay import (
    ReplayInputBatch,
    ReplayInputKind,
    ReplayInputRecord,
    ReplayInputValidationStatus,
    ReplayInstrumentRef,
    ReplayOrderingPolicy,
    ReplayTimelineCoverageIssueKind,
    ReplayTimelineCoverageIssueSeverity,
    ReplayTimelineCoverageStatus,
)
from futures_bot.domain.research import TemporalWindow, TemporalWindowKind
from futures_bot.infrastructure.replay.in_memory import (
    InMemoryReplayInputBatchStore,
    InMemoryReplayTimelineCoverageReportStore,
    InMemoryReplayTimelineStore,
)
from futures_bot.replay.local import LocalReplayTimelineBuilder, LocalReplayTimelineCoverageAuditor


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _window(start: int = 0, end: int = 10) -> TemporalWindow:
    return TemporalWindow(
        kind=TemporalWindowKind.TEST,
        start_at=_utc(start),
        end_at=_utc(end),
        window_id="tw-1",
    )


def _instrument(symbol: str = "BTCUSDT") -> ReplayInstrumentRef:
    return ReplayInstrumentRef(
        venue="binance",
        symbol=symbol,
        market_type="stablecoin-collateral-futures",
        settlement_asset="USDT",
    )


def _record(
    record_id: str = "rec-1",
    *,
    kind: ReplayInputKind = ReplayInputKind.MARK_PRICE,
    event_time: datetime | None = None,
    source_sequence: int = 0,
    instrument: ReplayInstrumentRef | None = None,
) -> ReplayInputRecord:
    return ReplayInputRecord(
        record_id=record_id,
        kind=kind,
        instrument=instrument or _instrument(),
        event_time=event_time or _utc(1),
        source_sequence=source_sequence,
        payload={"price": Decimal("100")},
    )


def _batch(
    batch_id: str = "batch-1",
    *,
    records: tuple[ReplayInputRecord, ...] | None = None,
    window: TemporalWindow | None = None,
) -> ReplayInputBatch:
    return ReplayInputBatch(
        batch_id=batch_id,
        replay_plan_id="plan-1",
        input_dataset_id="ds-1",
        temporal_window=window or _window(),
        ordering_policy=ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
        records=records or (_record(),),
        created_at=_utc(0),
        validation_status=ReplayInputValidationStatus.VALIDATED,
    )


def _setup_timeline_store(
    *,
    records: tuple[ReplayInputRecord, ...] | None = None,
    window: TemporalWindow | None = None,
) -> tuple[InMemoryReplayTimelineStore, InMemoryReplayInputBatchStore]:
    timeline_store = InMemoryReplayTimelineStore()
    batch_store = InMemoryReplayInputBatchStore()
    w = window or _window()
    batch = _batch(records=records, window=w)
    batch_store.save(batch)
    builder = LocalReplayTimelineBuilder(
        input_batch_store=batch_store,
        timeline_store=timeline_store,
    )
    builder.build_timeline(
        "tl-1",
        "plan-1",
        ("batch-1",),
        w,
        ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
    )
    return timeline_store, batch_store


def _auditor(
    timeline_store: InMemoryReplayTimelineStore | None = None,
    report_store: InMemoryReplayTimelineCoverageReportStore | None = None,
    now: datetime | None = None,
) -> LocalReplayTimelineCoverageAuditor:
    if timeline_store is None:
        timeline_store, _ = _setup_timeline_store()
    if report_store is None:
        report_store = InMemoryReplayTimelineCoverageReportStore()
    fixed_now = now or _utc(0)
    return LocalReplayTimelineCoverageAuditor(
        timeline_store=timeline_store,
        report_store=report_store,
        now=lambda: fixed_now,
    )


class TestLocalReplayTimelineCoverageAuditorBasic:
    def test_generate_report_returns_report(self) -> None:
        auditor = _auditor()
        report = auditor.generate_report("r-1", "tl-1")
        assert report.report_id == "r-1"
        assert report.timeline_id == "tl-1"
        assert report.status is ReplayTimelineCoverageStatus.GENERATED

    def test_generate_report_saves_to_store(self) -> None:
        report_store = InMemoryReplayTimelineCoverageReportStore()
        auditor = _auditor(report_store=report_store)
        auditor.generate_report("r-1", "tl-1")
        assert report_store.load("r-1") is not None

    def test_load_report_returns_saved(self) -> None:
        report_store = InMemoryReplayTimelineCoverageReportStore()
        auditor = _auditor(report_store=report_store)
        auditor.generate_report("r-1", "tl-1")
        loaded = auditor.load_report("r-1")
        assert loaded is not None
        assert loaded.report_id == "r-1"

    def test_load_report_returns_none_for_missing(self) -> None:
        auditor = _auditor()
        assert auditor.load_report("no-such-report") is None

    def test_reports_for_timeline_returns_tuple(self) -> None:
        report_store = InMemoryReplayTimelineCoverageReportStore()
        auditor = _auditor(report_store=report_store)
        auditor.generate_report("r-1", "tl-1")
        results = auditor.reports_for_timeline("tl-1")
        assert isinstance(results, tuple)
        assert len(results) == 1

    def test_unknown_timeline_raises(self) -> None:
        auditor = _auditor()
        with pytest.raises(ValueError, match="timeline not found"):
            auditor.generate_report("r-1", "no-such-timeline")


class TestLocalReplayTimelineCoverageAuditorSummary:
    def test_summary_total_events_matches(self) -> None:
        records = tuple(
            _record(f"r-{i}", event_time=_utc(i + 1), source_sequence=i)
            for i in range(3)
        )
        timeline_store, _ = _setup_timeline_store(records=records)
        auditor = _auditor(timeline_store=timeline_store)
        report = auditor.generate_report("r-1", "tl-1")
        assert report.summary.total_events == 3

    def test_summary_kind_counts(self) -> None:
        records = (
            _record("r-1", kind=ReplayInputKind.MARK_PRICE, event_time=_utc(1)),
            _record("r-2", kind=ReplayInputKind.INDEX_PRICE, event_time=_utc(2), source_sequence=1),
        )
        timeline_store, _ = _setup_timeline_store(records=records)
        auditor = _auditor(timeline_store=timeline_store)
        report = auditor.generate_report("r-1", "tl-1")
        kind_counts = dict(report.summary.event_count_by_kind)
        assert kind_counts[ReplayInputKind.MARK_PRICE] == 1
        assert kind_counts[ReplayInputKind.INDEX_PRICE] == 1

    def test_summary_instrument_counts(self) -> None:
        records = (
            _record("r-1", instrument=_instrument("BTCUSDT"), event_time=_utc(1)),
            _record(
                "r-2",
                instrument=_instrument("BTCUSDT"),
                event_time=_utc(2),
                source_sequence=1,
            ),
        )
        timeline_store, _ = _setup_timeline_store(records=records)
        auditor = _auditor(timeline_store=timeline_store)
        report = auditor.generate_report("r-1", "tl-1")
        assert report.summary.event_count_by_instrument["binance:BTCUSDT:USDT"] == 2

    def test_summary_first_last_event_at(self) -> None:
        records = (
            _record("r-1", event_time=_utc(2)),
            _record("r-2", event_time=_utc(5), source_sequence=1),
        )
        timeline_store, _ = _setup_timeline_store(records=records)
        auditor = _auditor(timeline_store=timeline_store)
        report = auditor.generate_report("r-1", "tl-1")
        assert report.summary.first_event_at == _utc(2)
        assert report.summary.last_event_at == _utc(5)

    def test_empty_timeline_has_none_event_times(self) -> None:
        timeline_store = InMemoryReplayTimelineStore()
        batch_store = InMemoryReplayInputBatchStore()
        batch = _batch(records=(_record(),))
        batch_store.save(batch)
        builder = LocalReplayTimelineBuilder(
            input_batch_store=batch_store,
            timeline_store=timeline_store,
        )
        builder.build_timeline(
            "tl-planned",
            "plan-1",
            ("batch-1",),
            _window(),
            ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
        )
        tl = timeline_store.load("tl-planned")
        assert tl is not None

        report_store = InMemoryReplayTimelineCoverageReportStore()
        auditor = LocalReplayTimelineCoverageAuditor(
            timeline_store=timeline_store,
            report_store=report_store,
            now=lambda: _utc(0),
        )
        report = auditor.generate_report("r-planned", "tl-planned")
        assert report.summary.total_events == len(tl.events)


class TestLocalReplayTimelineCoverageAuditorIssues:
    def test_missing_expected_kind_generates_issue(self) -> None:
        timeline_store, _ = _setup_timeline_store(
            records=(_record("r-1", kind=ReplayInputKind.MARK_PRICE, event_time=_utc(1)),)
        )
        auditor = _auditor(timeline_store=timeline_store)
        report = auditor.generate_report(
            "r-1",
            "tl-1",
            expected_input_kinds=(ReplayInputKind.MARK_PRICE, ReplayInputKind.INDEX_PRICE),
        )
        issue_kinds = {i.kind for i in report.issues}
        assert ReplayTimelineCoverageIssueKind.MISSING_EXPECTED_KIND in issue_kinds
        missing_issue = next(
            i for i in report.issues
            if i.kind is ReplayTimelineCoverageIssueKind.MISSING_EXPECTED_KIND
        )
        assert missing_issue.input_kind is ReplayInputKind.INDEX_PRICE
        assert missing_issue.severity is ReplayTimelineCoverageIssueSeverity.WARNING
        assert missing_issue.issue_id == "r-1:missing-kind:INDEX_PRICE"

    def test_present_expected_kind_no_issue(self) -> None:
        timeline_store, _ = _setup_timeline_store(
            records=(_record("r-1", kind=ReplayInputKind.MARK_PRICE, event_time=_utc(1)),)
        )
        auditor = _auditor(timeline_store=timeline_store)
        report = auditor.generate_report(
            "r-1",
            "tl-1",
            expected_input_kinds=(ReplayInputKind.MARK_PRICE,),
        )
        issue_kinds = {i.kind for i in report.issues}
        assert ReplayTimelineCoverageIssueKind.MISSING_EXPECTED_KIND not in issue_kinds

    def test_missing_expected_instrument_generates_issue(self) -> None:
        timeline_store, _ = _setup_timeline_store(
            records=(_record("r-1", instrument=_instrument("BTCUSDT"), event_time=_utc(1)),)
        )
        auditor = _auditor(timeline_store=timeline_store)
        report = auditor.generate_report(
            "r-1",
            "tl-1",
            expected_instrument_keys=("binance:BTCUSDT:USDT", "binance:ETHUSDT:USDT"),
        )
        missing_instruments = [
            i for i in report.issues
            if i.kind is ReplayTimelineCoverageIssueKind.MISSING_EXPECTED_INSTRUMENT
        ]
        assert len(missing_instruments) == 1
        assert missing_instruments[0].instrument_key == "binance:ETHUSDT:USDT"
        assert missing_instruments[0].issue_id == "r-1:missing-instrument:binance:ETHUSDT:USDT"

    def test_gap_issue_generated_when_exceeded(self) -> None:
        records = (
            _record("r-1", event_time=_utc(1)),
            _record("r-2", event_time=_utc(5), source_sequence=1),
        )
        timeline_store, _ = _setup_timeline_store(records=records)
        auditor = _auditor(timeline_store=timeline_store)
        report = auditor.generate_report("r-1", "tl-1", max_event_gap_seconds=3600)
        gap_issues = [
            i for i in report.issues
            if i.kind is ReplayTimelineCoverageIssueKind.EVENT_TIME_GAP
        ]
        assert len(gap_issues) == 1
        assert gap_issues[0].issue_id == "r-1:gap:0"
        assert gap_issues[0].severity is ReplayTimelineCoverageIssueSeverity.WARNING

    def test_no_gap_issue_when_within_threshold(self) -> None:
        records = (
            _record("r-1", event_time=_utc(1)),
            _record("r-2", event_time=_utc(2), source_sequence=1),
        )
        timeline_store, _ = _setup_timeline_store(records=records)
        auditor = _auditor(timeline_store=timeline_store)
        report = auditor.generate_report(
            "r-1", "tl-1", max_event_gap_seconds=7200
        )
        gap_issues = [
            i for i in report.issues
            if i.kind is ReplayTimelineCoverageIssueKind.EVENT_TIME_GAP
        ]
        assert len(gap_issues) == 0

    def test_invalid_gap_seconds_rejected(self) -> None:
        auditor = _auditor()
        with pytest.raises(ValueError, match="> 0"):
            auditor.generate_report("r-1", "tl-1", max_event_gap_seconds=0)

    def test_bool_gap_seconds_rejected(self) -> None:
        auditor = _auditor()
        with pytest.raises(ValueError, match="strict integer"):
            auditor.generate_report("r-1", "tl-1", max_event_gap_seconds=True)  # type: ignore[arg-type]

    def test_start_coverage_gap_issue_when_first_event_after_window_start(self) -> None:
        records = (_record("r-1", event_time=_utc(3)),)
        timeline_store, _ = _setup_timeline_store(records=records, window=_window(0, 10))
        auditor = _auditor(timeline_store=timeline_store)
        report = auditor.generate_report("r-1", "tl-1")
        start_gap = [
            i for i in report.issues
            if i.kind is ReplayTimelineCoverageIssueKind.START_COVERAGE_GAP
        ]
        assert len(start_gap) == 1
        assert start_gap[0].issue_id == "r-1:start-gap"

    def test_no_start_gap_when_first_event_at_window_start(self) -> None:
        records = (_record("r-1", event_time=_utc(0)),)
        timeline_store, _ = _setup_timeline_store(records=records, window=_window(0, 10))
        auditor = _auditor(timeline_store=timeline_store)
        report = auditor.generate_report("r-1", "tl-1")
        start_gap = [
            i for i in report.issues
            if i.kind is ReplayTimelineCoverageIssueKind.START_COVERAGE_GAP
        ]
        assert len(start_gap) == 0

    def test_end_coverage_gap_issue_when_last_event_before_window_end(self) -> None:
        records = (_record("r-1", event_time=_utc(5)),)
        timeline_store, _ = _setup_timeline_store(records=records, window=_window(0, 10))
        auditor = _auditor(timeline_store=timeline_store)
        report = auditor.generate_report("r-1", "tl-1")
        end_gap = [
            i for i in report.issues
            if i.kind is ReplayTimelineCoverageIssueKind.END_COVERAGE_GAP
        ]
        assert len(end_gap) == 1
        assert end_gap[0].issue_id == "r-1:end-gap"

    def test_issue_count_by_severity_matches_issues(self) -> None:
        records = (_record("r-1", event_time=_utc(3)),)
        timeline_store, _ = _setup_timeline_store(records=records)
        auditor = _auditor(timeline_store=timeline_store)
        report = auditor.generate_report(
            "r-1",
            "tl-1",
            expected_input_kinds=(ReplayInputKind.MARK_PRICE,),
        )
        actual_warning_count = sum(
            1 for i in report.issues
            if i.severity is ReplayTimelineCoverageIssueSeverity.WARNING
        )
        summary_warning_count = dict(report.summary.issue_count_by_severity).get(
            ReplayTimelineCoverageIssueSeverity.WARNING, 0
        )
        assert summary_warning_count == actual_warning_count

    def test_notes_passed_through(self) -> None:
        auditor = _auditor()
        report = auditor.generate_report("r-1", "tl-1", notes="audit note")
        assert report.notes == "audit note"

    def test_expected_kinds_stored_on_report(self) -> None:
        auditor = _auditor()
        expected = (ReplayInputKind.OHLCV_BAR, ReplayInputKind.MARK_PRICE)
        report = auditor.generate_report("r-1", "tl-1", expected_input_kinds=expected)
        assert report.expected_input_kinds == expected

    def test_expected_instrument_keys_stored_on_report(self) -> None:
        auditor = _auditor()
        expected = ("binance:BTCUSDT:USDT",)
        report = auditor.generate_report(
            "r-1", "tl-1", expected_instrument_keys=expected
        )
        assert report.expected_instrument_keys == expected

    def test_replay_plan_id_from_timeline(self) -> None:
        auditor = _auditor()
        report = auditor.generate_report("r-1", "tl-1")
        assert report.replay_plan_id == "plan-1"

    def test_report_has_no_execution_attributes(self) -> None:
        auditor = _auditor()
        report = auditor.generate_report("r-1", "tl-1")
        assert not hasattr(report, "pnl")
        assert not hasattr(report, "metric_observations")
        assert not hasattr(report, "evaluation_result")
        assert not hasattr(auditor, "run_replay")
        assert not hasattr(auditor, "execute_strategy")

    def test_reports_for_replay_plan(self) -> None:
        timeline_store, batch_store = _setup_timeline_store()
        builder = LocalReplayTimelineBuilder(
            input_batch_store=batch_store,
            timeline_store=timeline_store,
        )
        second_batch = ReplayInputBatch(
            batch_id="batch-2",
            replay_plan_id="plan-1",
            input_dataset_id="ds-1",
            temporal_window=_window(),
            ordering_policy=ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
            records=(_record("rec-x", event_time=_utc(1)),),
            created_at=_utc(0),
            validation_status=ReplayInputValidationStatus.VALIDATED,
        )
        batch_store.save(second_batch)
        builder.build_timeline(
            "tl-2",
            "plan-1",
            ("batch-2",),
            _window(),
            ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
        )
        other_batch = ReplayInputBatch(
            batch_id="batch-other",
            replay_plan_id="plan-other",
            input_dataset_id="ds-1",
            temporal_window=_window(),
            ordering_policy=ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
            records=(_record("rec-o", event_time=_utc(1)),),
            created_at=_utc(0),
            validation_status=ReplayInputValidationStatus.VALIDATED,
        )
        batch_store.save(other_batch)
        builder.build_timeline(
            "tl-other-plan",
            "plan-other",
            ("batch-other",),
            _window(),
            ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
        )
        report_store = InMemoryReplayTimelineCoverageReportStore()
        auditor = LocalReplayTimelineCoverageAuditor(
            timeline_store=timeline_store,
            report_store=report_store,
            now=lambda: _utc(0),
        )
        auditor.generate_report("r-tl1", "tl-1")
        auditor.generate_report("r-tl2", "tl-2")
        auditor.generate_report("r-other", "tl-other-plan")
        results = auditor.reports_for_replay_plan("plan-1")
        assert isinstance(results, tuple)
        assert len(results) == 2
        report_ids = {r.report_id for r in results}
        assert report_ids == {"r-tl1", "r-tl2"}
