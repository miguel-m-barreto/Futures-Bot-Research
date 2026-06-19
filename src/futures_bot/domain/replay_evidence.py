from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.evidence import (
    MarketEvidenceBuilderDescriptor,
    MarketEvidenceSet,
    build_market_evidence_set,
    derive_market_evidence_items,
)
from futures_bot.domain.ids import (
    DomainId,
    MarketEvidenceSetId,
    ReplayMarketEvidenceLookupEntryId,
    ReplayMarketEvidenceProjectionId,
    ReplayMarketEvidenceTimelineId,
    ReplayMarketFrameLookupEntryId,
    ReplayMarketFrameProjectionId,
)
from futures_bot.domain.market_data import MarketObservationKind
from futures_bot.domain.replay import ReplayInputKind
from futures_bot.domain.replay_market_data import (
    ReplayMarketFrameLookupAuthority,
    ReplayMarketFrameLookupDescriptor,
    ReplayMarketFrameLookupEntry,
    ReplayMarketFrameProjection,
    ReplayMarketFrameTimeline,
    build_replay_market_frame_lookup_authority,
    build_replay_market_frame_lookup_descriptor,
)
from futures_bot.domain.time import ensure_aware_utc

_MARKET_EVIDENCE_BUILDER_RE = re.compile(r"^market-evidence-builder:[0-9a-f]{64}$")
_MARKET_EVIDENCE_SET_ID_RE = re.compile(r"^market-evidence-set:[0-9a-f]{64}$")
_MARKET_FRAME_PROJECTION_ID_RE = re.compile(
    r"^replay-market-frame-projection:[0-9a-f]{64}$"
)
_MARKET_LOOKUP_ENTRY_ID_RE = re.compile(
    r"^replay-market-frame-lookup-entry:[0-9a-f]{64}$"
)
_MARKET_LOOKUP_AUTHORITY_FINGERPRINT_RE = re.compile(
    r"^replay-market-frame-lookup-authority:[0-9a-f]{64}$"
)
_PROJECTION_ID_RE = re.compile(
    r"^replay-market-evidence-projection:[0-9a-f]{64}$"
)
_TIMELINE_ID_RE = re.compile(r"^replay-market-evidence-timeline:[0-9a-f]{64}$")
_LOOKUP_ENTRY_ID_RE = re.compile(
    r"^replay-market-evidence-lookup-entry:[0-9a-f]{64}$"
)
_LOOKUP_AUTHORITY_FINGERPRINT_RE = re.compile(
    r"^replay-market-evidence-lookup-authority:[0-9a-f]{64}$"
)
_REPLAY_TO_MARKET_OBSERVATION_KIND = {
    ReplayInputKind.TRADE: MarketObservationKind.TRADE,
    ReplayInputKind.ORDER_BOOK_TOP: MarketObservationKind.TOP_OF_BOOK,
    ReplayInputKind.MARK_PRICE: MarketObservationKind.MARK_PRICE,
    ReplayInputKind.INDEX_PRICE: MarketObservationKind.INDEX_PRICE,
}


class ReplayMarketEvidenceProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    projection_id: ReplayMarketEvidenceProjectionId
    market_lookup_descriptor: ReplayMarketFrameLookupDescriptor
    market_lookup_entry: ReplayMarketFrameLookupEntry
    market_frame_projection: ReplayMarketFrameProjection
    evidence_set: MarketEvidenceSet

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("projection_id", mode="before")
    @classmethod
    def _revalidate_projection_id(
        cls,
        value: object,
    ) -> ReplayMarketEvidenceProjectionId:
        projection_id = _revalidate_domain_id(ReplayMarketEvidenceProjectionId, value)
        if not _PROJECTION_ID_RE.fullmatch(str(projection_id)):
            raise ValueError(
                "projection_id must match "
                "replay-market-evidence-projection:<64 lowercase hex>"
            )
        return projection_id

    @field_validator("market_lookup_descriptor", mode="before")
    @classmethod
    def _revalidate_lookup_descriptor(
        cls,
        value: object,
    ) -> ReplayMarketFrameLookupDescriptor:
        return _revalidate_model(ReplayMarketFrameLookupDescriptor, value)

    @field_validator("market_lookup_entry", mode="before")
    @classmethod
    def _revalidate_lookup_entry(
        cls,
        value: object,
    ) -> ReplayMarketFrameLookupEntry:
        return _revalidate_model(ReplayMarketFrameLookupEntry, value)

    @field_validator("market_frame_projection", mode="before")
    @classmethod
    def _revalidate_frame_projection(
        cls,
        value: object,
    ) -> ReplayMarketFrameProjection:
        return _revalidate_model(ReplayMarketFrameProjection, value)

    @field_validator("evidence_set", mode="before")
    @classmethod
    def _revalidate_evidence_set(cls, value: object) -> MarketEvidenceSet:
        return _revalidate_model(MarketEvidenceSet, value)

    @model_validator(mode="after")
    def _validate_projection(self) -> Self:
        validate_replay_market_evidence_projection_semantics(
            market_lookup_descriptor=self.market_lookup_descriptor,
            market_lookup_entry=self.market_lookup_entry,
            market_frame_projection=self.market_frame_projection,
            evidence_set=self.evidence_set,
        )
        expected = build_replay_market_evidence_projection_id(
            market_lookup_descriptor=self.market_lookup_descriptor,
            market_lookup_entry=self.market_lookup_entry,
            market_frame_projection=self.market_frame_projection,
            evidence_set=self.evidence_set,
        )
        if self.projection_id != expected:
            raise ValueError("projection_id must match deterministic evidence projection ID")
        return self


