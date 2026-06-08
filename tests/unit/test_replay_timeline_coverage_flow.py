from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from futures_bot.domain.replay import (
    ReplayInputBatch,
    ReplayInputKind,
    ReplayInputRecord,
    ReplayInputValidationStatus,
    ReplayInstrumentRef,
    ReplayOrderingPolicy,
    ReplayTimelineCoverageIssueKind,
    ReplayTimelineCoverageIssueSeverity,
    ReplayTimelineCoverageReport,
    ReplayTimelineCoverageStatus,
)
from futures_bot.domain.research import TemporalWindow, TemporalWindowKind
from futures_bot.infrastructure.replay.in_memory import (
    InMemoryReplayInputBatchStore,
    InMemoryReplayTimelineCoverageReportStore,
    InMemoryReplayTimelineStore,
)
from futures_bot.replay.local import LocalReplayTimelineBuilder, LocalReplayTimelineCoverageAuditor


def _utc(day: int = 1, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=UTC)


def _create_coverage_flow_stores() -> tuple[
    InMemoryReplayInputBatchStore,
    InMemoryReplayTimelineStore,
    InMemoryReplayTimelineCoverageReportStore,
]:
    return (
        InMemoryReplayInputBatchStore(),
        InMemoryReplayTimelineStore(),
        InMemoryReplayTimelineCoverageReportStore(),
    )


def _create_coverage_flow_window() -> TemporalWindow:
    return TemporalWindow(
        kind=TemporalWindowKind.TEST,
        start_at=_utc(2, 0),
        end_at=_utc(3, 0),
        window_id="cov-window",
    )


def _create_coverage_flow_instrument() -> ReplayInstrumentRef:
    return ReplayInstrumentRef(
        venue="binance",
        symbol="BTCUSDT",
        market_type="stablecoin-collateral-futures",
        settlement_asset="USDT",
        quote_asset="USDT",
        base_asset="BTC",
    )


def _create_coverage_flow_batch(
    batch_store: InMemoryReplayInputBatchStore,
    instrument: ReplayInstrumentRef,
    window: TemporalWindow,
) -> None:
    records = (
        ReplayInputRecord(
            record_id="r-ohlcv-1",
            kind=ReplayInputKind.OHLCV_BAR,
            instrument=instrument,
            event_time=_utc(2, 0),
            source_sequence=0,
            payload={
                "open": Decimal("100"),
                "high": Decimal("101"),
                "low": Decimal("99"),
                "close": Decimal("100"),
                "volume": Decimal("10"),
            },
        ),
        ReplayInputRecord(
            record_id="r-mark-1",
            kind=ReplayInputKind.MARK_PRICE,
            instrument=instrument,
            event_time=_utc(2, 1),
            source_sequence=1,
            payload={"price": Decimal("100.5")},
        ),
        ReplayInputRecord(
            record_id="r-ohlcv-2",
            kind=ReplayInputKind.OHLCV_BAR,
            instrument=instrument,
            event_time=_utc(2, 2),
            source_sequence=2,
            payload={
                "open": Decimal("101"),
                "high": Decimal("102"),
                "low": Decimal("100"),
                "close": Decimal("101"),
                "volume": Decimal("8"),
            },
        ),
        ReplayInputRecord(
            record_id="r-mark-2",
            kind=ReplayInputKind.MARK_PRICE,
            instrument=instrument,
            event_time=_utc(2, 3),
            source_sequence=3,
            payload={"price": Decimal("101.2")},
        ),
    )
    batch = ReplayInputBatch(
        batch_id="cov-batch",
        replay_plan_id="cov-plan",
        input_dataset_id="cov-ds",
        temporal_window=window,
        ordering_policy=ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
        records=records,
        created_at=_utc(1, 0),
        validation_status=ReplayInputValidationStatus.VALIDATED,
    )
    batch_store.save(batch)


def _build_coverage_flow_timeline(
    batch_store: InMemoryReplayInputBatchStore,
    timeline_store: InMemoryReplayTimelineStore,
    window: TemporalWindow,
) -> None:
    builder = LocalReplayTimelineBuilder(
        input_batch_store=batch_store,
        timeline_store=timeline_store,
    )
    builder.build_timeline(
        "cov-tl",
        "cov-plan",
        ("cov-batch",),
        window,
        ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
    )


