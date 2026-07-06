from __future__ import annotations

from typing import Protocol

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


class CollateralValuationSnapshotStorePort(Protocol):
    """Pure collateral valuation snapshot store interface."""

    def put(self, snapshot: CollateralValuationSnapshot) -> None:
        """Store a valuation snapshot idempotently."""
        ...

    def get(
        self,
        snapshot_id: CollateralValuationSnapshotId,
    ) -> CollateralValuationSnapshot | None:
        """Return a valuation snapshot by ID."""
        ...

    def get_latest(
        self,
        collateral_asset: AssetSymbol | str,
        reference_asset: AssetSymbol | str,
    ) -> CollateralValuationSnapshot | None:
        """Return the latest valuation snapshot for an asset pair."""
        ...

    def list_snapshots(self) -> tuple[CollateralValuationSnapshot, ...]:
        """Return all valuation snapshots in deterministic order."""
        ...


class CollateralHaircutRuleStorePort(Protocol):
    """Pure collateral haircut rule store interface."""

    def put(self, rule: CollateralHaircutRule) -> None:
        """Store a haircut rule idempotently."""
        ...

    def get(self, rule_id: CollateralHaircutRuleId) -> CollateralHaircutRule | None:
        """Return a haircut rule by ID."""
        ...

    def get_latest(
        self,
        collateral_asset: AssetSymbol | str,
        reference_asset: AssetSymbol | str,
    ) -> CollateralHaircutRule | None:
        """Return the latest haircut rule for an asset pair."""
        ...

    def list_rules(self) -> tuple[CollateralHaircutRule, ...]:
        """Return all haircut rules in deterministic order."""
        ...


class CollateralEligibilityRuleStorePort(Protocol):
    """Pure collateral eligibility rule store interface."""

    def put(self, rule: CollateralEligibilityRule) -> None:
        """Store an eligibility rule idempotently."""
        ...

    def get(
        self,
        rule_id: CollateralEligibilityRuleId,
    ) -> CollateralEligibilityRule | None:
        """Return an eligibility rule by ID."""
        ...

    def get_latest(
        self,
        collateral_asset: AssetSymbol | str,
    ) -> CollateralEligibilityRule | None:
        """Return the latest eligibility rule for a collateral asset."""
        ...

    def list_rules(self) -> tuple[CollateralEligibilityRule, ...]:
        """Return all eligibility rules in deterministic order."""
        ...
