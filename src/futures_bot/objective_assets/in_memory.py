from __future__ import annotations

from futures_bot.domain.assets import AssetSymbol
from futures_bot.domain.ids import ObjectiveAssetPolicyId
from futures_bot.domain.objective_assets import ObjectiveAssetPolicy


class InMemoryObjectiveAssetPolicyStore:
    """Deterministic objective asset policy store test double."""

    def __init__(self) -> None:
        self._policies_by_id: dict[str, ObjectiveAssetPolicy] = {}
        self._policy_ids_by_objective_asset: dict[str, set[str]] = {}
        self._policy_ids_by_reference_asset: dict[str, set[str]] = {}

    def put(self, policy: ObjectiveAssetPolicy) -> None:
        if policy.policy_id is None:
            raise ValueError("objective asset policy must have policy_id")
        key = str(policy.policy_id)
        existing = self._policies_by_id.get(key)
        if existing is not None:
            if existing != policy:
                raise ValueError("objective asset policy id collision")
            return
        self._policies_by_id[key] = policy
        if policy.objective_asset is not None:
            objective_asset = str(policy.objective_asset)
            self._policy_ids_by_objective_asset.setdefault(
                objective_asset,
                set(),
            ).add(key)
        if policy.reference_asset is not None:
            reference_asset = str(policy.reference_asset)
            self._policy_ids_by_reference_asset.setdefault(
                reference_asset,
                set(),
            ).add(key)

    def get(self, policy_id: ObjectiveAssetPolicyId) -> ObjectiveAssetPolicy | None:
        return self._policies_by_id.get(str(policy_id))

    def list_policies(self) -> tuple[ObjectiveAssetPolicy, ...]:
        return tuple(self._policies_by_id[key] for key in sorted(self._policies_by_id))

    def get_by_objective_asset(
        self,
        objective_asset: AssetSymbol | str,
    ) -> tuple[ObjectiveAssetPolicy, ...]:
        policy_ids = self._policy_ids_by_objective_asset.get(
            _asset_key(objective_asset),
            set(),
        )
        return tuple(self._policies_by_id[key] for key in sorted(policy_ids))

    def get_by_reference_asset(
        self,
        reference_asset: AssetSymbol | str,
    ) -> tuple[ObjectiveAssetPolicy, ...]:
        policy_ids = self._policy_ids_by_reference_asset.get(
            _asset_key(reference_asset),
            set(),
        )
        return tuple(self._policies_by_id[key] for key in sorted(policy_ids))


def _asset_key(value: AssetSymbol | str) -> str:
    return str(value if isinstance(value, AssetSymbol) else AssetSymbol(value))
