from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.ids import RunId
from futures_bot.domain.time import ensure_aware_utc


class ResearchRunStatus(StrEnum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INVALIDATED = "INVALIDATED"


class TemporalWindowKind(StrEnum):
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    TEST = "TEST"
    FINAL_HOLDOUT = "FINAL_HOLDOUT"
    REPLAY = "REPLAY"
    PAPER = "PAPER"
    SHADOW = "SHADOW"
    LIVE = "LIVE"


class EvaluationArtifactKind(StrEnum):
    MANIFEST = "MANIFEST"
    CONFIG = "CONFIG"
    METRICS = "METRICS"
    REPORT = "REPORT"
    PLOT = "PLOT"
    TABLE = "TABLE"
    LOG = "LOG"
    FAILURE_ANALYSIS = "FAILURE_ANALYSIS"
    ENVIRONMENT_SNAPSHOT = "ENVIRONMENT_SNAPSHOT"
    OTHER = "OTHER"


class ExecutionMode(StrEnum):
    BACKTEST = "BACKTEST"
    REPLAY = "REPLAY"
    PAPER = "PAPER"
    SHADOW = "SHADOW"
    LIVE = "LIVE"


class TemporalWindow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: TemporalWindowKind
    start_at: datetime
    end_at: datetime
    label: str | None = None

    @field_validator("start_at", "end_at")
    @classmethod
    def _validate_datetime(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("label")
    @classmethod
    def _validate_label(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "label")

    @model_validator(mode="after")
    def _validate_range(self) -> Self:
        if self.start_at >= self.end_at:
            raise ValueError("start_at must be before end_at")
        return self


class DatasetSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_id: str
    source: str
    market_type: str
    symbols: tuple[str, ...]
    timeframe: str
    start_at: datetime
    end_at: datetime
    data_version: str | None = None
    content_hash: str | None = None
    created_at: datetime

    @field_validator("dataset_id", "source", "market_type", "timeframe")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        return _validate_required_text(value, "field")

    @field_validator("data_version", "content_hash")
    @classmethod
    def _validate_optional_metadata(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "metadata")

    @field_validator("symbols")
    @classmethod
    def _validate_symbols(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("symbols must be non-empty")
        for symbol in value:
            _validate_required_text(symbol, "symbol")
        if len(set(value)) != len(value):
            raise ValueError("duplicate symbols are not allowed")
        return value

    @field_validator("start_at", "end_at", "created_at")
    @classmethod
    def _validate_datetime(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @model_validator(mode="after")
    def _validate_range(self) -> Self:
        if self.start_at >= self.end_at:
            raise ValueError("start_at must be before end_at")
        return self


class ExecutionAssumptions(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: ExecutionMode
    maker_fee_bps: Decimal | None = None
    taker_fee_bps: Decimal | None = None
    slippage_bps: Decimal | None = None
    funding_included: bool = False
    latency_model: str | None = None
    fill_model: str | None = None
    notes: str | None = None

    @field_validator("maker_fee_bps", "taker_fee_bps", "slippage_bps", mode="before")
    @classmethod
    def _reject_float_bps(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("bps values must be Decimal-compatible strings or Decimal")
        return value

    @field_validator("maker_fee_bps", "taker_fee_bps", "slippage_bps")
    @classmethod
    def _validate_non_negative_bps(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        if value < Decimal("0"):
            raise ValueError("bps values must be non-negative")
        return value

    @field_validator("latency_model", "fill_model", "notes")
    @classmethod
    def _validate_optional_text_fields(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "text")


class ExpectedOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    setup_id: str
    expectation: str
    primary_measurements: tuple[str, ...]
    failure_criteria: tuple[str, ...] = ()

    @field_validator("setup_id", "expectation")
    @classmethod
    def _validate_required_text_fields(cls, value: str) -> str:
        return _validate_required_text(value, "field")

    @field_validator("primary_measurements")
    @classmethod
    def _validate_primary_measurements(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("primary_measurements must be non-empty")
        for measurement in value:
            _validate_required_text(measurement, "primary_measurement")
        return value

    @field_validator("failure_criteria")
    @classmethod
    def _validate_failure_criteria(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for criterion in value:
            _validate_required_text(criterion, "failure_criterion")
        return value


class ResearchRunManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    experiment_id: str
    status: ResearchRunStatus
    execution_mode: ExecutionMode
    created_at: datetime
    updated_at: datetime
    git_commit: str
    code_branch: str
    config_hash: str
    dataset: DatasetSnapshot
    temporal_windows: tuple[TemporalWindow, ...]
    execution_assumptions: ExecutionAssumptions
    expected_outcomes: tuple[ExpectedOutcome, ...] = ()
    notes: str | None = None

    @field_validator("experiment_id", "git_commit", "code_branch", "config_hash")
    @classmethod
    def _validate_required_text_fields(cls, value: str) -> str:
        return _validate_required_text(value, "field")

    @field_validator("created_at", "updated_at")
    @classmethod
    def _validate_datetime(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("temporal_windows")
    @classmethod
    def _validate_temporal_windows(
        cls, value: tuple[TemporalWindow, ...]
    ) -> tuple[TemporalWindow, ...]:
        if not value:
            raise ValueError("temporal_windows must be non-empty")
        kinds = [window.kind for window in value]
        if len(set(kinds)) != len(kinds):
            raise ValueError("duplicate temporal window kinds are not allowed")
        return value

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "notes")

    @model_validator(mode="after")
    def _validate_updated_at(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must be >= created_at")
        return self


class EvaluationArtifactMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: str
    run_id: RunId
    kind: EvaluationArtifactKind
    created_at: datetime
    uri: str
    content_hash: str | None = None
    description: str | None = None

    @field_validator("artifact_id", "uri")
    @classmethod
    def _validate_required_text_fields(cls, value: str) -> str:
        return _validate_required_text(value, "field")

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("content_hash", "description")
    @classmethod
    def _validate_optional_text_fields(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "text")


def _validate_required_text(value: str, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty trimmed string")
    return value


def _validate_optional_text(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty trimmed string")
    return value
