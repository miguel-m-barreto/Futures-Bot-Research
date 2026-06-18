from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.ids import (
    DomainId,
    MarketConnectionId,
    MarketDataSourceId,
    MarketFrameId,
    MarketObservationId,
    ReplayMarketBindingId,
    ReplayMarketFrameLookupEntryId,
    ReplayMarketFrameProjectionId,
    ReplayMarketFrameTimelineId,
    ReplayMarketObservationProjectionId,
    VenueInstrumentId,
)
from futures_bot.domain.market_data import (
    CrossVenueMarketFrame,
    MarketDataSourceDescriptor,
    MarketDataSourceKind,
    MarketObservationKind,
    NormalizedMarketObservation,
    QuoteSemantics,
    VenueInstrumentRef,
    select_latest_market_observations,
)
from futures_bot.domain.replay import (
    ReplayInputKind,
    ReplayInstrumentRef,
)
from futures_bot.domain.time import ensure_aware_utc

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ADAPTER_FINGERPRINT_RE = re.compile(r"^replay-market-adapter:[0-9a-f]{64}$")
_BINDING_AUTHORITY_FINGERPRINT_RE = re.compile(
    r"^replay-market-binding-authority:[0-9a-f]{64}$"
)
_LOOKUP_AUTHORITY_FINGERPRINT_RE = re.compile(
    r"^replay-market-frame-lookup-authority:[0-9a-f]{64}$"
)
_CONNECTION_ID_RE = re.compile(r"^replay-market-connection:[0-9a-f]{64}$")
_MARKET_OBSERVATION_ID_RE = re.compile(r"^market-observation:[0-9a-f]{64}$")
_MARKET_FRAME_ID_RE = re.compile(r"^market-frame:[0-9a-f]{64}$")
_OBSERVATION_PROJECTION_ID_RE = re.compile(
    r"^replay-market-observation-projection:[0-9a-f]{64}$"
)
_FRAME_PROJECTION_ID_RE = re.compile(r"^replay-market-frame-projection:[0-9a-f]{64}$")
_TIMELINE_ID_RE = re.compile(r"^replay-market-frame-timeline:[0-9a-f]{64}$")
_LOOKUP_ENTRY_ID_RE = re.compile(r"^replay-market-frame-lookup-entry:[0-9a-f]{64}$")
_SUPPORTED_INPUT_KINDS = frozenset(
    {
        ReplayInputKind.TRADE,
        ReplayInputKind.ORDER_BOOK_TOP,
        ReplayInputKind.MARK_PRICE,
        ReplayInputKind.INDEX_PRICE,
    }
)
_REPLAY_TO_MARKET_OBSERVATION_KIND = {
    ReplayInputKind.TRADE: MarketObservationKind.TRADE,
    ReplayInputKind.ORDER_BOOK_TOP: MarketObservationKind.TOP_OF_BOOK,
    ReplayInputKind.MARK_PRICE: MarketObservationKind.MARK_PRICE,
    ReplayInputKind.INDEX_PRICE: MarketObservationKind.INDEX_PRICE,
}


class ReplayMarketTimestampPolicy(StrEnum):
    EVENT_TIME_AS_SOURCE_AND_RECEIVED = "EVENT_TIME_AS_SOURCE_AND_RECEIVED"


class ReplayMarketPayloadHashPolicy(StrEnum):
    CANONICAL_REPLAY_RECORD = "CANONICAL_REPLAY_RECORD"
    REQUIRE_SUPPLIED_SHA256 = "REQUIRE_SUPPLIED_SHA256"


class ReplayMarketAdapterDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    adapter_id: str
    adapter_version: str
    supported_input_kinds: tuple[ReplayInputKind, ...]
    timestamp_policy: ReplayMarketTimestampPolicy
    payload_hash_policy: ReplayMarketPayloadHashPolicy

    @field_validator("adapter_id", "adapter_version")
    @classmethod
    def _validate_ascii_text(cls, value: str) -> str:
        return _trimmed_ascii(value, "adapter descriptor text")

    @field_validator("supported_input_kinds")
    @classmethod
    def _validate_supported_input_kinds(
        cls,
        value: tuple[ReplayInputKind, ...],
    ) -> tuple[ReplayInputKind, ...]:
        if not value:
            raise ValueError("supported_input_kinds must be non-empty")
        if len(value) != len(set(value)):
            raise ValueError("supported_input_kinds must be unique")
        if value != tuple(sorted(value, key=lambda kind: kind.value)):
            raise ValueError("supported_input_kinds must be sorted by enum value")
        unsupported = tuple(kind for kind in value if kind not in _SUPPORTED_INPUT_KINDS)
        if unsupported:
            raise ValueError("unsupported replay input kind for market projection")
        return value


class ReplayMarketDataBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    binding_id: ReplayMarketBindingId
    input_dataset_id: str
    replay_instrument: ReplayInstrumentRef
    source: MarketDataSourceDescriptor
    venue_instrument: VenueInstrumentRef
    quote_semantics: QuoteSemantics
    binding_version: str

    @field_validator("binding_id", mode="before")
    @classmethod
    def _revalidate_binding_id(cls, value: object) -> ReplayMarketBindingId:
        return _revalidate_domain_id(ReplayMarketBindingId, value)

    @field_validator("input_dataset_id")
    @classmethod
    def _validate_dataset_id(cls, value: str) -> str:
        return _trimmed(value, "input_dataset_id")

    @field_validator("binding_version")
    @classmethod
    def _validate_binding_version(cls, value: str) -> str:
        return _trimmed_ascii(value, "binding_version")

    @field_validator("replay_instrument", mode="before")
    @classmethod
    def _revalidate_replay_instrument(cls, value: object) -> ReplayInstrumentRef:
        return _revalidate_model(ReplayInstrumentRef, value)

    @field_validator("source", mode="before")
    @classmethod
    def _revalidate_source(cls, value: object) -> MarketDataSourceDescriptor:
        return _revalidate_model(MarketDataSourceDescriptor, value)

    @field_validator("venue_instrument", mode="before")
    @classmethod
    def _revalidate_venue_instrument(cls, value: object) -> VenueInstrumentRef:
        return _revalidate_model(VenueInstrumentRef, value)

    @model_validator(mode="after")
    def _validate_binding(self) -> Self:
        if self.source.source_kind not in {
            MarketDataSourceKind.REPLAY,
            MarketDataSourceKind.SYNTHETIC,
        }:
            raise ValueError("replay market bindings require REPLAY or SYNTHETIC source")
        if self.replay_instrument.symbol != self.venue_instrument.raw_symbol:
            raise ValueError("replay symbol must match venue raw_symbol exactly")
        if self.source.venue is not None and self.source.venue != self.venue_instrument.venue:
            raise ValueError("source venue must match venue instrument venue when declared")
        if self.venue_instrument.settlement_asset is not None and (
            str(self.venue_instrument.settlement_asset)
            != str(self.replay_instrument.settlement_asset)
        ):
            raise ValueError("settlement asset must match replay instrument settlement")
        if self.replay_instrument.quote_asset is not None and (
            str(self.replay_instrument.quote_asset)
            != str(self.venue_instrument.logical_instrument.quote_asset)
        ):
            raise ValueError("quote asset must not conflict with venue instrument")
        return self


