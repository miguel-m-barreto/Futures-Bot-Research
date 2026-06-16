from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.replay import (
    ReplayEventDispatchReceipt,
    ReplayInputKind,
    ReplayRunState,
    ReplayRunStatus,
    ReplayRunStepResult,
    build_replay_dispatcher_fingerprint,
    build_replay_event_dispatch_receipt_id,
    validate_replay_run_state_transition,
)


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


EMPTY_DISPATCHER_FINGERPRINT = build_replay_dispatcher_fingerprint(())


def _state(  # noqa: PLR0913 - compact test fixture builder
    *,
    run_id: str = "run-1",
    manifest_id: str = "manifest-1",
    replay_plan_id: str = "plan-1",
    timeline_id: str = "timeline-1",
    timeline_fingerprint_id: str = "fp-1",
    dispatcher_fingerprint: str = EMPTY_DISPATCHER_FINGERPRINT,
    created_at: datetime | None = None,
    status: ReplayRunStatus = ReplayRunStatus.CREATED,
    revision: int = 0,
    total_event_count: int = 3,
    next_event_index: int = 0,
    processed_event_count: int = 0,
    started_at: datetime | None = None,
    paused_at: datetime | None = None,
    completed_at: datetime | None = None,
    updated_at: datetime | None = None,
    last_processed_event_id: str | None = None,
) -> ReplayRunState:
    return ReplayRunState(
        run_id=run_id,
        manifest_id=manifest_id,
        replay_plan_id=replay_plan_id,
        timeline_id=timeline_id,
        timeline_fingerprint_id=timeline_fingerprint_id,
        dispatcher_fingerprint=dispatcher_fingerprint,
        created_at=created_at or _utc(1),
        updated_at=updated_at or created_at or _utc(1),
        started_at=started_at,
        paused_at=paused_at,
        completed_at=completed_at,
        status=status,
        revision=revision,
        total_event_count=total_event_count,
        next_event_index=next_event_index,
        processed_event_count=processed_event_count,
        last_processed_event_id=last_processed_event_id,
    )


def _receipt(  # noqa: PLR0913 - compact receipt fixture builder
    *,
    run_id: str = "run-1",
    manifest_id: str = "manifest-1",
    replay_plan_id: str = "plan-1",
    timeline_id: str = "timeline-1",
    timeline_fingerprint_id: str = "fp-1",
    dispatcher_fingerprint: str = EMPTY_DISPATCHER_FINGERPRINT,
    event_id: str = "event-0",
    order_index: int = 0,
    receipt_id: str | None = None,
    handler_ids: tuple[str, ...] = (),
    output_record_ids: tuple[str, ...] = (),
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
        manifest_id=manifest_id,
        replay_plan_id=replay_plan_id,
        timeline_id=timeline_id,
        timeline_fingerprint_id=timeline_fingerprint_id,
        dispatcher_fingerprint=dispatcher_fingerprint,
        event_id=event_id,
        event_order_index=order_index,
        event_time=_utc(2),
        event_kind=ReplayInputKind.MARK_PRICE,
        handler_ids=handler_ids,
        output_record_ids=output_record_ids,
    )


def _result(  # noqa: PLR0913 - compact test fixture builder
    *,
    previous_status: ReplayRunStatus = ReplayRunStatus.RUNNING,
    current_status: ReplayRunStatus = ReplayRunStatus.RUNNING,
    previous_revision: int = 1,
    current_revision: int = 2,
    previous_index: int = 0,
    current_index: int = 1,
    receipts: tuple[ReplayEventDispatchReceipt, ...] | None = None,
    completed: bool = False,
    total_event_count: int = 3,
) -> ReplayRunStepResult:
    if receipts is None:
        receipts = tuple(
            _receipt(order_index=i, event_id=f"event-{i}")
            for i in range(previous_index, current_index)
        )
    return ReplayRunStepResult(
        run_id="run-1",
        previous_status=previous_status,
        current_status=current_status,
        previous_revision=previous_revision,
        current_revision=current_revision,
        previous_next_event_index=previous_index,
        previous_processed_event_count=previous_index,
        processed_receipts=receipts,
        next_event_index=current_index,
        processed_event_count=current_index,
        total_event_count=total_event_count,
        completed=completed,
    )


