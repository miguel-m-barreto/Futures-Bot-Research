from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from futures_bot.domain.market_data import (
    MarketDataContinuityStatus,
    MarketDataObservationKind,
    MarketDataObservationSnapshot,
    MarketDataReadinessPolicy,
    MarketDataSourceHealth,
    MarketDataSourceKind,
    MarketDataSourceTrust,
)
from futures_bot.market_data.in_memory import (
    InMemoryMarketDataObservationSnapshotStore,
    InMemoryMarketDataReadinessPolicyStore,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _snapshot(**overrides: object) -> MarketDataObservationSnapshot:
    values = {
        "venue_id": "kucoin",
        "instrument_id": "BTCUSDTM",
        "observation_kind": MarketDataObservationKind.BEST_BID_ASK,
        "best_bid_price": Decimal("100"),
        "best_ask_price": Decimal("101"),
        "depth_reference_asset": "USDT",
        "depth_notional": Decimal("1000"),
        "spread_bps": Decimal("10"),
        "sequence_number": 101,
        "previous_sequence_number": 100,
        "continuity_status": MarketDataContinuityStatus.CONTINUOUS,
        "observed_at": NOW,
        "captured_at": NOW,
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
        "allowed_source_kinds": (MarketDataSourceKind.VENUE_PUBLIC_MARKET_DATA,),
        "allowed_source_trust": (MarketDataSourceTrust.OFFICIAL,),
        "allowed_source_health": (MarketDataSourceHealth.HEALTHY,),
        "allowed_observation_kinds": (MarketDataObservationKind.BEST_BID_ASK,),
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


def test_snapshot_store_put_get_idempotent_and_conflict() -> None:
    store = InMemoryMarketDataObservationSnapshotStore()
    snapshot = _snapshot()
    if snapshot.snapshot_id is None:
        raise AssertionError("snapshot_id was not assigned")

    store.put(snapshot)
    store.put(snapshot)

    assert store.get(snapshot.snapshot_id) == snapshot

    conflict = snapshot.model_copy(update={"best_bid_price": Decimal("99")})
    with pytest.raises(ValueError, match="collision"):
        store.put(conflict)


def test_snapshot_store_lists_by_id_and_latest_for_scope() -> None:
    store = InMemoryMarketDataObservationSnapshotStore()
    older = _snapshot(
        observed_at=NOW - timedelta(seconds=1),
        captured_at=NOW - timedelta(seconds=1),
    )
    newer = _snapshot(source_record_id="source-record-2")

    store.put(newer)
    store.put(older)

    assert store.list_snapshots() == tuple(
        sorted((newer, older), key=lambda item: str(item.snapshot_id))
    )
    assert store.latest_for_scope(
        "kucoin",
        "BTCUSDTM",
        MarketDataObservationKind.BEST_BID_ASK,
        NOW,
    ) == newer


def test_policy_store_put_get_idempotent_and_conflict() -> None:
    store = InMemoryMarketDataReadinessPolicyStore()
    policy = _policy()
    if policy.policy_id is None:
        raise AssertionError("policy_id was not assigned")

    store.put(policy)
    store.put(policy)

    assert store.get(policy.policy_id) == policy

    conflict = policy.model_copy(update={"max_observation_age": 1})
    with pytest.raises(ValueError, match="collision"):
        store.put(conflict)


def test_policy_store_lists_by_id() -> None:
    store = InMemoryMarketDataReadinessPolicyStore()
    first = _policy(allowed_observation_kinds=(MarketDataObservationKind.BEST_BID_ASK,))
    second = _policy(allowed_observation_kinds=(MarketDataObservationKind.MARK_PRICE,))

    store.put(second)
    store.put(first)

    assert store.list_policies() == tuple(
        sorted((first, second), key=lambda item: str(item.policy_id))
    )
