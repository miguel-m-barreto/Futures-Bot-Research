from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from futures_bot.domain.assets import AssetSymbol
from futures_bot.domain.ids import (
    DomainId,
    MarketConnectionId,
    MarketDataSourceId,
    MarketFrameId,
    MarketHealthSnapshotId,
    MarketObservationId,
    VenueInstrumentId,
)
from futures_bot.domain.instruments import (
    InstrumentSymbol,
    VenueId,
    normalize_instrument_symbol,
)
from futures_bot.domain.time import ensure_aware_utc

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_MARKET_OBSERVATION_ID_RE = re.compile(r"^market-observation:[0-9a-f]{64}$")
_MARKET_HEALTH_ID_RE = re.compile(r"^market-health:[0-9a-f]{64}$")
_MARKET_FRAME_ID_RE = re.compile(r"^market-frame:[0-9a-f]{64}$")


class MarketDataSourceKind(StrEnum):
    DIRECT_VENUE = "DIRECT_VENUE"
    AGGREGATOR = "AGGREGATOR"
    REFERENCE = "REFERENCE"
    REPLAY = "REPLAY"
    SYNTHETIC = "SYNTHETIC"


class MarketTransportKind(StrEnum):
    WEBSOCKET = "WEBSOCKET"
    REST = "REST"
    FILE = "FILE"
    IN_MEMORY = "IN_MEMORY"


class VenueMarketKind(StrEnum):
    SPOT = "SPOT"
    LINEAR_PERPETUAL = "LINEAR_PERPETUAL"
    INVERSE_PERPETUAL = "INVERSE_PERPETUAL"
    DELIVERY_FUTURE = "DELIVERY_FUTURE"
    INDEX = "INDEX"
    LEVERAGED_PRODUCT = "LEVERAGED_PRODUCT"
    OTHER = "OTHER"


class MarketObservationKind(StrEnum):
    TRADE = "TRADE"
    TOP_OF_BOOK = "TOP_OF_BOOK"
    MARK_PRICE = "MARK_PRICE"
    INDEX_PRICE = "INDEX_PRICE"


class QuoteSemantics(StrEnum):
    CENTRAL_LIMIT_ORDER_BOOK = "CENTRAL_LIMIT_ORDER_BOOK"
    EXECUTABLE_REQUEST = "EXECUTABLE_REQUEST"
    INDICATIVE = "INDICATIVE"
    UNKNOWN = "UNKNOWN"


class AggressorSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    UNKNOWN = "UNKNOWN"


class MarketSourceHealthState(StrEnum):
    LIVE = "LIVE"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    GAP_DETECTED = "GAP_DETECTED"
    RECONNECTING = "RECONNECTING"
    RECOVERING = "RECOVERING"
    DISCONNECTED = "DISCONNECTED"
    UNSUPPORTED = "UNSUPPORTED"


class MarketSourceIssueKind(StrEnum):
    NO_DATA = "NO_DATA"
    STALE_DATA = "STALE_DATA"
    SEQUENCE_GAP = "SEQUENCE_GAP"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    CLOCK_SKEW = "CLOCK_SKEW"
    RECONNECTING = "RECONNECTING"
    RATE_LIMITED = "RATE_LIMITED"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"
    INVALID_PAYLOAD = "INVALID_PAYLOAD"
    UNSUPPORTED = "UNSUPPORTED"


class MarketDataSourceDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: MarketDataSourceId
    source_kind: MarketDataSourceKind
    provider: str
    transport: MarketTransportKind
    venue: VenueId | None = None
    source_version: str

    @field_validator("source_id", mode="before")
    @classmethod
    def _revalidate_source_id(cls, value: object) -> MarketDataSourceId:
        return _revalidate_domain_id(MarketDataSourceId, value)

    @field_validator("provider", "source_version")
    @classmethod
    def _validate_ascii_text(cls, value: str) -> str:
        return _trimmed_ascii(value, "source descriptor text")

    @field_validator("venue", mode="before")
    @classmethod
    def _revalidate_venue(cls, value: object) -> VenueId | None:
        return _optional_venue_id(value)

    @model_validator(mode="after")
    def _validate_source_kind(self) -> Self:
        if self.source_kind is MarketDataSourceKind.DIRECT_VENUE and self.venue is None:
            raise ValueError("DIRECT_VENUE market data sources require a venue")
        return self


class VenueInstrumentRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    venue_instrument_id: VenueInstrumentId
    venue: VenueId
    raw_symbol: str
    logical_instrument: InstrumentSymbol
    market_kind: VenueMarketKind
    settlement_asset: AssetSymbol | None = None
    collateral_asset: AssetSymbol | None = None
    contract_expiry: datetime | None = None
    metadata_version: str

    @field_validator("venue_instrument_id", mode="before")
    @classmethod
    def _revalidate_venue_instrument_id(cls, value: object) -> VenueInstrumentId:
        return _revalidate_domain_id(VenueInstrumentId, value)

    @field_validator("venue", mode="before")
    @classmethod
    def _revalidate_venue(cls, value: object) -> VenueId:
        return _venue_id(value)

    @field_validator("raw_symbol")
    @classmethod
    def _validate_raw_symbol(cls, value: str) -> str:
        return _trimmed_ascii(value, "raw_symbol")

    @field_validator("logical_instrument", mode="before")
    @classmethod
    def _coerce_logical_instrument(cls, value: object) -> InstrumentSymbol:
        return _instrument_symbol(value)

    @field_validator("settlement_asset", "collateral_asset", mode="before")
    @classmethod
    def _revalidate_asset(cls, value: object) -> AssetSymbol | None:
        return _optional_asset_symbol(value)

    @field_validator("contract_expiry")
    @classmethod
    def _validate_contract_expiry(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return ensure_aware_utc(value)

    @field_validator("metadata_version")
    @classmethod
    def _validate_metadata_version(cls, value: str) -> str:
        return _trimmed(value, "metadata_version")

    @model_validator(mode="after")
    def _validate_expiry_rules(self) -> Self:
        if self.market_kind is VenueMarketKind.DELIVERY_FUTURE:
            if self.contract_expiry is None:
                raise ValueError("DELIVERY_FUTURE instruments require contract_expiry")
        elif self.contract_expiry is not None:
            raise ValueError("only DELIVERY_FUTURE instruments may have contract_expiry")
        return self


class MarketObservationProvenance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_event_id: str
    source_event_time: datetime | None = None
    engine_time: datetime | None = None
    received_at: datetime
    received_monotonic_ns: int
    source_sequence: int | None = None
    connection_id: MarketConnectionId
    reconnect_generation: int
    raw_payload_sha256: str

    @field_validator("source_event_id")
    @classmethod
    def _validate_source_event_id(cls, value: str) -> str:
        return _trimmed(value, "source_event_id")

    @field_validator("source_event_time", "engine_time", "received_at")
    @classmethod
    def _validate_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return ensure_aware_utc(value)

    @field_validator("received_monotonic_ns", "reconnect_generation", mode="before")
    @classmethod
    def _validate_non_negative_ints(cls, value: object) -> int:
        return _strict_non_negative_int(value, "market observation provenance integer")

    @field_validator("source_sequence", mode="before")
    @classmethod
    def _validate_optional_sequence(cls, value: object) -> int | None:
        if value is None:
            return None
        return _strict_non_negative_int(value, "source_sequence")

    @field_validator("connection_id", mode="before")
    @classmethod
    def _revalidate_connection_id(cls, value: object) -> MarketConnectionId:
        return _revalidate_domain_id(MarketConnectionId, value)

    @field_validator("raw_payload_sha256")
    @classmethod
    def _validate_raw_payload_sha256(cls, value: str) -> str:
        value = _trimmed(value, "raw_payload_sha256")
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("raw_payload_sha256 must match sha256:<64 lowercase hex>")
        return value


class TradeObservationPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[MarketObservationKind.TRADE] = MarketObservationKind.TRADE
    trade_id: str
    price: Decimal
    quantity: Decimal
    aggressor_side: AggressorSide

    @field_validator("trade_id")
    @classmethod
    def _validate_trade_id(cls, value: str) -> str:
        return _trimmed(value, "trade_id")

    @field_validator("price", "quantity", mode="before")
    @classmethod
    def _coerce_decimal_field(cls, value: object) -> Decimal:
        return _decimal(value)

    @field_validator("price", "quantity")
    @classmethod
    def _validate_positive_decimal(cls, value: Decimal) -> Decimal:
        return _positive_decimal(value, "trade payload decimal")


class TopOfBookObservationPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[MarketObservationKind.TOP_OF_BOOK] = MarketObservationKind.TOP_OF_BOOK
    bid_price: Decimal
    bid_quantity: Decimal
    ask_price: Decimal
    ask_quantity: Decimal
    quote_semantics: QuoteSemantics

    @field_validator("bid_price", "bid_quantity", "ask_price", "ask_quantity", mode="before")
    @classmethod
    def _coerce_decimal_field(cls, value: object) -> Decimal:
        return _decimal(value)

    @field_validator("bid_price", "bid_quantity", "ask_price", "ask_quantity")
    @classmethod
    def _validate_positive_decimal(cls, value: Decimal) -> Decimal:
        return _positive_decimal(value, "top-of-book payload decimal")

    @model_validator(mode="after")
    def _validate_book(self) -> Self:
        if self.bid_price > self.ask_price:
            raise ValueError("top-of-book bid_price must be <= ask_price")
        return self


class MarkPriceObservationPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[MarketObservationKind.MARK_PRICE] = MarketObservationKind.MARK_PRICE
    price: Decimal

    @field_validator("price", mode="before")
    @classmethod
    def _coerce_price(cls, value: object) -> Decimal:
        return _decimal(value)

    @field_validator("price")
    @classmethod
    def _validate_price(cls, value: Decimal) -> Decimal:
        return _positive_decimal(value, "mark price")


class IndexPriceObservationPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[MarketObservationKind.INDEX_PRICE] = MarketObservationKind.INDEX_PRICE
    price: Decimal

    @field_validator("price", mode="before")
    @classmethod
    def _coerce_price(cls, value: object) -> Decimal:
        return _decimal(value)

    @field_validator("price")
    @classmethod
    def _validate_price(cls, value: Decimal) -> Decimal:
        return _positive_decimal(value, "index price")


MarketObservationPayload = Annotated[
    TradeObservationPayload
    | TopOfBookObservationPayload
    | MarkPriceObservationPayload
    | IndexPriceObservationPayload,
    Field(discriminator="kind"),
]


class NormalizedMarketObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    observation_id: MarketObservationId
    source: MarketDataSourceDescriptor
    instrument: VenueInstrumentRef
    provenance: MarketObservationProvenance
    payload: MarketObservationPayload

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("observation_id", mode="before")
    @classmethod
    def _revalidate_observation_id(cls, value: object) -> MarketObservationId:
        observation_id = _revalidate_domain_id(MarketObservationId, value)
        if not _MARKET_OBSERVATION_ID_RE.fullmatch(str(observation_id)):
            raise ValueError("observation_id must match market-observation:<64 lowercase hex>")
        return observation_id

    @field_validator("source", mode="before")
    @classmethod
    def _revalidate_source(cls, value: object) -> MarketDataSourceDescriptor:
        return _revalidate_model(MarketDataSourceDescriptor, value)

    @field_validator("instrument", mode="before")
    @classmethod
    def _revalidate_instrument(cls, value: object) -> VenueInstrumentRef:
        return _revalidate_model(VenueInstrumentRef, value)

    @field_validator("provenance", mode="before")
    @classmethod
    def _revalidate_provenance(cls, value: object) -> MarketObservationProvenance:
        return _revalidate_model(MarketObservationProvenance, value)

    @field_validator("payload", mode="before")
    @classmethod
    def _revalidate_payload(cls, value: object) -> object:
        return _payload_model_data(value)

    @model_validator(mode="after")
    def _validate_observation_id_matches(self) -> Self:
        _validate_direct_venue_matches_instrument(self.source, self.instrument)
        expected = build_market_observation_id(
            source=self.source,
            instrument=self.instrument,
            provenance=self.provenance,
            payload=self.payload,
        )
        if self.observation_id != expected:
            raise ValueError("observation_id must match deterministic market observation ID")
        return self


class MarketSourceHealthSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    health_snapshot_id: MarketHealthSnapshotId
    source: MarketDataSourceDescriptor
    instrument: VenueInstrumentRef | None = None
    observation_kind: MarketObservationKind | None = None
    state: MarketSourceHealthState
    evaluated_at: datetime
    last_received_at: datetime | None = None
    last_source_event_time: datetime | None = None
    last_sequence: int | None = None
    reconnect_generation: int
    consecutive_failures: int
    issues: tuple[MarketSourceIssueKind, ...] = ()

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

    @field_validator("source", mode="before")
    @classmethod
    def _revalidate_source(cls, value: object) -> MarketDataSourceDescriptor:
        return _revalidate_model(MarketDataSourceDescriptor, value)

    @field_validator("instrument", mode="before")
    @classmethod
    def _revalidate_instrument(cls, value: object) -> VenueInstrumentRef | None:
        if value is None:
            return None
        return _revalidate_model(VenueInstrumentRef, value)

    @field_validator("evaluated_at", "last_received_at", "last_source_event_time")
    @classmethod
    def _validate_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return ensure_aware_utc(value)

    @field_validator("last_sequence", mode="before")
    @classmethod
    def _validate_last_sequence(cls, value: object) -> int | None:
        if value is None:
            return None
        return _strict_non_negative_int(value, "last_sequence")

    @field_validator("reconnect_generation", "consecutive_failures", mode="before")
    @classmethod
    def _validate_counts(cls, value: object) -> int:
        return _strict_non_negative_int(value, "market source health count")

    @field_validator("issues")
    @classmethod
    def _validate_issues(
        cls,
        value: tuple[MarketSourceIssueKind, ...],
    ) -> tuple[MarketSourceIssueKind, ...]:
        if len(value) != len(set(value)):
            raise ValueError("market source health issues must be unique")
        canonical = tuple(sorted(value, key=lambda issue: issue.value))
        if value != canonical:
            raise ValueError("market source health issues must be sorted by enum value")
        return value

    @model_validator(mode="after")
    def _validate_snapshot(self) -> Self:
        if self.last_received_at is not None and self.last_received_at > self.evaluated_at:
            raise ValueError("last_received_at must be <= evaluated_at")
        if self.instrument is not None:
            _validate_direct_venue_matches_instrument(self.source, self.instrument)
        _validate_health_state_consistency(
            self.state,
            self.last_received_at,
            self.last_sequence,
            self.issues,
        )
        expected = build_market_health_snapshot_id(
            source=self.source,
            instrument=self.instrument,
            observation_kind=self.observation_kind,
            state=self.state,
            evaluated_at=self.evaluated_at,
            last_received_at=self.last_received_at,
            last_source_event_time=self.last_source_event_time,
            last_sequence=self.last_sequence,
            reconnect_generation=self.reconnect_generation,
            consecutive_failures=self.consecutive_failures,
            issues=self.issues,
        )
        if self.health_snapshot_id != expected:
            raise ValueError("health_snapshot_id must match deterministic market health ID")
        return self


class CrossVenueMarketFrame(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    frame_id: MarketFrameId
    logical_instrument: InstrumentSymbol
    as_of: datetime
    observations: tuple[NormalizedMarketObservation, ...]
    source_health: tuple[MarketSourceHealthSnapshot, ...]

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("frame_id", mode="before")
    @classmethod
    def _revalidate_frame_id(cls, value: object) -> MarketFrameId:
        frame_id = _revalidate_domain_id(MarketFrameId, value)
        if not _MARKET_FRAME_ID_RE.fullmatch(str(frame_id)):
            raise ValueError("frame_id must match market-frame:<64 lowercase hex>")
        return frame_id

    @field_validator("logical_instrument", mode="before")
    @classmethod
    def _coerce_logical_instrument(cls, value: object) -> InstrumentSymbol:
        return _instrument_symbol(value)

    @field_validator("as_of")
    @classmethod
    def _validate_as_of(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("observations", mode="before")
    @classmethod
    def _revalidate_observations(cls, value: object) -> tuple[NormalizedMarketObservation, ...]:
        if not isinstance(value, tuple | list):
            raise ValueError("observations must be a tuple or list")
        return tuple(_revalidate_model(NormalizedMarketObservation, item) for item in value)

    @field_validator("source_health", mode="before")
    @classmethod
    def _revalidate_source_health(cls, value: object) -> tuple[MarketSourceHealthSnapshot, ...]:
        if not isinstance(value, tuple | list):
            raise ValueError("source_health must be a tuple or list")
        return tuple(_revalidate_model(MarketSourceHealthSnapshot, item) for item in value)

    @model_validator(mode="after")
    def _validate_frame(self) -> Self:
        # 1. Logical-instrument consistency + future-data checks + stream/scope uniqueness
        observation_keys: set[tuple[str, str, str]] = set()
        for observation in self.observations:
            if observation.instrument.logical_instrument != self.logical_instrument:
                raise ValueError("frame observation logical instrument mismatch")
            if observation.provenance.received_at > self.as_of:
                raise ValueError("frame observations must not be newer than as_of")
            key = observation_stream_key(observation)
            if key in observation_keys:
                raise ValueError("frame observations must be unique by stream key")
            observation_keys.add(key)

        health_keys: set[tuple[str, str, str, str, str]] = set()
        for snapshot in self.source_health:
            if (
                snapshot.instrument is not None
                and snapshot.instrument.logical_instrument != self.logical_instrument
            ):
                raise ValueError("frame health logical instrument mismatch")
            if snapshot.evaluated_at > self.as_of:
                raise ValueError("frame source health must not be newer than as_of")
            key = health_scope_key(snapshot)
            if key in health_keys:
                raise ValueError("frame source health must be unique by health scope")
            health_keys.add(key)

        # 2. Canonical ordering
        if self.observations != tuple(sorted(self.observations, key=observation_stream_key)):
            raise ValueError("frame observations must be sorted by stream key")
        if self.source_health != tuple(sorted(self.source_health, key=health_scope_key)):
            raise ValueError("frame source_health must be sorted by health scope key")

        # 3. Authority collision checks — before ID verification
        validate_market_frame_authority_consistency(
            observations=self.observations,
            source_health=self.source_health,
        )

        # 4. Deterministic ID verification
        expected = build_market_frame_id(
            logical_instrument=self.logical_instrument,
            as_of=self.as_of,
            observations=self.observations,
            source_health=self.source_health,
        )
        if self.frame_id != expected:
            raise ValueError("frame_id must match deterministic market frame ID")
        return self


def build_market_observation_id(
    *,
    source: MarketDataSourceDescriptor,
    instrument: VenueInstrumentRef,
    provenance: MarketObservationProvenance,
    payload: MarketObservationPayload,
) -> MarketObservationId:
    revalidated_source = _revalidate_model(MarketDataSourceDescriptor, source)
    revalidated_instrument = _revalidate_model(VenueInstrumentRef, instrument)
    _validate_direct_venue_matches_instrument(revalidated_source, revalidated_instrument)
    revalidated_provenance = _revalidate_model(MarketObservationProvenance, provenance)
    revalidated_payload = _payload_model(payload)
    material = {
        "schema_version": 1,
        "instrument": revalidated_instrument.model_dump(mode="json"),
        "payload": revalidated_payload.model_dump(mode="json"),
        "provenance": revalidated_provenance.model_dump(mode="json"),
        "source": revalidated_source.model_dump(mode="json"),
    }
    return MarketObservationId.from_str(
        f"market-observation:{_sha256_text(_canonical_json(material))}"
    )


def build_normalized_market_observation(
    *,
    source: MarketDataSourceDescriptor,
    instrument: VenueInstrumentRef,
    provenance: MarketObservationProvenance,
    payload: MarketObservationPayload,
) -> NormalizedMarketObservation:
    observation_id = build_market_observation_id(
        source=source,
        instrument=instrument,
        provenance=provenance,
        payload=payload,
    )
    return NormalizedMarketObservation(
        observation_id=observation_id,
        source=source,
        instrument=instrument,
        provenance=provenance,
        payload=payload,
    )


def build_market_health_snapshot_id(  # noqa: PLR0913
    *,
    source: MarketDataSourceDescriptor,
    instrument: VenueInstrumentRef | None,
    observation_kind: MarketObservationKind | None,
    state: MarketSourceHealthState,
    evaluated_at: datetime,
    last_received_at: datetime | None,
    last_source_event_time: datetime | None,
    last_sequence: int | None,
    reconnect_generation: int,
    consecutive_failures: int,
    issues: tuple[MarketSourceIssueKind, ...],
) -> MarketHealthSnapshotId:
    state = MarketSourceHealthState(state)
    observation_kind = (
        None if observation_kind is None else MarketObservationKind(observation_kind)
    )
    evaluated_at = ensure_aware_utc(evaluated_at)
    last_received_at = None if last_received_at is None else ensure_aware_utc(last_received_at)
    last_source_event_time = (
        None
        if last_source_event_time is None
        else ensure_aware_utc(last_source_event_time)
    )
    if last_received_at is not None and last_received_at > evaluated_at:
        raise ValueError("last_received_at must be <= evaluated_at")
    if last_sequence is not None:
        last_sequence = _strict_non_negative_int(last_sequence, "last_sequence")
    reconnect_generation = _strict_non_negative_int(
        reconnect_generation,
        "reconnect_generation",
    )
    consecutive_failures = _strict_non_negative_int(
        consecutive_failures,
        "consecutive_failures",
    )
    issues = tuple(MarketSourceIssueKind(issue) for issue in issues)
    if len(issues) != len(set(issues)):
        raise ValueError("market source health issues must be unique")
    if issues != tuple(sorted(issues, key=lambda issue: issue.value)):
        raise ValueError("market source health issues must be sorted by enum value")
    revalidated_source = _revalidate_model(MarketDataSourceDescriptor, source)
    revalidated_instrument = (
        None if instrument is None else _revalidate_model(VenueInstrumentRef, instrument)
    )
    if revalidated_instrument is not None:
        _validate_direct_venue_matches_instrument(
            revalidated_source,
            revalidated_instrument,
        )
    _validate_health_state_consistency(state, last_received_at, last_sequence, issues)
    material = {
        "schema_version": 1,
        "consecutive_failures": consecutive_failures,
        "evaluated_at": _json_datetime(evaluated_at),
        "instrument": None
        if revalidated_instrument is None
        else revalidated_instrument.model_dump(mode="json"),
        "issues": [issue.value for issue in issues],
        "last_received_at": None if last_received_at is None else _json_datetime(
            last_received_at
        ),
        "last_sequence": last_sequence,
        "last_source_event_time": None
        if last_source_event_time is None
        else _json_datetime(last_source_event_time),
        "observation_kind": None if observation_kind is None else observation_kind.value,
        "reconnect_generation": reconnect_generation,
        "source": revalidated_source.model_dump(mode="json"),
        "state": state.value,
    }
    return MarketHealthSnapshotId.from_str(
        f"market-health:{_sha256_text(_canonical_json(material))}"
    )


def build_market_source_health_snapshot(  # noqa: PLR0913
    *,
    source: MarketDataSourceDescriptor,
    instrument: VenueInstrumentRef | None,
    observation_kind: MarketObservationKind | None,
    state: MarketSourceHealthState,
    evaluated_at: datetime,
    last_received_at: datetime | None,
    last_source_event_time: datetime | None,
    last_sequence: int | None,
    reconnect_generation: int,
    consecutive_failures: int,
    issues: tuple[MarketSourceIssueKind, ...],
) -> MarketSourceHealthSnapshot:
    health_snapshot_id = build_market_health_snapshot_id(
        source=source,
        instrument=instrument,
        observation_kind=observation_kind,
        state=state,
        evaluated_at=evaluated_at,
        last_received_at=last_received_at,
        last_source_event_time=last_source_event_time,
        last_sequence=last_sequence,
        reconnect_generation=reconnect_generation,
        consecutive_failures=consecutive_failures,
        issues=issues,
    )
    return MarketSourceHealthSnapshot(
        health_snapshot_id=health_snapshot_id,
        source=source,
        instrument=instrument,
        observation_kind=observation_kind,
        state=state,
        evaluated_at=evaluated_at,
        last_received_at=last_received_at,
        last_source_event_time=last_source_event_time,
        last_sequence=last_sequence,
        reconnect_generation=reconnect_generation,
        consecutive_failures=consecutive_failures,
        issues=issues,
    )


def validate_market_frame_authority_consistency(
    *,
    observations: tuple[NormalizedMarketObservation, ...],
    source_health: tuple[MarketSourceHealthSnapshot, ...],
) -> None:
    """Reject source-descriptor and venue-instrument collisions across a frame's components.

    A source_id must map to exactly one MarketDataSourceDescriptor.
    A venue_instrument_id must map to exactly one VenueInstrumentRef.
    Consistent repeated references (equal values) are allowed.
    """
    descriptors: dict[str, MarketDataSourceDescriptor] = {}
    for descriptor in (
        *(obs.source for obs in observations),
        *(snap.source for snap in source_health),
    ):
        sid = str(descriptor.source_id)
        existing = descriptors.get(sid)
        if existing is None:
            descriptors[sid] = descriptor
        elif existing != descriptor:
            raise ValueError(
                f"conflicting source descriptors share source_id {sid!r}"
            )

    instruments: dict[str, VenueInstrumentRef] = {}
    for inst in (
        *(obs.instrument for obs in observations),
        *(snap.instrument for snap in source_health if snap.instrument is not None),
    ):
        iid = str(inst.venue_instrument_id)
        existing = instruments.get(iid)
        if existing is None:
            instruments[iid] = inst
        elif existing != inst:
            raise ValueError(
                f"conflicting venue instrument refs share venue_instrument_id {iid!r}"
            )


def build_market_frame_id(
    *,
    logical_instrument: InstrumentSymbol,
    as_of: datetime,
    observations: tuple[NormalizedMarketObservation, ...],
    source_health: tuple[MarketSourceHealthSnapshot, ...],
) -> MarketFrameId:
    logical_instrument = _instrument_symbol(logical_instrument)
    as_of = ensure_aware_utc(as_of)
    revalidated_observations = tuple(
        _revalidate_model(NormalizedMarketObservation, observation)
        for observation in observations
    )
    revalidated_source_health = tuple(
        _revalidate_model(MarketSourceHealthSnapshot, snapshot)
        for snapshot in source_health
    )
    validate_market_frame_authority_consistency(
        observations=revalidated_observations,
        source_health=revalidated_source_health,
    )
    material = {
        "schema_version": 1,
        "as_of": _json_datetime(as_of),
        "health_snapshot_ids": [
            str(snapshot.health_snapshot_id) for snapshot in revalidated_source_health
        ],
        "logical_instrument": logical_instrument.model_dump(mode="json"),
        "observation_ids": [
            str(observation.observation_id) for observation in revalidated_observations
        ],
    }
    return MarketFrameId.from_str(f"market-frame:{_sha256_text(_canonical_json(material))}")


def observation_stream_key(
    observation: NormalizedMarketObservation,
) -> tuple[str, str, str]:
    observation = _revalidate_model(NormalizedMarketObservation, observation)
    return (
        str(observation.source.source_id),
        str(observation.instrument.venue_instrument_id),
        observation.payload.kind.value,
    )


def health_scope_key(
    snapshot: MarketSourceHealthSnapshot,
) -> tuple[str, str, str, str, str]:
    snapshot = _revalidate_model(MarketSourceHealthSnapshot, snapshot)
    instrument_scope = ("SOURCE", "") if snapshot.instrument is None else (
        "INSTRUMENT",
        str(snapshot.instrument.venue_instrument_id),
    )
    observation_scope = ("ALL", "") if snapshot.observation_kind is None else (
        "KIND",
        snapshot.observation_kind.value,
    )
    return (
        str(snapshot.source.source_id),
        instrument_scope[0],
        instrument_scope[1],
        observation_scope[0],
        observation_scope[1],
    )


def _revalidate_domain_id[T: DomainId](id_type: type[T], value: object) -> T:
    if isinstance(value, id_type):
        return id_type.model_validate(value.model_dump())
    if isinstance(value, str):
        return id_type(value)
    return id_type.model_validate(value)


def _revalidate_model[T: BaseModel](model_type: type[T], value: object) -> T:
    if isinstance(value, model_type):
        return model_type.model_validate(value.model_dump())
    return model_type.model_validate(value)


def _venue_id(value: object) -> VenueId:
    if isinstance(value, VenueId):
        return VenueId.model_validate(value.model_dump())
    if isinstance(value, str):
        return VenueId(value=value)
    return VenueId.model_validate(value)


def _optional_venue_id(value: object) -> VenueId | None:
    if value is None:
        return None
    return _venue_id(value)


def _asset_symbol(value: object) -> AssetSymbol:
    if isinstance(value, AssetSymbol):
        return AssetSymbol.model_validate(value.model_dump())
    if isinstance(value, str):
        return AssetSymbol(value)
    if isinstance(value, Mapping):
        if set(value) != {"value"}:
            raise ValueError("serialized asset symbol must contain only value")
        return AssetSymbol.model_validate(dict(value))
    raise ValueError("asset symbol input must be an AssetSymbol, string, or mapping")


def _optional_asset_symbol(value: object) -> AssetSymbol | None:
    if value is None:
        return None
    return _asset_symbol(value)


def _instrument_symbol(value: object) -> InstrumentSymbol:
    if not isinstance(value, str | InstrumentSymbol | Mapping):
        raise ValueError(
            "instrument must be an InstrumentSymbol, string, or serialized mapping"
        )
    return normalize_instrument_symbol(value)


def _trimmed(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty trimmed string")
    return value


def _trimmed_ascii(value: str, field_name: str) -> str:
    value = _trimmed(value, field_name)
    if not value.isascii():
        raise ValueError(f"{field_name} must contain ASCII characters only")
    return value


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


def _decimal(value: object) -> Decimal:
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


def _positive_decimal(value: Decimal, field_name: str) -> Decimal:
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    if value <= 0:
        raise ValueError(f"{field_name} must be strictly positive")
    return value


def _payload_model_data(value: object) -> object:
    if isinstance(
        value,
        (
            TradeObservationPayload,
            TopOfBookObservationPayload,
            MarkPriceObservationPayload,
            IndexPriceObservationPayload,
        ),
    ):
        return value.model_dump()
    return value


def _payload_model(value: MarketObservationPayload) -> BaseModel:
    payload = _payload_model_data(value)
    if not isinstance(payload, Mapping):
        raise ValueError("market observation payload must be a mapping or payload model")
    kind = payload.get("kind")
    if kind is MarketObservationKind.TRADE or kind == MarketObservationKind.TRADE.value:
        return TradeObservationPayload.model_validate(payload)
    if (
        kind is MarketObservationKind.TOP_OF_BOOK
        or kind == MarketObservationKind.TOP_OF_BOOK.value
    ):
        return TopOfBookObservationPayload.model_validate(payload)
    if (
        kind is MarketObservationKind.MARK_PRICE
        or kind == MarketObservationKind.MARK_PRICE.value
    ):
        return MarkPriceObservationPayload.model_validate(payload)
    if (
        kind is MarketObservationKind.INDEX_PRICE
        or kind == MarketObservationKind.INDEX_PRICE.value
    ):
        return IndexPriceObservationPayload.model_validate(payload)
    raise ValueError("market observation payload kind is unsupported")


def _validate_direct_venue_matches_instrument(
    source: MarketDataSourceDescriptor,
    instrument: VenueInstrumentRef,
) -> None:
    if source.source_kind is not MarketDataSourceKind.DIRECT_VENUE:
        return
    if source.venue != instrument.venue:
        raise ValueError("DIRECT_VENUE source venue must match instrument venue")


_HEALTH_ALLOWED_ISSUES: dict[MarketSourceHealthState, frozenset[MarketSourceIssueKind]] = {
    MarketSourceHealthState.LIVE: frozenset(),
    MarketSourceHealthState.DEGRADED: frozenset({
        MarketSourceIssueKind.OUT_OF_ORDER,
        MarketSourceIssueKind.CLOCK_SKEW,
        MarketSourceIssueKind.RATE_LIMITED,
        MarketSourceIssueKind.INVALID_PAYLOAD,
    }),
    MarketSourceHealthState.STALE: frozenset({
        MarketSourceIssueKind.STALE_DATA,
        MarketSourceIssueKind.CLOCK_SKEW,
        MarketSourceIssueKind.RATE_LIMITED,
        MarketSourceIssueKind.INVALID_PAYLOAD,
    }),
    MarketSourceHealthState.GAP_DETECTED: frozenset({
        MarketSourceIssueKind.SEQUENCE_GAP,
        MarketSourceIssueKind.OUT_OF_ORDER,
        MarketSourceIssueKind.CLOCK_SKEW,
        MarketSourceIssueKind.RATE_LIMITED,
        MarketSourceIssueKind.INVALID_PAYLOAD,
    }),
    MarketSourceHealthState.RECONNECTING: frozenset({
        MarketSourceIssueKind.RECONNECTING,
        MarketSourceIssueKind.NO_DATA,
        MarketSourceIssueKind.TRANSPORT_ERROR,
        MarketSourceIssueKind.RATE_LIMITED,
    }),
    MarketSourceHealthState.RECOVERING: frozenset({
        MarketSourceIssueKind.STALE_DATA,
        MarketSourceIssueKind.SEQUENCE_GAP,
        MarketSourceIssueKind.OUT_OF_ORDER,
        MarketSourceIssueKind.CLOCK_SKEW,
        MarketSourceIssueKind.RECONNECTING,
        MarketSourceIssueKind.RATE_LIMITED,
        MarketSourceIssueKind.TRANSPORT_ERROR,
        MarketSourceIssueKind.INVALID_PAYLOAD,
    }),
    MarketSourceHealthState.DISCONNECTED: frozenset({
        MarketSourceIssueKind.NO_DATA,
        MarketSourceIssueKind.TRANSPORT_ERROR,
    }),
    MarketSourceHealthState.UNSUPPORTED: frozenset({
        MarketSourceIssueKind.UNSUPPORTED,
    }),
}


def _validate_health_state_consistency(  # noqa: PLR0912
    state: MarketSourceHealthState,
    last_received_at: datetime | None,
    last_sequence: int | None,
    issues: tuple[MarketSourceIssueKind, ...],
) -> None:
    issue_set = set(issues)
    allowed = _HEALTH_ALLOWED_ISSUES[state]
    forbidden = issue_set - allowed
    if forbidden:
        forbidden_names = ", ".join(sorted(i.value for i in forbidden))
        raise ValueError(
            f"{state.value} market source health does not permit issues: {forbidden_names}"
        )
    if state is MarketSourceHealthState.LIVE:
        if last_received_at is None:
            raise ValueError("LIVE market source health requires last_received_at")
        if issue_set:
            raise ValueError("LIVE market source health must be issue-free")
    elif state is MarketSourceHealthState.DEGRADED:
        if last_received_at is None:
            raise ValueError("DEGRADED market source health requires last_received_at")
        if not issue_set:
            raise ValueError("DEGRADED market source health requires at least one issue")
    elif state is MarketSourceHealthState.STALE:
        if last_received_at is None:
            raise ValueError("STALE market source health requires last_received_at")
        if MarketSourceIssueKind.STALE_DATA not in issue_set:
            raise ValueError("STALE market source health requires STALE_DATA")
    elif state is MarketSourceHealthState.GAP_DETECTED:
        if MarketSourceIssueKind.SEQUENCE_GAP not in issue_set:
            raise ValueError("GAP_DETECTED market source health requires SEQUENCE_GAP")
        if last_received_at is None or last_sequence is None:
            raise ValueError(
                "GAP_DETECTED market source health requires receive and sequence context"
            )
    elif state is MarketSourceHealthState.RECONNECTING:
        if MarketSourceIssueKind.RECONNECTING not in issue_set:
            raise ValueError("RECONNECTING market source health requires RECONNECTING")
    elif state is MarketSourceHealthState.RECOVERING:
        if not issue_set:
            raise ValueError("RECOVERING market source health requires a relevant issue")
    elif state is MarketSourceHealthState.DISCONNECTED:
        if not (
            issue_set & {MarketSourceIssueKind.NO_DATA, MarketSourceIssueKind.TRANSPORT_ERROR}
        ):
            raise ValueError("DISCONNECTED market source health requires outage issue")
    elif state is MarketSourceHealthState.UNSUPPORTED:
        if MarketSourceIssueKind.UNSUPPORTED not in issue_set:
            raise ValueError("UNSUPPORTED market source health requires UNSUPPORTED")


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_datetime(value: datetime) -> str:
    return ensure_aware_utc(value).isoformat()
