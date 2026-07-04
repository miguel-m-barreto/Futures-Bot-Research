from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.assets import AssetAmount, AssetSymbol
from futures_bot.domain.ids import (
    BotId,
    DecisionIntentId,
    ExecutionIntentId,
    InstrumentId,
    OrderIntentId,
    RunId,
)
from futures_bot.domain.time import ensure_aware_utc


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class TimeInForce(StrEnum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


class ExecutionIntentStatus(StrEnum):
    CREATED = "CREATED"
    SUBMIT_ATTEMPTED = "SUBMIT_ATTEMPTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class OrderIntent(BaseModel):
    """Order-level execution intent; not an exchange submission."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_intent_id: OrderIntentId
    instrument_id: InstrumentId
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    limit_price: Decimal | None = None
    # Domain intent leaves time_in_force unspecified by default. Choosing IOC for
    # market orders or GTC for limit orders is future execution policy, not a
    # property of this immutable intent contract.
    time_in_force: TimeInForce | None = None
    reduce_only: bool = False
    client_order_id: str

    @field_validator("quantity", mode="before")
    @classmethod
    def _coerce_quantity(cls, value: object) -> Decimal:
        return _coerce_decimal(value)

    @field_validator("quantity")
    @classmethod
    def _validate_quantity(cls, value: Decimal) -> Decimal:
        return _positive_decimal(value, "quantity")

    @field_validator("limit_price", mode="before")
    @classmethod
    def _coerce_limit_price(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return _coerce_decimal(value)

    @field_validator("client_order_id")
    @classmethod
    def _validate_client_order_id(cls, value: str) -> str:
        return _trimmed(value, "client_order_id")

    @model_validator(mode="after")
    def _validate_order_type_price(self) -> Self:
        if self.order_type is OrderType.MARKET and self.limit_price is not None:
            raise ValueError("MARKET order must not have limit_price")
        if self.order_type is OrderType.LIMIT:
            if self.limit_price is None:
                raise ValueError("LIMIT order requires limit_price")
            _positive_decimal(self.limit_price, "limit_price")
        return self


class ExecutionIntent(BaseModel):
    """A durable intent to execute a decision; still not exchange submission."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_intent_id: ExecutionIntentId
    run_id: RunId
    bot_id: BotId
    decision_intent_id: DecisionIntentId
    order_intent: OrderIntent
    margin_asset: AssetSymbol
    max_margin: AssetAmount
    status: ExecutionIntentStatus = ExecutionIntentStatus.CREATED
    created_at: datetime

    @field_validator("margin_asset", mode="before")
    @classmethod
    def _coerce_margin_asset(cls, value: object) -> AssetSymbol:
        return _coerce_asset_symbol(value)

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @model_validator(mode="after")
    def _validate_margin(self) -> Self:
        if self.max_margin.asset != self.margin_asset:
            raise ValueError("max_margin asset must match margin_asset")
        if self.max_margin.amount <= 0:
            raise ValueError("max_margin amount must be positive")
        return self


def _trimmed(value: str, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty trimmed string")
    return value


def _coerce_asset_symbol(value: object) -> AssetSymbol:
    if (
        isinstance(value, Mapping)
        and set(value) == {"symbol"}
        and isinstance(value.get("symbol"), Mapping)
        and set(value["symbol"]) == {"value"}
        and isinstance(value["symbol"].get("value"), str)
    ):
        return AssetSymbol(value["symbol"]["value"])
    if isinstance(value, AssetSymbol):
        return AssetSymbol.model_validate(value.model_dump())
    if isinstance(value, str):
        return AssetSymbol(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return _coerce_asset_symbol(dumped)
    return AssetSymbol.model_validate(value)


def _coerce_decimal(value: object) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("decimal value must not be bool")
    if isinstance(value, float):
        raise ValueError("float input is prohibited")
    if isinstance(value, Decimal):
        decimal_value = value
    elif isinstance(value, int):
        decimal_value = Decimal(value)
    elif isinstance(value, str):
        if value != value.strip():
            raise ValueError("decimal string must not have leading or trailing whitespace")
        try:
            decimal_value = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"decimal string is not a valid number: {value!r}") from exc
    else:
        raise ValueError("decimal value must be Decimal, int, or string")
    if not decimal_value.is_finite():
        raise ValueError("decimal value must be finite")
    return decimal_value


def _positive_decimal(value: Decimal, field_name: str) -> Decimal:
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value
