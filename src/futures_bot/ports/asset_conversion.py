from __future__ import annotations

from datetime import datetime
from typing import Protocol

from futures_bot.domain.asset_conversion import (
    AssetConversionPolicy,
    AssetConversionRateSnapshot,
)
from futures_bot.domain.assets import AssetSymbol
from futures_bot.domain.ids import (
    AssetConversionPolicyId,
    AssetConversionRateSnapshotId,
)


class AssetConversionRateSnapshotStorePort(Protocol):
    """Pure asset conversion rate snapshot store interface."""

    def put(self, snapshot: AssetConversionRateSnapshot) -> None:
        """Store a conversion rate snapshot idempotently."""
        ...

    def get(
        self,
        snapshot_id: AssetConversionRateSnapshotId,
    ) -> AssetConversionRateSnapshot | None:
        """Return a conversion rate snapshot by ID."""
        ...

    def latest_for_pair(
        self,
        from_asset: AssetSymbol | str,
        to_asset: AssetSymbol | str,
        checked_at: datetime,
    ) -> AssetConversionRateSnapshot | None:
        """Return the latest deterministic snapshot for a pair at checked_at."""
        ...

    def list_snapshots(self) -> tuple[AssetConversionRateSnapshot, ...]:
        """Return all snapshots in deterministic ID order."""
        ...


class AssetConversionPolicyStorePort(Protocol):
    """Pure asset conversion policy store interface."""

    def put(self, policy: AssetConversionPolicy) -> None:
        """Store a conversion policy idempotently."""
        ...

    def get(self, policy_id: AssetConversionPolicyId) -> AssetConversionPolicy | None:
        """Return a conversion policy by ID."""
        ...

    def list_policies(self) -> tuple[AssetConversionPolicy, ...]:
        """Return all policies in deterministic ID order."""
        ...
