from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator

from futures_bot.domain.assets import AssetAmount, StableCollateralAsset
from futures_bot.domain.ids import BotId, BucketId


class BucketState(BaseModel):
    """Validated BucketState foundation; monetary mutation belongs to future Ledger."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bucket_id: BucketId
    bot_id: BotId
    capital_asset: StableCollateralAsset
    initial_units: AssetAmount
    active_units: AssetAmount
    reserved_units: AssetAmount
    settled_profit_units: AssetAmount

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
