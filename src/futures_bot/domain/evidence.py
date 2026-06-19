from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from futures_bot.domain.ids import (
    DomainId,
    EvidenceId,
    MarketEvidenceItemId,
    MarketEvidenceSetId,
    MarketHealthSnapshotId,
    MarketObservationId,
)
from futures_bot.domain.instruments import InstrumentSymbol, normalize_instrument_symbol
from futures_bot.domain.market_data import (
    CrossVenueMarketFrame,
    IndexPriceObservationPayload,
    MarketSourceHealthSnapshot,
    MarkPriceObservationPayload,
    NormalizedMarketObservation,
    TopOfBookObservationPayload,
    TradeObservationPayload,
)

_MARKET_OBSERVATION_ID_RE = re.compile(r"^market-observation:[0-9a-f]{64}$")
_MARKET_HEALTH_ID_RE = re.compile(r"^market-health:[0-9a-f]{64}$")
_MARKET_EVIDENCE_ITEM_ID_RE = re.compile(
    r"^market-evidence-item:[0-9a-f]{64}$"
)
_MARKET_EVIDENCE_SET_ID_RE = re.compile(r"^market-evidence-set:[0-9a-f]{64}$")
_MARKET_EVIDENCE_BUILDER_RE = re.compile(r"^market-evidence-builder:[0-9a-f]{64}$")


def _all_market_evidence_kinds() -> tuple[MarketEvidenceKind, ...]:
    return tuple(sorted(MarketEvidenceKind, key=lambda kind: kind.value))


class EvidenceSourceKind(StrEnum):
    MARKET_ANNOTATION = "MARKET_ANNOTATION"
    TECHNICAL_INDICATOR = "TECHNICAL_INDICATOR"
    STATISTICAL_MODEL = "STATISTICAL_MODEL"
    ML_MODEL = "ML_MODEL"
    NEURAL_MODEL = "NEURAL_MODEL"
    LLM = "LLM"
    RULE_BASED = "RULE_BASED"
    MANUAL_RESEARCH = "MANUAL_RESEARCH"
    HYBRID = "HYBRID"


class EvidenceDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"
    NO_TRADE = "NO_TRADE"
    UNKNOWN = "UNKNOWN"


class MarketEvidenceOriginKind(StrEnum):
    OBSERVATION = "OBSERVATION"
    SOURCE_HEALTH = "SOURCE_HEALTH"


class MarketEvidenceValueKind(StrEnum):
    DECIMAL = "DECIMAL"
    INTEGER = "INTEGER"
    TEXT = "TEXT"
    TEXT_TUPLE = "TEXT_TUPLE"


class MarketEvidenceUnit(StrEnum):
    PRICE = "PRICE"
    QUANTITY = "QUANTITY"
    COUNT = "COUNT"
    SEQUENCE = "SEQUENCE"
    ENUM = "ENUM"
    ENUM_SET = "ENUM_SET"


class MarketEvidenceKind(StrEnum):
    TRADE_PRICE = "TRADE_PRICE"
    TRADE_QUANTITY = "TRADE_QUANTITY"
    TRADE_AGGRESSOR_SIDE = "TRADE_AGGRESSOR_SIDE"
    TOP_OF_BOOK_BID_PRICE = "TOP_OF_BOOK_BID_PRICE"
    TOP_OF_BOOK_BID_QUANTITY = "TOP_OF_BOOK_BID_QUANTITY"
    TOP_OF_BOOK_ASK_PRICE = "TOP_OF_BOOK_ASK_PRICE"
    TOP_OF_BOOK_ASK_QUANTITY = "TOP_OF_BOOK_ASK_QUANTITY"
    TOP_OF_BOOK_QUOTE_SEMANTICS = "TOP_OF_BOOK_QUOTE_SEMANTICS"
    MARK_PRICE = "MARK_PRICE"
    INDEX_PRICE = "INDEX_PRICE"
    SOURCE_HEALTH_STATE = "SOURCE_HEALTH_STATE"
    SOURCE_HEALTH_ISSUES = "SOURCE_HEALTH_ISSUES"
    SOURCE_HEALTH_RECONNECT_GENERATION = "SOURCE_HEALTH_RECONNECT_GENERATION"
    SOURCE_HEALTH_CONSECUTIVE_FAILURES = "SOURCE_HEALTH_CONSECUTIVE_FAILURES"
    SOURCE_HEALTH_LAST_SEQUENCE = "SOURCE_HEALTH_LAST_SEQUENCE"


