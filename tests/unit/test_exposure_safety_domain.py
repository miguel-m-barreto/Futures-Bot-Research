from __future__ import annotations

from datetime import UTC, datetime

from futures_bot.domain.ids import (
    ExposureStateId,
    KillSwitchId,
    RuntimeDataHealthSnapshotId,
)
from futures_bot.domain.runtime_control import (
    DecisionStackRuntimeState,
    ExposureSafetyPolicy,
    KillSwitchScopeKind,
    KillSwitchState,
    OpenExposureState,
    OrderFlowPermissionReason,
    PositionOwnership,
    ProgramRuntimeState,
    ProtectionMode,
    RuntimeDataHealthSnapshot,
    RuntimeDataScopeKind,
)
from futures_bot.runtime_control.policies import evaluate_order_flow_permission

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def _policy(
    *,
    allow_emergency_close_during_gap: bool = True,
) -> ExposureSafetyPolicy:
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


def _exposure(
    *,
    open_position: bool = False,
    protection_mode: ProtectionMode | None = None,
) -> OpenExposureState:
    return OpenExposureState(
        exposure_state_id=ExposureStateId("exposure-1"),
        venue_id="BINANCE",
        instrument_id="BTC/USDT",
        account_id="acct-1",
        has_open_position=open_position,
        has_open_entry_orders=False,
        has_open_exit_orders=False,
        has_unknown_fills=False,
        has_unreconciled_orders=False,
        position_ownership=(
            PositionOwnership.DECISION_STACK_MANAGED
            if open_position
            else PositionOwnership.NONE
        ),
        protection_mode=protection_mode or (
            ProtectionMode.MONITOR_ONLY if open_position else ProtectionMode.NONE
        ),
        updated_at=BASE_TIME,
    )


def _health(**overrides: object) -> RuntimeDataHealthSnapshot:
    values = {
        "data_health_id": RuntimeDataHealthSnapshotId("health-1"),
        "scope_kind": RuntimeDataScopeKind.INSTRUMENT,
        "scope_id": "BTC/USDT",
        "gap_detected": False,
        "stale_data": False,
        "stream_unavailable": False,
        "account_state_unknown": False,
        "orders_state_unknown": False,
        "fills_state_unknown": False,
        "ledger_state_unknown": False,
        "freshness_ms": 10,
        "updated_at": BASE_TIME,
    }
    values.update(overrides)
    return RuntimeDataHealthSnapshot(**values)


def _permission(  # noqa: PLR0913
    *,
    program_state: ProgramRuntimeState = ProgramRuntimeState.RUNNING,
    stack_state: DecisionStackRuntimeState = DecisionStackRuntimeState.RUNNING,
    exposure: OpenExposureState | None = None,
    health: RuntimeDataHealthSnapshot | None = None,
    switches: tuple[KillSwitchState, ...] = (),
    policy: ExposureSafetyPolicy | None = None,
):
    return evaluate_order_flow_permission(
        program_state=program_state,
        stack_state=stack_state,
        exposure_state=exposure or _exposure(),
        data_health=health or _health(),
        kill_switches=switches,
        policy=policy or _policy(),
    )


def _kill(
    scope_kind: KillSwitchScopeKind,
    scope_id: str | None = None,
) -> KillSwitchState:
    return KillSwitchState(
        kill_switch_id=KillSwitchId(f"kill-{scope_kind.value}-{scope_id or 'all'}"),
        scope_kind=scope_kind,
        scope_id=scope_id,
        enabled=True,
        reason="test",
        activated_at=BASE_TIME,
    )


def test_running_healthy_no_exposure_allows_entries() -> None:
    permission = _permission()
    assert permission.allow_new_entries
    assert permission.reason is OrderFlowPermissionReason.OK


def test_none_mode_does_not_block_entries_when_otherwise_healthy() -> None:
    permission = _permission(
        exposure=_exposure(protection_mode=ProtectionMode.NONE),
    )
    assert permission.allow_new_entries
    assert permission.reason is OrderFlowPermissionReason.OK


def test_monitor_only_mode_does_not_block_entries_when_otherwise_healthy() -> None:
    permission = _permission(
        exposure=_exposure(protection_mode=ProtectionMode.MONITOR_ONLY),
    )
    assert permission.allow_new_entries
    assert permission.reason is OrderFlowPermissionReason.OK


def test_market_gap_no_exposure_blocks_entries() -> None:
    permission = _permission(health=_health(gap_detected=True))
    assert not permission.allow_new_entries
    assert not permission.allow_exit_orders
    assert permission.allow_reconciliation
    assert permission.reason is OrderFlowPermissionReason.LIVE_DATA_GAP


