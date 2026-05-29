import pytest
from pydantic import ValidationError

from futures_bot.domain.ids import BotId, EventId


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
