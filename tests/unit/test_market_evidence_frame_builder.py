from __future__ import annotations

from decimal import Decimal
from typing import cast

import pytest
from pydantic import ValidationError
from tests.unit.market_evidence_fixtures import build_market_evidence_fixture_frame

from futures_bot.domain.evidence import (
    DecimalMarketEvidenceValue,
    MarketEvidenceItem,
    MarketEvidenceKind,
    MarketEvidenceSet,
    ObservationMarketEvidenceOrigin,
    TextMarketEvidenceValue,
    build_market_evidence_item_id,
    build_market_evidence_set_id,
)
from futures_bot.domain.market_data import (
    IndexPriceObservationPayload,
    MarkPriceObservationPayload,
    TopOfBookObservationPayload,
    TradeObservationPayload,
)
from futures_bot.evidence.frame_builder import (
    DeterministicCrossVenueMarketEvidenceBuilder,
)


def test_builder_extracts_exact_observation_evidence() -> None:
    frame = build_market_evidence_fixture_frame()
    evidence_set = DeterministicCrossVenueMarketEvidenceBuilder().build(frame)
    by_kind = _items_by_kind(evidence_set.items)
    trade = next(
        observation
        for observation in frame.observations
        if isinstance(observation.payload, TradeObservationPayload)
    )
    top = next(
        observation
        for observation in frame.observations
        if isinstance(observation.payload, TopOfBookObservationPayload)
    )
    mark = next(
        observation
        for observation in frame.observations
        if isinstance(observation.payload, MarkPriceObservationPayload)
    )
    index = next(
        observation
        for observation in frame.observations
        if isinstance(observation.payload, IndexPriceObservationPayload)
    )
    trade_payload = cast(TradeObservationPayload, trade.payload)
    top_payload = cast(TopOfBookObservationPayload, top.payload)
    mark_payload = cast(MarkPriceObservationPayload, mark.payload)
    index_payload = cast(IndexPriceObservationPayload, index.payload)

    assert _decimal_value(by_kind[MarketEvidenceKind.TRADE_PRICE][0]) == (
        trade_payload.price
    )
    assert _decimal_value(by_kind[MarketEvidenceKind.TRADE_QUANTITY][0]) == (
        trade_payload.quantity
    )
    assert _text_value(by_kind[MarketEvidenceKind.TRADE_AGGRESSOR_SIDE][0]) == (
        trade_payload.aggressor_side.value
    )
    assert _decimal_value(
        _item_for_origin(
            by_kind[MarketEvidenceKind.TOP_OF_BOOK_BID_PRICE],
            str(top.observation_id),
        )
    ) == top_payload.bid_price
    assert _decimal_value(
        _item_for_origin(
            by_kind[MarketEvidenceKind.TOP_OF_BOOK_BID_QUANTITY],
            str(top.observation_id),
        )
    ) == top_payload.bid_quantity
    assert _decimal_value(
        _item_for_origin(
            by_kind[MarketEvidenceKind.TOP_OF_BOOK_ASK_PRICE],
            str(top.observation_id),
        )
    ) == top_payload.ask_price
    assert _decimal_value(
        _item_for_origin(
            by_kind[MarketEvidenceKind.TOP_OF_BOOK_ASK_QUANTITY],
            str(top.observation_id),
        )
    ) == top_payload.ask_quantity
    assert _text_value(
        _item_for_origin(
            by_kind[MarketEvidenceKind.TOP_OF_BOOK_QUOTE_SEMANTICS],
            str(top.observation_id),
        )
    ) == top_payload.quote_semantics.value
    assert _decimal_value(by_kind[MarketEvidenceKind.MARK_PRICE][0]) == (
        mark_payload.price
    )
    assert _decimal_value(by_kind[MarketEvidenceKind.INDEX_PRICE][0]) == (
        index_payload.price
    )


