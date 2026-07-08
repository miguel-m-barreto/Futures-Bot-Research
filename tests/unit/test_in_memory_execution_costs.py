from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from futures_bot.domain.execution_costs import (
    DepthModelKind,
    ExecutionCostPolicy,
    ExecutionCostRuleSnapshot,
    ExecutionCostSourceHealth,
    ExecutionCostSourceKind,
    ExecutionCostSourceTrust,
    FeeModelKind,
    FundingModelKind,
)
from futures_bot.execution_costs.in_memory import (
    InMemoryExecutionCostPolicyStore,
    InMemoryExecutionCostRuleSnapshotStore,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _snapshot(**overrides: object) -> ExecutionCostRuleSnapshot:
    values = {
        "venue_id": "kucoin",
        "instrument_id": "BTCUSDTM",
        "fee_asset": "USDT",
        "funding_asset": "USDT",
        "depth_reference_asset": "USDT",
        "fee_model_kind": FeeModelKind.MAKER_TAKER_BPS,
        "maker_fee_rate": Decimal("0.0002"),
        "taker_fee_rate": Decimal("0.0006"),
        "fee_tier_id": "tier-1",
        "funding_model_kind": FundingModelKind.PERIODIC_RATE,
        "funding_interval_ms": 28_800_000,
        "funding_rate_cap": Decimal("0.01"),
        "depth_model_kind": DepthModelKind.ORDER_BOOK_DEPTH,
        "min_depth_notional": Decimal("1000"),
        "max_spread_bps": Decimal("5"),
        "observed_at": NOW,
        "captured_at": NOW,
        "source_kind": ExecutionCostSourceKind.VENUE_FEE_SCHEDULE,
        "source_trust": ExecutionCostSourceTrust.OFFICIAL,
        "source_health": ExecutionCostSourceHealth.HEALTHY,
        "source_record_id": "source-record-1",
        "metadata": {},
    }
    values.update(overrides)
    return ExecutionCostRuleSnapshot(**values)


def _policy(**overrides: object) -> ExecutionCostPolicy:
    values = {
        "max_snapshot_age": 60_000,
        "require_source_record": True,
        "allowed_source_kinds": (ExecutionCostSourceKind.VENUE_FEE_SCHEDULE,),
        "allowed_source_trust": (ExecutionCostSourceTrust.OFFICIAL,),
        "allowed_source_health": (ExecutionCostSourceHealth.HEALTHY,),
        "allowed_fee_models": (FeeModelKind.MAKER_TAKER_BPS,),
        "allowed_funding_models": (FundingModelKind.PERIODIC_RATE,),
        "allowed_depth_models": (DepthModelKind.ORDER_BOOK_DEPTH,),
        "require_fee_model": True,
        "require_maker_fee": True,
        "require_taker_fee": True,
        "require_fee_asset_match": True,
        "require_funding_model": True,
        "require_funding_interval": True,
        "require_funding_asset_match": True,
        "require_depth_model": True,
        "require_min_depth_notional": True,
        "require_depth_reference_asset_match": True,
        "require_max_spread_bps": True,
        "metadata": {},
    }
    values.update(overrides)
    return ExecutionCostPolicy(**values)


def test_snapshot_store_put_get_idempotent_and_conflict() -> None:
    store = InMemoryExecutionCostRuleSnapshotStore()
    snapshot = _snapshot()
    if snapshot.snapshot_id is None:
        raise AssertionError("snapshot_id was not assigned")

    store.put(snapshot)
    store.put(snapshot)

    assert store.get(snapshot.snapshot_id) == snapshot

    conflict = snapshot.model_copy(update={"fee_tier_id": "tier-2"})
    with pytest.raises(ValueError, match="collision"):
        store.put(conflict)


def test_snapshot_store_lists_by_id_and_latest_for_scope() -> None:
    store = InMemoryExecutionCostRuleSnapshotStore()
    older = _snapshot(
        captured_at=NOW - timedelta(seconds=1),
        observed_at=NOW - timedelta(seconds=1),
    )
    newer = _snapshot(source_record_id="source-record-2")

    store.put(newer)
    store.put(older)

    assert store.list_snapshots() == tuple(
        sorted((newer, older), key=lambda item: str(item.snapshot_id))
    )
    assert store.latest_for_scope("kucoin", "BTCUSDTM", NOW) == newer


def test_policy_store_put_get_idempotent_and_conflict() -> None:
    store = InMemoryExecutionCostPolicyStore()
    policy = _policy()
    if policy.policy_id is None:
        raise AssertionError("policy_id was not assigned")

    store.put(policy)
    store.put(policy)

    assert store.get(policy.policy_id) == policy

    conflict = policy.model_copy(update={"max_snapshot_age": 1})
    with pytest.raises(ValueError, match="collision"):
        store.put(conflict)


def test_policy_store_lists_by_id() -> None:
    store = InMemoryExecutionCostPolicyStore()
    first = _policy(allowed_fee_models=(FeeModelKind.MAKER_TAKER_BPS,))
    second = _policy(allowed_fee_models=(FeeModelKind.INSTRUMENT_SPECIFIC,))

    store.put(second)
    store.put(first)

    assert store.list_policies() == tuple(
        sorted((first, second), key=lambda item: str(item.policy_id))
    )