def _start_state(total_event_count: int = 3) -> ReplayRunState:
    return _state(total_event_count=total_event_count)


def _running_state(
    *,
    revision: int = 1,
    index: int = 0,
    updated_at: datetime | None = None,
    last_event_id: str | None = None,
    total_event_count: int = 3,
) -> ReplayRunState:
    if updated_at is None:
        updated_at = _utc(2)
    return _state(
        status=ReplayRunStatus.RUNNING,
        revision=revision,
        total_event_count=total_event_count,
        started_at=_utc(2),
        updated_at=updated_at,
        next_event_index=index,
        processed_event_count=index,
        last_processed_event_id=last_event_id,
    )


def _paused_state(
    *,
    revision: int = 2,
    index: int = 0,
    updated_at: datetime | None = None,
    last_event_id: str | None = None,
) -> ReplayRunState:
    if updated_at is None:
        updated_at = _utc(3)
    return _state(
        status=ReplayRunStatus.PAUSED,
        revision=revision,
        started_at=_utc(2),
        paused_at=updated_at,
        updated_at=updated_at,
        next_event_index=index,
        processed_event_count=index,
        last_processed_event_id=last_event_id,
    )


def _completed_state(
    *,
    revision: int = 2,
    total_event_count: int = 3,
    updated_at: datetime | None = None,
    last_event_id: str | None = "event-2",
) -> ReplayRunState:
    if updated_at is None:
        updated_at = _utc(4)
    return _state(
        status=ReplayRunStatus.COMPLETED,
        revision=revision,
        total_event_count=total_event_count,
        started_at=_utc(2),
        completed_at=updated_at,
        updated_at=updated_at,
        next_event_index=total_event_count,
        processed_event_count=total_event_count,
        last_processed_event_id=last_event_id,
    )


