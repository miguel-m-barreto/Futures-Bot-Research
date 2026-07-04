from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.assets import AssetAmount, AssetSymbol
from futures_bot.domain.ids import BotBlueprintId, BotId, BucketId, CohortId, ExperimentId, PolicyId
from futures_bot.domain.modes import CapitalMode, OperationalStatus, ResearchStatus, RunMode
from futures_bot.domain.time import ensure_aware_utc


class BotBlueprint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    blueprint_id: BotBlueprintId
    bot_family: str
    run_mode: RunMode
    capital_mode: CapitalMode
    initial_capital: AssetAmount
    decision_policy_id: PolicyId | None = None
    risk_policy_id: PolicyId | None = None
    universe_policy_id: PolicyId | None = None
    evaluation_policy_id: PolicyId | None = None

    @field_validator("bot_family")
    @classmethod
    def _validate_bot_family(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("bot_family must be a non-empty trimmed string")
        return value

    @model_validator(mode="after")
    def _validate_initial_capital_asset(self) -> BotBlueprint:
        if self.initial_capital.amount < 0:
            raise ValueError("initial_capital must be non-negative")
        return self


class BotInstance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bot_id: BotId
    blueprint_id: BotBlueprintId
    experiment_id: ExperimentId
    cohort_id: CohortId
    bucket_id: BucketId
    run_mode: RunMode
    capital_mode: CapitalMode
    operational_status: OperationalStatus
    research_status: ResearchStatus
    capital_asset: AssetSymbol
    created_at: datetime

    @field_validator("capital_asset", mode="before")
    @classmethod
    def _coerce_capital_asset(cls, value: object) -> AssetSymbol:
        return _coerce_asset_symbol(value)

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    def can_trade_paper_intents(self) -> bool:
        return (
            self.operational_status is OperationalStatus.RUNNING
            and self.run_mode is RunMode.PAPER_LIVE
            and self.capital_mode is CapitalMode.SIMULATED
        )

    def can_evaluate(self) -> bool:
        return self.operational_status is not OperationalStatus.BALANCE_DEPLETED


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
