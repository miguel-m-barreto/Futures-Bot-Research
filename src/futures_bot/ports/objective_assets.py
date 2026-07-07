from __future__ import annotations

from typing import Protocol

from futures_bot.domain.assets import AssetSymbol
from futures_bot.domain.ids import ObjectiveAssetPolicyId
from futures_bot.domain.objective_assets import ObjectiveAssetPolicy


class ObjectiveAssetPolicyStorePort(Protocol):
    """Pure objective asset policy store interface."""

    def put(self, policy: ObjectiveAssetPolicy) -> None:
        """Store an objective asset policy idempotently."""
        ...

    def get(self, policy_id: ObjectiveAssetPolicyId) -> ObjectiveAssetPolicy | None:
        """Return an objective asset policy by ID."""
        ...

    def list_policies(self) -> tuple[ObjectiveAssetPolicy, ...]:
        """Return all policies in deterministic order."""
        ...

    def get_by_objective_asset(
        self,
        objective_asset: AssetSymbol | str,
    ) -> tuple[ObjectiveAssetPolicy, ...]:
        """Return policies matching an objective asset in deterministic order."""
        ...

    def get_by_reference_asset(
        self,
        reference_asset: AssetSymbol | str,
    ) -> tuple[ObjectiveAssetPolicy, ...]:
        """Return policies matching a reference asset in deterministic order."""
        ...