class ReplayMarketAdapterAuthority(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    descriptor: ReplayMarketAdapterDescriptor
    bindings: tuple[ReplayMarketDataBinding, ...]
    adapter_fingerprint: str

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("descriptor", mode="before")
    @classmethod
    def _revalidate_descriptor(cls, value: object) -> ReplayMarketAdapterDescriptor:
        return _revalidate_model(ReplayMarketAdapterDescriptor, value)

    @field_validator("bindings", mode="before")
    @classmethod
    def _revalidate_bindings(
        cls,
        value: object,
    ) -> tuple[ReplayMarketDataBinding, ...]:
        if not isinstance(value, tuple | list):
            raise ValueError("adapter authority bindings must be a tuple or list")
        bindings = tuple(_revalidate_model(ReplayMarketDataBinding, item) for item in value)
        if not bindings:
            raise ValueError("adapter authority bindings must be non-empty")
        return validate_replay_market_data_bindings(bindings)

    @field_validator("adapter_fingerprint")
    @classmethod
    def _validate_adapter_fingerprint(cls, value: str) -> str:
        return _validate_adapter_fingerprint(value)

    @model_validator(mode="after")
    def _validate_authority(self) -> Self:
        expected = build_replay_market_adapter_fingerprint(
            descriptor=self.descriptor,
            bindings=self.bindings,
        )
        if self.adapter_fingerprint != expected:
            raise ValueError("adapter_fingerprint must match descriptor and bindings")
        return self


class ReplayMarketBindingAuthority(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    descriptor: ReplayMarketAdapterDescriptor
    binding: ReplayMarketDataBinding
    binding_authority_fingerprint: str

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("descriptor", mode="before")
    @classmethod
    def _revalidate_descriptor(cls, value: object) -> ReplayMarketAdapterDescriptor:
        return _revalidate_model(ReplayMarketAdapterDescriptor, value)

    @field_validator("binding", mode="before")
    @classmethod
    def _revalidate_binding(cls, value: object) -> ReplayMarketDataBinding:
        return _revalidate_model(ReplayMarketDataBinding, value)

    @field_validator("binding_authority_fingerprint")
    @classmethod
    def _validate_binding_authority_fingerprint(cls, value: str) -> str:
        return _validate_binding_authority_fingerprint(value)

    @model_validator(mode="after")
    def _validate_authority(self) -> Self:
        expected = build_replay_market_binding_authority_fingerprint(
            descriptor=self.descriptor,
            binding=self.binding,
        )
        if self.binding_authority_fingerprint != expected:
            raise ValueError(
                "binding_authority_fingerprint must match descriptor and binding"
            )
        return self


class ReplayMarketFrameLookupEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    entry_id: ReplayMarketFrameLookupEntryId
    market_timeline_id: ReplayMarketFrameTimelineId
    replay_timeline_id: str
    replay_plan_id: str
    adapter_fingerprint: str
    event_id: str
    event_order_index: int
    event_time: datetime
    event_kind: ReplayInputKind
    observation_projection_id: ReplayMarketObservationProjectionId
    frame_projection_id: ReplayMarketFrameProjectionId
    frame_id: MarketFrameId
    triggering_observation_id: MarketObservationId
    binding_authority_fingerprint: str

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("entry_id", mode="before")
    @classmethod
    def _revalidate_entry_id(cls, value: object) -> ReplayMarketFrameLookupEntryId:
        entry_id = _revalidate_domain_id(ReplayMarketFrameLookupEntryId, value)
        if not _LOOKUP_ENTRY_ID_RE.fullmatch(str(entry_id)):
            raise ValueError("invalid replay market frame lookup entry ID")
        return entry_id

    @field_validator("market_timeline_id", mode="before")
    @classmethod
    def _revalidate_market_timeline_id(
        cls,
        value: object,
    ) -> ReplayMarketFrameTimelineId:
        return _validate_market_timeline_id(value)

    @field_validator("replay_timeline_id", "replay_plan_id", "event_id")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return _trimmed(value, "lookup entry text")

    @field_validator("adapter_fingerprint")
    @classmethod
    def _validate_adapter_fingerprint(cls, value: str) -> str:
        return _validate_adapter_fingerprint(value)

    @field_validator("event_order_index", mode="before")
    @classmethod
    def _validate_event_order_index(cls, value: object) -> int:
        return _strict_non_negative_int(value, "event_order_index")

    @field_validator("event_time")
    @classmethod
    def _validate_event_time(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("observation_projection_id", mode="before")
    @classmethod
    def _revalidate_observation_projection_id(
        cls,
        value: object,
    ) -> ReplayMarketObservationProjectionId:
        return _validate_observation_projection_id(value)

    @field_validator("frame_projection_id", mode="before")
    @classmethod
    def _revalidate_frame_projection_id(
        cls,
        value: object,
    ) -> ReplayMarketFrameProjectionId:
        return _validate_frame_projection_id(value)

    @field_validator("frame_id", mode="before")
    @classmethod
    def _revalidate_frame_id(cls, value: object) -> MarketFrameId:
        return _validate_market_frame_id(value)

    @field_validator("triggering_observation_id", mode="before")
    @classmethod
    def _revalidate_triggering_observation_id(cls, value: object) -> MarketObservationId:
        return _validate_market_observation_id(value)

    @field_validator("binding_authority_fingerprint")
    @classmethod
    def _validate_binding_authority_fingerprint(cls, value: str) -> str:
        return _validate_binding_authority_fingerprint(value)

    @model_validator(mode="after")
    def _validate_entry(self) -> Self:
        expected = build_replay_market_frame_lookup_entry_id(
            market_timeline_id=self.market_timeline_id,
            replay_timeline_id=self.replay_timeline_id,
            replay_plan_id=self.replay_plan_id,
            adapter_fingerprint=self.adapter_fingerprint,
            event_id=self.event_id,
            event_order_index=self.event_order_index,
            event_time=self.event_time,
            event_kind=self.event_kind,
            observation_projection_id=self.observation_projection_id,
            frame_projection_id=self.frame_projection_id,
            frame_id=self.frame_id,
            triggering_observation_id=self.triggering_observation_id,
            binding_authority_fingerprint=self.binding_authority_fingerprint,
        )
        if self.entry_id != expected:
            raise ValueError("entry_id must match deterministic lookup entry ID")
        return self


class ReplayMarketFrameLookupAuthority(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    market_timeline_id: ReplayMarketFrameTimelineId
    replay_timeline_id: str
    replay_plan_id: str
    adapter_fingerprint: str
    supported_event_kinds: tuple[ReplayInputKind, ...]
    entries: tuple[ReplayMarketFrameLookupEntry, ...]
    lookup_authority_fingerprint: str

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("market_timeline_id", mode="before")
    @classmethod
    def _revalidate_market_timeline_id(
        cls,
        value: object,
    ) -> ReplayMarketFrameTimelineId:
        return _validate_market_timeline_id(value)

    @field_validator("replay_timeline_id", "replay_plan_id")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return _trimmed(value, "lookup authority text")

    @field_validator("adapter_fingerprint")
    @classmethod
    def _validate_adapter_fingerprint(cls, value: str) -> str:
        return _validate_adapter_fingerprint(value)

    @field_validator("supported_event_kinds")
    @classmethod
    def _validate_supported_event_kinds(
        cls,
        value: tuple[ReplayInputKind, ...],
    ) -> tuple[ReplayInputKind, ...]:
        return _validate_market_projection_event_kinds(value)

    @field_validator("entries", mode="before")
    @classmethod
    def _revalidate_entries(
        cls,
        value: object,
    ) -> tuple[ReplayMarketFrameLookupEntry, ...]:
        if not isinstance(value, tuple | list):
            raise ValueError("lookup authority entries must be a tuple or list")
        entries = tuple(
            _revalidate_model(ReplayMarketFrameLookupEntry, item) for item in value
        )
        if not entries:
            raise ValueError("lookup authority entries must be non-empty")
        return entries

    @field_validator("lookup_authority_fingerprint")
    @classmethod
    def _validate_lookup_authority_fingerprint(cls, value: str) -> str:
        return _validate_lookup_authority_fingerprint(value)

    @model_validator(mode="after")
    def _validate_authority(self) -> Self:
        _validate_lookup_authority_entries(
            market_timeline_id=self.market_timeline_id,
            replay_timeline_id=self.replay_timeline_id,
            replay_plan_id=self.replay_plan_id,
            adapter_fingerprint=self.adapter_fingerprint,
            supported_event_kinds=self.supported_event_kinds,
            entries=self.entries,
        )
        expected = build_replay_market_frame_lookup_authority_fingerprint(
            market_timeline_id=self.market_timeline_id,
            replay_timeline_id=self.replay_timeline_id,
            replay_plan_id=self.replay_plan_id,
            adapter_fingerprint=self.adapter_fingerprint,
            supported_event_kinds=self.supported_event_kinds,
            entries=self.entries,
        )
        if self.lookup_authority_fingerprint != expected:
            raise ValueError("lookup_authority_fingerprint must match lookup authority")
        return self


class ReplayMarketFrameLookupDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    market_timeline_id: ReplayMarketFrameTimelineId
    replay_timeline_id: str
    replay_plan_id: str
    adapter_fingerprint: str
    lookup_authority_fingerprint: str
    supported_event_kinds: tuple[ReplayInputKind, ...]

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("market_timeline_id", mode="before")
    @classmethod
    def _revalidate_market_timeline_id(
        cls,
        value: object,
    ) -> ReplayMarketFrameTimelineId:
        timeline_id = _revalidate_domain_id(ReplayMarketFrameTimelineId, value)
        if not _TIMELINE_ID_RE.fullmatch(str(timeline_id)):
            raise ValueError("invalid replay market frame timeline ID")
        return timeline_id

    @field_validator("replay_timeline_id", "replay_plan_id")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return _trimmed(value, "market frame lookup descriptor text")

    @field_validator("adapter_fingerprint")
    @classmethod
    def _validate_adapter_fingerprint(cls, value: str) -> str:
        return _validate_adapter_fingerprint(value)

    @field_validator("lookup_authority_fingerprint")
    @classmethod
    def _validate_lookup_authority_fingerprint(cls, value: str) -> str:
        return _validate_lookup_authority_fingerprint(value)

    @field_validator("supported_event_kinds")
    @classmethod
    def _validate_supported_event_kinds(
        cls,
        value: tuple[ReplayInputKind, ...],
    ) -> tuple[ReplayInputKind, ...]:
        return _validate_market_projection_event_kinds(value)


class ReplayMarketObservationProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    projection_id: ReplayMarketObservationProjectionId
    timeline_id: str
    event_id: str
    event_order_index: int
    event_time: datetime
    batch_id: str
    input_dataset_id: str
    record_id: str
    event_kind: ReplayInputKind
    binding_authority: ReplayMarketBindingAuthority
    observation: NormalizedMarketObservation

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("projection_id", mode="before")
    @classmethod
    def _revalidate_projection_id(
        cls,
        value: object,
    ) -> ReplayMarketObservationProjectionId:
        projection_id = _revalidate_domain_id(ReplayMarketObservationProjectionId, value)
        if not _OBSERVATION_PROJECTION_ID_RE.fullmatch(str(projection_id)):
            raise ValueError("invalid replay market observation projection ID")
        return projection_id

    @field_validator("timeline_id", "event_id", "batch_id", "input_dataset_id", "record_id")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return _trimmed(value, "projection text")

    @field_validator("event_order_index", mode="before")
    @classmethod
    def _validate_event_order_index(cls, value: object) -> int:
        return _strict_non_negative_int(value, "event_order_index")

    @field_validator("event_time")
    @classmethod
    def _validate_event_time(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("binding_authority", mode="before")
    @classmethod
    def _revalidate_binding_authority(
        cls,
        value: object,
    ) -> ReplayMarketBindingAuthority:
        return _revalidate_model(ReplayMarketBindingAuthority, value)

    @field_validator("observation", mode="before")
    @classmethod
    def _revalidate_observation(cls, value: object) -> NormalizedMarketObservation:
        return _revalidate_model(NormalizedMarketObservation, value)

    @model_validator(mode="after")
    def _validate_projection(self) -> Self:
        validate_replay_market_observation_kind(
            event_kind=self.event_kind,
            observation=self.observation,
        )
        validate_replay_market_projection_descriptor(
            event_kind=self.event_kind,
            binding_authority=self.binding_authority,
        )
        validate_replay_market_projection_binding(
            input_dataset_id=self.input_dataset_id,
            binding_authority=self.binding_authority,
            observation=self.observation,
        )
        validate_replay_market_observation_provenance(
            timeline_id=self.timeline_id,
            event_id=self.event_id,
            event_time=self.event_time,
            input_dataset_id=self.input_dataset_id,
            binding_authority=self.binding_authority,
            observation=self.observation,
        )
        expected = build_replay_market_observation_projection_id(
            timeline_id=self.timeline_id,
            event_id=self.event_id,
            event_order_index=self.event_order_index,
            event_time=self.event_time,
            batch_id=self.batch_id,
            input_dataset_id=self.input_dataset_id,
            record_id=self.record_id,
            event_kind=self.event_kind,
            binding_authority=self.binding_authority,
            observation=self.observation,
        )
        if self.projection_id != expected:
            raise ValueError("projection_id must match deterministic observation projection ID")
        return self


class ReplayMarketFrameProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    projection_id: ReplayMarketFrameProjectionId
    timeline_id: str
    event_id: str
    event_order_index: int
    event_time: datetime
    triggering_observation_projection_id: ReplayMarketObservationProjectionId
    triggering_observation_id: MarketObservationId
    frame: CrossVenueMarketFrame

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("projection_id", mode="before")
    @classmethod
    def _revalidate_projection_id(cls, value: object) -> ReplayMarketFrameProjectionId:
        projection_id = _revalidate_domain_id(ReplayMarketFrameProjectionId, value)
        if not _FRAME_PROJECTION_ID_RE.fullmatch(str(projection_id)):
            raise ValueError("invalid replay market frame projection ID")
        return projection_id

    @field_validator("timeline_id", "event_id")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return _trimmed(value, "frame projection text")

    @field_validator("event_order_index", mode="before")
    @classmethod
    def _validate_event_order_index(cls, value: object) -> int:
        return _strict_non_negative_int(value, "event_order_index")

    @field_validator("event_time")
    @classmethod
    def _validate_event_time(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("triggering_observation_projection_id", mode="before")
    @classmethod
    def _revalidate_triggering_projection_id(
        cls,
        value: object,
    ) -> ReplayMarketObservationProjectionId:
        return _validate_observation_projection_id(value)

    @field_validator("triggering_observation_id", mode="before")
    @classmethod
    def _revalidate_triggering_observation_id(cls, value: object) -> MarketObservationId:
        return _validate_market_observation_id(value)

    @field_validator("frame", mode="before")
    @classmethod
    def _revalidate_frame(cls, value: object) -> CrossVenueMarketFrame:
        return _revalidate_model(CrossVenueMarketFrame, value)

    @model_validator(mode="after")
    def _validate_projection(self) -> Self:
        if self.frame.as_of != self.event_time:
            raise ValueError("frame.as_of must match frame projection event_time")
        if not any(
            observation.observation_id == self.triggering_observation_id
            for observation in self.frame.observations
        ):
            raise ValueError("triggering observation ID must exist in frame")
        expected = build_replay_market_frame_projection_id(
            timeline_id=self.timeline_id,
            event_id=self.event_id,
            event_order_index=self.event_order_index,
            event_time=self.event_time,
            triggering_observation_projection_id=self.triggering_observation_projection_id,
            triggering_observation_id=self.triggering_observation_id,
            frame=self.frame,
        )
        if self.projection_id != expected:
            raise ValueError("projection_id must match deterministic frame projection ID")
        return self


class ReplayMarketFrameLookupResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    descriptor: ReplayMarketFrameLookupDescriptor
    entry: ReplayMarketFrameLookupEntry
    observation_projection: ReplayMarketObservationProjection
    frame_projection: ReplayMarketFrameProjection

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("descriptor", mode="before")
    @classmethod
    def _revalidate_descriptor(cls, value: object) -> ReplayMarketFrameLookupDescriptor:
        return _revalidate_model(ReplayMarketFrameLookupDescriptor, value)

    @field_validator("entry", mode="before")
    @classmethod
    def _revalidate_entry(cls, value: object) -> ReplayMarketFrameLookupEntry:
        return _revalidate_model(ReplayMarketFrameLookupEntry, value)

    @field_validator("observation_projection", mode="before")
    @classmethod
    def _revalidate_observation_projection(
        cls,
        value: object,
    ) -> ReplayMarketObservationProjection:
        return _revalidate_model(ReplayMarketObservationProjection, value)

    @field_validator("frame_projection", mode="before")
    @classmethod
    def _revalidate_frame_projection(cls, value: object) -> ReplayMarketFrameProjection:
        return _revalidate_model(ReplayMarketFrameProjection, value)

    @model_validator(mode="after")
    def _validate_result(self) -> Self:
        validate_replay_market_frame_lookup_result(
            descriptor=self.descriptor,
            entry=self.entry,
            observation_projection=self.observation_projection,
            frame_projection=self.frame_projection,
        )
        return self


class ReplayMarketFrameTimeline(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    market_timeline_id: ReplayMarketFrameTimelineId
    replay_timeline_id: str
    replay_plan_id: str
    adapter_authority: ReplayMarketAdapterAuthority
    observation_projections: tuple[ReplayMarketObservationProjection, ...]
    frame_projections: tuple[ReplayMarketFrameProjection, ...]

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("market_timeline_id", mode="before")
    @classmethod
    def _revalidate_timeline_id(cls, value: object) -> ReplayMarketFrameTimelineId:
        timeline_id = _revalidate_domain_id(ReplayMarketFrameTimelineId, value)
        if not _TIMELINE_ID_RE.fullmatch(str(timeline_id)):
            raise ValueError("invalid replay market frame timeline ID")
        return timeline_id

    @field_validator("replay_timeline_id", "replay_plan_id")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return _trimmed(value, "timeline text")

    @field_validator("adapter_authority", mode="before")
    @classmethod
    def _revalidate_adapter_authority(cls, value: object) -> ReplayMarketAdapterAuthority:
        return _revalidate_model(ReplayMarketAdapterAuthority, value)

    @field_validator("observation_projections", mode="before")
    @classmethod
    def _revalidate_observation_projections(
        cls,
        value: object,
    ) -> tuple[ReplayMarketObservationProjection, ...]:
        if not isinstance(value, tuple | list):
            raise ValueError("observation_projections must be a tuple or list")
        return tuple(_revalidate_model(ReplayMarketObservationProjection, item) for item in value)

    @field_validator("frame_projections", mode="before")
    @classmethod
    def _revalidate_frame_projections(
        cls,
        value: object,
    ) -> tuple[ReplayMarketFrameProjection, ...]:
        if not isinstance(value, tuple | list):
            raise ValueError("frame_projections must be a tuple or list")
        return tuple(_revalidate_model(ReplayMarketFrameProjection, item) for item in value)

    @model_validator(mode="after")
    def _validate_timeline(self) -> Self:
        _validate_replay_market_frame_timeline_semantics(
            replay_timeline_id=self.replay_timeline_id,
            adapter_authority=self.adapter_authority,
            observation_projections=self.observation_projections,
            frame_projections=self.frame_projections,
        )
        expected = build_replay_market_frame_timeline_id(
            replay_timeline_id=self.replay_timeline_id,
            replay_plan_id=self.replay_plan_id,
            adapter_authority=self.adapter_authority,
            observation_projections=self.observation_projections,
            frame_projections=self.frame_projections,
        )
        if self.market_timeline_id != expected:
            raise ValueError("market_timeline_id must match deterministic timeline ID")
        return self


def replay_market_binding_key(binding: ReplayMarketDataBinding) -> tuple[str, str]:
    binding = _revalidate_model(ReplayMarketDataBinding, binding)
    return (
        binding.input_dataset_id,
        _canonical_json(binding.replay_instrument.model_dump(mode="json")),
    )


def validate_replay_market_observation_kind(
    *,
    event_kind: ReplayInputKind,
    observation: NormalizedMarketObservation,
) -> None:
    observation = _revalidate_model(NormalizedMarketObservation, observation)
    expected = _REPLAY_TO_MARKET_OBSERVATION_KIND.get(ReplayInputKind(event_kind))
    if expected is None:
        raise ValueError("unsupported replay input kind for market observation")
    if observation.payload.kind is not expected:
        raise ValueError("replay event kind must match market observation payload kind")


def _validate_market_projection_event_kinds(
    value: tuple[ReplayInputKind, ...],
) -> tuple[ReplayInputKind, ...]:
    if not value:
        raise ValueError("supported_event_kinds must be non-empty")
    if len(value) != len(set(value)):
        raise ValueError("supported_event_kinds must be unique")
    if value != tuple(sorted(value, key=lambda kind: kind.value)):
        raise ValueError("supported_event_kinds must be sorted by enum value")
    unsupported = tuple(kind for kind in value if kind not in _SUPPORTED_INPUT_KINDS)
    if unsupported:
        raise ValueError("supported_event_kinds must be market projection kinds")
    return value


def validate_replay_market_projection_descriptor(
    *,
    event_kind: ReplayInputKind,
    binding_authority: ReplayMarketBindingAuthority,
) -> None:
    event_kind = ReplayInputKind(event_kind)
    binding_authority = _revalidate_model(ReplayMarketBindingAuthority, binding_authority)
    descriptor = binding_authority.descriptor
    if event_kind not in descriptor.supported_input_kinds:
        raise ValueError("projection event kind is not supported by binding authority")
    if (
        descriptor.timestamp_policy
        is not ReplayMarketTimestampPolicy.EVENT_TIME_AS_SOURCE_AND_RECEIVED
    ):
        raise ValueError("unsupported replay market timestamp policy")


def validate_replay_market_projection_binding(
    *,
    input_dataset_id: str,
    binding_authority: ReplayMarketBindingAuthority,
    observation: NormalizedMarketObservation,
) -> None:
    input_dataset_id = _trimmed(input_dataset_id, "input_dataset_id")
    binding_authority = _revalidate_model(ReplayMarketBindingAuthority, binding_authority)
    binding = binding_authority.binding
    observation = _revalidate_model(NormalizedMarketObservation, observation)
    if binding.input_dataset_id != input_dataset_id:
        raise ValueError("projection input_dataset_id must match binding")
    if observation.source != binding.source:
        raise ValueError("observation source must exactly match projection binding source")
    if observation.instrument != binding.venue_instrument:
        raise ValueError(
            "observation instrument must exactly match projection binding venue instrument"
        )


def validate_replay_market_observation_provenance(  # noqa: PLR0913
    *,
    timeline_id: str,
    event_id: str,
    event_time: datetime,
    input_dataset_id: str,
    binding_authority: ReplayMarketBindingAuthority,
    observation: NormalizedMarketObservation,
) -> None:
    _trimmed(timeline_id, "timeline_id")
    event_id = _trimmed(event_id, "event_id")
    event_time = ensure_aware_utc(event_time)
    input_dataset_id = _trimmed(input_dataset_id, "input_dataset_id")
    binding_authority = _revalidate_model(ReplayMarketBindingAuthority, binding_authority)
    observation = _revalidate_model(NormalizedMarketObservation, observation)
    validate_replay_market_projection_binding(
        input_dataset_id=input_dataset_id,
        binding_authority=binding_authority,
        observation=observation,
    )
    if observation.source.source_kind not in {
        MarketDataSourceKind.REPLAY,
        MarketDataSourceKind.SYNTHETIC,
    }:
        raise ValueError("replay market observations require REPLAY or SYNTHETIC source")
    provenance = observation.provenance
    if provenance.source_event_id != event_id:
        raise ValueError("observation source_event_id must match event_id")
    if provenance.source_event_time != event_time:
        raise ValueError("observation source_event_time must match event_time")
    if provenance.received_at != event_time:
        raise ValueError("observation received_at must match event_time")
    if provenance.engine_time is not None:
        raise ValueError("replay observation engine_time must be None")
    if provenance.received_monotonic_ns != 0:
        raise ValueError("replay observation received_monotonic_ns must be 0")
    if provenance.source_sequence is None:
        raise ValueError("observation source_sequence must be present")
    if provenance.reconnect_generation != 0:
        raise ValueError("replay observation reconnect_generation must be 0")
    expected_connection_id = build_replay_market_connection_id(
        input_dataset_id=input_dataset_id,
        binding_authority=binding_authority,
    )
    if provenance.connection_id != expected_connection_id:
        raise ValueError("observation connection_id must match deterministic replay authority")


def validate_replay_market_data_bindings(
    bindings: tuple[ReplayMarketDataBinding, ...],
) -> tuple[ReplayMarketDataBinding, ...]:
    revalidated = tuple(_revalidate_model(ReplayMarketDataBinding, binding) for binding in bindings)
    by_key: dict[tuple[str, str], ReplayMarketDataBinding] = {}
    by_binding_id: dict[str, ReplayMarketDataBinding] = {}
    by_source_id: dict[str, MarketDataSourceDescriptor] = {}
    by_instrument_id: dict[str, VenueInstrumentRef] = {}
    for binding in revalidated:
        key = replay_market_binding_key(binding)
        existing = by_key.get(key)
        if existing is not None:
            if existing != binding:
                raise ValueError("conflicting replay market bindings share a binding key")
            continue
        binding_id = str(binding.binding_id)
        existing_binding = by_binding_id.get(binding_id)
        if existing_binding is not None and existing_binding != binding:
            raise ValueError("conflicting replay market bindings share a binding_id")
        source_id = str(binding.source.source_id)
        existing_source = by_source_id.get(source_id)
        if existing_source is not None and existing_source != binding.source:
            raise ValueError("conflicting source descriptors share a source_id")
        venue_instrument_id = str(binding.venue_instrument.venue_instrument_id)
        existing_instrument = by_instrument_id.get(venue_instrument_id)
        if existing_instrument is not None and existing_instrument != binding.venue_instrument:
            raise ValueError("conflicting venue instruments share a venue_instrument_id")
        by_key[key] = binding
        by_binding_id[binding_id] = binding
        by_source_id[source_id] = binding.source
        by_instrument_id[venue_instrument_id] = binding.venue_instrument
    return tuple(
        sorted(
            by_key.values(),
            key=lambda binding: (*replay_market_binding_key(binding), str(binding.binding_id)),
        )
    )


def build_replay_market_adapter_authority(
    *,
    descriptor: ReplayMarketAdapterDescriptor,
    bindings: tuple[ReplayMarketDataBinding, ...],
) -> ReplayMarketAdapterAuthority:
    revalidated_descriptor = _revalidate_model(ReplayMarketAdapterDescriptor, descriptor)
    canonical_bindings = validate_replay_market_data_bindings(bindings)
    adapter_fingerprint = build_replay_market_adapter_fingerprint(
        descriptor=revalidated_descriptor,
        bindings=canonical_bindings,
    )
    return ReplayMarketAdapterAuthority(
        descriptor=revalidated_descriptor,
        bindings=canonical_bindings,
        adapter_fingerprint=adapter_fingerprint,
    )


def build_replay_market_binding_authority_fingerprint(
    *,
    descriptor: ReplayMarketAdapterDescriptor,
    binding: ReplayMarketDataBinding,
) -> str:
    revalidated_descriptor = _revalidate_model(ReplayMarketAdapterDescriptor, descriptor)
    revalidated_binding = _revalidate_model(ReplayMarketDataBinding, binding)
    material = {
        "schema_version": 1,
        "binding": revalidated_binding.model_dump(mode="json"),
        "descriptor": revalidated_descriptor.model_dump(mode="json"),
    }
    return f"replay-market-binding-authority:{_sha256_text(_canonical_json(material))}"


def build_replay_market_binding_authority(
    *,
    descriptor: ReplayMarketAdapterDescriptor,
    binding: ReplayMarketDataBinding,
) -> ReplayMarketBindingAuthority:
    revalidated_descriptor = _revalidate_model(ReplayMarketAdapterDescriptor, descriptor)
    revalidated_binding = _revalidate_model(ReplayMarketDataBinding, binding)
    return ReplayMarketBindingAuthority(
        descriptor=revalidated_descriptor,
        binding=revalidated_binding,
        binding_authority_fingerprint=build_replay_market_binding_authority_fingerprint(
            descriptor=revalidated_descriptor,
            binding=revalidated_binding,
        ),
    )


def build_replay_market_frame_lookup_entry_id(  # noqa: PLR0913
    *,
    market_timeline_id: ReplayMarketFrameTimelineId,
    replay_timeline_id: str,
    replay_plan_id: str,
    adapter_fingerprint: str,
    event_id: str,
    event_order_index: int,
    event_time: datetime,
    event_kind: ReplayInputKind,
    observation_projection_id: ReplayMarketObservationProjectionId,
    frame_projection_id: ReplayMarketFrameProjectionId,
    frame_id: MarketFrameId,
    triggering_observation_id: MarketObservationId,
    binding_authority_fingerprint: str,
) -> ReplayMarketFrameLookupEntryId:
    material = {
        "schema_version": 1,
        "adapter_fingerprint": _validate_adapter_fingerprint(adapter_fingerprint),
        "binding_authority_fingerprint": _validate_binding_authority_fingerprint(
            binding_authority_fingerprint
        ),
        "event_id": _trimmed(event_id, "event_id"),
        "event_kind": ReplayInputKind(event_kind).value,
        "event_order_index": _strict_non_negative_int(
            event_order_index,
            "event_order_index",
        ),
        "event_time": _json_datetime(event_time),
        "frame_id": _validate_market_frame_id(frame_id).model_dump(mode="json"),
        "frame_projection_id": _validate_frame_projection_id(
            frame_projection_id
        ).model_dump(mode="json"),
        "market_timeline_id": _validate_market_timeline_id(
            market_timeline_id
        ).model_dump(mode="json"),
        "observation_projection_id": _validate_observation_projection_id(
            observation_projection_id
        ).model_dump(mode="json"),
        "replay_plan_id": _trimmed(replay_plan_id, "replay_plan_id"),
        "replay_timeline_id": _trimmed(replay_timeline_id, "replay_timeline_id"),
        "triggering_observation_id": _validate_market_observation_id(
            triggering_observation_id
        ).model_dump(mode="json"),
    }
    return ReplayMarketFrameLookupEntryId.from_str(
        f"replay-market-frame-lookup-entry:{_sha256_text(_canonical_json(material))}"
    )


def build_replay_market_frame_lookup_entry(  # noqa: PLR0913
    *,
    market_timeline_id: ReplayMarketFrameTimelineId,
    replay_timeline_id: str,
    replay_plan_id: str,
    adapter_fingerprint: str,
    observation_projection: ReplayMarketObservationProjection,
    frame_projection: ReplayMarketFrameProjection,
) -> ReplayMarketFrameLookupEntry:
    observation_projection = _revalidate_model(
        ReplayMarketObservationProjection,
        observation_projection,
    )
    frame_projection = _revalidate_model(ReplayMarketFrameProjection, frame_projection)
    _validate_projection_pair(
        descriptor_replay_timeline_id=_trimmed(replay_timeline_id, "replay_timeline_id"),
        supported_event_kinds=(observation_projection.event_kind,),
        observation_projection=observation_projection,
        frame_projection=frame_projection,
    )
    entry_id = build_replay_market_frame_lookup_entry_id(
        market_timeline_id=market_timeline_id,
        replay_timeline_id=replay_timeline_id,
        replay_plan_id=replay_plan_id,
        adapter_fingerprint=adapter_fingerprint,
        event_id=observation_projection.event_id,
        event_order_index=observation_projection.event_order_index,
        event_time=observation_projection.event_time,
        event_kind=observation_projection.event_kind,
        observation_projection_id=observation_projection.projection_id,
        frame_projection_id=frame_projection.projection_id,
        frame_id=frame_projection.frame.frame_id,
        triggering_observation_id=frame_projection.triggering_observation_id,
        binding_authority_fingerprint=(
            observation_projection.binding_authority.binding_authority_fingerprint
        ),
    )
    return ReplayMarketFrameLookupEntry(
        entry_id=entry_id,
        market_timeline_id=market_timeline_id,
        replay_timeline_id=replay_timeline_id,
        replay_plan_id=replay_plan_id,
        adapter_fingerprint=adapter_fingerprint,
        event_id=observation_projection.event_id,
        event_order_index=observation_projection.event_order_index,
        event_time=observation_projection.event_time,
        event_kind=observation_projection.event_kind,
        observation_projection_id=observation_projection.projection_id,
        frame_projection_id=frame_projection.projection_id,
        frame_id=frame_projection.frame.frame_id,
        triggering_observation_id=frame_projection.triggering_observation_id,
        binding_authority_fingerprint=(
            observation_projection.binding_authority.binding_authority_fingerprint
        ),
    )


def build_replay_market_frame_lookup_authority_fingerprint(  # noqa: PLR0913
    *,
    market_timeline_id: ReplayMarketFrameTimelineId,
    replay_timeline_id: str,
    replay_plan_id: str,
    adapter_fingerprint: str,
    supported_event_kinds: tuple[ReplayInputKind, ...],
    entries: tuple[ReplayMarketFrameLookupEntry, ...],
) -> str:
    revalidated_entries = tuple(
        _revalidate_model(ReplayMarketFrameLookupEntry, entry) for entry in entries
    )
    revalidated_kinds = _validate_market_projection_event_kinds(supported_event_kinds)
    _validate_lookup_authority_entries(
        market_timeline_id=_validate_market_timeline_id(market_timeline_id),
        replay_timeline_id=_trimmed(replay_timeline_id, "replay_timeline_id"),
        replay_plan_id=_trimmed(replay_plan_id, "replay_plan_id"),
        adapter_fingerprint=_validate_adapter_fingerprint(adapter_fingerprint),
        supported_event_kinds=revalidated_kinds,
        entries=revalidated_entries,
    )
    material = {
        "schema_version": 1,
        "adapter_fingerprint": _validate_adapter_fingerprint(adapter_fingerprint),
        "entries": [entry.model_dump(mode="json") for entry in revalidated_entries],
        "market_timeline_id": _validate_market_timeline_id(
            market_timeline_id
        ).model_dump(mode="json"),
        "replay_plan_id": _trimmed(replay_plan_id, "replay_plan_id"),
        "replay_timeline_id": _trimmed(replay_timeline_id, "replay_timeline_id"),
        "supported_event_kinds": [kind.value for kind in revalidated_kinds],
    }
    return f"replay-market-frame-lookup-authority:{_sha256_text(_canonical_json(material))}"


def build_replay_market_frame_lookup_authority(
    market_timeline: ReplayMarketFrameTimeline,
) -> ReplayMarketFrameLookupAuthority:
    revalidated = _revalidate_model(ReplayMarketFrameTimeline, market_timeline)
    entries = tuple(
        build_replay_market_frame_lookup_entry(
            market_timeline_id=revalidated.market_timeline_id,
            replay_timeline_id=revalidated.replay_timeline_id,
            replay_plan_id=revalidated.replay_plan_id,
            adapter_fingerprint=revalidated.adapter_authority.adapter_fingerprint,
            observation_projection=observation_projection,
            frame_projection=frame_projection,
        )
        for observation_projection, frame_projection in zip(
            revalidated.observation_projections,
            revalidated.frame_projections,
            strict=True,
        )
    )
    fingerprint = build_replay_market_frame_lookup_authority_fingerprint(
        market_timeline_id=revalidated.market_timeline_id,
        replay_timeline_id=revalidated.replay_timeline_id,
        replay_plan_id=revalidated.replay_plan_id,
        adapter_fingerprint=revalidated.adapter_authority.adapter_fingerprint,
        supported_event_kinds=revalidated.adapter_authority.descriptor.supported_input_kinds,
        entries=entries,
    )
    return ReplayMarketFrameLookupAuthority(
        market_timeline_id=revalidated.market_timeline_id,
        replay_timeline_id=revalidated.replay_timeline_id,
        replay_plan_id=revalidated.replay_plan_id,
        adapter_fingerprint=revalidated.adapter_authority.adapter_fingerprint,
        supported_event_kinds=revalidated.adapter_authority.descriptor.supported_input_kinds,
        entries=entries,
        lookup_authority_fingerprint=fingerprint,
    )


def build_replay_market_frame_lookup_descriptor(
    authority: ReplayMarketFrameLookupAuthority,
) -> ReplayMarketFrameLookupDescriptor:
    revalidated = _revalidate_model(ReplayMarketFrameLookupAuthority, authority)
    return ReplayMarketFrameLookupDescriptor(
        market_timeline_id=revalidated.market_timeline_id,
        replay_timeline_id=revalidated.replay_timeline_id,
        replay_plan_id=revalidated.replay_plan_id,
        adapter_fingerprint=revalidated.adapter_fingerprint,
        lookup_authority_fingerprint=revalidated.lookup_authority_fingerprint,
        supported_event_kinds=revalidated.supported_event_kinds,
    )


def validate_replay_market_frame_lookup_result(
    *,
    descriptor: ReplayMarketFrameLookupDescriptor,
    entry: ReplayMarketFrameLookupEntry,
    observation_projection: ReplayMarketObservationProjection,
    frame_projection: ReplayMarketFrameProjection,
) -> None:
    descriptor = _revalidate_model(ReplayMarketFrameLookupDescriptor, descriptor)
    entry = _revalidate_model(ReplayMarketFrameLookupEntry, entry)
    observation_projection = _revalidate_model(
        ReplayMarketObservationProjection,
        observation_projection,
    )
    frame_projection = _revalidate_model(ReplayMarketFrameProjection, frame_projection)
    if entry.market_timeline_id != descriptor.market_timeline_id:
        raise ValueError("lookup entry market_timeline_id must match descriptor")
    if entry.replay_timeline_id != descriptor.replay_timeline_id:
        raise ValueError("lookup entry replay_timeline_id must match descriptor")
    if entry.replay_plan_id != descriptor.replay_plan_id:
        raise ValueError("lookup entry replay_plan_id must match descriptor")
    if entry.adapter_fingerprint != descriptor.adapter_fingerprint:
        raise ValueError("lookup entry adapter_fingerprint must match descriptor")
    _validate_lookup_entry_matches_projection_pair(
        entry=entry,
        observation_projection=observation_projection,
        frame_projection=frame_projection,
    )
    _validate_projection_pair(
        descriptor_replay_timeline_id=descriptor.replay_timeline_id,
        supported_event_kinds=descriptor.supported_event_kinds,
        observation_projection=observation_projection,
        frame_projection=frame_projection,
    )


def validate_replay_market_frame_lookup_membership(
    *,
    authority: ReplayMarketFrameLookupAuthority,
    result: ReplayMarketFrameLookupResult,
) -> None:
    authority = _revalidate_model(ReplayMarketFrameLookupAuthority, authority)
    result = _revalidate_model(ReplayMarketFrameLookupResult, result)
    expected_descriptor = build_replay_market_frame_lookup_descriptor(authority)
    if result.descriptor != expected_descriptor:
        raise ValueError("lookup result descriptor must match lookup authority")
    entries_by_id = {str(entry.entry_id): entry for entry in authority.entries}
    authority_entry = entries_by_id.get(str(result.entry.entry_id))
    if authority_entry is None:
        raise ValueError("lookup result entry is absent from lookup authority")
    if authority_entry != result.entry:
        raise ValueError("lookup result entry differs from lookup authority")
    validate_replay_market_frame_lookup_result(
        descriptor=result.descriptor,
        entry=result.entry,
        observation_projection=result.observation_projection,
        frame_projection=result.frame_projection,
    )


def build_replay_market_frame_lookup_result(
    *,
    descriptor: ReplayMarketFrameLookupDescriptor,
    entry: ReplayMarketFrameLookupEntry,
    observation_projection: ReplayMarketObservationProjection,
    frame_projection: ReplayMarketFrameProjection,
) -> ReplayMarketFrameLookupResult:
    validate_replay_market_frame_lookup_result(
        descriptor=descriptor,
        entry=entry,
        observation_projection=observation_projection,
        frame_projection=frame_projection,
    )
    return ReplayMarketFrameLookupResult(
        descriptor=descriptor,
        entry=entry,
        observation_projection=observation_projection,
        frame_projection=frame_projection,
    )


def _validate_replay_market_frame_timeline_semantics(  # noqa: PLR0912, PLR0915
    *,
    replay_timeline_id: str,
    adapter_authority: ReplayMarketAdapterAuthority,
    observation_projections: tuple[ReplayMarketObservationProjection, ...],
    frame_projections: tuple[ReplayMarketFrameProjection, ...],
) -> None:
    timeline_id = _trimmed(replay_timeline_id, "replay_timeline_id")
    authority = _revalidate_model(ReplayMarketAdapterAuthority, adapter_authority)
    bindings_by_id = {str(binding.binding_id): binding for binding in authority.bindings}
    bindings_by_key = {
        replay_market_binding_key(binding): binding for binding in authority.bindings
    }
    observations = tuple(
        _revalidate_model(ReplayMarketObservationProjection, projection)
        for projection in observation_projections
    )
    frames = tuple(
        _revalidate_model(ReplayMarketFrameProjection, projection)
        for projection in frame_projections
    )
    if len(observations) != len(frames):
        raise ValueError("one frame projection is required per observation projection")
    _reject_duplicate_ids(
        tuple(str(projection.projection_id) for projection in observations),
        "observation projection",
    )
    _reject_duplicate_ids(
        tuple(str(projection.projection_id) for projection in frames),
        "frame projection",
    )
    order_indexes = tuple(projection.event_order_index for projection in observations)
    if order_indexes != tuple(sorted(order_indexes)):
        raise ValueError("observation projections must be sorted by event_order_index")
    if len(set(order_indexes)) != len(order_indexes):
        raise ValueError("projected event_order_index values must be strictly increasing")
    accumulated: dict[str, tuple[NormalizedMarketObservation, ...]] = {}
    for observation_projection, frame_projection in zip(observations, frames, strict=True):
        if observation_projection.timeline_id != timeline_id:
            raise ValueError("observation projection timeline_id must match replay_timeline_id")
        if frame_projection.timeline_id != timeline_id:
            raise ValueError("frame projection timeline_id must match replay_timeline_id")
        if observation_projection.binding_authority.descriptor != authority.descriptor:
            raise ValueError("observation projection descriptor differs from authority")
        projection_binding = observation_projection.binding_authority.binding
        authority_binding = bindings_by_id.get(str(projection_binding.binding_id))
        if authority_binding is None:
            raise ValueError("observation projection binding ID is absent from authority")
        if authority_binding != projection_binding:
            raise ValueError("observation projection binding differs from authority")
        binding_key = replay_market_binding_key(projection_binding)
        if bindings_by_key.get(binding_key) != projection_binding:
            raise ValueError("observation projection binding key differs from authority")
        if frame_projection.timeline_id != observation_projection.timeline_id:
            raise ValueError("paired projection timeline IDs must match")
        if (
            frame_projection.triggering_observation_projection_id
            != observation_projection.projection_id
        ):
            raise ValueError("frame triggering projection must match observation projection")
        if (
            frame_projection.triggering_observation_id
            != observation_projection.observation.observation_id
        ):
            raise ValueError("frame triggering observation ID must match observation projection")
        if frame_projection.event_order_index != observation_projection.event_order_index:
            raise ValueError("projection order indexes must match")
        if frame_projection.event_id != observation_projection.event_id:
            raise ValueError("projection event IDs must match")
        if frame_projection.event_time != observation_projection.event_time:
            raise ValueError("projection event times must match")
        if frame_projection.frame.as_of != observation_projection.event_time:
            raise ValueError("frame.as_of must match observation projection event_time")
        if (
            frame_projection.frame.logical_instrument
            != observation_projection.observation.instrument.logical_instrument
        ):
            raise ValueError("frame logical instrument must match triggering observation")
        if frame_projection.frame.source_health != ():
            raise ValueError("replay market frame projections must not fabricate source health")
        logical = str(observation_projection.observation.instrument.logical_instrument)
        accumulated[logical] = (
            *accumulated.get(logical, ()),
            observation_projection.observation,
        )
        expected_observations = select_latest_market_observations(
            logical_instrument=observation_projection.observation.instrument.logical_instrument,
            as_of=observation_projection.event_time,
            observations=accumulated[logical],
        )
        if frame_projection.frame.observations != expected_observations:
            raise ValueError("frame observations must equal replay-order cumulative state")
        if not any(
            observation.observation_id == frame_projection.triggering_observation_id
            for observation in expected_observations
        ):
            raise ValueError("triggering observation ID must exist in expected frame")


def build_replay_market_adapter_fingerprint(
    *,
    descriptor: ReplayMarketAdapterDescriptor,
    bindings: tuple[ReplayMarketDataBinding, ...],
) -> str:
    revalidated_descriptor = _revalidate_model(ReplayMarketAdapterDescriptor, descriptor)
    revalidated_bindings = validate_replay_market_data_bindings(bindings)
    material = {
        "bindings": [binding.model_dump(mode="json") for binding in revalidated_bindings],
        "descriptor": revalidated_descriptor.model_dump(mode="json"),
    }
    return f"replay-market-adapter:{_sha256_text(_canonical_json(material))}"


def build_replay_market_connection_id(
    *,
    input_dataset_id: str,
    binding_authority: ReplayMarketBindingAuthority,
) -> MarketConnectionId:
    input_dataset_id = _trimmed(input_dataset_id, "input_dataset_id")
    binding_authority = _revalidate_model(ReplayMarketBindingAuthority, binding_authority)
    binding = binding_authority.binding
    return build_replay_market_connection_id_from_authority(
        input_dataset_id=input_dataset_id,
        binding_authority_fingerprint=binding_authority.binding_authority_fingerprint,
        binding_id=binding.binding_id,
        source_id=binding.source.source_id,
        venue_instrument_id=binding.venue_instrument.venue_instrument_id,
    )


def build_replay_market_connection_id_from_authority(
    *,
    input_dataset_id: str,
    binding_authority_fingerprint: str,
    binding_id: ReplayMarketBindingId,
    source_id: MarketDataSourceId,
    venue_instrument_id: VenueInstrumentId,
) -> MarketConnectionId:
    input_dataset_id = _trimmed(input_dataset_id, "input_dataset_id")
    binding_authority_fingerprint = _validate_binding_authority_fingerprint(
        binding_authority_fingerprint
    )
    binding_id = _revalidate_domain_id(ReplayMarketBindingId, binding_id)
    source_id = _revalidate_domain_id(MarketDataSourceId, source_id)
    venue_instrument_id = _revalidate_domain_id(VenueInstrumentId, venue_instrument_id)
    material = {
        "binding_authority_fingerprint": binding_authority_fingerprint,
        "binding_id": str(binding_id),
        "input_dataset_id": input_dataset_id,
        "source_id": str(source_id),
        "venue_instrument_id": str(venue_instrument_id),
    }
    return MarketConnectionId.from_str(
        f"replay-market-connection:{_sha256_text(_canonical_json(material))}"
    )


def build_replay_market_observation_projection_id(  # noqa: PLR0913
    *,
    timeline_id: str,
    event_id: str,
    event_order_index: int,
    event_time: datetime,
    batch_id: str,
    input_dataset_id: str,
    record_id: str,
    event_kind: ReplayInputKind,
    binding_authority: ReplayMarketBindingAuthority,
    observation: NormalizedMarketObservation,
) -> ReplayMarketObservationProjectionId:
    validate_replay_market_observation_kind(
        event_kind=event_kind,
        observation=observation,
    )
    validate_replay_market_projection_descriptor(
        event_kind=event_kind,
        binding_authority=binding_authority,
    )
    validate_replay_market_projection_binding(
        input_dataset_id=input_dataset_id,
        binding_authority=binding_authority,
        observation=observation,
    )
    validate_replay_market_observation_provenance(
        timeline_id=timeline_id,
        event_id=event_id,
        event_time=event_time,
        input_dataset_id=input_dataset_id,
        binding_authority=binding_authority,
        observation=observation,
    )
    revalidated_authority = _revalidate_model(
        ReplayMarketBindingAuthority,
        binding_authority,
    )
    material = {
        "schema_version": 1,
        "batch_id": _trimmed(batch_id, "batch_id"),
        "binding_authority": revalidated_authority.model_dump(mode="json"),
        "event_id": _trimmed(event_id, "event_id"),
        "event_kind": ReplayInputKind(event_kind).value,
        "event_order_index": _strict_non_negative_int(
            event_order_index,
            "event_order_index",
        ),
        "event_time": _json_datetime(event_time),
        "input_dataset_id": _trimmed(input_dataset_id, "input_dataset_id"),
        "observation": _revalidate_model(NormalizedMarketObservation, observation).model_dump(
            mode="json"
        ),
        "record_id": _trimmed(record_id, "record_id"),
        "timeline_id": _trimmed(timeline_id, "timeline_id"),
    }
    return ReplayMarketObservationProjectionId.from_str(
        f"replay-market-observation-projection:{_sha256_text(_canonical_json(material))}"
    )


def build_replay_market_observation_projection(  # noqa: PLR0913
    *,
    timeline_id: str,
    event_id: str,
    event_order_index: int,
    event_time: datetime,
    batch_id: str,
    input_dataset_id: str,
    record_id: str,
    event_kind: ReplayInputKind,
    binding_authority: ReplayMarketBindingAuthority,
    observation: NormalizedMarketObservation,
) -> ReplayMarketObservationProjection:
    validate_replay_market_observation_kind(
        event_kind=event_kind,
        observation=observation,
    )
    validate_replay_market_projection_descriptor(
        event_kind=event_kind,
        binding_authority=binding_authority,
    )
    validate_replay_market_projection_binding(
        input_dataset_id=input_dataset_id,
        binding_authority=binding_authority,
        observation=observation,
    )
    validate_replay_market_observation_provenance(
        timeline_id=timeline_id,
        event_id=event_id,
        event_time=event_time,
        input_dataset_id=input_dataset_id,
        binding_authority=binding_authority,
        observation=observation,
    )
    projection_id = build_replay_market_observation_projection_id(
        timeline_id=timeline_id,
        event_id=event_id,
        event_order_index=event_order_index,
        event_time=event_time,
        batch_id=batch_id,
        input_dataset_id=input_dataset_id,
        record_id=record_id,
        event_kind=event_kind,
        binding_authority=binding_authority,
        observation=observation,
    )
    return ReplayMarketObservationProjection(
        projection_id=projection_id,
        timeline_id=timeline_id,
        event_id=event_id,
        event_order_index=event_order_index,
        event_time=event_time,
        batch_id=batch_id,
        input_dataset_id=input_dataset_id,
        record_id=record_id,
        event_kind=event_kind,
        binding_authority=binding_authority,
        observation=observation,
    )


def build_replay_market_frame_projection_id(  # noqa: PLR0913
    *,
    timeline_id: str,
    event_id: str,
    event_order_index: int,
    event_time: datetime,
    triggering_observation_projection_id: ReplayMarketObservationProjectionId,
    triggering_observation_id: MarketObservationId,
    frame: CrossVenueMarketFrame,
) -> ReplayMarketFrameProjectionId:
    revalidated_frame = _revalidate_model(CrossVenueMarketFrame, frame)
    revalidated_triggering_projection_id = _validate_observation_projection_id(
        triggering_observation_projection_id
    )
    revalidated_triggering_observation_id = _validate_market_observation_id(
        triggering_observation_id
    )
    if not any(
        observation.observation_id == revalidated_triggering_observation_id
        for observation in revalidated_frame.observations
    ):
        raise ValueError("triggering observation ID must exist in frame")
    material = {
        "schema_version": 1,
        "event_id": _trimmed(event_id, "event_id"),
        "event_order_index": _strict_non_negative_int(
            event_order_index,
            "event_order_index",
        ),
        "event_time": _json_datetime(event_time),
        "frame": revalidated_frame.model_dump(mode="json"),
        "timeline_id": _trimmed(timeline_id, "timeline_id"),
        "triggering_observation_id": revalidated_triggering_observation_id.model_dump(
            mode="json"
        ),
        "triggering_observation_projection_id": revalidated_triggering_projection_id.model_dump(
            mode="json"
        ),
    }
    return ReplayMarketFrameProjectionId.from_str(
        f"replay-market-frame-projection:{_sha256_text(_canonical_json(material))}"
    )


def build_replay_market_frame_projection(  # noqa: PLR0913
    *,
    timeline_id: str,
    event_id: str,
    event_order_index: int,
    event_time: datetime,
    triggering_observation_projection_id: ReplayMarketObservationProjectionId,
    triggering_observation_id: MarketObservationId,
    frame: CrossVenueMarketFrame,
) -> ReplayMarketFrameProjection:
    projection_id = build_replay_market_frame_projection_id(
        timeline_id=timeline_id,
        event_id=event_id,
        event_order_index=event_order_index,
        event_time=event_time,
        triggering_observation_projection_id=triggering_observation_projection_id,
        triggering_observation_id=triggering_observation_id,
        frame=frame,
    )
    return ReplayMarketFrameProjection(
        projection_id=projection_id,
        timeline_id=timeline_id,
        event_id=event_id,
        event_order_index=event_order_index,
        event_time=event_time,
        triggering_observation_projection_id=triggering_observation_projection_id,
        triggering_observation_id=triggering_observation_id,
        frame=frame,
    )


def build_replay_market_frame_timeline_id(
    *,
    replay_timeline_id: str,
    replay_plan_id: str,
    adapter_authority: ReplayMarketAdapterAuthority,
    observation_projections: tuple[ReplayMarketObservationProjection, ...],
    frame_projections: tuple[ReplayMarketFrameProjection, ...],
) -> ReplayMarketFrameTimelineId:
    revalidated_authority = _revalidate_model(ReplayMarketAdapterAuthority, adapter_authority)
    revalidated_observations = tuple(
        _revalidate_model(ReplayMarketObservationProjection, projection)
        for projection in observation_projections
    )
    revalidated_frames = tuple(
        _revalidate_model(ReplayMarketFrameProjection, projection)
        for projection in frame_projections
    )
    _validate_replay_market_frame_timeline_semantics(
        replay_timeline_id=replay_timeline_id,
        adapter_authority=revalidated_authority,
        observation_projections=revalidated_observations,
        frame_projections=revalidated_frames,
    )
    material = {
        "schema_version": 1,
        "adapter_authority": revalidated_authority.model_dump(mode="json"),
        "frame_projection_ids": [
            str(projection.projection_id) for projection in revalidated_frames
        ],
        "observation_projection_ids": [
            str(projection.projection_id) for projection in revalidated_observations
        ],
        "replay_plan_id": _trimmed(replay_plan_id, "replay_plan_id"),
        "replay_timeline_id": _trimmed(replay_timeline_id, "replay_timeline_id"),
    }
    return ReplayMarketFrameTimelineId.from_str(
        f"replay-market-frame-timeline:{_sha256_text(_canonical_json(material))}"
    )


def build_replay_market_frame_timeline_model(
    *,
    replay_timeline_id: str,
    replay_plan_id: str,
    adapter_authority: ReplayMarketAdapterAuthority,
    observation_projections: tuple[ReplayMarketObservationProjection, ...],
    frame_projections: tuple[ReplayMarketFrameProjection, ...],
) -> ReplayMarketFrameTimeline:
    market_timeline_id = build_replay_market_frame_timeline_id(
        replay_timeline_id=replay_timeline_id,
        replay_plan_id=replay_plan_id,
        adapter_authority=adapter_authority,
        observation_projections=observation_projections,
        frame_projections=frame_projections,
    )
    return ReplayMarketFrameTimeline(
        market_timeline_id=market_timeline_id,
        replay_timeline_id=replay_timeline_id,
        replay_plan_id=replay_plan_id,
        adapter_authority=adapter_authority,
        observation_projections=observation_projections,
        frame_projections=frame_projections,
    )


def _revalidate_domain_id[T: DomainId](id_type: type[T], value: object) -> T:
    if isinstance(value, id_type):
        return id_type.model_validate(value.model_dump())
    if isinstance(value, str):
        return id_type(value)
    return id_type.model_validate(value)


def _validate_market_observation_id(value: object) -> MarketObservationId:
    observation_id = _revalidate_domain_id(MarketObservationId, value)
    if not _MARKET_OBSERVATION_ID_RE.fullmatch(str(observation_id)):
        raise ValueError("invalid market observation ID")
    return observation_id


def _validate_market_frame_id(value: object) -> MarketFrameId:
    frame_id = _revalidate_domain_id(MarketFrameId, value)
    if not _MARKET_FRAME_ID_RE.fullmatch(str(frame_id)):
        raise ValueError("invalid market frame ID")
    return frame_id


def _validate_market_timeline_id(value: object) -> ReplayMarketFrameTimelineId:
    timeline_id = _revalidate_domain_id(ReplayMarketFrameTimelineId, value)
    if not _TIMELINE_ID_RE.fullmatch(str(timeline_id)):
        raise ValueError("invalid replay market frame timeline ID")
    return timeline_id


def _validate_observation_projection_id(
    value: object,
) -> ReplayMarketObservationProjectionId:
    projection_id = _revalidate_domain_id(ReplayMarketObservationProjectionId, value)
    if not _OBSERVATION_PROJECTION_ID_RE.fullmatch(str(projection_id)):
        raise ValueError("invalid replay market observation projection ID")
    return projection_id


def _validate_frame_projection_id(value: object) -> ReplayMarketFrameProjectionId:
    projection_id = _revalidate_domain_id(ReplayMarketFrameProjectionId, value)
    if not _FRAME_PROJECTION_ID_RE.fullmatch(str(projection_id)):
        raise ValueError("invalid replay market frame projection ID")
    return projection_id


def _revalidate_model[T: BaseModel](model_type: type[T], value: object) -> T:
    if isinstance(value, model_type):
        return model_type.model_validate(value.model_dump())
    return model_type.model_validate(value)


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


def _validate_adapter_fingerprint(value: str) -> str:
    value = _trimmed(value, "adapter_fingerprint")
    if not _ADAPTER_FINGERPRINT_RE.fullmatch(value):
        raise ValueError("adapter_fingerprint must match replay-market-adapter:<64 hex>")
    return value


def _validate_binding_authority_fingerprint(value: str) -> str:
    value = _trimmed(value, "binding_authority_fingerprint")
    if not _BINDING_AUTHORITY_FINGERPRINT_RE.fullmatch(value):
        raise ValueError(
            "binding_authority_fingerprint must match "
            "replay-market-binding-authority:<64 hex>"
        )
    return value


def _validate_lookup_authority_fingerprint(value: str) -> str:
    value = _trimmed(value, "lookup_authority_fingerprint")
    if not _LOOKUP_AUTHORITY_FINGERPRINT_RE.fullmatch(value):
        raise ValueError(
            "lookup_authority_fingerprint must match "
            "replay-market-frame-lookup-authority:<64 hex>"
        )
    return value


def validate_sha256_prefixed(value: str) -> str:
    value = _trimmed(value, "sha256")
    if not _SHA256_RE.fullmatch(value):
        raise ValueError("value must match sha256:<64 lowercase hex>")
    return value


def validate_replay_market_connection_id(value: MarketConnectionId) -> MarketConnectionId:
    value = _revalidate_domain_id(MarketConnectionId, value)
    if not _CONNECTION_ID_RE.fullmatch(str(value)):
        raise ValueError("invalid replay market connection ID")
    return value


def _validate_projection_pair(
    *,
    descriptor_replay_timeline_id: str,
    supported_event_kinds: tuple[ReplayInputKind, ...],
    observation_projection: ReplayMarketObservationProjection,
    frame_projection: ReplayMarketFrameProjection,
) -> None:
    descriptor_replay_timeline_id = _trimmed(
        descriptor_replay_timeline_id,
        "descriptor_replay_timeline_id",
    )
    supported_event_kinds = _validate_market_projection_event_kinds(supported_event_kinds)
    if observation_projection.timeline_id != descriptor_replay_timeline_id:
        raise ValueError("lookup observation projection timeline_id must match descriptor")
    if frame_projection.timeline_id != descriptor_replay_timeline_id:
        raise ValueError("lookup frame projection timeline_id must match descriptor")
    if observation_projection.event_id != frame_projection.event_id:
        raise ValueError("lookup projection event_id values must match")
    if observation_projection.event_order_index != frame_projection.event_order_index:
        raise ValueError("lookup projection event_order_index values must match")
    if observation_projection.event_time != frame_projection.event_time:
        raise ValueError("lookup projection event_time values must match")
    if (
        frame_projection.triggering_observation_projection_id
        != observation_projection.projection_id
    ):
        raise ValueError("lookup frame trigger projection must match observation projection")
    if (
        frame_projection.triggering_observation_id
        != observation_projection.observation.observation_id
    ):
        raise ValueError("lookup frame trigger observation must match observation projection")
    if frame_projection.frame.as_of != observation_projection.event_time:
        raise ValueError("lookup frame as_of must match observation event_time")
    if frame_projection.frame.frame_id != _validate_market_frame_id(
        frame_projection.frame.frame_id
    ):
        raise ValueError("lookup frame ID must be valid")
    if observation_projection.event_kind not in supported_event_kinds:
        raise ValueError("lookup observation event_kind must be supported")


def _validate_lookup_entry_matches_projection_pair(
    *,
    entry: ReplayMarketFrameLookupEntry,
    observation_projection: ReplayMarketObservationProjection,
    frame_projection: ReplayMarketFrameProjection,
) -> None:
    if entry.replay_timeline_id != observation_projection.timeline_id:
        raise ValueError("lookup entry timeline_id must match observation projection")
    if entry.replay_timeline_id != frame_projection.timeline_id:
        raise ValueError("lookup entry timeline_id must match frame projection")
    if entry.event_id != observation_projection.event_id:
        raise ValueError("lookup entry event_id must match observation projection")
    if entry.event_order_index != observation_projection.event_order_index:
        raise ValueError("lookup entry order index must match observation projection")
    if entry.event_time != observation_projection.event_time:
        raise ValueError("lookup entry event_time must match observation projection")
    if entry.event_kind != observation_projection.event_kind:
        raise ValueError("lookup entry event_kind must match observation projection")
    if entry.observation_projection_id != observation_projection.projection_id:
        raise ValueError("lookup entry observation projection ID must match projection")
    if entry.frame_projection_id != frame_projection.projection_id:
        raise ValueError("lookup entry frame projection ID must match projection")
    if entry.frame_id != frame_projection.frame.frame_id:
        raise ValueError("lookup entry frame ID must match frame projection")
    if entry.triggering_observation_id != frame_projection.triggering_observation_id:
        raise ValueError("lookup entry triggering observation ID must match frame")
    if (
        entry.binding_authority_fingerprint
        != observation_projection.binding_authority.binding_authority_fingerprint
    ):
        raise ValueError("lookup entry binding authority must match observation projection")


def _validate_lookup_authority_entries(  # noqa: PLR0912, PLR0913
    *,
    market_timeline_id: ReplayMarketFrameTimelineId,
    replay_timeline_id: str,
    replay_plan_id: str,
    adapter_fingerprint: str,
    supported_event_kinds: tuple[ReplayInputKind, ...],
    entries: tuple[ReplayMarketFrameLookupEntry, ...],
) -> None:
    event_ids: set[str] = set()
    event_order_indexes: set[int] = set()
    event_keys: set[tuple[str, int]] = set()
    entry_ids: set[str] = set()
    observation_projection_ids: set[str] = set()
    frame_projection_ids: set[str] = set()
    ordering_keys: list[tuple[int, str]] = []
    for entry in entries:
        if entry.market_timeline_id != market_timeline_id:
            raise ValueError("lookup authority entry market_timeline_id mismatch")
        if entry.replay_timeline_id != replay_timeline_id:
            raise ValueError("lookup authority entry replay_timeline_id mismatch")
        if entry.replay_plan_id != replay_plan_id:
            raise ValueError("lookup authority entry replay_plan_id mismatch")
        if entry.adapter_fingerprint != adapter_fingerprint:
            raise ValueError("lookup authority entry adapter_fingerprint mismatch")
        if entry.event_kind not in supported_event_kinds:
            raise ValueError("lookup authority entry event kind is unsupported")
        entry_id = str(entry.entry_id)
        if entry_id in entry_ids:
            raise ValueError("lookup authority entry IDs must be unique")
        entry_ids.add(entry_id)
        key = (entry.event_id, entry.event_order_index)
        if key in event_keys:
            raise ValueError("lookup authority event keys must be unique")
        event_keys.add(key)
        if entry.event_id in event_ids:
            raise ValueError("lookup authority event IDs must be unique")
        event_ids.add(entry.event_id)
        if entry.event_order_index in event_order_indexes:
            raise ValueError("lookup authority event order indexes must be unique")
        event_order_indexes.add(entry.event_order_index)
        observation_projection_id = str(entry.observation_projection_id)
        if observation_projection_id in observation_projection_ids:
            raise ValueError("lookup authority observation projection IDs must be unique")
        observation_projection_ids.add(observation_projection_id)
        frame_projection_id = str(entry.frame_projection_id)
        if frame_projection_id in frame_projection_ids:
            raise ValueError("lookup authority frame projection IDs must be unique")
        frame_projection_ids.add(frame_projection_id)
        ordering_keys.append((entry.event_order_index, entry.event_id))
    if ordering_keys != sorted(ordering_keys):
        raise ValueError(
            "lookup authority entries must be sorted by event_order_index and event_id"
        )


def _reject_duplicate_ids(values: tuple[str, ...], field_name: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate {field_name} IDs are not allowed")


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_datetime(value: datetime) -> str:
    return ensure_aware_utc(value).isoformat()