_KIND_MATRIX: dict[
    MarketEvidenceKind,
    tuple[MarketEvidenceOriginKind, MarketEvidenceValueKind, MarketEvidenceUnit],
] = {
    MarketEvidenceKind.TRADE_PRICE: (
        MarketEvidenceOriginKind.OBSERVATION,
        MarketEvidenceValueKind.DECIMAL,
        MarketEvidenceUnit.PRICE,
    ),
    MarketEvidenceKind.TRADE_QUANTITY: (
        MarketEvidenceOriginKind.OBSERVATION,
        MarketEvidenceValueKind.DECIMAL,
        MarketEvidenceUnit.QUANTITY,
    ),
    MarketEvidenceKind.TRADE_AGGRESSOR_SIDE: (
        MarketEvidenceOriginKind.OBSERVATION,
        MarketEvidenceValueKind.TEXT,
        MarketEvidenceUnit.ENUM,
    ),
    MarketEvidenceKind.TOP_OF_BOOK_BID_PRICE: (
        MarketEvidenceOriginKind.OBSERVATION,
        MarketEvidenceValueKind.DECIMAL,
        MarketEvidenceUnit.PRICE,
    ),
    MarketEvidenceKind.TOP_OF_BOOK_BID_QUANTITY: (
        MarketEvidenceOriginKind.OBSERVATION,
        MarketEvidenceValueKind.DECIMAL,
        MarketEvidenceUnit.QUANTITY,
    ),
    MarketEvidenceKind.TOP_OF_BOOK_ASK_PRICE: (
        MarketEvidenceOriginKind.OBSERVATION,
        MarketEvidenceValueKind.DECIMAL,
        MarketEvidenceUnit.PRICE,
    ),
    MarketEvidenceKind.TOP_OF_BOOK_ASK_QUANTITY: (
        MarketEvidenceOriginKind.OBSERVATION,
        MarketEvidenceValueKind.DECIMAL,
        MarketEvidenceUnit.QUANTITY,
    ),
    MarketEvidenceKind.TOP_OF_BOOK_QUOTE_SEMANTICS: (
        MarketEvidenceOriginKind.OBSERVATION,
        MarketEvidenceValueKind.TEXT,
        MarketEvidenceUnit.ENUM,
    ),
    MarketEvidenceKind.MARK_PRICE: (
        MarketEvidenceOriginKind.OBSERVATION,
        MarketEvidenceValueKind.DECIMAL,
        MarketEvidenceUnit.PRICE,
    ),
    MarketEvidenceKind.INDEX_PRICE: (
        MarketEvidenceOriginKind.OBSERVATION,
        MarketEvidenceValueKind.DECIMAL,
        MarketEvidenceUnit.PRICE,
    ),
    MarketEvidenceKind.SOURCE_HEALTH_STATE: (
        MarketEvidenceOriginKind.SOURCE_HEALTH,
        MarketEvidenceValueKind.TEXT,
        MarketEvidenceUnit.ENUM,
    ),
    MarketEvidenceKind.SOURCE_HEALTH_ISSUES: (
        MarketEvidenceOriginKind.SOURCE_HEALTH,
        MarketEvidenceValueKind.TEXT_TUPLE,
        MarketEvidenceUnit.ENUM_SET,
    ),
    MarketEvidenceKind.SOURCE_HEALTH_RECONNECT_GENERATION: (
        MarketEvidenceOriginKind.SOURCE_HEALTH,
        MarketEvidenceValueKind.INTEGER,
        MarketEvidenceUnit.COUNT,
    ),
    MarketEvidenceKind.SOURCE_HEALTH_CONSECUTIVE_FAILURES: (
        MarketEvidenceOriginKind.SOURCE_HEALTH,
        MarketEvidenceValueKind.INTEGER,
        MarketEvidenceUnit.COUNT,
    ),
    MarketEvidenceKind.SOURCE_HEALTH_LAST_SEQUENCE: (
        MarketEvidenceOriginKind.SOURCE_HEALTH,
        MarketEvidenceValueKind.INTEGER,
        MarketEvidenceUnit.SEQUENCE,
    ),
}

_POSITIVE_DECIMAL_KINDS = frozenset(
    {
        MarketEvidenceKind.TRADE_PRICE,
        MarketEvidenceKind.TRADE_QUANTITY,
        MarketEvidenceKind.TOP_OF_BOOK_BID_PRICE,
        MarketEvidenceKind.TOP_OF_BOOK_BID_QUANTITY,
        MarketEvidenceKind.TOP_OF_BOOK_ASK_PRICE,
        MarketEvidenceKind.TOP_OF_BOOK_ASK_QUANTITY,
        MarketEvidenceKind.MARK_PRICE,
        MarketEvidenceKind.INDEX_PRICE,
    }
)


