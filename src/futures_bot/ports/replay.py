from __future__ import annotations

from typing import Protocol

from futures_bot.domain.replay import (
    ReplayArtifactFingerprint,
    ReplayArtifactFingerprintVerification,
    ReplayArtifactFingerprintVerificationBatchReport,
    ReplayArtifactKind,
    ReplayInputBatch,
    ReplayInputDataset,
    ReplayReadinessReport,
    ReplayTimeline,
    ReplayTimelineCoverageDiff,
    ReplayTimelineCoverageReport,
    ReplayTimelineCursor,
)


class ReplayInputDatasetStorePort(Protocol):
    """Persistence abstraction for replay input dataset metadata."""

    def save(self, dataset: ReplayInputDataset) -> None:
        """Persist replay input dataset metadata."""
        ...

    def load(self, input_dataset_id: str) -> ReplayInputDataset | None:
        """Return replay input dataset by input_dataset_id, or None."""
        ...

    def list_for_dataset(self, dataset_id: str) -> tuple[ReplayInputDataset, ...]:
        """Return input datasets for dataset_id in deterministic order."""
        ...

    def list_all(self) -> tuple[ReplayInputDataset, ...]:
        """Return all input datasets in deterministic order."""
        ...


class ReplayInputBatchStorePort(Protocol):
    """Persistence abstraction for replay input batch metadata."""

    def save(self, batch: ReplayInputBatch) -> None:
        """Persist replay input batch metadata."""
        ...

    def load(self, batch_id: str) -> ReplayInputBatch | None:
        """Return replay input batch by batch_id, or None."""
        ...

    def list_for_replay_plan(self, replay_plan_id: str) -> tuple[ReplayInputBatch, ...]:
        """Return input batches for replay_plan_id in deterministic order."""
        ...

    def list_for_input_dataset(
        self, input_dataset_id: str
    ) -> tuple[ReplayInputBatch, ...]:
        """Return input batches for input_dataset_id in deterministic order."""
        ...


class ReplayTimelineStorePort(Protocol):
    """Persistence abstraction for replay timeline metadata."""

    def save(self, timeline: ReplayTimeline) -> None:
        """Persist replay timeline metadata."""
        ...

    def load(self, timeline_id: str) -> ReplayTimeline | None:
        """Return replay timeline by timeline_id, or None."""
        ...

    def list_for_replay_plan(self, replay_plan_id: str) -> tuple[ReplayTimeline, ...]:
        """Return replay timelines for replay_plan_id in deterministic order."""
        ...


class ReplayTimelineCursorStorePort(Protocol):
    """Persistence abstraction for replay timeline cursor metadata."""

    def save(self, cursor: ReplayTimelineCursor) -> None:
        """Persist replay timeline cursor metadata."""
        ...

    def load(self, cursor_id: str) -> ReplayTimelineCursor | None:
        """Return cursor by cursor_id, or None."""
        ...

    def list_for_timeline(self, timeline_id: str) -> tuple[ReplayTimelineCursor, ...]:
        """Return cursors for timeline_id in deterministic order."""
        ...


class ReplayTimelineCoverageReportStorePort(Protocol):
    """Persistence abstraction for replay timeline coverage report metadata."""

    def save(self, report: ReplayTimelineCoverageReport) -> None:
        """Persist coverage report metadata."""
        ...

    def load(self, report_id: str) -> ReplayTimelineCoverageReport | None:
        """Return coverage report by report_id, or None."""
        ...

    def list_for_timeline(
        self, timeline_id: str
    ) -> tuple[ReplayTimelineCoverageReport, ...]:
        """Return coverage reports for timeline_id in deterministic order."""
        ...

    def list_for_replay_plan(
        self, replay_plan_id: str
    ) -> tuple[ReplayTimelineCoverageReport, ...]:
        """Return coverage reports for replay_plan_id in deterministic order."""
        ...


class ReplayTimelineCoverageDiffStorePort(Protocol):
    """Persistence abstraction for replay timeline coverage diff metadata."""

    def save(self, diff: ReplayTimelineCoverageDiff) -> None:
        """Persist coverage diff metadata."""
        ...

    def load(self, diff_id: str) -> ReplayTimelineCoverageDiff | None:
        """Return coverage diff by diff_id, or None."""
        ...

    def list_for_report(
        self, report_id: str
    ) -> tuple[ReplayTimelineCoverageDiff, ...]:
        """Return diffs where baseline_report_id or candidate_report_id matches."""
        ...

    def list_for_replay_plan(
        self, replay_plan_id: str
    ) -> tuple[ReplayTimelineCoverageDiff, ...]:
        """Return diffs where baseline_replay_plan_id or candidate_replay_plan_id matches."""
        ...

    def list_all(self) -> tuple[ReplayTimelineCoverageDiff, ...]:
        """Return all diffs in deterministic order."""
        ...


