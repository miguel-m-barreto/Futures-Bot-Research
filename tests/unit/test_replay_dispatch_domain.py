from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.replay import (
    ReplayDispatchContext,
    ReplayDispatchHandlerDescriptor,
    ReplayEventDispatchPlan,
    ReplayEventOutputRecord,
    ReplayHandlerOutputProposal,
    ReplayInputKind,
    build_replay_dispatcher_fingerprint,
    build_replay_event_dispatch_receipt_id,
    build_replay_event_output_record_id,
)


def _utc() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _descriptor(
    handler_id: str = "handler-a",
    *,
    version: str = "1",
    kinds: tuple[ReplayInputKind, ...] = (ReplayInputKind.MARK_PRICE,),
) -> ReplayDispatchHandlerDescriptor:
    return ReplayDispatchHandlerDescriptor(
        handler_id=handler_id,
        handler_version=version,
        supported_event_kinds=kinds,
    )


def _context() -> ReplayDispatchContext:
    return ReplayDispatchContext(
        run_id="run-1",
        manifest_id="manifest-1",
        replay_plan_id="plan-1",
        timeline_id="timeline-1",
        timeline_fingerprint_id="fp-1",
        dispatcher_fingerprint=build_replay_dispatcher_fingerprint((_descriptor(),)),
        event_id="event-1",
        event_order_index=0,
        event_time=_utc(),
        event_kind=ReplayInputKind.MARK_PRICE,
    )


def _record(  # noqa: PLR0913 - compact output record fixture
    *,
    context: ReplayDispatchContext | None = None,
    handler_id: str = "handler-a",
    handler_version: str = "1",
    handler_output_index: int = 0,
    output_kind: str = "audit",
    payload: str = '{"price":"123.4500"}',
) -> ReplayEventOutputRecord:
    if context is None:
        context = _context()
    payload_sha256 = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return ReplayEventOutputRecord(
        output_record_id=build_replay_event_output_record_id(
            run_id=context.run_id,
            event_order_index=context.event_order_index,
            event_id=context.event_id,
            handler_id=handler_id,
            handler_version=handler_version,
            handler_output_index=handler_output_index,
            output_kind=output_kind,
            payload_sha256=payload_sha256,
        ),
        dispatch_receipt_id=build_replay_event_dispatch_receipt_id(
            context.run_id,
            context.event_order_index,
            context.event_id,
        ),
        run_id=context.run_id,
        manifest_id=context.manifest_id,
        replay_plan_id=context.replay_plan_id,
        timeline_id=context.timeline_id,
        timeline_fingerprint_id=context.timeline_fingerprint_id,
        dispatcher_fingerprint=context.dispatcher_fingerprint,
        event_id=context.event_id,
        event_order_index=context.event_order_index,
        event_time=context.event_time,
        event_kind=context.event_kind,
        handler_id=handler_id,
        handler_version=handler_version,
        handler_output_index=handler_output_index,
        output_kind=output_kind,
        canonical_payload=payload,
        payload_sha256=payload_sha256,
    )


def test_handler_descriptor_validation() -> None:
    assert _descriptor().handler_id == "handler-a"
    with pytest.raises(ValidationError, match="supported_event_kinds"):
        _descriptor(kinds=())
    with pytest.raises(ValidationError, match="duplicate"):
        _descriptor(kinds=(ReplayInputKind.MARK_PRICE, ReplayInputKind.MARK_PRICE))
    with pytest.raises(ValidationError, match="sorted"):
        _descriptor(kinds=(ReplayInputKind.TRADE, ReplayInputKind.MARK_PRICE))


def test_dispatcher_fingerprint_is_stable_and_changes_with_semantics() -> None:
    first = _descriptor("handler-a", version="1")
    second = _descriptor("handler-b", version="1")
    assert build_replay_dispatcher_fingerprint((second, first)) == (
        build_replay_dispatcher_fingerprint((first, second))
    )
    assert build_replay_dispatcher_fingerprint(()) == build_replay_dispatcher_fingerprint(())
    assert build_replay_dispatcher_fingerprint((first,)) != (
        build_replay_dispatcher_fingerprint((_descriptor("handler-a", version="2"),))
    )
    assert build_replay_dispatcher_fingerprint((first,)) != (
        build_replay_dispatcher_fingerprint(
            (_descriptor("handler-a", kinds=(ReplayInputKind.TRADE,)),)
        )
    )
    with pytest.raises(ValueError, match="unique"):
        build_replay_dispatcher_fingerprint((first, first))


def test_handler_output_payload_validation() -> None:
    assert ReplayHandlerOutputProposal(
        output_kind="audit",
        canonical_payload='{"price":"123.4500","quantity":"0.0100"}',
    )
    with pytest.raises(ValidationError, match="canonical"):
        ReplayHandlerOutputProposal(output_kind="audit", canonical_payload='{ "a": 1 }')
    with pytest.raises(ValidationError, match="top-level"):
        ReplayHandlerOutputProposal(output_kind="audit", canonical_payload='["x"]')
    with pytest.raises(ValidationError, match="float"):
        ReplayHandlerOutputProposal(output_kind="audit", canonical_payload='{"a":[1.2]}')


