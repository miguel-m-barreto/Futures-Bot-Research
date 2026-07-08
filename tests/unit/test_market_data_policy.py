from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from futures_bot.domain.market_data import (
    MarketDataContinuityStatus,
    MarketDataObservationKind,
    MarketDataObservationSnapshot,
    MarketDataReadinessPolicy,
    MarketDataReadinessReason,
    MarketDataSourceHealth,
    MarketDataSourceKind,
    MarketDataSourceTrust,
)
from futures_bot.market_data.policies import evaluate_market_data_readiness

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _snapshot(**overrides: object) -> MarketDataObservationSnapshot:
    values = {
        "venue_id": "kucoin",
        "instrument_id": "BTCUSDTM",
        "observation_kind": MarketDataObservationKind.BEST_BID_ASK,
        "best_bid_price": Decimal("100"),
        "best_ask_price": Decimal("101"),
        "mark_price": Decimal("100.5"),
        "index_price": Decimal("100.4"),
        "last_trade_price": Decimal("100.6"),
        "depth_reference_asset": "USDT",
        "depth_notional": Decimal("1000"),
        "spread_bps": Decimal("10"),
        "sequence_number": 101,
        "previous_sequence_number": 100,
        "continuity_status": MarketDataContinuityStatus.CONTINUOUS,
        "observed_at": NOW - timedelta(seconds=1),
        "captured_at": NOW - timedelta(seconds=1),
        "source_kind": MarketDataSourceKind.VENUE_PUBLIC_MARKET_DATA,
        "source_trust": MarketDataSourceTrust.OFFICIAL,
        "source_health": MarketDataSourceHealth.HEALTHY,
        "source_record_id": "source-record-1",
        "metadata": {},
    }
    values.update(overrides)
    return MarketDataObservationSnapshot(**values)


def _policy(**overrides: object) -> MarketDataReadinessPolicy:
    values = {
        "max_observation_age": 5_000,
        "require_source_record": True,
        "allowed_source_kinds": (
            MarketDataSourceKind.VENUE_PUBLIC_MARKET_DATA,
            MarketDataSourceKind.VENUE_ORDER_BOOK_FEED,
            MarketDataSourceKind.MANUAL_REVIEWED_OBSERVATION,
        ),
        "allowed_source_trust": (MarketDataSourceTrust.OFFICIAL,),
        "allowed_source_health": (MarketDataSourceHealth.HEALTHY,),
        "allowed_observation_kinds": (
            MarketDataObservationKind.BEST_BID_ASK,
            MarketDataObservationKind.ORDER_BOOK_DEPTH,
            MarketDataObservationKind.MARK_PRICE,
            MarketDataObservationKind.INDEX_PRICE,
            MarketDataObservationKind.LAST_TRADE,
        ),
        "allowed_continuity_statuses": (MarketDataContinuityStatus.CONTINUOUS,),
        "require_sequence": True,
        "require_continuous_sequence": True,
        "require_best_bid": True,
        "require_best_ask": True,
        "require_bid_ask_not_crossed": True,
        "require_mark_price": False,
        "require_index_price": False,
        "require_last_trade_price": False,
        "require_depth_notional": False,
        "require_depth_reference_asset_match": False,
        "require_spread_bps": True,
        "metadata": {},
    }
    values.update(overrides)
    return MarketDataReadinessPolicy(**values)


def _evaluate(  # noqa: PLR0913
    *,
    snapshot: MarketDataObservationSnapshot | None = None,
    policy: MarketDataReadinessPolicy | None = None,
    venue_id: str = "kucoin",
    instrument_id: str = "BTCUSDTM",
    observation_kind: MarketDataObservationKind = MarketDataObservationKind.BEST_BID_ASK,
    depth_reference_asset: str = "USDT",
):
    return evaluate_market_data_readiness(
        policy=_policy() if policy is None else policy,
        checked_at=NOW,
        snapshot=_snapshot() if snapshot is None else snapshot,
        venue_id=venue_id,
        instrument_id=instrument_id,
        observation_kind=observation_kind,
        depth_reference_asset=depth_reference_asset,
    )


def test_strict_official_best_bid_ask_snapshot_ready() -> None:
    decision = _evaluate(policy=MarketDataReadinessPolicy.strict_official(metadata={}))

    assert decision.ready
    assert decision.reason is MarketDataReadinessReason.READY