class ReplayArtifactFingerprintStorePort(Protocol):
    """Persistence abstraction for replay artifact integrity fingerprints."""

    def save(self, fingerprint: ReplayArtifactFingerprint) -> None:
        """Persist fingerprint; idempotent if identical, raises on conflict."""
        ...

    def load(self, fingerprint_id: str) -> ReplayArtifactFingerprint | None:
        """Return fingerprint by fingerprint_id, or None."""
        ...

    def list_for_artifact(
        self, artifact_kind: ReplayArtifactKind, artifact_id: str
    ) -> tuple[ReplayArtifactFingerprint, ...]:
        """Return fingerprints for (artifact_kind, artifact_id) in deterministic order."""
        ...

    def list_for_replay_plan(
        self, replay_plan_id: str
    ) -> tuple[ReplayArtifactFingerprint, ...]:
        """Return fingerprints where replay_plan_id matches, in deterministic order."""
        ...

    def list_all(self) -> tuple[ReplayArtifactFingerprint, ...]:
        """Return all fingerprints in deterministic order."""
        ...


class ReplayArtifactFingerprintVerificationStorePort(Protocol):
    """Persistence abstraction for replay artifact fingerprint verifications."""

    def save(self, verification: ReplayArtifactFingerprintVerification) -> None:
        """Persist verification; idempotent if identical, raises on conflict."""
        ...

    def load(
        self, verification_id: str
    ) -> ReplayArtifactFingerprintVerification | None:
        """Return verification by verification_id, or None."""
        ...

    def list_for_fingerprint(
        self, fingerprint_id: str
    ) -> tuple[ReplayArtifactFingerprintVerification, ...]:
        """Return verifications for fingerprint_id in deterministic order."""
        ...

    def list_for_artifact(
        self, artifact_kind: ReplayArtifactKind, artifact_id: str
    ) -> tuple[ReplayArtifactFingerprintVerification, ...]:
        """Return verifications for (artifact_kind, artifact_id) in deterministic order."""
        ...

    def list_for_replay_plan(
        self, replay_plan_id: str
    ) -> tuple[ReplayArtifactFingerprintVerification, ...]:
        """Return verifications where replay_plan_id matches, in deterministic order."""
        ...

    def list_all(self) -> tuple[ReplayArtifactFingerprintVerification, ...]:
        """Return all verifications in deterministic order."""
        ...


class ReplayArtifactFingerprintVerificationBatchReportStorePort(Protocol):
    """Persistence abstraction for replay artifact fingerprint verification batch reports."""

    def save(self, report: ReplayArtifactFingerprintVerificationBatchReport) -> None:
        """Persist report; idempotent if identical, raises on conflict."""
        ...

    def load(
        self, report_id: str
    ) -> ReplayArtifactFingerprintVerificationBatchReport | None:
        """Return report by report_id, or None."""
        ...

    def list_for_replay_plan(
        self, replay_plan_id: str
    ) -> tuple[ReplayArtifactFingerprintVerificationBatchReport, ...]:
        """Return reports where replay_plan_id matches, in deterministic order."""
        ...

    def list_all(self) -> tuple[ReplayArtifactFingerprintVerificationBatchReport, ...]:
        """Return all reports in deterministic order."""
        ...


class ReplayReadinessReportStorePort(Protocol):
    """Persistence abstraction for replay readiness reports."""

    def save(self, report: ReplayReadinessReport) -> None:
        """Persist report; idempotent if identical, raises on conflict."""
        ...

    def load(self, report_id: str) -> ReplayReadinessReport | None:
        """Return report by report_id, or None."""
        ...

    def list_for_replay_plan(
        self, replay_plan_id: str
    ) -> tuple[ReplayReadinessReport, ...]:
        """Return reports where replay_plan_id matches, in deterministic order."""
        ...

    def list_all(self) -> tuple[ReplayReadinessReport, ...]:
        """Return all reports in deterministic order."""
        ...
