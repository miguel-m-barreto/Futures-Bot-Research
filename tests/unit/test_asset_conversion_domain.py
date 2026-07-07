from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from pydantic import ValidationError

from futures_bot.domain.asset_conversion import (
    AssetConversionCompatibility,
    AssetConversionDecisionReason,
    AssetConversionEvidenceKind,
    AssetConversionPolicy,
    AssetConversionRateSnapshot,
    AssetConversionReadinessDecision,
    AssetConversionSourceHealth,
    AssetConversionSourceKind,
    AssetConversionSourceTrust,
    deterministic_asset_conversion_policy_id,
    deterministic_asset_conversion_rate_snapshot_id,
    deterministic_asset_conversion_readiness_decision_id,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _snapshot(**overrides: object) -> AssetConversionRateSnapshot:
    values = {
        "from_asset": "BTC",
        "to_asset": "USDT",
        "rate": Decimal("50000"),
        "observed_at": NOW,
        "captured_at": NOW,
        "source_kind": AssetConversionSourceKind.ORACLE_PRICE,
        "source_trust": AssetConversionSourceTrust.OFFICIAL,
        "source_health": AssetConversionSourceHealth.HEALTHY,
        "evidence_kind": AssetConversionEvidenceKind.DIRECT_PAIR_RATE,
        "source_record_id": "source-record-1",
        "metadata": {},
    }
    values.update(overrides)
    return AssetConversionRateSnapshot(**values)


def _policy(**overrides: object) -> AssetConversionPolicy:
    values = {
        "max_rate_age": 60_000,
        "require_source_record": True,
        "allowed_source_trust": (AssetConversionSourceTrust.OFFICIAL,),
        "allowed_source_health": (AssetConversionSourceHealth.HEALTHY,),
        "allow_same_asset_direct_match": False,
        "allow_inverse_rate": False,
        "allow_triangulation": False,
        "require_bid_ask": False,
        "metadata": {},
    }
    values.update(overrides)
    return AssetConversionPolicy(**values)


def _decision(**overrides: object) -> AssetConversionReadinessDecision:
    policy = _policy()
    if policy.policy_id is None:
        raise AssertionError("policy_id was not assigned")
    values = {
        "policy_id": policy.policy_id,
        "from_asset": "BTC",
        "to_asset": "USDT",
        "ready": True,
        "reason": AssetConversionDecisionReason.READY,
        "compatibility": AssetConversionCompatibility.DIRECT_RATE,
        "checked_at": NOW,
        "effective_rate": Decimal("50000"),
        "details": {},
    }
    values.update(overrides)
    return AssetConversionReadinessDecision(**values)


def test_conversion_snapshot_deterministic_id() -> None:
    assert _snapshot().snapshot_id == _snapshot().snapshot_id


def test_policy_deterministic_id() -> None:
    assert _policy().policy_id == _policy().policy_id


def test_decision_deterministic_id() -> None:
    assert _decision().decision_id == _decision().decision_id


def test_snapshot_rejects_same_asset_pair() -> None:
    with pytest.raises(ValidationError, match="different assets"):
        _snapshot(from_asset="USDT", to_asset="USDT")


def test_snapshot_rejects_non_positive_rate_and_negative_spread() -> None:
    with pytest.raises(ValidationError, match="positive"):
        _snapshot(rate=Decimal("0"))
    with pytest.raises(ValidationError, match="spread_bps"):
        _snapshot(spread_bps=Decimal("-1"))


def test_policy_requires_positive_max_rate_age() -> None:
    with pytest.raises(ValidationError, match="max_rate_age"):
        _policy(max_rate_age=0)


def test_metadata_and_details_are_deeply_immutable_and_id_stable() -> None:
    snapshot = _snapshot(metadata={"nested": {"x": [1]}})
    policy = _policy(metadata={"nested": {"x": [1]}})
    decision = _decision(details={"nested": {"x": [1]}})
    old_snapshot_id = snapshot.snapshot_id
    old_policy_id = policy.policy_id
    old_decision_id = decision.decision_id

    with pytest.raises(TypeError):
        cast(Any, snapshot.metadata)["nested"]["new"] = True
    with pytest.raises(TypeError):
        cast(Any, policy.metadata)["nested"]["new"] = True
    with pytest.raises(TypeError):
        cast(Any, decision.details)["nested"]["new"] = True
    with pytest.raises(AttributeError):
        cast(Any, snapshot.metadata)["nested"]["x"].append(2)

    assert deterministic_asset_conversion_rate_snapshot_id(snapshot) == old_snapshot_id
    assert deterministic_asset_conversion_policy_id(policy) == old_policy_id
    assert deterministic_asset_conversion_readiness_decision_id(decision) == old_decision_id


def test_json_mode_dump_thaws_metadata_and_details() -> None:
    snapshot_dump = _snapshot(metadata={"nested": {"x": [1]}}).model_dump(mode="json")
    policy_dump = _policy(metadata={"nested": {"x": [1]}}).model_dump(mode="json")
    decision_dump = _decision(details={"nested": {"x": [1]}}).model_dump(mode="json")

    for dumped, field_name in (
        (snapshot_dump, "metadata"),
        (policy_dump, "metadata"),
        (decision_dump, "details"),
    ):
        assert dumped[field_name] == {"nested": {"x": [1]}}
        assert isinstance(dumped[field_name], dict)
        assert isinstance(dumped[field_name]["nested"]["x"], list)


def test_decision_ready_reason_consistency() -> None:
    with pytest.raises(ValidationError, match="READY"):
        _decision(ready=True, reason=AssetConversionDecisionReason.NOT_READY)
    with pytest.raises(ValidationError, match="READY"):
        _decision(ready=False, reason=AssetConversionDecisionReason.READY)
    with pytest.raises(ValidationError, match="compatible"):
        _decision(compatibility=AssetConversionCompatibility.NOT_COMPATIBLE)
