from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from futures_bot.domain.margin_liquidation import (
    LiquidationModelKind,
    MarginLiquidationPolicy,
    MarginLiquidationRuleSnapshot,
    MarginLiquidationSourceHealth,
    MarginLiquidationSourceKind,
    MarginLiquidationSourceTrust,
    MarginMode,
)
from futures_bot.margin_liquidation.in_memory import (
    InMemoryMarginLiquidationPolicyStore,
    InMemoryMarginLiquidationRuleSnapshotStore,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _snapshot(**overrides: object) -> MarginLiquidationRuleSnapshot:
    values = {
        "venue_id": "kucoin",
        "instrument_id": "BTCUSDTM",
        "margin_mode": MarginMode.ISOLATED,
        "collateral_asset": "USDT",
        "margin_asset": "USDT",
        "settlement_asset": "USDT",
        "initial_margin_rate": Decimal("0.01"),
        "maintenance_margin_rate": Decimal("0.005"),
        "liquidation_fee_rate": Decimal("0.002"),
        "max_leverage": Decimal("100"),
        "liquidation_model_kind": LiquidationModelKind.VENUE_FORMULA,
        "risk_tier_id": "tier-1",
        "observed_at": NOW,
        "captured_at": NOW,
        "source_kind": MarginLiquidationSourceKind.VENUE_RISK_BRACKET,
        "source_trust": MarginLiquidationSourceTrust.OFFICIAL,
        "source_health": MarginLiquidationSourceHealth.HEALTHY,
        "source_record_id": "source-record-1",
        "metadata": {},
    }
    values.update(overrides)
    return MarginLiquidationRuleSnapshot(**values)


def _policy(**overrides: object) -> MarginLiquidationPolicy:
    values = {
        "max_snapshot_age": 60_000,
        "require_source_record": True,
        "allowed_source_kinds": (MarginLiquidationSourceKind.VENUE_RISK_BRACKET,),
        "allowed_source_trust": (MarginLiquidationSourceTrust.OFFICIAL,),
        "allowed_source_health": (MarginLiquidationSourceHealth.HEALTHY,),
        "allowed_margin_modes": (MarginMode.ISOLATED,),
        "require_initial_margin": True,
        "require_maintenance_margin": True,
        "require_liquidation_fee": True,
        "require_max_leverage": True,
        "require_liquidation_model": True,
        "require_risk_tier": True,
        "require_collateral_asset_match": True,
        "require_margin_asset_match": True,
        "require_settlement_asset_match": True,
        "metadata": {},
    }
    values.update(overrides)
    return MarginLiquidationPolicy(**values)


def test_snapshot_store_put_get_idempotent_and_conflict() -> None:
    store = InMemoryMarginLiquidationRuleSnapshotStore()
    snapshot = _snapshot()
    if snapshot.snapshot_id is None:
        raise AssertionError("snapshot_id was not assigned")

    store.put(snapshot)
    store.put(snapshot)

    assert store.get(snapshot.snapshot_id) == snapshot

    conflict = snapshot.model_copy(update={"risk_tier_id": "tier-2"})
    with pytest.raises(ValueError, match="collision"):
        store.put(conflict)


def test_snapshot_store_lists_by_id_and_latest_for_scope() -> None:
    store = InMemoryMarginLiquidationRuleSnapshotStore()
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
    assert store.latest_for_scope("kucoin", "BTCUSDTM", MarginMode.ISOLATED, NOW) == newer


def test_policy_store_put_get_idempotent_and_conflict() -> None:
    store = InMemoryMarginLiquidationPolicyStore()
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
    store = InMemoryMarginLiquidationPolicyStore()
    first = _policy(allowed_margin_modes=(MarginMode.ISOLATED,))
    second = _policy(allowed_margin_modes=(MarginMode.CROSS,))

    store.put(second)
    store.put(first)

    assert store.list_policies() == tuple(
        sorted((first, second), key=lambda item: str(item.policy_id))
    )
