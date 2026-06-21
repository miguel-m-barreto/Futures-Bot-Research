from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from futures_bot.domain.ids import (
    ClientOrderId,
    ExecutionOrderRecordId,
    FillReportId,
    VenueOrderId,
)
from futures_bot.domain.order_lifecycle import (
    CancelOrderIntent,
    CancelScope,
    ExecutionOrderRecord,
    FillReport,
    OrderIntent,
    OrderIntentKind,
    OrderLifecycleEvent,
    OrderLifecycleEventKind,
    OrderLifecycleState,
    OrderSide,
    OrderType,
    PositionSide,
    ReplaceOrderIntent,
    TimeInForce,
    canonical_payload_hash,
)
from futures_bot.domain.runtime_control import OrderFlowPermissionReason

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _order_intent(  # noqa: PLR0913
    *,
    intent_kind: OrderIntentKind = OrderIntentKind.ENTRY,
    order_type: OrderType = OrderType.MARKET,
    quantity: str | None = "1",
    limit_price: str | None = None,
    stop_price: str | None = None,
    reduce_only: bool = False,
    post_only: bool = False,
    close_position: bool = False,
    time_in_force: TimeInForce | None = None,
    expires_at: datetime | None = None,
) -> OrderIntent:
    return OrderIntent(
        intent_kind=intent_kind,
        venue_id="venue-1",
        instrument_id="BTC-PERP",
        account_id="acct-1",
        side=OrderSide.BUY,
        position_side=PositionSide.LONG,
        order_type=order_type,
        time_in_force=time_in_force,
        quantity=quantity,
        limit_price=limit_price,
        stop_price=stop_price,
        reduce_only=reduce_only,
        post_only=post_only,
        close_position=close_position,
        expires_at=expires_at,
        permission_reason=OrderFlowPermissionReason.OK,
        created_at=NOW,
    )


def _reduce_intent(**overrides: object) -> OrderIntent:
    kwargs = {
        "intent_kind": OrderIntentKind.REDUCE_ONLY,
        "reduce_only": True,
    }
    kwargs.update(overrides)
    return _order_intent(**kwargs)


def test_order_intent_deterministic_intent_id_client_order_id_idempotency_key() -> None:
    first = _order_intent()
    second = _order_intent()

    assert first.intent_id == second.intent_id
    assert first.client_order_id == second.client_order_id
    assert first.idempotency_key == second.idempotency_key


def test_entry_cannot_be_reduce_only() -> None:
    with pytest.raises(ValidationError, match="ENTRY must not be reduce_only"):
        _order_intent(reduce_only=True)


def test_entry_cannot_close_position() -> None:
    with pytest.raises(ValidationError, match="ENTRY must not be close_position"):
        _order_intent(quantity=None, close_position=True)


def test_reduce_only_must_be_reduce_only() -> None:
    with pytest.raises(ValidationError, match="reduce/protective intents"):
        _order_intent(intent_kind=OrderIntentKind.REDUCE_ONLY, reduce_only=False)


def test_emergency_close_must_be_reduce_only_or_close_position() -> None:
    with pytest.raises(ValidationError, match="EMERGENCY_CLOSE"):
        _order_intent(intent_kind=OrderIntentKind.EMERGENCY_CLOSE)


def test_market_cannot_be_post_only() -> None:
    with pytest.raises(ValidationError, match="post_only cannot be used with MARKET"):
        _order_intent(post_only=True)


def test_limit_requires_limit_price() -> None:
    with pytest.raises(ValidationError, match="require limit_price"):
        _order_intent(order_type=OrderType.LIMIT)


def test_stop_market_requires_stop_price() -> None:
    with pytest.raises(ValidationError, match="require stop_price"):
        _order_intent(order_type=OrderType.STOP_MARKET)


def test_take_profit_limit_requires_stop_price_and_limit_price() -> None:
    with pytest.raises(ValidationError, match="require stop_price"):
        _reduce_intent(order_type=OrderType.TAKE_PROFIT_LIMIT, limit_price="101")
    with pytest.raises(ValidationError, match="TAKE_PROFIT_LIMIT requires limit_price"):
        _reduce_intent(order_type=OrderType.TAKE_PROFIT_LIMIT, stop_price="100")


def test_gtd_requires_expires_at() -> None:
    with pytest.raises(ValidationError, match="GTD requires expires_at"):
        _order_intent(time_in_force=TimeInForce.GTD)

    intent = _order_intent(
        time_in_force=TimeInForce.GTD,
        expires_at=NOW + timedelta(minutes=5),
    )
    assert intent.expires_at == NOW + timedelta(minutes=5)


def test_cancel_order_intent_single_order_target_required() -> None:
    with pytest.raises(ValidationError, match="single-order cancel requires"):
        CancelOrderIntent(
            venue_id="venue-1",
            instrument_id="BTC-PERP",
            account_id="acct-1",
            cancel_scope=CancelScope.SINGLE_ORDER,
            cancel_reason="operator requested cancel",
            created_at=NOW,
        )


