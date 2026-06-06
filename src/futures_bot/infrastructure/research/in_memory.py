"""In-memory research stores for local tests and contract validation.

No DB. No filesystem. No Kafka. No ML/data libraries.
"""
from __future__ import annotations

from futures_bot.domain.ids import RunId
from futures_bot.domain.research import (
    EvaluationArtifactMetadata,
    ResearchRunManifest,
    ResearchRunStatus,
)

_TERMINAL_STATUSES = frozenset(
    {
        ResearchRunStatus.COMPLETED,
        ResearchRunStatus.FAILED,
        ResearchRunStatus.INVALIDATED,
    }
)
_NON_TERMINAL_STATUSES = frozenset(
    {
        ResearchRunStatus.PLANNED,
        ResearchRunStatus.RUNNING,
    }
)


class InMemoryResearchRunManifestStore:
    """In-memory ResearchRunManifestStorePort implementation."""

    def __init__(self) -> None:
        self._manifests: dict[str, ResearchRunManifest] = {}

    def save(self, manifest: ResearchRunManifest) -> None:
        """Save manifest, enforcing updated_at and terminal status rules."""
        key = str(manifest.run_id)
        existing = self._manifests.get(key)
        if existing is not None:
            if manifest.updated_at < existing.updated_at:
                raise ValueError(
                    "manifest updated_at regression: "
                    f"existing {existing.updated_at.isoformat()}, "
                    f"new {manifest.updated_at.isoformat()}"
                )
            if (
                existing.status in _TERMINAL_STATUSES
                and manifest.status in _NON_TERMINAL_STATUSES
            ):
                raise ValueError(
                    f"invalid research run status transition: "
                    f"{existing.status} -> {manifest.status}"
                )
        self._manifests[key] = manifest

    def load(self, run_id: RunId) -> ResearchRunManifest | None:
        """Return manifest by run_id, or None."""
        return self._manifests.get(str(run_id))

    def list_all(self) -> tuple[ResearchRunManifest, ...]:
        """Return manifests sorted by created_at then run_id."""
        return tuple(
            sorted(
                self._manifests.values(),
                key=lambda manifest: (manifest.created_at, str(manifest.run_id)),
            )
        )


class InMemoryEvaluationArtifactStore:
    """In-memory EvaluationArtifactStorePort implementation."""

    def __init__(self) -> None:
        self._artifacts: dict[str, EvaluationArtifactMetadata] = {}

    def save(self, artifact: EvaluationArtifactMetadata) -> None:
        """Save artifact metadata, rejecting conflicting artifact IDs."""
        existing = self._artifacts.get(artifact.artifact_id)
        if existing is not None:
            if (
                existing.run_id != artifact.run_id
                or existing.kind != artifact.kind
                or existing.uri != artifact.uri
                or existing.content_hash != artifact.content_hash
            ):
                raise ValueError(
                    f"artifact_id conflict for {artifact.artifact_id!r}"
                )
            return
        self._artifacts[artifact.artifact_id] = artifact

    def load(self, artifact_id: str) -> EvaluationArtifactMetadata | None:
        """Return artifact metadata by artifact_id, or None."""
        return self._artifacts.get(artifact_id)

    def list_for_run(self, run_id: RunId) -> tuple[EvaluationArtifactMetadata, ...]:
        """Return artifacts for run_id sorted by created_at then artifact_id."""
        return tuple(
            sorted(
                (
                    artifact
                    for artifact in self._artifacts.values()
                    if artifact.run_id == run_id
                ),
                key=lambda artifact: (artifact.created_at, artifact.artifact_id),
            )
        )
