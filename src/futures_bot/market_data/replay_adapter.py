from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal

from futures_bot.domain.market_data import (
    AggressorSide,
    IndexPriceObservationPayload,
    MarketObservationProvenance,
    MarkPriceObservationPayload,
    TopOfBookObservationPayload,
    TradeObservationPayload,
    build_normalized_market_observation,
)
from futures_bot.domain.replay import (
    ReplayInputBatch,
    ReplayInputKind,
    ReplayInputRecord,
    ReplayInputValidationStatus,
    ReplayTimeline,
    ReplayTimelineEvent,
    ReplayTimelineStatus,
)
from futures_bot.domain.replay_market_data import (
    ReplayMarketAdapterDescriptor,
    ReplayMarketBindingAuthority,
    ReplayMarketDataBinding,
    ReplayMarketFrameProjection,
    ReplayMarketFrameTimeline,
    ReplayMarketObservationProjection,
    ReplayMarketPayloadHashPolicy,
    build_replay_market_adapter_authority,
    build_replay_market_binding_authority,
    build_replay_market_connection_id,
    build_replay_market_frame_projection,
    build_replay_market_frame_timeline_model,
    build_replay_market_observation_projection,
    replay_market_binding_key,
    validate_replay_market_observation_kind,
    validate_replay_market_observation_provenance,
    validate_replay_market_projection_binding,
    validate_sha256_prefixed,
)
from futures_bot.market_data.frame_builder import build_cross_venue_market_frame


def resolve_replay_input_record(
    *,
    event: ReplayTimelineEvent,
    input_batches: tuple[ReplayInputBatch, ...],
) -> ReplayInputRecord:
    revalidated_event = _revalidate_model(ReplayTimelineEvent, event)
    revalidated_batches = tuple(
        _revalidate_model(ReplayInputBatch, batch) for batch in input_batches
    )
    batches_by_id: dict[str, ReplayInputBatch] = {}
    for batch in revalidated_batches:
        if batch.batch_id in batches_by_id:
            raise ValueError("duplicate replay input batch ID")
        batches_by_id[batch.batch_id] = batch
    batch = batches_by_id.get(revalidated_event.batch_id)
    if batch is None:
        raise ValueError("event batch_id does not identify an input batch")
    if batch.input_dataset_id != revalidated_event.input_dataset_id:
        raise ValueError("batch input_dataset_id must match event input_dataset_id")
    if batch.validation_status is not ReplayInputValidationStatus.VALIDATED:
        raise ValueError("input batch must be VALIDATED")
    matches = tuple(
        record for record in batch.records if record.record_id == revalidated_event.record_id
    )
    if not matches:
        raise ValueError("event record_id does not identify an input record")
    if len(matches) != 1:
        raise ValueError("event record_id identifies multiple input records")
    record = matches[0]
    validate_replay_event_record_consistency(event=revalidated_event, record=record)
    return record


def validate_replay_event_record_consistency(
    *,
    event: ReplayTimelineEvent,
    record: ReplayInputRecord,
) -> None:
    revalidated_event = _revalidate_model(ReplayTimelineEvent, event)
    revalidated_record = _revalidate_model(ReplayInputRecord, record)
    expected = {
        "record_id": revalidated_record.record_id,
        "kind": revalidated_record.kind,
        "instrument": revalidated_record.instrument,
        "event_time": revalidated_record.event_time,
        "source_sequence": revalidated_record.source_sequence,
        "content_hash": revalidated_record.content_hash,
    }
    for field_name, record_value in expected.items():
        event_value = getattr(revalidated_event, field_name)
        if event_value != record_value:
            raise ValueError(f"replay event {field_name} must match input record")


