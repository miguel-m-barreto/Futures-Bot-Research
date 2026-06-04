from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from futures_bot.domain.events import (
    EventEnvelope,
    EventType,
    OrderFillReceivedPayload,
    OrderRejectedPayload,
    OrderSubmitAttemptedPayload,
    RecoveryAdoptCompletedPayload,
    RecoveryAdoptStartedPayload,
)
from futures_bot.domain.execution import OrderSide, OrderType
from futures_bot.domain.ids import (
    BotId,
    EventId,
    ExchangeOrderId,
    ExecutionIntentId,
    FillId,
    InstrumentId,
    OrderIntentId,
    RunId,
)


def test_valid_event_creation_and_payload_default() -> None:
    event = EventEnvelope(
        event_id=EventId("event-1"),
        event_type=EventType.BOT_CREATED,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        bot_id=BotId("bot-1"),
        schema_version="v1",
    )

    assert event.payload == {}
    assert event.local_sequence is None


def test_empty_schema_version_rejected() -> None:
    with pytest.raises(ValidationError, match="schema_version"):
        EventEnvelope(
            event_id=EventId("event-1"),
            event_type=EventType.BOT_CREATED,
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            schema_version="",
        )


def test_negative_local_sequence_rejected() -> None:
    with pytest.raises(ValidationError, match="local_sequence"):
        EventEnvelope(
            event_id=EventId("event-1"),
            event_type=EventType.BOT_CREATED,
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            schema_version="v1",
            local_sequence=-1,
        )


def test_naive_occurred_at_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        EventEnvelope(
            event_id=EventId("event-1"),
            event_type=EventType.BOT_CREATED,
            occurred_at=datetime(2026, 1, 1),
            schema_version="v1",
        )


def test_payload_accepts_dict_safely() -> None:
    payload = {"note": "created"}
    event = EventEnvelope(
        event_id=EventId("event-1"),
        event_type=EventType.BOT_CREATED,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        schema_version="v1",
        payload=payload,
    )

    payload["note"] = "mutated outside"
    assert event.payload == {"note": "created"}


def _attempted_at() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _order_submit_payload(**overrides: object) -> dict[str, object]:
    payload = {
        "execution_intent_id": ExecutionIntentId("execution-intent-1"),
        "order_intent_id": OrderIntentId("order-intent-1"),
        "client_order_id": "client-order-1",
        "instrument_id": InstrumentId("BTC-USDT-PERP"),
        "side": OrderSide.BUY,
        "order_type": OrderType.MARKET,
        "quantity": "0.25",
        "reduce_only": False,
        "attempted_at": _attempted_at(),
    }
    payload.update(overrides)
    return payload


def _typed_event(payload: dict[str, object] | OrderSubmitAttemptedPayload | None) -> EventEnvelope:
    return EventEnvelope(
        event_id=EventId("event-typed-1"),
        event_type=EventType.ORDER_SUBMIT_ATTEMPTED,
        occurred_at=_attempted_at(),
        schema_version="v1",
        payload=payload,
    )


@pytest.mark.parametrize(
    "event_type",
    [
        EventType.EXECUTION_INTENT_CREATED,
        EventType.ORDER_SUBMIT_ATTEMPTED,
        EventType.ORDER_ACCEPTED,
        EventType.ORDER_REJECTED,
        EventType.ORDER_FILL_RECEIVED,
        EventType.ORDER_CANCEL_REQUESTED,
        EventType.ORDER_CANCELLED,
        EventType.ORDER_EXPIRED,
        EventType.WAL_REPLAY_STARTED,
        EventType.WAL_REPLAY_COMPLETED,
        EventType.RECOVERY_ADOPT_STARTED,
        EventType.RECOVERY_ADOPT_COMPLETED,
        EventType.RECOVERY_ADOPT_FAILED,
    ],
)
def test_new_event_type_values_exist(event_type: EventType) -> None:
    assert EventType(event_type.value) is event_type