class TestReplayRunState:
    def test_created_valid(self) -> None:
        state = _state()
        assert state.status is ReplayRunStatus.CREATED
        assert state.updated_at == state.created_at

    def test_all_ids_must_be_trimmed(self) -> None:
        with pytest.raises(ValidationError):
            ReplayRunState(**{**_state().model_dump(), "run_id": " run-1"})

    @pytest.mark.parametrize("field", ["revision", "total_event_count", "next_event_index"])
    @pytest.mark.parametrize("value", [True, "1", 1.2])
    def test_strict_integer_fields(self, field: str, value: object) -> None:
        with pytest.raises(ValidationError):
            _state(**{field: value})  # type: ignore[arg-type]

    def test_timestamp_validation_and_temporal_ordering(self) -> None:
        with pytest.raises(ValidationError):
            _state(updated_at=datetime(2026, 1, 1))
        with pytest.raises(ValidationError, match="updated_at must be >= created_at"):
            _state(updated_at=_utc(0))
        with pytest.raises(ValidationError, match="updated_at must be >= started_at"):
            _state(
                status=ReplayRunStatus.RUNNING,
                revision=1,
                started_at=_utc(3),
                updated_at=_utc(2),
            )
        with pytest.raises(ValidationError, match="paused_at must be >= started_at"):
            _state(
                status=ReplayRunStatus.PAUSED,
                revision=2,
                started_at=_utc(3),
                paused_at=_utc(2),
                updated_at=_utc(3),
            )
        with pytest.raises(ValidationError, match="completed_at must be >= started_at"):
            _state(
                status=ReplayRunStatus.COMPLETED,
                revision=2,
                started_at=_utc(3),
                completed_at=_utc(2),
                updated_at=_utc(3),
                next_event_index=3,
                processed_event_count=3,
                last_processed_event_id="event-2",
            )

    def test_equal_timestamps_accepted(self) -> None:
        running = _state(
            status=ReplayRunStatus.RUNNING,
            revision=1,
            started_at=_utc(2),
            updated_at=_utc(2),
        )
        paused = _state(
            status=ReplayRunStatus.PAUSED,
            revision=2,
            started_at=_utc(2),
            paused_at=_utc(2),
            updated_at=_utc(2),
        )
        completed = _state(
            status=ReplayRunStatus.COMPLETED,
            revision=3,
            started_at=_utc(2),
            completed_at=_utc(2),
            updated_at=_utc(2),
            next_event_index=3,
            processed_event_count=3,
            last_processed_event_id="event-2",
        )
        assert running.updated_at == running.started_at
        assert paused.paused_at == paused.updated_at
        assert completed.completed_at == completed.updated_at

    def test_progress_count_coherence(self) -> None:
        with pytest.raises(ValidationError, match="processed_event_count must equal"):
            _state(next_event_index=1, processed_event_count=0)
        with pytest.raises(ValidationError, match="last_processed_event_id is required"):
            _state(
                status=ReplayRunStatus.RUNNING,
                revision=1,
                started_at=_utc(2),
                updated_at=_utc(2),
                next_event_index=1,
                processed_event_count=1,
            )
        with pytest.raises(ValidationError, match="last_processed_event_id must be None"):
            _state(last_processed_event_id="event-0")

    def test_status_invariants(self) -> None:
        with pytest.raises(ValidationError, match="CREATED requires updated_at"):
            _state(updated_at=_utc(2))
        with pytest.raises(ValidationError, match="RUNNING requires started_at"):
            _state(status=ReplayRunStatus.RUNNING, revision=1)
        with pytest.raises(ValidationError, match="PAUSED requires paused_at"):
            _state(
                status=ReplayRunStatus.PAUSED,
                revision=2,
                started_at=_utc(2),
                updated_at=_utc(2),
            )
        with pytest.raises(ValidationError, match="COMPLETED requires completed_at"):
            _state(
                status=ReplayRunStatus.COMPLETED,
                revision=3,
                started_at=_utc(2),
                updated_at=_utc(2),
                next_event_index=3,
                processed_event_count=3,
                last_processed_event_id="event-2",
            )

    def test_failed_and_invalidated_are_minimally_coherent(self) -> None:
        assert _state(status=ReplayRunStatus.FAILED, revision=5).status is ReplayRunStatus.FAILED
        assert (
            _state(status=ReplayRunStatus.INVALIDATED, revision=5).status
            is ReplayRunStatus.INVALIDATED
        )

    def test_frozen_and_extra_forbidden(self) -> None:
        state = _state()
        with pytest.raises((ValidationError, TypeError)):
            state.run_id = "other"  # type: ignore[misc]
        with pytest.raises(ValidationError):
            ReplayRunState(**state.model_dump(), extra_field="x")  # type: ignore[arg-type]


class TestReplayEventDispatchReceiptId:
    def test_same_inputs_produce_same_id(self) -> None:
        first = build_replay_event_dispatch_receipt_id("run-1", 0, "event-1")
        second = build_replay_event_dispatch_receipt_id("run-1", 0, "event-1")
        assert first == second
        assert re.fullmatch(r"replay-dispatch:[0-9a-f]{64}", first)

    def test_changed_material_changes_id(self) -> None:
        base = build_replay_event_dispatch_receipt_id("run-1", 0, "event-1")
        assert build_replay_event_dispatch_receipt_id("run-2", 0, "event-1") != base
        assert build_replay_event_dispatch_receipt_id("run-1", 1, "event-1") != base
        assert build_replay_event_dispatch_receipt_id("run-1", 0, "event-2") != base

    def test_colon_ambiguity_is_delimiter_safe(self) -> None:
        first = build_replay_event_dispatch_receipt_id("a", 1, "2:b")
        second = build_replay_event_dispatch_receipt_id("a:1", 2, "b")
        assert first != second

    @pytest.mark.parametrize("value", [True, "0", 0.5, -1])
    def test_strict_non_negative_index_validation(self, value: object) -> None:
        with pytest.raises((TypeError, ValueError)):
            build_replay_event_dispatch_receipt_id("run-1", value, "event-1")  # type: ignore[arg-type]


