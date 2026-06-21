from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.ids import (
    DecisionStackRuntimeId,
    ExposureStateId,
    RuntimeDataHealthSnapshotId,
    RuntimeManifestId,
    RuntimeStateTransitionId,
    WarmupPolicyId,
)
from futures_bot.domain.runtime_control import (
    DecisionStackRuntimeManifest,
    DecisionStackRuntimeState,
    ExposureSafetyPolicy,
    OpenExposureState,
    PositionOwnership,
    ProgramRuntimeState,
    ProtectionMode,
    RuntimeControlTargetScope,
    RuntimeDataHealthSnapshot,
    RuntimeDataScopeKind,
    RuntimeStateTransition,
    RuntimeWarmupPolicy,
)
from futures_bot.runtime_control.policies import (
    can_enter_running_after_warmup,
    evaluate_order_flow_permission,
)

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def _warmup_policy() -> RuntimeWarmupPolicy:
    return RuntimeWarmupPolicy(
        warmup_policy_id=WarmupPolicyId("warmup-1"),
        min_warmup_ms=100,
        require_live_state_fresh=True,
        require_gap_free_state=True,
        require_source_health_ok=True,
        require_fee_snapshot=True,
        require_venue_rules=True,
        require_account_reconciliation=True,
    )


def _safety_policy(allow_emergency_close_during_gap: bool) -> ExposureSafetyPolicy:
    return ExposureSafetyPolicy(
        policy_id="safety",
        block_entries_on_any_gap=True,
        allow_reduce_only_during_gap=True,
        allow_emergency_close_during_gap=allow_emergency_close_during_gap,
        allow_cancel_during_gap=True,
        require_guardian_for_open_exposure_gap=True,
        require_manual_intervention_for_unknown_fills=True,
        require_manual_intervention_for_ledger_unknown=True,
        max_allowed_staleness_ms=100,
    )


def _open_exposure(
    protection_mode: ProtectionMode = ProtectionMode.GUARDIAN_ACTIVE,
) -> OpenExposureState:
    return OpenExposureState(
        exposure_state_id=ExposureStateId("exposure-open"),
        has_open_position=True,
        has_open_entry_orders=False,
        has_open_exit_orders=False,
        has_unknown_fills=False,
        has_unreconciled_orders=False,
        position_ownership=PositionOwnership.GUARDIAN_MANAGED,
        protection_mode=protection_mode,
        updated_at=BASE_TIME,
    )


def _healthy_data() -> RuntimeDataHealthSnapshot:
    return RuntimeDataHealthSnapshot(
        data_health_id=RuntimeDataHealthSnapshotId("health-1"),
        scope_kind=RuntimeDataScopeKind.GLOBAL,
        gap_detected=False,
        stale_data=False,
        stream_unavailable=False,
        account_state_unknown=False,
        orders_state_unknown=False,
        fills_state_unknown=False,
        ledger_state_unknown=False,
        freshness_ms=10,
        updated_at=BASE_TIME,
    )


def test_resume_cannot_go_paused_to_running_directly() -> None:
    with pytest.raises(ValidationError, match="invalid runtime state transition"):
        RuntimeStateTransition(
            transition_id=RuntimeStateTransitionId("transition-paused-running"),
            target_scope=RuntimeControlTargetScope.DECISION_STACK,
            previous_state=DecisionStackRuntimeState.PAUSED,
            next_state=DecisionStackRuntimeState.RUNNING,
            reason="resume requested",
            occurred_at=BASE_TIME,
        )


def test_restart_requires_resyncing_then_warming_up_before_running() -> None:
    with pytest.raises(ValidationError, match="invalid runtime state transition"):
        RuntimeStateTransition(
            transition_id=RuntimeStateTransitionId("transition-stopped-running"),
            target_scope=RuntimeControlTargetScope.DECISION_STACK,
            previous_state=DecisionStackRuntimeState.STOPPED,
            next_state=DecisionStackRuntimeState.RUNNING,
            reason="restart requested",
            occurred_at=BASE_TIME,
        )
    RuntimeStateTransition(
        transition_id=RuntimeStateTransitionId("transition-stopped-resync"),
        target_scope=RuntimeControlTargetScope.DECISION_STACK,
        previous_state=DecisionStackRuntimeState.STOPPED,
        next_state=DecisionStackRuntimeState.RESYNCING,
        reason="restart requested",
        occurred_at=BASE_TIME,
    )
    RuntimeStateTransition(
        transition_id=RuntimeStateTransitionId("transition-warm-running"),
        target_scope=RuntimeControlTargetScope.DECISION_STACK,
        previous_state=DecisionStackRuntimeState.WARMING_UP,
        next_state=DecisionStackRuntimeState.RUNNING,
        reason="warmup complete",
        occurred_at=BASE_TIME,
    )


