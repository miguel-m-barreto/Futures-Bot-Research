from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.ids import PolicyId
from futures_bot.domain.instruments import InstrumentSymbol
from futures_bot.domain.market_annotations import MarketAnnotationKind, MarketAnnotationSet
from futures_bot.domain.policies import UniversePolicyKind


class UniverseEligibilityDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: InstrumentSymbol
    eligible: bool
    policy_kind: UniversePolicyKind
    reason: str

    @field_validator("instrument", mode="before")
    @classmethod
    def _coerce_instrument(cls, value: object) -> InstrumentSymbol:
        return _coerce_instrument(value)

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        return _trimmed(value, "reason")


class UniversePolicySpec(BaseModel):
    """Bot/cohort/DecisionStack-specific universe policy hypothesis."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: PolicyId
    policy_kind: UniversePolicyKind
    allowed_instruments: tuple[InstrumentSymbol, ...] = ()
    blocked_instruments: tuple[InstrumentSymbol, ...] = ()
    required_annotations: tuple[MarketAnnotationKind, ...] = ()
    blocked_annotations: tuple[MarketAnnotationKind, ...] = ()

    @field_validator("allowed_instruments", "blocked_instruments", mode="before")
    @classmethod
    def _coerce_instrument_tuple(cls, value: object) -> tuple[InstrumentSymbol, ...]:
        if value is None:
            return ()
        if not isinstance(value, tuple | list):
            raise ValueError("instruments must be a tuple or list")
        return tuple(_coerce_instrument(item) for item in value)

    @model_validator(mode="after")
    def _validate_policy(self) -> UniversePolicySpec:
        allowed = frozenset(str(instrument) for instrument in self.allowed_instruments)
        blocked = frozenset(str(instrument) for instrument in self.blocked_instruments)
        required = frozenset(self.required_annotations)
        blocked_annotations = frozenset(self.blocked_annotations)

        if len(allowed) != len(self.allowed_instruments):
            raise ValueError("duplicate allowed instruments are not allowed")
        if len(blocked) != len(self.blocked_instruments):
            raise ValueError("duplicate blocked instruments are not allowed")
        if allowed & blocked:
            raise ValueError("instrument cannot be both allowed and blocked")
        if len(required) != len(self.required_annotations):
            raise ValueError("duplicate required annotations are not allowed")
        if len(blocked_annotations) != len(self.blocked_annotations):
            raise ValueError("duplicate blocked annotations are not allowed")
        if required & blocked_annotations:
            raise ValueError("annotation cannot be both required and blocked")
        if (
            self.policy_kind is UniversePolicyKind.SINGLE_INSTRUMENT
            and len(self.allowed_instruments) != 1
        ):
            raise ValueError("SINGLE_INSTRUMENT policy requires exactly one allowed instrument")
        return self

    def evaluate(
        self,
        instrument: InstrumentSymbol | str,
        annotations: MarketAnnotationSet | None = None,
    ) -> UniverseEligibilityDecision:
        candidate = _coerce_instrument(instrument)
        if annotations is not None and annotations.instrument != candidate:
            raise ValueError("annotation set instrument must match evaluated instrument")

        if any(candidate == blocked for blocked in self.blocked_instruments):
            return self._decision(candidate, False, "instrument blocked by local universe policy")

        if self.allowed_instruments and not any(
            candidate == allowed for allowed in self.allowed_instruments
        ):
            return self._decision(candidate, False, "instrument absent from allowed universe")

        annotation_kinds = annotations.kinds() if annotations is not None else frozenset()
        missing_required = frozenset(self.required_annotations) - annotation_kinds
        if missing_required:
            return self._decision(candidate, False, "required annotations missing")

        blocked_annotations = frozenset(self.blocked_annotations) & annotation_kinds
        if blocked_annotations:
            return self._decision(candidate, False, "blocked annotation present")

        return self._decision(candidate, True, "eligible under local universe policy")

    def _decision(
        self,
        instrument: InstrumentSymbol,
        eligible: bool,
        reason: str,
    ) -> UniverseEligibilityDecision:
        return UniverseEligibilityDecision(
            instrument=instrument,
            eligible=eligible,
            policy_kind=self.policy_kind,
            reason=reason,
        )


def _coerce_instrument(value: object) -> InstrumentSymbol:
    if isinstance(value, InstrumentSymbol):
        return value
    if isinstance(value, str):
        return InstrumentSymbol(value)
    raise ValueError("instrument must be an InstrumentSymbol or string")


def _trimmed(value: str, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty trimmed string")
    return value
