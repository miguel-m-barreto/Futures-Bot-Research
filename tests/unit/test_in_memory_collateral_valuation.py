from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from futures_bot.collateral_valuation.in_memory import (
    InMemoryCollateralEligibilityRuleStore,
    InMemoryCollateralHaircutRuleStore,
    InMemoryCollateralValuationSnapshotStore,
)
from futures_bot.domain.collateral_valuation import (
    CollateralEligibilityRule,
    CollateralEligibilityStatus,
    CollateralHaircutKind,
    CollateralHaircutRule,
    CollateralValuationHealth,
    CollateralValuationSnapshot,
    CollateralValuationSourceKind,
    CollateralValuationTrust,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _snapshot(**overrides: object) -> CollateralValuationSnapshot:
    values = {
        "collateral_asset": "BTC",
        "reference_asset": "USD",
        "price": Decimal("50000"),
        "source_kind": CollateralValuationSourceKind.ORACLE_PRICE,
        "trust": CollateralValuationTrust.OFFICIAL,
        "health": CollateralValuationHealth.HEALTHY,
        "observed_at": NOW,
        "captured_at": NOW,
        "metadata": {},
    }
    values.update(overrides)
    return CollateralValuationSnapshot(**values)


def _haircut(**overrides: object) -> CollateralHaircutRule:
    values = {
        "collateral_asset": "BTC",
        "reference_asset": "USD",
        "haircut_kind": CollateralHaircutKind.FIXED_PERCENTAGE,
        "haircut_rate": Decimal("0.25"),
        "effective_at": NOW,
        "metadata": {},
    }
    values.update(overrides)
    return CollateralHaircutRule(**values)


def _eligibility(**overrides: object) -> CollateralEligibilityRule:
    values = {
        "collateral_asset": "BTC",
        "eligibility_status": CollateralEligibilityStatus.ELIGIBLE,
        "effective_at": NOW,
        "metadata": {},
    }
    values.update(overrides)
    return CollateralEligibilityRule(**values)


def test_valuation_store_put_get_idempotent_and_conflict() -> None:
    store = InMemoryCollateralValuationSnapshotStore()
    snapshot = _snapshot()
    conflict = snapshot.model_copy(update={"metadata": {"different": True}})

    store.put(snapshot)
    store.put(snapshot)

    assert snapshot.snapshot_id is not None
    assert store.get(snapshot.snapshot_id) == snapshot
    with pytest.raises(ValueError, match="collision"):
        store.put(conflict)


def test_latest_valuation_deterministic_by_captured_at_then_id() -> None:
    store = InMemoryCollateralValuationSnapshotStore()
    older = _snapshot(
        price=Decimal("49000"),
        observed_at=NOW - timedelta(seconds=1),
        captured_at=NOW - timedelta(seconds=1),
    )
    first = _snapshot(price=Decimal("50000"))
    second = _snapshot(price=Decimal("51000"))

    for snapshot in (second, older, first):
        store.put(snapshot)

    expected = max((first, second), key=lambda item: str(item.snapshot_id))
    assert store.get_latest("BTC", "USD") == expected
    assert store.list_snapshots() == tuple(
        sorted((older, first, second), key=lambda item: str(item.snapshot_id))
    )


def test_haircut_store_put_get_idempotent_and_conflict() -> None:
    store = InMemoryCollateralHaircutRuleStore()
    rule = _haircut()
    conflict = rule.model_copy(update={"metadata": {"different": True}})

    store.put(rule)
    store.put(rule)

    assert rule.rule_id is not None
    assert store.get(rule.rule_id) == rule
    with pytest.raises(ValueError, match="collision"):
        store.put(conflict)


def test_latest_haircut_deterministic_by_effective_at_then_id() -> None:
    store = InMemoryCollateralHaircutRuleStore()
    older = _haircut(haircut_rate=Decimal("0.20"), effective_at=NOW - timedelta(days=1))
    first = _haircut(haircut_rate=Decimal("0.25"))
    second = _haircut(haircut_rate=Decimal("0.30"))

    for rule in (second, older, first):
        store.put(rule)

    expected = max((first, second), key=lambda item: str(item.rule_id))
    assert store.get_latest("BTC", "USD") == expected
    assert store.list_rules() == tuple(
        sorted((older, first, second), key=lambda item: str(item.rule_id))
    )


def test_eligibility_store_put_get_idempotent_conflict_and_order() -> None:
    store = InMemoryCollateralEligibilityRuleStore()
    older = _eligibility(effective_at=NOW - timedelta(days=1), reason="older")
    rule = _eligibility(reason="latest")
    conflict = rule.model_copy(update={"metadata": {"different": True}})

    store.put(rule)
    store.put(older)
    store.put(rule)

    assert rule.eligibility_rule_id is not None
    assert store.get(rule.eligibility_rule_id) == rule
    assert store.get_latest("BTC") == rule
    assert store.list_rules() == tuple(
        sorted((older, rule), key=lambda item: str(item.eligibility_rule_id))
    )
    with pytest.raises(ValueError, match="collision"):
        store.put(conflict)
