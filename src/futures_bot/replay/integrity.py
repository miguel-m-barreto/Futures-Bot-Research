"""Local metadata-only replay artifact integrity fingerprinter.

No file IO. No market data loading. No replay execution.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime

from futures_bot.domain.replay import (
    ReplayArtifactFingerprint,
    ReplayArtifactFingerprintStatus,
    ReplayArtifactFingerprintVerification,
    ReplayArtifactFingerprintVerificationBatchItem,
    ReplayArtifactFingerprintVerificationBatchReport,
    ReplayArtifactFingerprintVerificationBatchReportStatus,
    ReplayArtifactFingerprintVerificationBatchScopeKind,
    ReplayArtifactFingerprintVerificationBatchSummary,
    ReplayArtifactFingerprintVerificationIssue,
    ReplayArtifactFingerprintVerificationIssueKind,
    ReplayArtifactFingerprintVerificationIssueSeverity,
    ReplayArtifactFingerprintVerificationStatus,
    ReplayArtifactHashAlgorithm,
    ReplayArtifactKind,
    ReplayReadinessIssue,
    ReplayReadinessIssueKind,
    ReplayReadinessIssueSeverity,
    ReplayReadinessReport,
    ReplayReadinessStatus,
    ReplayReadinessSummary,
    ReplayTimelineCoverageIssueSeverity,
)
from futures_bot.ports.replay import (
    ReplayArtifactFingerprintStorePort,
    ReplayArtifactFingerprintVerificationBatchReportStorePort,
    ReplayArtifactFingerprintVerificationStorePort,
    ReplayReadinessReportStorePort,
    ReplayTimelineCoverageDiffStorePort,
    ReplayTimelineCoverageReportStorePort,
    ReplayTimelineStorePort,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _reject_floats(value: object, path: str = "root") -> None:
    if isinstance(value, float):
        raise ValueError(f"float value at {path!r} not allowed in canonical payload")
    if isinstance(value, dict):
        for k, v in value.items():
            _reject_floats(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _reject_floats(v, f"{path}[{i}]")


def _make_canonical_payload(artifact_kind: ReplayArtifactKind, data: object) -> str:
    _reject_floats(data)
    structure: dict[str, object] = {
        "artifact_kind": artifact_kind.value,
        "artifact": data,
    }
    return json.dumps(structure, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _compute_sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class LocalReplayArtifactFingerprinter:
    """Generate deterministic integrity fingerprints for replay artifacts.

    No replay execution. No file IO. No DB. No Kafka.
    """

    def __init__(
        self,
        *,
        timeline_store: ReplayTimelineStorePort,
        coverage_report_store: ReplayTimelineCoverageReportStorePort,
        coverage_diff_store: ReplayTimelineCoverageDiffStorePort,
        fingerprint_store: ReplayArtifactFingerprintStorePort,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._timeline_store = timeline_store
        self._coverage_report_store = coverage_report_store
        self._coverage_diff_store = coverage_diff_store
        self._fingerprint_store = fingerprint_store
        self._now: Callable[[], datetime] = now if now is not None else _utcnow

    def _build(  # noqa: PLR0913
        self,
        fingerprint_id: str,
        artifact_kind: ReplayArtifactKind,
        artifact_id: str,
        data: object,
        replay_plan_id: str | None,
        notes: str | None,
    ) -> ReplayArtifactFingerprint:
        payload = _make_canonical_payload(artifact_kind, data)
        sha = _compute_sha256(payload)
        fingerprint = ReplayArtifactFingerprint(
            fingerprint_id=fingerprint_id,
            artifact_kind=artifact_kind,
            artifact_id=artifact_id,
            replay_plan_id=replay_plan_id,
            generated_at=self._now(),
            status=ReplayArtifactFingerprintStatus.GENERATED,
            hash_algorithm=ReplayArtifactHashAlgorithm.SHA256,
            canonical_payload=payload,
            sha256=sha,
            notes=notes,
        )
        self._fingerprint_store.save(fingerprint)
        return fingerprint

    def fingerprint_timeline(
        self,
        fingerprint_id: str,
        timeline_id: str,
        notes: str | None = None,
    ) -> ReplayArtifactFingerprint:
        timeline = self._timeline_store.load(timeline_id)
        if timeline is None:
            raise ValueError(f"timeline not found: {timeline_id!r}")
        return self._build(
            fingerprint_id,
            ReplayArtifactKind.TIMELINE,
            timeline_id,
            timeline.model_dump(mode="json"),
            timeline.replay_plan_id,
            notes,
        )

    def fingerprint_coverage_report(
        self,
        fingerprint_id: str,
        report_id: str,
        notes: str | None = None,
    ) -> ReplayArtifactFingerprint:
        report = self._coverage_report_store.load(report_id)
        if report is None:
            raise ValueError(f"coverage report not found: {report_id!r}")
        return self._build(
            fingerprint_id,
            ReplayArtifactKind.COVERAGE_REPORT,
            report_id,
            report.model_dump(mode="json"),
            report.replay_plan_id,
            notes,
        )

    def fingerprint_coverage_diff(
        self,
        fingerprint_id: str,
        diff_id: str,
        notes: str | None = None,
    ) -> ReplayArtifactFingerprint:
        diff = self._coverage_diff_store.load(diff_id)
        if diff is None:
            raise ValueError(f"coverage diff not found: {diff_id!r}")
        if diff.baseline_replay_plan_id == diff.candidate_replay_plan_id:
            replay_plan_id: str | None = diff.baseline_replay_plan_id
        else:
            replay_plan_id = None
        return self._build(
            fingerprint_id,
            ReplayArtifactKind.COVERAGE_DIFF,
            diff_id,
            diff.model_dump(mode="json"),
            replay_plan_id,
            notes,
        )

    def load_fingerprint(self, fingerprint_id: str) -> ReplayArtifactFingerprint | None:
        return self._fingerprint_store.load(fingerprint_id)

    def fingerprints_for_artifact(
        self,
        artifact_kind: ReplayArtifactKind,
        artifact_id: str,
    ) -> tuple[ReplayArtifactFingerprint, ...]:
        return self._fingerprint_store.list_for_artifact(artifact_kind, artifact_id)

    def fingerprints_for_replay_plan(
        self, replay_plan_id: str
    ) -> tuple[ReplayArtifactFingerprint, ...]:
        return self._fingerprint_store.list_for_replay_plan(replay_plan_id)


def _build_mismatch_issues(
    recomputed_sha: str,
    stored_sha: str,
    recomputed_payload: str,
    stored_payload: str,
) -> tuple[ReplayArtifactFingerprintVerificationIssue, ...]:
    issues: list[ReplayArtifactFingerprintVerificationIssue] = []
    if recomputed_sha != stored_sha:
        issues.append(
            ReplayArtifactFingerprintVerificationIssue(
                issue_id="iss-hash-mismatch",
                kind=ReplayArtifactFingerprintVerificationIssueKind.HASH_MISMATCH,
                severity=ReplayArtifactFingerprintVerificationIssueSeverity.ERROR,
                message="recomputed SHA-256 does not match stored SHA-256",
                expected_value=stored_sha,
                observed_value=recomputed_sha,
            )
        )
    if recomputed_payload != stored_payload:
        issues.append(
            ReplayArtifactFingerprintVerificationIssue(
                issue_id="iss-payload-mismatch",
                kind=ReplayArtifactFingerprintVerificationIssueKind.CANONICAL_PAYLOAD_MISMATCH,
                severity=ReplayArtifactFingerprintVerificationIssueSeverity.ERROR,
                message="recomputed canonical payload does not match stored canonical payload",
            )
        )
    return tuple(issues)


class LocalReplayArtifactFingerprintVerifier:
    """Metadata-only integrity verifier for replay artifact fingerprints.

    No replay execution. No file IO. No DB. No Kafka.
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        timeline_store: ReplayTimelineStorePort,
        coverage_report_store: ReplayTimelineCoverageReportStorePort,
        coverage_diff_store: ReplayTimelineCoverageDiffStorePort,
        fingerprint_store: ReplayArtifactFingerprintStorePort,
        verification_store: ReplayArtifactFingerprintVerificationStorePort,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._timeline_store = timeline_store
        self._coverage_report_store = coverage_report_store
        self._coverage_diff_store = coverage_diff_store
        self._fingerprint_store = fingerprint_store
        self._verification_store = verification_store
        self._now: Callable[[], datetime] = now if now is not None else _utcnow

    def _load_artifact_data(self, fingerprint: ReplayArtifactFingerprint) -> object | None:
        kind = fingerprint.artifact_kind
        aid = fingerprint.artifact_id
        if kind is ReplayArtifactKind.TIMELINE:
            tl = self._timeline_store.load(aid)
            return tl.model_dump(mode="json") if tl is not None else None
        if kind is ReplayArtifactKind.COVERAGE_REPORT:
            rep = self._coverage_report_store.load(aid)
            return rep.model_dump(mode="json") if rep is not None else None
        if kind is ReplayArtifactKind.COVERAGE_DIFF:
            diff = self._coverage_diff_store.load(aid)
            return diff.model_dump(mode="json") if diff is not None else None
        return None

    def verify_fingerprint(
        self,
        verification_id: str,
        fingerprint_id: str,
        notes: str | None = None,
    ) -> ReplayArtifactFingerprintVerification:
        now = self._now()
        fingerprint = self._fingerprint_store.load(fingerprint_id)
        if fingerprint is None:
            verification = ReplayArtifactFingerprintVerification(
                verification_id=verification_id,
                fingerprint_id=fingerprint_id,
                verified_at=now,
                status=ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT,
                issues=(
                    ReplayArtifactFingerprintVerificationIssue(
                        issue_id="iss-fingerprint-not-found",
                        kind=ReplayArtifactFingerprintVerificationIssueKind.FINGERPRINT_NOT_FOUND,
                        severity=ReplayArtifactFingerprintVerificationIssueSeverity.ERROR,
                        message=f"fingerprint {fingerprint_id!r} not found",
                    ),
                ),
                notes=notes,
            )
            self._verification_store.save(verification)
            return verification
        artifact_data = self._load_artifact_data(fingerprint)
        if artifact_data is None:
            verification = ReplayArtifactFingerprintVerification(
                verification_id=verification_id,
                fingerprint_id=fingerprint_id,
                artifact_kind=fingerprint.artifact_kind,
                artifact_id=fingerprint.artifact_id,
                replay_plan_id=fingerprint.replay_plan_id,
                verified_at=now,
                status=ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT,
                stored_sha256=fingerprint.sha256,
                stored_canonical_payload=fingerprint.canonical_payload,
                issues=(
                    ReplayArtifactFingerprintVerificationIssue(
                        issue_id="iss-artifact-not-found",
                        kind=ReplayArtifactFingerprintVerificationIssueKind.ARTIFACT_NOT_FOUND,
                        severity=ReplayArtifactFingerprintVerificationIssueSeverity.ERROR,
                        message=(
                            f"{fingerprint.artifact_kind.value} "
                            f"{fingerprint.artifact_id!r} not found"
                        ),
                    ),
                ),
                notes=notes,
            )
            self._verification_store.save(verification)
            return verification
        recomputed_payload = _make_canonical_payload(fingerprint.artifact_kind, artifact_data)
        recomputed_sha = _compute_sha256(recomputed_payload)
        if (
            recomputed_sha == fingerprint.sha256
            and recomputed_payload == fingerprint.canonical_payload
        ):
            verification = ReplayArtifactFingerprintVerification(
                verification_id=verification_id,
                fingerprint_id=fingerprint_id,
                artifact_kind=fingerprint.artifact_kind,
                artifact_id=fingerprint.artifact_id,
                replay_plan_id=fingerprint.replay_plan_id,
                verified_at=now,
                status=ReplayArtifactFingerprintVerificationStatus.VALID,
                stored_sha256=fingerprint.sha256,
                recomputed_sha256=recomputed_sha,
                stored_canonical_payload=fingerprint.canonical_payload,
                recomputed_canonical_payload=recomputed_payload,
                notes=notes,
            )
        else:
            issues = _build_mismatch_issues(
                recomputed_sha,
                fingerprint.sha256,
                recomputed_payload,
                fingerprint.canonical_payload,
            )
            verification = ReplayArtifactFingerprintVerification(
                verification_id=verification_id,
                fingerprint_id=fingerprint_id,
                artifact_kind=fingerprint.artifact_kind,
                artifact_id=fingerprint.artifact_id,
                replay_plan_id=fingerprint.replay_plan_id,
                verified_at=now,
                status=ReplayArtifactFingerprintVerificationStatus.MISMATCH,
                stored_sha256=fingerprint.sha256,
                recomputed_sha256=recomputed_sha,
                stored_canonical_payload=fingerprint.canonical_payload,
                recomputed_canonical_payload=recomputed_payload,
                issues=issues,
                notes=notes,
            )
        self._verification_store.save(verification)
        return verification

    def load_verification(
        self, verification_id: str
    ) -> ReplayArtifactFingerprintVerification | None:
        return self._verification_store.load(verification_id)

    def verifications_for_fingerprint(
        self, fingerprint_id: str
    ) -> tuple[ReplayArtifactFingerprintVerification, ...]:
        return self._verification_store.list_for_fingerprint(fingerprint_id)

    def verifications_for_artifact(
        self,
        artifact_kind: ReplayArtifactKind,
        artifact_id: str,
    ) -> tuple[ReplayArtifactFingerprintVerification, ...]:
        return self._verification_store.list_for_artifact(artifact_kind, artifact_id)

    def verifications_for_replay_plan(
        self, replay_plan_id: str
    ) -> tuple[ReplayArtifactFingerprintVerification, ...]:
        return self._verification_store.list_for_replay_plan(replay_plan_id)


