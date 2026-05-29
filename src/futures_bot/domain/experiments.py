from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from futures_bot.domain.ids import CohortId, ExperimentId
from futures_bot.domain.time import ensure_aware_utc


class Experiment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    experiment_id: ExperimentId
    name: str
    description: str
    created_at: datetime

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("name must be a non-empty trimmed string")
        return value

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)


class Cohort(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cohort_id: CohortId
    experiment_id: ExperimentId
    name: str
    description: str
    created_at: datetime

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("name must be a non-empty trimmed string")
        return value

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)
