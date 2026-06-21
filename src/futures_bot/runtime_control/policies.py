from __future__ import annotations

from futures_bot.domain.ids import DecisionStackRuntimeId
from futures_bot.domain.runtime_control import (
    DecisionStackRuntimeState,
    ExposureSafetyPolicy,
    KillSwitchScopeKind,
    KillSwitchState,
    OpenExposureState,
    OrderFlowPermission,
    OrderFlowPermissionReason,
    ProgramRuntimeState,
    ProtectionMode,
    RuntimeDataHealthSnapshot,
    RuntimeWarmupPolicy,
)


def evaluate_order_flow_permission(  # noqa: PLR0913
    *,
    program_state: ProgramRuntimeState,
    stack_state: DecisionStackRuntimeState,
    exposure_state: OpenExposureState,
    data_health: RuntimeDataHealthSnapshot,
    kill_switches: tuple[KillSwitchState, ...],
    policy: ExposureSafetyPolicy,
    stack_runtime_id: DecisionStackRuntimeId | None = None,
) -> OrderFlowPermission:
    has_open_exposure = _has_open_exposure(exposure_state)
    reason = _blocking_reason(
        program_state=program_state,
        stack_state=stack_state,
        exposure_state=exposure_state,
        data_health=data_health,
        kill_switches=kill_switches,
        policy=policy,
        stack_runtime_id=stack_runtime_id,
    )
    blocked = reason is not OrderFlowPermissionReason.OK
    gap_or_unavailable = data_health.gap_detected or data_health.stream_unavailable
    degraded = (
        gap_or_unavailable
        or data_health.stale_data
        or data_health.has_severe_unknown_state
        or _staleness_exceeds_policy(data_health, policy)
    )
    halted = program_state is ProgramRuntimeState.EMERGENCY_HALTED or (
        stack_state is DecisionStackRuntimeState.EMERGENCY_HALTED
    )
    guardian_required = (
        has_open_exposure
        and gap_or_unavailable
        and policy.require_guardian_for_open_exposure_gap
    ) or (
        has_open_exposure and exposure_state.requires_guardian
    )
    manual_required = (
        reason is OrderFlowPermissionReason.MANUAL_INTERVENTION_REQUIRED
        or exposure_state.requires_manual_intervention
    )

    allow_protection = has_open_exposure and (
        not degraded
        or policy.allow_reduce_only_during_gap
        or program_state
        in {
            ProgramRuntimeState.PAUSING,
            ProgramRuntimeState.PAUSED,
            ProgramRuntimeState.DRAINING,
            ProgramRuntimeState.STOPPING,
            ProgramRuntimeState.ERROR,
            ProgramRuntimeState.EMERGENCY_HALTED,
        }
        or stack_state
        in {
            DecisionStackRuntimeState.PAUSING,
            DecisionStackRuntimeState.PAUSED,
            DecisionStackRuntimeState.DRAINING,
            DecisionStackRuntimeState.STOPPING,
            DecisionStackRuntimeState.ERROR,
            DecisionStackRuntimeState.EXPOSURE_GUARDIAN_ACTIVE,
            DecisionStackRuntimeState.STOPPED_BUT_EXPOSURE_GUARDED,
            DecisionStackRuntimeState.EMERGENCY_HALTED,
        }
    )
    if exposure_state.protection_mode in {
        ProtectionMode.BLOCK_ENTRIES,
        ProtectionMode.GUARDIAN_ACTIVE,
        ProtectionMode.REDUCE_ONLY,
        ProtectionMode.EMERGENCY_CLOSE_REQUIRED,
    }:
        allow_protection = has_open_exposure
    if exposure_state.requires_manual_intervention and not degraded:
        allow_protection = False
    allow_cancel = has_open_exposure and (not degraded or policy.allow_cancel_during_gap)
    if exposure_state.protection_mode in {
        ProtectionMode.BLOCK_ENTRIES,
        ProtectionMode.GUARDIAN_ACTIVE,
        ProtectionMode.REDUCE_ONLY,
        ProtectionMode.EMERGENCY_CLOSE_REQUIRED,
    }:
        allow_cancel = has_open_exposure
    lifecycle_emergency_close = (
        program_state is ProgramRuntimeState.STOPPING
        or stack_state is DecisionStackRuntimeState.STOPPING
    )
    allow_emergency_close = has_open_exposure and (
        exposure_state.requires_emergency_close
        or
        lifecycle_emergency_close
        or (policy.allow_emergency_close_during_gap and (halted or degraded))
    )

    return OrderFlowPermission(
        allow_new_entries=not blocked,
        allow_entry_order_cancel=allow_cancel,
        allow_exit_orders=allow_protection,
        allow_reduce_only_orders=allow_protection,
        allow_exit_order_cancel=allow_cancel,
        allow_emergency_close=allow_emergency_close,
        allow_reconciliation=blocked or degraded or manual_required,
        guardian_required=guardian_required,
        manual_intervention_required=manual_required,
        reason=reason,
    )


