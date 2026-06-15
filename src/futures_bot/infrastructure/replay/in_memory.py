"""In-memory replay input stores.

No DB. No filesystem. No Kafka. No market data loading.
"""
from __future__ import annotations

from futures_bot.domain.replay import (
    ReplayArtifactFingerprint,
    ReplayArtifactFingerprintVerification,
    ReplayArtifactFingerprintVerificationBatchReport,
    ReplayArtifactKind,
    ReplayEventDispatchReceipt,
    ReplayInputBatch,
    ReplayInputDataset,
    ReplayReadinessReport,
    ReplayRunManifest,
    ReplayRunState,
    ReplayRunStatus,
    ReplayTimeline,
    ReplayTimelineCoverageDiff,
    ReplayTimelineCoverageReport,
    ReplayTimelineCursor,
    ReplayTimelineCursorStatus,
    validate_replay_run_state_transition,
)

_CURSOR_ALLOWED_TRANSITIONS: dict[
    ReplayTimelineCursorStatus, frozenset[ReplayTimelineCursorStatus]
] = {
    ReplayTimelineCursorStatus.CREATED: frozenset({
        ReplayTimelineCursorStatus.ADVANCED,
        ReplayTimelineCursorStatus.COMPLETED,
        ReplayTimelineCursorStatus.INVALIDATED,
    }),
    ReplayTimelineCursorStatus.ADVANCED: frozenset({
        ReplayTimelineCursorStatus.ADVANCED,
        ReplayTimelineCursorStatus.COMPLETED,
        ReplayTimelineCursorStatus.INVALIDATED,
    }),
    ReplayTimelineCursorStatus.COMPLETED: frozenset({
        ReplayTimelineCursorStatus.INVALIDATED,
    }),
    ReplayTimelineCursorStatus.INVALIDATED: frozenset(),
}


class InMemoryReplayInputDatasetStore:
    """In-memory ReplayInputDatasetStorePort implementation."""

    def __init__(self) -> None:
        self._datasets: dict[str, ReplayInputDataset] = {}

    def save(self, dataset: ReplayInputDataset) -> None:
        """Save replay input dataset metadata, rejecting conflicting IDs."""
        dataset = ReplayInputDataset.model_validate(dataset.model_dump())
        existing = self._datasets.get(dataset.input_dataset_id)
        if existing is not None:
            if existing != dataset:
                raise ValueError(
                    f"input_dataset_id conflict for {dataset.input_dataset_id!r}"
                )
            return
        self._datasets[dataset.input_dataset_id] = dataset

    def load(self, input_dataset_id: str) -> ReplayInputDataset | None:
        """Return replay input dataset by input_dataset_id, or None."""
        return self._datasets.get(input_dataset_id)

    def list_for_dataset(self, dataset_id: str) -> tuple[ReplayInputDataset, ...]:
        """Return input datasets for dataset_id sorted by created_at then id."""
        return tuple(
            sorted(
                (
                    dataset
                    for dataset in self._datasets.values()
                    if dataset.dataset_id == dataset_id
                ),
                key=lambda dataset: (dataset.created_at, dataset.input_dataset_id),
            )
        )

    def list_all(self) -> tuple[ReplayInputDataset, ...]:
        """Return input datasets sorted by created_at then id."""
        return tuple(
            sorted(
                self._datasets.values(),
                key=lambda dataset: (dataset.created_at, dataset.input_dataset_id),
            )
        )


class InMemoryReplayInputBatchStore:
    """In-memory ReplayInputBatchStorePort implementation."""

    def __init__(self) -> None:
        self._batches: dict[str, ReplayInputBatch] = {}

    def save(self, batch: ReplayInputBatch) -> None:
        """Save replay input batch metadata, rejecting conflicting IDs."""
        batch = ReplayInputBatch.model_validate(batch.model_dump())
        existing = self._batches.get(batch.batch_id)
        if existing is not None:
            if existing != batch:
                raise ValueError(f"batch_id conflict for {batch.batch_id!r}")
            return
        self._batches[batch.batch_id] = batch

    def load(self, batch_id: str) -> ReplayInputBatch | None:
        """Return replay input batch by batch_id, or None."""
        return self._batches.get(batch_id)

    def list_for_replay_plan(self, replay_plan_id: str) -> tuple[ReplayInputBatch, ...]:
        """Return input batches for replay_plan_id sorted by created_at then id."""
        return tuple(
            sorted(
                (
                    batch
                    for batch in self._batches.values()
                    if batch.replay_plan_id == replay_plan_id
                ),
                key=lambda batch: (batch.created_at, batch.batch_id),
            )
        )

    def list_for_input_dataset(
        self, input_dataset_id: str
    ) -> tuple[ReplayInputBatch, ...]:
        """Return input batches for input_dataset_id sorted by created_at then id."""
        return tuple(
            sorted(
                (
                    batch
                    for batch in self._batches.values()
                    if batch.input_dataset_id == input_dataset_id
                ),
                key=lambda batch: (batch.created_at, batch.batch_id),
            )
        )