def _generate_coverage_flow_report(
    timeline_store: InMemoryReplayTimelineStore,
    report_store: InMemoryReplayTimelineCoverageReportStore,
) -> ReplayTimelineCoverageReport:
    auditor = LocalReplayTimelineCoverageAuditor(
        timeline_store=timeline_store,
        report_store=report_store,
        now=lambda: _utc(1, 12),
    )
    return auditor.generate_report(
        "cov-report",
        "cov-tl",
        expected_input_kinds=(ReplayInputKind.OHLCV_BAR, ReplayInputKind.MARK_PRICE),
        expected_instrument_keys=("binance:BTCUSDT:USDT",),
    )


def _assert_coverage_flow_report(report: ReplayTimelineCoverageReport) -> None:
    assert report.report_id == "cov-report"
    assert report.timeline_id == "cov-tl"
    assert report.replay_plan_id == "cov-plan"
    assert report.status is ReplayTimelineCoverageStatus.GENERATED
    assert report.generated_at == _utc(1, 12)
    assert report.summary.total_events == 4
    assert report.summary.first_event_at == _utc(2, 0)
    assert report.summary.last_event_at == _utc(2, 3)
    assert dict(report.summary.event_count_by_kind)[ReplayInputKind.OHLCV_BAR] == 2
    assert dict(report.summary.event_count_by_kind)[ReplayInputKind.MARK_PRICE] == 2
    assert report.summary.event_count_by_instrument["binance:BTCUSDT:USDT"] == 4
    assert report.summary.event_count_by_dataset["cov-ds"] == 4
    assert report.expected_input_kinds == (ReplayInputKind.OHLCV_BAR, ReplayInputKind.MARK_PRICE)
    assert report.expected_instrument_keys == ("binance:BTCUSDT:USDT",)


def _assert_coverage_flow_issues(report: ReplayTimelineCoverageReport) -> None:
    issue_kinds = {i.kind for i in report.issues}
    assert ReplayTimelineCoverageIssueKind.MISSING_EXPECTED_KIND not in issue_kinds
    assert ReplayTimelineCoverageIssueKind.MISSING_EXPECTED_INSTRUMENT not in issue_kinds
    assert ReplayTimelineCoverageIssueKind.EMPTY_TIMELINE not in issue_kinds
    end_gap_issues = [
        i for i in report.issues
        if i.kind is ReplayTimelineCoverageIssueKind.END_COVERAGE_GAP
    ]
    assert len(end_gap_issues) == 1
    assert end_gap_issues[0].severity is ReplayTimelineCoverageIssueSeverity.WARNING
    warning_count = dict(report.summary.issue_count_by_severity).get(
        ReplayTimelineCoverageIssueSeverity.WARNING, 0
    )
    total_warnings = sum(
        1 for i in report.issues
        if i.severity is ReplayTimelineCoverageIssueSeverity.WARNING
    )
    assert warning_count == total_warnings


def _assert_coverage_flow_persistence(
    report: ReplayTimelineCoverageReport,
    report_store: InMemoryReplayTimelineCoverageReportStore,
) -> None:
    loaded = report_store.load("cov-report")
    assert loaded == report
    timeline_reports = report_store.list_for_timeline("cov-tl")
    assert len(timeline_reports) == 1
    assert timeline_reports[0].report_id == "cov-report"


def test_replay_timeline_coverage_flow() -> None:
    batch_store, timeline_store, report_store = _create_coverage_flow_stores()
    window = _create_coverage_flow_window()
    instrument = _create_coverage_flow_instrument()
    _create_coverage_flow_batch(batch_store, instrument, window)
    _build_coverage_flow_timeline(batch_store, timeline_store, window)
    report = _generate_coverage_flow_report(timeline_store, report_store)
    _assert_coverage_flow_report(report)
    _assert_coverage_flow_issues(report)
    _assert_coverage_flow_persistence(report, report_store)
    assert not hasattr(report, "pnl")
    assert not hasattr(report, "evaluation_result")
    assert not hasattr(report, "metric_observations")