def test_disabled_stack_does_not_auto_start_after_program_restart() -> None:
    manifest = DecisionStackRuntimeManifest(
        manifest_id=RuntimeManifestId("manifest-disabled"),
        stack_runtime_id=DecisionStackRuntimeId("stack-1"),
        desired_state=DecisionStackRuntimeState.RUNNING,
        actual_state=DecisionStackRuntimeState.DISABLED,
        enabled=False,
        config_hash="cfg",
        updated_at=BASE_TIME,
    )
    assert not manifest.allows_auto_start()


def test_stop_with_open_exposure_uses_guarded_state() -> None:
    exposure = _open_exposure()
    transition = RuntimeStateTransition(
        transition_id=RuntimeStateTransitionId("transition-guarded"),
        target_scope=RuntimeControlTargetScope.DECISION_STACK,
        previous_state=DecisionStackRuntimeState.STOPPING,
        next_state=DecisionStackRuntimeState.STOPPED_BUT_EXPOSURE_GUARDED,
        reason="open exposure guarded",
        occurred_at=BASE_TIME,
    )
    assert exposure.position_ownership is PositionOwnership.GUARDIAN_MANAGED
    assert transition.next_state is DecisionStackRuntimeState.STOPPED_BUT_EXPOSURE_GUARDED


def test_emergency_halted_open_exposure_respects_emergency_close_policy() -> None:
    denied = evaluate_order_flow_permission(
        program_state=ProgramRuntimeState.EMERGENCY_HALTED,
        stack_state=DecisionStackRuntimeState.RUNNING,
        exposure_state=_open_exposure(),
        data_health=_healthy_data(),
        kill_switches=(),
        policy=_safety_policy(allow_emergency_close_during_gap=False),
    )
    allowed = evaluate_order_flow_permission(
        program_state=ProgramRuntimeState.EMERGENCY_HALTED,
        stack_state=DecisionStackRuntimeState.RUNNING,
        exposure_state=_open_exposure(),
        data_health=_healthy_data(),
        kill_switches=(),
        policy=_safety_policy(allow_emergency_close_during_gap=True),
    )
    assert not denied.allow_new_entries
    assert not denied.allow_emergency_close
    assert allowed.allow_emergency_close


def test_halted_policy_false_stays_false_without_emergency_close_required_mode() -> None:
    permission = evaluate_order_flow_permission(
        program_state=ProgramRuntimeState.EMERGENCY_HALTED,
        stack_state=DecisionStackRuntimeState.RUNNING,
        exposure_state=_open_exposure(ProtectionMode.MONITOR_ONLY),
        data_health=_healthy_data(),
        kill_switches=(),
        policy=_safety_policy(allow_emergency_close_during_gap=False),
    )
    assert not permission.allow_new_entries
    assert not permission.allow_emergency_close


def test_warmup_policy_blocks_direct_running_until_requirements_pass() -> None:
    policy = _warmup_policy()
    assert not can_enter_running_after_warmup(
        policy=policy,
        elapsed_warmup_ms=99,
        live_state_fresh=True,
        gap_free_state=True,
        source_health_ok=True,
        fee_snapshot_ready=True,
        venue_rules_ready=True,
        account_reconciled=True,
    )
    assert not can_enter_running_after_warmup(
        policy=policy,
        elapsed_warmup_ms=100,
        live_state_fresh=False,
        gap_free_state=True,
        source_health_ok=True,
        fee_snapshot_ready=True,
        venue_rules_ready=True,
        account_reconciled=True,
    )
    assert can_enter_running_after_warmup(
        policy=policy,
        elapsed_warmup_ms=100,
        live_state_fresh=True,
        gap_free_state=True,
        source_health_ok=True,
        fee_snapshot_ready=True,
        venue_rules_ready=True,
        account_reconciled=True,
    )
