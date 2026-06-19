from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError
from tests.unit.market_evidence_fixtures import build_market_evidence_fixture_frame

from futures_bot.domain.evidence import (
    DecimalMarketEvidenceValue,
    IntegerMarketEvidenceValue,
    MarketEvidenceBuilderDescriptor,
    MarketEvidenceKind,
    MarketEvidenceOriginKind,
    MarketEvidenceSet,
    MarketEvidenceUnit,
    ObservationMarketEvidenceOrigin,
    SourceHealthMarketEvidenceOrigin,
    TextMarketEvidenceValue,
    TextTupleMarketEvidenceValue,
    build_market_evidence_builder_descriptor,
    build_market_evidence_builder_fingerprint,
    build_market_evidence_item_id,
    build_market_evidence_set_id,
    derive_market_evidence_items,
    market_evidence_item_key,
)
from futures_bot.domain.ids import DomainId, MarketEvidenceItemId, MarketEvidenceSetId


def test_market_evidence_value_variants_validate_strict_inputs() -> None:
    assert DecimalMarketEvidenceValue.model_validate({"value": "100.00"}).value == (
        Decimal("100.00")
    )
    assert DecimalMarketEvidenceValue.model_validate({"value": 1}).value == Decimal("1")
    assert IntegerMarketEvidenceValue(value=3).value == 3
    assert TextMarketEvidenceValue(value="BUY").value == "BUY"
    assert TextTupleMarketEvidenceValue(value=()).value == ()
    assert TextTupleMarketEvidenceValue(value=("A", "B")).value == ("A", "B")

    for bad in (1.2, True, "NaN", "Infinity", "-Infinity"):
        with pytest.raises(ValidationError):
            DecimalMarketEvidenceValue.model_validate({"value": bad})
    for bad in (True, -1, 1.2):
        with pytest.raises(ValidationError):
            IntegerMarketEvidenceValue.model_validate({"value": bad})
    with pytest.raises(ValidationError, match="trimmed"):
        TextMarketEvidenceValue(value=" BUY ")
    with pytest.raises(ValidationError, match="unique"):
        TextTupleMarketEvidenceValue(value=("A", "A"))
    with pytest.raises(ValidationError, match="sorted"):
        TextTupleMarketEvidenceValue(value=("B", "A"))


def test_market_evidence_origins_enforce_exact_id_prefixes() -> None:
    frame = build_market_evidence_fixture_frame()
    observation = frame.observations[0]
    snapshot = frame.source_health[0]

    assert ObservationMarketEvidenceOrigin(
        observation_id=observation.observation_id,
    ).origin_kind is MarketEvidenceOriginKind.OBSERVATION
    assert SourceHealthMarketEvidenceOrigin(
        health_snapshot_id=snapshot.health_snapshot_id,
    ).origin_kind is MarketEvidenceOriginKind.SOURCE_HEALTH

    with pytest.raises(ValidationError, match="market-observation"):
        ObservationMarketEvidenceOrigin.model_validate(
            {"observation_id": DomainId("market-health:" + "a" * 64)}
        )
    with pytest.raises(ValidationError, match="market-health"):
        SourceHealthMarketEvidenceOrigin.model_validate(
            {"health_snapshot_id": DomainId("market-observation:" + "a" * 64)}
        )