def can_enter_running_after_warmup(  # noqa: PLR0911, PLR0913
    *,
    policy: RuntimeWarmupPolicy,
    elapsed_warmup_ms: int,
    live_state_fresh: bool,
    gap_free_state: bool,
    source_health_ok: bool,
    fee_snapshot_ready: bool,
    venue_rules_ready: bool,
    account_reconciled: bool,
) -> bool:
    if elapsed_warmup_ms < 0:
        raise ValueError("elapsed_warmup_ms must be >= 0")
    if elapsed_warmup_ms < policy.min_warmup_ms:
        return False
    if policy.require_live_state_fresh and not live_state_fresh:
        return False
    if policy.require_gap_free_state and not gap_free_state:
        return False
    if policy.require_source_health_ok and not source_health_ok:
        return False
    if policy.require_fee_snapshot and not fee_snapshot_ready:
        return False
    if policy.require_venue_rules and not venue_rules_ready:
        return False
    return not (
        policy.require_account_reconciliation and not account_reconciled
    )


def _blocking_reason(  # noqa: PLR0911, PLR0912, PLR0913
    *,
    program_state: ProgramRuntimeState,
    stack_state: DecisionStackRuntimeState,
    exposure_state: OpenExposureState,
    data_health: RuntimeDataHealthSnapshot,
    kill_switches: tuple[KillSwitchState, ...],
    policy: ExposureSafetyPolicy,
    stack_runtime_id: DecisionStackRuntimeId | None,
) -> OrderFlowPermissionReason:
    kill_switch_reason = _kill_switch_reason(
        exposure_state,
        kill_switches,
        stack_runtime_id,
    )
    if kill_switch_reason is not None:
        return kill_switch_reason
    if program_state is ProgramRuntimeState.EMERGENCY_HALTED:
        return OrderFlowPermissionReason.EMERGENCY_HALTED
    if stack_state is DecisionStackRuntimeState.EMERGENCY_HALTED:
        return OrderFlowPermissionReason.EMERGENCY_HALTED
    if program_state is not ProgramRuntimeState.RUNNING:
        return OrderFlowPermissionReason.PROGRAM_NOT_RUNNING
    stack_reason = _stack_state_reason(stack_state)
    if stack_reason is not None:
        return stack_reason
    protection_reason = _protection_mode_reason(exposure_state)
    if protection_reason is not None:
        return protection_reason
    if exposure_state.has_unknown_fills:
        if policy.require_manual_intervention_for_unknown_fills:
            return OrderFlowPermissionReason.MANUAL_INTERVENTION_REQUIRED
        return OrderFlowPermissionReason.UNKNOWN_FILLS
    if exposure_state.has_unreconciled_orders:
        return OrderFlowPermissionReason.UNRECONCILED_ORDERS
    if data_health.account_state_unknown:
        return OrderFlowPermissionReason.ACCOUNT_STATE_UNKNOWN
    if data_health.ledger_state_unknown:
        if policy.require_manual_intervention_for_ledger_unknown:
            return OrderFlowPermissionReason.MANUAL_INTERVENTION_REQUIRED
        return OrderFlowPermissionReason.LEDGER_STATE_UNKNOWN
    if data_health.fills_state_unknown:
        return OrderFlowPermissionReason.UNKNOWN_FILLS
    if data_health.orders_state_unknown:
        return OrderFlowPermissionReason.UNRECONCILED_ORDERS
    if _staleness_exceeds_policy(data_health, policy):
        return OrderFlowPermissionReason.STALE_DATA
    if (
        policy.block_entries_on_any_gap
        and (data_health.gap_detected or data_health.stream_unavailable)
    ):
        if _has_open_exposure(exposure_state):
            return OrderFlowPermissionReason.OPEN_EXPOSURE_GUARDIAN_REQUIRED
        return OrderFlowPermissionReason.LIVE_DATA_GAP
    if data_health.stale_data:
        return OrderFlowPermissionReason.STALE_DATA
    return OrderFlowPermissionReason.OK


