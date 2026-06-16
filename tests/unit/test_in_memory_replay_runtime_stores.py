from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.replay import (
    ReplayEventDispatchReceipt,
    ReplayInputKind,
    ReplayRunState,
    ReplayRunStatus,
    build_replay_dispatcher_fingerprint,
    build_replay_event_dispatch_receipt_id,
)
from futures_bot.infrastructure.replay.in_memory import (
    InMemoryReplayEventDispatchReceiptStore,
    InMemoryReplayRunStateStore,
)
from futures_bot.ports.replay import (
    ReplayEventDispatchReceiptStorePort,
    ReplayRunStateStorePort,
)


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


EMPTY_DISPATCHER_FINGERPRINT = build_replay_dispatcher_fingerprint(())


def _state(  # noqa: PLR0913 - compact test fixture builder
    run_id: str = "run-1",
    *,
    manifest_id: str = "manifest-1",
    timeline_id: str = "timeline-1",
    timeline_fingerprint_id: str = "fp-1",
    replay_plan_id: str = "plan-1",
    created_at: datetime | None = None,
    revision: int = 0,
    status: ReplayRunStatus = ReplayRunStatus.CREATED,
    next_event_index: int = 0,
    processed_event_count: int = 0,
    last_processed_event_id: str | None = None,
) -> ReplayRunState:
    active_statuses = {
        ReplayRunStatus.RUNNING,
        ReplayRunStatus.PAUSED,
        ReplayRunStatus.COMPLETED,
    }
    started_at = _utc(2) if status in active_statuses else None
    paused_at = _utc(3) if status is ReplayRunStatus.PAUSED else None
    completed_at = _utc(4) if status is ReplayRunStatus.COMPLETED else None
    if completed_at is not None:
        updated_at = _utc(4)
    elif paused_at is not None:
        updated_at = _utc(3)
    elif started_at is not None:
        updated_at = _utc(2)
    else:
        updated_at = created_at or _utc(1)
    return ReplayRunState(
        run_id=run_id,
        manifest_id=manifest_id,
        replay_plan_id=replay_plan_id,
        timeline_id=timeline_id,
        timeline_fingerprint_id=timeline_fingerprint_id,
        dispatcher_fingerprint=EMPTY_DISPATCHER_FINGERPRINT,
        created_at=created_at or _utc(1),
        updated_at=updated_at,
        started_at=started_at,
        paused_at=paused_at,
        completed_at=completed_at,
        status=status,
        revision=revision,
        total_event_count=3,
        next_event_index=next_event_index,
        processed_event_count=processed_event_count,
        last_processed_event_id=last_processed_event_id,
    )


def _running(revision: int = 1, index: int = 0) -> ReplayRunState:
    return _state(
        revision=revision,
        status=ReplayRunStatus.RUNNING,
        next_event_index=index,
        processed_event_count=index,
        last_processed_event_id=f"event-{index}" if index else None,
    )


def _paused(revision: int = 2, index: int = 0) -> ReplayRunState:
    return _state(
        revision=revision,
        status=ReplayRunStatus.PAUSED,
        next_event_index=index,
        processed_event_count=index,
        last_processed_event_id=f"event-{index - 1}" if index else None,
    )


def _completed(revision: int = 2) -> ReplayRunState:
    return _state(
        revision=revision,
        status=ReplayRunStatus.COMPLETED,
        next_event_index=3,
        processed_event_count=3,
        last_processed_event_id="event-2",
    )


def _receipt(
    receipt_id: str | None = None,
    *,
    run_id: str = "run-1",
    order_index: int = 0,
    event_id: str = "event-0",
) -> ReplayEventDispatchReceipt:
    if receipt_id is None:
        receipt_id = build_replay_event_dispatch_receipt_id(
            run_id,
            order_index,
            event_id,
        )
    return ReplayEventDispatchReceipt(
        receipt_id=receipt_id,
        run_id=run_id,
        manifest_id="manifest-1",
        replay_plan_id="plan-1",
        timeline_id="timeline-1",
        timeline_fingerprint_id="fp-1",
        dispatcher_fingerprint=EMPTY_DISPATCHER_FINGERPRINT,
        event_id=event_id,
        event_order_index=order_index,
        event_time=_utc(order_index + 1),
        event_kind=ReplayInputKind.MARK_PRICE,
    )