def test_strict_official_order_book_depth_snapshot_ready() -> None:
    policy = MarketDataReadinessPolicy.strict_official(
        metadata={},
    ).model_copy(
        update={
            "require_depth_notional": True,
            "require_depth_reference_asset_match": True,
        },
    )
    decision = _evaluate(
        policy=policy,
        snapshot=_snapshot(
            observation_kind=MarketDataObservationKind.ORDER_BOOK_DEPTH,
            source_kind=MarketDataSourceKind.VENUE_ORDER_BOOK_FEED,
        ),
        observation_kind=MarketDataObservationKind.ORDER_BOOK_DEPTH,
    )

    assert decision.ready
    assert decision.reason is MarketDataReadinessReason.READY


def test_missing_future_and_stale_snapshot_reject() -> None:
    missing = evaluate_market_data_readiness(
        policy=_policy(),
        checked_at=NOW,
        snapshot=None,
    )
    future_observed = _evaluate(
        snapshot=_snapshot(
            observed_at=NOW + timedelta(milliseconds=1),
            captured_at=NOW + timedelta(milliseconds=1),
        ),
    )
    future_captured = _evaluate(
        snapshot=_snapshot(captured_at=NOW + timedelta(milliseconds=1)),
    )
    stale = _evaluate(
        policy=_policy(max_observation_age=500),
        snapshot=_snapshot(observed_at=NOW - timedelta(seconds=2)),
    )

    assert missing.reason is MarketDataReadinessReason.SNAPSHOT_MISSING
    assert future_observed.reason is MarketDataReadinessReason.SNAPSHOT_FUTURE_DATED
    assert future_captured.reason is MarketDataReadinessReason.SNAPSHOT_FUTURE_DATED
    assert stale.reason is MarketDataReadinessReason.SNAPSHOT_STALE


def test_source_gates_reject() -> None:
    unknown_kind = _evaluate(snapshot=_snapshot(source_kind=MarketDataSourceKind.UNKNOWN))
    test_fixture_kind = _evaluate(
        policy=MarketDataReadinessPolicy.strict_official(metadata={}),
        snapshot=_snapshot(source_kind=MarketDataSourceKind.TEST_FIXTURE),
    )
    untrusted = _evaluate(snapshot=_snapshot(source_trust=MarketDataSourceTrust.UNTRUSTED))
    unhealthy = _evaluate(
        snapshot=_snapshot(source_health=MarketDataSourceHealth.UNHEALTHY),
    )
    gapped = _evaluate(snapshot=_snapshot(source_health=MarketDataSourceHealth.GAPPED))
    missing_record = _evaluate(snapshot=_snapshot(source_record_id=None))

    assert unknown_kind.reason is MarketDataReadinessReason.SOURCE_KIND_UNKNOWN
    assert test_fixture_kind.reason is MarketDataReadinessReason.SOURCE_KIND_UNSUPPORTED
    assert untrusted.reason is MarketDataReadinessReason.SOURCE_UNTRUSTED
    assert unhealthy.reason is MarketDataReadinessReason.SOURCE_UNHEALTHY
    assert gapped.reason is MarketDataReadinessReason.SOURCE_UNHEALTHY
    assert missing_record.reason is MarketDataReadinessReason.SOURCE_RECORD_REQUIRED


def test_kind_and_scope_gates_reject() -> None:
    unknown_kind = _evaluate(
        snapshot=_snapshot(observation_kind=MarketDataObservationKind.UNKNOWN),
    )
    unsupported_kind = _evaluate(
        policy=_policy(allowed_observation_kinds=(MarketDataObservationKind.MARK_PRICE,)),
    )
    requested_mismatch = _evaluate(
        observation_kind=MarketDataObservationKind.MARK_PRICE,
    )
    venue_mismatch = _evaluate(venue_id="binance")
    instrument_mismatch = _evaluate(instrument_id="ETHUSDT")

    assert unknown_kind.reason is MarketDataReadinessReason.OBSERVATION_KIND_UNKNOWN
    assert unsupported_kind.reason is (
        MarketDataReadinessReason.OBSERVATION_KIND_UNSUPPORTED
    )
    assert requested_mismatch.reason is (
        MarketDataReadinessReason.OBSERVATION_KIND_UNSUPPORTED
    )
    assert venue_mismatch.reason is MarketDataReadinessReason.VENUE_MISMATCH
    assert instrument_mismatch.reason is MarketDataReadinessReason.INSTRUMENT_MISMATCH


def test_continuity_and_sequence_gates_reject() -> None:
    unknown = _evaluate(
        snapshot=_snapshot(continuity_status=MarketDataContinuityStatus.UNKNOWN),
    )
    declared_gap = _evaluate(
        snapshot=_snapshot(continuity_status=MarketDataContinuityStatus.GAP_DECLARED),
    )
    missing_sequence = _evaluate(snapshot=_snapshot(sequence_number=None))
    sequence_gap = _evaluate(snapshot=_snapshot(sequence_number=103))

    assert unknown.reason is MarketDataReadinessReason.CONTINUITY_UNKNOWN
    assert declared_gap.reason is MarketDataReadinessReason.CONTINUITY_GAPPED
    assert missing_sequence.reason is MarketDataReadinessReason.SEQUENCE_REQUIRED
    assert sequence_gap.reason is MarketDataReadinessReason.SEQUENCE_GAP_DECLARED


