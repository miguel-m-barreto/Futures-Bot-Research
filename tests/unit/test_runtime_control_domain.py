from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from futures_bot.domain.ids import (
    DecisionStackRuntimeId,
    ExposureStateId,
    KillSwitchId,
    RuntimeCheckpointId,
    RuntimeControlEventId,
    RuntimeManifestId,
    RuntimeStateTransitionId,
    WarmupPolicyId,
)
from futures_bot.domain.runtime_control import (
    DecisionStackCheckpoint,
    DecisionStackRuntimeManifest,
    DecisionStackRuntimeState,
    ExposureSafetyPolicy,
    KillSwitchScopeKind,
    KillSwitchState,
    OpenExposureState,
    PositionOwnership,
    ProgramRuntimeState,
    ProtectionMode,
    RuntimeControlCommand,
    RuntimeControlCommandKind,
    RuntimeControlEvent,
    RuntimeControlEventKind,
    RuntimeControlTargetScope,
    RuntimeStateTransition,
    RuntimeWarmupPolicy,
    canonical_payload_hash,
    deterministic_runtime_control_command_id,
    program_state_may_emit_tradable_decisions,
    stack_state_may_emit_tradable_decisions,
)

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def _command() -> RuntimeControlCommand:
    command_id = deterministic_runtime_control_command_id(
        command_kind=RuntimeControlCommandKind.PAUSE_PROGRAM,
        target_scope=RuntimeControlTargetScope.PROGRAM,
        target_id=None,
        requested_by="operator",
        reason="maintenance",
        issued_at=BASE_TIME,
        expected_state=ProgramRuntimeState.RUNNING,
        command_epoch=1,
    )
    return RuntimeControlCommand(
        command_id=command_id,
        command_kind=RuntimeControlCommandKind.PAUSE_PROGRAM,
        target_scope=RuntimeControlTargetScope.PROGRAM,
        requested_by="operator",
        reason="maintenance",
        issued_at=BASE_TIME,
        expected_state=ProgramRuntimeState.RUNNING,
        command_epoch=1,
    )


def _closed_exposure() -> OpenExposureState:
    return OpenExposureState(
        exposure_state_id=ExposureStateId("exposure-closed"),
        venue_id="BINANCE",
        instrument_id="BTC/USDT",
        account_id="acct-1",
        has_open_position=False,
        has_open_entry_orders=False,
        has_open_exit_orders=False,
        has_unknown_fills=False,
        has_unreconciled_orders=False,
        position_ownership=PositionOwnership.NONE,
        protection_mode=ProtectionMode.NONE,
        updated_at=BASE_TIME,
    )


def test_program_state_tradable_permissions() -> None:
    assert program_state_may_emit_tradable_decisions(ProgramRuntimeState.RUNNING)
    assert not program_state_may_emit_tradable_decisions(ProgramRuntimeState.PAUSED)
    assert not program_state_may_emit_tradable_decisions(
        ProgramRuntimeState.RESYNCING_GLOBAL
    )


def test_stack_state_tradable_permissions() -> None:
    assert stack_state_may_emit_tradable_decisions(DecisionStackRuntimeState.RUNNING)
    assert not stack_state_may_emit_tradable_decisions(
        DecisionStackRuntimeState.WARMING_UP
    )
    assert not stack_state_may_emit_tradable_decisions(
        DecisionStackRuntimeState.EXPOSURE_GUARDIAN_ACTIVE
    )


def test_runtime_command_deterministic_id() -> None:
    command = _command()
    assert command.command_id == deterministic_runtime_control_command_id(
        command_kind=command.command_kind,
        target_scope=command.target_scope,
        target_id=command.target_id,
        requested_by=command.requested_by,
        reason=command.reason,
        issued_at=command.issued_at,
        expected_state=command.expected_state,
        command_epoch=command.command_epoch,
    )
    with pytest.raises(ValidationError, match="command_id"):
        RuntimeControlCommand(
            **{**command.model_dump(), "command_id": "runtime-command:wrong"}
        )


def test_runtime_command_cas_expected_state_preserved() -> None:
    assert _command().expected_state is ProgramRuntimeState.RUNNING


def test_control_event_payload_hash_validation() -> None:
    command = _command()
    payload = {"accepted": True}
    event = RuntimeControlEvent(
        event_id=RuntimeControlEventId("event-1"),
        command_id=command.command_id,
        event_kind=RuntimeControlEventKind.COMMAND_ACCEPTED,
        target_scope=RuntimeControlTargetScope.PROGRAM,
        emitted_at=BASE_TIME,
        payload=payload,
        payload_hash=canonical_payload_hash(payload),
    )
    assert event.payload_hash == canonical_payload_hash(payload)
    with pytest.raises(ValidationError, match="payload_hash"):
        RuntimeControlEvent(**{**event.model_dump(), "payload_hash": "0" * 64})