class InMemoryReplayTimelineStore:
    """In-memory ReplayTimelineStorePort implementation."""

    def __init__(self) -> None:
        self._timelines: dict[str, ReplayTimeline] = {}

    def save(self, timeline: ReplayTimeline) -> None:
        """Save replay timeline metadata, rejecting conflicting IDs."""
        timeline = ReplayTimeline.model_validate(timeline.model_dump())
        existing = self._timelines.get(timeline.timeline_id)
        if existing is not None:
            if existing != timeline:
                raise ValueError(
                    f"timeline_id conflict for {timeline.timeline_id!r}"
                )
            return
        self._timelines[timeline.timeline_id] = timeline

    def load(self, timeline_id: str) -> ReplayTimeline | None:
        """Return replay timeline by timeline_id, or None."""
        return self._timelines.get(timeline_id)

    def list_for_replay_plan(self, replay_plan_id: str) -> tuple[ReplayTimeline, ...]:
        """Return timelines for replay_plan_id sorted by created_at then timeline_id."""
        return tuple(
            sorted(
                (t for t in self._timelines.values() if t.replay_plan_id == replay_plan_id),
                key=lambda t: (t.created_at, t.timeline_id),
            )
        )


class InMemoryReplayTimelineCursorStore:
    """In-memory ReplayTimelineCursorStorePort implementation."""

    def __init__(self) -> None:
        self._cursors: dict[str, ReplayTimelineCursor] = {}

    def save(self, cursor: ReplayTimelineCursor) -> None:
        """Save cursor, enforcing valid state transitions."""
        cursor = ReplayTimelineCursor.model_validate(cursor.model_dump())
        existing = self._cursors.get(cursor.cursor_id)
        if existing is None:
            self._cursors[cursor.cursor_id] = cursor
            return
        if existing.timeline_id != cursor.timeline_id:
            raise ValueError("cursor timeline_id cannot change")
        if existing.replay_plan_id != cursor.replay_plan_id:
            raise ValueError("cursor replay_plan_id cannot change")
        if cursor == existing:
            return
        if cursor.updated_at < existing.updated_at:
            raise ValueError("cursor updated_at cannot go backwards")
        if existing.status is ReplayTimelineCursorStatus.INVALIDATED:
            raise ValueError("INVALIDATED cursor is terminal")
        allowed = _CURSOR_ALLOWED_TRANSITIONS.get(existing.status, frozenset())
        if cursor.status not in allowed:
            raise ValueError(
                f"invalid cursor transition {existing.status!r} -> {cursor.status!r}"
            )
        if (
            existing.status is ReplayTimelineCursorStatus.ADVANCED
            and cursor.status is ReplayTimelineCursorStatus.ADVANCED
            and cursor.next_order_index < existing.next_order_index
        ):
            raise ValueError("next_order_index cannot decrease for ADVANCED -> ADVANCED")
        self._cursors[cursor.cursor_id] = cursor

    def load(self, cursor_id: str) -> ReplayTimelineCursor | None:
        """Return cursor by cursor_id, or None."""
        return self._cursors.get(cursor_id)

    def list_for_timeline(self, timeline_id: str) -> tuple[ReplayTimelineCursor, ...]:
        """Return cursors for timeline_id sorted by updated_at then cursor_id."""
        return tuple(
            sorted(
                (c for c in self._cursors.values() if c.timeline_id == timeline_id),
                key=lambda c: (c.updated_at, c.cursor_id),
            )
        )


