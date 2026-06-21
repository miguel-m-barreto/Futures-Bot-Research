from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.ids import (
    DecisionStackRuntimeId,
    ExposureStateId,
    KillSwitchId,
    ResyncPlanId,
    RuntimeCheckpointId,
    RuntimeControlCommandId,
    RuntimeControlEventId,
    RuntimeDataHealthSnapshotId,
    RuntimeManifestId,
    RuntimeStateTransitionId,
    WarmupPolicyId,
)
from futures_bot.domain.live_state import StreamPosition
from futures_bot.domain.time import ensure_aware_utc


class ProgramRuntimeState(StrEnum):
    BOOTING = "BOOTING"
    RESYNCING_GLOBAL = "RESYNCING_GLOBAL"
    WARMING_UP = "WARMING_UP"
    RUNNING = "RUNNING"
    PAUSING = "PAUSING"
    PAUSED = "PAUSED"
    DRAINING = "DRAINING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"
    EMERGENCY_HALTED = "EMERGENCY_HALTED"


class DecisionStackRuntimeState(StrEnum):
    DISABLED = "DISABLED"
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RESYNCING = "RESYNCING"
    WARMING_UP = "WARMING_UP"
    RUNNING = "RUNNING"
    PAUSING = "PAUSING"
    PAUSED = "PAUSED"
    DRAINING = "DRAINING"
    STOPPING = "STOPPING"
    ERROR = "ERROR"
    RESYNC_REQUIRED = "RESYNC_REQUIRED"
    EXPOSURE_GUARDIAN_ACTIVE = "EXPOSURE_GUARDIAN_ACTIVE"
    STOPPED_BUT_EXPOSURE_GUARDED = "STOPPED_BUT_EXPOSURE_GUARDED"
    MANUAL_INTERVENTION_REQUIRED = "MANUAL_INTERVENTION_REQUIRED"
    EMERGENCY_HALTED = "EMERGENCY_HALTED"


class RuntimeControlCommandKind(StrEnum):
    PAUSE_PROGRAM = "PAUSE_PROGRAM"
    RESUME_PROGRAM = "RESUME_PROGRAM"
    STOP_PROGRAM = "STOP_PROGRAM"
    RESTART_PROGRAM = "RESTART_PROGRAM"
    EMERGENCY_HALT_PROGRAM = "EMERGENCY_HALT_PROGRAM"
    PAUSE_DECISION_STACK = "PAUSE_DECISION_STACK"
    RESUME_DECISION_STACK = "RESUME_DECISION_STACK"
    STOP_DECISION_STACK = "STOP_DECISION_STACK"
    START_DECISION_STACK = "START_DECISION_STACK"
    RESTART_DECISION_STACK = "RESTART_DECISION_STACK"
    DISABLE_DECISION_STACK = "DISABLE_DECISION_STACK"
    ENABLE_DECISION_STACK = "ENABLE_DECISION_STACK"
    EMERGENCY_HALT_DECISION_STACK = "EMERGENCY_HALT_DECISION_STACK"
    PAUSE_ALL_DECISION_STACKS = "PAUSE_ALL_DECISION_STACKS"
    RESUME_ALL_DECISION_STACKS = "RESUME_ALL_DECISION_STACKS"
    STOP_ALL_DECISION_STACKS = "STOP_ALL_DECISION_STACKS"
    DISABLE_ALL_DECISION_STACKS = "DISABLE_ALL_DECISION_STACKS"
    RESYNC_GLOBAL_DATA = "RESYNC_GLOBAL_DATA"
    RESYNC_DECISION_STACK = "RESYNC_DECISION_STACK"
    RESYNC_INSTRUMENT = "RESYNC_INSTRUMENT"
    RESYNC_VENUE = "RESYNC_VENUE"
    RESYNC_ACCOUNT = "RESYNC_ACCOUNT"


class RuntimeControlTargetScope(StrEnum):
    PROGRAM = "PROGRAM"
    DECISION_STACK = "DECISION_STACK"
    ALL_DECISION_STACKS = "ALL_DECISION_STACKS"
    VENUE = "VENUE"
    INSTRUMENT = "INSTRUMENT"
    ACCOUNT = "ACCOUNT"
    GLOBAL = "GLOBAL"