class ObservationMarketEvidenceOrigin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    origin_kind: Literal[MarketEvidenceOriginKind.OBSERVATION] = (
        MarketEvidenceOriginKind.OBSERVATION
    )
    observation_id: MarketObservationId

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("observation_id", mode="before")
    @classmethod
    def _revalidate_observation_id(cls, value: object) -> MarketObservationId:
        observation_id = _revalidate_domain_id(MarketObservationId, value)
        if not _MARKET_OBSERVATION_ID_RE.fullmatch(str(observation_id)):
            raise ValueError(
                "observation_id must match market-observation:<64 lowercase hex>"
            )
        return observation_id


class SourceHealthMarketEvidenceOrigin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    origin_kind: Literal[MarketEvidenceOriginKind.SOURCE_HEALTH] = (
        MarketEvidenceOriginKind.SOURCE_HEALTH
    )
    health_snapshot_id: MarketHealthSnapshotId

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("health_snapshot_id", mode="before")
    @classmethod
    def _revalidate_health_snapshot_id(cls, value: object) -> MarketHealthSnapshotId:
        health_id = _revalidate_domain_id(MarketHealthSnapshotId, value)
        if not _MARKET_HEALTH_ID_RE.fullmatch(str(health_id)):
            raise ValueError("health_snapshot_id must match market-health:<64 lowercase hex>")
        return health_id


MarketEvidenceOrigin = Annotated[
    ObservationMarketEvidenceOrigin | SourceHealthMarketEvidenceOrigin,
    Field(discriminator="origin_kind"),
]


class DecimalMarketEvidenceValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    value_kind: Literal[MarketEvidenceValueKind.DECIMAL] = (
        MarketEvidenceValueKind.DECIMAL
    )
    value: Decimal

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("value", mode="before")
    @classmethod
    def _coerce_value(cls, value: object) -> Decimal:
        return _coerce_decimal(value)


class IntegerMarketEvidenceValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    value_kind: Literal[MarketEvidenceValueKind.INTEGER] = (
        MarketEvidenceValueKind.INTEGER
    )
    value: int

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("value", mode="before")
    @classmethod
    def _validate_value(cls, value: object) -> int:
        return _strict_non_negative_int(value, "integer evidence value")


class TextMarketEvidenceValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    value_kind: Literal[MarketEvidenceValueKind.TEXT] = MarketEvidenceValueKind.TEXT
    value: str

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value: str) -> str:
        return _trimmed(value, "text evidence value")


class TextTupleMarketEvidenceValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    value_kind: Literal[MarketEvidenceValueKind.TEXT_TUPLE] = (
        MarketEvidenceValueKind.TEXT_TUPLE
    )
    value: tuple[str, ...]

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_trimmed(item, "text tuple evidence value") for item in value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("text tuple evidence value must be unique")
        if normalized != tuple(sorted(normalized)):
            raise ValueError("text tuple evidence value must be sorted lexically")
        return normalized


MarketEvidenceValue = Annotated[
    DecimalMarketEvidenceValue
    | IntegerMarketEvidenceValue
    | TextMarketEvidenceValue
    | TextTupleMarketEvidenceValue,
    Field(discriminator="value_kind"),
]


class MarketEvidenceItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    evidence_item_id: MarketEvidenceItemId
    evidence_kind: MarketEvidenceKind
    origin: MarketEvidenceOrigin
    unit: MarketEvidenceUnit
    value: MarketEvidenceValue

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("evidence_item_id", mode="before")
    @classmethod
    def _revalidate_evidence_item_id(cls, value: object) -> MarketEvidenceItemId:
        item_id = _revalidate_domain_id(MarketEvidenceItemId, value)
        if not _MARKET_EVIDENCE_ITEM_ID_RE.fullmatch(str(item_id)):
            raise ValueError(
                "evidence_item_id must match market-evidence-item:<64 lowercase hex>"
            )
        return item_id

    @field_validator("origin", mode="before")
    @classmethod
    def _revalidate_origin(cls, value: object) -> object:
        return _market_evidence_origin_model(value).model_dump()

    @field_validator("value", mode="before")
    @classmethod
    def _revalidate_value(cls, value: object) -> object:
        return _market_evidence_value_model(value).model_dump()

    @model_validator(mode="after")
    def _validate_item(self) -> Self:
        _validate_evidence_kind_matrix(
            evidence_kind=self.evidence_kind,
            origin=self.origin,
            unit=self.unit,
            value=self.value,
        )
        expected = build_market_evidence_item_id(
            evidence_kind=self.evidence_kind,
            origin=self.origin,
            unit=self.unit,
            value=self.value,
        )
        if self.evidence_item_id != expected:
            raise ValueError("evidence_item_id must match deterministic evidence item ID")
        return self


class MarketEvidenceBuilderDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    builder_id: Literal["cross-venue-frame-direct-evidence"] = (
        "cross-venue-frame-direct-evidence"
    )
    builder_version: Literal["1"] = "1"
    supported_evidence_kinds: tuple[MarketEvidenceKind, ...]
    builder_fingerprint: str

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("supported_evidence_kinds")
    @classmethod
    def _validate_supported_kinds(
        cls,
        value: tuple[MarketEvidenceKind, ...],
    ) -> tuple[MarketEvidenceKind, ...]:
        if not value:
            raise ValueError("supported_evidence_kinds must be non-empty")
        if len(value) != len(set(value)):
            raise ValueError("supported_evidence_kinds must be unique")
        canonical = _all_market_evidence_kinds()
        if value != canonical:
            raise ValueError("supported_evidence_kinds must be the complete v1 set")
        return value

    @field_validator("builder_fingerprint")
    @classmethod
    def _validate_builder_fingerprint(cls, value: str) -> str:
        value = _trimmed(value, "builder_fingerprint")
        if not _MARKET_EVIDENCE_BUILDER_RE.fullmatch(value):
            raise ValueError(
                "builder_fingerprint must match market-evidence-builder:<64 lowercase hex>"
            )
        return value

    @model_validator(mode="after")
    def _validate_descriptor(self) -> Self:
        expected = build_market_evidence_builder_fingerprint(
            builder_id=self.builder_id,
            builder_version=self.builder_version,
            supported_evidence_kinds=self.supported_evidence_kinds,
        )
        if self.builder_fingerprint != expected:
            raise ValueError("builder_fingerprint must match descriptor")
        return self


class MarketEvidenceSet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    evidence_set_id: MarketEvidenceSetId
    builder: MarketEvidenceBuilderDescriptor
    source_frame: CrossVenueMarketFrame
    items: tuple[MarketEvidenceItem, ...]

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("evidence_set_id", mode="before")
    @classmethod
    def _revalidate_evidence_set_id(cls, value: object) -> MarketEvidenceSetId:
        set_id = _revalidate_domain_id(MarketEvidenceSetId, value)
        if not _MARKET_EVIDENCE_SET_ID_RE.fullmatch(str(set_id)):
            raise ValueError(
                "evidence_set_id must match market-evidence-set:<64 lowercase hex>"
            )
        return set_id

    @field_validator("builder", mode="before")
    @classmethod
    def _revalidate_builder(cls, value: object) -> MarketEvidenceBuilderDescriptor:
        return _revalidate_model(MarketEvidenceBuilderDescriptor, value)

    @field_validator("source_frame", mode="before")
    @classmethod
    def _revalidate_source_frame(cls, value: object) -> CrossVenueMarketFrame:
        return _revalidate_model(CrossVenueMarketFrame, value)

    @field_validator("items", mode="before")
    @classmethod
    def _revalidate_items(cls, value: object) -> tuple[MarketEvidenceItem, ...]:
        if not isinstance(value, tuple | list):
            raise ValueError("items must be a tuple or list")
        return tuple(_revalidate_model(MarketEvidenceItem, item) for item in value)

    @model_validator(mode="after")
    def _validate_set(self) -> Self:
        _validate_canonical_items(self.items)
        expected_items = derive_market_evidence_items(
            source_frame=self.source_frame,
            builder=self.builder,
        )
        if self.items != expected_items:
            raise ValueError("items must match exact source-frame derivation")
        expected = build_market_evidence_set_id(
            builder=self.builder,
            source_frame=self.source_frame,
            items=self.items,
        )
        if self.evidence_set_id != expected:
            raise ValueError("evidence_set_id must match deterministic evidence set ID")
        return self