class InMemoryReplayTimelineCoverageReportStore:
    """In-memory ReplayTimelineCoverageReportStorePort implementation."""

    def __init__(self) -> None:
        self._reports: dict[str, ReplayTimelineCoverageReport] = {}

    def save(self, report: ReplayTimelineCoverageReport) -> None:
        """Save coverage report metadata, rejecting conflicting IDs."""
        report = ReplayTimelineCoverageReport.model_validate(report.model_dump())
        existing = self._reports.get(report.report_id)
        if existing is not None:
            if existing != report:
                raise ValueError(f"report_id conflict for {report.report_id!r}")
            return
        self._reports[report.report_id] = report

    def load(self, report_id: str) -> ReplayTimelineCoverageReport | None:
        """Return coverage report by report_id, or None."""
        return self._reports.get(report_id)

    def list_for_timeline(
        self, timeline_id: str
    ) -> tuple[ReplayTimelineCoverageReport, ...]:
        """Return coverage reports for timeline_id sorted by generated_at then report_id."""
        return tuple(
            sorted(
                (r for r in self._reports.values() if r.timeline_id == timeline_id),
                key=lambda r: (r.generated_at, r.report_id),
            )
        )

    def list_for_replay_plan(
        self, replay_plan_id: str
    ) -> tuple[ReplayTimelineCoverageReport, ...]:
        """Return coverage reports for replay_plan_id sorted by generated_at then report_id."""
        return tuple(
            sorted(
                (r for r in self._reports.values() if r.replay_plan_id == replay_plan_id),
                key=lambda r: (r.generated_at, r.report_id),
            )
        )


class InMemoryReplayTimelineCoverageDiffStore:
    """In-memory ReplayTimelineCoverageDiffStorePort implementation."""

    def __init__(self) -> None:
        self._diffs: dict[str, ReplayTimelineCoverageDiff] = {}

    def save(self, diff: ReplayTimelineCoverageDiff) -> None:
        """Save coverage diff metadata, rejecting conflicting IDs."""
        diff = ReplayTimelineCoverageDiff.model_validate(diff.model_dump())
        existing = self._diffs.get(diff.diff_id)
        if existing is not None:
            if existing != diff:
                raise ValueError(f"diff_id conflict for {diff.diff_id!r}")
            return
        self._diffs[diff.diff_id] = diff

    def load(self, diff_id: str) -> ReplayTimelineCoverageDiff | None:
        """Return coverage diff by diff_id, or None."""
        return self._diffs.get(diff_id)

    def list_for_report(
        self, report_id: str
    ) -> tuple[ReplayTimelineCoverageDiff, ...]:
        """Return diffs where baseline_report_id or candidate_report_id matches."""
        return tuple(
            sorted(
                (
                    d for d in self._diffs.values()
                    if report_id in {d.baseline_report_id, d.candidate_report_id}
                ),
                key=lambda d: (d.generated_at, d.diff_id),
            )
        )

    def list_for_replay_plan(
        self, replay_plan_id: str
    ) -> tuple[ReplayTimelineCoverageDiff, ...]:
        """Return diffs where baseline_replay_plan_id or candidate_replay_plan_id matches."""
        return tuple(
            sorted(
                (
                    d for d in self._diffs.values()
                    if replay_plan_id
                    in {d.baseline_replay_plan_id, d.candidate_replay_plan_id}
                ),
                key=lambda d: (d.generated_at, d.diff_id),
            )
        )

    def list_all(self) -> tuple[ReplayTimelineCoverageDiff, ...]:
        """Return all diffs sorted by generated_at then diff_id."""
        return tuple(
            sorted(
                self._diffs.values(),
                key=lambda d: (d.generated_at, d.diff_id),
            )
        )