def test_replace_order_intent_target_required() -> None:
    replacement = _reduce_intent()
    with pytest.raises(ValidationError, match="replace target is required"):
        ReplaceOrderIntent(
            target_intent_kind=OrderIntentKind.REDUCE_ONLY,
            replacement_order=replacement,
            replace_reason="move stop",
            created_at=NOW,
        )


def test_replace_order_intent_requires_target_intent_kind() -> None:
    replacement = _reduce_intent()
    with pytest.raises(ValidationError, match="target_intent_kind"):
        ReplaceOrderIntent(
            target_client_order_id=ClientOrderId("client-reduce-1"),
            replacement_order=replacement,
            replace_reason="move stop",
            created_at=NOW,
        )


def test_replace_order_intent_entry_target_requires_entry_replacement() -> None:
    replacement = _reduce_intent()
    with pytest.raises(ValidationError, match="ENTRY target requires ENTRY"):
        ReplaceOrderIntent(
            target_client_order_id=ClientOrderId("client-entry-1"),
            target_intent_kind=OrderIntentKind.ENTRY,
            replacement_order=replacement,
            replace_reason="unsafe replace",
            created_at=NOW,
        )


def test_replace_order_intent_non_entry_target_rejects_entry_replacement() -> None:
    entry = _order_intent()
    assert entry.client_order_id is not None
    with pytest.raises(ValidationError, match="non-entry target must not become ENTRY"):
        ReplaceOrderIntent(
            target_client_order_id=ClientOrderId("client-protective-1"),
            target_intent_kind=OrderIntentKind.PROTECTIVE_STOP,
            replacement_order=entry,
            replace_reason="unsafe replace",
            created_at=NOW,
        )


def test_execution_order_record_fill_quantities_validate() -> None:
    intent = _order_intent(quantity="2")
    assert intent.client_order_id is not None
    record = ExecutionOrderRecord(
        record_id=ExecutionOrderRecordId("record-1"),
        order_intent=intent,
        lifecycle_state=OrderLifecycleState.PARTIALLY_FILLED,
        client_order_id=intent.client_order_id,
        cumulative_filled_quantity=Decimal("1.25"),
        remaining_quantity=Decimal("0.75"),
        average_fill_price=Decimal("100"),
        created_at=NOW,
        updated_at=NOW,
    )
    assert record.cumulative_filled_quantity == Decimal("1.25")

    with pytest.raises(ValidationError, match="filled \\+ remaining"):
        ExecutionOrderRecord(
            record_id=ExecutionOrderRecordId("record-2"),
            order_intent=intent,
            lifecycle_state=OrderLifecycleState.PARTIALLY_FILLED,
            client_order_id=intent.client_order_id,
            cumulative_filled_quantity=Decimal("1.25"),
            remaining_quantity=Decimal("0.5"),
            created_at=NOW,
            updated_at=NOW,
        )


def test_fill_report_quantity_price_validate() -> None:
    with pytest.raises(ValidationError, match="fill_quantity must be > 0"):
        FillReport(
            fill_report_id=FillReportId("fill-1"),
            record_id=ExecutionOrderRecordId("record-1"),
            client_order_id=ClientOrderId("client-1"),
            venue_order_id=VenueOrderId("venue-order-1"),
            fill_quantity=Decimal("0"),
            fill_price=Decimal("100"),
            occurred_at=NOW,
        )

    with pytest.raises(ValidationError, match="fill_price must be > 0"):
        FillReport(
            fill_report_id=FillReportId("fill-2"),
            record_id=ExecutionOrderRecordId("record-1"),
            client_order_id=ClientOrderId("client-1"),
            fill_quantity=Decimal("1"),
            fill_price=Decimal("0"),
            occurred_at=NOW,
        )


def test_order_lifecycle_event_payload_hash_validation() -> None:
    intent = _order_intent()
    assert intent.client_order_id is not None
    payload = {"status": "created"}
    event = OrderLifecycleEvent(
        client_order_id=intent.client_order_id,
        event_kind=OrderLifecycleEventKind.INTENT_CREATED,
        previous_state=None,
        next_state=OrderLifecycleState.CREATED,
        occurred_at=NOW,
        payload=payload,
        payload_hash=canonical_payload_hash(payload),
    )
    assert event.event_id is not None

    with pytest.raises(ValidationError, match="payload_hash does not match"):
        OrderLifecycleEvent(
            client_order_id=intent.client_order_id,
            event_kind=OrderLifecycleEventKind.INTENT_CREATED,
            previous_state=None,
            next_state=OrderLifecycleState.CREATED,
            occurred_at=NOW,
            payload=payload,
            payload_hash="0" * 64,
        )