def test_market_gap_open_exposure_activates_guardian_and_reduce_only() -> None:
    permission = _permission(
        exposure=_exposure(open_position=True),
        health=_health(gap_detected=True),
    )
    assert not permission.allow_new_entries
    assert permission.guardian_required
    assert permission.allow_reduce_only_orders
    assert permission.allow_emergency_close
    assert permission.reason is OrderFlowPermissionReason.OPEN_EXPOSURE_GUARDIAN_REQUIRED


def test_open_exposure_gap_respects_emergency_close_policy_when_false() -> None:
    permission = _permission(
        exposure=_exposure(open_position=True),
        health=_health(gap_detected=True),
        policy=_policy(allow_emergency_close_during_gap=False),
    )
    assert not permission.allow_new_entries
    assert permission.guardian_required
    assert not permission.allow_emergency_close
    assert permission.reason is OrderFlowPermissionReason.OPEN_EXPOSURE_GUARDIAN_REQUIRED


def test_gap_policy_false_stays_false_without_emergency_close_required_mode() -> None:
    permission = _permission(
        exposure=_exposure(
            open_position=True,
            protection_mode=ProtectionMode.MONITOR_ONLY,
        ),
        health=_health(gap_detected=True),
        policy=_policy(allow_emergency_close_during_gap=False),
    )
    assert not permission.allow_new_entries
    assert not permission.allow_emergency_close
    assert permission.reason is OrderFlowPermissionReason.OPEN_EXPOSURE_GUARDIAN_REQUIRED


def test_open_exposure_gap_allows_emergency_close_when_policy_true() -> None:
    permission = _permission(
        exposure=_exposure(open_position=True),
        health=_health(gap_detected=True),
        policy=_policy(allow_emergency_close_during_gap=True),
    )
    assert not permission.allow_new_entries
    assert permission.allow_emergency_close
    assert permission.reason is OrderFlowPermissionReason.OPEN_EXPOSURE_GUARDIAN_REQUIRED


def test_stale_data_open_exposure_respects_emergency_close_policy() -> None:
    denied = _permission(
        exposure=_exposure(open_position=True),
        health=_health(stale_data=True),
        policy=_policy(allow_emergency_close_during_gap=False),
    )
    allowed = _permission(
        exposure=_exposure(open_position=True),
        health=_health(stale_data=True),
        policy=_policy(allow_emergency_close_during_gap=True),
    )
    assert not denied.allow_new_entries
    assert not denied.allow_emergency_close
    assert denied.reason is OrderFlowPermissionReason.STALE_DATA
    assert allowed.allow_emergency_close


def test_block_entries_protection_mode_blocks_new_entries_when_healthy() -> None:
    permission = _permission(
        exposure=_exposure(
            open_position=True,
            protection_mode=ProtectionMode.BLOCK_ENTRIES,
        )
    )
    assert not permission.allow_new_entries
    assert permission.allow_exit_orders
    assert permission.allow_reduce_only_orders
    assert permission.allow_entry_order_cancel
    assert permission.allow_exit_order_cancel
    assert not permission.guardian_required
    assert permission.reason is OrderFlowPermissionReason.OPEN_EXPOSURE_GUARDIAN_REQUIRED


def test_guardian_active_protection_mode_blocks_entries_and_requires_guardian() -> None:
    permission = _permission(
        exposure=_exposure(
            open_position=True,
            protection_mode=ProtectionMode.GUARDIAN_ACTIVE,
        )
    )
    assert not permission.allow_new_entries
    assert permission.guardian_required
    assert permission.allow_exit_orders
    assert permission.allow_reduce_only_orders
    assert permission.allow_entry_order_cancel
    assert permission.allow_exit_order_cancel
    assert permission.reason is OrderFlowPermissionReason.OPEN_EXPOSURE_GUARDIAN_REQUIRED


def test_reduce_only_protection_mode_blocks_entries_and_allows_reduce_only() -> None:
    permission = _permission(
        exposure=_exposure(
            open_position=True,
            protection_mode=ProtectionMode.REDUCE_ONLY,
        )
    )
    assert not permission.allow_new_entries
    assert permission.allow_exit_orders
    assert permission.allow_reduce_only_orders
    assert permission.allow_entry_order_cancel
    assert permission.allow_exit_order_cancel
    assert permission.reason is OrderFlowPermissionReason.OPEN_EXPOSURE_GUARDIAN_REQUIRED


def test_emergency_close_required_mode_allows_emergency_close_when_healthy() -> None:
    permission = _permission(
        exposure=_exposure(
            open_position=True,
            protection_mode=ProtectionMode.EMERGENCY_CLOSE_REQUIRED,
        ),
        policy=_policy(allow_emergency_close_during_gap=False),
    )
    assert not permission.allow_new_entries
    assert permission.guardian_required
    assert permission.allow_exit_orders
    assert permission.allow_reduce_only_orders
    assert permission.allow_emergency_close
    assert permission.reason is OrderFlowPermissionReason.OPEN_EXPOSURE_GUARDIAN_REQUIRED