class InMemoryReplayArtifactFingerprintStore:
    """In-memory store for replay artifact integrity fingerprints."""

    def __init__(self) -> None:
        self._fingerprints: dict[str, ReplayArtifactFingerprint] = {}

    def save(self, fingerprint: ReplayArtifactFingerprint) -> None:
        """Persist fingerprint; idempotent if identical, raises on conflict."""
        fingerprint = ReplayArtifactFingerprint.model_validate(fingerprint.model_dump())
        existing = self._fingerprints.get(fingerprint.fingerprint_id)
        if existing is not None:
            if existing != fingerprint:
                raise ValueError(
                    f"fingerprint_id conflict for {fingerprint.fingerprint_id!r}"
                )
            return
        self._fingerprints[fingerprint.fingerprint_id] = fingerprint

    def load(self, fingerprint_id: str) -> ReplayArtifactFingerprint | None:
        """Return fingerprint by fingerprint_id, or None."""
        return self._fingerprints.get(fingerprint_id)

    def list_for_artifact(
        self, artifact_kind: ReplayArtifactKind, artifact_id: str
    ) -> tuple[ReplayArtifactFingerprint, ...]:
        """Return fingerprints for (artifact_kind, artifact_id) in deterministic order."""
        return tuple(
            sorted(
                (
                    f for f in self._fingerprints.values()
                    if f.artifact_kind is artifact_kind and f.artifact_id == artifact_id
                ),
                key=lambda f: (f.generated_at, f.fingerprint_id),
            )
        )

    def list_for_replay_plan(
        self, replay_plan_id: str
    ) -> tuple[ReplayArtifactFingerprint, ...]:
        """Return fingerprints where replay_plan_id matches, in deterministic order."""
        return tuple(
            sorted(
                (
                    f for f in self._fingerprints.values()
                    if f.replay_plan_id == replay_plan_id
                ),
                key=lambda f: (f.generated_at, f.fingerprint_id),
            )
        )

    def list_all(self) -> tuple[ReplayArtifactFingerprint, ...]:
        """Return all fingerprints sorted by generated_at then fingerprint_id."""
        return tuple(
            sorted(
                self._fingerprints.values(),
                key=lambda f: (f.generated_at, f.fingerprint_id),
            )
        )


class InMemoryReplayArtifactFingerprintVerificationStore:
    """In-memory store for replay artifact fingerprint verifications.

    No DB. No filesystem. No Kafka.
    """

    def __init__(self) -> None:
        self._verifications: dict[str, ReplayArtifactFingerprintVerification] = {}

    def save(self, verification: ReplayArtifactFingerprintVerification) -> None:
        """Persist verification; idempotent if identical, raises on conflict."""
        revalidated = ReplayArtifactFingerprintVerification.model_validate(
            verification.model_dump()
        )
        existing = self._verifications.get(revalidated.verification_id)
        if existing is not None:
            if existing != revalidated:
                raise ValueError(
                    f"verification_id conflict for {revalidated.verification_id!r}"
                )
            return
        self._verifications[revalidated.verification_id] = revalidated

    def load(
        self, verification_id: str
    ) -> ReplayArtifactFingerprintVerification | None:
        """Return verification by verification_id, or None."""
        return self._verifications.get(verification_id)

    def list_for_fingerprint(
        self, fingerprint_id: str
    ) -> tuple[ReplayArtifactFingerprintVerification, ...]:
        """Return verifications for fingerprint_id in deterministic order."""
        return tuple(
            sorted(
                (v for v in self._verifications.values() if v.fingerprint_id == fingerprint_id),
                key=lambda v: (v.verified_at, v.verification_id),
            )
        )

    def list_for_artifact(
        self, artifact_kind: ReplayArtifactKind, artifact_id: str
    ) -> tuple[ReplayArtifactFingerprintVerification, ...]:
        """Return verifications for (artifact_kind, artifact_id) in deterministic order."""
        return tuple(
            sorted(
                (
                    v for v in self._verifications.values()
                    if v.artifact_kind is artifact_kind and v.artifact_id == artifact_id
                ),
                key=lambda v: (v.verified_at, v.verification_id),
            )
        )

    def list_for_replay_plan(
        self, replay_plan_id: str
    ) -> tuple[ReplayArtifactFingerprintVerification, ...]:
        """Return verifications where replay_plan_id matches, in deterministic order."""
        return tuple(
            sorted(
                (v for v in self._verifications.values() if v.replay_plan_id == replay_plan_id),
                key=lambda v: (v.verified_at, v.verification_id),
            )
        )

    def list_all(self) -> tuple[ReplayArtifactFingerprintVerification, ...]:
        """Return all verifications sorted by verified_at then verification_id."""
        return tuple(
            sorted(
                self._verifications.values(),
                key=lambda v: (v.verified_at, v.verification_id),
            )
        )