def project_replay_record_to_market_observation(
    *,
    timeline_id: str,
    event: ReplayTimelineEvent,
    record: ReplayInputRecord,
    binding_authority: ReplayMarketBindingAuthority,
) -> ReplayMarketObservationProjection:
    revalidated_event = _revalidate_model(ReplayTimelineEvent, event)
    revalidated_record = _revalidate_model(ReplayInputRecord, record)
    revalidated_authority = _revalidate_model(
        ReplayMarketBindingAuthority,
        binding_authority,
    )
    revalidated_binding = revalidated_authority.binding
    revalidated_descriptor = revalidated_authority.descriptor
    validate_replay_event_record_consistency(
        event=revalidated_event,
        record=revalidated_record,
    )
    if revalidated_event.input_dataset_id != revalidated_binding.input_dataset_id:
        raise ValueError("event input_dataset_id must match replay market binding")
    if revalidated_record.instrument != revalidated_binding.replay_instrument:
        raise ValueError("record instrument must match replay market binding")
    if revalidated_event.kind not in revalidated_descriptor.supported_input_kinds:
        raise ValueError("event kind is not supported by replay market adapter")

    payload = _market_payload_for_record(
        revalidated_event,
        revalidated_record,
        revalidated_binding,
    )
    provenance = MarketObservationProvenance(
        source_event_id=revalidated_event.event_id,
        source_event_time=revalidated_record.event_time,
        engine_time=None,
        received_at=revalidated_record.event_time,
        received_monotonic_ns=0,
        source_sequence=revalidated_record.source_sequence,
        connection_id=build_replay_market_connection_id(
            input_dataset_id=revalidated_event.input_dataset_id,
            binding_authority=revalidated_authority,
        ),
        reconnect_generation=0,
        raw_payload_sha256=_raw_payload_sha256(
            event=revalidated_event,
            record=revalidated_record,
            policy=revalidated_descriptor.payload_hash_policy,
        ),
    )
    observation = build_normalized_market_observation(
        source=revalidated_binding.source,
        instrument=revalidated_binding.venue_instrument,
        provenance=provenance,
        payload=payload,
    )
    validate_replay_market_observation_kind(
        event_kind=revalidated_event.kind,
        observation=observation,
    )
    validate_replay_market_projection_binding(
        input_dataset_id=revalidated_event.input_dataset_id,
        binding_authority=revalidated_authority,
        observation=observation,
    )
    validate_replay_market_observation_provenance(
        timeline_id=timeline_id,
        event_id=revalidated_event.event_id,
        event_time=revalidated_event.event_time,
        input_dataset_id=revalidated_event.input_dataset_id,
        binding_authority=revalidated_authority,
        observation=observation,
    )
    return build_replay_market_observation_projection(
        timeline_id=timeline_id,
        event_id=revalidated_event.event_id,
        event_order_index=revalidated_event.order_index,
        event_time=revalidated_event.event_time,
        batch_id=revalidated_event.batch_id,
        input_dataset_id=revalidated_event.input_dataset_id,
        record_id=revalidated_event.record_id,
        event_kind=revalidated_event.kind,
        binding_authority=revalidated_authority,
        observation=observation,
    )


def build_replay_market_frame_timeline(
    *,
    replay_timeline: ReplayTimeline,
    input_batches: tuple[ReplayInputBatch, ...],
    descriptor: ReplayMarketAdapterDescriptor,
    bindings: tuple[ReplayMarketDataBinding, ...],
) -> ReplayMarketFrameTimeline:
    revalidated_timeline = _revalidate_model(ReplayTimeline, replay_timeline)
    if revalidated_timeline.status not in {
        ReplayTimelineStatus.BUILT,
        ReplayTimelineStatus.VALIDATED,
    }:
        raise ValueError("replay timeline must be BUILT or VALIDATED")
    revalidated_descriptor = _revalidate_model(ReplayMarketAdapterDescriptor, descriptor)
    revalidated_batches = tuple(
        _revalidate_model(ReplayInputBatch, batch) for batch in input_batches
    )
    adapter_authority = build_replay_market_adapter_authority(
        descriptor=revalidated_descriptor,
        bindings=tuple(
            _revalidate_model(ReplayMarketDataBinding, binding) for binding in bindings
        ),
    )
    revalidated_bindings = adapter_authority.bindings
    binding_by_key = {
        replay_market_binding_key(binding): binding for binding in revalidated_bindings
    }
    accumulated: dict[str, tuple[ReplayMarketObservationProjection, ...]] = {}
    observation_projections: list[ReplayMarketObservationProjection] = []
    frame_projections: list[ReplayMarketFrameProjection] = []
    for event in revalidated_timeline.events:
        if event.kind not in revalidated_descriptor.supported_input_kinds:
            continue
        record = resolve_replay_input_record(
            event=event,
            input_batches=revalidated_batches,
        )
        key = (
            event.input_dataset_id,
            _canonical_json(record.instrument.model_dump(mode="json")),
        )
        binding = binding_by_key.get(key)
        if binding is None:
            raise ValueError("no replay market binding matches supported event")
        binding_authority = build_replay_market_binding_authority(
            descriptor=adapter_authority.descriptor,
            binding=binding,
        )
        projection = project_replay_record_to_market_observation(
            timeline_id=revalidated_timeline.timeline_id,
            event=event,
            record=record,
            binding_authority=binding_authority,
        )
        observation_projections.append(projection)
        logical = str(projection.observation.instrument.logical_instrument)
        accumulated[logical] = (*accumulated.get(logical, ()), projection)
        frame = build_cross_venue_market_frame(
            logical_instrument=projection.observation.instrument.logical_instrument,
            as_of=event.event_time,
            observations=tuple(
                item.observation for item in accumulated[logical]
                if item.event_order_index <= event.order_index
            ),
            source_health=(),
        )
        frame_projections.append(
            build_replay_market_frame_projection(
                timeline_id=revalidated_timeline.timeline_id,
                event_id=event.event_id,
                event_order_index=event.order_index,
                event_time=event.event_time,
                triggering_observation_projection_id=projection.projection_id,
                triggering_observation_id=projection.observation.observation_id,
                frame=frame,
            )
        )
    return build_replay_market_frame_timeline_model(
        replay_timeline_id=revalidated_timeline.timeline_id,
        replay_plan_id=revalidated_timeline.replay_plan_id,
        adapter_authority=adapter_authority,
        observation_projections=tuple(observation_projections),
        frame_projections=tuple(frame_projections),
    )


