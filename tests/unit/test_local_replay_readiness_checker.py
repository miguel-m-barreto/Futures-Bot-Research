from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from futures_bot.domain.replay import (
    ReplayArtifactFingerprint,
    ReplayArtifactFingerprintStatus,
    ReplayArtifactFingerprintVerificationBatchItem,
    ReplayArtifactFingerprintVerificationBatchReport,
    ReplayArtifactFingerprintVerificationBatchReportStatus,
    ReplayArtifactFingerprintVerificationBatchScopeKind,
    ReplayArtifactFingerprintVerificationBatchSummary,
    ReplayArtifactFingerprintVerificationStatus,
    ReplayArtifactHashAlgorithm,
    ReplayArtifactKind,
    ReplayReadinessIssueKind,
    ReplayReadinessIssueSeverity,
    ReplayReadinessStatus,
    ReplayTimelineCoverageIssue,
    ReplayTimelineCoverageIssueKind,
    ReplayTimelineCoverageIssueSeverity,
    ReplayTimelineCoverageReport,
    ReplayTimelineCoverageStatus,
    ReplayTimelineCoverageSummary,
)
from futures_bot.domain.research import TemporalWindow, TemporalWindowKind
from futures_bot.infrastructure.replay.in_memory import (
    InMemoryReplayArtifactFingerprintStore,
    InMemoryReplayArtifactFingerprintVerificationBatchReportStore,
    InMemoryReplayReadinessReportStore,
    InMemoryReplayTimelineCoverageReportStore,
)
from futures_bot.replay.integrity import LocalReplayReadinessChecker


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


_KIND_ID_FIELD: dict[ReplayArtifactKind, str] = {
    ReplayArtifactKind.TIMELINE: "timeline_id",
    ReplayArtifactKind.COVERAGE_REPORT: "report_id",
    ReplayArtifactKind.COVERAGE_DIFF: "diff_id",
}


def _fp(
    fingerprint_id: str,
    artifact_kind: ReplayArtifactKind,
    artifact_id: str,
    replay_plan_id: str | None = None,
    generated_at: datetime | None = None,
) -> ReplayArtifactFingerprint:
    id_field = _KIND_ID_FIELD[artifact_kind]
    artifact: dict[str, object] = {id_field: artifact_id}
    if replay_plan_id is not None:
        if artifact_kind is ReplayArtifactKind.COVERAGE_DIFF:
            artifact["baseline_replay_plan_id"] = replay_plan_id
            artifact["candidate_replay_plan_id"] = replay_plan_id
        else:
            artifact["replay_plan_id"] = replay_plan_id
    data: dict[str, object] = {"artifact_kind": artifact_kind.value, "artifact": artifact}
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    sha = hashlib.sha256(payload.encode()).hexdigest()
    return ReplayArtifactFingerprint(
        fingerprint_id=fingerprint_id,
        artifact_kind=artifact_kind,
        artifact_id=artifact_id,
        replay_plan_id=replay_plan_id,
        generated_at=generated_at or _utc(0),
        status=ReplayArtifactFingerprintStatus.GENERATED,
        hash_algorithm=ReplayArtifactHashAlgorithm.SHA256,
        canonical_payload=payload,
        sha256=sha,
    )


