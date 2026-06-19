from __future__ import annotations

import hashlib
import json
import re
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
    ReplayMarketEvidenceProjectionId,
    ReplayMarketEvidenceTimelineId,
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

_MARKET_EVIDENCE_BUILDER_RE = re.compile(r"^market-evidence-builder:[0-9a-f]{64}$")
_PROJECTION_ID_RE = re.compile(
    r"^replay-market-evidence-projection:[0-9a-f]{64}$"
)
_TIMELINE_ID_RE = re.compile(r"^replay-market-evidence-timeline:[0-9a-f]{64}$")
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


def _validate_builder_fingerprint(value: str) -> str:
    value = _trimmed(value, "builder_fingerprint")
    if not _MARKET_EVIDENCE_BUILDER_RE.fullmatch(value):
        raise ValueError(
            "builder_fingerprint must match market-evidence-builder:<64 lowercase hex>"
        )
    return value


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