def test_order_submit_attempted_payload_validates_valid_payload() -> None:
    payload = OrderSubmitAttemptedPayload(**_order_submit_payload())

    assert payload.quantity == Decimal("0.25")
    assert payload.attempted_at == _attempted_at()


def test_order_submit_attempted_payload_rejects_market_with_limit_price() -> None:
    with pytest.raises(ValidationError, match="MARKET order"):
        OrderSubmitAttemptedPayload(**_order_submit_payload(limit_price="100"))


def test_order_submit_attempted_payload_rejects_limit_without_limit_price() -> None:
    with pytest.raises(ValidationError, match="LIMIT order"):
        OrderSubmitAttemptedPayload(
            **_order_submit_payload(order_type=OrderType.LIMIT),
        )


def test_order_rejected_payload_rejects_blank_reason() -> None:
    with pytest.raises(ValidationError, match="reason"):
        OrderRejectedPayload(
            order_intent_id=OrderIntentId("order-intent-1"),
            rejected_at=_attempted_at(),
            reason=" ",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("filled_quantity", "0"), ("fill_price", "0")],
)
def test_order_fill_received_payload_rejects_non_positive_fill_values(
    field: str,
    value: str,
) -> None:
    payload = {
        "order_intent_id": OrderIntentId("order-intent-1"),
        "exchange_order_id": ExchangeOrderId("exchange-order-1"),
        "fill_id": FillId("fill-1"),
        "filled_quantity": "0.25",
        "fill_price": "100",
        "received_at": _attempted_at(),
        field: value,
    }

    with pytest.raises(ValidationError, match=field):
        OrderFillReceivedPayload(**payload)


def test_recovery_adopt_started_payload_rejects_same_run_ids() -> None:
    with pytest.raises(ValidationError, match="adopting_run_id"):
        RecoveryAdoptStartedPayload(
            adopting_run_id=RunId("run-1"),
            predecessor_run_id=RunId("run-1"),
            started_at=_attempted_at(),
            reason="recovering after restart",
        )


def test_recovery_adopt_completed_payload_rejects_negative_counts() -> None:
    with pytest.raises(ValidationError, match="adoption counts"):
        RecoveryAdoptCompletedPayload(
            adopting_run_id=RunId("run-2"),
            predecessor_run_id=RunId("run-1"),
            completed_at=_attempted_at(),
            adopted_positions_count=-1,
            adopted_open_orders_count=0,
        )


def test_event_envelope_rejects_missing_payload_for_typed_event() -> None:
    with pytest.raises(ValidationError, match="ORDER_SUBMIT_ATTEMPTED"):
        EventEnvelope(
            event_id=EventId("event-typed-1"),
            event_type=EventType.ORDER_SUBMIT_ATTEMPTED,
            occurred_at=_attempted_at(),
            schema_version="v1",
        )


def test_event_envelope_rejects_extra_fields_for_typed_payload_event() -> None:
    with pytest.raises(ValidationError, match="extra"):
        _typed_event({**_order_submit_payload(), "unexpected": "field"})


def test_event_envelope_accepts_typed_payload_model_instance() -> None:
    payload = OrderSubmitAttemptedPayload(**_order_submit_payload())
    event = _typed_event(payload)

    assert event.payload["quantity"] == "0.25"
    assert event.payload["attempted_at"] == "2026-01-01T00:00:00Z"


def test_event_envelope_accepts_valid_payload_dict() -> None:
    event = _typed_event(_order_submit_payload())

    assert event.payload["client_order_id"] == "client-order-1"
    assert event.payload["order_type"] == "MARKET"


def test_legacy_event_types_still_accept_generic_payload_behavior() -> None:
    event = EventEnvelope(
        event_id=EventId("event-legacy-1"),
        event_type=EventType.BOT_CREATED,
        occurred_at=_attempted_at(),
        schema_version="v1",
        payload={"arbitrary": {"nested": "value"}},
    )

    assert event.payload == {"arbitrary": {"nested": "value"}}