def _market_payload_for_record(
    event: ReplayTimelineEvent,
    record: ReplayInputRecord,
    binding: ReplayMarketDataBinding,
) -> (
    TradeObservationPayload
    | TopOfBookObservationPayload
    | MarkPriceObservationPayload
    | IndexPriceObservationPayload
):
    payload = record.payload
    if record.kind is ReplayInputKind.TRADE:
        return TradeObservationPayload(
            trade_id=_optional_text(payload, "trade_id") or event.event_id,
            price=_decimal_field(payload, "price"),
            quantity=_decimal_field(payload, "quantity"),
            aggressor_side=_aggressor_side(payload.get("side")),
        )
    if record.kind is ReplayInputKind.ORDER_BOOK_TOP:
        return TopOfBookObservationPayload(
            bid_price=_decimal_field(payload, "bid_price"),
            bid_quantity=_decimal_field(payload, "bid_size"),
            ask_price=_decimal_field(payload, "ask_price"),
            ask_quantity=_decimal_field(payload, "ask_size"),
            quote_semantics=binding.quote_semantics,
        )
    if record.kind is ReplayInputKind.MARK_PRICE:
        return MarkPriceObservationPayload(price=_decimal_field(payload, "price"))
    if record.kind is ReplayInputKind.INDEX_PRICE:
        return IndexPriceObservationPayload(price=_decimal_field(payload, "price"))
    raise ValueError("unsupported replay input kind for market observation projection")


def _raw_payload_sha256(
    *,
    event: ReplayTimelineEvent,
    record: ReplayInputRecord,
    policy: ReplayMarketPayloadHashPolicy,
) -> str:
    if policy is ReplayMarketPayloadHashPolicy.REQUIRE_SUPPLIED_SHA256:
        if record.content_hash is None:
            raise ValueError("content_hash is required by payload hash policy")
        return validate_sha256_prefixed(record.content_hash)
    material = {
        "batch_id": event.batch_id,
        "input_dataset_id": event.input_dataset_id,
        "record": record.model_dump(mode="json"),
    }
    _reject_float_values(material)
    return f"sha256:{hashlib.sha256(_canonical_json(material).encode('utf-8')).hexdigest()}"


def _decimal_field(payload: Mapping[str, object], key: str) -> Decimal:
    value = payload.get(key)
    if not isinstance(value, Decimal):
        raise ValueError(f"payload field {key!r} must be Decimal")
    return value


def _optional_text(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"payload field {key!r} must be a non-empty trimmed string")
    return value


def _aggressor_side(value: object) -> AggressorSide:
    if value is None:
        return AggressorSide.UNKNOWN
    if value == "buy":
        return AggressorSide.BUY
    if value == "sell":
        return AggressorSide.SELL
    raise ValueError("trade side must be 'buy' or 'sell' when present")


def _reject_float_values(value: object) -> None:
    if isinstance(value, float):
        raise ValueError("canonical replay record hash material must not contain floats")
    if isinstance(value, Mapping):
        for item in value.values():
            _reject_float_values(item)
    elif isinstance(value, tuple | list):
        for item in value:
            _reject_float_values(item)


def _revalidate_model[T](model_type: type[T], value: object) -> T:
    if isinstance(value, model_type):
        return model_type.model_validate(value.model_dump())  # type: ignore[attr-defined]
    return model_type.model_validate(value)  # type: ignore[attr-defined]


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
