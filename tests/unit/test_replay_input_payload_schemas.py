from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from futures_bot.domain.replay import (
    ReplayInputKind,
    ReplayInputRecord,
    ReplayInstrumentRef,
)


def _utc() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _instrument() -> ReplayInstrumentRef:
    return ReplayInstrumentRef(
        venue="binance",
        symbol="BTCUSDT",
        market_type="stablecoin-collateral-futures",
        settlement_asset="USDT",
    )


def _record(kind: ReplayInputKind, payload: dict[str, object]) -> ReplayInputRecord:
    return ReplayInputRecord(
        record_id=f"record-{kind.value.lower()}",
        kind=kind,
        instrument=_instrument(),
        event_time=_utc(),
        source_sequence=0,
        payload=payload,
    )


def _ohlcv_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "open": Decimal("100"),
        "high": Decimal("110"),
        "low": Decimal("90"),
        "close": Decimal("105"),
        "volume": Decimal("12.5"),
    }
    payload.update(updates)
    return payload


def test_ohlcv_accepts_valid_payload_and_optional_fields() -> None:
    record = _record(
        ReplayInputKind.OHLCV_BAR,
        _ohlcv_payload(
            quote_volume=Decimal("1300"),
            taker_buy_base_volume=Decimal("4"),
            taker_buy_quote_volume=Decimal("420"),
            trade_count=12,
            vendor_extra={"session": "regular"},
        ),
    )
    assert record.payload["trade_count"] == 12


@pytest.mark.parametrize("field", ("open", "high", "low", "close", "volume"))
def test_ohlcv_rejects_missing_required_fields(field: str) -> None:
    payload = _ohlcv_payload()
    payload.pop(field)
    with pytest.raises(ValidationError, match=field):
        _record(ReplayInputKind.OHLCV_BAR, payload)


@pytest.mark.parametrize("bad_value", (1, "1", 1.0))
def test_ohlcv_rejects_non_decimal_open(bad_value: object) -> None:
    with pytest.raises(ValidationError, match="open"):
        _record(ReplayInputKind.OHLCV_BAR, _ohlcv_payload(open=bad_value))


@pytest.mark.parametrize("bad_value", (Decimal("0"), Decimal("-1")))
def test_ohlcv_rejects_non_positive_open(bad_value: Decimal) -> None:
    with pytest.raises(ValidationError, match="open"):
        _record(ReplayInputKind.OHLCV_BAR, _ohlcv_payload(open=bad_value))


def test_ohlcv_rejects_negative_volume_and_invalid_relationships() -> None:
    with pytest.raises(ValidationError, match="volume"):
        _record(ReplayInputKind.OHLCV_BAR, _ohlcv_payload(volume=Decimal("-1")))
    with pytest.raises(ValidationError, match="high"):
        _record(
            ReplayInputKind.OHLCV_BAR,
            _ohlcv_payload(high=Decimal("80"), low=Decimal("90")),
        )
    with pytest.raises(ValidationError, match="high"):
        _record(ReplayInputKind.OHLCV_BAR, _ohlcv_payload(high=Decimal("95")))
    with pytest.raises(ValidationError, match="low"):
        _record(ReplayInputKind.OHLCV_BAR, _ohlcv_payload(low=Decimal("106")))


def test_ohlcv_rejects_bad_trade_count() -> None:
    with pytest.raises(ValidationError, match="trade_count"):
        _record(ReplayInputKind.OHLCV_BAR, _ohlcv_payload(trade_count=True))
    with pytest.raises(ValidationError, match="trade_count"):
        _record(ReplayInputKind.OHLCV_BAR, _ohlcv_payload(trade_count="1"))


def test_mark_price_schema() -> None:
    record = _record(
        ReplayInputKind.MARK_PRICE,
        {
            "price": Decimal("100"),
            "funding_rate": Decimal("-0.0001"),
            "index_price": Decimal("101"),
        },
    )
    assert record.payload["funding_rate"] == Decimal("-0.0001")
    with pytest.raises(ValidationError, match="price"):
        _record(ReplayInputKind.MARK_PRICE, {"price": Decimal("0")})
    with pytest.raises(ValidationError, match="index_price"):
        _record(
            ReplayInputKind.MARK_PRICE,
            {"price": Decimal("100"), "index_price": Decimal("0")},
        )


def test_index_price_schema() -> None:
    assert _record(ReplayInputKind.INDEX_PRICE, {"price": Decimal("100")})
    with pytest.raises(ValidationError, match="price"):
        _record(ReplayInputKind.INDEX_PRICE, {"price": Decimal("-1")})


def test_funding_rate_schema() -> None:
    for value in (Decimal("-0.01"), Decimal("0"), Decimal("0.01")):
        assert _record(ReplayInputKind.FUNDING_RATE, {"funding_rate": value})
    with pytest.raises(ValidationError, match="finite"):
        _record(ReplayInputKind.FUNDING_RATE, {"funding_rate": Decimal("NaN")})
    with pytest.raises(ValidationError, match="mark_price"):
        _record(
            ReplayInputKind.FUNDING_RATE,
            {"funding_rate": Decimal("0"), "mark_price": Decimal("0")},
        )