def test_builder_extracts_exact_health_evidence_and_optional_sequence() -> None:
    frame = build_market_evidence_fixture_frame()
    evidence_set = DeterministicCrossVenueMarketEvidenceBuilder().build(frame)
    health_items = [
        item
        for item in evidence_set.items
        if item.origin.origin_kind.value == "SOURCE_HEALTH"
    ]
    sequence_items = [
        item
        for item in health_items
        if item.evidence_kind is MarketEvidenceKind.SOURCE_HEALTH_LAST_SEQUENCE
    ]

    assert len(sequence_items) == sum(
        1 for snapshot in frame.source_health if snapshot.last_sequence is not None
    )
    assert len(health_items) == 14

    no_health = build_market_evidence_fixture_frame(include_source_health=False)
    no_health_set = DeterministicCrossVenueMarketEvidenceBuilder().build(no_health)
    assert all(
        item.origin.origin_kind.value != "SOURCE_HEALTH" for item in no_health_set.items
    )


def test_market_evidence_has_no_decision_or_direction_fields() -> None:
    evidence_set = DeterministicCrossVenueMarketEvidenceBuilder().build(
        build_market_evidence_fixture_frame()
    )
    forbidden = {
        "direction",
        "confidence",
        "recommended_side",
        "target",
        "candidate",
        "decision",
        "action",
        "leverage",
        "margin",
        "risk",
        "order",
    }

    for item in evidence_set.items:
        dumped = item.model_dump(mode="json")
        assert forbidden.isdisjoint(dumped)
        assert forbidden.isdisjoint(dumped["value"])
    assert forbidden.isdisjoint(evidence_set.model_dump(mode="json"))


def test_builder_is_deterministic_and_embeds_source_frame_snapshot() -> None:
    builder = DeterministicCrossVenueMarketEvidenceBuilder()
    frame = build_market_evidence_fixture_frame()
    first = builder.build(frame)
    second = builder.build(frame)
    equivalent = builder.build(build_market_evidence_fixture_frame())

    assert first == second == equivalent
    assert first.source_frame == frame

    object.__setattr__(frame, "source_health", ())
    assert first.source_frame.source_health


def test_changed_frame_and_decimal_scale_change_evidence_identity() -> None:
    builder = DeterministicCrossVenueMarketEvidenceBuilder()
    base = builder.build(build_market_evidence_fixture_frame(trade_price="100.00"))
    changed_price = builder.build(build_market_evidence_fixture_frame(trade_price="101.00"))
    changed_scale = builder.build(build_market_evidence_fixture_frame(trade_price="100.0"))

    assert base.evidence_set_id != changed_price.evidence_set_id
    assert base.evidence_set_id != changed_scale.evidence_set_id
    assert _first_trade_price_item(base).evidence_item_id != (
        _first_trade_price_item(changed_scale).evidence_item_id
    )


def test_set_rejects_items_not_derived_from_embedded_frame() -> None:
    builder = DeterministicCrossVenueMarketEvidenceBuilder()
    valid = builder.build(build_market_evidence_fixture_frame())
    changed_value = _replace_value(_first_trade_price_item(valid), "101.00")
    changed_items = _replace_item(valid.items, _first_trade_price_item(valid), changed_value)

    with pytest.raises(ValidationError, match="derivation"):
        MarketEvidenceSet.model_validate(
            {
                **valid.model_dump(mode="json"),
                "items": [item.model_dump(mode="json") for item in changed_items],
            }
        )
    with pytest.raises(ValueError, match="derivation"):
        build_market_evidence_set_id(
            builder=valid.builder,
            source_frame=valid.source_frame,
            items=changed_items,
        )


def test_set_rejects_extra_omitted_reordered_and_changed_origins() -> None:
    valid = DeterministicCrossVenueMarketEvidenceBuilder().build(
        build_market_evidence_fixture_frame()
    )
    payload = valid.model_dump(mode="json")

    with pytest.raises(ValidationError):
        MarketEvidenceSet.model_validate({**payload, "items": payload["items"][:-1]})
    with pytest.raises(ValidationError):
        MarketEvidenceSet.model_validate(
            {**payload, "items": [*payload["items"], payload["items"][0]]}
        )
    with pytest.raises(ValidationError, match="sorted"):
        MarketEvidenceSet.model_validate(
            {**payload, "items": [payload["items"][1], payload["items"][0], *payload["items"][2:]]}
        )

    first = _first_trade_price_item(valid)
    first_index = valid.items.index(first)
    changed_origin = _replace_observation_origin(first, valid)
    with pytest.raises(ValidationError):
        MarketEvidenceSet.model_validate(
            {
                **payload,
                "items": [
                    item.model_dump(mode="json")
                    for item in _replace_item(valid.items, first, changed_origin)
                ],
            }
        )
    with pytest.raises(ValidationError):
        MarketEvidenceSet.model_validate(
            {
                **payload,
                "items": [
                    *payload["items"][:first_index],
                    {
                        **first.model_dump(mode="json"),
                        "evidence_kind": MarketEvidenceKind.MARK_PRICE.value,
                    },
                    *payload["items"][first_index + 1:],
                ],
            }
        )


