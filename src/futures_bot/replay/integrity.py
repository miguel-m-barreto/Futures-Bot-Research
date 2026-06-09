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
    ReplayArtifactFingerprintVerificationIssue,
    ReplayArtifactFingerprintVerificationIssueKind,
    ReplayArtifactFingerprintVerificationIssueSeverity,
    ReplayArtifactFingerprintVerificationStatus,
    ReplayArtifactHashAlgorithm,
    ReplayArtifactKind,
)
from futures_bot.ports.replay import (
    ReplayArtifactFingerprintStorePort,
    ReplayArtifactFingerprintVerificationStorePort,
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
