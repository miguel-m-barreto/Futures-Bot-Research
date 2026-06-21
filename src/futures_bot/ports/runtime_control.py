from __future__ import annotations

from typing import Protocol

from futures_bot.domain.ids import (
    DecisionStackRuntimeId,
    RuntimeManifestId,
)
from futures_bot.domain.runtime_control import (
    DecisionStackCheckpoint,
    DecisionStackRuntimeManifest,
    DecisionStackRuntimeState,
    ExposureSafetyPolicy,
    KillSwitchScopeKind,
    KillSwitchState,
    OpenExposureState,
    OrderFlowPermission,
    ProgramRuntimeState,
    RuntimeControlEvent,
    RuntimeDataHealthSnapshot,
    RuntimeResyncPlan,
    RuntimeWarmupPolicy,
)


class RuntimeControlEventStorePort(Protocol):
    def save(self, event: RuntimeControlEvent) -> None:
        """Persist a runtime control event."""
        ...


class RuntimeManifestStorePort(Protocol):
    def save(self, manifest: DecisionStackRuntimeManifest) -> None:
        """Upsert a runtime manifest by stack runtime id."""
        ...

    def load_by_stack(
        self,
        stack_runtime_id: DecisionStackRuntimeId,
    ) -> DecisionStackRuntimeManifest | None:
        """Return manifest for stack runtime id, or None."""
        ...

    def load(self, manifest_id: RuntimeManifestId) -> DecisionStackRuntimeManifest | None:
        """Return manifest by manifest id, or None."""
        ...


class DecisionStackCheckpointStorePort(Protocol):
    def save(self, checkpoint: DecisionStackCheckpoint) -> None:
        """Upsert a checkpoint by stack runtime id."""
        ...

    def load_latest(
        self,
        stack_runtime_id: DecisionStackRuntimeId,
    ) -> DecisionStackCheckpoint | None:
        """Return latest checkpoint for stack runtime id, or None."""
        ...


class KillSwitchStorePort(Protocol):
    def save(self, kill_switch: KillSwitchState) -> None:
        """Upsert a kill switch."""
        ...

    def list_matching(
        self,
        scope_kind: KillSwitchScopeKind,
        scope_id: str | None = None,
    ) -> tuple[KillSwitchState, ...]:
        """Return enabled matching switches in deterministic order."""
        ...


class RuntimePermissionEvaluatorPort(Protocol):
    def evaluate(  # noqa: PLR0913
        self,
        *,
        program_state: ProgramRuntimeState,
        stack_state: DecisionStackRuntimeState,
        exposure_state: OpenExposureState,
        data_health: RuntimeDataHealthSnapshot,
        kill_switches: tuple[KillSwitchState, ...],
        policy: ExposureSafetyPolicy,
    ) -> OrderFlowPermission:
        """Return current order-flow permission."""
        ...


class RuntimeResyncPlannerPort(Protocol):
    def plan_resync(
        self,
        *,
        manifest: DecisionStackRuntimeManifest,
        warmup_policy: RuntimeWarmupPolicy,
        reason: str,
    ) -> RuntimeResyncPlan:
        """Return a deterministic resync plan contract."""
        ...
