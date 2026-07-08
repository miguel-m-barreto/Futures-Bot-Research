from __future__ import annotations

from datetime import datetime

from futures_bot.domain.ids import (
    MarketDataObservationSnapshotId,
    MarketDataReadinessPolicyId,
)
from futures_bot.domain.market_data import (
    MarketDataObservationKind,
    MarketDataObservationSnapshot,
    MarketDataReadinessPolicy,
)
from futures_bot.domain.time import ensure_aware_utc


class InMemoryMarketDataObservationSnapshotStore:
    """Deterministic market-data observation snapshot store test double."""

    def __init__(self) -> None:
        self._snapshots_by_id: dict[str, MarketDataObservationSnapshot] = {}
        self._snapshot_ids_by_scope: dict[tuple[str, str, str], set[str]] = {}

    def put(self, snapshot: MarketDataObservationSnapshot) -> None:
        if snapshot.snapshot_id is None:
            raise ValueError("market data snapshot must have snapshot_id")
        key = str(snapshot.snapshot_id)
        existing = self._snapshots_by_id.get(key)
        if existing is not None:
            if existing != snapshot:
                raise ValueError("market data snapshot id collision")
            return
        self._snapshots_by_id[key] = snapshot
        scope = (
            snapshot.venue_id,
            snapshot.instrument_id,
            snapshot.observation_kind.value,
        )
        self._snapshot_ids_by_scope.setdefault(scope, set()).add(key)

    def get(
        self,
        snapshot_id: MarketDataObservationSnapshotId,
    ) -> MarketDataObservationSnapshot | None:
        return self._snapshots_by_id.get(str(snapshot_id))

    def latest_for_scope(
        self,
        venue_id: str,
        instrument_id: str,
        observation_kind: MarketDataObservationKind | str,
        checked_at: datetime,
    ) -> MarketDataObservationSnapshot | None:
        checked_at = ensure_aware_utc(checked_at)
        kind = (
            observation_kind
            if isinstance(observation_kind, MarketDataObservationKind)
            else MarketDataObservationKind(observation_kind)
        )
        scope = (venue_id, instrument_id, kind.value)
        snapshot_ids = self._snapshot_ids_by_scope.get(scope, set())
        snapshots = tuple(
            self._snapshots_by_id[snapshot_id]
            for snapshot_id in snapshot_ids
            if self._snapshots_by_id[snapshot_id].captured_at <= checked_at
        )
        if not snapshots:
            return None
        return max(snapshots, key=lambda item: (item.captured_at, str(item.snapshot_id)))

    def list_snapshots(self) -> tuple[MarketDataObservationSnapshot, ...]:
        return tuple(
            self._snapshots_by_id[key] for key in sorted(self._snapshots_by_id)
        )


class InMemoryMarketDataReadinessPolicyStore:
    """Deterministic market-data readiness policy store test double."""

    def __init__(self) -> None:
        self._policies_by_id: dict[str, MarketDataReadinessPolicy] = {}

    def put(self, policy: MarketDataReadinessPolicy) -> None:
        if policy.policy_id is None:
            raise ValueError("market data policy must have policy_id")
        key = str(policy.policy_id)
        existing = self._policies_by_id.get(key)
        if existing is not None:
            if existing != policy:
                raise ValueError("market data policy id collision")
            return
        self._policies_by_id[key] = policy

    def get(
        self,
        policy_id: MarketDataReadinessPolicyId,
    ) -> MarketDataReadinessPolicy | None:
        return self._policies_by_id.get(str(policy_id))

    def list_policies(self) -> tuple[MarketDataReadinessPolicy, ...]:
        return tuple(self._policies_by_id[key] for key in sorted(self._policies_by_id))
