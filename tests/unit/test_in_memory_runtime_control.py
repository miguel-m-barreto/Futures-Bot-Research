from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from futures_bot.domain.ids import (
    DecisionStackRuntimeId,
    KillSwitchId,
    RuntimeCheckpointId,
    RuntimeControlCommandId,
    RuntimeControlEventId,
    RuntimeManifestId,
)
from futures_bot.domain.runtime_control import (
    DecisionStackCheckpoint,
    DecisionStackRuntimeManifest,
    DecisionStackRuntimeState,
    KillSwitchScopeKind,
    KillSwitchState,
    RuntimeControlEvent,
    RuntimeControlEventKind,
    RuntimeControlTargetScope,
    canonical_payload_hash,
)
from futures_bot.runtime_control.in_memory import (
    InMemoryDecisionStackCheckpointStore,
    InMemoryKillSwitchStore,
    InMemoryRuntimeControlEventStore,
    InMemoryRuntimeManifestStore,
)

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)
STACK_ID = DecisionStackRuntimeId("stack-1")


def _event(payload: object | None = None) -> RuntimeControlEvent:
    payload = {"accepted": True} if payload is None else payload
    return RuntimeControlEvent(
        event_id=RuntimeControlEventId("event-1"),
        command_id=RuntimeControlCommandId("command-1"),
        event_kind=RuntimeControlEventKind.COMMAND_ACCEPTED,
        target_scope=RuntimeControlTargetScope.DECISION_STACK,
        target_id=str(STACK_ID),
        emitted_at=BASE_TIME,
        payload=payload,
        payload_hash=canonical_payload_hash(payload),
    )


def _manifest(state: DecisionStackRuntimeState) -> DecisionStackRuntimeManifest:
    return DecisionStackRuntimeManifest(
        manifest_id=RuntimeManifestId("manifest-1"),
        stack_runtime_id=STACK_ID,
        desired_state=DecisionStackRuntimeState.RUNNING,
        actual_state=state,
        enabled=True,
        config_hash="cfg",
        updated_at=BASE_TIME,
    )


def _checkpoint(state: DecisionStackRuntimeState) -> DecisionStackCheckpoint:
    return DecisionStackCheckpoint(
        checkpoint_id=RuntimeCheckpointId(f"checkpoint-{state.value}"),
        stack_runtime_id=STACK_ID,
        stack_state=state,
        config_hash="cfg",
        checkpointed_at=BASE_TIME + timedelta(milliseconds=1),
    )


def test_event_store_idempotent_same_event() -> None:
    store = InMemoryRuntimeControlEventStore()
    event = _event()
    store.save(event)
    store.save(event)
    assert store.load(event.event_id) == event


def test_event_store_rejects_same_id_different_payload() -> None:
    store = InMemoryRuntimeControlEventStore()
    store.save(_event())
    with pytest.raises(ValueError, match="event id conflict"):
        store.save(_event({"accepted": False}))


def test_manifest_store_upserts_by_stack_runtime_id() -> None:
    store = InMemoryRuntimeManifestStore()
    store.save(_manifest(DecisionStackRuntimeState.RESYNCING))
    updated = _manifest(DecisionStackRuntimeState.WARMING_UP)
    store.save(updated)
    assert store.load_by_stack(STACK_ID) == updated
    assert store.load(RuntimeManifestId("manifest-1")) == updated


def test_checkpoint_store_upserts_by_stack_runtime_id() -> None:
    store = InMemoryDecisionStackCheckpointStore()
    store.save(_checkpoint(DecisionStackRuntimeState.RESYNCING))
    updated = _checkpoint(DecisionStackRuntimeState.WARMING_UP)
    store.save(updated)
    assert store.load_latest(STACK_ID) == updated


def test_kill_switch_store_returns_matching_global_venue_instrument_account() -> None:
    store = InMemoryKillSwitchStore()
    switches = (
        KillSwitchState(
            kill_switch_id=KillSwitchId("kill-global"),
            scope_kind=KillSwitchScopeKind.GLOBAL,
            enabled=True,
            reason="global",
            activated_at=BASE_TIME,
        ),
        KillSwitchState(
            kill_switch_id=KillSwitchId("kill-venue"),
            scope_kind=KillSwitchScopeKind.VENUE,
            scope_id="BINANCE",
            enabled=True,
            reason="venue",
            activated_at=BASE_TIME,
        ),
        KillSwitchState(
            kill_switch_id=KillSwitchId("kill-instrument"),
            scope_kind=KillSwitchScopeKind.INSTRUMENT,
            scope_id="BTC/USDT",
            enabled=True,
            reason="instrument",
            activated_at=BASE_TIME,
        ),
        KillSwitchState(
            kill_switch_id=KillSwitchId("kill-account"),
            scope_kind=KillSwitchScopeKind.ACCOUNT,
            scope_id="acct-1",
            enabled=True,
            reason="account",
            activated_at=BASE_TIME,
        ),
    )
    for switch in switches:
        store.save(switch)

    venue_matches = store.list_matching(KillSwitchScopeKind.VENUE, "BINANCE")
    instrument_matches = store.list_matching(KillSwitchScopeKind.INSTRUMENT, "BTC/USDT")
    account_matches = store.list_matching(KillSwitchScopeKind.ACCOUNT, "acct-1")
    assert {switch.scope_kind for switch in venue_matches} == {
        KillSwitchScopeKind.GLOBAL,
        KillSwitchScopeKind.VENUE,
    }
    assert {switch.scope_kind for switch in instrument_matches} == {
        KillSwitchScopeKind.GLOBAL,
        KillSwitchScopeKind.INSTRUMENT,
    }
    assert {switch.scope_kind for switch in account_matches} == {
        KillSwitchScopeKind.GLOBAL,
        KillSwitchScopeKind.ACCOUNT,
    }
