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

_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _issue(
    issue_id: str = "iss-1",
    severity: ReplayReadinessIssueSeverity = ReplayReadinessIssueSeverity.ERROR,
    kind: ReplayReadinessIssueKind = ReplayReadinessIssueKind.NO_FINGERPRINTS,
    message: str = "some error",
) -> ReplayReadinessIssue:
    return ReplayReadinessIssue(
        issue_id=issue_id,
        kind=kind,
        severity=severity,
        message=message,
    )


def _summary(  # noqa: PLR0913
    *,
    total_fingerprints: int = 0,
    latest_batch_report_id: str | None = None,
    latest_batch_all_valid: bool | None = None,
    latest_batch_total_fingerprints: int | None = None,
    latest_batch_total_issues: int | None = None,
    blocking_issue_count: int = 0,
    warning_issue_count: int = 0,
    info_issue_count: int = 0,
) -> ReplayReadinessSummary:
    return ReplayReadinessSummary(
        total_fingerprints=total_fingerprints,
        latest_batch_report_id=latest_batch_report_id,
        latest_batch_all_valid=latest_batch_all_valid,
        latest_batch_total_fingerprints=latest_batch_total_fingerprints,
        latest_batch_total_issues=latest_batch_total_issues,
        blocking_issue_count=blocking_issue_count,
        warning_issue_count=warning_issue_count,
        info_issue_count=info_issue_count,
    )


def _ready_report(report_id: str = "rpt-1") -> ReplayReadinessReport:
    return ReplayReadinessReport(
        report_id=report_id,
        replay_plan_id="plan-1",
        checked_at=_TS,
        status=ReplayReadinessStatus.READY,
        summary=_summary(
            total_fingerprints=2,
            latest_batch_report_id="batch-1",
            latest_batch_all_valid=True,
            latest_batch_total_fingerprints=2,
            latest_batch_total_issues=0,
        ),
    )


def _blocked_report(
    report_id: str = "rpt-1",
    issues: tuple[ReplayReadinessIssue, ...] | None = None,
) -> ReplayReadinessReport:
    if issues is None:
        issues = (_issue(),)
    return ReplayReadinessReport(
        report_id=report_id,
        replay_plan_id="plan-1",
        checked_at=_TS,
        status=ReplayReadinessStatus.BLOCKED,
        summary=_summary(blocking_issue_count=len(issues)),
        issues=issues,
    )


class TestReplayReadinessIssue:
    def test_valid_issue(self) -> None:
        issue = _issue()
        assert issue.issue_id == "iss-1"
        assert issue.severity is ReplayReadinessIssueSeverity.ERROR

    def test_optional_refs_accepted(self) -> None:
        issue = ReplayReadinessIssue(
            issue_id="i1",
            kind=ReplayReadinessIssueKind.BATCH_HAS_MISMATCHES,
            severity=ReplayReadinessIssueSeverity.WARNING,
            message="msg",
            artifact_id="art-1",
            fingerprint_id="fp-1",
            batch_report_id="batch-1",
        )
        assert issue.artifact_id == "art-1"

    def test_empty_issue_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayReadinessIssue(
                issue_id="",
                kind=ReplayReadinessIssueKind.OTHER,
                severity=ReplayReadinessIssueSeverity.INFO,
                message="msg",
            )

    def test_empty_message_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayReadinessIssue(
                issue_id="i1",
                kind=ReplayReadinessIssueKind.OTHER,
                severity=ReplayReadinessIssueSeverity.INFO,
                message="",
            )

    def test_empty_artifact_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayReadinessIssue(
                issue_id="i1",
                kind=ReplayReadinessIssueKind.OTHER,
                severity=ReplayReadinessIssueSeverity.INFO,
                message="msg",
                artifact_id="",
            )

    def test_whitespace_fingerprint_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayReadinessIssue(
                issue_id="i1",
                kind=ReplayReadinessIssueKind.OTHER,
                severity=ReplayReadinessIssueSeverity.INFO,
                message="msg",
                fingerprint_id=" fp",
            )


