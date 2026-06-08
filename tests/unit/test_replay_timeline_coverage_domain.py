from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.replay import (
    ReplayInputKind,
    ReplayTimelineCoverageIssue,
    ReplayTimelineCoverageIssueKind,
    ReplayTimelineCoverageIssueSeverity,
    ReplayTimelineCoverageReport,
    ReplayTimelineCoverageStatus,
    ReplayTimelineCoverageSummary,
)
from futures_bot.domain.research import TemporalWindow, TemporalWindowKind


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _window() -> TemporalWindow:
    return TemporalWindow(
        kind=TemporalWindowKind.TEST,
        start_at=_utc(0),
        end_at=_utc(10),
        window_id="tw-1",
    )


def _issue(
    issue_id: str = "issue-1",
    *,
    kind: ReplayTimelineCoverageIssueKind = ReplayTimelineCoverageIssueKind.OTHER,
    severity: ReplayTimelineCoverageIssueSeverity = ReplayTimelineCoverageIssueSeverity.INFO,
    message: str = "test issue",
) -> ReplayTimelineCoverageIssue:
    return ReplayTimelineCoverageIssue(
        issue_id=issue_id,
        kind=kind,
        severity=severity,
        message=message,
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


def _report(  # noqa: PLR0913
    report_id: str = "report-1",
    *,
    timeline_id: str = "tl-1",
    replay_plan_id: str = "plan-1",
    issues: tuple[ReplayTimelineCoverageIssue, ...] = (),
    status: ReplayTimelineCoverageStatus = ReplayTimelineCoverageStatus.GENERATED,
    notes: str | None = None,
) -> ReplayTimelineCoverageReport:
    severity_counts: dict[ReplayTimelineCoverageIssueSeverity, int] = {}
    for issue in issues:
        severity_counts[issue.severity] = severity_counts.get(issue.severity, 0) + 1
    return ReplayTimelineCoverageReport(
        report_id=report_id,
        timeline_id=timeline_id,
        replay_plan_id=replay_plan_id,
        temporal_window=_window(),
        generated_at=_utc(0),
        status=status,
        summary=_empty_summary(severity_counts),
        issues=issues,
        notes=notes,
    )


class TestReplayTimelineCoverageIssue:
    def test_valid_minimal_issue(self) -> None:
        issue = _issue()
        assert issue.issue_id == "issue-1"
        assert issue.kind is ReplayTimelineCoverageIssueKind.OTHER
        assert issue.severity is ReplayTimelineCoverageIssueSeverity.INFO
        assert issue.message == "test issue"
        assert issue.event_id is None
        assert issue.instrument_key is None
        assert issue.input_kind is None
        assert issue.observed_count is None
        assert issue.expected_count is None

    def test_valid_full_issue(self) -> None:
        issue = ReplayTimelineCoverageIssue(
            issue_id="issue-full",
            kind=ReplayTimelineCoverageIssueKind.EVENT_TIME_GAP,
            severity=ReplayTimelineCoverageIssueSeverity.WARNING,
            message="gap detected",
            event_id="batch-1:rec-1",
            instrument_key="binance:BTCUSDT:USDT",
            input_kind=ReplayInputKind.OHLCV_BAR,
            observed_count=5,
            expected_count=10,
        )
        assert issue.event_id == "batch-1:rec-1"
        assert issue.instrument_key == "binance:BTCUSDT:USDT"
        assert issue.input_kind is ReplayInputKind.OHLCV_BAR
        assert issue.observed_count == 5
        assert issue.expected_count == 10

    def test_empty_issue_id_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty"):
            _issue(issue_id="")

    def test_whitespace_issue_id_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty"):
            _issue(issue_id="  ")

    def test_empty_message_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty"):
            _issue(message="")

    def test_empty_event_id_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty"):
            ReplayTimelineCoverageIssue(
                issue_id="i-1",
                kind=ReplayTimelineCoverageIssueKind.OTHER,
                severity=ReplayTimelineCoverageIssueSeverity.INFO,
                message="msg",
                event_id="",
            )

    def test_empty_instrument_key_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty"):
            ReplayTimelineCoverageIssue(
                issue_id="i-1",
                kind=ReplayTimelineCoverageIssueKind.OTHER,
                severity=ReplayTimelineCoverageIssueSeverity.INFO,
                message="msg",
                instrument_key="",
            )

    def test_bool_observed_count_rejected(self) -> None:
        with pytest.raises(ValidationError, match="strict integer"):
            ReplayTimelineCoverageIssue(
                issue_id="i-1",
                kind=ReplayTimelineCoverageIssueKind.OTHER,
                severity=ReplayTimelineCoverageIssueSeverity.INFO,
                message="msg",
                observed_count=True,
            )

    def test_negative_observed_count_rejected(self) -> None:
        with pytest.raises(ValidationError, match=">= 0"):
            ReplayTimelineCoverageIssue(
                issue_id="i-1",
                kind=ReplayTimelineCoverageIssueKind.OTHER,
                severity=ReplayTimelineCoverageIssueSeverity.INFO,
                message="msg",
                observed_count=-1,
            )

    def test_string_expected_count_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayTimelineCoverageIssue(
                issue_id="i-1",
                kind=ReplayTimelineCoverageIssueKind.OTHER,
                severity=ReplayTimelineCoverageIssueSeverity.INFO,
                message="msg",
                expected_count="10",  # type: ignore[arg-type]
            )

    def test_zero_counts_accepted(self) -> None:
        issue = ReplayTimelineCoverageIssue(
            issue_id="i-1",
            kind=ReplayTimelineCoverageIssueKind.OTHER,
            severity=ReplayTimelineCoverageIssueSeverity.INFO,
            message="msg",
            observed_count=0,
            expected_count=0,
        )
        assert issue.observed_count == 0
        assert issue.expected_count == 0

    def test_frozen(self) -> None:
        issue = _issue()
        with pytest.raises((AttributeError, ValidationError)):
            issue.message = "changed"  # type: ignore[misc]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayTimelineCoverageIssue(
                issue_id="i-1",
                kind=ReplayTimelineCoverageIssueKind.OTHER,
                severity=ReplayTimelineCoverageIssueSeverity.INFO,
                message="msg",
                extra_field="not allowed",  # type: ignore[call-arg]
            )


