from __future__ import annotations

from futures_bot.domain.ids import (
    DecisionStackRuntimeId,
    RuntimeControlEventId,
    RuntimeManifestId,
)
from futures_bot.domain.runtime_control import (
    DecisionStackCheckpoint,
    DecisionStackRuntimeManifest,
    KillSwitchScopeKind,
    KillSwitchState,
    RuntimeControlEvent,
)


class InMemoryRuntimeControlEventStore:
    def __init__(self) -> None:
        self._events: dict[str, RuntimeControlEvent] = {}

    def save(self, event: RuntimeControlEvent) -> None:
        key = str(event.event_id)
        existing = self._events.get(key)
        if existing is not None:
            if existing.payload_hash != event.payload_hash or existing != event:
                raise ValueError("runtime control event id conflict")
            return
        self._events[key] = event

    def load(self, event_id: RuntimeControlEventId) -> RuntimeControlEvent | None:
        return self._events.get(str(event_id))

    def list_all(self) -> tuple[RuntimeControlEvent, ...]:
        return tuple(
            sorted(
                self._events.values(),
                key=lambda event: (event.emitted_at, str(event.event_id)),
            )
        )


class InMemoryRuntimeManifestStore:
    def __init__(self) -> None:
        self._by_manifest_id: dict[str, DecisionStackRuntimeManifest] = {}
        self._by_stack_id: dict[str, DecisionStackRuntimeManifest] = {}

    def save(self, manifest: DecisionStackRuntimeManifest) -> None:
        manifest_key = str(manifest.manifest_id)
        stack_key = str(manifest.stack_runtime_id)
        existing_by_manifest = self._by_manifest_id.get(manifest_key)
        if (
            existing_by_manifest is not None
            and existing_by_manifest.stack_runtime_id != manifest.stack_runtime_id
        ):
            raise ValueError("runtime manifest id conflict")
        self._by_manifest_id[manifest_key] = manifest
        self._by_stack_id[stack_key] = manifest

    def load_by_stack(
        self,
        stack_runtime_id: DecisionStackRuntimeId,
    ) -> DecisionStackRuntimeManifest | None:
        return self._by_stack_id.get(str(stack_runtime_id))

    def load(self, manifest_id: RuntimeManifestId) -> DecisionStackRuntimeManifest | None:
        return self._by_manifest_id.get(str(manifest_id))


class InMemoryDecisionStackCheckpointStore:
    def __init__(self) -> None:
        self._by_stack_id: dict[str, DecisionStackCheckpoint] = {}

    def save(self, checkpoint: DecisionStackCheckpoint) -> None:
        self._by_stack_id[str(checkpoint.stack_runtime_id)] = checkpoint

    def load_latest(
        self,
        stack_runtime_id: DecisionStackRuntimeId,
    ) -> DecisionStackCheckpoint | None:
        return self._by_stack_id.get(str(stack_runtime_id))


class InMemoryKillSwitchStore:
    def __init__(self) -> None:
        self._switches: dict[str, KillSwitchState] = {}

    def save(self, kill_switch: KillSwitchState) -> None:
        self._switches[str(kill_switch.kill_switch_id)] = kill_switch

    def list_matching(
        self,
        scope_kind: KillSwitchScopeKind,
        scope_id: str | None = None,
    ) -> tuple[KillSwitchState, ...]:
        matches = []
        for kill_switch in self._switches.values():
            if not kill_switch.enabled:
                continue
            if kill_switch.scope_kind is KillSwitchScopeKind.GLOBAL:
                matches.append(kill_switch)
                continue
            if kill_switch.scope_kind is scope_kind and kill_switch.scope_id == scope_id:
                matches.append(kill_switch)
        return tuple(
            sorted(
                matches,
                key=lambda switch: (
                    switch.activated_at,
                    switch.scope_kind.value,
                    switch.scope_id or "",
                    str(switch.kill_switch_id),
                ),
            )
        )