class TechnicalEvidence(BaseModel):
    """Analytical evidence; not an order, trade, or selected target."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: EvidenceId
    instrument: InstrumentSymbol
    source_kind: EvidenceSourceKind
    source_id: str
    direction: EvidenceDirection
    confidence: Decimal | None = None
    tags: tuple[str, ...] = ()
    notes: str | None = None

    @field_validator("instrument", mode="before")
    @classmethod
    def _coerce_instrument(cls, value: object) -> InstrumentSymbol:
        return _coerce_instrument(value)

    @field_validator("source_id")
    @classmethod
    def _validate_source_id(cls, value: str) -> str:
        return _trimmed(value, "source_id")

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return _coerce_decimal(value)

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, value: Decimal | None) -> Decimal | None:
        return _optional_probability(value, "confidence")

    @field_validator("tags")
    @classmethod
    def _validate_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_trimmed_tuple(value, "tags")

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, value: str | None) -> str | None:
        return _optional_trimmed(value, "notes")


class EvidenceSet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: InstrumentSymbol
    evidence: tuple[TechnicalEvidence, ...] = ()

    @field_validator("instrument", mode="before")
    @classmethod
    def _coerce_instrument(cls, value: object) -> InstrumentSymbol:
        return _coerce_instrument(value)

    @field_validator("evidence", mode="before")
    @classmethod
    def _revalidate_evidence(cls, value: object) -> tuple[TechnicalEvidence, ...]:
        if value is None:
            return ()
        if not isinstance(value, tuple | list):
            raise ValueError("evidence must be a tuple or list")
        return tuple(
            TechnicalEvidence.model_validate(
                item.model_dump() if isinstance(item, TechnicalEvidence) else item
            )
            for item in value
        )

    @model_validator(mode="after")
    def _validate_evidence(self) -> Self:
        seen: set[EvidenceId] = set()
        for item in self.evidence:
            if item.instrument != self.instrument:
                raise ValueError("evidence instrument must match evidence set instrument")
            if item.evidence_id in seen:
                raise ValueError("duplicate evidence_id is not allowed")
            seen.add(item.evidence_id)
        return self

    def has_source_kind(self, kind: EvidenceSourceKind) -> bool:
        return any(item.source_kind is kind for item in self.evidence)

    def directions(self) -> frozenset[EvidenceDirection]:
        return frozenset(item.direction for item in self.evidence)


def build_market_evidence_item_id(
    *,
    evidence_kind: MarketEvidenceKind,
    origin: MarketEvidenceOrigin,
    unit: MarketEvidenceUnit,
    value: MarketEvidenceValue,
) -> MarketEvidenceItemId:
    evidence_kind = MarketEvidenceKind(evidence_kind)
    unit = MarketEvidenceUnit(unit)
    origin = _market_evidence_origin_model(origin)
    value = _market_evidence_value_model(value)
    _validate_evidence_kind_matrix(
        evidence_kind=evidence_kind,
        origin=origin,
        unit=unit,
        value=value,
    )
    material = {
        "schema_version": 1,
        "evidence_kind": evidence_kind.value,
        "origin": origin.model_dump(mode="json"),
        "unit": unit.value,
        "value": value.model_dump(mode="json"),
    }
    return MarketEvidenceItemId.from_str(
        f"market-evidence-item:{_sha256_text(_canonical_json(material))}"
    )


def build_market_evidence_builder_fingerprint(
    *,
    builder_id: str,
    builder_version: str,
    supported_evidence_kinds: tuple[MarketEvidenceKind, ...],
) -> str:
    builder_id = _trimmed(builder_id, "builder_id")
    builder_version = _trimmed(builder_version, "builder_version")
    supported_evidence_kinds = tuple(
        MarketEvidenceKind(kind) for kind in supported_evidence_kinds
    )
    if supported_evidence_kinds != _all_market_evidence_kinds():
        raise ValueError("supported_evidence_kinds must be the complete v1 set")
    material = {
        "schema_version": 1,
        "builder_id": builder_id,
        "builder_version": builder_version,
        "supported_evidence_kinds": [kind.value for kind in supported_evidence_kinds],
    }
    return f"market-evidence-builder:{_sha256_text(_canonical_json(material))}"


def build_market_evidence_builder_descriptor() -> MarketEvidenceBuilderDescriptor:
    supported = _all_market_evidence_kinds()
    fingerprint = build_market_evidence_builder_fingerprint(
        builder_id="cross-venue-frame-direct-evidence",
        builder_version="1",
        supported_evidence_kinds=supported,
    )
    return MarketEvidenceBuilderDescriptor(
        supported_evidence_kinds=supported,
        builder_fingerprint=fingerprint,
    )


def derive_market_evidence_items(
    *,
    source_frame: CrossVenueMarketFrame,
    builder: MarketEvidenceBuilderDescriptor,
) -> tuple[MarketEvidenceItem, ...]:
    source_frame = _revalidate_model(CrossVenueMarketFrame, source_frame)
    builder = _revalidate_model(MarketEvidenceBuilderDescriptor, builder)
    items: list[MarketEvidenceItem] = []
    for observation in source_frame.observations:
        items.extend(_derive_observation_items(observation, builder))
    for snapshot in source_frame.source_health:
        items.extend(_derive_health_items(snapshot, builder))
    ordered = tuple(sorted(items, key=market_evidence_item_key))
    _validate_canonical_items(ordered)
    return ordered


def build_market_evidence_set_id(
    *,
    builder: MarketEvidenceBuilderDescriptor,
    source_frame: CrossVenueMarketFrame,
    items: tuple[MarketEvidenceItem, ...],
) -> MarketEvidenceSetId:
    builder = _revalidate_model(MarketEvidenceBuilderDescriptor, builder)
    source_frame = _revalidate_model(CrossVenueMarketFrame, source_frame)
    items = tuple(_revalidate_model(MarketEvidenceItem, item) for item in items)
    _validate_canonical_items(items)
    expected_items = derive_market_evidence_items(
        source_frame=source_frame,
        builder=builder,
    )
    if items != expected_items:
        raise ValueError("items must match exact source-frame derivation")
    material = {
        "schema_version": 1,
        "builder": builder.model_dump(mode="json"),
        "source_frame": source_frame.model_dump(mode="json"),
        "items": [item.model_dump(mode="json") for item in items],
    }
    return MarketEvidenceSetId.from_str(
        f"market-evidence-set:{_sha256_text(_canonical_json(material))}"
    )


def build_market_evidence_set(
    *,
    builder: MarketEvidenceBuilderDescriptor,
    source_frame: CrossVenueMarketFrame,
    items: tuple[MarketEvidenceItem, ...],
) -> MarketEvidenceSet:
    evidence_set_id = build_market_evidence_set_id(
        builder=builder,
        source_frame=source_frame,
        items=items,
    )
    return MarketEvidenceSet(
        evidence_set_id=evidence_set_id,
        builder=builder,
        source_frame=source_frame,
        items=items,
    )


def market_evidence_item_key(item: MarketEvidenceItem) -> tuple[str, str, str]:
    item = _revalidate_model(MarketEvidenceItem, item)
    return (
        item.origin.origin_kind.value,
        _origin_deterministic_id(item.origin),
        item.evidence_kind.value,
    )


def _derive_observation_items(
    observation: NormalizedMarketObservation,
    builder: MarketEvidenceBuilderDescriptor,
) -> tuple[MarketEvidenceItem, ...]:
    observation = _revalidate_model(NormalizedMarketObservation, observation)
    origin = ObservationMarketEvidenceOrigin(observation_id=observation.observation_id)
    payload = observation.payload
    if isinstance(payload, TradeObservationPayload):
        return (
            _item(
                builder,
                MarketEvidenceKind.TRADE_PRICE,
                origin,
                MarketEvidenceUnit.PRICE,
                _decimal_value(payload.price),
            ),
            _item(
                builder,
                MarketEvidenceKind.TRADE_QUANTITY,
                origin,
                MarketEvidenceUnit.QUANTITY,
                _decimal_value(payload.quantity),
            ),
            _item(
                builder,
                MarketEvidenceKind.TRADE_AGGRESSOR_SIDE,
                origin,
                MarketEvidenceUnit.ENUM,
                _text_value(payload.aggressor_side.value),
            ),
        )
    if isinstance(payload, TopOfBookObservationPayload):
        return (
            _item(
                builder,
                MarketEvidenceKind.TOP_OF_BOOK_BID_PRICE,
                origin,
                MarketEvidenceUnit.PRICE,
                _decimal_value(payload.bid_price),
            ),
            _item(
                builder,
                MarketEvidenceKind.TOP_OF_BOOK_BID_QUANTITY,
                origin,
                MarketEvidenceUnit.QUANTITY,
                _decimal_value(payload.bid_quantity),
            ),
            _item(
                builder,
                MarketEvidenceKind.TOP_OF_BOOK_ASK_PRICE,
                origin,
                MarketEvidenceUnit.PRICE,
                _decimal_value(payload.ask_price),
            ),
            _item(
                builder,
                MarketEvidenceKind.TOP_OF_BOOK_ASK_QUANTITY,
                origin,
                MarketEvidenceUnit.QUANTITY,
                _decimal_value(payload.ask_quantity),
            ),
            _item(
                builder,
                MarketEvidenceKind.TOP_OF_BOOK_QUOTE_SEMANTICS,
                origin,
                MarketEvidenceUnit.ENUM,
                _text_value(payload.quote_semantics.value),
            ),
        )
    if isinstance(payload, MarkPriceObservationPayload):
        return (
            _item(
                builder,
                MarketEvidenceKind.MARK_PRICE,
                origin,
                MarketEvidenceUnit.PRICE,
                _decimal_value(payload.price),
            ),
        )
    if isinstance(payload, IndexPriceObservationPayload):
        return (
            _item(
                builder,
                MarketEvidenceKind.INDEX_PRICE,
                origin,
                MarketEvidenceUnit.PRICE,
                _decimal_value(payload.price),
            ),
        )
    raise ValueError("unsupported market observation payload for evidence")


def _derive_health_items(
    snapshot: MarketSourceHealthSnapshot,
    builder: MarketEvidenceBuilderDescriptor,
) -> tuple[MarketEvidenceItem, ...]:
    snapshot = _revalidate_model(MarketSourceHealthSnapshot, snapshot)
    origin = SourceHealthMarketEvidenceOrigin(
        health_snapshot_id=snapshot.health_snapshot_id,
    )
    items = [
        _item(
            builder,
            MarketEvidenceKind.SOURCE_HEALTH_STATE,
            origin,
            MarketEvidenceUnit.ENUM,
            _text_value(snapshot.state.value),
        ),
        _item(
            builder,
            MarketEvidenceKind.SOURCE_HEALTH_ISSUES,
            origin,
            MarketEvidenceUnit.ENUM_SET,
            _text_tuple_value(tuple(issue.value for issue in snapshot.issues)),
        ),
        _item(
            builder,
            MarketEvidenceKind.SOURCE_HEALTH_RECONNECT_GENERATION,
            origin,
            MarketEvidenceUnit.COUNT,
            _integer_value(snapshot.reconnect_generation),
        ),
        _item(
            builder,
            MarketEvidenceKind.SOURCE_HEALTH_CONSECUTIVE_FAILURES,
            origin,
            MarketEvidenceUnit.COUNT,
            _integer_value(snapshot.consecutive_failures),
        ),
    ]
    if snapshot.last_sequence is not None:
        items.append(
            _item(
                builder,
                MarketEvidenceKind.SOURCE_HEALTH_LAST_SEQUENCE,
                origin,
                MarketEvidenceUnit.SEQUENCE,
                _integer_value(snapshot.last_sequence),
            )
        )
    return tuple(items)


def _item(
    builder: MarketEvidenceBuilderDescriptor,
    evidence_kind: MarketEvidenceKind,
    origin: MarketEvidenceOrigin,
    unit: MarketEvidenceUnit,
    value: MarketEvidenceValue,
) -> MarketEvidenceItem:
    if evidence_kind not in builder.supported_evidence_kinds:
        raise ValueError("builder does not support evidence kind")
    evidence_item_id = build_market_evidence_item_id(
        evidence_kind=evidence_kind,
        origin=origin,
        unit=unit,
        value=value,
    )
    return MarketEvidenceItem(
        evidence_item_id=evidence_item_id,
        evidence_kind=evidence_kind,
        origin=origin,
        unit=unit,
        value=value,
    )


def _decimal_value(value: Decimal) -> DecimalMarketEvidenceValue:
    return DecimalMarketEvidenceValue(value=value)


def _integer_value(value: int) -> IntegerMarketEvidenceValue:
    return IntegerMarketEvidenceValue(value=value)


def _text_value(value: str) -> TextMarketEvidenceValue:
    return TextMarketEvidenceValue(value=value)


def _text_tuple_value(value: tuple[str, ...]) -> TextTupleMarketEvidenceValue:
    return TextTupleMarketEvidenceValue(value=value)


def _validate_evidence_kind_matrix(
    *,
    evidence_kind: MarketEvidenceKind,
    origin: MarketEvidenceOrigin,
    unit: MarketEvidenceUnit,
    value: MarketEvidenceValue,
) -> None:
    expected_origin, expected_value, expected_unit = _KIND_MATRIX[evidence_kind]
    if origin.origin_kind is not expected_origin:
        raise ValueError("market evidence origin kind does not match evidence kind")
    if value.value_kind is not expected_value:
        raise ValueError("market evidence value kind does not match evidence kind")
    if unit is not expected_unit:
        raise ValueError("market evidence unit does not match evidence kind")
    if evidence_kind in _POSITIVE_DECIMAL_KINDS:
        decimal_value = _expect_decimal_value(value)
        if decimal_value <= 0:
            raise ValueError("price and quantity evidence values must be positive")


def _validate_canonical_items(items: tuple[MarketEvidenceItem, ...]) -> None:
    keys = tuple(market_evidence_item_key(item) for item in items)
    if keys != tuple(sorted(keys)):
        raise ValueError("market evidence items must be sorted by canonical key")
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate market evidence semantic key")
    ids = tuple(str(item.evidence_item_id) for item in items)
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate market evidence item ID")


def _origin_deterministic_id(origin: MarketEvidenceOrigin) -> str:
    if isinstance(origin, ObservationMarketEvidenceOrigin):
        return str(origin.observation_id)
    return str(origin.health_snapshot_id)


def _expect_decimal_value(value: MarketEvidenceValue) -> Decimal:
    if not isinstance(value, DecimalMarketEvidenceValue):
        raise ValueError("expected decimal evidence value")
    return value.value


def _market_evidence_origin_model(value: object) -> MarketEvidenceOrigin:
    if isinstance(value, ObservationMarketEvidenceOrigin):
        return ObservationMarketEvidenceOrigin.model_validate(value.model_dump())
    if isinstance(value, SourceHealthMarketEvidenceOrigin):
        return SourceHealthMarketEvidenceOrigin.model_validate(value.model_dump())
    if isinstance(value, Mapping):
        origin_kind = value.get("origin_kind")
        if origin_kind == MarketEvidenceOriginKind.OBSERVATION.value:
            return ObservationMarketEvidenceOrigin.model_validate(value)
        if origin_kind == MarketEvidenceOriginKind.SOURCE_HEALTH.value:
            return SourceHealthMarketEvidenceOrigin.model_validate(value)
    raise ValueError("unsupported market evidence origin")


def _market_evidence_value_model(value: object) -> MarketEvidenceValue:
    model_types = (
        DecimalMarketEvidenceValue,
        IntegerMarketEvidenceValue,
        TextMarketEvidenceValue,
        TextTupleMarketEvidenceValue,
    )
    for model_type in model_types:
        if isinstance(value, model_type):
            return model_type.model_validate(value.model_dump())
    if isinstance(value, Mapping):
        value_kind = value.get("value_kind")
        if isinstance(value_kind, str):
            by_kind = {
                MarketEvidenceValueKind.DECIMAL.value: DecimalMarketEvidenceValue,
                MarketEvidenceValueKind.INTEGER.value: IntegerMarketEvidenceValue,
                MarketEvidenceValueKind.TEXT.value: TextMarketEvidenceValue,
                MarketEvidenceValueKind.TEXT_TUPLE.value: TextTupleMarketEvidenceValue,
            }
            model_type = by_kind.get(value_kind)
            if model_type is not None:
                return model_type.model_validate(value)
    raise ValueError("unsupported market evidence value")


def _revalidate_domain_id[T: DomainId](id_type: type[T], value: object) -> T:
    if isinstance(value, id_type):
        return id_type.model_validate(value.model_dump())
    if isinstance(value, DomainId):
        return id_type.from_str(str(value))
    if isinstance(value, str):
        return id_type.from_str(value)
    return id_type.model_validate(value)


def _revalidate_model[T: BaseModel](model_type: type[T], value: object) -> T:
    if isinstance(value, model_type):
        model = model_type.model_validate(value.model_dump())
    else:
        model = model_type.model_validate(value)
    if type(model) is not model_type:
        raise ValueError(f"expected exact {model_type.__name__}")
    return model


def _strict_literal_one(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be the strict integer 1")
    if value != 1:
        raise ValueError(f"{field_name} must be 1")
    return value


def _strict_non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _coerce_instrument(value: object) -> InstrumentSymbol:
    if not isinstance(value, str | InstrumentSymbol | Mapping):
        raise ValueError(
            "instrument must be an InstrumentSymbol, string, or serialized mapping"
        )
    return normalize_instrument_symbol(value)


def _trimmed(value: str, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty trimmed string")
    return value


def _optional_trimmed(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _trimmed(value, field_name)


def _unique_trimmed_tuple(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = tuple(_trimmed(value, field_name) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must be unique")
    return normalized


def _coerce_decimal(value: object) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("decimal value must not be bool")
    if isinstance(value, float):
        raise ValueError("float input is prohibited")
    if isinstance(value, Decimal):
        decimal_value = value
    elif isinstance(value, int):
        decimal_value = Decimal(value)
    elif isinstance(value, str):
        if value != value.strip():
            raise ValueError("decimal string must not have leading or trailing whitespace")
        try:
            decimal_value = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"decimal string is not a valid number: {value!r}") from exc
    else:
        raise ValueError("decimal value must be Decimal, int, or string")
    if not decimal_value.is_finite():
        raise ValueError("decimal value must be finite")
    return decimal_value


def _optional_probability(value: Decimal | None, field_name: str) -> Decimal | None:
    if value is None:
        return None
    if value < 0 or value > 1:
        raise ValueError(f"{field_name} must be between 0 and 1 inclusive")
    return value