def _batch_report(  # noqa: PLR0913
    report_id: str,
    *,
    replay_plan_id: str | None = None,
    fingerprint_ids: tuple[str, ...] = (),
    all_valid: bool = True,
    has_mismatches: bool = False,
    has_missing: bool = False,
    status: ReplayArtifactFingerprintVerificationBatchReportStatus = (
        ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED
    ),
    generated_at: datetime | None = None,
) -> ReplayArtifactFingerprintVerificationBatchReport:
    total = len(fingerprint_ids)
    if all_valid and total > 0:
        count_by_status = {ReplayArtifactFingerprintVerificationStatus.VALID: total}
        ver_status = ReplayArtifactFingerprintVerificationStatus.VALID
    elif has_mismatches:
        count_by_status = {ReplayArtifactFingerprintVerificationStatus.MISMATCH: total}
        ver_status = ReplayArtifactFingerprintVerificationStatus.MISMATCH
    elif has_missing:
        count_by_status = {ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT: total}
        ver_status = ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT
    elif total > 0:
        count_by_status = {ReplayArtifactFingerprintVerificationStatus.INVALIDATED: total}
        ver_status = ReplayArtifactFingerprintVerificationStatus.INVALIDATED
    else:
        count_by_status = {}
        ver_status = ReplayArtifactFingerprintVerificationStatus.VALID
    issue_count = 1 if ver_status in {
        ReplayArtifactFingerprintVerificationStatus.MISMATCH,
        ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT,
        ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT,
    } else 0
    items = tuple(
        ReplayArtifactFingerprintVerificationBatchItem(
            item_id=f"{report_id}:{fp_id}:item",
            fingerprint_id=fp_id,
            verification_id=f"{report_id}:{fp_id}:verification",
            verification_status=ver_status,
            issue_count=issue_count,
        )
        for fp_id in fingerprint_ids
    )
    summary = ReplayArtifactFingerprintVerificationBatchSummary(
        total_fingerprints=total,
        count_by_status=count_by_status,
        total_issues=issue_count * total,
        all_valid=(total > 0 and all_valid),
        has_mismatches=has_mismatches,
        has_missing=has_missing,
    )
    return ReplayArtifactFingerprintVerificationBatchReport(
        report_id=report_id,
        scope_kind=ReplayArtifactFingerprintVerificationBatchScopeKind.REPLAY_PLAN,
        replay_plan_id=replay_plan_id,
        generated_at=generated_at or _utc(10),
        status=status,
        summary=summary,
        items=items,
        requested_fingerprint_ids=fingerprint_ids,
    )


def _batch_report_mixed(
    report_id: str,
    *,
    replay_plan_id: str | None = None,
    items_by_status: dict[ReplayArtifactFingerprintVerificationStatus, list[str]],
    status: ReplayArtifactFingerprintVerificationBatchReportStatus = (
        ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED
    ),
    generated_at: datetime | None = None,
) -> ReplayArtifactFingerprintVerificationBatchReport:
    count_by_status: dict[ReplayArtifactFingerprintVerificationStatus, int] = {}
    built_items: list[ReplayArtifactFingerprintVerificationBatchItem] = []
    for ver_status, fp_ids in items_by_status.items():
        count_by_status[ver_status] = len(fp_ids)
        issue_count = 1 if ver_status in {
            ReplayArtifactFingerprintVerificationStatus.MISMATCH,
            ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT,
            ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT,
        } else 0
        built_items.extend(
            ReplayArtifactFingerprintVerificationBatchItem(
                item_id=f"{report_id}:{fp_id}:item",
                fingerprint_id=fp_id,
                verification_id=f"{report_id}:{fp_id}:verification",
                verification_status=ver_status,
                issue_count=issue_count,
            )
            for fp_id in fp_ids
        )
    total = len(built_items)
    valid_count = count_by_status.get(ReplayArtifactFingerprintVerificationStatus.VALID, 0)
    mismatch_count = count_by_status.get(
        ReplayArtifactFingerprintVerificationStatus.MISMATCH, 0
    )
    missing_fp = count_by_status.get(
        ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT, 0
    )
    missing_art = count_by_status.get(
        ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT, 0
    )
    all_valid = total > 0 and valid_count == total
    summary = ReplayArtifactFingerprintVerificationBatchSummary(
        total_fingerprints=total,
        count_by_status=count_by_status,
        total_issues=sum(item.issue_count for item in built_items),
        all_valid=all_valid,
        has_mismatches=mismatch_count > 0,
        has_missing=(missing_fp + missing_art) > 0,
    )
    fp_ids_ordered = tuple(fp_id for fp_ids in items_by_status.values() for fp_id in fp_ids)
    return ReplayArtifactFingerprintVerificationBatchReport(
        report_id=report_id,
        scope_kind=ReplayArtifactFingerprintVerificationBatchScopeKind.REPLAY_PLAN,
        replay_plan_id=replay_plan_id,
        generated_at=generated_at or _utc(10),
        status=status,
        summary=summary,
        items=tuple(built_items),
        requested_fingerprint_ids=fp_ids_ordered,
    )