class InMemoryReplayArtifactFingerprintVerificationBatchReportStore:
    """In-memory store for replay artifact fingerprint verification batch reports.

    No DB. No filesystem. No Kafka.
    """

    def __init__(self) -> None:
        self._batch_reports: dict[str, ReplayArtifactFingerprintVerificationBatchReport] = {}

    def save(self, report: ReplayArtifactFingerprintVerificationBatchReport) -> None:
        """Persist report; idempotent if identical, raises on conflict."""
        revalidated = ReplayArtifactFingerprintVerificationBatchReport.model_validate(
            report.model_dump()
        )
        existing = self._batch_reports.get(revalidated.report_id)
        if existing is not None:
            if existing != revalidated:
                raise ValueError(
                    f"report_id conflict for {revalidated.report_id!r}"
                )
            return
        self._batch_reports[revalidated.report_id] = revalidated

    def load(
        self, report_id: str
    ) -> ReplayArtifactFingerprintVerificationBatchReport | None:
        """Return report by report_id, or None."""
        return self._batch_reports.get(report_id)

    def list_for_replay_plan(
        self, replay_plan_id: str
    ) -> tuple[ReplayArtifactFingerprintVerificationBatchReport, ...]:
        """Return reports where replay_plan_id matches, in deterministic order."""
        return tuple(
            sorted(
                (r for r in self._batch_reports.values() if r.replay_plan_id == replay_plan_id),
                key=lambda r: (r.generated_at, r.report_id),
            )
        )

    def list_all(self) -> tuple[ReplayArtifactFingerprintVerificationBatchReport, ...]:
        """Return all reports sorted by generated_at then report_id."""
        return tuple(
            sorted(
                self._batch_reports.values(),
                key=lambda r: (r.generated_at, r.report_id),
            )
        )


class InMemoryReplayReadinessReportStore:
    """In-memory store for replay readiness reports.

    No DB. No filesystem. No Kafka.
    """

    def __init__(self) -> None:
        self._reports: dict[str, ReplayReadinessReport] = {}

    def save(self, report: ReplayReadinessReport) -> None:
        """Persist report; idempotent if identical, raises on conflict."""
        revalidated = ReplayReadinessReport.model_validate(report.model_dump())
        existing = self._reports.get(revalidated.report_id)
        if existing is not None:
            if existing != revalidated:
                raise ValueError(f"report_id conflict for {revalidated.report_id!r}")
            return
        self._reports[revalidated.report_id] = revalidated

    def load(self, report_id: str) -> ReplayReadinessReport | None:
        """Return report by report_id, or None."""
        return self._reports.get(report_id)

    def list_for_replay_plan(
        self, replay_plan_id: str
    ) -> tuple[ReplayReadinessReport, ...]:
        """Return reports where replay_plan_id matches, in deterministic order."""
        return tuple(
            sorted(
                (r for r in self._reports.values() if r.replay_plan_id == replay_plan_id),
                key=lambda r: (r.checked_at, r.report_id),
            )
        )

    def list_all(self) -> tuple[ReplayReadinessReport, ...]:
        """Return all reports sorted by checked_at then report_id."""
        return tuple(
            sorted(
                self._reports.values(),
                key=lambda r: (r.checked_at, r.report_id),
            )
        )


class InMemoryReplayRunManifestStore:
    """In-memory store for replay run manifests.

    No DB. No filesystem. No Kafka.
    """

    def __init__(self) -> None:
        self._manifests: dict[str, ReplayRunManifest] = {}

    def save(self, manifest: ReplayRunManifest) -> None:
        """Persist manifest; idempotent if identical, raises on conflict."""
        revalidated = ReplayRunManifest.model_validate(manifest.model_dump())
        existing = self._manifests.get(revalidated.manifest_id)
        if existing is not None:
            if existing != revalidated:
                raise ValueError(f"manifest_id conflict for {revalidated.manifest_id!r}")
            return
        self._manifests[revalidated.manifest_id] = revalidated

    def load(self, manifest_id: str) -> ReplayRunManifest | None:
        """Return manifest by manifest_id, or None."""
        return self._manifests.get(manifest_id)

    def list_for_replay_plan(
        self, replay_plan_id: str
    ) -> tuple[ReplayRunManifest, ...]:
        """Return manifests where replay_plan_id matches, in deterministic order."""
        return tuple(
            sorted(
                (m for m in self._manifests.values() if m.replay_plan_id == replay_plan_id),
                key=lambda m: (m.created_at, m.manifest_id),
            )
        )

    def list_all(self) -> tuple[ReplayRunManifest, ...]:
        """Return all manifests sorted by created_at then manifest_id."""
        return tuple(
            sorted(
                self._manifests.values(),
                key=lambda m: (m.created_at, m.manifest_id),
            )
        )


