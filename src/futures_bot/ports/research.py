from __future__ import annotations

from typing import Protocol

from futures_bot.domain.ids import RunId
from futures_bot.domain.research import EvaluationArtifactMetadata, ResearchRunManifest


class ResearchRunManifestStorePort(Protocol):
    """Persistence abstraction for research run manifests."""

    def save(self, manifest: ResearchRunManifest) -> None:
        """Persist a research run manifest."""
        ...

    def load(self, run_id: RunId) -> ResearchRunManifest | None:
        """Return manifest by run_id, or None."""
        ...

    def list_all(self) -> tuple[ResearchRunManifest, ...]:
        """Return all manifests in deterministic order."""
        ...


class EvaluationArtifactStorePort(Protocol):
    """Persistence abstraction for evaluation artifact metadata."""

    def save(self, artifact: EvaluationArtifactMetadata) -> None:
        """Persist evaluation artifact metadata."""
        ...

    def load(self, artifact_id: str) -> EvaluationArtifactMetadata | None:
        """Return artifact metadata by artifact_id, or None."""
        ...

    def list_for_run(self, run_id: RunId) -> tuple[EvaluationArtifactMetadata, ...]:
        """Return artifact metadata for run_id in deterministic order."""
        ...
