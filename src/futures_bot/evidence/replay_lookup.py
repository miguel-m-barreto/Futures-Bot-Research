from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel

from futures_bot.domain.replay import ReplayDispatchContext, ReplayTimelineEvent
from futures_bot.domain.replay_evidence import (
    ReplayMarketEvidenceLookupAuthority,
    ReplayMarketEvidenceLookupDescriptor,
    ReplayMarketEvidenceLookupEntry,
    ReplayMarketEvidenceLookupResult,
    ReplayMarketEvidenceProjection,
    ReplayMarketEvidenceTimeline,
    build_replay_market_evidence_lookup_authority,
    build_replay_market_evidence_lookup_descriptor,
    build_replay_market_evidence_lookup_result,
    validate_replay_market_evidence_lookup_membership,
)

type _EventKey = tuple[str, int]
type _LookupProjection = tuple[
    ReplayMarketEvidenceLookupEntry,
    ReplayMarketEvidenceProjection,
]


class LocalReplayMarketEvidenceLookup:
    def __init__(
        self,
        evidence_timeline: ReplayMarketEvidenceTimeline,
    ) -> None:
        timeline = _snapshot_model(ReplayMarketEvidenceTimeline, evidence_timeline)
        authority = build_replay_market_evidence_lookup_authority(timeline)
        descriptor = build_replay_market_evidence_lookup_descriptor(authority)
        projections: dict[_EventKey, _LookupProjection] = {}
        for entry, projection in zip(
            authority.entries,
            timeline.projections,
            strict=True,
        ):
            result = build_replay_market_evidence_lookup_result(
                descriptor=descriptor,
                entry=entry,
                projection=projection,
            )
            validate_replay_market_evidence_lookup_membership(
                authority=authority,
                result=result,
            )
            key = _event_key(entry.event_id, entry.event_order_index)
            if key in projections:
                raise ValueError("ambiguous replay market evidence projection key")
            projections[key] = (entry, projection)
        self._authority = _snapshot_model(ReplayMarketEvidenceLookupAuthority, authority)
        self._descriptor = _snapshot_model(
            ReplayMarketEvidenceLookupDescriptor,
            descriptor,
        )
        self._projections = dict(projections)

    @property
    def authority(self) -> ReplayMarketEvidenceLookupAuthority:
        return _snapshot_model(ReplayMarketEvidenceLookupAuthority, self._authority)

    @property
    def descriptor(self) -> ReplayMarketEvidenceLookupDescriptor:
        return _snapshot_model(ReplayMarketEvidenceLookupDescriptor, self._descriptor)

    def lookup(
        self,
        context: ReplayDispatchContext,
        event: ReplayTimelineEvent,
    ) -> ReplayMarketEvidenceLookupResult:
        revalidated_context = _snapshot_model(ReplayDispatchContext, context)
        revalidated_event = _snapshot_model(ReplayTimelineEvent, event)
        descriptor = self.descriptor
        authority = self.authority
        _validate_context_matches_event(revalidated_context, revalidated_event)
        if revalidated_context.timeline_id != descriptor.replay_timeline_id:
            raise ValueError("dispatch context timeline_id does not match evidence lookup")
        if revalidated_context.replay_plan_id != descriptor.replay_plan_id:
            raise ValueError(
                "dispatch context replay_plan_id does not match evidence lookup"
            )
        if revalidated_event.kind not in descriptor.supported_event_kinds:
            raise ValueError("event kind is not supported by evidence lookup")
        projection = self._projections.get(
            _event_key(revalidated_event.event_id, revalidated_event.order_index)
        )
        if projection is None:
            raise ValueError("no replay market evidence projection for event")
        entry, evidence_projection = projection
        if entry.event_id != revalidated_event.event_id:
            raise ValueError("evidence projection event_id does not match event")
        if entry.event_order_index != revalidated_event.order_index:
            raise ValueError("evidence projection order_index does not match event")
        if entry.event_time != revalidated_event.event_time:
            raise ValueError("evidence projection event_time does not match event")
        if entry.event_kind != revalidated_event.kind:
            raise ValueError("evidence projection event_kind does not match event")
        result = build_replay_market_evidence_lookup_result(
            descriptor=descriptor,
            entry=entry,
            projection=evidence_projection,
        )
        validate_replay_market_evidence_lookup_membership(
            authority=authority,
            result=result,
        )
        return result


def _snapshot_model[T: BaseModel](model_type: type[T], value: object) -> T:
    if isinstance(value, BaseModel):
        dumped = value.model_dump(mode="json")
        if dumped is value:
            raise ValueError("model_dump must return inert plain data")
        if isinstance(value, model_type) and type(value) is not model_type:
            raise ValueError(f"expected exact {model_type.__name__}")
        model = model_type.model_validate(dumped)
    elif isinstance(value, Mapping):
        if type(value) is not dict:
            raise ValueError("boundary mappings must be exact built-in dict")
        model = model_type.model_validate(value)
    else:
        model = model_type.model_validate(value)
    if type(model) is not model_type:
        raise ValueError(f"expected exact {model_type.__name__}")
    return model


def _event_key(event_id: str, event_order_index: int) -> _EventKey:
    return (event_id, event_order_index)


def _validate_context_matches_event(
    context: ReplayDispatchContext,
    event: ReplayTimelineEvent,
) -> None:
    if context.event_id != event.event_id:
        raise ValueError("dispatch context event_id does not match event")
    if context.event_order_index != event.order_index:
        raise ValueError("dispatch context event_order_index does not match event")
    if context.event_time != event.event_time:
        raise ValueError("dispatch context event_time does not match event")
    if context.event_kind != event.kind:
        raise ValueError("dispatch context event_kind does not match event")