def test_output_record_hash_and_deterministic_id_validation() -> None:
    record = _record()
    assert record.payload_sha256 == hashlib.sha256(
        record.canonical_payload.encode("utf-8")
    ).hexdigest()
    tampered_hash = record.model_copy(update={"payload_sha256": "0" * 64})
    with pytest.raises(ValidationError, match="payload_sha256"):
        ReplayEventOutputRecord.model_validate(tampered_hash.model_dump())
    tampered_id = record.model_copy(update={"output_record_id": "replay-output:" + "1" * 64})
    with pytest.raises(ValidationError, match="output_record_id"):
        ReplayEventOutputRecord.model_validate(tampered_id.model_dump())


def test_output_record_dispatch_receipt_id_must_be_deterministic() -> None:
    record = _record()
    assert record.dispatch_receipt_id == build_replay_event_dispatch_receipt_id(
        record.run_id,
        record.event_order_index,
        record.event_id,
    )
    for wrong_receipt_id in (
        "not-a-receipt",
        build_replay_event_dispatch_receipt_id("other-run", 0, "event-1"),
    ):
        tampered = record.model_copy(update={"dispatch_receipt_id": wrong_receipt_id})
        with pytest.raises(ValidationError, match="dispatch_receipt_id"):
            ReplayEventOutputRecord.model_validate(tampered.model_dump())


def test_output_record_id_is_delimiter_safe() -> None:
    first = build_replay_event_output_record_id(
        run_id="a",
        event_order_index=1,
        event_id="2:b",
        handler_id="h",
        handler_version="1",
        handler_output_index=0,
        output_kind="x",
        payload_sha256="0" * 64,
    )
    second = build_replay_event_output_record_id(
        run_id="a:1",
        event_order_index=2,
        event_id="b",
        handler_id="h",
        handler_version="1",
        handler_output_index=0,
        output_kind="x",
        payload_sha256="0" * 64,
    )
    assert first != second


def test_dispatch_plan_validates_context_order_and_indexes() -> None:
    context = _context()
    first = _record(context=context, handler_output_index=0)
    second = _record(context=context, handler_output_index=1, payload='{"x":1}')
    plan = ReplayEventDispatchPlan(
        context=context,
        handler_ids=("handler-a",),
        output_records=(first, second),
    )
    assert [record.handler_output_index for record in plan.output_records] == [0, 1]

    mismatch_context = context.model_copy(update={"event_id": "other"})
    mismatch = _record(context=mismatch_context)
    with pytest.raises(ValidationError, match="event_id"):
        ReplayEventDispatchPlan(
            context=context,
            handler_ids=("handler-a",),
            output_records=(mismatch,),
        )
    gap = _record(context=context, handler_output_index=2, payload='{"x":2}')
    with pytest.raises(ValidationError, match="contiguous"):
        ReplayEventDispatchPlan(
            context=context,
            handler_ids=("handler-a",),
            output_records=(first, gap),
        )
    with pytest.raises(ValidationError, match="duplicate"):
        ReplayEventDispatchPlan(
            context=context,
            handler_ids=("handler-a",),
            output_records=(first, first),
        )


def test_dispatch_plan_fully_revalidates_nested_context_and_records() -> None:
    context = _context()
    record = _record(context=context)
    ReplayEventDispatchPlan(context=context, handler_ids=("handler-a",), output_records=(record,))

    bad_context = context.model_copy(update={"run_id": "   "})
    with pytest.raises(ValidationError, match="run_id"):
        ReplayEventDispatchPlan(context=bad_context, handler_ids=(), output_records=())

    bad_fingerprint = context.model_copy(update={"dispatcher_fingerprint": "bad"})
    with pytest.raises(ValidationError, match="dispatcher_fingerprint"):
        ReplayEventDispatchPlan(
            context=bad_fingerprint,
            handler_ids=(),
            output_records=(),
        )

    bad_receipt = record.model_copy(update={"dispatch_receipt_id": "replay-dispatch:" + "1" * 64})
    with pytest.raises(ValidationError, match="dispatch_receipt_id"):
        ReplayEventDispatchPlan(
            context=context,
            handler_ids=("handler-a",),
            output_records=(bad_receipt,),
        )

    bad_payload = record.model_copy(update={"canonical_payload": '{"float":1.2}'})
    with pytest.raises(ValidationError, match=r"canonical_payload|float|payload_sha256"):
        ReplayEventDispatchPlan(
            context=context,
            handler_ids=("handler-a",),
            output_records=(bad_payload,),
        )

    bad_hash = record.model_copy(update={"payload_sha256": "0" * 64})
    with pytest.raises(ValidationError, match="payload_sha256"):
        ReplayEventDispatchPlan(
            context=context,
            handler_ids=("handler-a",),
            output_records=(bad_hash,),
        )

    bad_id = record.model_copy(update={"output_record_id": "replay-output:" + "1" * 64})
    with pytest.raises(ValidationError, match="output_record_id"):
        ReplayEventDispatchPlan(
            context=context,
            handler_ids=("handler-a",),
            output_records=(bad_id,),
        )
