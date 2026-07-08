from __future__ import annotations

from datetime import datetime
from typing import Protocol

from futures_bot.domain.execution_costs import (
    ExecutionCostPolicy,
    ExecutionCostRuleSnapshot,
)
from futures_bot.domain.ids import (
    ExecutionCostPolicyId,
    ExecutionCostRuleSnapshotId,
)


class ExecutionCostRuleSnapshotStorePort(Protocol):
    """Pure execution cost rule snapshot store interface."""

    def put(self, snapshot: ExecutionCostRuleSnapshot) -> None:
        """Store an execution cost rule snapshot idempotently."""
        ...

    def get(
        self,
        snapshot_id: ExecutionCostRuleSnapshotId,
    ) -> ExecutionCostRuleSnapshot | None:
        """Return an execution cost rule snapshot by ID."""
        ...

    def latest_for_scope(
        self,
        venue_id: str,
        instrument_id: str | None,
        checked_at: datetime,
    ) -> ExecutionCostRuleSnapshot | None:
        """Return the latest deterministic snapshot for a scope at checked_at."""
        ...

    def list_snapshots(self) -> tuple[ExecutionCostRuleSnapshot, ...]:
        """Return all snapshots in deterministic ID order."""
        ...


class ExecutionCostPolicyStorePort(Protocol):
    """Pure execution cost policy store interface."""

    def put(self, policy: ExecutionCostPolicy) -> None:
        """Store an execution cost policy idempotently."""
        ...

    def get(self, policy_id: ExecutionCostPolicyId) -> ExecutionCostPolicy | None:
        """Return an execution cost policy by ID."""
        ...

    def list_policies(self) -> tuple[ExecutionCostPolicy, ...]:
        """Return all policies in deterministic ID order."""
        ...
