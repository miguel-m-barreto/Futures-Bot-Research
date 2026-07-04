from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.assets import AssetAmount, AssetSymbol
from futures_bot.domain.execution import (
    ExecutionIntent,
    ExecutionIntentStatus,
    OrderIntent,
    OrderSide,
    OrderType,
)
from futures_bot.domain.ids import (
    BotId,
    DecisionIntentId,
    ExecutionIntentId,
    InstrumentId,
    OrderIntentId,
    RunId,
)


def _created_at() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _order_intent(**overrides: object) -> OrderIntent:
    data = {
        "order_intent_id": OrderIntentId("order-intent-1"),
        "instrument_id": InstrumentId("BTC-USDT-PERP"),
        "side": OrderSide.BUY,
        "order_type": OrderType.MARKET,
        "quantity": "0.25",
        "client_order_id": "client-order-1",
    }
    data.update(overrides)
    return OrderIntent(**data)


def _execution_intent(**overrides: object) -> ExecutionIntent:
    data = {
        "execution_intent_id": ExecutionIntentId("execution-intent-1"),
        "run_id": RunId("run-1"),
        "bot_id": BotId("bot-1"),
        "decision_intent_id": DecisionIntentId("decision-intent-1"),
        "order_intent": _order_intent(),
        "margin_asset": "USDT",
        "max_margin": AssetAmount(asset="USDT", amount="25"),
        "created_at": _created_at(),
    }
    data.update(overrides)
    return ExecutionIntent(**data)


def test_order_intent_market_rejects_limit_price() -> None:
    with pytest.raises(ValidationError, match="MARKET order"):
        _order_intent(limit_price="100")


def test_order_intent_limit_requires_positive_limit_price() -> None:
    with pytest.raises(ValidationError, match="LIMIT order"):
        _order_intent(order_type=OrderType.LIMIT)

    with pytest.raises(ValidationError, match="limit_price"):
        _order_intent(order_type=OrderType.LIMIT, limit_price="0")


def test_order_intent_rejects_non_positive_quantity() -> None:
    with pytest.raises(ValidationError, match="quantity"):
        _order_intent(quantity="0")


def test_order_intent_rejects_blank_client_order_id() -> None:
    with pytest.raises(ValidationError, match="client_order_id"):
        _order_intent(client_order_id=" ")


def test_execution_intent_rejects_max_margin_asset_mismatch() -> None:
    with pytest.raises(ValidationError, match="max_margin asset"):
        _execution_intent(max_margin=AssetAmount(asset="USDC", amount="25"))


def test_execution_intent_rejects_non_positive_max_margin() -> None:
    with pytest.raises(ValidationError, match="max_margin amount"):
        _execution_intent(max_margin=AssetAmount(asset="USDT", amount="0"))


def test_execution_intent_accepts_btc_margin_asset() -> None:
    intent = _execution_intent(
        margin_asset="BTC",
        max_margin=AssetAmount(asset="BTC", amount="0.05"),
    )

    assert intent.margin_asset == AssetSymbol("BTC")
    assert intent.max_margin == AssetAmount(asset="BTC", amount="0.05")


def test_execution_intent_normalizes_aware_datetime_and_defaults_status() -> None:
    intent = _execution_intent()

    assert intent.created_at == _created_at()
    assert intent.status is ExecutionIntentStatus.CREATED


def test_execution_intent_does_not_contain_exchange_fact_ids() -> None:
    fields = ExecutionIntent.model_fields

    assert "exchange_order_id" not in fields
    assert "fill_id" not in fields
    assert "quote_asset" not in fields
    assert "margin_asset" in fields
