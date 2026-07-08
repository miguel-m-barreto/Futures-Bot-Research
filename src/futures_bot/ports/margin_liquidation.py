from __future__ import annotations

from datetime import datetime
from typing import Protocol

from futures_bot.domain.ids import (
    MarginLiquidationPolicyId,
    MarginLiquidationRuleSnapshotId,
)
from futures_bot.domain.margin_liquidation import (
    MarginLiquidationPolicy,
    MarginLiquidationRuleSnapshot,
    MarginMode,
)


class MarginLiquidationRuleSnapshotStorePort(Protocol):
    """Pure margin/liquidation rule snapshot store interface."""

    def put(self, snapshot: MarginLiquidationRuleSnapshot) -> None:
        """Store a margin/liquidation rule snapshot idempotently."""
        ...

    def get(
        self,
        snapshot_id: MarginLiquidationRuleSnapshotId,
    ) -> MarginLiquidationRuleSnapshot | None:
        """Return a margin/liquidation rule snapshot by ID."""
        ...

    def latest_for_scope(
        self,
        venue_id: str,
        instrument_id: str | None,
        margin_mode: MarginMode | str,
        checked_at: datetime,
    ) -> MarginLiquidationRuleSnapshot | None:
        """Return the latest deterministic snapshot for a scope at checked_at."""
        ...

    def list_snapshots(self) -> tuple[MarginLiquidationRuleSnapshot, ...]:
        """Return all snapshots in deterministic ID order."""
        ...


class MarginLiquidationPolicyStorePort(Protocol):
    """Pure margin/liquidation policy store interface."""

    def put(self, policy: MarginLiquidationPolicy) -> None:
        """Store a margin/liquidation policy idempotently."""
        ...

    def get(self, policy_id: MarginLiquidationPolicyId) -> MarginLiquidationPolicy | None:
        """Return a margin/liquidation policy by ID."""
        ...

    def list_policies(self) -> tuple[MarginLiquidationPolicy, ...]:
        """Return all policies in deterministic ID order."""
        ...
