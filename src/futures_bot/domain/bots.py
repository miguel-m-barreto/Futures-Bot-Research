from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.assets import AssetAmount, StableCollateralAsset
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
        StableCollateralAsset(self.initial_capital.asset)
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
    capital_asset: StableCollateralAsset
    created_at: datetime

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
