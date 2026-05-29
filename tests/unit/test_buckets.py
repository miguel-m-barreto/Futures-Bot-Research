from decimal import Decimal

import pytest
from pydantic import ValidationError

from futures_bot.domain.assets import AssetAmount, StableCollateralAsset
from futures_bot.domain.buckets import BucketState
from futures_bot.domain.ids import BotId, BucketId


def _amount(asset: str, amount: str) -> AssetAmount:
    return AssetAmount(asset=asset, amount=amount)


def test_valid_bucket_creation_and_tradable_units() -> None:
    bucket = BucketState(
        bucket_id=BucketId("bucket-1"),
        bot_id=BotId("bot-1"),
        capital_asset=StableCollateralAsset("USDT"),
        initial_units=_amount("USDT", "100"),
        active_units=_amount("USDT", "80"),
        reserved_units=_amount("USDT", "30"),
        settled_profit_units=_amount("USDT", "20"),
    )

    assert bucket.tradable_units == AssetAmount(asset="USDT", amount=Decimal("50"))
    assert bucket.has_tradable_units_for(_amount("USDT", "50"))
    assert not bucket.has_tradable_units_for(_amount("USDT", "51"))


def test_settled_profit_is_not_tradable() -> None:
    bucket = BucketState(
        bucket_id=BucketId("bucket-1"),
        bot_id=BotId("bot-1"),
        capital_asset=StableCollateralAsset("USDC"),
        initial_units=_amount("USDC", "100"),
        active_units=_amount("USDC", "10"),
        reserved_units=_amount("USDC", "0"),
        settled_profit_units=_amount("USDC", "90"),
    )

    assert bucket.tradable_units == AssetAmount(asset="USDC", amount="10")


def test_bucket_rejects_amount_asset_mismatch() -> None:
    with pytest.raises(ValidationError, match="capital_asset"):
        BucketState(
            bucket_id=BucketId("bucket-1"),
            bot_id=BotId("bot-1"),
            capital_asset=StableCollateralAsset("USDT"),
            initial_units=_amount("USDT", "100"),
            active_units=_amount("USDC", "80"),
            reserved_units=_amount("USDT", "30"),
            settled_profit_units=_amount("USDT", "20"),
        )


def test_bucket_rejects_reserved_greater_than_active() -> None:
    with pytest.raises(ValidationError, match="reserved_units"):
        BucketState(
            bucket_id=BucketId("bucket-1"),
            bot_id=BotId("bot-1"),
            capital_asset=StableCollateralAsset("USDT"),
            initial_units=_amount("USDT", "100"),
            active_units=_amount("USDT", "20"),
            reserved_units=_amount("USDT", "30"),
            settled_profit_units=_amount("USDT", "0"),
        )


def test_bucket_rejects_negative_units() -> None:
    with pytest.raises(ValidationError, match="non-negative"):
        _amount("USDT", "-1")


@pytest.mark.parametrize("asset", ["ETH", "BTC"])
def test_bucket_rejects_eth_btc_capital_asset(asset: str) -> None:
    with pytest.raises(ValidationError):
        StableCollateralAsset(asset)