def test_open_interest_schema() -> None:
    for value in (Decimal("0"), Decimal("100")):
        assert _record(ReplayInputKind.OPEN_INTEREST, {"open_interest": value})
    with pytest.raises(ValidationError, match="open_interest"):
        _record(ReplayInputKind.OPEN_INTEREST, {"open_interest": Decimal("-1")})
    with pytest.raises(ValidationError, match="open_interest"):
        _record(ReplayInputKind.OPEN_INTEREST, {"open_interest": 1})


def test_order_book_top_schema() -> None:
    payload = {
        "bid_price": Decimal("99"),
        "ask_price": Decimal("100"),
        "bid_size": Decimal("1"),
        "ask_size": Decimal("2"),
        "bid_count": 1,
        "ask_count": 2,
    }
    assert _record(ReplayInputKind.ORDER_BOOK_TOP, payload)
    with pytest.raises(ValidationError, match="ask_price"):
        _record(ReplayInputKind.ORDER_BOOK_TOP, {**payload, "ask_price": Decimal("98")})
    with pytest.raises(ValidationError, match="bid_price"):
        _record(ReplayInputKind.ORDER_BOOK_TOP, {**payload, "bid_price": Decimal("0")})
    with pytest.raises(ValidationError, match="bid_size"):
        _record(ReplayInputKind.ORDER_BOOK_TOP, {**payload, "bid_size": Decimal("-1")})
    with pytest.raises(ValidationError, match="bid_count"):
        _record(ReplayInputKind.ORDER_BOOK_TOP, {**payload, "bid_count": True})
    with pytest.raises(ValidationError, match="ask_count"):
        _record(ReplayInputKind.ORDER_BOOK_TOP, {**payload, "ask_count": "1"})


def test_trade_schema() -> None:
    assert _record(
        ReplayInputKind.TRADE,
        {
            "price": Decimal("100"),
            "quantity": Decimal("0.1"),
            "side": "buy",
            "trade_id": "trade-1",
        },
    )
    with pytest.raises(ValidationError, match="price"):
        _record(ReplayInputKind.TRADE, {"price": Decimal("0"), "quantity": Decimal("1")})
    with pytest.raises(ValidationError, match="quantity"):
        _record(
            ReplayInputKind.TRADE,
            {"price": Decimal("1"), "quantity": Decimal("0")},
        )
    for side in ("long", "BUY", ""):
        with pytest.raises(ValidationError, match="side"):
            _record(
                ReplayInputKind.TRADE,
                {"price": Decimal("1"), "quantity": Decimal("1"), "side": side},
            )
    with pytest.raises(ValidationError, match="trade_id"):
        _record(
            ReplayInputKind.TRADE,
            {"price": Decimal("1"), "quantity": Decimal("1"), "trade_id": ""},
        )


def test_liquidation_schema() -> None:
    assert _record(
        ReplayInputKind.LIQUIDATION,
        {"price": Decimal("100"), "quantity": Decimal("1"), "side": "sell"},
    )
    with pytest.raises(ValidationError, match="side"):
        _record(ReplayInputKind.LIQUIDATION, {"price": Decimal("1"), "quantity": Decimal("1")})
    with pytest.raises(ValidationError, match="side"):
        _record(
            ReplayInputKind.LIQUIDATION,
            {"price": Decimal("1"), "quantity": Decimal("1"), "side": "long"},
        )
    with pytest.raises(ValidationError, match="price"):
        _record(
            ReplayInputKind.LIQUIDATION,
            {"price": Decimal("0"), "quantity": Decimal("1"), "side": "buy"},
        )
    with pytest.raises(ValidationError, match="quantity"):
        _record(
            ReplayInputKind.LIQUIDATION,
            {"price": Decimal("1"), "quantity": Decimal("-1"), "side": "buy"},
        )


def test_synthetic_event_schema() -> None:
    assert _record(
        ReplayInputKind.SYNTHETIC_EVENT,
        {"event_type": "session_start", "metadata": {"note": "fixture"}},
    )
    with pytest.raises(ValidationError, match="event_type"):
        _record(ReplayInputKind.SYNTHETIC_EVENT, {"other": "value"})
    with pytest.raises(ValidationError, match="event_type"):
        _record(ReplayInputKind.SYNTHETIC_EVENT, {"event_type": ""})


def test_other_only_uses_generic_payload_validation() -> None:
    assert _record(
        ReplayInputKind.OTHER,
        {"nested": {"value": Decimal("1")}, "tags": ("a", "b")},
    )
    with pytest.raises(ValidationError, match="floats"):
        _record(ReplayInputKind.OTHER, {"value": 1.2})
    with pytest.raises(ValidationError, match="finite"):
        _record(ReplayInputKind.OTHER, {"value": Decimal("Infinity")})