class TestReplayTimelineCoverageSummary:
    def test_valid_empty_summary(self) -> None:
        s = _empty_summary()
        assert s.total_events == 0
        assert s.first_event_at is None
        assert s.last_event_at is None
        assert dict(s.event_count_by_kind) == {}
        assert dict(s.issue_count_by_severity) == {}

    def test_valid_summary_with_events(self) -> None:
        s = ReplayTimelineCoverageSummary(
            total_events=3,
            first_event_at=_utc(1),
            last_event_at=_utc(3),
            event_count_by_kind={ReplayInputKind.OHLCV_BAR: 2, ReplayInputKind.MARK_PRICE: 1},
            event_count_by_instrument={"binance:BTCUSDT:USDT": 3},
            event_count_by_dataset={"ds-1": 3},
            issue_count_by_severity={ReplayTimelineCoverageIssueSeverity.WARNING: 1},
        )
        assert s.total_events == 3
        assert s.first_event_at == _utc(1)
        assert s.last_event_at == _utc(3)

    def test_bool_total_events_rejected(self) -> None:
        with pytest.raises(ValidationError, match="strict integer"):
            ReplayTimelineCoverageSummary(
                total_events=True,
                event_count_by_kind={},
                event_count_by_instrument={},
                event_count_by_dataset={},
                issue_count_by_severity={},
            )

    def test_negative_total_events_rejected(self) -> None:
        with pytest.raises(ValidationError, match=">= 0"):
            ReplayTimelineCoverageSummary(
                total_events=-1,
                event_count_by_kind={},
                event_count_by_instrument={},
                event_count_by_dataset={},
                issue_count_by_severity={},
            )

    def test_zero_events_with_event_times_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must be None"):
            ReplayTimelineCoverageSummary(
                total_events=0,
                first_event_at=_utc(1),
                event_count_by_kind={},
                event_count_by_instrument={},
                event_count_by_dataset={},
                issue_count_by_severity={},
            )

    def test_nonzero_events_missing_first_at_rejected(self) -> None:
        with pytest.raises(ValidationError, match="required"):
            ReplayTimelineCoverageSummary(
                total_events=1,
                last_event_at=_utc(2),
                event_count_by_kind={},
                event_count_by_instrument={},
                event_count_by_dataset={},
                issue_count_by_severity={},
            )

    def test_first_after_last_rejected(self) -> None:
        with pytest.raises(ValidationError, match="<="):
            ReplayTimelineCoverageSummary(
                total_events=2,
                first_event_at=_utc(5),
                last_event_at=_utc(1),
                event_count_by_kind={},
                event_count_by_instrument={},
                event_count_by_dataset={},
                issue_count_by_severity={},
            )

    def test_first_equals_last_accepted(self) -> None:
        s = ReplayTimelineCoverageSummary(
            total_events=1,
            first_event_at=_utc(3),
            last_event_at=_utc(3),
            event_count_by_kind={ReplayInputKind.OHLCV_BAR: 1},
            event_count_by_instrument={"binance:BTCUSDT:USDT": 1},
            event_count_by_dataset={"ds-1": 1},
            issue_count_by_severity={},
        )
        assert s.first_event_at == s.last_event_at

    def test_bool_count_value_rejected(self) -> None:
        with pytest.raises(ValidationError, match="strict integers"):
            ReplayTimelineCoverageSummary(
                total_events=0,
                event_count_by_kind={ReplayInputKind.OHLCV_BAR: True},
                event_count_by_instrument={},
                event_count_by_dataset={},
                issue_count_by_severity={},
            )

    def test_negative_kind_count_rejected(self) -> None:
        with pytest.raises(ValidationError, match=">= 0"):
            ReplayTimelineCoverageSummary(
                total_events=0,
                event_count_by_kind={ReplayInputKind.OHLCV_BAR: -1},
                event_count_by_instrument={},
                event_count_by_dataset={},
                issue_count_by_severity={},
            )

    def test_empty_string_instrument_key_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty"):
            ReplayTimelineCoverageSummary(
                total_events=0,
                event_count_by_kind={},
                event_count_by_instrument={"": 1},
                event_count_by_dataset={},
                issue_count_by_severity={},
            )

    def test_naive_event_time_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayTimelineCoverageSummary(
                total_events=1,
                first_event_at=datetime(2026, 1, 1, 1),  # naive
                last_event_at=_utc(1),
                event_count_by_kind={},
                event_count_by_instrument={},
                event_count_by_dataset={},
                issue_count_by_severity={},
            )

    def test_kind_count_sum_mismatch_rejected(self) -> None:
        with pytest.raises(ValidationError, match="event_count_by_kind"):
            ReplayTimelineCoverageSummary(
                total_events=2,
                first_event_at=_utc(1),
                last_event_at=_utc(2),
                event_count_by_kind={ReplayInputKind.MARK_PRICE: 3},
                event_count_by_instrument={"binance:BTCUSDT:USDT": 2},
                event_count_by_dataset={"ds-1": 2},
                issue_count_by_severity={},
            )

    def test_instrument_count_sum_mismatch_rejected(self) -> None:
        with pytest.raises(ValidationError, match="event_count_by_instrument"):
            ReplayTimelineCoverageSummary(
                total_events=2,
                first_event_at=_utc(1),
                last_event_at=_utc(2),
                event_count_by_kind={ReplayInputKind.MARK_PRICE: 2},
                event_count_by_instrument={"binance:BTCUSDT:USDT": 3},
                event_count_by_dataset={"ds-1": 2},
                issue_count_by_severity={},
            )

    def test_dataset_count_sum_mismatch_rejected(self) -> None:
        with pytest.raises(ValidationError, match="event_count_by_dataset"):
            ReplayTimelineCoverageSummary(
                total_events=2,
                first_event_at=_utc(1),
                last_event_at=_utc(2),
                event_count_by_kind={ReplayInputKind.MARK_PRICE: 2},
                event_count_by_instrument={"binance:BTCUSDT:USDT": 2},
                event_count_by_dataset={"ds-1": 3},
                issue_count_by_severity={},
            )

    def test_zero_events_non_empty_kind_mapping_rejected(self) -> None:
        with pytest.raises(ValidationError, match="empty when total_events is 0"):
            ReplayTimelineCoverageSummary(
                total_events=0,
                event_count_by_kind={ReplayInputKind.OHLCV_BAR: 1},
                event_count_by_instrument={},
                event_count_by_dataset={},
                issue_count_by_severity={},
            )