def _protection_mode_reason(
    exposure_state: OpenExposureState,
) -> OrderFlowPermissionReason | None:
    if exposure_state.requires_manual_intervention:
        return OrderFlowPermissionReason.MANUAL_INTERVENTION_REQUIRED
    if exposure_state.requires_entry_block:
        return OrderFlowPermissionReason.OPEN_EXPOSURE_GUARDIAN_REQUIRED
    return None


def _stack_state_reason(
    stack_state: DecisionStackRuntimeState,
) -> OrderFlowPermissionReason | None:
    if stack_state is DecisionStackRuntimeState.RUNNING:
        return None
    if stack_state is DecisionStackRuntimeState.DISABLED:
        return OrderFlowPermissionReason.STACK_DISABLED
    if stack_state in {
        DecisionStackRuntimeState.PAUSING,
        DecisionStackRuntimeState.PAUSED,
        DecisionStackRuntimeState.DRAINING,
    }:
        return OrderFlowPermissionReason.STACK_PAUSED
    if stack_state in {
        DecisionStackRuntimeState.RESYNCING,
        DecisionStackRuntimeState.RESYNC_REQUIRED,
        DecisionStackRuntimeState.STARTING,
    }:
        return OrderFlowPermissionReason.STACK_RESYNCING
    if stack_state is DecisionStackRuntimeState.WARMING_UP:
        return OrderFlowPermissionReason.STACK_WARMING_UP
    return OrderFlowPermissionReason.STACK_NOT_RUNNING


def _kill_switch_reason(
    exposure_state: OpenExposureState,
    kill_switches: tuple[KillSwitchState, ...],
    stack_runtime_id: DecisionStackRuntimeId | None,
) -> OrderFlowPermissionReason | None:
    for kill_switch in kill_switches:
        if not kill_switch.applies_to(
            venue_id=exposure_state.venue_id,
            instrument_id=exposure_state.instrument_id,
            account_id=exposure_state.account_id,
            stack_runtime_id=stack_runtime_id,
        ):
            continue
        if kill_switch.scope_kind is KillSwitchScopeKind.GLOBAL:
            return OrderFlowPermissionReason.GLOBAL_KILL_SWITCH
        if kill_switch.scope_kind is KillSwitchScopeKind.VENUE:
            return OrderFlowPermissionReason.VENUE_KILL_SWITCH
        if kill_switch.scope_kind is KillSwitchScopeKind.INSTRUMENT:
            return OrderFlowPermissionReason.INSTRUMENT_KILL_SWITCH
        if kill_switch.scope_kind is KillSwitchScopeKind.ACCOUNT:
            return OrderFlowPermissionReason.ACCOUNT_KILL_SWITCH
        return OrderFlowPermissionReason.GLOBAL_KILL_SWITCH
    return None


def _has_open_exposure(exposure_state: OpenExposureState) -> bool:
    return (
        exposure_state.has_open_position
        or exposure_state.has_open_entry_orders
        or exposure_state.has_open_exit_orders
    )


def _staleness_exceeds_policy(
    data_health: RuntimeDataHealthSnapshot,
    policy: ExposureSafetyPolicy,
) -> bool:
    return (
        data_health.freshness_ms is not None
        and data_health.freshness_ms > policy.max_allowed_staleness_ms
    )