class InMemoryReplayRunStateStore:
    """In-memory replay runtime state store with optimistic revision checks.

    No DB. No filesystem. No Kafka.
    """

    def __init__(self) -> None:
        self._states: dict[str, ReplayRunState] = {}

    def create(self, state: ReplayRunState) -> None:
        """Persist a new run state, allowing exact duplicate creates."""
        revalidated = ReplayRunState.model_validate(state.model_dump())
        if revalidated.status is not ReplayRunStatus.CREATED:
            raise ValueError("replay run state create requires CREATED status")
        if revalidated.revision != 0:
            raise ValueError("replay run state create requires revision 0")
        existing = self._states.get(revalidated.run_id)
        if existing is not None:
            if existing != revalidated:
                raise ValueError(f"run_id conflict for {revalidated.run_id!r}")
            return
        self._states[revalidated.run_id] = revalidated

    def load(self, run_id: str) -> ReplayRunState | None:
        """Return replay run state by run_id, or None."""
        return self._states.get(run_id)

    def replace(self, state: ReplayRunState, expected_revision: int) -> None:
        """Replace run state if the stored revision matches expected_revision."""
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise ValueError("expected_revision must be a strict integer")
        revalidated = ReplayRunState.model_validate(state.model_dump())
        existing = self._states.get(revalidated.run_id)
        if existing is None:
            raise ValueError(f"replay run state not found: {revalidated.run_id!r}")
        if existing.revision != expected_revision:
            raise ValueError(
                "stale replay run revision: "
                f"expected {expected_revision}, stored {existing.revision}"
            )
        validate_replay_run_state_transition(existing, revalidated)
        self._states[revalidated.run_id] = revalidated

    def list_for_replay_plan(
        self,
        replay_plan_id: str,
    ) -> tuple[ReplayRunState, ...]:
        """Return run states for replay_plan_id sorted by created_at then run_id."""
        return tuple(
            sorted(
                (s for s in self._states.values() if s.replay_plan_id == replay_plan_id),
                key=lambda s: (s.created_at, s.run_id),
            )
        )

    def list_all(self) -> tuple[ReplayRunState, ...]:
        """Return all run states sorted by created_at then run_id."""
        return tuple(
            sorted(
                self._states.values(),
                key=lambda s: (s.created_at, s.run_id),
            )
        )


class InMemoryReplayEventDispatchReceiptStore:
    """Append-only in-memory replay event dispatch receipt store.

    No DB. No filesystem. No Kafka.
    """

    def __init__(self) -> None:
        self._receipts: dict[str, ReplayEventDispatchReceipt] = {}

    def save(self, receipt: ReplayEventDispatchReceipt) -> None:
        """Save a receipt, allowing exact duplicate saves only."""
        revalidated = ReplayEventDispatchReceipt.model_validate(receipt.model_dump())
        existing = self._receipts.get(revalidated.receipt_id)
        if existing is not None:
            if existing != revalidated:
                raise ValueError(f"receipt_id conflict for {revalidated.receipt_id!r}")
            return
        self._receipts[revalidated.receipt_id] = revalidated

    def load(self, receipt_id: str) -> ReplayEventDispatchReceipt | None:
        """Return receipt by receipt_id, or None."""
        return self._receipts.get(receipt_id)

    def list_for_run(self, run_id: str) -> tuple[ReplayEventDispatchReceipt, ...]:
        """Return receipts for run_id sorted by event_order_index then receipt_id."""
        return tuple(
            sorted(
                (r for r in self._receipts.values() if r.run_id == run_id),
                key=lambda r: (r.event_order_index, r.receipt_id),
            )
        )

    def list_all(self) -> tuple[ReplayEventDispatchReceipt, ...]:
        """Return all receipts sorted by run_id, event_order_index, receipt_id."""
        return tuple(
            sorted(
                self._receipts.values(),
                key=lambda r: (r.run_id, r.event_order_index, r.receipt_id),
            )
        )