def _coverage_report(
    report_id: str,
    *,
    timeline_id: str = "tl-1",
    replay_plan_id: str = "plan-1",
    has_error_issues: bool = False,
    generated_at: datetime | None = None,
) -> ReplayTimelineCoverageReport:
    issues: tuple[ReplayTimelineCoverageIssue, ...] = ()
    severity_counts: dict[ReplayTimelineCoverageIssueSeverity, int] = {}
    if has_error_issues:
        issues = (
            ReplayTimelineCoverageIssue(
                issue_id="cov-err-1",
                kind=ReplayTimelineCoverageIssueKind.EMPTY_TIMELINE,
                severity=ReplayTimelineCoverageIssueSeverity.ERROR,
                message="coverage error",
            ),
        )
        severity_counts[ReplayTimelineCoverageIssueSeverity.ERROR] = 1
    summary = ReplayTimelineCoverageSummary(
        total_events=0,
        event_count_by_kind={},
        event_count_by_instrument={},
        event_count_by_dataset={},
        issue_count_by_severity=severity_counts,
    )
    return ReplayTimelineCoverageReport(
        report_id=report_id,
        timeline_id=timeline_id,
        replay_plan_id=replay_plan_id,
        temporal_window=TemporalWindow(
            kind=TemporalWindowKind.TEST,
            start_at=_utc(0),
            end_at=_utc(10),
            window_id="tw-1",
        ),
        generated_at=generated_at or _utc(0),
        status=ReplayTimelineCoverageStatus.GENERATED,
        summary=summary,
        issues=issues,
    )


def _checker(
    fp_store: InMemoryReplayArtifactFingerprintStore,
    batch_store: InMemoryReplayArtifactFingerprintVerificationBatchReportStore,
    readiness_store: InMemoryReplayReadinessReportStore,
    coverage_store: InMemoryReplayTimelineCoverageReportStore | None = None,
    now: datetime | None = None,
) -> LocalReplayReadinessChecker:
    ts = now or _utc(5)
    return LocalReplayReadinessChecker(
        fingerprint_store=fp_store,
        batch_report_store=batch_store,
        readiness_report_store=readiness_store,
        coverage_report_store=coverage_store,
        now=lambda: ts,
    )


class TestLocalReplayReadinessCheckerNoFingerprints:
    def test_no_fingerprints_blocked(self) -> None:
        fp_store = InMemoryReplayArtifactFingerprintStore()
        batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        readiness_store = InMemoryReplayReadinessReportStore()
        c = _checker(fp_store, batch_store, readiness_store)
        report = c.check_replay_plan("rpt-1", "plan-1")
        assert report.status is ReplayReadinessStatus.BLOCKED
        assert any(i.kind is ReplayReadinessIssueKind.NO_FINGERPRINTS for i in report.issues)

    def test_no_fingerprints_error_severity(self) -> None:
        fp_store = InMemoryReplayArtifactFingerprintStore()
        batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        readiness_store = InMemoryReplayReadinessReportStore()
        c = _checker(fp_store, batch_store, readiness_store)
        report = c.check_replay_plan("rpt-1", "plan-1")
        assert all(i.severity is ReplayReadinessIssueSeverity.ERROR for i in report.issues)


