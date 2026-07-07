from __future__ import annotations

from datetime import datetime

from futures_bot.domain.asset_conversion import (
    AssetConversionPolicy,
    AssetConversionRateSnapshot,
)
from futures_bot.domain.assets import AssetSymbol
from futures_bot.domain.ids import (
    AssetConversionPolicyId,
    AssetConversionRateSnapshotId,
)
from futures_bot.domain.time import ensure_aware_utc


class InMemoryAssetConversionRateSnapshotStore:
    """Deterministic conversion rate snapshot store test double."""

    def __init__(self) -> None:
        self._snapshots_by_id: dict[str, AssetConversionRateSnapshot] = {}
        self._snapshot_ids_by_pair: dict[tuple[str, str], set[str]] = {}

    def put(self, snapshot: AssetConversionRateSnapshot) -> None:
        if snapshot.snapshot_id is None:
            raise ValueError("asset conversion snapshot must have snapshot_id")
        key = str(snapshot.snapshot_id)
        existing = self._snapshots_by_id.get(key)
        if existing is not None:
            if existing != snapshot:
                raise ValueError("asset conversion snapshot id collision")
            return
        self._snapshots_by_id[key] = snapshot
        pair = (str(snapshot.from_asset), str(snapshot.to_asset))
        self._snapshot_ids_by_pair.setdefault(pair, set()).add(key)

    def get(
        self,
        snapshot_id: AssetConversionRateSnapshotId,
    ) -> AssetConversionRateSnapshot | None:
        return self._snapshots_by_id.get(str(snapshot_id))

    def latest_for_pair(
        self,
        from_asset: AssetSymbol | str,
        to_asset: AssetSymbol | str,
        checked_at: datetime,
    ) -> AssetConversionRateSnapshot | None:
        checked_at = ensure_aware_utc(checked_at)
        pair = (_asset_key(from_asset), _asset_key(to_asset))
        snapshot_ids = self._snapshot_ids_by_pair.get(pair, set())
        snapshots = tuple(
            self._snapshots_by_id[snapshot_id]
            for snapshot_id in snapshot_ids
            if self._snapshots_by_id[snapshot_id].captured_at <= checked_at
        )
        if not snapshots:
            return None
        return max(snapshots, key=lambda item: (item.captured_at, str(item.snapshot_id)))

    def list_snapshots(self) -> tuple[AssetConversionRateSnapshot, ...]:
        return tuple(
            self._snapshots_by_id[key] for key in sorted(self._snapshots_by_id)
        )


class InMemoryAssetConversionPolicyStore:
    """Deterministic conversion policy store test double."""

    def __init__(self) -> None:
        self._policies_by_id: dict[str, AssetConversionPolicy] = {}

    def put(self, policy: AssetConversionPolicy) -> None:
        if policy.policy_id is None:
            raise ValueError("asset conversion policy must have policy_id")
        key = str(policy.policy_id)
        existing = self._policies_by_id.get(key)
        if existing is not None:
            if existing != policy:
                raise ValueError("asset conversion policy id collision")
            return
        self._policies_by_id[key] = policy

    def get(self, policy_id: AssetConversionPolicyId) -> AssetConversionPolicy | None:
        return self._policies_by_id.get(str(policy_id))

    def list_policies(self) -> tuple[AssetConversionPolicy, ...]:
        return tuple(self._policies_by_id[key] for key in sorted(self._policies_by_id))


def _asset_key(value: AssetSymbol | str) -> str:
    return str(value if isinstance(value, AssetSymbol) else AssetSymbol(value))