@pytest.mark.parametrize(
    ("kind", "origin_kind", "value_kind", "unit"),
    (
        (MarketEvidenceKind.TRADE_PRICE, "observation", "decimal", MarketEvidenceUnit.PRICE),
        (MarketEvidenceKind.TRADE_QUANTITY, "observation", "decimal", MarketEvidenceUnit.QUANTITY),
        (MarketEvidenceKind.TRADE_AGGRESSOR_SIDE, "observation", "text", MarketEvidenceUnit.ENUM),
        (
            MarketEvidenceKind.TOP_OF_BOOK_BID_PRICE,
            "observation",
            "decimal",
            MarketEvidenceUnit.PRICE,
        ),
        (
            MarketEvidenceKind.TOP_OF_BOOK_BID_QUANTITY,
            "observation",
            "decimal",
            MarketEvidenceUnit.QUANTITY,
        ),
        (
            MarketEvidenceKind.TOP_OF_BOOK_ASK_PRICE,
            "observation",
            "decimal",
            MarketEvidenceUnit.PRICE,
        ),
        (
            MarketEvidenceKind.TOP_OF_BOOK_ASK_QUANTITY,
            "observation",
            "decimal",
            MarketEvidenceUnit.QUANTITY,
        ),
        (
            MarketEvidenceKind.TOP_OF_BOOK_QUOTE_SEMANTICS,
            "observation",
            "text",
            MarketEvidenceUnit.ENUM,
        ),
        (MarketEvidenceKind.MARK_PRICE, "observation", "decimal", MarketEvidenceUnit.PRICE),
        (MarketEvidenceKind.INDEX_PRICE, "observation", "decimal", MarketEvidenceUnit.PRICE),
        (MarketEvidenceKind.SOURCE_HEALTH_STATE, "health", "text", MarketEvidenceUnit.ENUM),
        (
            MarketEvidenceKind.SOURCE_HEALTH_ISSUES,
            "health",
            "text_tuple",
            MarketEvidenceUnit.ENUM_SET,
        ),
        (
            MarketEvidenceKind.SOURCE_HEALTH_RECONNECT_GENERATION,
            "health",
            "integer",
            MarketEvidenceUnit.COUNT,
        ),
        (
            MarketEvidenceKind.SOURCE_HEALTH_CONSECUTIVE_FAILURES,
            "health",
            "integer",
            MarketEvidenceUnit.COUNT,
        ),
        (
            MarketEvidenceKind.SOURCE_HEALTH_LAST_SEQUENCE,
            "health",
            "integer",
            MarketEvidenceUnit.SEQUENCE,
        ),
    ),
)
def test_market_evidence_kind_matrix_accepts_exact_combinations(
    kind: MarketEvidenceKind,
    origin_kind: str,
    value_kind: str,
    unit: MarketEvidenceUnit,
) -> None:
    frame = build_market_evidence_fixture_frame()
    origin = (
        ObservationMarketEvidenceOrigin(observation_id=frame.observations[0].observation_id)
        if origin_kind == "observation"
        else SourceHealthMarketEvidenceOrigin(
            health_snapshot_id=frame.source_health[0].health_snapshot_id,
        )
    )
    value = _value(value_kind)
    item_id = build_market_evidence_item_id(
        evidence_kind=kind,
        origin=origin,
        unit=unit,
        value=value,
    )

    assert str(item_id).startswith("market-evidence-item:")


def test_market_evidence_kind_matrix_rejects_invalid_combinations_and_non_positive() -> None:
    frame = build_market_evidence_fixture_frame()
    observation_origin = ObservationMarketEvidenceOrigin(
        observation_id=frame.observations[0].observation_id,
    )
    health_origin = SourceHealthMarketEvidenceOrigin(
        health_snapshot_id=frame.source_health[0].health_snapshot_id,
    )

    with pytest.raises(ValueError, match="origin"):
        build_market_evidence_item_id(
            evidence_kind=MarketEvidenceKind.TRADE_PRICE,
            origin=health_origin,
            unit=MarketEvidenceUnit.PRICE,
            value=DecimalMarketEvidenceValue.model_validate({"value": "1"}),
        )
    with pytest.raises(ValueError, match="value kind"):
        build_market_evidence_item_id(
            evidence_kind=MarketEvidenceKind.TRADE_PRICE,
            origin=observation_origin,
            unit=MarketEvidenceUnit.PRICE,
            value=TextMarketEvidenceValue(value="BUY"),
        )
    with pytest.raises(ValueError, match="unit"):
        build_market_evidence_item_id(
            evidence_kind=MarketEvidenceKind.TRADE_PRICE,
            origin=observation_origin,
            unit=MarketEvidenceUnit.QUANTITY,
            value=DecimalMarketEvidenceValue.model_validate({"value": "1"}),
        )
    with pytest.raises(ValueError, match="positive"):
        build_market_evidence_item_id(
            evidence_kind=MarketEvidenceKind.TRADE_PRICE,
            origin=observation_origin,
            unit=MarketEvidenceUnit.PRICE,
            value=DecimalMarketEvidenceValue.model_validate({"value": "0"}),
        )


def test_market_evidence_descriptor_fingerprint_and_tampering() -> None:
    descriptor = build_market_evidence_builder_descriptor()
    assert descriptor.builder_fingerprint == build_market_evidence_builder_fingerprint(
        builder_id=descriptor.builder_id,
        builder_version=descriptor.builder_version,
        supported_evidence_kinds=descriptor.supported_evidence_kinds,
    )
    assert descriptor.supported_evidence_kinds == tuple(
        sorted(MarketEvidenceKind, key=lambda kind: kind.value)
    )

    with pytest.raises(ValidationError, match="builder_fingerprint"):
        MarketEvidenceBuilderDescriptor.model_validate(
            {
                **descriptor.model_dump(mode="json"),
                "builder_fingerprint": "market-evidence-builder:" + "0" * 64,
            }
        )
    with pytest.raises(ValidationError, match="complete v1"):
        MarketEvidenceBuilderDescriptor.model_validate(
            {
                **descriptor.model_dump(mode="json"),
                "supported_evidence_kinds": list(reversed([
                    kind.value for kind in descriptor.supported_evidence_kinds
                ])),
            }
        )