class TestInMemoryReplayRunStateStoreConformance:
    def test_conforms_to_port(self) -> None:
        _: ReplayRunStateStorePort = InMemoryReplayRunStateStore()


class TestInMemoryReplayRunStateStore:
    def test_create_and_load(self) -> None:
        store = InMemoryReplayRunStateStore()
        state = _state()
        store.create(state)
        assert store.load("run-1") == state

    def test_load_missing_returns_none(self) -> None:
        assert InMemoryReplayRunStateStore().load("missing") is None

    def test_idempotent_create(self) -> None:
        store = InMemoryReplayRunStateStore()
        state = _state()
        store.create(state)
        store.create(state)
        assert store.list_all() == (state,)

    def test_conflicting_create_rejected(self) -> None:
        store = InMemoryReplayRunStateStore()
        store.create(_state())
        with pytest.raises(ValueError, match="conflict"):
            store.create(_state(replay_plan_id="plan-2"))

    @pytest.mark.parametrize(
        "state",
        [_running(), _paused(), _completed()],
    )
    def test_create_non_created_state_rejected(self, state: ReplayRunState) -> None:
        store = InMemoryReplayRunStateStore()
        with pytest.raises(ValueError, match="create requires CREATED"):
            store.create(state)

    def test_correct_cas_replacement(self) -> None:
        store = InMemoryReplayRunStateStore()
        state = _state()
        store.create(state)
        replacement = state.model_copy(
            update={
                "status": ReplayRunStatus.RUNNING,
                "revision": 1,
                "started_at": _utc(2),
                "updated_at": _utc(2),
            }
        )
        store.replace(replacement, expected_revision=0)
        assert store.load("run-1") == replacement

    def test_valid_start_step_pause_resume_complete_replacements_accepted(self) -> None:
        store = InMemoryReplayRunStateStore()
        created = _state()
        running = _running(revision=1)
        progressed = _running(revision=2, index=1).model_copy(
            update={"updated_at": _utc(3), "last_processed_event_id": "event-0"}
        )
        paused = _paused(revision=3, index=1).model_copy(
            update={
                "updated_at": _utc(4),
                "paused_at": _utc(4),
                "last_processed_event_id": "event-0",
            }
        )
        resumed = _running(revision=4, index=1).model_copy(
            update={"updated_at": _utc(5), "last_processed_event_id": "event-0"}
        )
        completed = _completed(revision=5).model_copy(
            update={"updated_at": _utc(6), "completed_at": _utc(6)}
        )
        store.create(created)
        store.replace(running, expected_revision=0)
        store.replace(progressed, expected_revision=1)
        store.replace(paused, expected_revision=2)
        store.replace(resumed, expected_revision=3)
        store.replace(completed, expected_revision=4)
        assert store.load("run-1") == completed

    def test_stale_expected_revision_rejected(self) -> None:
        store = InMemoryReplayRunStateStore()
        state = _state()
        store.create(state)
        replacement = state.model_copy(
            update={
                "status": ReplayRunStatus.RUNNING,
                "revision": 1,
                "started_at": _utc(2),
                "updated_at": _utc(2),
            }
        )
        with pytest.raises(ValueError, match="stale"):
            store.replace(replacement, expected_revision=1)

    def test_skipped_revision_rejected(self) -> None:
        store = InMemoryReplayRunStateStore()
        state = _state()
        store.create(state)
        replacement = state.model_copy(
            update={
                "status": ReplayRunStatus.RUNNING,
                "revision": 2,
                "started_at": _utc(2),
                "updated_at": _utc(2),
            }
        )
        with pytest.raises(ValueError, match="revision"):
            store.replace(replacement, expected_revision=0)

    def test_replacement_timestamp_regression_rejected(self) -> None:
        store = InMemoryReplayRunStateStore()
        state = _state()
        store.create(state)
        running = state.model_copy(
            update={
                "status": ReplayRunStatus.RUNNING,
                "revision": 1,
                "started_at": _utc(2),
                "updated_at": _utc(2),
            }
        )
        store.replace(running, expected_revision=0)
        progressed = running.model_copy(
            update={
                "revision": 2,
                "updated_at": _utc(4),
                "next_event_index": 1,
                "processed_event_count": 1,
                "last_processed_event_id": "event-0",
            }
        )
        store.replace(progressed, expected_revision=1)
        regressed = progressed.model_copy(
            update={
                "revision": 3,
                "updated_at": _utc(3),
                "next_event_index": 2,
                "processed_event_count": 2,
                "last_processed_event_id": "event-1",
            }
        )
        with pytest.raises(ValueError, match="updated_at"):
            store.replace(regressed, expected_revision=2)

    def test_created_to_paused_replacement_rejected(self) -> None:
        store = InMemoryReplayRunStateStore()
        store.create(_state())
        with pytest.raises(ValueError, match="invalid replay run state transition"):
            store.replace(_paused(revision=1), expected_revision=0)

    def test_running_to_created_replacement_rejected(self) -> None:
        store = InMemoryReplayRunStateStore()
        created = _state()
        running = _running(revision=1)
        store.create(created)
        store.replace(running, expected_revision=0)
        invalid_created = created.model_copy(update={"revision": 2})
        with pytest.raises((ValidationError, ValueError)):
            store.replace(invalid_created, expected_revision=1)

    def test_paused_to_completed_replacement_rejected(self) -> None:
        store = InMemoryReplayRunStateStore()
        created = _state()
        running = _running(revision=1)
        paused = _paused(revision=2)
        completed = _completed(revision=3)
        store.create(created)
        store.replace(running, expected_revision=0)
        store.replace(paused, expected_revision=1)
        with pytest.raises(ValueError, match="invalid replay run state transition"):
            store.replace(completed, expected_revision=2)

    def test_completed_to_running_replacement_rejected(self) -> None:
        store = InMemoryReplayRunStateStore()
        created = _state()
        running = _running(revision=1)
        completed = _completed(revision=2)
        resumed = _running(revision=3).model_copy(
            update={
                "updated_at": _utc(5),
                "next_event_index": 2,
                "processed_event_count": 2,
                "last_processed_event_id": "event-1",
            }
        )
        store.create(created)
        store.replace(running, expected_revision=0)
        store.replace(completed, expected_revision=1)
        with pytest.raises(
            ValueError,
            match=r"completed_at|invalid replay run state transition",
        ):
            store.replace(resumed, expected_revision=2)

    def test_started_at_mutation_rejected(self) -> None:
        store = InMemoryReplayRunStateStore()
        created = _state()
        running = _running(revision=1)
        mutated = _running(revision=2).model_copy(
            update={
                "updated_at": _utc(3),
                "started_at": _utc(3),
                "next_event_index": 1,
                "processed_event_count": 1,
                "last_processed_event_id": "event-0",
            }
        )
        store.create(created)
        store.replace(running, expected_revision=0)
        with pytest.raises(ValueError, match="started_at"):
            store.replace(mutated, expected_revision=1)

    def test_positive_progress_with_stale_last_processed_event_id_rejected(self) -> None:
        store = InMemoryReplayRunStateStore()
        created = _state()
        running = _running(revision=1)
        progressed = running.model_copy(
            update={
                "revision": 2,
                "updated_at": _utc(3),
                "next_event_index": 1,
                "processed_event_count": 1,
                "last_processed_event_id": "event-0",
            }
        )
        stale_progress = progressed.model_copy(
            update={
                "revision": 3,
                "updated_at": _utc(4),
                "next_event_index": 2,
                "processed_event_count": 2,
                "last_processed_event_id": "event-0",
            }
        )
        store.create(created)
        store.replace(running, expected_revision=0)
        store.replace(progressed, expected_revision=1)
        with pytest.raises(ValueError, match="last_processed_event_id to advance"):
            store.replace(stale_progress, expected_revision=2)

    @pytest.mark.parametrize(
        "field,value",
        [
            ("run_id", "run-2"),
            ("manifest_id", "manifest-2"),
            ("replay_plan_id", "plan-2"),
            ("timeline_id", "timeline-2"),
            ("timeline_fingerprint_id", "fp-2"),
            ("created_at", _utc(0)),
            ("total_event_count", 4),
        ],
    )
    def test_identity_mutation_rejected(self, field: str, value: object) -> None:
        store = InMemoryReplayRunStateStore()
        state = _state()
        store.create(state)
        replacement = state.model_copy(
            update={
                "status": ReplayRunStatus.RUNNING,
                "revision": 1,
                "started_at": _utc(2),
                "updated_at": _utc(2),
                field: value,
            }
        )
        with pytest.raises(
            ValueError,
            match=r"identity|not found|revision|total_event_count",
        ):
            store.replace(replacement, expected_revision=0)

    def test_model_copy_tampering_rejected(self) -> None:
        store = InMemoryReplayRunStateStore()
        state = _state()
        store.create(state)
        tampered = state.model_copy(update={"revision": "1"})
        with pytest.raises((ValidationError, ValueError)):
            store.replace(tampered, expected_revision=0)

    def test_deterministic_lists(self) -> None:
        store = InMemoryReplayRunStateStore()
        store.create(_state("run-b", created_at=_utc(2)))
        store.create(_state("run-a", created_at=_utc(1)))
        store.create(_state("run-c", replay_plan_id="plan-2", created_at=_utc(1)))
        assert [s.run_id for s in store.list_all()] == ["run-a", "run-c", "run-b"]
        assert [s.run_id for s in store.list_for_replay_plan("plan-1")] == [
            "run-a",
            "run-b",
        ]