class TestReplayEventDispatchReceipt:
    def test_receipt_model_is_deterministic_and_minimal(self) -> None:
        receipt = _receipt()
        assert receipt.receipt_id == build_replay_event_dispatch_receipt_id(
            "run-1",
            0,
            "event-0",
        )
        assert not hasattr(receipt, "processed_at")
        assert not hasattr(receipt, "payload")
        assert not hasattr(receipt, "strategy_output")

    def test_arbitrary_receipt_id_rejected(self) -> None:
        with pytest.raises(ValidationError, match="receipt_id"):
            _receipt(receipt_id="not-the-deterministic-id")

    def test_time_and_id_validation(self) -> None:
        data = _receipt().model_dump()
        data["event_time"] = datetime(2026, 1, 1)
        with pytest.raises(ValidationError):
            ReplayEventDispatchReceipt(**data)
        with pytest.raises((ValidationError, ValueError)):
            _receipt(run_id=" run-1")


class TestReplayRunStepResult:
    def test_valid_start_step_pause_resume_and_completion_results(self) -> None:
        start = _result(
            previous_status=ReplayRunStatus.CREATED,
            current_status=ReplayRunStatus.RUNNING,
            previous_revision=0,
            current_revision=1,
            previous_index=0,
            current_index=0,
            receipts=(),
        )
        step = _result()
        pause = _result(
            previous_status=ReplayRunStatus.RUNNING,
            current_status=ReplayRunStatus.PAUSED,
            previous_revision=2,
            current_revision=3,
            previous_index=1,
            current_index=1,
            receipts=(),
        )
        resume = _result(
            previous_status=ReplayRunStatus.PAUSED,
            current_status=ReplayRunStatus.RUNNING,
            previous_revision=3,
            current_revision=4,
            previous_index=1,
            current_index=1,
            receipts=(),
        )
        completed = _result(
            current_status=ReplayRunStatus.COMPLETED,
            previous_index=2,
            current_index=3,
            completed=True,
        )
        empty_completed = _result(
            previous_status=ReplayRunStatus.CREATED,
            current_status=ReplayRunStatus.COMPLETED,
            previous_revision=0,
            current_revision=1,
            previous_index=0,
            current_index=0,
            receipts=(),
            completed=True,
            total_event_count=0,
        )
        assert start.current_status is ReplayRunStatus.RUNNING
        assert step.processed_receipts
        assert pause.current_status is ReplayRunStatus.PAUSED
        assert resume.current_status is ReplayRunStatus.RUNNING
        assert completed.completed is True
        assert empty_completed.completed is True

    def test_revision_must_increment_by_one(self) -> None:
        with pytest.raises(ValidationError, match="current_revision"):
            _result(current_revision=3)

    def test_receipt_from_another_run_rejected(self) -> None:
        with pytest.raises(ValidationError, match="run_id"):
            _result(receipts=(_receipt(run_id="run-other"),))

    @pytest.mark.parametrize(
        "tamper",
        [
            {"dispatcher_fingerprint": "bad"},
            {"handler_ids": ("handler-a", "handler-a")},
            {"handler_ids": (), "output_record_ids": ("replay-output:" + "0" * 64,)},
            {
                "handler_ids": ("handler-a",),
                "output_record_ids": ("bad-output-id",),
            },
            {
                "handler_ids": ("handler-a",),
                "output_record_ids": (
                    "replay-output:" + "0" * 64,
                    "replay-output:" + "0" * 64,
                ),
            },
            {"receipt_id": "replay-dispatch:" + "0" * 64},
        ],
    )
    def test_processed_receipts_are_fully_revalidated(
        self,
        tamper: dict[str, object],
    ) -> None:
        receipt = _receipt().model_copy(update=tamper)
        with pytest.raises(ValidationError):
            _result(receipts=(receipt,))

    @pytest.mark.parametrize(
        "field,value",
        [
            ("manifest_id", "manifest-2"),
            ("replay_plan_id", "plan-2"),
            ("timeline_id", "timeline-2"),
            ("timeline_fingerprint_id", "fp-2"),
            ("dispatcher_fingerprint", "replay-dispatcher:" + "0" * 64),
        ],
    )
    def test_processed_receipts_must_share_immutable_binding(
        self,
        field: str,
        value: str,
    ) -> None:
        receipts = (
            _receipt(order_index=0, event_id="event-0"),
            _receipt(order_index=1, event_id="event-1").model_copy(update={field: value}),
        )
        with pytest.raises(ValidationError, match=field):
            _result(previous_index=0, current_index=2, receipts=receipts)

    def test_receipt_output_ids_require_handler_ids(self) -> None:
        with pytest.raises(ValidationError, match="output_record_ids require"):
            _receipt(output_record_ids=("replay-output:" + "0" * 64,))
        assert _receipt(handler_ids=("handler-a",), output_record_ids=()).handler_ids == (
            "handler-a",
        )

    def test_receipt_count_must_match_progress_delta(self) -> None:
        with pytest.raises(ValidationError, match="receipt count"):
            _result(previous_index=0, current_index=2, receipts=(_receipt(order_index=0),))

    def test_skipped_or_wrong_order_indexes_rejected(self) -> None:
        with pytest.raises(ValidationError, match="exactly match progress"):
            _result(
                previous_index=0,
                current_index=2,
                receipts=(
                    _receipt(order_index=0, event_id="event-0"),
                    _receipt(order_index=2, event_id="event-2"),
                ),
            )
        with pytest.raises(ValidationError, match="exactly match progress"):
            _result(
                previous_index=0,
                current_index=2,
                receipts=(
                    _receipt(order_index=1, event_id="event-1"),
                    _receipt(order_index=0, event_id="event-0"),
                ),
            )

    def test_illegal_transition_pair_rejected(self) -> None:
        with pytest.raises(ValidationError, match="invalid replay run transition"):
            _result(
                previous_status=ReplayRunStatus.PAUSED,
                current_status=ReplayRunStatus.COMPLETED,
                previous_index=2,
                current_index=3,
                receipts=(_receipt(order_index=2, event_id="event-2"),),
                completed=True,
            )

    def test_pause_resume_progress_mutation_rejected(self) -> None:
        with pytest.raises(ValidationError, match="no-progress transitions"):
            _result(
                previous_status=ReplayRunStatus.RUNNING,
                current_status=ReplayRunStatus.PAUSED,
                previous_index=1,
                current_index=2,
                receipts=(_receipt(order_index=1, event_id="event-1"),),
            )
        with pytest.raises(ValidationError, match="no-progress transitions"):
            _result(
                previous_status=ReplayRunStatus.PAUSED,
                current_status=ReplayRunStatus.RUNNING,
                previous_index=1,
                current_index=2,
                receipts=(_receipt(order_index=1, event_id="event-1"),),
            )

    def test_step_and_running_completion_require_progress_and_receipts(self) -> None:
        with pytest.raises(ValidationError, match="RUNNING step transitions"):
            _result(previous_index=1, current_index=1, receipts=())
        with pytest.raises(ValidationError, match="RUNNING step transitions"):
            _result(
                current_status=ReplayRunStatus.COMPLETED,
                previous_index=2,
                current_index=2,
                receipts=(),
                completed=True,
            )

    def test_terminal_and_running_status_coherence(self) -> None:
        with pytest.raises(ValidationError, match="CREATED -> COMPLETED"):
            _result(
                previous_status=ReplayRunStatus.CREATED,
                current_status=ReplayRunStatus.COMPLETED,
                previous_revision=0,
                current_revision=1,
                previous_index=0,
                current_index=0,
                receipts=(),
                completed=True,
                total_event_count=3,
            )
        with pytest.raises(ValidationError, match="COMPLETED result"):
            _result(
                current_status=ReplayRunStatus.COMPLETED,
                previous_index=1,
                current_index=2,
                receipts=(_receipt(order_index=1, event_id="event-1"),),
                completed=True,
                total_event_count=3,
            )
        with pytest.raises(ValidationError, match="RUNNING result"):
            _result(
                previous_index=2,
                current_index=3,
                receipts=(_receipt(order_index=2, event_id="event-2"),),
                total_event_count=3,
            )
        assert _result(total_event_count=3).current_status is ReplayRunStatus.RUNNING
        assert (
            _result(
                current_status=ReplayRunStatus.COMPLETED,
                previous_index=2,
                current_index=3,
                receipts=(_receipt(order_index=2, event_id="event-2"),),
                completed=True,
                total_event_count=3,
            ).current_status
            is ReplayRunStatus.COMPLETED
        )

    def test_created_result_history_must_start_at_zero(self) -> None:
        with pytest.raises(ValidationError, match="previous_revision == 0"):
            _result(
                previous_status=ReplayRunStatus.CREATED,
                current_status=ReplayRunStatus.RUNNING,
                previous_revision=7,
                current_revision=8,
                previous_index=0,
                current_index=0,
                receipts=(),
            )
        with pytest.raises(ValidationError, match="previous_next_event_index == 0"):
            _result(
                previous_status=ReplayRunStatus.CREATED,
                current_status=ReplayRunStatus.RUNNING,
                previous_revision=0,
                current_revision=1,
                previous_index=1,
                current_index=1,
                receipts=(),
            )
        with pytest.raises(ValidationError, match="previous_revision == 0"):
            _result(
                previous_status=ReplayRunStatus.CREATED,
                current_status=ReplayRunStatus.COMPLETED,
                previous_revision=7,
                current_revision=8,
                previous_index=0,
                current_index=0,
                receipts=(),
                completed=True,
                total_event_count=0,
            )
        with pytest.raises(ValidationError):
            _result(
                previous_status=ReplayRunStatus.CREATED,
                current_status=ReplayRunStatus.COMPLETED,
                previous_revision=0,
                current_revision=1,
                previous_index=1,
                current_index=1,
                receipts=(),
                completed=True,
                total_event_count=1,
            )

    def test_active_and_paused_result_history_must_be_before_total(self) -> None:
        with pytest.raises(ValidationError, match="previous_next_event_index <"):
            _result(
                previous_status=ReplayRunStatus.RUNNING,
                current_status=ReplayRunStatus.PAUSED,
                previous_revision=2,
                current_revision=3,
                previous_index=3,
                current_index=3,
                receipts=(),
                total_event_count=3,
            )
        with pytest.raises(ValidationError, match="PAUSED result"):
            _result(
                previous_status=ReplayRunStatus.RUNNING,
                current_status=ReplayRunStatus.PAUSED,
                previous_revision=2,
                current_revision=3,
                previous_index=2,
                current_index=3,
                receipts=(_receipt(order_index=2, event_id="event-2"),),
                total_event_count=3,
            )
        with pytest.raises(ValidationError, match="previous_next_event_index <"):
            _result(
                previous_status=ReplayRunStatus.PAUSED,
                current_status=ReplayRunStatus.RUNNING,
                previous_revision=3,
                current_revision=4,
                previous_index=3,
                current_index=3,
                receipts=(),
                total_event_count=3,
            )

    def test_completed_flag_must_match_status(self) -> None:
        with pytest.raises(ValidationError, match="completed"):
            _result(current_status=ReplayRunStatus.COMPLETED, completed=False)