class TestLocalReplayReadinessCheckerNoBatchReport:
    def test_fingerprints_no_batch_blocked(self) -> None:
        fp_store = InMemoryReplayArtifactFingerprintStore()
        batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        readiness_store = InMemoryReplayReadinessReportStore()
        fp_store.save(_fp("fp-1", ReplayArtifactKind.TIMELINE, "tl-1", "plan-1"))
        c = _checker(fp_store, batch_store, readiness_store)
        report = c.check_replay_plan("rpt-1", "plan-1")
        assert report.status is ReplayReadinessStatus.BLOCKED
        assert any(
            i.kind is ReplayReadinessIssueKind.NO_VERIFICATION_BATCH_REPORT
            for i in report.issues
        )


class TestLocalReplayReadinessCheckerBatchValid:
    def test_all_valid_ready(self) -> None:
        fp_store = InMemoryReplayArtifactFingerprintStore()
        batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        readiness_store = InMemoryReplayReadinessReportStore()
        fp_store.save(_fp("fp-1", ReplayArtifactKind.TIMELINE, "tl-1", "plan-1"))
        batch_store.save(
            _batch_report("batch-1", replay_plan_id="plan-1", fingerprint_ids=("fp-1",))
        )
        c = _checker(fp_store, batch_store, readiness_store)
        report = c.check_replay_plan("rpt-1", "plan-1")
        assert report.status is ReplayReadinessStatus.READY
        assert report.issues == ()
        assert report.summary.total_fingerprints == 1
        assert report.summary.latest_batch_all_valid is True


class TestLocalReplayReadinessCheckerBatchIssues:
    def test_has_mismatches_blocked(self) -> None:
        fp_store = InMemoryReplayArtifactFingerprintStore()
        batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        readiness_store = InMemoryReplayReadinessReportStore()
        fp_store.save(_fp("fp-1", ReplayArtifactKind.TIMELINE, "tl-1", "plan-1"))
        batch_store.save(
            _batch_report(
                "batch-1",
                replay_plan_id="plan-1",
                fingerprint_ids=("fp-1",),
                all_valid=False,
                has_mismatches=True,
            )
        )
        c = _checker(fp_store, batch_store, readiness_store)
        report = c.check_replay_plan("rpt-1", "plan-1")
        assert report.status is ReplayReadinessStatus.BLOCKED
        assert any(i.kind is ReplayReadinessIssueKind.BATCH_HAS_MISMATCHES for i in report.issues)

    def test_has_missing_blocked(self) -> None:
        fp_store = InMemoryReplayArtifactFingerprintStore()
        batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        readiness_store = InMemoryReplayReadinessReportStore()
        fp_store.save(_fp("fp-1", ReplayArtifactKind.TIMELINE, "tl-1", "plan-1"))
        batch_store.save(
            _batch_report(
                "batch-1",
                replay_plan_id="plan-1",
                fingerprint_ids=("fp-1",),
                all_valid=False,
                has_missing=True,
            )
        )
        c = _checker(fp_store, batch_store, readiness_store)
        report = c.check_replay_plan("rpt-1", "plan-1")
        assert report.status is ReplayReadinessStatus.BLOCKED
        assert any(i.kind is ReplayReadinessIssueKind.BATCH_HAS_MISSING for i in report.issues)

    def test_not_all_valid_blocked(self) -> None:
        fp_store = InMemoryReplayArtifactFingerprintStore()
        batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        readiness_store = InMemoryReplayReadinessReportStore()
        fp_store.save(_fp("fp-1", ReplayArtifactKind.TIMELINE, "tl-1", "plan-1"))
        batch_store.save(
            _batch_report(
                "batch-1",
                replay_plan_id="plan-1",
                fingerprint_ids=("fp-1",),
                all_valid=False,
            )
        )
        c = _checker(fp_store, batch_store, readiness_store)
        report = c.check_replay_plan("rpt-1", "plan-1")
        assert report.status is ReplayReadinessStatus.BLOCKED
        assert any(
            i.kind is ReplayReadinessIssueKind.BATCH_NOT_ALL_VALID for i in report.issues
        )

    def test_fingerprint_count_mismatch_blocked(self) -> None:
        fp_store = InMemoryReplayArtifactFingerprintStore()
        batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        readiness_store = InMemoryReplayReadinessReportStore()
        fp_store.save(_fp("fp-1", ReplayArtifactKind.TIMELINE, "tl-1", "plan-1"))
        fp_store.save(_fp("fp-2", ReplayArtifactKind.TIMELINE, "tl-2", "plan-1"))
        batch_store.save(
            _batch_report(
                "batch-1",
                replay_plan_id="plan-1",
                fingerprint_ids=("fp-1",),
            )
        )
        c = _checker(fp_store, batch_store, readiness_store)
        report = c.check_replay_plan("rpt-1", "plan-1")
        assert report.status is ReplayReadinessStatus.BLOCKED
        assert any(
            i.kind is ReplayReadinessIssueKind.FINGERPRINT_COUNT_MISMATCH for i in report.issues
        )

    def test_invalidated_batch_blocked(self) -> None:
        fp_store = InMemoryReplayArtifactFingerprintStore()
        batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        readiness_store = InMemoryReplayReadinessReportStore()
        fp_store.save(_fp("fp-1", ReplayArtifactKind.TIMELINE, "tl-1", "plan-1"))
        batch_store.save(
            _batch_report(
                "batch-1",
                replay_plan_id="plan-1",
                fingerprint_ids=("fp-1",),
                status=ReplayArtifactFingerprintVerificationBatchReportStatus.INVALIDATED,
            )
        )
        c = _checker(fp_store, batch_store, readiness_store)
        report = c.check_replay_plan("rpt-1", "plan-1")
        assert report.status is ReplayReadinessStatus.BLOCKED
        assert any(
            i.kind is ReplayReadinessIssueKind.LATEST_BATCH_REPORT_INVALIDATED
            for i in report.issues
        )