class TestReplayReadinessSummary:
    def test_valid_minimal(self) -> None:
        s = _summary()
        assert s.total_fingerprints == 0
        assert s.blocking_issue_count == 0

    def test_total_fingerprints_bool_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _summary(total_fingerprints=True)  # type: ignore[arg-type]

    def test_total_fingerprints_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _summary(total_fingerprints="1")  # type: ignore[arg-type]

    def test_blocking_issue_count_bool_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _summary(blocking_issue_count=False)  # type: ignore[arg-type]

    def test_warning_issue_count_float_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _summary(warning_issue_count=1.0)  # type: ignore[arg-type]

    def test_optional_int_bool_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _summary(latest_batch_total_fingerprints=True)  # type: ignore[arg-type]

    def test_optional_int_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _summary(latest_batch_total_issues="0")  # type: ignore[arg-type]

    def test_negative_total_fingerprints_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _summary(total_fingerprints=-1)

    def test_negative_blocking_count_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _summary(blocking_issue_count=-1)

    def test_negative_optional_int_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _summary(latest_batch_total_fingerprints=-1)

    def test_empty_latest_batch_report_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _summary(latest_batch_report_id="")

    def test_whitespace_latest_batch_report_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _summary(latest_batch_report_id=" r")

    def test_none_optional_fields_accepted(self) -> None:
        s = _summary(
            latest_batch_report_id=None,
            latest_batch_all_valid=None,
            latest_batch_total_fingerprints=None,
            latest_batch_total_issues=None,
        )
        assert s.latest_batch_all_valid is None


class TestReplayReadinessReportReady:
    def test_valid_ready(self) -> None:
        r = _ready_report()
        assert r.status is ReplayReadinessStatus.READY
        assert r.issues == ()
        assert r.summary.latest_batch_total_fingerprints == 2
        assert r.summary.latest_batch_total_issues == 0

    def test_ready_with_issue_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayReadinessReport(
                report_id="rpt-1",
                replay_plan_id="plan-1",
                checked_at=_TS,
                status=ReplayReadinessStatus.READY,
                summary=_summary(
                    total_fingerprints=1,
                    latest_batch_report_id="b1",
                    latest_batch_all_valid=True,
                    blocking_issue_count=1,
                ),
                issues=(_issue(),),
            )

    def test_ready_zero_fingerprints_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayReadinessReport(
                report_id="rpt-1",
                replay_plan_id="plan-1",
                checked_at=_TS,
                status=ReplayReadinessStatus.READY,
                summary=_summary(
                    total_fingerprints=0,
                    latest_batch_report_id="b1",
                    latest_batch_all_valid=True,
                ),
            )

    def test_ready_no_latest_batch_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayReadinessReport(
                report_id="rpt-1",
                replay_plan_id="plan-1",
                checked_at=_TS,
                status=ReplayReadinessStatus.READY,
                summary=_summary(
                    total_fingerprints=1,
                    latest_batch_report_id=None,
                    latest_batch_all_valid=True,
                ),
            )

    def test_ready_all_valid_false_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayReadinessReport(
                report_id="rpt-1",
                replay_plan_id="plan-1",
                checked_at=_TS,
                status=ReplayReadinessStatus.READY,
                summary=_summary(
                    total_fingerprints=1,
                    latest_batch_report_id="b1",
                    latest_batch_all_valid=False,
                ),
            )

    def test_ready_all_valid_none_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayReadinessReport(
                report_id="rpt-1",
                replay_plan_id="plan-1",
                checked_at=_TS,
                status=ReplayReadinessStatus.READY,
                summary=_summary(
                    total_fingerprints=1,
                    latest_batch_report_id="b1",
                    latest_batch_all_valid=None,
                ),
            )

    def test_ready_latest_batch_total_fingerprints_none_rejected(self) -> None:
        with pytest.raises(ValidationError, match="latest_batch_total_fingerprints"):
            ReplayReadinessReport(
                report_id="rpt-1",
                replay_plan_id="plan-1",
                checked_at=_TS,
                status=ReplayReadinessStatus.READY,
                summary=_summary(
                    total_fingerprints=2,
                    latest_batch_report_id="b1",
                    latest_batch_all_valid=True,
                    latest_batch_total_fingerprints=None,
                    latest_batch_total_issues=0,
                ),
            )

    def test_ready_latest_batch_total_fingerprints_lower_rejected(self) -> None:
        with pytest.raises(ValidationError, match="latest_batch_total_fingerprints"):
            ReplayReadinessReport(
                report_id="rpt-1",
                replay_plan_id="plan-1",
                checked_at=_TS,
                status=ReplayReadinessStatus.READY,
                summary=_summary(
                    total_fingerprints=2,
                    latest_batch_report_id="b1",
                    latest_batch_all_valid=True,
                    latest_batch_total_fingerprints=1,
                    latest_batch_total_issues=0,
                ),
            )

    def test_ready_latest_batch_total_fingerprints_higher_rejected(self) -> None:
        with pytest.raises(ValidationError, match="latest_batch_total_fingerprints"):
            ReplayReadinessReport(
                report_id="rpt-1",
                replay_plan_id="plan-1",
                checked_at=_TS,
                status=ReplayReadinessStatus.READY,
                summary=_summary(
                    total_fingerprints=2,
                    latest_batch_report_id="b1",
                    latest_batch_all_valid=True,
                    latest_batch_total_fingerprints=3,
                    latest_batch_total_issues=0,
                ),
            )

    def test_ready_latest_batch_total_fingerprints_exact_accepted(self) -> None:
        r = ReplayReadinessReport(
            report_id="rpt-1",
            replay_plan_id="plan-1",
            checked_at=_TS,
            status=ReplayReadinessStatus.READY,
            summary=_summary(
                total_fingerprints=2,
                latest_batch_report_id="b1",
                latest_batch_all_valid=True,
                latest_batch_total_fingerprints=2,
                latest_batch_total_issues=0,
            ),
        )

        assert r.status is ReplayReadinessStatus.READY

    def test_ready_latest_batch_total_issues_none_rejected(self) -> None:
        with pytest.raises(ValidationError, match="latest_batch_total_issues"):
            ReplayReadinessReport(
                report_id="rpt-1",
                replay_plan_id="plan-1",
                checked_at=_TS,
                status=ReplayReadinessStatus.READY,
                summary=_summary(
                    total_fingerprints=1,
                    latest_batch_report_id="b1",
                    latest_batch_all_valid=True,
                    latest_batch_total_fingerprints=1,
                    latest_batch_total_issues=None,
                ),
            )

    def test_ready_latest_batch_total_issues_positive_rejected(self) -> None:
        with pytest.raises(ValidationError, match="latest_batch_total_issues"):
            ReplayReadinessReport(
                report_id="rpt-1",
                replay_plan_id="plan-1",
                checked_at=_TS,
                status=ReplayReadinessStatus.READY,
                summary=_summary(
                    total_fingerprints=1,
                    latest_batch_report_id="b1",
                    latest_batch_all_valid=True,
                    latest_batch_total_fingerprints=1,
                    latest_batch_total_issues=1,
                ),
            )

    def test_ready_latest_batch_total_issues_zero_accepted(self) -> None:
        r = ReplayReadinessReport(
            report_id="rpt-1",
            replay_plan_id="plan-1",
            checked_at=_TS,
            status=ReplayReadinessStatus.READY,
            summary=_summary(
                total_fingerprints=1,
                latest_batch_report_id="b1",
                latest_batch_all_valid=True,
                latest_batch_total_fingerprints=1,
                latest_batch_total_issues=0,
            ),
        )

        assert r.status is ReplayReadinessStatus.READY


