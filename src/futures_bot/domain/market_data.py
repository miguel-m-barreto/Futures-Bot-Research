from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from math import isfinite
from types import MappingProxyType
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from futures_bot.domain.assets import AssetSymbol
from futures_bot.domain.ids import (
    DomainId,
    MarketConnectionId,
    MarketDataObservationSnapshotId,
    MarketDataReadinessDecisionId,
    MarketDataReadinessPolicyId,
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
    VENUE_PUBLIC_MARKET_DATA = "VENUE_PUBLIC_MARKET_DATA"
    VENUE_PRIVATE_ACCOUNT_MARKET_DATA = "VENUE_PRIVATE_ACCOUNT_MARKET_DATA"
    VENUE_MARK_PRICE_FEED = "VENUE_MARK_PRICE_FEED"
    VENUE_INDEX_PRICE_FEED = "VENUE_INDEX_PRICE_FEED"
    VENUE_ORDER_BOOK_FEED = "VENUE_ORDER_BOOK_FEED"
    MANUAL_REVIEWED_OBSERVATION = "MANUAL_REVIEWED_OBSERVATION"
    TEST_FIXTURE = "TEST_FIXTURE"
    UNKNOWN = "UNKNOWN"


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

        if self.observations != tuple(sorted(self.observations, key=observation_stream_key)):
            raise ValueError("frame observations must be sorted by stream key")
        if self.source_health != tuple(sorted(self.source_health, key=health_scope_key)):
            raise ValueError("frame source_health must be sorted by health scope key")

        validate_market_frame_authority_consistency(
            observations=self.observations,
            source_health=self.source_health,
        )

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


def select_latest_market_observations(
    *,
    logical_instrument: InstrumentSymbol,
    as_of: datetime,
    observations: tuple[NormalizedMarketObservation, ...],
) -> tuple[NormalizedMarketObservation, ...]:
    frame_instrument = _instrument_symbol(logical_instrument)
    frame_as_of = ensure_aware_utc(as_of)
    selected: dict[tuple[str, str, str], NormalizedMarketObservation] = {}
    for raw_observation in observations:
        observation = _revalidate_model(NormalizedMarketObservation, raw_observation)
        if observation.instrument.logical_instrument != frame_instrument:
            raise ValueError("observation logical instrument differs from frame instrument")
        if observation.provenance.received_at > frame_as_of:
            raise ValueError("observation contains future information")
        key = observation_stream_key(observation)
        current = selected.get(key)
        if current is None:
            selected[key] = observation
            continue
        comparison = _compare_market_observations(observation, current)
        if comparison > 0:
            selected[key] = observation
    return tuple(sorted(selected.values(), key=observation_stream_key))


def validate_market_frame_authority_consistency(
    *,
    observations: tuple[NormalizedMarketObservation, ...],
    source_health: tuple[MarketSourceHealthSnapshot, ...],
) -> None:
    descriptors: dict[str, MarketDataSourceDescriptor] = {}
    for descriptor in (
        *(observation.source for observation in observations),
        *(snapshot.source for snapshot in source_health),
    ):
        source_id = str(descriptor.source_id)
        existing = descriptors.get(source_id)
        if existing is None:
            descriptors[source_id] = descriptor
        elif existing != descriptor:
            raise ValueError(
                f"conflicting source descriptors share source_id {source_id!r}"
            )

    instruments: dict[str, VenueInstrumentRef] = {}
    for instrument in (
        *(observation.instrument for observation in observations),
        *(snapshot.instrument for snapshot in source_health if snapshot.instrument is not None),
    ):
        instrument_id = str(instrument.venue_instrument_id)
        existing = instruments.get(instrument_id)
        if existing is None:
            instruments[instrument_id] = instrument
        elif existing != instrument:
            raise ValueError(
                "conflicting venue instrument refs share "
                f"venue_instrument_id {instrument_id!r}"
            )


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
    instrument_scope = (
        ("SOURCE", "")
        if snapshot.instrument is None
        else ("INSTRUMENT", str(snapshot.instrument.venue_instrument_id))
    )
    observation_scope = (
        ("ALL", "")
        if snapshot.observation_kind is None
        else ("KIND", snapshot.observation_kind.value)
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


def _compare_market_observations(
    candidate: NormalizedMarketObservation,
    current: NormalizedMarketObservation,
) -> int:
    if candidate.observation_id == current.observation_id:
        return 0

    candidate_provenance = candidate.provenance
    current_provenance = current.provenance
    same_session = (
        candidate_provenance.connection_id == current_provenance.connection_id
        and candidate_provenance.reconnect_generation
        == current_provenance.reconnect_generation
    )
    if same_session:
        candidate_sequence = candidate_provenance.source_sequence
        current_sequence = current_provenance.source_sequence
        if candidate_sequence is not None and current_sequence is not None:
            if candidate_sequence > current_sequence:
                return 1
            if candidate_sequence < current_sequence:
                return -1
            raise ValueError("ambiguous latest observation for equal source sequence")
        if candidate_sequence is not None or current_sequence is not None:
            raise ValueError(
                "ambiguous latest observation with inconsistent sequence availability"
            )
        return _compare_unsequenced_same_session(candidate, current)

    if candidate_provenance.received_at > current_provenance.received_at:
        return 1
    if candidate_provenance.received_at < current_provenance.received_at:
        return -1
    raise ValueError("ambiguous latest observation across incomparable sessions")


def _compare_unsequenced_same_session(
    candidate: NormalizedMarketObservation,
    current: NormalizedMarketObservation,
) -> int:
    candidate_provenance = candidate.provenance
    current_provenance = current.provenance
    if candidate_provenance.received_at > current_provenance.received_at:
        return 1
    if candidate_provenance.received_at < current_provenance.received_at:
        return -1
    if (
        candidate_provenance.received_monotonic_ns
        > current_provenance.received_monotonic_ns
    ):
        return 1
    if (
        candidate_provenance.received_monotonic_ns
        < current_provenance.received_monotonic_ns
    ):
        return -1
    raise ValueError("ambiguous latest observation for equal same-session ordering position")


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
    MarketSourceHealthState.DEGRADED: frozenset(
        {
            MarketSourceIssueKind.CLOCK_SKEW,
            MarketSourceIssueKind.INVALID_PAYLOAD,
            MarketSourceIssueKind.OUT_OF_ORDER,
            MarketSourceIssueKind.RATE_LIMITED,
        }
    ),
    MarketSourceHealthState.STALE: frozenset(
        {
            MarketSourceIssueKind.CLOCK_SKEW,
            MarketSourceIssueKind.INVALID_PAYLOAD,
            MarketSourceIssueKind.RATE_LIMITED,
            MarketSourceIssueKind.STALE_DATA,
        }
    ),
    MarketSourceHealthState.GAP_DETECTED: frozenset(
        {
            MarketSourceIssueKind.CLOCK_SKEW,
            MarketSourceIssueKind.INVALID_PAYLOAD,
            MarketSourceIssueKind.OUT_OF_ORDER,
            MarketSourceIssueKind.RATE_LIMITED,
            MarketSourceIssueKind.SEQUENCE_GAP,
        }
    ),
    MarketSourceHealthState.RECONNECTING: frozenset(
        {
            MarketSourceIssueKind.NO_DATA,
            MarketSourceIssueKind.RATE_LIMITED,
            MarketSourceIssueKind.RECONNECTING,
            MarketSourceIssueKind.TRANSPORT_ERROR,
        }
    ),
    MarketSourceHealthState.RECOVERING: frozenset(
        {
            MarketSourceIssueKind.CLOCK_SKEW,
            MarketSourceIssueKind.INVALID_PAYLOAD,
            MarketSourceIssueKind.OUT_OF_ORDER,
            MarketSourceIssueKind.RATE_LIMITED,
            MarketSourceIssueKind.RECONNECTING,
            MarketSourceIssueKind.SEQUENCE_GAP,
            MarketSourceIssueKind.STALE_DATA,
            MarketSourceIssueKind.TRANSPORT_ERROR,
        }
    ),
    MarketSourceHealthState.DISCONNECTED: frozenset(
        {
            MarketSourceIssueKind.NO_DATA,
            MarketSourceIssueKind.TRANSPORT_ERROR,
        }
    ),
    MarketSourceHealthState.UNSUPPORTED: frozenset(
        {
            MarketSourceIssueKind.UNSUPPORTED,
        }
    ),
}


def _validate_health_state_consistency(  # noqa: PLR0912
    state: MarketSourceHealthState,
    last_received_at: datetime | None,
    last_sequence: int | None,
    issues: tuple[MarketSourceIssueKind, ...],
) -> None:
    issue_set = set(issues)
    forbidden = issue_set - _HEALTH_ALLOWED_ISSUES[state]
    if forbidden:
        forbidden_names = ", ".join(sorted(issue.value for issue in forbidden))
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
        if last_received_at is None:
            raise ValueError("GAP_DETECTED market source health requires last_received_at")
        if last_sequence is None:
            raise ValueError("GAP_DETECTED market source health requires last_sequence")
        if MarketSourceIssueKind.SEQUENCE_GAP not in issue_set:
            raise ValueError("GAP_DETECTED market source health requires SEQUENCE_GAP")
    elif state is MarketSourceHealthState.RECONNECTING:
        if MarketSourceIssueKind.RECONNECTING not in issue_set:
            raise ValueError("RECONNECTING market source health requires RECONNECTING")
    elif state is MarketSourceHealthState.RECOVERING:
        if not issue_set:
            raise ValueError("RECOVERING market source health requires at least one issue")
    elif state is MarketSourceHealthState.DISCONNECTED:
        outage_issues = {
            MarketSourceIssueKind.NO_DATA,
            MarketSourceIssueKind.TRANSPORT_ERROR,
        }
        if not (issue_set & outage_issues):
            raise ValueError("DISCONNECTED market source health requires outage issue")
    elif state is MarketSourceHealthState.UNSUPPORTED and issue_set != {
        MarketSourceIssueKind.UNSUPPORTED
    }:
        raise ValueError("UNSUPPORTED market source health requires only UNSUPPORTED")


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_datetime(value: datetime) -> str:
    return ensure_aware_utc(value).isoformat()


class MarketDataObservationKind(StrEnum):
    BEST_BID_ASK = "BEST_BID_ASK"
    MARK_PRICE = "MARK_PRICE"
    INDEX_PRICE = "INDEX_PRICE"
    LAST_TRADE = "LAST_TRADE"
    ORDER_BOOK_DEPTH = "ORDER_BOOK_DEPTH"
    FUNDING_REFERENCE = "FUNDING_REFERENCE"
    AGGREGATED_TICKER = "AGGREGATED_TICKER"
    TEST_FIXTURE = "TEST_FIXTURE"
    UNKNOWN = "UNKNOWN"


class MarketDataSourceTrust(StrEnum):
    OFFICIAL = "OFFICIAL"
    MANUAL_REVIEWED_OFFICIAL = "MANUAL_REVIEWED_OFFICIAL"
    TEST_ONLY = "TEST_ONLY"
    UNTRUSTED = "UNTRUSTED"
    UNKNOWN = "UNKNOWN"


class MarketDataSourceHealth(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    GAPPED = "GAPPED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


class MarketDataContinuityStatus(StrEnum):
    CONTINUOUS = "CONTINUOUS"
    GAP_DECLARED = "GAP_DECLARED"
    GAP_SUSPECTED = "GAP_SUSPECTED"
    SNAPSHOT_ONLY = "SNAPSHOT_ONLY"
    UNKNOWN = "UNKNOWN"


class MarketDataCompatibility(StrEnum):
    DIRECT_MATCH = "DIRECT_MATCH"
    KIND_UNSUPPORTED = "KIND_UNSUPPORTED"
    SOURCE_UNSUPPORTED = "SOURCE_UNSUPPORTED"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    NOT_COMPATIBLE = "NOT_COMPATIBLE"
    UNKNOWN = "UNKNOWN"


class MarketDataReadinessReason(StrEnum):
    READY = "READY"
    POLICY_DISABLED = "POLICY_DISABLED"
    SNAPSHOT_MISSING = "SNAPSHOT_MISSING"
    SNAPSHOT_STALE = "SNAPSHOT_STALE"
    SNAPSHOT_FUTURE_DATED = "SNAPSHOT_FUTURE_DATED"
    SOURCE_RECORD_REQUIRED = "SOURCE_RECORD_REQUIRED"
    SOURCE_KIND_UNKNOWN = "SOURCE_KIND_UNKNOWN"
    SOURCE_KIND_UNSUPPORTED = "SOURCE_KIND_UNSUPPORTED"
    SOURCE_UNTRUSTED = "SOURCE_UNTRUSTED"
    SOURCE_UNHEALTHY = "SOURCE_UNHEALTHY"
    OBSERVATION_KIND_UNKNOWN = "OBSERVATION_KIND_UNKNOWN"
    OBSERVATION_KIND_UNSUPPORTED = "OBSERVATION_KIND_UNSUPPORTED"
    CONTINUITY_UNKNOWN = "CONTINUITY_UNKNOWN"
    CONTINUITY_GAPPED = "CONTINUITY_GAPPED"
    VENUE_MISMATCH = "VENUE_MISMATCH"
    INSTRUMENT_MISMATCH = "INSTRUMENT_MISMATCH"
    BID_MISSING = "BID_MISSING"
    ASK_MISSING = "ASK_MISSING"
    BID_ASK_CROSSED = "BID_ASK_CROSSED"
    MARK_PRICE_MISSING = "MARK_PRICE_MISSING"
    INDEX_PRICE_MISSING = "INDEX_PRICE_MISSING"
    LAST_PRICE_MISSING = "LAST_PRICE_MISSING"
    DEPTH_NOTIONAL_MISSING = "DEPTH_NOTIONAL_MISSING"
    DEPTH_REFERENCE_ASSET_MISSING = "DEPTH_REFERENCE_ASSET_MISSING"
    DEPTH_REFERENCE_ASSET_MISMATCH = "DEPTH_REFERENCE_ASSET_MISMATCH"
    SPREAD_MISSING = "SPREAD_MISSING"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    SEQUENCE_REQUIRED = "SEQUENCE_REQUIRED"
    SEQUENCE_GAP_DECLARED = "SEQUENCE_GAP_DECLARED"
    NOT_READY = "NOT_READY"
    UNKNOWN = "UNKNOWN"


class MarketDataObservationSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: MarketDataObservationSnapshotId | None = None
    venue_id: str
    instrument_id: str
    observation_kind: MarketDataObservationKind
    best_bid_price: Decimal | None = None
    best_ask_price: Decimal | None = None
    mark_price: Decimal | None = None
    index_price: Decimal | None = None
    last_trade_price: Decimal | None = None
    depth_reference_asset: AssetSymbol | None = None
    depth_notional: Decimal | None = None
    spread_bps: Decimal | None = None
    sequence_number: int | None = None
    previous_sequence_number: int | None = None
    continuity_status: MarketDataContinuityStatus
    observed_at: datetime
    captured_at: datetime
    source_kind: MarketDataSourceKind
    source_trust: MarketDataSourceTrust
    source_health: MarketDataSourceHealth
    source_record_id: str | None = None
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("venue_id", "instrument_id", "source_record_id")
    @classmethod
    def _validate_text(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "market data text")

    @field_validator("depth_reference_asset", mode="before")
    @classmethod
    def _coerce_asset(cls, value: object) -> AssetSymbol | None:
        return None if value is None else _readiness_asset_symbol(value)

    @field_validator(
        "best_bid_price",
        "best_ask_price",
        "mark_price",
        "index_price",
        "last_trade_price",
        "depth_notional",
        "spread_bps",
        mode="before",
    )
    @classmethod
    def _coerce_decimal_field(cls, value: object) -> Decimal | None:
        return None if value is None else _readiness_decimal(value)

    @field_validator(
        "best_bid_price",
        "best_ask_price",
        "mark_price",
        "index_price",
        "last_trade_price",
    )
    @classmethod
    def _validate_positive_price(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (not value.is_finite() or value <= 0):
            raise ValueError("market data price values must be positive")
        return value

    @field_validator("depth_notional")
    @classmethod
    def _validate_positive_depth(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (not value.is_finite() or value <= 0):
            raise ValueError("depth_notional must be positive")
        return value

    @field_validator("spread_bps")
    @classmethod
    def _validate_non_negative_spread(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (not value.is_finite() or value < 0):
            raise ValueError("spread_bps must be >= 0")
        return value

    @field_validator("sequence_number", "previous_sequence_number")
    @classmethod
    def _validate_sequence(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("sequence values must be >= 0")
        return value

    @field_validator("observed_at", "captured_at")
    @classmethod
    def _validate_timestamp(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return _readiness_freeze_json_mapping(value, path="metadata")

    @field_serializer("metadata")
    def _serialize_metadata(self, value: Mapping[str, Any]) -> Any:
        return _readiness_thaw_json_value(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.captured_at < self.observed_at:
            raise ValueError("captured_at must be >= observed_at")
        if (
            self.sequence_number is not None
            and self.previous_sequence_number is not None
            and self.sequence_number < self.previous_sequence_number
        ):
            raise ValueError("sequence_number must be >= previous_sequence_number")
        expected = deterministic_market_data_observation_snapshot_id(self)
        if self.snapshot_id is not None and self.snapshot_id != expected:
            raise ValueError("snapshot_id is not deterministic")
        object.__setattr__(self, "snapshot_id", expected)
        return self


class MarketDataReadinessPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: MarketDataReadinessPolicyId | None = None
    max_observation_age: int
    require_source_record: bool
    allowed_source_kinds: tuple[MarketDataSourceKind, ...]
    allowed_source_trust: tuple[MarketDataSourceTrust, ...]
    allowed_source_health: tuple[MarketDataSourceHealth, ...]
    allowed_observation_kinds: tuple[MarketDataObservationKind, ...]
    allowed_continuity_statuses: tuple[MarketDataContinuityStatus, ...]
    require_sequence: bool
    require_continuous_sequence: bool
    require_best_bid: bool
    require_best_ask: bool
    require_bid_ask_not_crossed: bool
    require_mark_price: bool
    require_index_price: bool
    require_last_trade_price: bool
    require_depth_notional: bool
    require_depth_reference_asset_match: bool
    require_spread_bps: bool
    max_spread_bps: Decimal | None = None
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @classmethod
    def strict_official(cls, *, metadata: Mapping[str, Any] | None = None) -> Self:
        return cls(
            max_observation_age=5_000,
            require_source_record=True,
            allowed_source_kinds=(
                MarketDataSourceKind.VENUE_PUBLIC_MARKET_DATA,
                MarketDataSourceKind.VENUE_PRIVATE_ACCOUNT_MARKET_DATA,
                MarketDataSourceKind.VENUE_MARK_PRICE_FEED,
                MarketDataSourceKind.VENUE_INDEX_PRICE_FEED,
                MarketDataSourceKind.VENUE_ORDER_BOOK_FEED,
                MarketDataSourceKind.MANUAL_REVIEWED_OBSERVATION,
            ),
            allowed_source_trust=(MarketDataSourceTrust.OFFICIAL,),
            allowed_source_health=(MarketDataSourceHealth.HEALTHY,),
            allowed_observation_kinds=(
                MarketDataObservationKind.BEST_BID_ASK,
                MarketDataObservationKind.ORDER_BOOK_DEPTH,
                MarketDataObservationKind.MARK_PRICE,
                MarketDataObservationKind.INDEX_PRICE,
                MarketDataObservationKind.LAST_TRADE,
                MarketDataObservationKind.FUNDING_REFERENCE,
            ),
            allowed_continuity_statuses=(MarketDataContinuityStatus.CONTINUOUS,),
            require_sequence=True,
            require_continuous_sequence=True,
            require_best_bid=True,
            require_best_ask=True,
            require_bid_ask_not_crossed=True,
            require_mark_price=False,
            require_index_price=False,
            require_last_trade_price=False,
            require_depth_notional=False,
            require_depth_reference_asset_match=False,
            require_spread_bps=True,
            max_spread_bps=None,
            metadata={"factory": "strict_official"} if metadata is None else metadata,
        )

    @classmethod
    def research_fixture(cls, *, metadata: Mapping[str, Any] | None = None) -> Self:
        return cls(
            max_observation_age=60_000,
            require_source_record=True,
            allowed_source_kinds=(MarketDataSourceKind.TEST_FIXTURE,),
            allowed_source_trust=(MarketDataSourceTrust.TEST_ONLY,),
            allowed_source_health=(MarketDataSourceHealth.HEALTHY,),
            allowed_observation_kinds=(MarketDataObservationKind.TEST_FIXTURE,),
            allowed_continuity_statuses=(MarketDataContinuityStatus.SNAPSHOT_ONLY,),
            require_sequence=False,
            require_continuous_sequence=False,
            require_best_bid=False,
            require_best_ask=False,
            require_bid_ask_not_crossed=False,
            require_mark_price=False,
            require_index_price=False,
            require_last_trade_price=False,
            require_depth_notional=False,
            require_depth_reference_asset_match=False,
            require_spread_bps=False,
            metadata={"factory": "research_fixture"} if metadata is None else metadata,
        )

    @field_validator("max_observation_age")
    @classmethod
    def _validate_max_observation_age(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("max_observation_age must be positive")
        return value

    @field_validator("max_spread_bps", mode="before")
    @classmethod
    def _coerce_max_spread(cls, value: object) -> Decimal | None:
        return None if value is None else _readiness_decimal(value)

    @field_validator("max_spread_bps")
    @classmethod
    def _validate_max_spread(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (not value.is_finite() or value < 0):
            raise ValueError("max_spread_bps must be >= 0")
        return value

    @field_validator("allowed_source_kinds")
    @classmethod
    def _validate_allowed_source_kinds(
        cls,
        value: tuple[MarketDataSourceKind, ...],
    ) -> tuple[MarketDataSourceKind, ...]:
        if not value:
            raise ValueError("allowed_source_kinds must be non-empty")
        kinds = tuple(sorted(set(value), key=lambda item: item.value))
        if MarketDataSourceKind.UNKNOWN in kinds:
            raise ValueError("UNKNOWN source kind is not allowed")
        return kinds

    @field_validator("allowed_source_trust")
    @classmethod
    def _validate_allowed_source_trust(
        cls,
        value: tuple[MarketDataSourceTrust, ...],
    ) -> tuple[MarketDataSourceTrust, ...]:
        if not value:
            raise ValueError("allowed_source_trust must be non-empty")
        return tuple(sorted(set(value), key=lambda item: item.value))

    @field_validator("allowed_source_health")
    @classmethod
    def _validate_allowed_source_health(
        cls,
        value: tuple[MarketDataSourceHealth, ...],
    ) -> tuple[MarketDataSourceHealth, ...]:
        if not value:
            raise ValueError("allowed_source_health must be non-empty")
        return tuple(sorted(set(value), key=lambda item: item.value))

    @field_validator("allowed_observation_kinds")
    @classmethod
    def _validate_allowed_observation_kinds(
        cls,
        value: tuple[MarketDataObservationKind, ...],
    ) -> tuple[MarketDataObservationKind, ...]:
        if not value:
            raise ValueError("allowed_observation_kinds must be non-empty")
        kinds = tuple(sorted(set(value), key=lambda item: item.value))
        if MarketDataObservationKind.UNKNOWN in kinds:
            raise ValueError("UNKNOWN observation kind is not allowed")
        return kinds

    @field_validator("allowed_continuity_statuses")
    @classmethod
    def _validate_allowed_continuity_statuses(
        cls,
        value: tuple[MarketDataContinuityStatus, ...],
    ) -> tuple[MarketDataContinuityStatus, ...]:
        if not value:
            raise ValueError("allowed_continuity_statuses must be non-empty")
        return tuple(sorted(set(value), key=lambda item: item.value))

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return _readiness_freeze_json_mapping(value, path="metadata")

    @field_serializer("metadata")
    def _serialize_metadata(self, value: Mapping[str, Any]) -> Any:
        return _readiness_thaw_json_value(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if (
            self.require_continuous_sequence
            and MarketDataContinuityStatus.UNKNOWN in self.allowed_continuity_statuses
        ):
            raise ValueError("UNKNOWN continuity is not allowed for continuous policy")
        expected = deterministic_market_data_readiness_policy_id(self)
        if self.policy_id is not None and self.policy_id != expected:
            raise ValueError("policy_id is not deterministic")
        object.__setattr__(self, "policy_id", expected)
        return self


class MarketDataReadinessDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: MarketDataReadinessDecisionId | None = None
    policy_id: MarketDataReadinessPolicyId
    venue_id: str | None = None
    instrument_id: str | None = None
    observation_kind: MarketDataObservationKind | None = None
    depth_reference_asset: AssetSymbol | None = None
    ready: bool
    reason: MarketDataReadinessReason
    compatibility: MarketDataCompatibility
    snapshot_id: MarketDataObservationSnapshotId | None = None
    checked_at: datetime
    details: Any = Field(default_factory=dict)

    @field_validator("venue_id", "instrument_id")
    @classmethod
    def _validate_text(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "market data text")

    @field_validator("depth_reference_asset", mode="before")
    @classmethod
    def _coerce_asset(cls, value: object) -> AssetSymbol | None:
        return None if value is None else _readiness_asset_symbol(value)

    @field_validator("checked_at")
    @classmethod
    def _validate_checked_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("details")
    @classmethod
    def _validate_details(cls, value: Any) -> Any:
        return _readiness_freeze_json_value(value, path="details")

    @field_serializer("details")
    def _serialize_details(self, value: Any) -> Any:
        return _readiness_thaw_json_value(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.ready and self.reason is not MarketDataReadinessReason.READY:
            raise ValueError("ready market data decision requires READY reason")
        if not self.ready and self.reason is MarketDataReadinessReason.READY:
            raise ValueError("not-ready market data decision requires non-READY reason")
        if self.ready and self.compatibility in {
            MarketDataCompatibility.UNKNOWN,
            MarketDataCompatibility.NOT_COMPATIBLE,
        }:
            raise ValueError("ready market data decision requires compatibility")
        expected = deterministic_market_data_readiness_decision_id(self)
        if self.decision_id is not None and self.decision_id != expected:
            raise ValueError("decision_id is not deterministic")
        object.__setattr__(self, "decision_id", expected)
        return self


def deterministic_market_data_observation_snapshot_id(
    snapshot: MarketDataObservationSnapshot,
) -> MarketDataObservationSnapshotId:
    digest = _readiness_digest(_readiness_model_identity(snapshot, exclude={"snapshot_id"}))
    return MarketDataObservationSnapshotId(value=f"market-data-observation:{digest}")


def deterministic_market_data_readiness_policy_id(
    policy: MarketDataReadinessPolicy,
) -> MarketDataReadinessPolicyId:
    digest = _readiness_digest(_readiness_model_identity(policy, exclude={"policy_id"}))
    return MarketDataReadinessPolicyId(value=f"market-data-policy:{digest}")


def deterministic_market_data_readiness_decision_id(
    decision: MarketDataReadinessDecision,
) -> MarketDataReadinessDecisionId:
    digest = _readiness_digest(_readiness_model_identity(decision, exclude={"decision_id"}))
    return MarketDataReadinessDecisionId(value=f"market-data-readiness:{digest}")


def _readiness_asset_symbol(value: object) -> AssetSymbol:
    if isinstance(value, AssetSymbol):
        return AssetSymbol.model_validate(value.model_dump())
    if isinstance(value, str):
        return AssetSymbol(value)
    if isinstance(value, Mapping):
        if set(value) != {"value"}:
            raise ValueError("serialized asset symbol must contain only value")
        return AssetSymbol.model_validate(dict(value))
    raise ValueError("asset symbol input must be an AssetSymbol, string, or mapping")


def _readiness_decimal(value: object) -> Decimal:
    if isinstance(value, bool | float):
        raise ValueError("decimal value must be Decimal, int, or string")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int | str):
        try:
            result = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError("decimal value is invalid") from exc
    else:
        raise ValueError("decimal value must be Decimal, int, or string")
    if not result.is_finite():
        raise ValueError("decimal value must be finite")
    return result


def _readiness_model_identity(model: BaseModel, *, exclude: set[str]) -> dict[str, Any]:
    dumped = model.model_dump()
    for key in exclude:
        dumped.pop(key, None)
    return _readiness_canonical_value(dumped)


def _readiness_digest(payload: Any) -> str:
    return hashlib.sha256(_readiness_canonical_json_bytes(payload)).hexdigest()


def _readiness_canonical_value(value: Any) -> Any:
    result: Any
    if isinstance(value, Decimal):
        result = format(value, "f")
    elif isinstance(value, datetime):
        result = ensure_aware_utc(value).isoformat()
    elif isinstance(value, StrEnum):
        result = value.value
    elif isinstance(value, BaseModel):
        result = _readiness_canonical_value(value.model_dump())
    elif isinstance(value, Mapping):
        result = {str(key): _readiness_canonical_value(item) for key, item in value.items()}
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        result = [_readiness_canonical_value(item) for item in value]
    else:
        result = value
    return result


def _readiness_canonical_json_bytes(payload: Any) -> bytes:
    payload = _readiness_canonical_value(payload)
    _readiness_validate_json_compatible(payload, path="payload")
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _readiness_validate_json_compatible(value: Any, *, path: str) -> None:
    if value is None or isinstance(value, str | bool | int):
        return
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f"{path} float must be finite")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} object keys must be strings")
            _readiness_validate_json_compatible(item, path=f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, item in enumerate(value):
            _readiness_validate_json_compatible(item, path=f"{path}[{index}]")
        return
    raise ValueError(f"{path} must be JSON-compatible")


def _readiness_freeze_json_mapping(
    value: Mapping[str, Any],
    *,
    path: str,
) -> Mapping[str, Any]:
    frozen = _readiness_freeze_json_value(value, path=path)
    if not isinstance(frozen, Mapping):
        raise ValueError(f"{path} must be a JSON-compatible object")
    return frozen


def _readiness_freeze_json_value(value: Any, *, path: str) -> Any:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f"{path} float must be finite")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} object keys must be strings")
            frozen[key] = _readiness_freeze_json_value(item, path=f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return tuple(
            _readiness_freeze_json_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    raise ValueError(f"{path} must be JSON-compatible")


def _readiness_thaw_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _readiness_thaw_json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_readiness_thaw_json_value(item) for item in value]
    return value