class TestInMemoryReplayEventDispatchReceiptStoreConformance:
    def test_conforms_to_port(self) -> None:
        _: ReplayEventDispatchReceiptStorePort = InMemoryReplayEventDispatchReceiptStore()


class TestInMemoryReplayEventDispatchReceiptStore:
    def test_save_and_load(self) -> None:
        store = InMemoryReplayEventDispatchReceiptStore()
        receipt = _receipt()
        store.save(receipt)
        assert store.load(receipt.receipt_id) == receipt

    def test_load_missing_returns_none(self) -> None:
        assert InMemoryReplayEventDispatchReceiptStore().load("missing") is None

    def test_receipt_idempotency_and_conflict(self) -> None:
        store = InMemoryReplayEventDispatchReceiptStore()
        receipt = _receipt()
        store.save(receipt)
        store.save(receipt)
        conflict = receipt.model_copy(update={"event_time": _utc(3)})
        with pytest.raises(ValueError, match="conflict"):
            store.save(conflict)

    def test_model_copy_tampering_rejected(self) -> None:
        store = InMemoryReplayEventDispatchReceiptStore()
        tampered = _receipt().model_copy(update={"event_order_index": "0"})
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_deterministic_receipt_order(self) -> None:
        store = InMemoryReplayEventDispatchReceiptStore()
        rb2 = _receipt(run_id="run-b", order_index=2, event_id="e2")
        ra1 = _receipt(run_id="run-a", order_index=1, event_id="e1")
        rb1 = _receipt(run_id="run-b", order_index=1, event_id="e1")
        rb1b = _receipt(run_id="run-b", order_index=1, event_id="e1b")
        store.save(rb2)
        store.save(ra1)
        store.save(rb1)
        store.save(rb1b)
        same_index = tuple(sorted((rb1, rb1b), key=lambda r: r.receipt_id))
        assert store.list_for_run("run-b") == (*same_index, rb2)
        assert store.list_all() == (ra1, *same_index, rb2)

    def test_formerly_colliding_receipts_can_coexist(self) -> None:
        store = InMemoryReplayEventDispatchReceiptStore()
        first = _receipt(run_id="a", order_index=1, event_id="2:b")
        second = _receipt(run_id="a:1", order_index=2, event_id="b")
        assert first.receipt_id != second.receipt_id
        store.save(first)
        store.save(second)
        assert store.load(first.receipt_id) == first
        assert store.load(second.receipt_id) == second
