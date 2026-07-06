from __future__ import annotations

from futures_bot.domain.assets import AssetSymbol
from futures_bot.domain.collateral_valuation import (
    CollateralEligibilityRule,
    CollateralHaircutRule,
    CollateralValuationSnapshot,
)
from futures_bot.domain.ids import (
    CollateralEligibilityRuleId,
    CollateralHaircutRuleId,
    CollateralValuationSnapshotId,
)


class InMemoryCollateralValuationSnapshotStore:
    """Deterministic valuation snapshot store test double."""

    def __init__(self) -> None:
        self._snapshots_by_id: dict[str, CollateralValuationSnapshot] = {}
        self._snapshot_ids_by_pair: dict[tuple[str, str], set[str]] = {}

    def put(self, snapshot: CollateralValuationSnapshot) -> None:
        if snapshot.snapshot_id is None:
            raise ValueError("valuation snapshot must have snapshot_id")
        key = str(snapshot.snapshot_id)
        existing = self._snapshots_by_id.get(key)
        if existing is not None:
            if existing != snapshot:
                raise ValueError("collateral valuation snapshot id collision")
            return
        self._snapshots_by_id[key] = snapshot
        pair = (str(snapshot.collateral_asset), str(snapshot.reference_asset))
        self._snapshot_ids_by_pair.setdefault(pair, set()).add(key)

    def get(
        self,
        snapshot_id: CollateralValuationSnapshotId,
    ) -> CollateralValuationSnapshot | None:
        return self._snapshots_by_id.get(str(snapshot_id))

    def get_latest(
        self,
        collateral_asset: AssetSymbol | str,
        reference_asset: AssetSymbol | str,
    ) -> CollateralValuationSnapshot | None:
        pair = (_asset_key(collateral_asset), _asset_key(reference_asset))
        snapshot_ids = self._snapshot_ids_by_pair.get(pair, set())
        snapshots = tuple(self._snapshots_by_id[snapshot_id] for snapshot_id in snapshot_ids)
        if not snapshots:
            return None
        return max(snapshots, key=lambda item: (item.captured_at, str(item.snapshot_id)))

    def list_snapshots(self) -> tuple[CollateralValuationSnapshot, ...]:
        return tuple(
            self._snapshots_by_id[key] for key in sorted(self._snapshots_by_id)
        )


class InMemoryCollateralHaircutRuleStore:
    """Deterministic collateral haircut rule store test double."""

    def __init__(self) -> None:
        self._rules_by_id: dict[str, CollateralHaircutRule] = {}
        self._rule_ids_by_pair: dict[tuple[str, str], set[str]] = {}

    def put(self, rule: CollateralHaircutRule) -> None:
        if rule.rule_id is None:
            raise ValueError("haircut rule must have rule_id")
        key = str(rule.rule_id)
        existing = self._rules_by_id.get(key)
        if existing is not None:
            if existing != rule:
                raise ValueError("collateral haircut rule id collision")
            return
        self._rules_by_id[key] = rule
        pair = (str(rule.collateral_asset), str(rule.reference_asset))
        self._rule_ids_by_pair.setdefault(pair, set()).add(key)

    def get(self, rule_id: CollateralHaircutRuleId) -> CollateralHaircutRule | None:
        return self._rules_by_id.get(str(rule_id))

    def get_latest(
        self,
        collateral_asset: AssetSymbol | str,
        reference_asset: AssetSymbol | str,
    ) -> CollateralHaircutRule | None:
        pair = (_asset_key(collateral_asset), _asset_key(reference_asset))
        rule_ids = self._rule_ids_by_pair.get(pair, set())
        rules = tuple(self._rules_by_id[rule_id] for rule_id in rule_ids)
        if not rules:
            return None
        return max(rules, key=lambda item: (item.effective_at, str(item.rule_id)))

    def list_rules(self) -> tuple[CollateralHaircutRule, ...]:
        return tuple(self._rules_by_id[key] for key in sorted(self._rules_by_id))


class InMemoryCollateralEligibilityRuleStore:
    """Deterministic collateral eligibility rule store test double."""

    def __init__(self) -> None:
        self._rules_by_id: dict[str, CollateralEligibilityRule] = {}
        self._rule_ids_by_asset: dict[str, set[str]] = {}

    def put(self, rule: CollateralEligibilityRule) -> None:
        if rule.eligibility_rule_id is None:
            raise ValueError("eligibility rule must have eligibility_rule_id")
        key = str(rule.eligibility_rule_id)
        existing = self._rules_by_id.get(key)
        if existing is not None:
            if existing != rule:
                raise ValueError("collateral eligibility rule id collision")
            return
        self._rules_by_id[key] = rule
        asset = str(rule.collateral_asset)
        self._rule_ids_by_asset.setdefault(asset, set()).add(key)

    def get(
        self,
        rule_id: CollateralEligibilityRuleId,
    ) -> CollateralEligibilityRule | None:
        return self._rules_by_id.get(str(rule_id))

    def get_latest(
        self,
        collateral_asset: AssetSymbol | str,
    ) -> CollateralEligibilityRule | None:
        rule_ids = self._rule_ids_by_asset.get(_asset_key(collateral_asset), set())
        rules = tuple(self._rules_by_id[rule_id] for rule_id in rule_ids)
        if not rules:
            return None
        return max(
            rules,
            key=lambda item: (item.effective_at, str(item.eligibility_rule_id)),
        )

    def list_rules(self) -> tuple[CollateralEligibilityRule, ...]:
        return tuple(self._rules_by_id[key] for key in sorted(self._rules_by_id))


def _asset_key(value: AssetSymbol | str) -> str:
    return str(value if isinstance(value, AssetSymbol) else AssetSymbol(value))