class ReplayMarketEvidenceTimeline(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    evidence_timeline_id: ReplayMarketEvidenceTimelineId
    market_lookup_authority: ReplayMarketFrameLookupAuthority
    evidence_builder: MarketEvidenceBuilderDescriptor
    projections: tuple[ReplayMarketEvidenceProjection, ...]

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("evidence_timeline_id", mode="before")
    @classmethod
    def _revalidate_timeline_id(
        cls,
        value: object,
    ) -> ReplayMarketEvidenceTimelineId:
        timeline_id = _revalidate_domain_id(ReplayMarketEvidenceTimelineId, value)
        if not _TIMELINE_ID_RE.fullmatch(str(timeline_id)):
            raise ValueError(
                "evidence_timeline_id must match "
                "replay-market-evidence-timeline:<64 lowercase hex>"
            )
        return timeline_id

    @field_validator("market_lookup_authority", mode="before")
    @classmethod
    def _revalidate_lookup_authority(
        cls,
        value: object,
    ) -> ReplayMarketFrameLookupAuthority:
        return _revalidate_model(ReplayMarketFrameLookupAuthority, value)

    @field_validator("evidence_builder", mode="before")
    @classmethod
    def _revalidate_evidence_builder(
        cls,
        value: object,
    ) -> MarketEvidenceBuilderDescriptor:
        return _revalidate_model(MarketEvidenceBuilderDescriptor, value)

    @field_validator("projections", mode="before")
    @classmethod
    def _revalidate_projections(
        cls,
        value: object,
    ) -> tuple[ReplayMarketEvidenceProjection, ...]:
        if not isinstance(value, tuple | list):
            raise ValueError("projections must be a tuple or list")
        return tuple(
            _revalidate_model(ReplayMarketEvidenceProjection, item) for item in value
        )

    @model_validator(mode="after")
    def _validate_timeline(self) -> Self:
        validate_replay_market_evidence_timeline_semantics(
            market_lookup_authority=self.market_lookup_authority,
            evidence_builder=self.evidence_builder,
            projections=self.projections,
        )
        expected = build_replay_market_evidence_timeline_id(
            market_lookup_authority=self.market_lookup_authority,
            evidence_builder=self.evidence_builder,
            projections=self.projections,
        )
        if self.evidence_timeline_id != expected:
            raise ValueError("evidence_timeline_id must match deterministic evidence timeline ID")
        return self


class ReplayMarketEvidenceLookupEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    entry_id: ReplayMarketEvidenceLookupEntryId
    evidence_timeline_id: ReplayMarketEvidenceTimelineId
    market_lookup_authority_fingerprint: str
    evidence_builder_fingerprint: str
    event_id: str
    event_order_index: int
    event_time: datetime
    event_kind: ReplayInputKind
    evidence_projection_id: ReplayMarketEvidenceProjectionId
    evidence_set_id: MarketEvidenceSetId
    market_frame_projection_id: ReplayMarketFrameProjectionId
    market_lookup_entry_id: ReplayMarketFrameLookupEntryId

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("entry_id", mode="before")
    @classmethod
    def _revalidate_entry_id(
        cls,
        value: object,
    ) -> ReplayMarketEvidenceLookupEntryId:
        entry_id = _revalidate_domain_id(ReplayMarketEvidenceLookupEntryId, value)
        if not _LOOKUP_ENTRY_ID_RE.fullmatch(str(entry_id)):
            raise ValueError(
                "entry_id must match "
                "replay-market-evidence-lookup-entry:<64 lowercase hex>"
            )
        return entry_id

    @field_validator("evidence_timeline_id", mode="before")
    @classmethod
    def _revalidate_evidence_timeline_id(
        cls,
        value: object,
    ) -> ReplayMarketEvidenceTimelineId:
        return _validate_evidence_timeline_id(value)

    @field_validator("market_lookup_authority_fingerprint")
    @classmethod
    def _validate_market_lookup_fingerprint(cls, value: str) -> str:
        return _validate_market_lookup_authority_fingerprint(value)

    @field_validator("evidence_builder_fingerprint")
    @classmethod
    def _validate_evidence_builder_fingerprint(cls, value: str) -> str:
        return _validate_builder_fingerprint(value)

    @field_validator("event_id")
    @classmethod
    def _validate_event_id(cls, value: str) -> str:
        return _trimmed(value, "event_id")

    @field_validator("event_order_index", mode="before")
    @classmethod
    def _validate_event_order_index(cls, value: object) -> int:
        return _strict_non_negative_int(value, "event_order_index")

    @field_validator("event_time")
    @classmethod
    def _validate_event_time(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("evidence_projection_id", mode="before")
    @classmethod
    def _revalidate_evidence_projection_id(
        cls,
        value: object,
    ) -> ReplayMarketEvidenceProjectionId:
        return _validate_evidence_projection_id(value)

    @field_validator("evidence_set_id", mode="before")
    @classmethod
    def _revalidate_evidence_set_id(cls, value: object) -> MarketEvidenceSetId:
        return _validate_evidence_set_id(value)

    @field_validator("market_frame_projection_id", mode="before")
    @classmethod
    def _revalidate_market_frame_projection_id(
        cls,
        value: object,
    ) -> ReplayMarketFrameProjectionId:
        return _validate_market_frame_projection_id(value)

    @field_validator("market_lookup_entry_id", mode="before")
    @classmethod
    def _revalidate_market_lookup_entry_id(
        cls,
        value: object,
    ) -> ReplayMarketFrameLookupEntryId:
        return _validate_market_lookup_entry_id(value)

    @model_validator(mode="after")
    def _validate_entry(self) -> Self:
        expected = build_replay_market_evidence_lookup_entry_id(
            evidence_timeline_id=self.evidence_timeline_id,
            market_lookup_authority_fingerprint=(
                self.market_lookup_authority_fingerprint
            ),
            evidence_builder_fingerprint=self.evidence_builder_fingerprint,
            event_id=self.event_id,
            event_order_index=self.event_order_index,
            event_time=self.event_time,
            event_kind=self.event_kind,
            evidence_projection_id=self.evidence_projection_id,
            evidence_set_id=self.evidence_set_id,
            market_frame_projection_id=self.market_frame_projection_id,
            market_lookup_entry_id=self.market_lookup_entry_id,
        )
        if self.entry_id != expected:
            raise ValueError("entry_id must match deterministic evidence lookup entry ID")
        return self


class ReplayMarketEvidenceLookupAuthority(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    evidence_timeline_id: ReplayMarketEvidenceTimelineId
    market_lookup_authority_fingerprint: str
    evidence_builder_fingerprint: str
    replay_timeline_id: str
    replay_plan_id: str
    supported_event_kinds: tuple[ReplayInputKind, ...]
    entries: tuple[ReplayMarketEvidenceLookupEntry, ...]
    lookup_authority_fingerprint: str

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("evidence_timeline_id", mode="before")
    @classmethod
    def _revalidate_evidence_timeline_id(
        cls,
        value: object,
    ) -> ReplayMarketEvidenceTimelineId:
        return _validate_evidence_timeline_id(value)

    @field_validator("market_lookup_authority_fingerprint")
    @classmethod
    def _validate_market_lookup_fingerprint(cls, value: str) -> str:
        return _validate_market_lookup_authority_fingerprint(value)

    @field_validator("evidence_builder_fingerprint")
    @classmethod
    def _validate_evidence_builder_fingerprint(cls, value: str) -> str:
        return _validate_builder_fingerprint(value)

    @field_validator("replay_timeline_id", "replay_plan_id")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return _trimmed(value, "evidence lookup authority text")

    @field_validator("supported_event_kinds")
    @classmethod
    def _validate_supported_event_kinds(
        cls,
        value: tuple[ReplayInputKind, ...],
    ) -> tuple[ReplayInputKind, ...]:
        return _validate_supported_event_kinds(value)

    @field_validator("entries", mode="before")
    @classmethod
    def _revalidate_entries(
        cls,
        value: object,
    ) -> tuple[ReplayMarketEvidenceLookupEntry, ...]:
        if not isinstance(value, tuple | list):
            raise ValueError("entries must be a tuple or list")
        entries = tuple(
            _revalidate_model(ReplayMarketEvidenceLookupEntry, entry)
            for entry in value
        )
        if not entries:
            raise ValueError("entries must be non-empty")
        return entries

    @field_validator("lookup_authority_fingerprint")
    @classmethod
    def _validate_lookup_authority_fingerprint(cls, value: str) -> str:
        return _validate_evidence_lookup_authority_fingerprint(value)

    @model_validator(mode="after")
    def _validate_authority(self) -> Self:
        _validate_evidence_lookup_authority_entries(
            evidence_timeline_id=self.evidence_timeline_id,
            market_lookup_authority_fingerprint=(
                self.market_lookup_authority_fingerprint
            ),
            evidence_builder_fingerprint=self.evidence_builder_fingerprint,
            supported_event_kinds=self.supported_event_kinds,
            entries=self.entries,
        )
        expected = build_replay_market_evidence_lookup_authority_fingerprint(
            evidence_timeline_id=self.evidence_timeline_id,
            market_lookup_authority_fingerprint=(
                self.market_lookup_authority_fingerprint
            ),
            evidence_builder_fingerprint=self.evidence_builder_fingerprint,
            replay_timeline_id=self.replay_timeline_id,
            replay_plan_id=self.replay_plan_id,
            supported_event_kinds=self.supported_event_kinds,
            entries=self.entries,
        )
        if self.lookup_authority_fingerprint != expected:
            raise ValueError(
                "lookup_authority_fingerprint must match evidence lookup authority"
            )
        return self


class ReplayMarketEvidenceLookupDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    evidence_timeline_id: ReplayMarketEvidenceTimelineId
    replay_timeline_id: str
    replay_plan_id: str
    market_lookup_authority_fingerprint: str
    evidence_builder_fingerprint: str
    evidence_lookup_authority_fingerprint: str
    supported_event_kinds: tuple[ReplayInputKind, ...]

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("evidence_timeline_id", mode="before")
    @classmethod
    def _revalidate_evidence_timeline_id(
        cls,
        value: object,
    ) -> ReplayMarketEvidenceTimelineId:
        return _validate_evidence_timeline_id(value)

    @field_validator("replay_timeline_id", "replay_plan_id")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return _trimmed(value, "evidence lookup descriptor text")

    @field_validator("market_lookup_authority_fingerprint")
    @classmethod
    def _validate_market_lookup_fingerprint(cls, value: str) -> str:
        return _validate_market_lookup_authority_fingerprint(value)

    @field_validator("evidence_builder_fingerprint")
    @classmethod
    def _validate_evidence_builder_fingerprint(cls, value: str) -> str:
        return _validate_builder_fingerprint(value)

    @field_validator("evidence_lookup_authority_fingerprint")
    @classmethod
    def _validate_evidence_lookup_fingerprint(cls, value: str) -> str:
        return _validate_evidence_lookup_authority_fingerprint(value)

    @field_validator("supported_event_kinds")
    @classmethod
    def _validate_supported_event_kinds(
        cls,
        value: tuple[ReplayInputKind, ...],
    ) -> tuple[ReplayInputKind, ...]:
        return _validate_supported_event_kinds(value)


class ReplayMarketEvidenceLookupResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    descriptor: ReplayMarketEvidenceLookupDescriptor
    entry: ReplayMarketEvidenceLookupEntry
    projection: ReplayMarketEvidenceProjection

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        return _strict_literal_one(value, "schema_version")

    @field_validator("descriptor", mode="before")
    @classmethod
    def _revalidate_descriptor(
        cls,
        value: object,
    ) -> ReplayMarketEvidenceLookupDescriptor:
        return _revalidate_model(ReplayMarketEvidenceLookupDescriptor, value)

    @field_validator("entry", mode="before")
    @classmethod
    def _revalidate_entry(
        cls,
        value: object,
    ) -> ReplayMarketEvidenceLookupEntry:
        return _revalidate_model(ReplayMarketEvidenceLookupEntry, value)

    @field_validator("projection", mode="before")
    @classmethod
    def _revalidate_projection(
        cls,
        value: object,
    ) -> ReplayMarketEvidenceProjection:
        return _revalidate_model(ReplayMarketEvidenceProjection, value)

    @model_validator(mode="after")
    def _validate_result(self) -> Self:
        validate_replay_market_evidence_lookup_result(
            descriptor=self.descriptor,
            entry=self.entry,
            projection=self.projection,
        )
        return self


def validate_replay_market_evidence_projection_semantics(  # noqa: PLR0912
    *,
    market_lookup_descriptor: ReplayMarketFrameLookupDescriptor,
    market_lookup_entry: ReplayMarketFrameLookupEntry,
    market_frame_projection: ReplayMarketFrameProjection,
    evidence_set: MarketEvidenceSet,
) -> None:
    descriptor = _revalidate_model(
        ReplayMarketFrameLookupDescriptor,
        market_lookup_descriptor,
    )
    entry = _revalidate_model(ReplayMarketFrameLookupEntry, market_lookup_entry)
    frame_projection = _revalidate_model(
        ReplayMarketFrameProjection,
        market_frame_projection,
    )
    evidence = _revalidate_model(MarketEvidenceSet, evidence_set)
    if entry.event_id != frame_projection.event_id:
        raise ValueError("lookup entry event_id must match frame projection")
    if entry.event_order_index != frame_projection.event_order_index:
        raise ValueError("lookup entry event_order_index must match frame projection")
    if entry.event_time != frame_projection.event_time:
        raise ValueError("lookup entry event_time must match frame projection")
    if _REPLAY_TO_MARKET_OBSERVATION_KIND.get(entry.event_kind) != (
        _event_kind_from_frame_projection(frame_projection)
    ):
        raise ValueError("lookup entry event_kind must match frame projection")
    if entry.frame_projection_id != frame_projection.projection_id:
        raise ValueError("lookup entry frame_projection_id must match frame projection")
    if entry.frame_id != frame_projection.frame.frame_id:
        raise ValueError("lookup entry frame_id must match frame projection frame")
    if entry.triggering_observation_id != frame_projection.triggering_observation_id:
        raise ValueError("lookup entry triggering_observation_id must match frame")
    if descriptor.market_timeline_id != entry.market_timeline_id:
        raise ValueError("lookup descriptor market_timeline_id must match entry")
    if descriptor.replay_timeline_id != entry.replay_timeline_id:
        raise ValueError("lookup descriptor replay_timeline_id must match entry")
    if descriptor.replay_plan_id != entry.replay_plan_id:
        raise ValueError("lookup descriptor replay_plan_id must match entry")
    if descriptor.adapter_fingerprint != entry.adapter_fingerprint:
        raise ValueError("lookup descriptor adapter_fingerprint must match entry")
    if entry.event_kind not in descriptor.supported_event_kinds:
        raise ValueError("lookup entry event_kind must be supported by descriptor")
    if evidence.source_frame != frame_projection.frame:
        raise ValueError("evidence_set source_frame must match frame projection frame")
    if evidence.source_frame.frame_id != entry.frame_id:
        raise ValueError("evidence_set source_frame frame_id must match lookup entry")
    if evidence.source_frame.as_of != entry.event_time:
        raise ValueError("evidence_set source_frame as_of must match lookup entry")
    _validate_builder_fingerprint(evidence.builder.builder_fingerprint)


def build_replay_market_evidence_projection_id(
    *,
    market_lookup_descriptor: ReplayMarketFrameLookupDescriptor,
    market_lookup_entry: ReplayMarketFrameLookupEntry,
    market_frame_projection: ReplayMarketFrameProjection,
    evidence_set: MarketEvidenceSet,
) -> ReplayMarketEvidenceProjectionId:
    descriptor = _revalidate_model(
        ReplayMarketFrameLookupDescriptor,
        market_lookup_descriptor,
    )
    entry = _revalidate_model(ReplayMarketFrameLookupEntry, market_lookup_entry)
    frame_projection = _revalidate_model(
        ReplayMarketFrameProjection,
        market_frame_projection,
    )
    evidence = _revalidate_model(MarketEvidenceSet, evidence_set)
    validate_replay_market_evidence_projection_semantics(
        market_lookup_descriptor=descriptor,
        market_lookup_entry=entry,
        market_frame_projection=frame_projection,
        evidence_set=evidence,
    )
    material = {
        "schema_version": 1,
        "evidence_set": evidence.model_dump(mode="json"),
        "market_frame_projection": frame_projection.model_dump(mode="json"),
        "market_lookup_descriptor": descriptor.model_dump(mode="json"),
        "market_lookup_entry": entry.model_dump(mode="json"),
    }
    return ReplayMarketEvidenceProjectionId.from_str(
        f"replay-market-evidence-projection:{_sha256_text(_canonical_json(material))}"
    )


def build_replay_market_evidence_projection(
    *,
    market_lookup_descriptor: ReplayMarketFrameLookupDescriptor,
    market_lookup_entry: ReplayMarketFrameLookupEntry,
    market_frame_projection: ReplayMarketFrameProjection,
    evidence_set: MarketEvidenceSet,
) -> ReplayMarketEvidenceProjection:
    projection_id = build_replay_market_evidence_projection_id(
        market_lookup_descriptor=market_lookup_descriptor,
        market_lookup_entry=market_lookup_entry,
        market_frame_projection=market_frame_projection,
        evidence_set=evidence_set,
    )
    return ReplayMarketEvidenceProjection(
        projection_id=projection_id,
        market_lookup_descriptor=market_lookup_descriptor,
        market_lookup_entry=market_lookup_entry,
        market_frame_projection=market_frame_projection,
        evidence_set=evidence_set,
    )


def validate_replay_market_evidence_timeline_semantics(
    *,
    market_lookup_authority: ReplayMarketFrameLookupAuthority,
    evidence_builder: MarketEvidenceBuilderDescriptor,
    projections: tuple[ReplayMarketEvidenceProjection, ...],
) -> None:
    authority = _revalidate_model(ReplayMarketFrameLookupAuthority, market_lookup_authority)
    builder = _revalidate_model(MarketEvidenceBuilderDescriptor, evidence_builder)
    revalidated_projections = tuple(
        _revalidate_model(ReplayMarketEvidenceProjection, projection)
        for projection in projections
    )
    if not authority.entries:
        raise ValueError("market_lookup_authority entries must be non-empty")
    if not revalidated_projections:
        raise ValueError("projections must be non-empty")
    if len(revalidated_projections) != len(authority.entries):
        raise ValueError("one evidence projection is required per lookup entry")
    descriptor = build_replay_market_frame_lookup_descriptor(authority)
    projection_ids: set[str] = set()
    entry_ids: set[str] = set()
    for entry, projection in zip(authority.entries, revalidated_projections, strict=True):
        projection_id = str(projection.projection_id)
        if projection_id in projection_ids:
            raise ValueError("duplicate evidence projection ID")
        projection_ids.add(projection_id)
        entry_id = str(projection.market_lookup_entry.entry_id)
        if entry_id in entry_ids:
            raise ValueError("duplicate market lookup entry")
        entry_ids.add(entry_id)
        if projection.market_lookup_descriptor != descriptor:
            raise ValueError("projection descriptor must match lookup authority")
        if projection.market_lookup_entry != entry:
            raise ValueError(
                "projection lookup entry must match authority entry in canonical order"
            )
        if projection.evidence_set.builder != builder:
            raise ValueError("projection evidence builder must match timeline builder")
        if projection.evidence_set.source_frame != projection.market_frame_projection.frame:
            raise ValueError("projection evidence source_frame must match frame projection")


def build_replay_market_evidence_timeline_id(
    *,
    market_lookup_authority: ReplayMarketFrameLookupAuthority,
    evidence_builder: MarketEvidenceBuilderDescriptor,
    projections: tuple[ReplayMarketEvidenceProjection, ...],
) -> ReplayMarketEvidenceTimelineId:
    authority = _revalidate_model(ReplayMarketFrameLookupAuthority, market_lookup_authority)
    builder = _revalidate_model(MarketEvidenceBuilderDescriptor, evidence_builder)
    revalidated_projections = tuple(
        _revalidate_model(ReplayMarketEvidenceProjection, projection)
        for projection in projections
    )
    validate_replay_market_evidence_timeline_semantics(
        market_lookup_authority=authority,
        evidence_builder=builder,
        projections=revalidated_projections,
    )
    material = {
        "schema_version": 1,
        "evidence_builder": builder.model_dump(mode="json"),
        "market_lookup_authority": authority.model_dump(mode="json"),
        "projections": [
            projection.model_dump(mode="json") for projection in revalidated_projections
        ],
    }
    return ReplayMarketEvidenceTimelineId.from_str(
        f"replay-market-evidence-timeline:{_sha256_text(_canonical_json(material))}"
    )


def build_replay_market_evidence_timeline(
    *,
    market_lookup_authority: ReplayMarketFrameLookupAuthority,
    evidence_builder: MarketEvidenceBuilderDescriptor,
    projections: tuple[ReplayMarketEvidenceProjection, ...],
) -> ReplayMarketEvidenceTimeline:
    evidence_timeline_id = build_replay_market_evidence_timeline_id(
        market_lookup_authority=market_lookup_authority,
        evidence_builder=evidence_builder,
        projections=projections,
    )
    return ReplayMarketEvidenceTimeline(
        evidence_timeline_id=evidence_timeline_id,
        market_lookup_authority=market_lookup_authority,
        evidence_builder=evidence_builder,
        projections=projections,
    )


def build_replay_market_evidence_lookup_entry_id(  # noqa: PLR0913
    *,
    evidence_timeline_id: ReplayMarketEvidenceTimelineId,
    market_lookup_authority_fingerprint: str,
    evidence_builder_fingerprint: str,
    event_id: str,
    event_order_index: int,
    event_time: datetime,
    event_kind: ReplayInputKind,
    evidence_projection_id: ReplayMarketEvidenceProjectionId,
    evidence_set_id: MarketEvidenceSetId,
    market_frame_projection_id: ReplayMarketFrameProjectionId,
    market_lookup_entry_id: ReplayMarketFrameLookupEntryId,
) -> ReplayMarketEvidenceLookupEntryId:
    material = {
        "schema_version": 1,
        "event_id": _trimmed(event_id, "event_id"),
        "event_kind": ReplayInputKind(event_kind).value,
        "event_order_index": _strict_non_negative_int(
            event_order_index,
            "event_order_index",
        ),
        "event_time": _json_datetime(event_time),
        "evidence_builder_fingerprint": _validate_builder_fingerprint(
            evidence_builder_fingerprint
        ),
        "evidence_projection_id": _validate_evidence_projection_id(
            evidence_projection_id
        ).model_dump(mode="json"),
        "evidence_set_id": _validate_evidence_set_id(evidence_set_id).model_dump(
            mode="json"
        ),
        "evidence_timeline_id": _validate_evidence_timeline_id(
            evidence_timeline_id
        ).model_dump(mode="json"),
        "market_frame_projection_id": _validate_market_frame_projection_id(
            market_frame_projection_id
        ).model_dump(mode="json"),
        "market_lookup_authority_fingerprint": (
            _validate_market_lookup_authority_fingerprint(
                market_lookup_authority_fingerprint
            )
        ),
        "market_lookup_entry_id": _validate_market_lookup_entry_id(
            market_lookup_entry_id
        ).model_dump(mode="json"),
    }
    return ReplayMarketEvidenceLookupEntryId.from_str(
        "replay-market-evidence-lookup-entry:"
        f"{_sha256_text(_canonical_json(material))}"
    )


def build_replay_market_evidence_lookup_entry(
    *,
    evidence_timeline_id: ReplayMarketEvidenceTimelineId,
    market_lookup_authority_fingerprint: str,
    evidence_builder_fingerprint: str,
    projection: ReplayMarketEvidenceProjection,
) -> ReplayMarketEvidenceLookupEntry:
    revalidated_projection = _revalidate_model(ReplayMarketEvidenceProjection, projection)
    lookup_entry = revalidated_projection.market_lookup_entry
    entry_id = build_replay_market_evidence_lookup_entry_id(
        evidence_timeline_id=evidence_timeline_id,
        market_lookup_authority_fingerprint=market_lookup_authority_fingerprint,
        evidence_builder_fingerprint=evidence_builder_fingerprint,
        event_id=lookup_entry.event_id,
        event_order_index=lookup_entry.event_order_index,
        event_time=lookup_entry.event_time,
        event_kind=lookup_entry.event_kind,
        evidence_projection_id=revalidated_projection.projection_id,
        evidence_set_id=revalidated_projection.evidence_set.evidence_set_id,
        market_frame_projection_id=(
            revalidated_projection.market_frame_projection.projection_id
        ),
        market_lookup_entry_id=lookup_entry.entry_id,
    )
    return ReplayMarketEvidenceLookupEntry(
        entry_id=entry_id,
        evidence_timeline_id=evidence_timeline_id,
        market_lookup_authority_fingerprint=market_lookup_authority_fingerprint,
        evidence_builder_fingerprint=evidence_builder_fingerprint,
        event_id=lookup_entry.event_id,
        event_order_index=lookup_entry.event_order_index,
        event_time=lookup_entry.event_time,
        event_kind=lookup_entry.event_kind,
        evidence_projection_id=revalidated_projection.projection_id,
        evidence_set_id=revalidated_projection.evidence_set.evidence_set_id,
        market_frame_projection_id=(
            revalidated_projection.market_frame_projection.projection_id
        ),
        market_lookup_entry_id=lookup_entry.entry_id,
    )


def build_replay_market_evidence_lookup_authority_fingerprint(  # noqa: PLR0913
    *,
    evidence_timeline_id: ReplayMarketEvidenceTimelineId,
    market_lookup_authority_fingerprint: str,
    evidence_builder_fingerprint: str,
    replay_timeline_id: str,
    replay_plan_id: str,
    supported_event_kinds: tuple[ReplayInputKind, ...],
    entries: tuple[ReplayMarketEvidenceLookupEntry, ...],
) -> str:
    revalidated_timeline_id = _validate_evidence_timeline_id(evidence_timeline_id)
    revalidated_market_lookup_fingerprint = (
        _validate_market_lookup_authority_fingerprint(
            market_lookup_authority_fingerprint
        )
    )
    revalidated_builder_fingerprint = _validate_builder_fingerprint(
        evidence_builder_fingerprint
    )
    revalidated_kinds = _validate_supported_event_kinds(supported_event_kinds)
    revalidated_entries = tuple(
        _revalidate_model(ReplayMarketEvidenceLookupEntry, entry)
        for entry in entries
    )
    _validate_evidence_lookup_authority_entries(
        evidence_timeline_id=revalidated_timeline_id,
        market_lookup_authority_fingerprint=revalidated_market_lookup_fingerprint,
        evidence_builder_fingerprint=revalidated_builder_fingerprint,
        supported_event_kinds=revalidated_kinds,
        entries=revalidated_entries,
    )
    material = {
        "schema_version": 1,
        "entries": [entry.model_dump(mode="json") for entry in revalidated_entries],
        "evidence_builder_fingerprint": revalidated_builder_fingerprint,
        "evidence_timeline_id": revalidated_timeline_id.model_dump(mode="json"),
        "market_lookup_authority_fingerprint": (
            revalidated_market_lookup_fingerprint
        ),
        "replay_plan_id": _trimmed(replay_plan_id, "replay_plan_id"),
        "replay_timeline_id": _trimmed(replay_timeline_id, "replay_timeline_id"),
        "supported_event_kinds": [kind.value for kind in revalidated_kinds],
    }
    return (
        "replay-market-evidence-lookup-authority:"
        f"{_sha256_text(_canonical_json(material))}"
    )


def build_replay_market_evidence_lookup_authority(
    evidence_timeline: ReplayMarketEvidenceTimeline,
) -> ReplayMarketEvidenceLookupAuthority:
    timeline = _revalidate_model(ReplayMarketEvidenceTimeline, evidence_timeline)
    market_authority = timeline.market_lookup_authority
    entries = tuple(
        build_replay_market_evidence_lookup_entry(
            evidence_timeline_id=timeline.evidence_timeline_id,
            market_lookup_authority_fingerprint=(
                market_authority.lookup_authority_fingerprint
            ),
            evidence_builder_fingerprint=(
                timeline.evidence_builder.builder_fingerprint
            ),
            projection=projection,
        )
        for projection in timeline.projections
    )
    fingerprint = build_replay_market_evidence_lookup_authority_fingerprint(
        evidence_timeline_id=timeline.evidence_timeline_id,
        market_lookup_authority_fingerprint=market_authority.lookup_authority_fingerprint,
        evidence_builder_fingerprint=timeline.evidence_builder.builder_fingerprint,
        replay_timeline_id=market_authority.replay_timeline_id,
        replay_plan_id=market_authority.replay_plan_id,
        supported_event_kinds=market_authority.supported_event_kinds,
        entries=entries,
    )
    return ReplayMarketEvidenceLookupAuthority(
        evidence_timeline_id=timeline.evidence_timeline_id,
        market_lookup_authority_fingerprint=market_authority.lookup_authority_fingerprint,
        evidence_builder_fingerprint=timeline.evidence_builder.builder_fingerprint,
        replay_timeline_id=market_authority.replay_timeline_id,
        replay_plan_id=market_authority.replay_plan_id,
        supported_event_kinds=market_authority.supported_event_kinds,
        entries=entries,
        lookup_authority_fingerprint=fingerprint,
    )


def build_replay_market_evidence_lookup_descriptor(
    authority: ReplayMarketEvidenceLookupAuthority,
) -> ReplayMarketEvidenceLookupDescriptor:
    revalidated = _revalidate_model(ReplayMarketEvidenceLookupAuthority, authority)
    return ReplayMarketEvidenceLookupDescriptor(
        evidence_timeline_id=revalidated.evidence_timeline_id,
        replay_timeline_id=revalidated.replay_timeline_id,
        replay_plan_id=revalidated.replay_plan_id,
        market_lookup_authority_fingerprint=(
            revalidated.market_lookup_authority_fingerprint
        ),
        evidence_builder_fingerprint=revalidated.evidence_builder_fingerprint,
        evidence_lookup_authority_fingerprint=(
            revalidated.lookup_authority_fingerprint
        ),
        supported_event_kinds=revalidated.supported_event_kinds,
    )


def validate_replay_market_evidence_lookup_result(
    *,
    descriptor: ReplayMarketEvidenceLookupDescriptor,
    entry: ReplayMarketEvidenceLookupEntry,
    projection: ReplayMarketEvidenceProjection,
) -> None:
    revalidated_descriptor = _revalidate_model(
        ReplayMarketEvidenceLookupDescriptor,
        descriptor,
    )
    revalidated_entry = _revalidate_model(ReplayMarketEvidenceLookupEntry, entry)
    revalidated_projection = _revalidate_model(
        ReplayMarketEvidenceProjection,
        projection,
    )
    if revalidated_entry.evidence_timeline_id != (
        revalidated_descriptor.evidence_timeline_id
    ):
        raise ValueError("lookup entry evidence_timeline_id must match descriptor")
    if revalidated_entry.market_lookup_authority_fingerprint != (
        revalidated_descriptor.market_lookup_authority_fingerprint
    ):
        raise ValueError(
            "lookup entry market_lookup_authority_fingerprint must match descriptor"
        )
    if revalidated_entry.evidence_builder_fingerprint != (
        revalidated_descriptor.evidence_builder_fingerprint
    ):
        raise ValueError(
            "lookup entry evidence_builder_fingerprint must match descriptor"
        )
    if revalidated_entry.event_kind not in revalidated_descriptor.supported_event_kinds:
        raise ValueError("lookup entry event_kind must be supported by descriptor")
    _validate_evidence_lookup_entry_projection_pair(
        entry=revalidated_entry,
        projection=revalidated_projection,
    )


def build_replay_market_evidence_lookup_result(
    *,
    descriptor: ReplayMarketEvidenceLookupDescriptor,
    entry: ReplayMarketEvidenceLookupEntry,
    projection: ReplayMarketEvidenceProjection,
) -> ReplayMarketEvidenceLookupResult:
    validate_replay_market_evidence_lookup_result(
        descriptor=descriptor,
        entry=entry,
        projection=projection,
    )
    return ReplayMarketEvidenceLookupResult(
        descriptor=descriptor,
        entry=entry,
        projection=projection,
    )


def validate_replay_market_evidence_lookup_membership(
    *,
    authority: ReplayMarketEvidenceLookupAuthority,
    result: ReplayMarketEvidenceLookupResult,
) -> None:
    revalidated_authority = _revalidate_model(
        ReplayMarketEvidenceLookupAuthority,
        authority,
    )
    revalidated_result = _revalidate_model(ReplayMarketEvidenceLookupResult, result)
    expected_descriptor = build_replay_market_evidence_lookup_descriptor(
        revalidated_authority
    )
    if revalidated_result.descriptor != expected_descriptor:
        raise ValueError("lookup result descriptor must match lookup authority")
    entries_by_id = {
        str(entry.entry_id): entry for entry in revalidated_authority.entries
    }
    authority_entry = entries_by_id.get(str(revalidated_result.entry.entry_id))
    if authority_entry is None:
        raise ValueError("lookup result entry is absent from lookup authority")
    if authority_entry != revalidated_result.entry:
        raise ValueError("lookup result entry differs from lookup authority")
    key = _event_key(
        revalidated_result.entry.event_id,
        revalidated_result.entry.event_order_index,
    )
    matches = tuple(
        entry
        for entry in revalidated_authority.entries
        if _event_key(entry.event_id, entry.event_order_index) == key
    )
    if matches != (authority_entry,):
        raise ValueError("lookup result event key must identify exactly one entry")
    validate_replay_market_evidence_lookup_result(
        descriptor=revalidated_result.descriptor,
        entry=revalidated_result.entry,
        projection=revalidated_result.projection,
    )


def replay_market_evidence_projection_key(
    projection: ReplayMarketEvidenceProjection,
) -> tuple[int, str]:
    projection = _revalidate_model(ReplayMarketEvidenceProjection, projection)
    return (
        projection.market_lookup_entry.event_order_index,
        projection.market_lookup_entry.event_id,
    )


def derive_replay_market_evidence_projections(
    *,
    market_frame_timeline: ReplayMarketFrameTimeline,
    market_lookup_authority: ReplayMarketFrameLookupAuthority,
    evidence_builder: MarketEvidenceBuilderDescriptor,
) -> tuple[ReplayMarketEvidenceProjection, ...]:
    timeline = _revalidate_model(ReplayMarketFrameTimeline, market_frame_timeline)
    authority = _revalidate_model(ReplayMarketFrameLookupAuthority, market_lookup_authority)
    builder = _revalidate_model(MarketEvidenceBuilderDescriptor, evidence_builder)
    expected_authority = build_replay_market_frame_lookup_authority(timeline)
    if authority != expected_authority:
        raise ValueError("market lookup authority must correspond exactly to timeline")
    descriptor = build_replay_market_frame_lookup_descriptor(authority)
    projections: list[ReplayMarketEvidenceProjection] = []
    for entry, frame_projection in zip(
        authority.entries,
        timeline.frame_projections,
        strict=True,
    ):
        if entry.frame_projection_id != frame_projection.projection_id:
            raise ValueError("lookup entry frame projection must match timeline order")
        items = derive_market_evidence_items(
            source_frame=frame_projection.frame,
            builder=builder,
        )
        evidence_set = build_market_evidence_set(
            builder=builder,
            source_frame=frame_projection.frame,
            items=items,
        )
        projections.append(
            build_replay_market_evidence_projection(
                market_lookup_descriptor=descriptor,
                market_lookup_entry=entry,
                market_frame_projection=frame_projection,
                evidence_set=evidence_set,
            )
        )
    return tuple(projections)


def _event_kind_from_frame_projection(
    frame_projection: ReplayMarketFrameProjection,
) -> MarketObservationKind:
    triggering_id = frame_projection.triggering_observation_id
    for observation in frame_projection.frame.observations:
        if observation.observation_id == triggering_id:
            return observation.payload.kind
    raise ValueError("triggering observation ID must exist in frame projection frame")


def _validate_evidence_lookup_authority_entries(
    *,
    evidence_timeline_id: ReplayMarketEvidenceTimelineId,
    market_lookup_authority_fingerprint: str,
    evidence_builder_fingerprint: str,
    supported_event_kinds: tuple[ReplayInputKind, ...],
    entries: tuple[ReplayMarketEvidenceLookupEntry, ...],
) -> None:
    if not entries:
        raise ValueError("evidence lookup authority entries must be non-empty")
    ordering_keys: list[tuple[int, str]] = []
    event_ids: set[str] = set()
    event_order_indexes: set[int] = set()
    event_keys: set[tuple[str, int]] = set()
    entry_ids: set[str] = set()
    evidence_projection_ids: set[str] = set()
    evidence_set_ids: set[str] = set()
    market_frame_projection_ids: set[str] = set()
    market_lookup_entry_ids: set[str] = set()
    for entry in entries:
        if entry.evidence_timeline_id != evidence_timeline_id:
            raise ValueError("lookup entry evidence_timeline_id mismatch")
        if entry.market_lookup_authority_fingerprint != (
            market_lookup_authority_fingerprint
        ):
            raise ValueError("lookup entry market_lookup_authority_fingerprint mismatch")
        if entry.evidence_builder_fingerprint != evidence_builder_fingerprint:
            raise ValueError("lookup entry evidence_builder_fingerprint mismatch")
        if entry.event_kind not in supported_event_kinds:
            raise ValueError("lookup entry event kind is unsupported")
        _reject_duplicate_value(str(entry.entry_id), entry_ids, "entry_id")
        _reject_duplicate_value(entry.event_id, event_ids, "event_id")
        _reject_duplicate_value(
            entry.event_order_index,
            event_order_indexes,
            "event_order_index",
        )
        event_key = _event_key(entry.event_id, entry.event_order_index)
        _reject_duplicate_value(event_key, event_keys, "event key")
        _reject_duplicate_value(
            str(entry.evidence_projection_id),
            evidence_projection_ids,
            "evidence_projection_id",
        )
        _reject_duplicate_value(
            str(entry.evidence_set_id),
            evidence_set_ids,
            "evidence_set_id",
        )
        _reject_duplicate_value(
            str(entry.market_frame_projection_id),
            market_frame_projection_ids,
            "market_frame_projection_id",
        )
        _reject_duplicate_value(
            str(entry.market_lookup_entry_id),
            market_lookup_entry_ids,
            "market_lookup_entry_id",
        )
        ordering_keys.append((entry.event_order_index, entry.event_id))
    if ordering_keys != sorted(ordering_keys):
        raise ValueError(
            "evidence lookup authority entries must be sorted by "
            "event_order_index and event_id"
        )


def _validate_evidence_lookup_entry_projection_pair(
    *,
    entry: ReplayMarketEvidenceLookupEntry,
    projection: ReplayMarketEvidenceProjection,
) -> None:
    if projection.projection_id != entry.evidence_projection_id:
        raise ValueError("projection_id must match lookup entry")
    if projection.evidence_set.evidence_set_id != entry.evidence_set_id:
        raise ValueError("evidence_set_id must match lookup entry")
    if (
        projection.market_frame_projection.projection_id
        != entry.market_frame_projection_id
    ):
        raise ValueError("market frame projection ID must match lookup entry")
    if projection.market_lookup_entry.entry_id != entry.market_lookup_entry_id:
        raise ValueError("market lookup entry ID must match lookup entry")
    if projection.market_lookup_entry.event_id != entry.event_id:
        raise ValueError("projection lookup event_id must match lookup entry")
    if projection.market_lookup_entry.event_order_index != entry.event_order_index:
        raise ValueError("projection lookup event_order_index must match lookup entry")
    if projection.market_lookup_entry.event_time != entry.event_time:
        raise ValueError("projection lookup event_time must match lookup entry")
    if projection.market_lookup_entry.event_kind != entry.event_kind:
        raise ValueError("projection lookup event_kind must match lookup entry")


def _validate_evidence_timeline_id(value: object) -> ReplayMarketEvidenceTimelineId:
    timeline_id = _revalidate_domain_id(ReplayMarketEvidenceTimelineId, value)
    if not _TIMELINE_ID_RE.fullmatch(str(timeline_id)):
        raise ValueError(
            "evidence_timeline_id must match "
            "replay-market-evidence-timeline:<64 lowercase hex>"
        )
    return timeline_id


def _validate_evidence_projection_id(
    value: object,
) -> ReplayMarketEvidenceProjectionId:
    projection_id = _revalidate_domain_id(ReplayMarketEvidenceProjectionId, value)
    if not _PROJECTION_ID_RE.fullmatch(str(projection_id)):
        raise ValueError(
            "evidence_projection_id must match "
            "replay-market-evidence-projection:<64 lowercase hex>"
        )
    return projection_id


def _validate_evidence_set_id(value: object) -> MarketEvidenceSetId:
    evidence_set_id = _revalidate_domain_id(MarketEvidenceSetId, value)
    if not _MARKET_EVIDENCE_SET_ID_RE.fullmatch(str(evidence_set_id)):
        raise ValueError(
            "evidence_set_id must match market-evidence-set:<64 lowercase hex>"
        )
    return evidence_set_id


def _validate_market_frame_projection_id(
    value: object,
) -> ReplayMarketFrameProjectionId:
    projection_id = _revalidate_domain_id(ReplayMarketFrameProjectionId, value)
    if not _MARKET_FRAME_PROJECTION_ID_RE.fullmatch(str(projection_id)):
        raise ValueError(
            "market_frame_projection_id must match "
            "replay-market-frame-projection:<64 lowercase hex>"
        )
    return projection_id


def _validate_market_lookup_entry_id(
    value: object,
) -> ReplayMarketFrameLookupEntryId:
    entry_id = _revalidate_domain_id(ReplayMarketFrameLookupEntryId, value)
    if not _MARKET_LOOKUP_ENTRY_ID_RE.fullmatch(str(entry_id)):
        raise ValueError(
            "market_lookup_entry_id must match "
            "replay-market-frame-lookup-entry:<64 lowercase hex>"
        )
    return entry_id


def _validate_market_lookup_authority_fingerprint(value: str) -> str:
    value = _trimmed(value, "market_lookup_authority_fingerprint")
    if not _MARKET_LOOKUP_AUTHORITY_FINGERPRINT_RE.fullmatch(value):
        raise ValueError(
            "market_lookup_authority_fingerprint must match "
            "replay-market-frame-lookup-authority:<64 lowercase hex>"
        )
    return value


def _validate_evidence_lookup_authority_fingerprint(value: str) -> str:
    value = _trimmed(value, "evidence_lookup_authority_fingerprint")
    if not _LOOKUP_AUTHORITY_FINGERPRINT_RE.fullmatch(value):
        raise ValueError(
            "evidence_lookup_authority_fingerprint must match "
            "replay-market-evidence-lookup-authority:<64 lowercase hex>"
        )
    return value


def _validate_builder_fingerprint(value: str) -> str:
    value = _trimmed(value, "builder_fingerprint")
    if not _MARKET_EVIDENCE_BUILDER_RE.fullmatch(value):
        raise ValueError(
            "builder_fingerprint must match market-evidence-builder:<64 lowercase hex>"
        )
    return value


def _validate_supported_event_kinds(
    value: tuple[ReplayInputKind, ...],
) -> tuple[ReplayInputKind, ...]:
    if not value:
        raise ValueError("supported_event_kinds must be non-empty")
    kinds = tuple(ReplayInputKind(kind) for kind in value)
    if len(kinds) != len(set(kinds)):
        raise ValueError("supported_event_kinds must be unique")
    if kinds != tuple(sorted(kinds, key=lambda kind: kind.value)):
        raise ValueError("supported_event_kinds must be sorted by enum value")
    return kinds


def _event_key(event_id: str, event_order_index: int) -> tuple[str, int]:
    return (_trimmed(event_id, "event_id"), event_order_index)


def _reject_duplicate_value[T](
    value: T,
    seen: set[T],
    field_name: str,
) -> None:
    if value in seen:
        raise ValueError(f"duplicate {field_name} is not allowed")
    seen.add(value)


def _revalidate_domain_id[T: DomainId](id_type: type[T], value: object) -> T:
    if isinstance(value, id_type):
        return id_type.model_validate(value.model_dump(mode="json"))
    if isinstance(value, DomainId):
        return id_type.from_str(str(value))
    if isinstance(value, str):
        return id_type.from_str(value)
    return id_type.model_validate(value)


def _revalidate_model[T: BaseModel](model_type: type[T], value: object) -> T:
    if isinstance(value, BaseModel):
        dumped = value.model_dump(mode="json")
        if dumped is value:
            raise ValueError("model_dump must return inert plain data")
        model = model_type.model_validate(dumped)
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


def _trimmed(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty trimmed string")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_datetime(value: datetime) -> str:
    return ensure_aware_utc(value).isoformat()
