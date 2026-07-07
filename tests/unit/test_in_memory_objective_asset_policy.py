from __future__ import annotations

import pytest

from futures_bot.domain.ids import ObjectiveAssetPolicyId
from futures_bot.domain.objective_assets import ObjectiveAssetPolicy
from futures_bot.objective_assets.in_memory import InMemoryObjectiveAssetPolicyStore


def test_policy_store_put_get_idempotent_and_conflict() -> None:
    store = InMemoryObjectiveAssetPolicyStore()
    policy = ObjectiveAssetPolicy.accumulate("BTC")
    conflict = policy.model_copy(update={"metadata": {"different": True}})

    store.put(policy)
    store.put(policy)

    assert policy.policy_id is not None
    assert store.get(policy.policy_id) == policy
    with pytest.raises(ValueError, match="collision"):
        store.put(conflict)


def test_policy_store_lists_in_deterministic_order() -> None:
    store = InMemoryObjectiveAssetPolicyStore()
    btc = ObjectiveAssetPolicy.accumulate("BTC")
    usdt = ObjectiveAssetPolicy.accumulate("USDT")
    usd_reference = ObjectiveAssetPolicy.maximize_reference_value("USD")

    for policy in (usdt, usd_reference, btc):
        store.put(policy)

    assert store.list_policies() == tuple(
        sorted((btc, usdt, usd_reference), key=lambda item: str(item.policy_id))
    )


def test_policy_store_indexes_by_objective_and_reference_asset() -> None:
    store = InMemoryObjectiveAssetPolicyStore()
    btc = ObjectiveAssetPolicy.accumulate("BTC")
    usd_reference = ObjectiveAssetPolicy.maximize_reference_value("USD")

    store.put(usd_reference)
    store.put(btc)

    assert store.get_by_objective_asset("BTC") == (btc,)
    assert store.get_by_reference_asset("USD") == (usd_reference,)


def test_policy_store_get_unknown_returns_none() -> None:
    store = InMemoryObjectiveAssetPolicyStore()

    assert store.get(ObjectiveAssetPolicyId("objective-asset-policy:unknown")) is None
