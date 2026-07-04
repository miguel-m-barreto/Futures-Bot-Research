from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.assets import AssetAmount, AssetSymbol
from futures_bot.domain.ids import BotId, BucketId


class BucketState(BaseModel):
    """Validated BucketState foundation; monetary mutation belongs to future Ledger."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bucket_id: BucketId
    bot_id: BotId
    capital_asset: AssetSymbol
    initial_units: AssetAmount
    active_units: AssetAmount
    reserved_units: AssetAmount
    settled_profit_units: AssetAmount

    @field_validator("capital_asset", mode="before")
    @classmethod
    def _coerce_capital_asset(cls, value: object) -> AssetSymbol:
        return _coerce_asset_symbol(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> BucketState:
        for field_name in (
            "initial_units",
            "active_units",
            "reserved_units",
            "settled_profit_units",
        ):
            amount = getattr(self, field_name)
            if str(amount.asset) != str(self.capital_asset):
                raise ValueError(f"{field_name} must be denominated in capital_asset")
            if amount.amount < 0:
                raise ValueError(f"{field_name} must be non-negative")

        if self.reserved_units.amount > self.active_units.amount:
            raise ValueError("reserved_units must be less than or equal to active_units")
        return self

    @property
    def tradable_units(self) -> AssetAmount:
        return self.active_units.subtract_non_negative(self.reserved_units)

    def has_tradable_units_for(self, amount: AssetAmount) -> bool:
        if str(amount.asset) != str(self.capital_asset):
            raise ValueError("requested tradable amount must use bucket capital_asset")
        if amount.amount < 0:
            raise ValueError("requested tradable amount must be non-negative")
        return self.tradable_units.amount >= amount.amount


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