class TestLocalReplayReadinessCheckerCoverage:
    def test_coverage_missing_warning(self) -> None:
        fp_store = InMemoryReplayArtifactFingerprintStore()
        batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        readiness_store = InMemoryReplayReadinessReportStore()
        coverage_store = InMemoryReplayTimelineCoverageReportStore()
        fp_store.save(_fp("fp-1", ReplayArtifactKind.TIMELINE, "tl-1", "plan-1"))
        batch_store.save(
            _batch_report("batch-1", replay_plan_id="plan-1", fingerprint_ids=("fp-1",))
        )
        c = _checker(fp_store, batch_store, readiness_store, coverage_store=coverage_store)
        report = c.check_replay_plan("rpt-1", "plan-1")
        assert report.status is ReplayReadinessStatus.WARNING
        assert any(
            i.kind is ReplayReadinessIssueKind.COVERAGE_REPORT_MISSING for i in report.issues
        )
        assert any(i.severity is ReplayReadinessIssueSeverity.WARNING for i in report.issues)

    def test_coverage_with_errors_blocked(self) -> None:
        fp_store = InMemoryReplayArtifactFingerprintStore()
        batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        readiness_store = InMemoryReplayReadinessReportStore()
        coverage_store = InMemoryReplayTimelineCoverageReportStore()
        fp_store.save(_fp("fp-1", ReplayArtifactKind.TIMELINE, "tl-1", "plan-1"))
        batch_store.save(
            _batch_report("batch-1", replay_plan_id="plan-1", fingerprint_ids=("fp-1",))
        )
        coverage_store.save(
            _coverage_report("cov-1", replay_plan_id="plan-1", has_error_issues=True)
        )
        c = _checker(fp_store, batch_store, readiness_store, coverage_store=coverage_store)
        report = c.check_replay_plan("rpt-1", "plan-1")
        assert report.status is ReplayReadinessStatus.BLOCKED
        assert any(
            i.kind is ReplayReadinessIssueKind.COVERAGE_REPORT_HAS_ERRORS for i in report.issues
        )

    def test_no_coverage_store_skips_coverage_check(self) -> None:
        fp_store = InMemoryReplayArtifactFingerprintStore()
        batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        readiness_store = InMemoryReplayReadinessReportStore()
        fp_store.save(_fp("fp-1", ReplayArtifactKind.TIMELINE, "tl-1", "plan-1"))
        batch_store.save(
            _batch_report("batch-1", replay_plan_id="plan-1", fingerprint_ids=("fp-1",))
        )
        c = _checker(fp_store, batch_store, readiness_store, coverage_store=None)
        report = c.check_replay_plan("rpt-1", "plan-1")
        assert report.status is ReplayReadinessStatus.READY
        assert not any(
            i.kind is ReplayReadinessIssueKind.COVERAGE_REPORT_MISSING for i in report.issues
        )