def test_required_observation_field_gates_reject_without_substitution() -> None:
    assert _evaluate(snapshot=_snapshot(best_bid_price=None)).reason is (
        MarketDataReadinessReason.BID_MISSING
    )
    assert _evaluate(snapshot=_snapshot(best_ask_price=None)).reason is (
        MarketDataReadinessReason.ASK_MISSING
    )
    assert _evaluate(snapshot=_snapshot(best_bid_price=Decimal("102"))).reason is (
        MarketDataReadinessReason.BID_ASK_CROSSED
    )
    assert _evaluate(
        policy=_policy(require_mark_price=True, require_best_bid=False),
        snapshot=_snapshot(mark_price=None, last_trade_price=Decimal("100")),
    ).reason is MarketDataReadinessReason.MARK_PRICE_MISSING
    assert _evaluate(
        policy=_policy(require_index_price=True, require_best_bid=False),
        snapshot=_snapshot(index_price=None, mark_price=Decimal("100")),
    ).reason is MarketDataReadinessReason.INDEX_PRICE_MISSING
    assert _evaluate(
        policy=_policy(require_last_trade_price=True, require_best_bid=False),
        snapshot=_snapshot(last_trade_price=None, index_price=Decimal("100")),
    ).reason is MarketDataReadinessReason.LAST_PRICE_MISSING


def test_depth_and_spread_gates_reject() -> None:
    policy = _policy(
        require_depth_notional=True,
        require_depth_reference_asset_match=True,
        max_spread_bps=Decimal("20"),
    )
    missing_depth = _evaluate(policy=policy, snapshot=_snapshot(depth_notional=None))
    missing_asset = _evaluate(
        policy=policy,
        snapshot=_snapshot(depth_reference_asset=None),
    )
    mismatch = _evaluate(policy=policy, depth_reference_asset="USD")
    missing_spread = _evaluate(policy=policy, snapshot=_snapshot(spread_bps=None))
    wide = _evaluate(policy=policy, snapshot=_snapshot(spread_bps=Decimal("30")))

    assert missing_depth.reason is MarketDataReadinessReason.DEPTH_NOTIONAL_MISSING
    assert missing_asset.reason is (
        MarketDataReadinessReason.DEPTH_REFERENCE_ASSET_MISSING
    )
    assert mismatch.reason is MarketDataReadinessReason.DEPTH_REFERENCE_ASSET_MISMATCH
    assert missing_spread.reason is MarketDataReadinessReason.SPREAD_MISSING
    assert wide.reason is MarketDataReadinessReason.SPREAD_TOO_WIDE


def test_no_implicit_asset_or_price_kind_equivalence() -> None:
    usdt_usd = _evaluate(
        policy=_policy(require_depth_reference_asset_match=True),
        depth_reference_asset="USD",
    )
    usdc_usdt = _evaluate(
        policy=_policy(require_depth_reference_asset_match=True),
        snapshot=_snapshot(depth_reference_asset="USDC"),
    )
    btc_eth = _evaluate(
        policy=_policy(require_depth_reference_asset_match=True),
        snapshot=_snapshot(depth_reference_asset="BTC"),
        depth_reference_asset="ETH",
    )
    mark_is_not_index = _evaluate(
        policy=_policy(require_index_price=True),
        snapshot=_snapshot(index_price=None, mark_price=Decimal("100")),
    )

    assert usdt_usd.reason is MarketDataReadinessReason.DEPTH_REFERENCE_ASSET_MISMATCH
    assert usdc_usdt.reason is (
        MarketDataReadinessReason.DEPTH_REFERENCE_ASSET_MISMATCH
    )
    assert btc_eth.reason is MarketDataReadinessReason.DEPTH_REFERENCE_ASSET_MISMATCH
    assert mark_is_not_index.reason is MarketDataReadinessReason.INDEX_PRICE_MISSING


def test_other_readiness_decisions_are_not_market_data_snapshots() -> None:
    decision = evaluate_market_data_readiness(
        policy=_policy(),
        checked_at=NOW,
        snapshot=object(),  # type: ignore[arg-type]
    )

    assert not decision.ready
    assert decision.reason is MarketDataReadinessReason.SNAPSHOT_MISSING
