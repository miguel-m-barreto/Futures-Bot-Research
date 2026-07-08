from __future__ import annotations

from datetime import datetime

from futures_bot.domain.execution_costs import (
    ExecutionCostPolicy,
    ExecutionCostRuleSnapshot,
)
from futures_bot.domain.ids import (
    ExecutionCostPolicyId,
    ExecutionCostRuleSnapshotId,
)
from futures_bot.domain.time import ensure_aware_utc


class InMemoryExecutionCostRuleSnapshotStore:
    """Deterministic execution cost rule snapshot store test double."""

    def __init__(self) -> None:
        self._snapshots_by_id: dict[str, ExecutionCostRuleSnapshot] = {}
        self._snapshot_ids_by_scope: dict[tuple[str, str | None], set[str]] = {}

    def put(self, snapshot: ExecutionCostRuleSnapshot) -> None:
        if snapshot.snapshot_id is None:
            raise ValueError("execution cost snapshot must have snapshot_id")
        key = str(snapshot.snapshot_id)
        existing = self._snapshots_by_id.get(key)
        if existing is not None:
            if existing != snapshot:
                raise ValueError("execution cost snapshot id collision")
            return
        self._snapshots_by_id[key] = snapshot
        scope = (snapshot.venue_id, snapshot.instrument_id)
        self._snapshot_ids_by_scope.setdefault(scope, set()).add(key)

    def get(
        self,
        snapshot_id: ExecutionCostRuleSnapshotId,
    ) -> ExecutionCostRuleSnapshot | None:
        return self._snapshots_by_id.get(str(snapshot_id))

    def latest_for_scope(
        self,
        venue_id: str,
        instrument_id: str | None,
        checked_at: datetime,
    ) -> ExecutionCostRuleSnapshot | None:
        checked_at = ensure_aware_utc(checked_at)
        scope = (venue_id, instrument_id)
        snapshot_ids = self._snapshot_ids_by_scope.get(scope, set())
        snapshots = tuple(
            self._snapshots_by_id[snapshot_id]
            for snapshot_id in snapshot_ids
            if self._snapshots_by_id[snapshot_id].captured_at <= checked_at
        )
        if not snapshots:
            return None
        return max(snapshots, key=lambda item: (item.captured_at, str(item.snapshot_id)))

    def list_snapshots(self) -> tuple[ExecutionCostRuleSnapshot, ...]:
        return tuple(
            self._snapshots_by_id[key] for key in sorted(self._snapshots_by_id)
        )


class InMemoryExecutionCostPolicyStore:
    """Deterministic execution cost policy store test double."""

    def __init__(self) -> None:
        self._policies_by_id: dict[str, ExecutionCostPolicy] = {}

    def put(self, policy: ExecutionCostPolicy) -> None:
        if policy.policy_id is None:
            raise ValueError("execution cost policy must have policy_id")
        key = str(policy.policy_id)
        existing = self._policies_by_id.get(key)
        if existing is not None:
            if existing != policy:
                raise ValueError("execution cost policy id collision")
            return
        self._policies_by_id[key] = policy

    def get(self, policy_id: ExecutionCostPolicyId) -> ExecutionCostPolicy | None:
        return self._policies_by_id.get(str(policy_id))

    def list_policies(self) -> tuple[ExecutionCostPolicy, ...]:
        return tuple(self._policies_by_id[key] for key in sorted(self._policies_by_id))