class TestReplayReadinessReportWarning:
    def test_valid_warning(self) -> None:
        warn_issue = _issue(
            severity=ReplayReadinessIssueSeverity.WARNING,
            kind=ReplayReadinessIssueKind.COVERAGE_REPORT_MISSING,
            message="no coverage",
        )
        r = ReplayReadinessReport(
            report_id="rpt-1",
            replay_plan_id="plan-1",
            checked_at=_TS,
            status=ReplayReadinessStatus.WARNING,
            summary=_summary(warning_issue_count=1),
            issues=(warn_issue,),
        )
        assert r.status is ReplayReadinessStatus.WARNING

    def test_warning_no_warning_issues_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayReadinessReport(
                report_id="rpt-1",
                replay_plan_id="plan-1",
                checked_at=_TS,
                status=ReplayReadinessStatus.WARNING,
                summary=_summary(warning_issue_count=0),
            )

    def test_warning_with_error_issue_rejected(self) -> None:
        warn = _issue(
            issue_id="w1",
            severity=ReplayReadinessIssueSeverity.WARNING,
            kind=ReplayReadinessIssueKind.COVERAGE_REPORT_MISSING,
            message="warn",
        )
        err = _issue(issue_id="e1")
        with pytest.raises(ValidationError):
            ReplayReadinessReport(
                report_id="rpt-1",
                replay_plan_id="plan-1",
                checked_at=_TS,
                status=ReplayReadinessStatus.WARNING,
                summary=_summary(blocking_issue_count=1, warning_issue_count=1),
                issues=(warn, err),
            )