class RuntimeControlEventKind(StrEnum):
    COMMAND_ACCEPTED = "COMMAND_ACCEPTED"
    COMMAND_REJECTED = "COMMAND_REJECTED"
    TRANSITION_APPLIED = "TRANSITION_APPLIED"
    PROTECTION_ACTIVATED = "PROTECTION_ACTIVATED"


class PositionOwnership(StrEnum):
    NONE = "NONE"
    DECISION_STACK_MANAGED = "DECISION_STACK_MANAGED"
    GUARDIAN_MANAGED = "GUARDIAN_MANAGED"
    EXCHANGE_PROTECTION_ONLY = "EXCHANGE_PROTECTION_ONLY"
    MANUAL_INTERVENTION_REQUIRED = "MANUAL_INTERVENTION_REQUIRED"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class ProtectionMode(StrEnum):
    NONE = "NONE"
    MONITOR_ONLY = "MONITOR_ONLY"
    BLOCK_ENTRIES = "BLOCK_ENTRIES"
    GUARDIAN_ACTIVE = "GUARDIAN_ACTIVE"
    REDUCE_ONLY = "REDUCE_ONLY"
    EMERGENCY_CLOSE_REQUIRED = "EMERGENCY_CLOSE_REQUIRED"
    MANUAL_INTERVENTION_REQUIRED = "MANUAL_INTERVENTION_REQUIRED"


class RuntimeDataScopeKind(StrEnum):
    GLOBAL = "GLOBAL"
    VENUE = "VENUE"
    INSTRUMENT = "INSTRUMENT"
    ACCOUNT = "ACCOUNT"
    DECISION_STACK = "DECISION_STACK"


class OrderFlowPermissionReason(StrEnum):
    OK = "OK"
    PROGRAM_NOT_RUNNING = "PROGRAM_NOT_RUNNING"
    STACK_NOT_RUNNING = "STACK_NOT_RUNNING"
    STACK_DISABLED = "STACK_DISABLED"
    STACK_PAUSED = "STACK_PAUSED"
    STACK_RESYNCING = "STACK_RESYNCING"
    STACK_WARMING_UP = "STACK_WARMING_UP"
    GLOBAL_KILL_SWITCH = "GLOBAL_KILL_SWITCH"
    VENUE_KILL_SWITCH = "VENUE_KILL_SWITCH"
    INSTRUMENT_KILL_SWITCH = "INSTRUMENT_KILL_SWITCH"
    ACCOUNT_KILL_SWITCH = "ACCOUNT_KILL_SWITCH"
    LIVE_DATA_GAP = "LIVE_DATA_GAP"
    STALE_DATA = "STALE_DATA"
    OPEN_EXPOSURE_GUARDIAN_REQUIRED = "OPEN_EXPOSURE_GUARDIAN_REQUIRED"
    UNKNOWN_FILLS = "UNKNOWN_FILLS"
    UNRECONCILED_ORDERS = "UNRECONCILED_ORDERS"
    ACCOUNT_STATE_UNKNOWN = "ACCOUNT_STATE_UNKNOWN"
    LEDGER_STATE_UNKNOWN = "LEDGER_STATE_UNKNOWN"
    EMERGENCY_HALTED = "EMERGENCY_HALTED"
    MANUAL_INTERVENTION_REQUIRED = "MANUAL_INTERVENTION_REQUIRED"


class KillSwitchScopeKind(StrEnum):
    GLOBAL = "GLOBAL"
    VENUE = "VENUE"
    INSTRUMENT = "INSTRUMENT"
    ACCOUNT = "ACCOUNT"
    DECISION_STACK = "DECISION_STACK"
    ORDER_SUBMISSION = "ORDER_SUBMISSION"
    EXECUTION = "EXECUTION"


RuntimeStateValue = ProgramRuntimeState | DecisionStackRuntimeState


class RuntimeControlCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    command_id: RuntimeControlCommandId
    command_kind: RuntimeControlCommandKind
    target_scope: RuntimeControlTargetScope
    target_id: str | None = None
    requested_by: str
    reason: str
    issued_at: datetime
    expected_state: RuntimeStateValue | None = None
    command_epoch: int

    @field_validator("requested_by", "reason")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return _trimmed_text(value, "command text")

    @field_validator("target_id")
    @classmethod
    def _validate_target_id(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed_text(value, "target_id")

    @field_validator("issued_at")
    @classmethod
    def _validate_issued_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("command_epoch")
    @classmethod
    def _validate_epoch(cls, value: int) -> int:
        if value < 0:
            raise ValueError("command_epoch must be >= 0")
        return value

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.command_id != deterministic_runtime_control_command_id(
            command_kind=self.command_kind,
            target_scope=self.target_scope,
            target_id=self.target_id,
            requested_by=self.requested_by,
            reason=self.reason,
            issued_at=self.issued_at,
            expected_state=self.expected_state,
            command_epoch=self.command_epoch,
        ):
            raise ValueError("command_id is not deterministic for command fields")
        return self


class RuntimeControlEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: RuntimeControlEventId
    command_id: RuntimeControlCommandId
    event_kind: RuntimeControlEventKind
    target_scope: RuntimeControlTargetScope
    target_id: str | None = None
    emitted_at: datetime
    payload: Any
    payload_hash: str

    @field_validator("target_id")
    @classmethod
    def _validate_target_id(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed_text(value, "target_id")

    @field_validator("emitted_at")
    @classmethod
    def _validate_emitted_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("payload")
    @classmethod
    def _validate_payload(cls, value: Any) -> Any:
        _canonical_json_bytes(value)
        return value

    @field_validator("payload_hash")
    @classmethod
    def _validate_hash(cls, value: str) -> str:
        return _sha256_hex(value, "payload_hash")

    @model_validator(mode="after")
    def _validate_hash_matches(self) -> Self:
        if self.payload_hash != canonical_payload_hash(self.payload):
            raise ValueError("payload_hash does not match payload")
        return self


class RuntimeStateTransition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    transition_id: RuntimeStateTransitionId
    command_id: RuntimeControlCommandId | None = None
    target_scope: RuntimeControlTargetScope
    target_id: str | None = None
    previous_state: RuntimeStateValue
    next_state: RuntimeStateValue
    reason: str
    occurred_at: datetime

    @field_validator("target_id")
    @classmethod
    def _validate_target_id(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed_text(value, "target_id")

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        return _trimmed_text(value, "reason")

    @field_validator("occurred_at")
    @classmethod
    def _validate_occurred_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @model_validator(mode="after")
    def _validate_transition(self) -> Self:
        if type(self.previous_state) is not type(self.next_state):
            raise ValueError("previous_state and next_state must be the same state family")
        if not runtime_transition_allowed(self.previous_state, self.next_state):
            raise ValueError("invalid runtime state transition")
        return self


class OpenExposureState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    exposure_state_id: ExposureStateId
    venue_id: str | None = None
    instrument_id: str | None = None
    account_id: str | None = None
    has_open_position: bool
    has_open_entry_orders: bool
    has_open_exit_orders: bool
    has_unknown_fills: bool
    has_unreconciled_orders: bool
    position_ownership: PositionOwnership
    protection_mode: ProtectionMode
    updated_at: datetime

    @field_validator("venue_id", "instrument_id", "account_id")
    @classmethod
    def _validate_optional_scope_id(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed_text(value, "scope id")

    @field_validator("updated_at")
    @classmethod
    def _validate_updated_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @model_validator(mode="after")
    def _validate_no_orphaned_exposure(self) -> Self:
        has_open_exposure = (
            self.has_open_position
            or self.has_open_entry_orders
            or self.has_open_exit_orders
        )
        if not has_open_exposure:
            if self.position_ownership not in {
                PositionOwnership.NONE,
                PositionOwnership.CLOSED,
            }:
                raise ValueError("closed exposure must have NONE or CLOSED ownership")
            return self
        if self.position_ownership in {
            PositionOwnership.NONE,
            PositionOwnership.CLOSED,
        }:
            raise ValueError("open exposure may never be orphaned")
        return self

    @property
    def requires_entry_block(self) -> bool:
        return self.protection_mode in {
            ProtectionMode.BLOCK_ENTRIES,
            ProtectionMode.GUARDIAN_ACTIVE,
            ProtectionMode.REDUCE_ONLY,
            ProtectionMode.EMERGENCY_CLOSE_REQUIRED,
            ProtectionMode.MANUAL_INTERVENTION_REQUIRED,
        }

    @property
    def requires_guardian(self) -> bool:
        return self.protection_mode in {
            ProtectionMode.GUARDIAN_ACTIVE,
            ProtectionMode.EMERGENCY_CLOSE_REQUIRED,
        }

    @property
    def requires_manual_intervention(self) -> bool:
        return self.protection_mode is ProtectionMode.MANUAL_INTERVENTION_REQUIRED

    @property
    def requires_emergency_close(self) -> bool:
        return self.protection_mode is ProtectionMode.EMERGENCY_CLOSE_REQUIRED


class RuntimeDataHealthSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    data_health_id: RuntimeDataHealthSnapshotId
    scope_kind: RuntimeDataScopeKind
    scope_id: str | None = None
    gap_detected: bool
    stale_data: bool
    stream_unavailable: bool
    account_state_unknown: bool
    orders_state_unknown: bool
    fills_state_unknown: bool
    ledger_state_unknown: bool
    freshness_ms: int | None = None
    updated_at: datetime

    @field_validator("scope_id")
    @classmethod
    def _validate_scope_id(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed_text(value, "scope_id")

    @field_validator("freshness_ms")
    @classmethod
    def _validate_freshness(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("freshness_ms must be >= 0")
        return value

    @field_validator("updated_at")
    @classmethod
    def _validate_updated_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @property
    def has_market_data_problem(self) -> bool:
        return self.gap_detected or self.stale_data or self.stream_unavailable

    @property
    def has_severe_unknown_state(self) -> bool:
        return (
            self.account_state_unknown
            or self.orders_state_unknown
            or self.fills_state_unknown
            or self.ledger_state_unknown
        )


class OrderFlowPermission(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    allow_new_entries: bool
    allow_entry_order_cancel: bool
    allow_exit_orders: bool
    allow_reduce_only_orders: bool
    allow_exit_order_cancel: bool
    allow_emergency_close: bool
    allow_reconciliation: bool
    guardian_required: bool
    manual_intervention_required: bool
    reason: OrderFlowPermissionReason


class ExposureSafetyPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: str
    block_entries_on_any_gap: bool
    allow_reduce_only_during_gap: bool
    allow_emergency_close_during_gap: bool
    allow_cancel_during_gap: bool
    require_guardian_for_open_exposure_gap: bool
    require_manual_intervention_for_unknown_fills: bool
    require_manual_intervention_for_ledger_unknown: bool
    max_allowed_staleness_ms: int

    @field_validator("policy_id")
    @classmethod
    def _validate_policy_id(cls, value: str) -> str:
        return _trimmed_text(value, "policy_id")

    @field_validator("max_allowed_staleness_ms")
    @classmethod
    def _validate_staleness(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("max_allowed_staleness_ms must be > 0")
        return value


class KillSwitchState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kill_switch_id: KillSwitchId
    scope_kind: KillSwitchScopeKind
    scope_id: str | None = None
    enabled: bool
    reason: str
    activated_at: datetime | None = None

    @field_validator("scope_id")
    @classmethod
    def _validate_scope_id(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed_text(value, "scope_id")

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        return _trimmed_text(value, "reason")

    @field_validator("activated_at")
    @classmethod
    def _validate_activated_at(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_aware_utc(value)

    @model_validator(mode="after")
    def _validate_enabled_activation(self) -> Self:
        if self.enabled and self.activated_at is None:
            raise ValueError("enabled kill switch requires activated_at")
        return self

    def applies_to(  # noqa: PLR0911
        self,
        *,
        venue_id: str | None = None,
        instrument_id: str | None = None,
        account_id: str | None = None,
        stack_runtime_id: DecisionStackRuntimeId | None = None,
    ) -> bool:
        if not self.enabled:
            return False
        if self.scope_kind is KillSwitchScopeKind.GLOBAL:
            return True
        if self.scope_kind is KillSwitchScopeKind.VENUE:
            return self.scope_id == venue_id
        if self.scope_kind is KillSwitchScopeKind.INSTRUMENT:
            return self.scope_id == instrument_id
        if self.scope_kind is KillSwitchScopeKind.ACCOUNT:
            return self.scope_id == account_id
        if self.scope_kind is KillSwitchScopeKind.DECISION_STACK:
            return stack_runtime_id is not None and self.scope_id == str(stack_runtime_id)
        return True


class DecisionStackCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    checkpoint_id: RuntimeCheckpointId
    stack_runtime_id: DecisionStackRuntimeId
    stack_state: DecisionStackRuntimeState
    last_market_position: StreamPosition | None = None
    last_evidence_position: StreamPosition | None = None
    last_decision_output_id: str | None = None
    last_decision_output_position: StreamPosition | None = None
    config_hash: str
    model_version: str | None = None
    policy_id: str | None = None
    checkpointed_at: datetime

    @field_validator(
        "last_decision_output_id",
        "config_hash",
        "model_version",
        "policy_id",
    )
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed_text(value, "checkpoint text")

    @field_validator("checkpointed_at")
    @classmethod
    def _validate_checkpointed_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)


class DecisionStackRuntimeManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_id: RuntimeManifestId
    stack_runtime_id: DecisionStackRuntimeId
    desired_state: DecisionStackRuntimeState
    actual_state: DecisionStackRuntimeState
    enabled: bool
    config_hash: str
    model_version: str | None = None
    policy_id: str | None = None
    last_checkpoint_id: RuntimeCheckpointId | None = None
    updated_at: datetime

    @field_validator("config_hash", "model_version", "policy_id")
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed_text(value, "manifest text")

    @field_validator("updated_at")
    @classmethod
    def _validate_updated_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @model_validator(mode="after")
    def _validate_disabled_manifest(self) -> Self:
        if not self.enabled and self.actual_state is not DecisionStackRuntimeState.DISABLED:
            raise ValueError("disabled manifest must have DISABLED actual_state")
        return self

    def allows_auto_start(self) -> bool:
        if not self.enabled:
            return False
        return self.actual_state in {
            DecisionStackRuntimeState.RESYNCING,
            DecisionStackRuntimeState.WARMING_UP,
        }


class RuntimeResyncPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    resync_plan_id: ResyncPlanId
    scope_kind: RuntimeDataScopeKind
    scope_id: str | None = None
    required: bool
    reason: str
    created_at: datetime
    required_steps: tuple[str, ...]

    @field_validator("scope_id")
    @classmethod
    def _validate_scope_id(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed_text(value, "scope_id")

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        return _trimmed_text(value, "reason")

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("required_steps")
    @classmethod
    def _validate_required_steps(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for step in value:
            _trimmed_text(step, "required step")
        return value


class RuntimeWarmupPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    warmup_policy_id: WarmupPolicyId
    min_warmup_ms: int
    require_live_state_fresh: bool
    require_gap_free_state: bool
    require_source_health_ok: bool
    require_fee_snapshot: bool
    require_venue_rules: bool
    require_account_reconciliation: bool

    @field_validator("min_warmup_ms")
    @classmethod
    def _validate_min_warmup(cls, value: int) -> int:
        if value < 0:
            raise ValueError("min_warmup_ms must be >= 0")
        return value


def program_state_may_emit_tradable_decisions(state: ProgramRuntimeState) -> bool:
    return state is ProgramRuntimeState.RUNNING


def stack_state_may_emit_tradable_decisions(state: DecisionStackRuntimeState) -> bool:
    return state is DecisionStackRuntimeState.RUNNING


def program_state_blocks_new_entries(state: ProgramRuntimeState) -> bool:
    return state is not ProgramRuntimeState.RUNNING


def stack_state_blocks_new_entries(state: DecisionStackRuntimeState) -> bool:
    return state is not DecisionStackRuntimeState.RUNNING


def runtime_transition_allowed(
    previous_state: RuntimeStateValue,
    next_state: RuntimeStateValue,
) -> bool:
    if type(previous_state) is not type(next_state):
        return False
    if previous_state == next_state:
        return True
    if isinstance(previous_state, ProgramRuntimeState):
        return _program_transition_allowed(previous_state, next_state)  # type: ignore[arg-type]
    return _stack_transition_allowed(previous_state, next_state)  # type: ignore[arg-type]


def deterministic_runtime_control_command_id(  # noqa: PLR0913
    *,
    command_kind: RuntimeControlCommandKind,
    target_scope: RuntimeControlTargetScope,
    target_id: str | None,
    requested_by: str,
    reason: str,
    issued_at: datetime,
    expected_state: RuntimeStateValue | None,
    command_epoch: int,
) -> RuntimeControlCommandId:
    payload = {
        "command_epoch": command_epoch,
        "command_kind": command_kind.value,
        "expected_state": expected_state.value if expected_state is not None else None,
        "issued_at": ensure_aware_utc(issued_at).isoformat(),
        "reason": reason,
        "requested_by": requested_by,
        "target_id": target_id,
        "target_scope": target_scope.value,
    }
    digest = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
    return RuntimeControlCommandId(value=f"runtime-command:{digest}")


def canonical_payload_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _program_transition_allowed(
    previous_state: ProgramRuntimeState,
    next_state: ProgramRuntimeState,
) -> bool:
    if next_state is ProgramRuntimeState.RUNNING:
        return previous_state is ProgramRuntimeState.WARMING_UP
    if previous_state in {
        ProgramRuntimeState.PAUSED,
        ProgramRuntimeState.STOPPED,
        ProgramRuntimeState.ERROR,
    }:
        return next_state in {
            ProgramRuntimeState.RESYNCING_GLOBAL,
            ProgramRuntimeState.STOPPED,
            ProgramRuntimeState.EMERGENCY_HALTED,
        }
    return True


def _stack_transition_allowed(
    previous_state: DecisionStackRuntimeState,
    next_state: DecisionStackRuntimeState,
) -> bool:
    if previous_state is DecisionStackRuntimeState.DISABLED:
        return next_state is DecisionStackRuntimeState.DISABLED
    if next_state is DecisionStackRuntimeState.RUNNING:
        return previous_state is DecisionStackRuntimeState.WARMING_UP
    if previous_state in {
        DecisionStackRuntimeState.PAUSED,
        DecisionStackRuntimeState.STOPPED,
        DecisionStackRuntimeState.RESYNC_REQUIRED,
        DecisionStackRuntimeState.ERROR,
    }:
        return next_state in {
            DecisionStackRuntimeState.RESYNCING,
            DecisionStackRuntimeState.STOPPED_BUT_EXPOSURE_GUARDED,
            DecisionStackRuntimeState.MANUAL_INTERVENTION_REQUIRED,
            DecisionStackRuntimeState.EMERGENCY_HALTED,
        }
    return True


def _trimmed_text(value: str, name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty and trimmed")
    return value


def _sha256_hex(value: str, name: str) -> str:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lowercase sha256 hex")
    return value


def _canonical_json_bytes(payload: Any) -> bytes:
    _validate_json_compatible(payload, path="payload")
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _validate_json_compatible(value: Any, *, path: str) -> None:
    if value is None or isinstance(value, str | bool | int):
        return
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f"{path} float must be finite")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} object keys must be strings")
            _validate_json_compatible(item, path=f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, item in enumerate(value):
            _validate_json_compatible(item, path=f"{path}[{index}]")
        return
    raise ValueError(f"{path} must be JSON-compatible")
