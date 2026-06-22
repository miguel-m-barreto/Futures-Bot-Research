from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from math import isfinite
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.ids import (
    DeadManSwitchCapabilityId,
    VenueCapabilitySnapshotId,
    VenueInstrumentRuleSnapshotId,
    VenueOrderValidationId,
    VenueRateLimitProfileId,
)
from futures_bot.domain.order_lifecycle import OrderIntent
from futures_bot.domain.time import ensure_aware_utc


class VenueTradingStatus(StrEnum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


class InstrumentTradingStatus(StrEnum):
    TRADING = "TRADING"
    HALTED = "HALTED"
    BREAK_ONLY = "BREAK_ONLY"
    SETTLING = "SETTLING"
    DELISTED = "DELISTED"
    UNKNOWN = "UNKNOWN"


class FuturesContractKind(StrEnum):
    LINEAR_PERPETUAL = "LINEAR_PERPETUAL"
    LINEAR_DELIVERY = "LINEAR_DELIVERY"
    INVERSE_PERPETUAL = "INVERSE_PERPETUAL"
    INVERSE_DELIVERY = "INVERSE_DELIVERY"
    SPOT = "SPOT"
    UNKNOWN = "UNKNOWN"


class StableCollateralAsset(StrEnum):
    USDT = "USDT"
    USDC = "USDC"


class VenuePositionMode(StrEnum):
    ONE_WAY = "ONE_WAY"
    HEDGE = "HEDGE"


class VenueSelfTradePreventionMode(StrEnum):
    NONE = "NONE"
    EXPIRE_TAKER = "EXPIRE_TAKER"
    EXPIRE_MAKER = "EXPIRE_MAKER"
    EXPIRE_BOTH = "EXPIRE_BOTH"
    UNKNOWN = "UNKNOWN"


class DeadManSwitchScopeKind(StrEnum):
    VENUE = "VENUE"
    ACCOUNT = "ACCOUNT"
    INSTRUMENT = "INSTRUMENT"


class VenueOrderValidationReason(StrEnum):
    OK = "OK"
    VENUE_TRADING_DISABLED = "VENUE_TRADING_DISABLED"
    API_TRADING_DISABLED = "API_TRADING_DISABLED"
    INSTRUMENT_NOT_TRADING = "INSTRUMENT_NOT_TRADING"
    UNSUPPORTED_CONTRACT_KIND = "UNSUPPORTED_CONTRACT_KIND"
    UNSUPPORTED_MARGIN_ASSET = "UNSUPPORTED_MARGIN_ASSET"
    UNSUPPORTED_SETTLEMENT_ASSET = "UNSUPPORTED_SETTLEMENT_ASSET"
    UNSUPPORTED_ORDER_TYPE = "UNSUPPORTED_ORDER_TYPE"
    UNSUPPORTED_TIME_IN_FORCE = "UNSUPPORTED_TIME_IN_FORCE"
    UNSUPPORTED_REDUCE_ONLY = "UNSUPPORTED_REDUCE_ONLY"
    UNSUPPORTED_POST_ONLY = "UNSUPPORTED_POST_ONLY"
    UNSUPPORTED_CLOSE_POSITION = "UNSUPPORTED_CLOSE_POSITION"
    UNSUPPORTED_GTD = "UNSUPPORTED_GTD"
    GTD_BELOW_MINIMUM = "GTD_BELOW_MINIMUM"
    PRICE_REQUIRED = "PRICE_REQUIRED"
    PRICE_BELOW_MINIMUM = "PRICE_BELOW_MINIMUM"
    PRICE_ABOVE_MAXIMUM = "PRICE_ABOVE_MAXIMUM"
    STOP_PRICE_BELOW_MINIMUM = "STOP_PRICE_BELOW_MINIMUM"
    STOP_PRICE_ABOVE_MAXIMUM = "STOP_PRICE_ABOVE_MAXIMUM"
    PRICE_NOT_ON_TICK = "PRICE_NOT_ON_TICK"
    STOP_PRICE_NOT_ON_TICK = "STOP_PRICE_NOT_ON_TICK"
    QUANTITY_REQUIRED = "QUANTITY_REQUIRED"
    QUANTITY_BELOW_MINIMUM = "QUANTITY_BELOW_MINIMUM"
    QUANTITY_ABOVE_MAXIMUM = "QUANTITY_ABOVE_MAXIMUM"
    QUANTITY_NOT_ON_STEP = "QUANTITY_NOT_ON_STEP"
    NOTIONAL_BELOW_MINIMUM = "NOTIONAL_BELOW_MINIMUM"
    NOTIONAL_ABOVE_MAXIMUM = "NOTIONAL_ABOVE_MAXIMUM"
    REFERENCE_PRICE_REQUIRED = "REFERENCE_PRICE_REQUIRED"
    PRICE_PRECISION_EXCEEDED = "PRICE_PRECISION_EXCEEDED"
    QUANTITY_PRECISION_EXCEEDED = "QUANTITY_PRECISION_EXCEEDED"
    VENUE_INSTRUMENT_MISMATCH = "VENUE_INSTRUMENT_MISMATCH"
    ACCOUNT_ASSET_MISMATCH = "ACCOUNT_ASSET_MISMATCH"


class PriceFilter(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tick_size: Decimal
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    price_precision: int | None = None

    @field_validator("tick_size", "min_price", "max_price", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: object) -> Decimal | None:
        return None if value is None else _coerce_decimal(value)

    @field_validator("price_precision")
    @classmethod
    def _validate_precision(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("price_precision must be >= 0")
        return value

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.tick_size <= 0:
            raise ValueError("tick_size must be > 0")
        _validate_positive_optional(self.min_price, "min_price")
        _validate_positive_optional(self.max_price, "max_price")
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.max_price < self.min_price
        ):
            raise ValueError("max_price must be >= min_price")
        return self

    def is_price_on_tick(self, price: Decimal) -> bool:
        return _is_on_increment(price, self.tick_size)

    def price_precision_ok(self, price: Decimal) -> bool:
        return self.price_precision is None or _decimal_places(price) <= self.price_precision


class QuantityFilter(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    step_size: Decimal
    min_quantity: Decimal
    max_quantity: Decimal | None = None
    quantity_precision: int | None = None

    @field_validator("step_size", "min_quantity", "max_quantity", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: object) -> Decimal | None:
        return None if value is None else _coerce_decimal(value)

    @field_validator("quantity_precision")
    @classmethod
    def _validate_precision(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("quantity_precision must be >= 0")
        return value

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.step_size <= 0:
            raise ValueError("step_size must be > 0")
        if self.min_quantity <= 0:
            raise ValueError("min_quantity must be > 0")
        _validate_positive_optional(self.max_quantity, "max_quantity")
        if self.max_quantity is not None and self.max_quantity < self.min_quantity:
            raise ValueError("max_quantity must be >= min_quantity")
        return self

    def is_quantity_on_step(self, quantity: Decimal) -> bool:
        return _is_on_increment(quantity, self.step_size)

    def quantity_precision_ok(self, quantity: Decimal) -> bool:
        return (
            self.quantity_precision is None
            or _decimal_places(quantity) <= self.quantity_precision
        )


class NotionalFilter(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    min_notional: Decimal | None = None
    max_notional: Decimal | None = None
    requires_reference_price_for_market_orders: bool

    @field_validator("min_notional", "max_notional", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: object) -> Decimal | None:
        return None if value is None else _coerce_decimal(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        _validate_positive_optional(self.min_notional, "min_notional")
        _validate_positive_optional(self.max_notional, "max_notional")
        if (
            self.min_notional is not None
            and self.max_notional is not None
            and self.max_notional < self.min_notional
        ):
            raise ValueError("max_notional must be >= min_notional")
        return self


class VenueRateLimitRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    window_ms: int
    max_weight: int | None = None
    max_orders: int | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _trimmed(value, "rate limit rule name")

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.window_ms <= 0:
            raise ValueError("window_ms must be > 0")
        if self.max_weight is not None and self.max_weight <= 0:
            raise ValueError("max_weight must be > 0")
        if self.max_orders is not None and self.max_orders <= 0:
            raise ValueError("max_orders must be > 0")
        return self


class VenueRateLimitProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    profile_id: VenueRateLimitProfileId
    rules: tuple[VenueRateLimitRule, ...]


class DeadManSwitchCapability(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: DeadManSwitchCapabilityId
    supported: bool
    scope_kind: DeadManSwitchScopeKind
    min_countdown_ms: int | None = None
    max_countdown_ms: int | None = None
    recommended_heartbeat_ms: int | None = None

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        _validate_positive_optional_int(self.min_countdown_ms, "min_countdown_ms")
        _validate_positive_optional_int(self.max_countdown_ms, "max_countdown_ms")
        _validate_positive_optional_int(
            self.recommended_heartbeat_ms,
            "recommended_heartbeat_ms",
        )
        if self.supported and self.recommended_heartbeat_ms is None:
            raise ValueError("supported dead-man switch requires recommended heartbeat")
        if (
            self.min_countdown_ms is not None
            and self.max_countdown_ms is not None
            and self.max_countdown_ms < self.min_countdown_ms
        ):
            raise ValueError("max_countdown_ms must be >= min_countdown_ms")
        return self


class VenueCapabilitySnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: VenueCapabilitySnapshotId
    venue_id: str
    trading_status: VenueTradingStatus
    api_trading_enabled: bool
    captured_at: datetime
    account_tier: str | None = None
    supported_margin_assets: tuple[str, ...]
    supported_settlement_assets: tuple[str, ...]
    supported_position_modes: tuple[VenuePositionMode, ...]
    supports_reduce_only: bool
    supports_post_only: bool
    supports_close_position: bool
    supports_gtd: bool
    min_gtd_duration_ms: int | None = None
    supports_price_protection: bool
    supported_self_trade_prevention_modes: tuple[VenueSelfTradePreventionMode, ...]
    dead_man_switch: DeadManSwitchCapability
    rate_limit_profile: VenueRateLimitProfile | None = None
    source_hash: str | None = None

    @field_validator("venue_id", "account_tier")
    @classmethod
    def _validate_text(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "venue capability text")

    @field_validator("captured_at")
    @classmethod
    def _validate_captured_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("supported_margin_assets", "supported_settlement_assets")
    @classmethod
    def _validate_stable_assets(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("supported assets must be non-empty")
        stable = {item.value for item in StableCollateralAsset}
        for item in value:
            if item not in stable:
                raise ValueError("supported assets must be limited to USDT/USDC")
        return value

    @field_validator("source_hash")
    @classmethod
    def _validate_hash(cls, value: str | None) -> str | None:
        return None if value is None else _sha256_hex(value, "source_hash")

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.supports_gtd and self.min_gtd_duration_ms is not None:
            _validate_positive_optional_int(self.min_gtd_duration_ms, "min_gtd_duration_ms")
        return self


class VenueInstrumentRuleSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: VenueInstrumentRuleSnapshotId
    venue_id: str
    instrument_id: str
    symbol: str
    trading_status: InstrumentTradingStatus
    contract_kind: FuturesContractKind
    margin_asset: str
    settlement_asset: str
    base_asset: str | None = None
    quote_asset: str | None = None
    captured_at: datetime
    price_filter: PriceFilter
    quantity_filter: QuantityFilter
    notional_filter: NotionalFilter
    max_leverage: Decimal | None = None
    supported_order_types: tuple[str, ...]
    supported_time_in_force: tuple[str, ...]
    supports_reduce_only: bool
    supports_post_only: bool
    supports_close_position: bool
    supports_gtd: bool
    min_gtd_duration_ms: int | None = None
    supports_price_protection: bool
    supported_self_trade_prevention_modes: tuple[VenueSelfTradePreventionMode, ...]
    source_hash: str | None = None

    @field_validator(
        "venue_id",
        "instrument_id",
        "symbol",
        "margin_asset",
        "settlement_asset",
        "base_asset",
        "quote_asset",
    )
    @classmethod
    def _validate_text(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "instrument rule text")

    @field_validator("captured_at")
    @classmethod
    def _validate_captured_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("max_leverage", mode="before")
    @classmethod
    def _coerce_max_leverage(cls, value: object) -> Decimal | None:
        return None if value is None else _coerce_decimal(value)

    @field_validator("source_hash")
    @classmethod
    def _validate_hash(cls, value: str | None) -> str | None:
        return None if value is None else _sha256_hex(value, "source_hash")

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.max_leverage is not None and self.max_leverage <= 0:
            raise ValueError("max_leverage must be > 0")
        if not self.supported_order_types:
            raise ValueError("supported_order_types must be non-empty")
        if self.supports_gtd and self.min_gtd_duration_ms is not None:
            _validate_positive_optional_int(self.min_gtd_duration_ms, "min_gtd_duration_ms")
        return self


class VenueOrderValidationContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    validation_id: VenueOrderValidationId | None = None
    order_intent: OrderIntent
    venue_snapshot: VenueCapabilitySnapshot
    instrument_rules: VenueInstrumentRuleSnapshot
    reference_price: Decimal | None = None
    requested_at: datetime

    @field_validator("reference_price", mode="before")
    @classmethod
    def _coerce_reference_price(cls, value: object) -> Decimal | None:
        return None if value is None else _coerce_decimal(value)

    @field_validator("requested_at")
    @classmethod
    def _validate_requested_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.order_intent.venue_id != self.venue_snapshot.venue_id:
            raise ValueError("order_intent venue_id must match venue snapshot")
        if self.order_intent.venue_id != self.instrument_rules.venue_id:
            raise ValueError("order_intent venue_id must match instrument rules")
        if self.order_intent.instrument_id != self.instrument_rules.instrument_id:
            raise ValueError("order_intent instrument_id must match instrument rules")
        if self.reference_price is not None and self.reference_price <= 0:
            raise ValueError("reference_price must be > 0")
        expected = deterministic_venue_order_validation_id(self)
        if self.validation_id is not None and self.validation_id != expected:
            raise ValueError("validation_id is not deterministic")
        object.__setattr__(self, "validation_id", expected)
        return self


class VenueOrderValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    validation_id: VenueOrderValidationId
    valid: bool
    reason: VenueOrderValidationReason
    normalized_quantity: Decimal | None = None
    normalized_limit_price: Decimal | None = None
    normalized_stop_price: Decimal | None = None
    details: Any

    @field_validator(
        "normalized_quantity",
        "normalized_limit_price",
        "normalized_stop_price",
        mode="before",
    )
    @classmethod
    def _coerce_decimal(cls, value: object) -> Decimal | None:
        return None if value is None else _coerce_decimal(value)

    @field_validator("details")
    @classmethod
    def _validate_details(cls, value: Any) -> Any:
        _canonical_json_bytes(value)
        return value

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.valid and self.reason is not VenueOrderValidationReason.OK:
            raise ValueError("valid results require OK")
        if not self.valid and self.reason is VenueOrderValidationReason.OK:
            raise ValueError("invalid results require non-OK reason")
        return self


def deterministic_venue_order_validation_id(
    context: VenueOrderValidationContext,
) -> VenueOrderValidationId:
    digest = _digest(_model_identity(context, exclude={"validation_id"}))
    return VenueOrderValidationId(value=f"venue-order-validation:{digest}")


def canonical_payload_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _model_identity(model: BaseModel, *, exclude: set[str]) -> dict[str, Any]:
    dumped = model.model_dump()
    for key in exclude:
        dumped.pop(key, None)
    return _canonical_value(dumped)


def _digest(payload: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _canonical_value(value: Any) -> Any:
    result: Any
    if isinstance(value, Decimal):
        result = format(value, "f")
    elif isinstance(value, datetime):
        result = ensure_aware_utc(value).isoformat()
    elif isinstance(value, StrEnum):
        result = value.value
    elif isinstance(value, BaseModel):
        result = _canonical_value(value.model_dump())
    elif isinstance(value, Mapping):
        result = {str(key): _canonical_value(item) for key, item in value.items()}
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        result = [_canonical_value(item) for item in value]
    else:
        result = value
    return result


def _canonical_json_bytes(payload: Any) -> bytes:
    payload = _canonical_value(payload)
    _validate_json_compatible(payload, path="payload")
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _validate_json_compatible(value: Any, *, path: str) -> None:
    if value is None or isinstance(value, str | bool | int):
        return
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f"{path} float must be finite")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} object keys must be strings")
            _validate_json_compatible(item, path=f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, item in enumerate(value):
            _validate_json_compatible(item, path=f"{path}[{index}]")
        return
    raise ValueError(f"{path} must be JSON-compatible")


def _coerce_decimal(value: object) -> Decimal:
    if isinstance(value, bool | float):
        raise ValueError("decimal value must be Decimal, int, or string")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        if value != value.strip():
            raise ValueError("decimal string must be trimmed")
        try:
            result = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("invalid decimal string") from exc
    else:
        raise ValueError("decimal value must be Decimal, int, or string")
    if not result.is_finite():
        raise ValueError("decimal value must be finite")
    return result


def _validate_positive_optional(value: Decimal | None, name: str) -> None:
    if value is not None and value <= 0:
        raise ValueError(f"{name} must be > 0")


def _validate_positive_optional_int(value: int | None, name: str) -> None:
    if value is not None and value <= 0:
        raise ValueError(f"{name} must be > 0")


def _is_on_increment(value: Decimal, increment: Decimal) -> bool:
    if value <= 0:
        return False
    return value % increment == 0


def _decimal_places(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    if isinstance(exponent, str):
        return 0
    return max(0, -exponent)


def _trimmed(value: str, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty and trimmed")
    return value


def _sha256_hex(value: str, name: str) -> str:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lowercase sha256 hex")
    return value
