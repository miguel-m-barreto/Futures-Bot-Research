from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.replay import (
    ReplayDispatchContext,
    ReplayHandlerOutputProposal,
    ReplayInputKind,
    ReplayInstrumentRef,
    ReplayTimelineEvent,
    build_replay_dispatcher_fingerprint,
    build_replay_event_dispatch_receipt_id,
)
from futures_bot.replay.dispatch import LocalDeterministicReplayDispatcher


def _utc() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _event(kind: ReplayInputKind = ReplayInputKind.MARK_PRICE) -> ReplayTimelineEvent:
    return ReplayTimelineEvent(
        event_id="event-1",
        batch_id="batch-1",
        input_dataset_id="input-ds-1",
        record_id="record-1",
        kind=kind,
        instrument=ReplayInstrumentRef(
            venue="binance",
            symbol="BTCUSDT",
            market_type="stablecoin-collateral-futures",
            settlement_asset="USDT",
        ),
        event_time=_utc(),
        source_sequence=0,
        order_index=0,
    )


class _Handler:
    def __init__(
        self,
        handler_id: str,
        *,
        kinds: tuple[ReplayInputKind, ...] = (ReplayInputKind.MARK_PRICE,),
        outputs: tuple[str, ...] = ('{"value":"a"}',),
        fail: bool = False,
    ) -> None:
        self.handler_id = handler_id
        self.handler_version = "1"
        self.supported_event_kinds = kinds
        self.outputs = outputs
        self.fail = fail
        self.calls = 0

    def handle(
        self,
        context: ReplayDispatchContext,
        event: ReplayTimelineEvent,
    ) -> tuple[ReplayHandlerOutputProposal, ...]:
        self.calls += 1
        if self.fail:
            raise ValueError("boom")
        return tuple(
            ReplayHandlerOutputProposal(output_kind="audit", canonical_payload=payload)
            for payload in self.outputs
        )


def _context(
    dispatcher: LocalDeterministicReplayDispatcher,
    event: ReplayTimelineEvent,
) -> ReplayDispatchContext:
    return ReplayDispatchContext(
        run_id="run-1",
        manifest_id="manifest-1",
        replay_plan_id="plan-1",
        timeline_id="timeline-1",
        timeline_fingerprint_id="fp-1",
        dispatcher_fingerprint=dispatcher.dispatcher_fingerprint,
        event_id=event.event_id,
        event_order_index=event.order_index,
        event_time=event.event_time,
        event_kind=event.kind,
    )


def test_duplicate_handler_ids_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        LocalDeterministicReplayDispatcher((_Handler("h"), _Handler("h")))


def test_no_matching_handlers_produces_empty_plan() -> None:
    handler = _Handler("h", kinds=(ReplayInputKind.TRADE,))
    dispatcher = LocalDeterministicReplayDispatcher((handler,))
    event = _event()
    plan = dispatcher.plan_dispatch(
        _context(dispatcher, event),
        event,
        build_replay_event_dispatch_receipt_id("run-1", 0, "event-1"),
    )
    assert plan.handler_ids == ()
    assert plan.output_records == ()
    assert handler.calls == 0


def test_matching_handlers_execute_once_in_deterministic_order() -> None:
    second = _Handler("handler-b", outputs=('{"b":1}',))
    first = _Handler("handler-a", outputs=('{"a":1}', '{"a":2}'))
    dispatcher = LocalDeterministicReplayDispatcher((second, first))
    event = _event()
    plan = dispatcher.plan_dispatch(
        _context(dispatcher, event),
        event,
        build_replay_event_dispatch_receipt_id("run-1", 0, "event-1"),
    )
    assert plan.handler_ids == ("handler-a", "handler-b")
    assert [record.handler_id for record in plan.output_records] == [
        "handler-a",
        "handler-a",
        "handler-b",
    ]
    assert [record.handler_output_index for record in plan.output_records] == [0, 1, 0]
    assert first.calls == 1
    assert second.calls == 1