class TestReplayTimelineCoverageReport:
    def test_valid_report_no_issues(self) -> None:
        r = _report()
        assert r.report_id == "report-1"
        assert r.timeline_id == "tl-1"
        assert r.status is ReplayTimelineCoverageStatus.GENERATED
        assert r.issues == ()
        assert r.expected_input_kinds == ()
        assert r.expected_instrument_keys == ()
        assert r.notes is None

    def test_valid_report_with_issues(self) -> None:
        issues = (
            _issue("i-1", severity=ReplayTimelineCoverageIssueSeverity.WARNING),
            _issue("i-2", severity=ReplayTimelineCoverageIssueSeverity.ERROR),
        )
        r = _report(issues=issues)
        assert len(r.issues) == 2
        assert dict(r.summary.issue_count_by_severity) == {
            ReplayTimelineCoverageIssueSeverity.WARNING: 1,
            ReplayTimelineCoverageIssueSeverity.ERROR: 1,
        }

    def test_duplicate_issue_ids_rejected(self) -> None:
        issues = (
            _issue("same-id"),
            _issue("same-id", severity=ReplayTimelineCoverageIssueSeverity.WARNING),
        )
        with pytest.raises(ValidationError, match="duplicate issue_id"):
            _report(issues=issues)

    def test_duplicate_expected_kinds_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate expected_input_kinds"):
            r = ReplayTimelineCoverageReport(
                report_id="r-1",
                timeline_id="tl-1",
                replay_plan_id="plan-1",
                temporal_window=_window(),
                generated_at=_utc(0),
                status=ReplayTimelineCoverageStatus.GENERATED,
                summary=_empty_summary(),
                expected_input_kinds=(ReplayInputKind.OHLCV_BAR, ReplayInputKind.OHLCV_BAR),
            )
            del r

    def test_duplicate_expected_instrument_keys_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate expected_instrument_keys"):
            r = ReplayTimelineCoverageReport(
                report_id="r-1",
                timeline_id="tl-1",
                replay_plan_id="plan-1",
                temporal_window=_window(),
                generated_at=_utc(0),
                status=ReplayTimelineCoverageStatus.GENERATED,
                summary=_empty_summary(),
                expected_instrument_keys=("binance:BTCUSDT:USDT", "binance:BTCUSDT:USDT"),
            )
            del r

    def test_issue_count_mismatch_rejected(self) -> None:
        wrong_summary = ReplayTimelineCoverageSummary(
            total_events=0,
            event_count_by_kind={},
            event_count_by_instrument={},
            event_count_by_dataset={},
            issue_count_by_severity={ReplayTimelineCoverageIssueSeverity.INFO: 99},
        )
        with pytest.raises(ValidationError, match="issue_count_by_severity"):
            r = ReplayTimelineCoverageReport(
                report_id="r-1",
                timeline_id="tl-1",
                replay_plan_id="plan-1",
                temporal_window=_window(),
                generated_at=_utc(0),
                status=ReplayTimelineCoverageStatus.GENERATED,
                summary=wrong_summary,
                issues=(),
            )
            del r

    def test_notes_validation(self) -> None:
        r = _report(notes="useful context")
        assert r.notes == "useful context"

    def test_whitespace_notes_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty"):
            _report(notes="   ")

    def test_empty_report_id_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty"):
            _report(report_id="")

    def test_naive_generated_at_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayTimelineCoverageReport(
                report_id="r-1",
                timeline_id="tl-1",
                replay_plan_id="plan-1",
                temporal_window=_window(),
                generated_at=datetime(2026, 1, 1),  # naive
                status=ReplayTimelineCoverageStatus.GENERATED,
                summary=_empty_summary(),
            )

    def test_frozen(self) -> None:
        r = _report()
        with pytest.raises((AttributeError, ValidationError)):
            r.report_id = "changed"  # type: ignore[misc]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayTimelineCoverageReport(
                report_id="r-1",
                timeline_id="tl-1",
                replay_plan_id="plan-1",
                temporal_window=_window(),
                generated_at=_utc(0),
                status=ReplayTimelineCoverageStatus.GENERATED,
                summary=_empty_summary(),
                unexpected="nope",  # type: ignore[call-arg]
            )

    def test_all_statuses_valid(self) -> None:
        for status in ReplayTimelineCoverageStatus:
            r = _report(status=status)
            assert r.status is status

    def test_report_with_notes_and_expected_kinds(self) -> None:
        r = ReplayTimelineCoverageReport(
            report_id="r-annotated",
            timeline_id="tl-1",
            replay_plan_id="plan-1",
            temporal_window=_window(),
            generated_at=_utc(0),
            status=ReplayTimelineCoverageStatus.GENERATED,
            summary=_empty_summary(),
            expected_input_kinds=(ReplayInputKind.OHLCV_BAR, ReplayInputKind.MARK_PRICE),
            expected_instrument_keys=("binance:BTCUSDT:USDT",),
            notes="quarterly audit",
        )
        assert len(r.expected_input_kinds) == 2
        assert len(r.expected_instrument_keys) == 1
        assert r.notes == "quarterly audit"

    def test_whitespace_only_instrument_key_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty"):
            ReplayTimelineCoverageReport(
                report_id="r-1",
                timeline_id="tl-1",
                replay_plan_id="plan-1",
                temporal_window=_window(),
                generated_at=_utc(0),
                status=ReplayTimelineCoverageStatus.GENERATED,
                summary=_empty_summary(),
                expected_instrument_keys=("   ",),
            )

    def test_leading_whitespace_instrument_key_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty"):
            ReplayTimelineCoverageReport(
                report_id="r-1",
                timeline_id="tl-1",
                replay_plan_id="plan-1",
                temporal_window=_window(),
                generated_at=_utc(0),
                status=ReplayTimelineCoverageStatus.GENERATED,
                summary=_empty_summary(),
                expected_instrument_keys=(" binance:BTCUSDT:USDT",),
            )
