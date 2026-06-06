"""Local research run recorder.

No filesystem writes. No plotting. No DB. No Kafka. No runtime loops.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from futures_bot.domain.ids import RunId
from futures_bot.domain.research import (
    EvaluationArtifactMetadata,
    ResearchRunManifest,
    ResearchRunStatus,
)
from futures_bot.ports.research import (
    EvaluationArtifactStorePort,
    ResearchRunManifestStorePort,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LocalResearchRunRecorder:
    """Metadata-only local recorder for research/evaluation run reproducibility."""

    def __init__(
        self,
        *,
        manifest_store: ResearchRunManifestStorePort,
        artifact_store: EvaluationArtifactStorePort,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._manifest_store = manifest_store
        self._artifact_store = artifact_store
        self._now: Callable[[], datetime] = now if now is not None else _utcnow

    def create_manifest(self, manifest: ResearchRunManifest) -> ResearchRunManifest:
        """Save a planned research run manifest."""
        self._manifest_store.save(manifest)
        return manifest

    def mark_running(self, run_id: RunId) -> ResearchRunManifest:
        """Mark a research run as running."""
        return self._update_status(run_id, ResearchRunStatus.RUNNING)

    def mark_completed(self, run_id: RunId) -> ResearchRunManifest:
        """Mark a research run as completed."""
        return self._update_status(run_id, ResearchRunStatus.COMPLETED)

    def mark_failed(self, run_id: RunId, reason: str) -> ResearchRunManifest:
        """Mark a research run as failed and include reason in notes."""
        return self._update_status(
            run_id,
            ResearchRunStatus.FAILED,
            reason=reason,
        )

    def invalidate(self, run_id: RunId, reason: str) -> ResearchRunManifest:
        """Mark a research run as invalidated and include reason in notes."""
        return self._update_status(
            run_id,
            ResearchRunStatus.INVALIDATED,
            reason=reason,
        )

    def record_artifact(
        self, artifact: EvaluationArtifactMetadata
    ) -> EvaluationArtifactMetadata:
        """Record artifact metadata only; does not write artifact files."""
        self._artifact_store.save(artifact)
        return artifact

    def artifacts_for_run(self, run_id: RunId) -> tuple[EvaluationArtifactMetadata, ...]:
        """Return recorded artifact metadata for run_id."""
        return self._artifact_store.list_for_run(run_id)

    def _update_status(
        self,
        run_id: RunId,
        status: ResearchRunStatus,
        *,
        reason: str | None = None,
    ) -> ResearchRunManifest:
        manifest = self._manifest_store.load(run_id)
        if manifest is None:
            raise KeyError(f"research run manifest not found: {run_id!s}")

        updated = manifest.model_copy(
            update={
                "status": status,
                "updated_at": self._now(),
                "notes": _append_reason(manifest.notes, reason),
            }
        )
        self._manifest_store.save(updated)
        return updated


def _append_reason(existing_notes: str | None, reason: str | None) -> str | None:
    if reason is None:
        return existing_notes
    if not reason or reason != reason.strip():
        raise ValueError("reason must be a non-empty trimmed string")
    if existing_notes is None:
        return reason
    return f"{existing_notes}\n{reason}"
