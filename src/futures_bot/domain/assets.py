from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, field_validator

_ASSET_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,16}$")
_STABLE_COLLATERAL_ASSETS = frozenset({"USDT", "USDC"})


class AssetSymbol(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    value: str

    def __init__(self, value: str | None = None, **data: Any) -> None:
        if value is not None:
            if data:
                raise TypeError("pass either a positional value or keyword fields, not both")
            data = {"value": value}
        super().__init__(**data)

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("asset symbol must be a string")
        if not _ASSET_SYMBOL_RE.fullmatch(value):
            raise ValueError("asset symbol must be 2..16 uppercase ASCII letters/digits")
        return value

    @classmethod
    def from_str(cls, value: str) -> Self:
        return cls(value)

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"AssetSymbol({self.value!r})"


class StableCollateralAsset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: AssetSymbol

    def __init__(self, value: str | AssetSymbol | None = None, **data: Any) -> None:
        if value is not None:
            if data:
                raise TypeError("pass either a positional value or keyword fields, not both")
            data = {"symbol": value}
        super().__init__(**data)

    @field_validator("symbol", mode="before")
    @classmethod
    def _coerce_symbol(cls, value: object) -> AssetSymbol:
        if isinstance(value, StableCollateralAsset):
            return value.symbol
        if isinstance(value, AssetSymbol):
            return value
        if isinstance(value, str):
            return AssetSymbol(value)
        raise TypeError("stable collateral asset must be an asset symbol")

    @field_validator("symbol")
    @classmethod
    def _validate_allowed_symbol(cls, value: AssetSymbol) -> AssetSymbol:
        if str(value) not in _STABLE_COLLATERAL_ASSETS:
            raise ValueError("current stable collateral asset must be USDT or USDC")
        return value

    @property
    def value(self) -> str:
        return str(self.symbol)

    def __str__(self) -> str:
        return str(self.symbol)

    def __repr__(self) -> str:
        return f"StableCollateralAsset({str(self.symbol)!r})"


class RoundingPolicy(BaseModel):
    """Placeholder for explicit future rounding policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: str = "UNSPECIFIED"


class QuantizationPolicy(BaseModel):
    """Placeholder for explicit future exchange/domain quantization policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: str = "UNSPECIFIED"


class ConversionRateSnapshot(BaseModel):
    """Explicit future valuation placeholder; no implicit conversion is implemented."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_asset: AssetSymbol
    target_asset: AssetSymbol
    rate: Decimal
    source: str
    snapshot_id: str

    @field_validator("source_asset", "target_asset", mode="before")
    @classmethod
    def _coerce_asset_symbol(cls, value: object) -> AssetSymbol:
        return _coerce_asset_symbol(value)

    @field_validator("rate", mode="before")
    @classmethod
    def _validate_rate_input(cls, value: object) -> Decimal:
        return _coerce_decimal(value)

    @field_validator("rate")
    @classmethod
    def _validate_rate(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("conversion rate must be positive")
        return value


class AssetAmount(BaseModel):
    """Absolute asset-denominated quantity.

    AssetAmount is a balance/quantity primitive and is always non-negative. Signed accounting
    movement belongs in AssetDelta.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    asset: AssetSymbol
    amount: Decimal

    @field_validator("asset", mode="before")
    @classmethod
    def _coerce_asset(cls, value: object) -> AssetSymbol:
        return _coerce_asset_symbol(value)

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce_amount(cls, value: object) -> Decimal:
        return _coerce_decimal(value)

    @field_validator("amount")
    @classmethod
    def _validate_non_negative_decimal(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("asset amount must be finite")
        if value < 0:
            raise ValueError("asset amount must be non-negative")
        return value

    @classmethod
    def zero(cls, asset: AssetSymbol | StableCollateralAsset | str) -> Self:
        return cls(asset=_coerce_asset_symbol(asset), amount=Decimal("0"))

    @classmethod
    def non_negative(cls, asset: AssetSymbol | StableCollateralAsset | str, amount: object) -> Self:
        return cls(asset=_coerce_asset_symbol(asset), amount=_coerce_decimal(amount))

    @classmethod
    def positive(cls, asset: AssetSymbol | StableCollateralAsset | str, amount: object) -> Self:
        asset_amount = cls(asset=_coerce_asset_symbol(asset), amount=_coerce_decimal(amount))
        if asset_amount.amount <= 0:
            raise ValueError("asset amount must be positive")
        return asset_amount

    def _ensure_same_asset(self, other: AssetAmount) -> None:
        if self.asset != other.asset:
            raise ValueError("cross-asset accounting operation rejected")

    def __add__(self, other: AssetAmount) -> AssetAmount:
        self._ensure_same_asset(other)
        return AssetAmount(asset=self.asset, amount=self.amount + other.amount)

    def __sub__(self, other: AssetAmount) -> AssetAmount:
        self._ensure_same_asset(other)
        return AssetAmount(asset=self.asset, amount=self.amount - other.amount)

    def subtract_non_negative(self, other: AssetAmount) -> AssetAmount:
        return self - other

    def is_non_negative(self) -> bool:
        return self.amount >= 0

    def is_positive(self) -> bool:
        return self.amount > 0


class AssetDelta(BaseModel):
    """Signed accounting movement such as realized PnL, fees, funding, or ledger deltas.

    AssetDelta may be negative, zero, or positive. It is not a balance.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    asset: AssetSymbol
    amount: Decimal

    @field_validator("asset", mode="before")
    @classmethod
    def _coerce_asset(cls, value: object) -> AssetSymbol:
        return _coerce_asset_symbol(value)

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce_amount(cls, value: object) -> Decimal:
        return _coerce_decimal(value)

    @field_validator("amount")
    @classmethod
    def _validate_finite_decimal(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("asset delta must be finite")
        return value

    @classmethod
    def zero(cls, asset: AssetSymbol | StableCollateralAsset | str) -> Self:
        return cls(asset=_coerce_asset_symbol(asset), amount=Decimal("0"))

    def _ensure_same_asset(self, other: AssetDelta) -> None:
        if self.asset != other.asset:
            raise ValueError("cross-asset accounting operation rejected")

    def __add__(self, other: AssetDelta) -> AssetDelta:
        self._ensure_same_asset(other)
        return AssetDelta(asset=self.asset, amount=self.amount + other.amount)

    def __sub__(self, other: AssetDelta) -> AssetDelta:
        self._ensure_same_asset(other)
        return AssetDelta(asset=self.asset, amount=self.amount - other.amount)


def _coerce_asset_symbol(value: object) -> AssetSymbol:
    if isinstance(value, StableCollateralAsset):
        return value.symbol
    if isinstance(value, AssetSymbol):
        return value
    if isinstance(value, str):
        return AssetSymbol(value)
    raise TypeError("asset must be an AssetSymbol, StableCollateralAsset, or string")


def _coerce_decimal(value: object) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("accounting amount must not be bool")
    if isinstance(value, float):
        raise ValueError("float input is prohibited for accounting")
    if isinstance(value, Decimal):
        decimal_value = value
    elif isinstance(value, int | str):
        decimal_value = Decimal(value)
    else:
        raise ValueError("accounting amount must be Decimal, int, or string")
    if not decimal_value.is_finite():
        raise ValueError("accounting amount must be finite")
    return decimal_value
