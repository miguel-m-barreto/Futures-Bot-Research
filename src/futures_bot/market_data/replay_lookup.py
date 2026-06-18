from __future__ import annotations

from futures_bot.domain.replay import ReplayDispatchContext, ReplayTimelineEvent
from futures_bot.domain.replay_market_data import (
    ReplayMarketFrameLookupAuthority,
    ReplayMarketFrameLookupDescriptor,
    ReplayMarketFrameLookupEntry,
    ReplayMarketFrameLookupResult,
    ReplayMarketFrameProjection,
    ReplayMarketFrameTimeline,
    ReplayMarketObservationProjection,
    build_replay_market_frame_lookup_authority,
    build_replay_market_frame_lookup_descriptor,
    build_replay_market_frame_lookup_result,
    validate_replay_market_frame_lookup_membership,
)

type _EventKey = tuple[str, int]
type _LookupProjection = tuple[
    ReplayMarketFrameLookupEntry,
    ReplayMarketObservationProjection,
    ReplayMarketFrameProjection,
]


class LocalReplayMarketFrameLookup:
    """Immutable local lookup over a validated replay market-frame timeline."""

    def __init__(self, market_timeline: ReplayMarketFrameTimeline) -> None:
        timeline = ReplayMarketFrameTimeline.model_validate(market_timeline.model_dump())
        authority = build_replay_market_frame_lookup_authority(timeline)
        descriptor = build_replay_market_frame_lookup_descriptor(authority)
        projections: dict[_EventKey, _LookupProjection] = {}
        for entry, observation, frame in zip(
            authority.entries,
            timeline.observation_projections,
            timeline.frame_projections,
            strict=True,
        ):
            result = build_replay_market_frame_lookup_result(
                descriptor=descriptor,
                entry=entry,
                observation_projection=observation,
                frame_projection=frame,
            )
            validate_replay_market_frame_lookup_membership(
                authority=authority,
                result=result,
            )
            key = _event_key(observation.event_id, observation.event_order_index)
            existing = projections.get(key)
            projection = (
                result.entry,
                result.observation_projection,
                result.frame_projection,
            )
            if existing is not None:
                if existing != projection:
                    raise ValueError("ambiguous replay market projection key")
                raise ValueError("duplicate replay market projection key")
            projections[key] = projection
        self._authority = ReplayMarketFrameLookupAuthority.model_validate(
            authority.model_dump()
        )
        self._descriptor = ReplayMarketFrameLookupDescriptor.model_validate(
            descriptor.model_dump()
        )
        self._projections = dict(projections)

    @property
    def authority(self) -> ReplayMarketFrameLookupAuthority:
        return ReplayMarketFrameLookupAuthority.model_validate(
            self._authority.model_dump()
        )

    @property
    def descriptor(self) -> ReplayMarketFrameLookupDescriptor:
        return ReplayMarketFrameLookupDescriptor.model_validate(
            self._descriptor.model_dump()
        )

    def lookup(
        self,
        context: ReplayDispatchContext,
        event: ReplayTimelineEvent,
    ) -> ReplayMarketFrameLookupResult:
        context = ReplayDispatchContext.model_validate(context.model_dump())
        event = ReplayTimelineEvent.model_validate(event.model_dump())
        descriptor = self.descriptor
        _validate_context_matches_event(context, event)
        if context.timeline_id != descriptor.replay_timeline_id:
            raise ValueError("dispatch context timeline_id does not match market lookup")
        if context.replay_plan_id != descriptor.replay_plan_id:
            raise ValueError("dispatch context replay_plan_id does not match market lookup")
        if event.kind not in descriptor.supported_event_kinds:
            raise ValueError("event kind is not supported by market lookup")
        projection = self._projections.get(_event_key(event.event_id, event.order_index))
        if projection is None:
            raise ValueError("no replay market frame projection for event")
        entry, observation_projection, frame_projection = projection
        if observation_projection.event_id != event.event_id:
            raise ValueError("market projection event_id does not match event")
        if observation_projection.event_order_index != event.order_index:
            raise ValueError("market projection order_index does not match event")
        if observation_projection.event_time != event.event_time:
            raise ValueError("market projection event_time does not match event")
        if observation_projection.event_kind != event.kind:
            raise ValueError("market projection event_kind does not match event")
        return build_replay_market_frame_lookup_result(
            descriptor=descriptor,
            entry=entry,
            observation_projection=observation_projection,
            frame_projection=frame_projection,
        )


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