class TestLocalReplayReadinessCheckerPersistence:
    def test_report_persisted(self) -> None:
        fp_store = InMemoryReplayArtifactFingerprintStore()
        batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        readiness_store = InMemoryReplayReadinessReportStore()
        c = _checker(fp_store, batch_store, readiness_store)
        c.check_replay_plan("rpt-1", "plan-1")
        assert readiness_store.load("rpt-1") is not None

    def test_load_readiness_report(self) -> None:
        fp_store = InMemoryReplayArtifactFingerprintStore()
        batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        readiness_store = InMemoryReplayReadinessReportStore()
        c = _checker(fp_store, batch_store, readiness_store)
        c.check_replay_plan("rpt-1", "plan-1")
        loaded = c.load_readiness_report("rpt-1")
        assert loaded is not None
        assert loaded.report_id == "rpt-1"

    def test_load_missing_returns_none(self) -> None:
        fp_store = InMemoryReplayArtifactFingerprintStore()
        batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        readiness_store = InMemoryReplayReadinessReportStore()
        c = _checker(fp_store, batch_store, readiness_store)
        assert c.load_readiness_report("nonexistent") is None

    def test_readiness_reports_for_replay_plan(self) -> None:
        fp_store = InMemoryReplayArtifactFingerprintStore()
        batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        readiness_store = InMemoryReplayReadinessReportStore()
        c = _checker(fp_store, batch_store, readiness_store)
        c.check_replay_plan("rpt-1", "plan-1")
        c.check_replay_plan("rpt-2", "plan-1")
        results = c.readiness_reports_for_replay_plan("plan-1")
        assert len(results) == 2


class TestLocalReplayReadinessCheckerLatestBatch:
    def test_latest_batch_selected_by_generated_at(self) -> None:
        fp_store = InMemoryReplayArtifactFingerprintStore()
        batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        readiness_store = InMemoryReplayReadinessReportStore()
        fp_store.save(_fp("fp-1", ReplayArtifactKind.TIMELINE, "tl-1", "plan-1"))
        batch_store.save(
            _batch_report(
                "batch-old",
                replay_plan_id="plan-1",
                fingerprint_ids=("fp-1",),
                all_valid=False,
                has_mismatches=True,
                generated_at=_utc(1),
            )
        )
        batch_store.save(
            _batch_report(
                "batch-new",
                replay_plan_id="plan-1",
                fingerprint_ids=("fp-1",),
                all_valid=True,
                generated_at=_utc(2),
            )
        )
        c = _checker(fp_store, batch_store, readiness_store)
        report = c.check_replay_plan("rpt-1", "plan-1")
        assert report.status is ReplayReadinessStatus.READY
        assert report.summary.latest_batch_report_id == "batch-new"


