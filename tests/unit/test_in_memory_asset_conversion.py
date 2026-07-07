from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from futures_bot.asset_conversion.in_memory import (
    InMemoryAssetConversionPolicyStore,
    InMemoryAssetConversionRateSnapshotStore,
)
from futures_bot.domain.asset_conversion import (
    AssetConversionEvidenceKind,
    AssetConversionPolicy,
    AssetConversionRateSnapshot,
    AssetConversionSourceHealth,
    AssetConversionSourceKind,
    AssetConversionSourceTrust,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _snapshot(**overrides: object) -> AssetConversionRateSnapshot:
    values = {
        "from_asset": "BTC",
        "to_asset": "USDT",
        "rate": Decimal("50000"),
        "observed_at": NOW,
        "captured_at": NOW,
        "source_kind": AssetConversionSourceKind.ORACLE_PRICE,
        "source_trust": AssetConversionSourceTrust.OFFICIAL,
        "source_health": AssetConversionSourceHealth.HEALTHY,
        "evidence_kind": AssetConversionEvidenceKind.DIRECT_PAIR_RATE,
        "source_record_id": "source-record-1",
        "metadata": {},
    }
    values.update(overrides)
    return AssetConversionRateSnapshot(**values)


def _policy(**overrides: object) -> AssetConversionPolicy:
    values = {
        "max_rate_age": 60_000,
        "require_source_record": True,
        "allowed_source_trust": (AssetConversionSourceTrust.OFFICIAL,),
        "allowed_source_health": (AssetConversionSourceHealth.HEALTHY,),
        "allow_same_asset_direct_match": False,
        "allow_inverse_rate": False,
        "allow_triangulation": False,
        "require_bid_ask": False,
        "metadata": {},
    }
    values.update(overrides)
    return AssetConversionPolicy(**values)


def test_snapshot_store_put_get_idempotent_and_conflict() -> None:
    store = InMemoryAssetConversionRateSnapshotStore()
    snapshot = _snapshot()
    if snapshot.snapshot_id is None:
        raise AssertionError("snapshot_id was not assigned")

    store.put(snapshot)
    store.put(snapshot)

    assert store.get(snapshot.snapshot_id) == snapshot

    conflict = snapshot.model_copy(update={"rate": Decimal("1")})
    with pytest.raises(ValueError, match="collision"):
        store.put(conflict)


def test_snapshot_store_lists_by_id_and_latest_for_pair() -> None:
    store = InMemoryAssetConversionRateSnapshotStore()
    older = _snapshot(
        captured_at=NOW - timedelta(seconds=1),
        observed_at=NOW - timedelta(seconds=1),
    )
    newer = _snapshot(source_record_id="source-record-2")
    for snapshot in (newer, older):
        store.put(snapshot)

    assert store.list_snapshots() == tuple(
        sorted((newer, older), key=lambda item: str(item.snapshot_id))
    )
    assert store.latest_for_pair("BTC", "USDT", NOW) == newer


def test_policy_store_put_get_idempotent_and_conflict() -> None:
    store = InMemoryAssetConversionPolicyStore()
    policy = _policy()
    if policy.policy_id is None:
        raise AssertionError("policy_id was not assigned")

    store.put(policy)
    store.put(policy)

    assert store.get(policy.policy_id) == policy

    conflict = policy.model_copy(update={"max_rate_age": 1})
    with pytest.raises(ValueError, match="collision"):
        store.put(conflict)


def test_policy_store_lists_by_id() -> None:
    store = InMemoryAssetConversionPolicyStore()
    first = _policy(from_asset="BTC")
    second = _policy(from_asset="ETH")

    store.put(second)
    store.put(first)

    assert store.list_policies() == tuple(
        sorted((first, second), key=lambda item: str(item.policy_id))
    )
