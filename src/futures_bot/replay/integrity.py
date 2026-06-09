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
    ReplayArtifactHashAlgorithm,
    ReplayArtifactKind,
)
from futures_bot.ports.replay import (
    ReplayArtifactFingerprintStorePort,
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
