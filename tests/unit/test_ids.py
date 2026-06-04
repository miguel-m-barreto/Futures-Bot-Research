import pytest
from pydantic import ValidationError

from futures_bot.domain.ids import (
    BotId,
    DomainId,
    EventId,
    ExchangeOrderId,
    ExecutionIntentId,
    FillId,
    InstrumentId,
    OrderIntentId,
)


def test_domain_id_accepts_trimmed_non_empty_value() -> None:
    bot_id = BotId("bot-1")

    assert str(bot_id) == "bot-1"
    assert repr(bot_id) == "BotId('bot-1')"
    assert bot_id == BotId("bot-1")
    assert bot_id != EventId("bot-1")


@pytest.mark.parametrize("value", ["", " ", " bot", "bot ", "x" * 129])
def test_domain_id_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValidationError):
        BotId(value)


def test_domain_id_non_string_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        BotId(123)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "id_cls",
    [ExecutionIntentId, OrderIntentId, ExchangeOrderId, FillId, InstrumentId],
)
def test_new_domain_ids_reject_empty_strings(id_cls: type[DomainId]) -> None:
    with pytest.raises(ValidationError):
        id_cls("")


@pytest.mark.parametrize(
    ("id_cls", "value"),
    [
        (ExecutionIntentId, "execution-intent-1"),
        (OrderIntentId, "order-intent-1"),
        (ExchangeOrderId, "exchange-order-1"),
        (FillId, "fill-1"),
        (InstrumentId, "instrument-1"),
    ],
)
def test_new_domain_ids_stringify_consistently(
    id_cls: type[DomainId],
    value: str,
) -> None:
    domain_id = id_cls(value)

    assert str(domain_id) == value
    assert id_cls.from_str(value) == domain_id
