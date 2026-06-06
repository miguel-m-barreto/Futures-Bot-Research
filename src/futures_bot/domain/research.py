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


class ReplayDataSourceKind(StrEnum):
    DATASET_SNAPSHOT = "DATASET_SNAPSHOT"
    EVENT_JOURNAL = "EVENT_JOURNAL"
    WAL_SEGMENT = "WAL_SEGMENT"
    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"
    OTHER = "OTHER"


class EvaluationObjective(StrEnum):
    BASELINE_COMPARISON = "BASELINE_COMPARISON"
    ROBUSTNESS = "ROBUSTNESS"
    COST_SENSITIVITY = "COST_SENSITIVITY"
    REGIME_ANALYSIS = "REGIME_ANALYSIS"
    CALIBRATION = "CALIBRATION"
    FAILURE_ANALYSIS = "FAILURE_ANALYSIS"
    REPLAY_REPRODUCIBILITY = "REPLAY_REPRODUCIBILITY"
    OTHER = "OTHER"


class MetricDirection(StrEnum):
    MAXIMIZE = "MAXIMIZE"
    MINIMIZE = "MINIMIZE"
    TARGET = "TARGET"
    INFORMATION_ONLY = "INFORMATION_ONLY"


class TemporalWindow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: TemporalWindowKind
    start_at: datetime
    end_at: datetime
    label: str | None = None
    window_id: str | None = None
    fold_id: str | None = None
    sequence_index: int | None = None

    @field_validator("start_at", "end_at")
    @classmethod
    def _validate_datetime(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("label", "window_id", "fold_id")
    @classmethod
    def _validate_optional_text_fields(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "field")

    @field_validator("sequence_index")
    @classmethod
    def _validate_sequence_index(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("sequence_index must be >= 0")
        return value

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
        return _validate_non_negative_bps(value)

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
        _validate_no_duplicate_temporal_windows(value)
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


class MetricSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    metric_id: str
    name: str
    direction: MetricDirection
    unit: str | None = None
    description: str | None = None
    is_primary: bool = False

    @field_validator("metric_id", "name")
    @classmethod
    def _validate_required_text_fields(cls, value: str) -> str:
        return _validate_required_text(value, "field")

    @field_validator("unit", "description")
    @classmethod
    def _validate_optional_text_fields(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "text")


class CostScenario(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str
    maker_fee_bps: Decimal | None = None
    taker_fee_bps: Decimal | None = None
    slippage_bps: Decimal | None = None
    funding_included: bool = False
    latency_model: str | None = None
    fill_model: str | None = None
    notes: str | None = None

    @field_validator("scenario_id")
    @classmethod
    def _validate_scenario_id(cls, value: str) -> str:
        return _validate_required_text(value, "scenario_id")

    @field_validator("maker_fee_bps", "taker_fee_bps", "slippage_bps", mode="before")
    @classmethod
    def _reject_float_bps(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("bps values must be Decimal-compatible strings or Decimal")
        return value

    @field_validator("maker_fee_bps", "taker_fee_bps", "slippage_bps")
    @classmethod
    def _validate_non_negative_bps(cls, value: Decimal | None) -> Decimal | None:
        return _validate_non_negative_bps(value)

    @field_validator("latency_model", "fill_model", "notes")
    @classmethod
    def _validate_optional_text_fields(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "text")


class ReplayPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    replay_plan_id: str
    run_id: RunId
    data_source_kind: ReplayDataSourceKind
    dataset_id: str | None = None
    temporal_windows: tuple[TemporalWindow, ...]
    created_at: datetime
    random_seed: int | None = None
    notes: str | None = None

    @field_validator("replay_plan_id")
    @classmethod
    def _validate_replay_plan_id(cls, value: str) -> str:
        return _validate_required_text(value, "replay_plan_id")

    @field_validator("dataset_id", "notes")
    @classmethod
    def _validate_optional_text_fields(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "text")

    @field_validator("temporal_windows")
    @classmethod
    def _validate_temporal_windows(
        cls, value: tuple[TemporalWindow, ...]
    ) -> tuple[TemporalWindow, ...]:
        if not value:
            raise ValueError("temporal_windows must be non-empty")
        _validate_no_duplicate_temporal_windows(value)
        return value

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("random_seed")
    @classmethod
    def _validate_random_seed(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("random_seed must be >= 0")
        return value

    @model_validator(mode="after")
    def _validate_data_source(self) -> Self:
        if (
            self.data_source_kind is ReplayDataSourceKind.DATASET_SNAPSHOT
            and self.dataset_id is None
        ):
            raise ValueError("dataset_id is required for DATASET_SNAPSHOT replay plans")
        return self


class EvaluationPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evaluation_plan_id: str
    run_id: RunId
    replay_plan_id: str
    objective: EvaluationObjective
    metric_specs: tuple[MetricSpec, ...]
    cost_scenarios: tuple[CostScenario, ...]
    created_at: datetime
    expected_outcome_ids: tuple[str, ...] = ()
    notes: str | None = None

    @field_validator("evaluation_plan_id", "replay_plan_id")
    @classmethod
    def _validate_required_text_fields(cls, value: str) -> str:
        return _validate_required_text(value, "field")

    @field_validator("metric_specs")
    @classmethod
    def _validate_metric_specs(cls, value: tuple[MetricSpec, ...]) -> tuple[MetricSpec, ...]:
        if not value:
            raise ValueError("metric_specs must be non-empty")
        metric_ids = [spec.metric_id for spec in value]
        if len(set(metric_ids)) != len(metric_ids):
            raise ValueError("duplicate metric_id values are not allowed")
        if not any(spec.is_primary for spec in value):
            raise ValueError("at least one metric spec must be primary")
        return value

    @field_validator("cost_scenarios")
    @classmethod
    def _validate_cost_scenarios(
        cls, value: tuple[CostScenario, ...]
    ) -> tuple[CostScenario, ...]:
        if not value:
            raise ValueError("cost_scenarios must be non-empty")
        scenario_ids = [scenario.scenario_id for scenario in value]
        if len(set(scenario_ids)) != len(scenario_ids):
            raise ValueError("duplicate scenario_id values are not allowed")
        return value

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("expected_outcome_ids")
    @classmethod
    def _validate_expected_outcome_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for expected_outcome_id in value:
            _validate_required_text(expected_outcome_id, "expected_outcome_id")
        return value

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "notes")


def _validate_non_negative_bps(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if value < Decimal("0"):
        raise ValueError("bps values must be non-negative")
    return value


def _temporal_window_key(window: TemporalWindow) -> tuple[object, ...]:
    return (
        window.kind,
        window.start_at,
        window.end_at,
        window.label,
        window.window_id,
        window.fold_id,
        window.sequence_index,
    )


def _validate_no_duplicate_temporal_windows(
    windows: tuple[TemporalWindow, ...]
) -> None:
    keys = [_temporal_window_key(window) for window in windows]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate temporal windows are not allowed")


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
