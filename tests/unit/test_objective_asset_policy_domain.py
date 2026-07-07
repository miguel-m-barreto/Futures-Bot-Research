from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from pydantic import ValidationError

from futures_bot.domain.ids import ObjectiveAssetPolicyId
from futures_bot.domain.objective_assets import (
    ObjectiveAssetCompatibility,
    ObjectiveAssetDecisionReason,
    ObjectiveAssetPolicy,
    ObjectiveAssetReadinessDecision,
    ObjectiveMeasurementMode,
    ObjectivePolicyKind,
    deterministic_objective_asset_policy_id,
    deterministic_objective_asset_readiness_decision_id,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _policy(**overrides: object) -> ObjectiveAssetPolicy:
    values = {
        "policy_kind": ObjectivePolicyKind.ACCUMULATE_ASSET,
        "objective_asset": "USDT",
        "measurement_mode": ObjectiveMeasurementMode.NATIVE_ASSET_UNITS,
        "valuation_required": False,
        "conversion_required": False,
        "collateral_adjustment_required": False,
        "allow_direct_asset_match": True,
        "allow_reference_asset_measurement": False,
        "allow_collateral_adjusted_measurement": False,
        "metadata": {},
    }
    values.update(overrides)
    return ObjectiveAssetPolicy(**values)


def _decision(**overrides: object) -> ObjectiveAssetReadinessDecision:
    policy = ObjectiveAssetPolicy.accumulate("USDT")
    if policy.policy_id is None:
        raise AssertionError("policy_id was not assigned")
    values = {
        "policy_id": policy.policy_id,
        "objective_asset": "USDT",
        "pnl_asset": "USDT",
        "ready": True,
        "reason": ObjectiveAssetDecisionReason.READY,
        "compatibility": ObjectiveAssetCompatibility.DIRECT_MATCH,
        "checked_at": NOW,
        "details": {},
    }
    values.update(overrides)
    return ObjectiveAssetReadinessDecision(**values)


def test_objective_asset_policy_deterministic_id() -> None:
    assert ObjectiveAssetPolicy.accumulate("USDT").policy_id == (
        ObjectiveAssetPolicy.accumulate("USDT").policy_id
    )


@pytest.mark.parametrize("asset", ("USDT", "BTC", "ETH"))
def test_policy_accepts_generic_objective_assets(asset: str) -> None:
    policy = ObjectiveAssetPolicy.accumulate(asset)

    assert str(policy.objective_asset) == asset


def test_accumulate_asset_requires_objective_asset() -> None:
    with pytest.raises(ValidationError, match="objective_asset"):
        _policy(objective_asset=None)


def test_maximize_reference_value_requires_reference_asset() -> None:
    with pytest.raises(ValidationError, match="reference_asset"):
        _policy(
            policy_kind=ObjectivePolicyKind.MAXIMIZE_REFERENCE_VALUE,
            objective_asset=None,
            reference_asset=None,
            measurement_mode=ObjectiveMeasurementMode.REFERENCE_ASSET_VALUE,
            valuation_required=True,
            allow_reference_asset_measurement=True,
        )


def test_policy_metadata_deeply_immutable_and_id_stable() -> None:
    policy = _policy(metadata={"nested": {"x": [1]}})
    old_id = policy.policy_id

    with pytest.raises(TypeError):
        cast(Any, policy.metadata)["nested"]["new"] = True
    with pytest.raises(AttributeError):
        cast(Any, policy.metadata)["nested"]["x"].append(2)

    assert deterministic_objective_asset_policy_id(policy) == old_id


def test_factory_helpers_accept_metadata_and_deep_freeze_it() -> None:
    policies = (
        ObjectiveAssetPolicy.accumulate("BTC", metadata={"nested": {"x": [1]}}),
        ObjectiveAssetPolicy.maximize_reference_value(
            "USD",
            metadata={"nested": {"x": [1]}},
        ),
        ObjectiveAssetPolicy.preserve_collateral_asset(
            "ETH",
            metadata={"nested": {"x": [1]}},
        ),
    )

    for policy in policies:
        old_id = policy.policy_id

        with pytest.raises(TypeError):
            cast(Any, policy.metadata)["nested"]["new"] = True
        with pytest.raises(AttributeError):
            cast(Any, policy.metadata)["nested"]["x"].append(2)

        assert deterministic_objective_asset_policy_id(policy) == old_id


def test_policy_model_dump_json_thaws_metadata() -> None:
    dumped = _policy(metadata={"nested": {"x": [1]}}).model_dump(mode="json")

    assert dumped["metadata"] == {"nested": {"x": [1]}}
    assert isinstance(dumped["metadata"], dict)
    assert isinstance(dumped["metadata"]["nested"], dict)
    assert isinstance(dumped["metadata"]["nested"]["x"], list)


def test_factory_metadata_model_dump_json_thaws_metadata() -> None:
    dumped = ObjectiveAssetPolicy.accumulate(
        "BTC",
        metadata={"nested": {"x": [1]}},
    ).model_dump(mode="json")

    assert dumped["metadata"] == {"nested": {"x": [1]}}
    assert isinstance(dumped["metadata"], dict)
    assert isinstance(dumped["metadata"]["nested"], dict)
    assert isinstance(dumped["metadata"]["nested"]["x"], list)


def test_policy_rejects_non_json_metadata() -> None:
    with pytest.raises(ValidationError, match="JSON-compatible"):
        _policy(metadata={"bad": object()})


def test_decision_ready_reason_consistency() -> None:
    with pytest.raises(ValidationError, match="READY"):
        _decision(ready=True, reason=ObjectiveAssetDecisionReason.NOT_READY)
    with pytest.raises(ValidationError, match="READY"):
        _decision(ready=False, reason=ObjectiveAssetDecisionReason.READY)


def test_decision_ready_requires_compatible_assets() -> None:
    with pytest.raises(ValidationError, match="compatible"):
        _decision(compatibility=ObjectiveAssetCompatibility.NOT_COMPATIBLE)


def test_decision_details_deeply_immutable_and_id_stable() -> None:
    decision = _decision(details={"nested": {"x": [1]}})
    old_id = decision.decision_id

    with pytest.raises(TypeError):
        cast(Any, decision.details)["nested"]["new"] = True
    with pytest.raises(AttributeError):
        cast(Any, decision.details)["nested"]["x"].append(2)

    assert deterministic_objective_asset_readiness_decision_id(decision) == old_id


def test_decision_model_dump_json_thaws_details() -> None:
    dumped = _decision(details={"nested": {"x": [1]}}).model_dump(mode="json")

    assert dumped["details"] == {"nested": {"x": [1]}}
    assert isinstance(dumped["details"], dict)
    assert isinstance(dumped["details"]["nested"], dict)
    assert isinstance(dumped["details"]["nested"]["x"], list)


def test_decision_preserves_policy_id_value_object() -> None:
    policy_id = ObjectiveAssetPolicyId("objective-asset-policy:unit-test")
    decision = _decision(policy_id=policy_id)

    assert decision.policy_id == policy_id