def _infer_replay_plan_id_from_items(
    items: list[ReplayArtifactFingerprintVerificationBatchItem],
) -> str | None:
    if not items:
        return None
    plan_ids = {i.replay_plan_id for i in items}
    if len(plan_ids) == 1:
        (plan_id,) = plan_ids
        return plan_id
    return None


def _build_batch_summary(
    items: list[ReplayArtifactFingerprintVerificationBatchItem],
) -> ReplayArtifactFingerprintVerificationBatchSummary:
    total = len(items)
    count_by_status: dict[ReplayArtifactFingerprintVerificationStatus, int] = {}
    for item in items:
        vs = item.verification_status
        count_by_status[vs] = count_by_status.get(vs, 0) + 1
    total_issues = sum(item.issue_count for item in items)
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
    return ReplayArtifactFingerprintVerificationBatchSummary(
        total_fingerprints=total,
        count_by_status=count_by_status,
        total_issues=total_issues,
        all_valid=(total > 0 and valid_count == total),
        has_mismatches=mismatch_count > 0,
        has_missing=(missing_fp + missing_art) > 0,
    )


class LocalReplayArtifactFingerprintBatchVerifier:
    """Metadata-only batch verifier for replay artifact fingerprints.

    No replay execution. No file IO. No DB. No Kafka.
    """

    def __init__(
        self,
        *,
        verifier: LocalReplayArtifactFingerprintVerifier,
        fingerprint_store: ReplayArtifactFingerprintStorePort,
        batch_report_store: ReplayArtifactFingerprintVerificationBatchReportStorePort,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._verifier = verifier
        self._fingerprint_store = fingerprint_store
        self._batch_report_store = batch_report_store
        self._now: Callable[[], datetime] = now if now is not None else _utcnow

    def _build_report(
        self,
        report_id: str,
        fingerprint_ids: tuple[str, ...],
        scope_kind: ReplayArtifactFingerprintVerificationBatchScopeKind,
        replay_plan_id: str | None,
        notes: str | None,
    ) -> ReplayArtifactFingerprintVerificationBatchReport:
        now = self._now()
        if len(fingerprint_ids) != len(set(fingerprint_ids)):
            raise ValueError("duplicate fingerprint_ids in input")
        items: list[ReplayArtifactFingerprintVerificationBatchItem] = []
        for fp_id in fingerprint_ids:
            ver_id = f"{report_id}:{fp_id}:verification"
            item_id = f"{report_id}:{fp_id}:item"
            verification = self._verifier.verify_fingerprint(ver_id, fp_id)
            item = ReplayArtifactFingerprintVerificationBatchItem(
                item_id=item_id,
                fingerprint_id=fp_id,
                verification_id=ver_id,
                verification_status=verification.status,
                artifact_kind=verification.artifact_kind,
                artifact_id=verification.artifact_id,
                replay_plan_id=verification.replay_plan_id,
                issue_count=len(verification.issues),
            )
            items.append(item)
        effective_plan_id = replay_plan_id
        if effective_plan_id is None:
            effective_plan_id = _infer_replay_plan_id_from_items(items)
        summary = _build_batch_summary(items)
        report = ReplayArtifactFingerprintVerificationBatchReport(
            report_id=report_id,
            scope_kind=scope_kind,
            replay_plan_id=effective_plan_id,
            generated_at=now,
            status=ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED,
            items=tuple(items),
            summary=summary,
            requested_fingerprint_ids=fingerprint_ids,
            notes=notes,
        )
        self._batch_report_store.save(report)
        return report

    def verify_fingerprints(
        self,
        report_id: str,
        fingerprint_ids: tuple[str, ...],
        notes: str | None = None,
    ) -> ReplayArtifactFingerprintVerificationBatchReport:
        return self._build_report(
            report_id,
            fingerprint_ids,
            ReplayArtifactFingerprintVerificationBatchScopeKind.EXPLICIT_FINGERPRINT_SET,
            None,
            notes,
        )

    def verify_replay_plan(
        self,
        report_id: str,
        replay_plan_id: str,
        notes: str | None = None,
    ) -> ReplayArtifactFingerprintVerificationBatchReport:
        fingerprints = self._fingerprint_store.list_for_replay_plan(replay_plan_id)
        fp_ids = tuple(fp.fingerprint_id for fp in fingerprints)
        return self._build_report(
            report_id,
            fp_ids,
            ReplayArtifactFingerprintVerificationBatchScopeKind.REPLAY_PLAN,
            replay_plan_id,
            notes,
        )

    def load_report(
        self, report_id: str
    ) -> ReplayArtifactFingerprintVerificationBatchReport | None:
        return self._batch_report_store.load(report_id)

    def reports_for_replay_plan(
        self, replay_plan_id: str
    ) -> tuple[ReplayArtifactFingerprintVerificationBatchReport, ...]:
        return self._batch_report_store.list_for_replay_plan(replay_plan_id)


def _latest_batch_report(
    reports: tuple[ReplayArtifactFingerprintVerificationBatchReport, ...],
) -> ReplayArtifactFingerprintVerificationBatchReport | None:
    if not reports:
        return None
    return max(reports, key=lambda r: (r.generated_at, r.report_id))


def _make_readiness_issue(
    issue_id: str,
    kind: ReplayReadinessIssueKind,
    severity: ReplayReadinessIssueSeverity,
    message: str,
    batch_report_id: str | None = None,
) -> ReplayReadinessIssue:
    return ReplayReadinessIssue(
        issue_id=issue_id,
        kind=kind,
        severity=severity,
        message=message,
        batch_report_id=batch_report_id,
    )


def _build_readiness_summary(
    fingerprint_count: int,
    latest: ReplayArtifactFingerprintVerificationBatchReport | None,
    issues: list[ReplayReadinessIssue],
) -> ReplayReadinessSummary:
    blocking = sum(1 for i in issues if i.severity is ReplayReadinessIssueSeverity.ERROR)
    warning = sum(1 for i in issues if i.severity is ReplayReadinessIssueSeverity.WARNING)
    info = sum(1 for i in issues if i.severity is ReplayReadinessIssueSeverity.INFO)
    return ReplayReadinessSummary(
        total_fingerprints=fingerprint_count,
        latest_batch_report_id=latest.report_id if latest is not None else None,
        latest_batch_total_fingerprints=(
            latest.summary.total_fingerprints if latest is not None else None
        ),
        latest_batch_total_issues=(
            latest.summary.total_issues if latest is not None else None
        ),
        latest_batch_all_valid=latest.summary.all_valid if latest is not None else None,
        blocking_issue_count=blocking,
        warning_issue_count=warning,
        info_issue_count=info,
    )


def _determine_readiness_status(
    issues: list[ReplayReadinessIssue],
    fingerprint_count: int,
    latest: ReplayArtifactFingerprintVerificationBatchReport | None,
) -> ReplayReadinessStatus:
    has_errors = any(i.severity is ReplayReadinessIssueSeverity.ERROR for i in issues)
    has_warnings = any(i.severity is ReplayReadinessIssueSeverity.WARNING for i in issues)
    if has_errors:
        return ReplayReadinessStatus.BLOCKED
    if has_warnings:
        return ReplayReadinessStatus.WARNING
    if fingerprint_count > 0 and latest is not None and latest.summary.all_valid:
        return ReplayReadinessStatus.READY
    return ReplayReadinessStatus.BLOCKED


def _collect_readiness_issues(
    fingerprints: tuple[ReplayArtifactFingerprint, ...],
    batch_reports: tuple[ReplayArtifactFingerprintVerificationBatchReport, ...],
    latest: ReplayArtifactFingerprintVerificationBatchReport | None,
    coverage_reports: tuple | None,
) -> list[ReplayReadinessIssue]:
    issues: list[ReplayReadinessIssue] = []
    if not fingerprints:
        issues.append(_make_readiness_issue(
            "readiness-no-fingerprints",
            ReplayReadinessIssueKind.NO_FINGERPRINTS,
            ReplayReadinessIssueSeverity.ERROR,
            "no fingerprints found for replay plan",
        ))
        return issues
    if not batch_reports:
        issues.append(_make_readiness_issue(
            "readiness-no-batch-report",
            ReplayReadinessIssueKind.NO_VERIFICATION_BATCH_REPORT,
            ReplayReadinessIssueSeverity.ERROR,
            "no verification batch report found for replay plan",
        ))
        return issues
    assert latest is not None
    batch_id = latest.report_id
    if latest.status is ReplayArtifactFingerprintVerificationBatchReportStatus.INVALIDATED:
        issues.append(_make_readiness_issue(
            "readiness-batch-invalidated",
            ReplayReadinessIssueKind.LATEST_BATCH_REPORT_INVALIDATED,
            ReplayReadinessIssueSeverity.ERROR,
            "latest verification batch report is invalidated",
            batch_report_id=batch_id,
        ))
    if latest.summary.has_mismatches:
        issues.append(_make_readiness_issue(
            "readiness-batch-mismatches",
            ReplayReadinessIssueKind.BATCH_HAS_MISMATCHES,
            ReplayReadinessIssueSeverity.ERROR,
            "latest batch report has fingerprint mismatches",
            batch_report_id=batch_id,
        ))
    if latest.summary.has_missing:
        issues.append(_make_readiness_issue(
            "readiness-batch-missing",
            ReplayReadinessIssueKind.BATCH_HAS_MISSING,
            ReplayReadinessIssueSeverity.ERROR,
            "latest batch report has missing fingerprints or artifacts",
            batch_report_id=batch_id,
        ))
    if not latest.summary.all_valid and latest.summary.total_fingerprints > 0:
        issues.append(_make_readiness_issue(
            "readiness-batch-not-all-valid",
            ReplayReadinessIssueKind.BATCH_NOT_ALL_VALID,
            ReplayReadinessIssueSeverity.ERROR,
            "latest batch report is not all-valid",
            batch_report_id=batch_id,
        ))
    if latest.summary.total_fingerprints != len(fingerprints):
        issues.append(_make_readiness_issue(
            "readiness-fp-count-mismatch",
            ReplayReadinessIssueKind.FINGERPRINT_COUNT_MISMATCH,
            ReplayReadinessIssueSeverity.ERROR,
            (
                f"fingerprint count mismatch: "
                f"{len(fingerprints)} stored vs "
                f"{latest.summary.total_fingerprints} in latest batch"
            ),
            batch_report_id=batch_id,
        ))
    if coverage_reports is not None:
        if not coverage_reports:
            issues.append(_make_readiness_issue(
                "readiness-coverage-missing",
                ReplayReadinessIssueKind.COVERAGE_REPORT_MISSING,
                ReplayReadinessIssueSeverity.WARNING,
                "no coverage report found for replay plan",
            ))
        else:
            latest_cov = max(coverage_reports, key=lambda r: (r.generated_at, r.report_id))
            error_count = latest_cov.summary.issue_count_by_severity.get(
                ReplayTimelineCoverageIssueSeverity.ERROR, 0
            )
            if error_count > 0:
                issues.append(_make_readiness_issue(
                    "readiness-coverage-errors",
                    ReplayReadinessIssueKind.COVERAGE_REPORT_HAS_ERRORS,
                    ReplayReadinessIssueSeverity.ERROR,
                    "latest coverage report has ERROR issues",
                ))
    return issues


class LocalReplayReadinessChecker:
    """Metadata-only readiness checker for replay plans.

    No replay execution. No file IO. No DB. No Kafka.
    """

    def __init__(
        self,
        *,
        fingerprint_store: ReplayArtifactFingerprintStorePort,
        batch_report_store: ReplayArtifactFingerprintVerificationBatchReportStorePort,
        readiness_report_store: ReplayReadinessReportStorePort,
        coverage_report_store: ReplayTimelineCoverageReportStorePort | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._fingerprint_store = fingerprint_store
        self._batch_report_store = batch_report_store
        self._readiness_report_store = readiness_report_store
        self._coverage_report_store = coverage_report_store
        self._now: Callable[[], datetime] = now if now is not None else _utcnow

    def check_replay_plan(
        self,
        report_id: str,
        replay_plan_id: str,
        notes: str | None = None,
    ) -> ReplayReadinessReport:
        fingerprints = self._fingerprint_store.list_for_replay_plan(replay_plan_id)
        batch_reports = self._batch_report_store.list_for_replay_plan(replay_plan_id)
        latest = _latest_batch_report(batch_reports)
        coverage_reports: tuple | None = None
        if self._coverage_report_store is not None:
            coverage_reports = self._coverage_report_store.list_for_replay_plan(replay_plan_id)
        issues = _collect_readiness_issues(fingerprints, batch_reports, latest, coverage_reports)
        status = _determine_readiness_status(issues, len(fingerprints), latest)
        summary = _build_readiness_summary(len(fingerprints), latest, issues)
        report = ReplayReadinessReport(
            report_id=report_id,
            replay_plan_id=replay_plan_id,
            checked_at=self._now(),
            status=status,
            summary=summary,
            issues=tuple(issues),
            notes=notes,
        )
        self._readiness_report_store.save(report)
        return report

    def load_readiness_report(self, report_id: str) -> ReplayReadinessReport | None:
        return self._readiness_report_store.load(report_id)

    def readiness_reports_for_replay_plan(
        self, replay_plan_id: str
    ) -> tuple[ReplayReadinessReport, ...]:
        return self._readiness_report_store.list_for_replay_plan(replay_plan_id)