def test_state_transition_validation() -> None:
    RuntimeStateTransition(
        transition_id=RuntimeStateTransitionId("transition-1"),
        target_scope=RuntimeControlTargetScope.DECISION_STACK,
        previous_state=DecisionStackRuntimeState.WARMING_UP,
        next_state=DecisionStackRuntimeState.RUNNING,
        reason="warmup complete",
        occurred_at=BASE_TIME,
    )
    with pytest.raises(ValidationError, match="invalid runtime state transition"):
        RuntimeStateTransition(
            transition_id=RuntimeStateTransitionId("transition-2"),
            target_scope=RuntimeControlTargetScope.DECISION_STACK,
            previous_state=DecisionStackRuntimeState.PAUSED,
            next_state=DecisionStackRuntimeState.RUNNING,
            reason="bad direct resume",
            occurred_at=BASE_TIME,
        )


def test_open_exposure_state_cannot_be_orphaned() -> None:
    with pytest.raises(ValidationError, match="orphaned"):
        OpenExposureState(
            **{
                **_closed_exposure().model_dump(),
                "has_open_position": True,
                "position_ownership": PositionOwnership.NONE,
            }
        )


def test_unknown_fills_and_unreconciled_orders_are_modeled() -> None:
    exposure = OpenExposureState(
        **{
            **_closed_exposure().model_dump(),
            "has_unknown_fills": True,
            "has_unreconciled_orders": True,
        }
    )
    assert exposure.has_unknown_fills
    assert exposure.has_unreconciled_orders


def test_kill_switch_scope_matching() -> None:
    global_switch = KillSwitchState(
        kill_switch_id=KillSwitchId("kill-global"),
        scope_kind=KillSwitchScopeKind.GLOBAL,
        enabled=True,
        reason="operator",
        activated_at=BASE_TIME,
    )
    venue_switch = KillSwitchState(
        kill_switch_id=KillSwitchId("kill-venue"),
        scope_kind=KillSwitchScopeKind.VENUE,
        scope_id="BINANCE",
        enabled=True,
        reason="venue incident",
        activated_at=BASE_TIME,
    )
    assert global_switch.applies_to(venue_id="ANY")
    assert venue_switch.applies_to(venue_id="BINANCE")
    assert not venue_switch.applies_to(venue_id="COINBASE")


def test_checkpoint_model_explicit_positions() -> None:
    checkpoint = DecisionStackCheckpoint(
        checkpoint_id=RuntimeCheckpointId("checkpoint-1"),
        stack_runtime_id=DecisionStackRuntimeId("stack-1"),
        stack_state=DecisionStackRuntimeState.WARMING_UP,
        config_hash="cfg",
        checkpointed_at=BASE_TIME + timedelta(milliseconds=1),
    )
    assert checkpoint.checkpointed_at == BASE_TIME + timedelta(milliseconds=1)


def test_manifest_disabled_does_not_auto_start() -> None:
    manifest = DecisionStackRuntimeManifest(
        manifest_id=RuntimeManifestId("manifest-1"),
        stack_runtime_id=DecisionStackRuntimeId("stack-1"),
        desired_state=DecisionStackRuntimeState.RUNNING,
        actual_state=DecisionStackRuntimeState.DISABLED,
        enabled=False,
        config_hash="cfg",
        updated_at=BASE_TIME,
    )
    assert not manifest.allows_auto_start()


def test_warmup_policy_validation() -> None:
    policy = RuntimeWarmupPolicy(
        warmup_policy_id=WarmupPolicyId("warmup-1"),
        min_warmup_ms=0,
        require_live_state_fresh=True,
        require_gap_free_state=True,
        require_source_health_ok=True,
        require_fee_snapshot=True,
        require_venue_rules=True,
        require_account_reconciliation=True,
    )
    assert policy.min_warmup_ms == 0


def test_exposure_safety_policy_requires_positive_staleness() -> None:
    with pytest.raises(ValidationError, match="max_allowed_staleness_ms"):
        ExposureSafetyPolicy(
            policy_id="safety",
            block_entries_on_any_gap=True,
            allow_reduce_only_during_gap=True,
            allow_emergency_close_during_gap=True,
            allow_cancel_during_gap=True,
            require_guardian_for_open_exposure_gap=True,
            require_manual_intervention_for_unknown_fills=True,
            require_manual_intervention_for_ledger_unknown=True,
            max_allowed_staleness_ms=0,
        )