class TestLocalReplayReadinessCheckerMultipleIssues:
    def test_mismatches_and_missing_both_reported(self) -> None:
        fp_store = InMemoryReplayArtifactFingerprintStore()
        batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        readiness_store = InMemoryReplayReadinessReportStore()
        fp_store.save(_fp("fp-1", ReplayArtifactKind.TIMELINE, "tl-1", "plan-1"))
        fp_store.save(_fp("fp-2", ReplayArtifactKind.TIMELINE, "tl-2", "plan-1"))
        batch_store.save(
            _batch_report_mixed(
                "batch-1",
                replay_plan_id="plan-1",
                items_by_status={
                    ReplayArtifactFingerprintVerificationStatus.MISMATCH: ["fp-1"],
                    ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT: ["fp-2"],
                },
            )
        )
        c = _checker(fp_store, batch_store, readiness_store)
        report = c.check_replay_plan("rpt-1", "plan-1")
        kinds = {i.kind for i in report.issues}
        assert report.status is ReplayReadinessStatus.BLOCKED
        assert ReplayReadinessIssueKind.BATCH_HAS_MISMATCHES in kinds
        assert ReplayReadinessIssueKind.BATCH_HAS_MISSING in kinds
        assert ReplayReadinessIssueKind.BATCH_NOT_ALL_VALID in kinds

    def test_invalidated_and_count_mismatch_both_reported(self) -> None:
        fp_store = InMemoryReplayArtifactFingerprintStore()
        batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        readiness_store = InMemoryReplayReadinessReportStore()
        fp_store.save(_fp("fp-1", ReplayArtifactKind.TIMELINE, "tl-1", "plan-1"))
        fp_store.save(_fp("fp-2", ReplayArtifactKind.TIMELINE, "tl-2", "plan-1"))
        batch_store.save(
            _batch_report(
                "batch-1",
                replay_plan_id="plan-1",
                fingerprint_ids=("fp-1",),
                status=ReplayArtifactFingerprintVerificationBatchReportStatus.INVALIDATED,
            )
        )
        c = _checker(fp_store, batch_store, readiness_store)
        report = c.check_replay_plan("rpt-1", "plan-1")
        kinds = {i.kind for i in report.issues}
        assert report.status is ReplayReadinessStatus.BLOCKED
        assert ReplayReadinessIssueKind.LATEST_BATCH_REPORT_INVALIDATED in kinds
        assert ReplayReadinessIssueKind.FINGERPRINT_COUNT_MISMATCH in kinds

    def test_mismatches_missing_and_count_mismatch_all_reported(self) -> None:
        fp_store = InMemoryReplayArtifactFingerprintStore()
        batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        readiness_store = InMemoryReplayReadinessReportStore()
        fp_store.save(_fp("fp-1", ReplayArtifactKind.TIMELINE, "tl-1", "plan-1"))
        fp_store.save(_fp("fp-2", ReplayArtifactKind.TIMELINE, "tl-2", "plan-1"))
        fp_store.save(_fp("fp-3", ReplayArtifactKind.TIMELINE, "tl-3", "plan-1"))
        batch_store.save(
            _batch_report_mixed(
                "batch-1",
                replay_plan_id="plan-1",
                items_by_status={
                    ReplayArtifactFingerprintVerificationStatus.MISMATCH: ["fp-1"],
                    ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT: ["fp-2"],
                },
            )
        )
        c = _checker(fp_store, batch_store, readiness_store)
        report = c.check_replay_plan("rpt-1", "plan-1")
        kinds = {i.kind for i in report.issues}
        assert report.status is ReplayReadinessStatus.BLOCKED
        assert ReplayReadinessIssueKind.BATCH_HAS_MISMATCHES in kinds
        assert ReplayReadinessIssueKind.BATCH_HAS_MISSING in kinds
        assert ReplayReadinessIssueKind.BATCH_NOT_ALL_VALID in kinds
        assert ReplayReadinessIssueKind.FINGERPRINT_COUNT_MISMATCH in kinds