def test_empty_registry_has_stable_fingerprint() -> None:
    first = LocalDeterministicReplayDispatcher(())
    second = LocalDeterministicReplayDispatcher(())
    assert first.dispatcher_fingerprint == second.dispatcher_fingerprint
    assert first.dispatcher_fingerprint == build_replay_dispatcher_fingerprint(())


def test_selected_descriptors_are_exact_and_deterministic() -> None:
    handler_b = _Handler("handler-b", outputs=())
    handler_a = _Handler("handler-a", outputs=())
    unsupported = _Handler(
        "handler-z",
        kinds=(ReplayInputKind.TRADE,),
        outputs=(),
    )
    dispatcher = LocalDeterministicReplayDispatcher((handler_b, unsupported, handler_a))
    selected = dispatcher.selected_descriptors_for(ReplayInputKind.MARK_PRICE)
    assert [descriptor.handler_id for descriptor in selected] == [
        "handler-a",
        "handler-b",
    ]
    assert [descriptor.handler_version for descriptor in selected] == ["1", "1"]
    assert dispatcher.selected_descriptors_for(ReplayInputKind.FUNDING_RATE) == ()
    assert LocalDeterministicReplayDispatcher(()).selected_descriptors_for(
        ReplayInputKind.MARK_PRICE
    ) == ()


def test_registry_fingerprint_recomputes_from_exposed_descriptors() -> None:
    dispatcher = LocalDeterministicReplayDispatcher((_Handler("handler-a"),))
    assert build_replay_dispatcher_fingerprint(dispatcher.descriptors) == (
        dispatcher.dispatcher_fingerprint
    )


def test_invalid_context_and_handler_failures_are_rejected() -> None:
    handler = _Handler("handler-a")
    dispatcher = LocalDeterministicReplayDispatcher((handler,))
    event = _event()
    context = _context(dispatcher, event).model_copy(update={"event_id": "other"})
    with pytest.raises(ValueError, match="event_id"):
        dispatcher.plan_dispatch(
            context,
            event,
            build_replay_event_dispatch_receipt_id("run-1", 0, "event-1"),
        )

    failing = LocalDeterministicReplayDispatcher((_Handler("handler-a", fail=True),))
    with pytest.raises(RuntimeError, match="failed"):
        failing.plan_dispatch(
            _context(failing, event),
            event,
            build_replay_event_dispatch_receipt_id("run-1", 0, "event-1"),
        )


def test_mismatching_dispatch_receipt_id_rejected_before_handler_call() -> None:
    handler = _Handler("handler-a")
    dispatcher = LocalDeterministicReplayDispatcher((handler,))
    event = _event()
    with pytest.raises(ValueError, match="dispatch_receipt_id"):
        dispatcher.plan_dispatch(
            _context(dispatcher, event),
            event,
            "replay-dispatch:" + "0" * 64,
        )
    assert handler.calls == 0


def test_tampered_context_revalidated_before_handler_call() -> None:
    handler = _Handler("handler-a")
    dispatcher = LocalDeterministicReplayDispatcher((handler,))
    event = _event()
    context = _context(dispatcher, event).model_copy(update={"run_id": "   "})
    with pytest.raises(ValidationError, match="run_id"):
        dispatcher.plan_dispatch(
            context,
            event,
            build_replay_event_dispatch_receipt_id("run-1", 0, "event-1"),
        )
    assert handler.calls == 0


def test_invalid_proposal_is_rejected() -> None:
    handler = _Handler("handler-a")
    dispatcher = LocalDeterministicReplayDispatcher((handler,))
    event = _event()

    def invalid_handle(
        context: ReplayDispatchContext,
        handled_event: ReplayTimelineEvent,
    ) -> tuple[ReplayHandlerOutputProposal, ...]:
        return (
            ReplayHandlerOutputProposal.model_construct(
                output_kind="audit",
                canonical_payload='{"float":1.2}',
            ),
        )

    handler.handle = invalid_handle  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="handler-a"):
        dispatcher.plan_dispatch(
            _context(dispatcher, event),
            event,
            build_replay_event_dispatch_receipt_id("run-1", 0, "event-1"),
        )
