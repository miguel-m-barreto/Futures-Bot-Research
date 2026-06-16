from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.replay import (
    ReplayEventOutputRecord,
    ReplayInputKind,
    build_replay_dispatcher_fingerprint,
    build_replay_event_dispatch_receipt_id,
    build_replay_event_output_record_id,
)
from futures_bot.infrastructure.replay.in_memory import (
    InMemoryReplayEventOutputRecordStore,
)
from futures_bot.ports.replay import ReplayEventOutputRecordStorePort


def _utc() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


DISPATCHER_FINGERPRINT = build_replay_dispatcher_fingerprint(())


def _record(  # noqa: PLR0913 - compact output record fixture
    *,
    run_id: str = "run-1",
    event_order_index: int = 0,
    event_id: str = "event-0",
    handler_id: str = "handler-a",
    handler_version: str = "1",
    handler_output_index: int = 0,
    payload: str = '{"value":"a"}',
) -> ReplayEventOutputRecord:
    payload_sha256 = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return ReplayEventOutputRecord(
        output_record_id=build_replay_event_output_record_id(
            run_id=run_id,
            event_order_index=event_order_index,
            event_id=event_id,
            handler_id=handler_id,
            handler_version=handler_version,
            handler_output_index=handler_output_index,
            output_kind="audit",
            payload_sha256=payload_sha256,
        ),
        dispatch_receipt_id=build_replay_event_dispatch_receipt_id(
            run_id,
            event_order_index,
            event_id,
        ),
        run_id=run_id,
        manifest_id="manifest-1",
        replay_plan_id="plan-1",
        timeline_id="timeline-1",
        timeline_fingerprint_id="fp-1",
        dispatcher_fingerprint=DISPATCHER_FINGERPRINT,
        event_id=event_id,
        event_order_index=event_order_index,
        event_time=_utc(),
        event_kind=ReplayInputKind.MARK_PRICE,
        handler_id=handler_id,
        handler_version=handler_version,
        handler_output_index=handler_output_index,
        output_kind="audit",
        canonical_payload=payload,
        payload_sha256=payload_sha256,
    )


def test_conforms_to_port() -> None:
    _: ReplayEventOutputRecordStorePort = InMemoryReplayEventOutputRecordStore()


def test_save_load_idempotent_and_conflicting_duplicate() -> None:
    store = InMemoryReplayEventOutputRecordStore()
    record = _record()
    store.save(record)
    store.save(record)
    assert store.load(record.output_record_id) == record

    conflict = record.model_copy(update={"manifest_id": "manifest-other"})
    with pytest.raises(ValueError, match="conflict"):
        store.save(conflict)


def test_model_copy_tampering_rejected() -> None:
    store = InMemoryReplayEventOutputRecordStore()
    tampered = _record().model_copy(update={"handler_output_index": "0"})
    with pytest.raises((ValidationError, ValueError)):
        store.save(tampered)


def test_wrong_dispatch_receipt_link_rejected() -> None:
    store = InMemoryReplayEventOutputRecordStore()
    tampered = _record().model_copy(
        update={"dispatch_receipt_id": "replay-dispatch:" + "1" * 64}
    )
    with pytest.raises((ValidationError, ValueError), match="dispatch_receipt_id"):
        store.save(tampered)


def test_deterministic_run_event_and_all_ordering() -> None:
    store = InMemoryReplayEventOutputRecordStore()
    event_1_handler_b = _record(
        event_order_index=1,
        event_id="event-1",
        handler_id="handler-b",
    )
    event_0_handler_b = _record(
        event_order_index=0,
        event_id="event-0",
        handler_id="handler-b",
    )
    event_0_handler_a_1 = _record(
        event_order_index=0,
        event_id="event-0",
        handler_id="handler-a",
        handler_output_index=1,
        payload='{"value":"b"}',
    )
    event_0_handler_a_0 = _record(
        event_order_index=0,
        event_id="event-0",
        handler_id="handler-a",
        handler_output_index=0,
    )
    other_run = _record(run_id="run-0")
    for record in (
        event_1_handler_b,
        event_0_handler_b,
        event_0_handler_a_1,
        event_0_handler_a_0,
        other_run,
    ):
        store.save(record)

    assert store.list_for_event("run-1", 0) == (
        event_0_handler_a_0,
        event_0_handler_a_1,
        event_0_handler_b,
    )
    assert store.list_for_run("run-1") == (
        event_0_handler_a_0,
        event_0_handler_a_1,
        event_0_handler_b,
        event_1_handler_b,
    )
    assert store.list_all()[0] == other_run
