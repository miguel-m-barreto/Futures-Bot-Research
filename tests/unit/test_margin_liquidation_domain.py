from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from pydantic import ValidationError

from futures_bot.domain.margin_liquidation import (
    LiquidationModelKind,
    MarginLiquidationCompatibility,
    MarginLiquidationDecisionReason,
    MarginLiquidationPolicy,
    MarginLiquidationReadinessDecision,
    MarginLiquidationRuleSnapshot,
    MarginLiquidationSourceHealth,
    MarginLiquidationSourceKind,
    MarginLiquidationSourceTrust,
    MarginMode,
    deterministic_margin_liquidation_policy_id,
    deterministic_margin_liquidation_readiness_decision_id,
    deterministic_margin_liquidation_rule_snapshot_id,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _snapshot(**overrides: object) -> MarginLiquidationRuleSnapshot:
    values = {
        "venue_id": "kucoin",
        "instrument_id": "BTCUSDTM",
        "margin_mode": MarginMode.ISOLATED,
        "collateral_asset": "USDT",
        "margin_asset": "USDT",
        "settlement_asset": "USDT",
        "initial_margin_rate": Decimal("0.01"),
        "maintenance_margin_rate": Decimal("0.005"),
        "liquidation_fee_rate": Decimal("0.002"),
        "max_leverage": Decimal("100"),
        "liquidation_model_kind": LiquidationModelKind.VENUE_FORMULA,
        "risk_tier_id": "tier-1",
        "notional_floor": Decimal("0"),
        "notional_ceiling": Decimal("100000"),
        "observed_at": NOW,
        "captured_at": NOW,
        "source_kind": MarginLiquidationSourceKind.VENUE_RISK_BRACKET,
        "source_trust": MarginLiquidationSourceTrust.OFFICIAL,
        "source_health": MarginLiquidationSourceHealth.HEALTHY,
        "source_record_id": "source-record-1",
        "metadata": {},
    }
    values.update(overrides)
    return MarginLiquidationRuleSnapshot(**values)


def _policy(**overrides: object) -> MarginLiquidationPolicy:
    values = {
        "max_snapshot_age": 60_000,
        "require_source_record": True,
        "allowed_source_kinds": (MarginLiquidationSourceKind.VENUE_RISK_BRACKET,),
        "allowed_source_trust": (MarginLiquidationSourceTrust.OFFICIAL,),
        "allowed_source_health": (MarginLiquidationSourceHealth.HEALTHY,),
        "allowed_margin_modes": (MarginMode.ISOLATED,),
        "require_initial_margin": True,
        "require_maintenance_margin": True,
        "require_liquidation_fee": True,
        "require_max_leverage": True,
        "require_liquidation_model": True,
        "require_risk_tier": True,
        "require_collateral_asset_match": True,
        "require_margin_asset_match": True,
        "require_settlement_asset_match": True,
        "metadata": {},
    }
    values.update(overrides)
    return MarginLiquidationPolicy(**values)


def _decision(**overrides: object) -> MarginLiquidationReadinessDecision:
    policy = _policy()
    if policy.policy_id is None:
        raise AssertionError("policy_id was not assigned")
    values = {
        "policy_id": policy.policy_id,
        "venue_id": "kucoin",
        "instrument_id": "BTCUSDTM",
        "margin_mode": MarginMode.ISOLATED,
        "collateral_asset": "USDT",
        "margin_asset": "USDT",
        "settlement_asset": "USDT",
        "ready": True,
        "reason": MarginLiquidationDecisionReason.READY,
        "compatibility": MarginLiquidationCompatibility.DIRECT_MATCH,
        "checked_at": NOW,
        "details": {},
    }
    values.update(overrides)
    return MarginLiquidationReadinessDecision(**values)


def test_margin_liquidation_ids_are_deterministic() -> None:
    assert _snapshot().snapshot_id == _snapshot().snapshot_id
    assert _policy().policy_id == _policy().policy_id
    assert _decision().decision_id == _decision().decision_id


def test_policy_id_includes_allowed_source_kinds() -> None:
    official = _policy(
        allowed_source_kinds=(MarginLiquidationSourceKind.VENUE_RISK_BRACKET,),
    )
    test_fixture = _policy(
        allowed_source_kinds=(MarginLiquidationSourceKind.TEST_FIXTURE,),
        allowed_source_trust=(MarginLiquidationSourceTrust.TEST_ONLY,),
    )

    assert official.policy_id != test_fixture.policy_id


def test_snapshot_rejects_invalid_rates_and_notional_bounds() -> None:
    with pytest.raises(ValidationError, match="positive"):
        _snapshot(initial_margin_rate=Decimal("0"))
    with pytest.raises(ValidationError, match="positive"):
        _snapshot(max_leverage=Decimal("0"))
    with pytest.raises(ValidationError, match=">= 0"):
        _snapshot(liquidation_fee_rate=Decimal("-0.01"))
    with pytest.raises(ValidationError, match="notional_floor"):
        _snapshot(notional_floor=Decimal("10"), notional_ceiling=Decimal("1"))


def test_policy_rejects_invalid_gate_configuration() -> None:
    with pytest.raises(ValidationError, match="max_snapshot_age"):
        _policy(max_snapshot_age=0)
    with pytest.raises(ValidationError, match="allowed_source_kinds"):
        _policy(allowed_source_kinds=())
    with pytest.raises(ValidationError, match="UNKNOWN"):
        _policy(allowed_source_kinds=(MarginLiquidationSourceKind.UNKNOWN,))
    with pytest.raises(ValidationError, match="allowed_margin_modes"):
        _policy(allowed_margin_modes=())
    with pytest.raises(ValidationError, match="UNKNOWN"):
        _policy(allowed_margin_modes=(MarginMode.UNKNOWN,))


def test_strict_official_source_kind_contract() -> None:
    policy = MarginLiquidationPolicy.strict_official(metadata={})

    assert policy.allowed_source_kinds == (
        MarginLiquidationSourceKind.MANUAL_REVIEWED_RULE,
        MarginLiquidationSourceKind.VENUE_ACCOUNT_CONFIG,
        MarginLiquidationSourceKind.VENUE_RISK_BRACKET,
        MarginLiquidationSourceKind.VENUE_RULES,
    )
    assert MarginLiquidationSourceKind.UNKNOWN not in policy.allowed_source_kinds
    assert MarginLiquidationSourceKind.TEST_FIXTURE not in policy.allowed_source_kinds


def test_metadata_and_details_are_deeply_immutable_and_id_stable() -> None:
    snapshot = _snapshot(metadata={"nested": {"x": [1]}})
    policy = _policy(metadata={"nested": {"x": [1]}})
    decision = _decision(details={"nested": {"x": [1]}})

    with pytest.raises(TypeError):
        cast(Any, snapshot.metadata)["nested"]["new"] = True
    with pytest.raises(TypeError):
        cast(Any, policy.metadata)["nested"]["new"] = True
    with pytest.raises(TypeError):
        cast(Any, decision.details)["nested"]["new"] = True
    with pytest.raises(AttributeError):
        cast(Any, snapshot.metadata)["nested"]["x"].append(2)

    assert deterministic_margin_liquidation_rule_snapshot_id(snapshot) == snapshot.snapshot_id
    assert deterministic_margin_liquidation_policy_id(policy) == policy.policy_id
    assert (
        deterministic_margin_liquidation_readiness_decision_id(decision)
        == decision.decision_id
    )


def test_model_dump_json_thaws_metadata_and_details() -> None:
    cases = (
        (_snapshot(metadata={"nested": {"x": [1]}}).model_dump(mode="json"), "metadata"),
        (_policy(metadata={"nested": {"x": [1]}}).model_dump(mode="json"), "metadata"),
        (_decision(details={"nested": {"x": [1]}}).model_dump(mode="json"), "details"),
    )

    for dumped, field_name in cases:
        assert dumped[field_name] == {"nested": {"x": [1]}}
        assert isinstance(dumped[field_name]["nested"]["x"], list)


def test_decision_ready_reason_consistency() -> None:
    with pytest.raises(ValidationError, match="READY"):
        _decision(ready=True, reason=MarginLiquidationDecisionReason.NOT_READY)
    with pytest.raises(ValidationError, match="READY"):
        _decision(ready=False, reason=MarginLiquidationDecisionReason.READY)
    with pytest.raises(ValidationError, match="compatibility"):
        _decision(compatibility=MarginLiquidationCompatibility.NOT_COMPATIBLE)


def test_no_stablecoin_or_crypto_equivalence_assumptions() -> None:
    first = _snapshot(collateral_asset="USDT", margin_asset="USDT")
    second = _snapshot(collateral_asset="USDC", margin_asset="USDC")

    assert first.snapshot_id != second.snapshot_id