def test_manual_intervention_mode_blocks_entries_and_requires_manual_intervention() -> None:
    permission = _permission(
        exposure=_exposure(
            open_position=True,
            protection_mode=ProtectionMode.MANUAL_INTERVENTION_REQUIRED,
        )
    )
    assert not permission.allow_new_entries
    assert permission.manual_intervention_required
    assert permission.allow_reconciliation
    assert not permission.allow_emergency_close
    assert permission.reason is OrderFlowPermissionReason.MANUAL_INTERVENTION_REQUIRED


def test_paused_stack_with_open_exposure_keeps_protection_paths() -> None:
    permission = _permission(
        stack_state=DecisionStackRuntimeState.PAUSED,
        exposure=_exposure(open_position=True),
    )
    assert not permission.allow_new_entries
    assert permission.allow_exit_orders
    assert permission.allow_exit_order_cancel
    assert permission.reason is OrderFlowPermissionReason.STACK_PAUSED


def test_stopping_stack_with_open_exposure_keeps_emergency_close() -> None:
    permission = _permission(
        stack_state=DecisionStackRuntimeState.STOPPING,
        exposure=_exposure(open_position=True),
    )
    assert not permission.allow_new_entries
    assert permission.allow_emergency_close
    assert permission.reason is OrderFlowPermissionReason.STACK_NOT_RUNNING


def test_global_kill_switch_blocks_all_entries() -> None:
    permission = _permission(switches=(_kill(KillSwitchScopeKind.GLOBAL),))
    assert not permission.allow_new_entries
    assert permission.reason is OrderFlowPermissionReason.GLOBAL_KILL_SWITCH


def test_venue_kill_switch_only_affects_matching_venue() -> None:
    matching = _permission(switches=(_kill(KillSwitchScopeKind.VENUE, "BINANCE"),))
    non_matching = _permission(switches=(_kill(KillSwitchScopeKind.VENUE, "OTHER"),))
    assert matching.reason is OrderFlowPermissionReason.VENUE_KILL_SWITCH
    assert non_matching.allow_new_entries


def test_instrument_kill_switch_only_affects_matching_instrument() -> None:
    matching = _permission(
        switches=(_kill(KillSwitchScopeKind.INSTRUMENT, "BTC/USDT"),)
    )
    non_matching = _permission(
        switches=(_kill(KillSwitchScopeKind.INSTRUMENT, "ETH/USDT"),)
    )
    assert matching.reason is OrderFlowPermissionReason.INSTRUMENT_KILL_SWITCH
    assert non_matching.allow_new_entries


def test_account_kill_switch_only_affects_matching_account() -> None:
    matching = _permission(switches=(_kill(KillSwitchScopeKind.ACCOUNT, "acct-1"),))
    non_matching = _permission(switches=(_kill(KillSwitchScopeKind.ACCOUNT, "acct-2"),))
    assert matching.reason is OrderFlowPermissionReason.ACCOUNT_KILL_SWITCH
    assert non_matching.allow_new_entries


def test_unknown_fills_require_manual_intervention_when_policy_says_so() -> None:
    exposure = OpenExposureState(
        **{**_exposure().model_dump(), "has_unknown_fills": True}
    )
    permission = _permission(exposure=exposure)
    assert not permission.allow_new_entries
    assert permission.manual_intervention_required
    assert permission.reason is OrderFlowPermissionReason.MANUAL_INTERVENTION_REQUIRED


def test_ledger_unknown_requires_manual_intervention_when_policy_says_so() -> None:
    permission = _permission(health=_health(ledger_state_unknown=True))
    assert not permission.allow_new_entries
    assert permission.manual_intervention_required
    assert permission.reason is OrderFlowPermissionReason.MANUAL_INTERVENTION_REQUIRED


def test_unreconciled_orders_block_entries_and_allow_reconciliation() -> None:
    exposure = OpenExposureState(
        **{**_exposure().model_dump(), "has_unreconciled_orders": True}
    )
    permission = _permission(exposure=exposure)
    assert not permission.allow_new_entries
    assert permission.allow_reconciliation
    assert permission.reason is OrderFlowPermissionReason.UNRECONCILED_ORDERS


def test_emergency_halted_blocks_entries_but_allows_reconciliation() -> None:
    permission = _permission(program_state=ProgramRuntimeState.EMERGENCY_HALTED)
    assert not permission.allow_new_entries
    assert permission.allow_reconciliation
    assert permission.reason is OrderFlowPermissionReason.EMERGENCY_HALTED