class TestReplayRunStateTransition:
    def test_allowed_transitions_accepted(self) -> None:
        created = _start_state()
        running = _running_state()
        progressed = _running_state(
            revision=2,
            index=1,
            updated_at=_utc(3),
            last_event_id="event-0",
        )
        paused = _paused_state(
            revision=3,
            index=1,
            updated_at=_utc(4),
            last_event_id="event-0",
        )
        resumed = _running_state(
            revision=4,
            index=1,
            updated_at=_utc(5),
            last_event_id="event-0",
        )
        completed = _completed_state(
            revision=3,
            updated_at=_utc(4),
            last_event_id="event-2",
        )
        empty_created = _start_state(total_event_count=0)
        empty_completed = _completed_state(
            revision=1,
            total_event_count=0,
            updated_at=_utc(2),
            last_event_id=None,
        )

        validate_replay_run_state_transition(created, running)
        validate_replay_run_state_transition(running, progressed)
        validate_replay_run_state_transition(progressed, paused)
        validate_replay_run_state_transition(paused, resumed)
        validate_replay_run_state_transition(progressed, completed)
        validate_replay_run_state_transition(empty_created, empty_completed)

    @pytest.mark.parametrize(
        "current",
        [
            _paused_state(revision=1, index=0, updated_at=_utc(2)),
            _state(status=ReplayRunStatus.FAILED, revision=1, updated_at=_utc(2)),
        ],
    )
    def test_created_to_illegal_status_rejected(self, current: ReplayRunState) -> None:
        with pytest.raises(ValueError, match="invalid replay run state transition"):
            validate_replay_run_state_transition(_start_state(), current)

    def test_running_to_created_and_paused_to_completed_rejected(self) -> None:
        with pytest.raises(ValidationError, match="CREATED requires revision"):
            validate_replay_run_state_transition(
                _running_state(),
                _state(status=ReplayRunStatus.CREATED, revision=2, updated_at=_utc(3)),
            )
        with pytest.raises(ValueError, match="invalid replay run state transition"):
            validate_replay_run_state_transition(
                _paused_state(index=1, last_event_id="event-0"),
                _completed_state(revision=3),
            )

    def test_completed_terminal_rejected(self) -> None:
        completed = _completed_state(revision=3)
        with pytest.raises(ValueError, match="invalid replay run state transition"):
            validate_replay_run_state_transition(
                completed,
                _completed_state(revision=4),
            )

    def test_identity_revision_and_time_regression_rejected(self) -> None:
        previous = _running_state()
        with pytest.raises(ValueError, match="identity field"):
            validate_replay_run_state_transition(
                previous,
                _running_state(revision=2).model_copy(update={"timeline_id": "other"}),
            )
        with pytest.raises(ValueError, match="revision"):
            validate_replay_run_state_transition(previous, _running_state(revision=3))
        with pytest.raises(ValueError, match="updated_at"):
            validate_replay_run_state_transition(
                previous,
                _running_state(revision=2, updated_at=_utc(1)),
            )
        with pytest.raises(ValueError, match="identity field"):
            validate_replay_run_state_transition(
                previous,
                _running_state(revision=2).model_copy(update={"total_event_count": 4}),
            )

    def test_started_at_mutation_rejected(self) -> None:
        previous = _running_state()
        current = _running_state(
            revision=2,
            index=1,
            updated_at=_utc(3),
            last_event_id="event-0",
        ).model_copy(update={"started_at": _utc(3)})
        with pytest.raises(ValueError, match="started_at"):
            validate_replay_run_state_transition(previous, current)

    def test_pause_resume_progress_mutation_rejected(self) -> None:
        previous = _running_state(index=1, last_event_id="event-0")
        paused = _paused_state(revision=2, index=2, last_event_id="event-1")
        with pytest.raises(ValueError, match="unchanged next_event_index"):
            validate_replay_run_state_transition(previous, paused)

        previous_paused = _paused_state(index=1, last_event_id="event-0")
        resumed = _running_state(revision=3, index=2, updated_at=_utc(4), last_event_id="event-1")
        with pytest.raises(ValueError, match="unchanged next_event_index"):
            validate_replay_run_state_transition(previous_paused, resumed)

    def test_completion_before_end_rejected(self) -> None:
        previous = _running_state(index=1, last_event_id="event-0")
        with pytest.raises(ValidationError, match="COMPLETED requires next_event_index"):
            current = _state(
                status=ReplayRunStatus.COMPLETED,
                revision=2,
                started_at=_utc(2),
                completed_at=_utc(3),
                updated_at=_utc(3),
                next_event_index=2,
                processed_event_count=2,
                last_processed_event_id="event-1",
            )
            validate_replay_run_state_transition(previous, current)

    def test_progress_requires_last_processed_event_id_to_advance(self) -> None:
        previous = _running_state(index=1, last_event_id="event-0")
        running = _running_state(
            revision=2,
            index=2,
            updated_at=_utc(3),
            last_event_id="event-0",
        )
        with pytest.raises(ValueError, match="last_processed_event_id to advance"):
            validate_replay_run_state_transition(previous, running)

        completing = _completed_state(
            revision=2,
            updated_at=_utc(3),
            last_event_id="event-0",
        )
        with pytest.raises(ValueError, match="last_processed_event_id to advance"):
            validate_replay_run_state_transition(previous, completing)

    def test_progress_accepts_first_and_later_last_processed_event_id_advance(self) -> None:
        first_previous = _running_state(index=0)
        first_current = _running_state(
            revision=2,
            index=1,
            updated_at=_utc(3),
            last_event_id="event-0",
        )
        later_current = _running_state(
            revision=3,
            index=2,
            updated_at=_utc(4),
            last_event_id="event-1",
        )

        validate_replay_run_state_transition(first_previous, first_current)
        validate_replay_run_state_transition(first_current, later_current)