class TestReplayReadinessReportBlocked:
    def test_valid_blocked(self) -> None:
        r = _blocked_report()
        assert r.status is ReplayReadinessStatus.BLOCKED

    def test_blocked_no_error_issues_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayReadinessReport(
                report_id="rpt-1",
                replay_plan_id="plan-1",
                checked_at=_TS,
                status=ReplayReadinessStatus.BLOCKED,
                summary=_summary(blocking_issue_count=0),
            )


class TestReplayReadinessReportInvalidated:
    def test_valid_invalidated_no_issues(self) -> None:
        r = ReplayReadinessReport(
            report_id="rpt-1",
            replay_plan_id="plan-1",
            checked_at=_TS,
            status=ReplayReadinessStatus.INVALIDATED,
            summary=_summary(),
        )
        assert r.status is ReplayReadinessStatus.INVALIDATED

    def test_invalidated_with_error_issue(self) -> None:
        issue = _issue()
        r = ReplayReadinessReport(
            report_id="rpt-1",
            replay_plan_id="plan-1",
            checked_at=_TS,
            status=ReplayReadinessStatus.INVALIDATED,
            summary=_summary(blocking_issue_count=1),
            issues=(issue,),
        )
        assert len(r.issues) == 1


class TestReplayReadinessReportValidation:
    def test_duplicate_issue_ids_rejected(self) -> None:
        i1 = _issue(issue_id="dup")
        i2 = _issue(issue_id="dup", kind=ReplayReadinessIssueKind.NO_VERIFICATION_BATCH_REPORT)
        with pytest.raises(ValidationError):
            ReplayReadinessReport(
                report_id="rpt-1",
                replay_plan_id="plan-1",
                checked_at=_TS,
                status=ReplayReadinessStatus.BLOCKED,
                summary=_summary(blocking_issue_count=2),
                issues=(i1, i2),
            )

    def test_summary_severity_count_mismatch_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayReadinessReport(
                report_id="rpt-1",
                replay_plan_id="plan-1",
                checked_at=_TS,
                status=ReplayReadinessStatus.BLOCKED,
                summary=_summary(blocking_issue_count=2),
                issues=(_issue(),),
            )

    def test_empty_report_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayReadinessReport(
                report_id="",
                replay_plan_id="plan-1",
                checked_at=_TS,
                status=ReplayReadinessStatus.INVALIDATED,
                summary=_summary(),
            )

    def test_empty_replay_plan_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayReadinessReport(
                report_id="rpt-1",
                replay_plan_id="",
                checked_at=_TS,
                status=ReplayReadinessStatus.INVALIDATED,
                summary=_summary(),
            )

    def test_notes_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayReadinessReport(
                report_id="rpt-1",
                replay_plan_id="plan-1",
                checked_at=_TS,
                status=ReplayReadinessStatus.INVALIDATED,
                summary=_summary(),
                notes="",
            )

    def test_notes_leading_whitespace_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayReadinessReport(
                report_id="rpt-1",
                replay_plan_id="plan-1",
                checked_at=_TS,
                status=ReplayReadinessStatus.INVALIDATED,
                summary=_summary(),
                notes=" note",
            )

    def test_notes_valid(self) -> None:
        r = ReplayReadinessReport(
            report_id="rpt-1",
            replay_plan_id="plan-1",
            checked_at=_TS,
            status=ReplayReadinessStatus.INVALIDATED,
            summary=_summary(),
            notes="some note",
        )
        assert r.notes == "some note"

    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayReadinessReport(
                report_id="rpt-1",
                replay_plan_id="plan-1",
                checked_at=datetime(2026, 1, 1),
                status=ReplayReadinessStatus.INVALIDATED,
                summary=_summary(),
            )

    def test_frozen_immutable(self) -> None:
        r = _ready_report()
        with pytest.raises((ValidationError, TypeError)):
            r.report_id = "modified"  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            ReplayReadinessReport(
                report_id="rpt-1",
                replay_plan_id="plan-1",
                checked_at=_TS,
                status=ReplayReadinessStatus.INVALIDATED,
                summary=_summary(),
                extra_field="x",  # type: ignore[call-arg]
            )