def test_market_evidence_set_id_round_trip_and_tampering() -> None:
    frame = build_market_evidence_fixture_frame()
    builder = build_market_evidence_builder_descriptor()
    items = derive_market_evidence_items(source_frame=frame, builder=builder)
    set_id = build_market_evidence_set_id(
        builder=builder,
        source_frame=frame,
        items=items,
    )
    evidence_set = MarketEvidenceSet(
        evidence_set_id=set_id,
        builder=builder,
        source_frame=frame,
        items=items,
    )

    assert MarketEvidenceSet.model_validate(evidence_set.model_dump()) == evidence_set
    assert str(evidence_set.evidence_set_id).startswith("market-evidence-set:")

    with pytest.raises(ValidationError, match="market-evidence-set"):
        MarketEvidenceSet.model_validate(
            {
                **evidence_set.model_dump(mode="json"),
                "evidence_set_id": MarketEvidenceSetId.from_str("wrong-prefix"),
            }
        )
    tampered = evidence_set.model_copy(update={"items": items[:-1]})
    with pytest.raises(ValidationError):
        MarketEvidenceSet.model_validate(tampered.model_dump())


def test_market_evidence_set_rejects_order_duplicates_and_derivation_changes() -> None:
    frame = build_market_evidence_fixture_frame()
    builder = build_market_evidence_builder_descriptor()
    items = derive_market_evidence_items(source_frame=frame, builder=builder)
    valid_set_id = build_market_evidence_set_id(
        builder=builder,
        source_frame=frame,
        items=items,
    )
    payload = {
        "evidence_set_id": valid_set_id.model_dump(mode="json"),
        "builder": builder.model_dump(mode="json"),
        "source_frame": frame.model_dump(mode="json"),
        "items": [item.model_dump(mode="json") for item in items],
    }

    with pytest.raises(ValidationError, match="sorted"):
        MarketEvidenceSet.model_validate(
            {
                **payload,
                "items": [items[1].model_dump(mode="json"), items[0].model_dump(mode="json"), *[
                    item.model_dump(mode="json") for item in items[2:]
                ]],
            }
        )
    with pytest.raises(ValidationError, match="duplicate"):
        MarketEvidenceSet.model_validate(
                {
                    **payload,
                    "items": [
                        item.model_dump(mode="json") for item in (items[0], *items)
                    ],
                }
            )
    trade_item = next(
        item for item in items if item.evidence_kind is MarketEvidenceKind.TRADE_PRICE
    )
    trade_index = items.index(trade_item)
    changed = _changed_item_value(trade_item, "101.00")
    changed_in_place = (
        *items[:trade_index],
        changed,
        *items[trade_index + 1:],
    )
    with pytest.raises(ValueError, match="derivation"):
        build_market_evidence_set_id(
            builder=builder,
            source_frame=frame,
            items=changed_in_place,
        )
    changed_frame = build_market_evidence_fixture_frame(trade_price="101.00")
    with pytest.raises(ValueError, match="derivation"):
        build_market_evidence_set_id(builder=builder, source_frame=changed_frame, items=items)


def test_market_evidence_item_key_and_ids_are_canonical() -> None:
    frame = build_market_evidence_fixture_frame()
    builder = build_market_evidence_builder_descriptor()
    items = derive_market_evidence_items(source_frame=frame, builder=builder)

    assert tuple(sorted(items, key=market_evidence_item_key)) == items
    assert len({market_evidence_item_key(item) for item in items}) == len(items)
    assert len({str(item.evidence_item_id) for item in items}) == len(items)

    item = items[0]
    assert build_market_evidence_item_id(
        evidence_kind=item.evidence_kind,
        origin=item.origin,
        unit=item.unit,
        value=item.value,
    ) == item.evidence_item_id
    assert type(item) is not object
    with pytest.raises(ValidationError, match="market-evidence-item"):
        type(item).model_validate(
            {
                **item.model_dump(mode="json"),
                "evidence_item_id": MarketEvidenceItemId.from_str("wrong-prefix"),
            }
        )


def _value(kind: str):
    if kind == "decimal":
        return DecimalMarketEvidenceValue.model_validate({"value": "1.00"})
    if kind == "integer":
        return IntegerMarketEvidenceValue(value=1)
    if kind == "text":
        return TextMarketEvidenceValue(value="VALUE")
    return TextTupleMarketEvidenceValue(value=("A", "B"))


def _changed_item_value(item, value: str):
    changed_value = DecimalMarketEvidenceValue.model_validate({"value": value})
    changed_id = build_market_evidence_item_id(
        evidence_kind=item.evidence_kind,
        origin=item.origin,
        unit=item.unit,
        value=changed_value,
    )
    return type(item)(
        evidence_item_id=changed_id,
        evidence_kind=item.evidence_kind,
        origin=item.origin,
        unit=item.unit,
        value=changed_value,
    )