def test_set_rejects_changed_builder_or_source_frame_with_stale_items() -> None:
    valid = DeterministicCrossVenueMarketEvidenceBuilder().build(
        build_market_evidence_fixture_frame()
    )
    changed_frame = build_market_evidence_fixture_frame(trade_price="101.00")
    payload = valid.model_dump(mode="json")

    with pytest.raises(ValidationError, match="builder_fingerprint"):
        MarketEvidenceSet.model_validate(
            {
                **payload,
                "builder": {
                    **payload["builder"],
                    "builder_fingerprint": "market-evidence-builder:" + "0" * 64,
                },
            }
        )
    with pytest.raises(ValueError, match="derivation"):
        build_market_evidence_set_id(
            builder=valid.builder,
            source_frame=changed_frame,
            items=valid.items,
        )


def _items_by_kind(
    items: tuple[MarketEvidenceItem, ...],
) -> dict[MarketEvidenceKind, list[MarketEvidenceItem]]:
    by_kind: dict[MarketEvidenceKind, list[MarketEvidenceItem]] = {}
    for item in items:
        by_kind.setdefault(item.evidence_kind, []).append(item)
    return by_kind


def _decimal_value(item: MarketEvidenceItem) -> Decimal:
    assert isinstance(item.value, DecimalMarketEvidenceValue)
    return item.value.value


def _text_value(item: MarketEvidenceItem) -> str:
    assert isinstance(item.value, TextMarketEvidenceValue)
    return item.value.value


def _first_trade_price_item(evidence_set: MarketEvidenceSet) -> MarketEvidenceItem:
    return next(
        item
        for item in evidence_set.items
        if item.evidence_kind is MarketEvidenceKind.TRADE_PRICE
    )


def _replace_value(item: MarketEvidenceItem, value: str) -> MarketEvidenceItem:
    replacement = DecimalMarketEvidenceValue.model_validate({"value": value})
    replacement_id = build_market_evidence_item_id(
        evidence_kind=item.evidence_kind,
        origin=item.origin,
        unit=item.unit,
        value=replacement,
    )
    return MarketEvidenceItem(
        evidence_item_id=replacement_id,
        evidence_kind=item.evidence_kind,
        origin=item.origin,
        unit=item.unit,
        value=replacement,
    )


def _replace_observation_origin(
    item: MarketEvidenceItem,
    evidence_set: MarketEvidenceSet,
) -> MarketEvidenceItem:
    replacement_origin = ObservationMarketEvidenceOrigin(
        observation_id=next(
            observation.observation_id
            for observation in evidence_set.source_frame.observations
            if not isinstance(observation.payload, TradeObservationPayload)
        ),
    )
    replacement_id = build_market_evidence_item_id(
        evidence_kind=item.evidence_kind,
        origin=replacement_origin,
        unit=item.unit,
        value=item.value,
    )
    return MarketEvidenceItem(
        evidence_item_id=replacement_id,
        evidence_kind=item.evidence_kind,
        origin=replacement_origin,
        unit=item.unit,
        value=item.value,
    )


def _item_for_origin(
    items: list[MarketEvidenceItem],
    origin_id: str,
) -> MarketEvidenceItem:
    return next(
        item
        for item in items
        if isinstance(item.origin, ObservationMarketEvidenceOrigin)
        and str(item.origin.observation_id) == origin_id
    )


def _replace_item(
    items: tuple[MarketEvidenceItem, ...],
    old: MarketEvidenceItem,
    new: MarketEvidenceItem,
) -> tuple[MarketEvidenceItem, ...]:
    index = items.index(old)
    return (*items[:index], new, *items[index + 1:])
