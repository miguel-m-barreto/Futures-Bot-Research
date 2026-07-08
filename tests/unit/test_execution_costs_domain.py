from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from pydantic import ValidationError

from futures_bot.domain.execution_costs import (
    DepthModelKind,
    ExecutionCostCompatibility,
    ExecutionCostDecisionReason,
    ExecutionCostPolicy,
    ExecutionCostReadinessDecision,
    ExecutionCostRuleSnapshot,
    ExecutionCostSourceHealth,
    ExecutionCostSourceKind,
    ExecutionCostSourceTrust,
    FeeModelKind,
    FundingModelKind,
    deterministic_execution_cost_policy_id,
    deterministic_execution_cost_readiness_decision_id,
    deterministic_execution_cost_rule_snapshot_id,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _snapshot(**overrides: object) -> ExecutionCostRuleSnapshot:
    values = {
        "venue_id": "kucoin",
        "instrument_id": "BTCUSDTM",
        "fee_asset": "USDT",
        "funding_asset": "USDT",
        "depth_reference_asset": "USDT",
        "fee_model_kind": FeeModelKind.MAKER_TAKER_BPS,
        "maker_fee_rate": Decimal("0.0002"),
        "taker_fee_rate": Decimal("0.0006"),
        "flat_fee_rate": None,
        "fee_tier_id": "tier-1",
        "funding_model_kind": FundingModelKind.PERIODIC_RATE,
        "funding_interval_ms": 28_800_000,
        "funding_rate_cap": Decimal("0.01"),
        "depth_model_kind": DepthModelKind.ORDER_BOOK_DEPTH,
        "min_depth_notional": Decimal("1000"),
        "max_spread_bps": Decimal("5"),
        "observed_at": NOW,
        "captured_at": NOW,
        "source_kind": ExecutionCostSourceKind.VENUE_FEE_SCHEDULE,
        "source_trust": ExecutionCostSourceTrust.OFFICIAL,
        "source_health": ExecutionCostSourceHealth.HEALTHY,
        "source_record_id": "source-record-1",
        "metadata": {},
    }
    values.update(overrides)
    return ExecutionCostRuleSnapshot(**values)


def _policy(**overrides: object) -> ExecutionCostPolicy:
    values = {
        "max_snapshot_age": 60_000,
        "require_source_record": True,
        "allowed_source_kinds": (ExecutionCostSourceKind.VENUE_FEE_SCHEDULE,),
        "allowed_source_trust": (ExecutionCostSourceTrust.OFFICIAL,),
        "allowed_source_health": (ExecutionCostSourceHealth.HEALTHY,),
        "allowed_fee_models": (FeeModelKind.MAKER_TAKER_BPS,),
        "allowed_funding_models": (FundingModelKind.PERIODIC_RATE,),
        "allowed_depth_models": (DepthModelKind.ORDER_BOOK_DEPTH,),
        "require_fee_model": True,
        "require_maker_fee": True,
        "require_taker_fee": True,
        "require_fee_asset_match": True,
        "require_funding_model": True,
        "require_funding_interval": True,
        "require_funding_asset_match": True,
        "require_depth_model": True,
        "require_min_depth_notional": True,
        "require_depth_reference_asset_match": True,
        "require_max_spread_bps": True,
        "metadata": {},
    }
    values.update(overrides)
    return ExecutionCostPolicy(**values)


def _decision(**overrides: object) -> ExecutionCostReadinessDecision:
    policy = _policy()
    if policy.policy_id is None:
        raise AssertionError("policy_id was not assigned")
    values = {
        "policy_id": policy.policy_id,
        "venue_id": "kucoin",
        "instrument_id": "BTCUSDTM",
        "fee_asset": "USDT",
        "funding_asset": "USDT",
        "depth_reference_asset": "USDT",
        "ready": True,
        "reason": ExecutionCostDecisionReason.READY,
        "compatibility": ExecutionCostCompatibility.DIRECT_MATCH,
        "checked_at": NOW,
        "details": {},
    }
    values.update(overrides)
    return ExecutionCostReadinessDecision(**values)


def test_execution_cost_ids_are_deterministic() -> None:
    assert _snapshot().snapshot_id == _snapshot().snapshot_id
    assert _policy().policy_id == _policy().policy_id
    assert _decision().decision_id == _decision().decision_id


def test_policy_id_includes_allowed_source_and_model_sets() -> None:
    first = _policy()
    second = _policy(
        allowed_source_kinds=(ExecutionCostSourceKind.MANUAL_REVIEWED_RULE,),
        allowed_fee_models=(FeeModelKind.INSTRUMENT_SPECIFIC,),
    )

    assert first.policy_id != second.policy_id


def test_snapshot_rejects_invalid_rates_intervals_and_depth() -> None:
    for field_name in (
        "maker_fee_rate",
        "taker_fee_rate",
        "flat_fee_rate",
        "funding_rate_cap",
        "max_spread_bps",
    ):
        with pytest.raises(ValidationError, match=">= 0"):
            _snapshot(**{field_name: Decimal("-0.01")})
    with pytest.raises(ValidationError, match="funding_interval_ms"):
        _snapshot(funding_interval_ms=0)
    with pytest.raises(ValidationError, match="min_depth_notional"):
        _snapshot(min_depth_notional=Decimal("0"))


def test_policy_rejects_invalid_gate_configuration() -> None:
    with pytest.raises(ValidationError, match="max_snapshot_age"):
        _policy(max_snapshot_age=0)
    with pytest.raises(ValidationError, match="allowed_source_kinds"):
        _policy(allowed_source_kinds=())
    with pytest.raises(ValidationError, match="UNKNOWN source"):
        _policy(allowed_source_kinds=(ExecutionCostSourceKind.UNKNOWN,))
    with pytest.raises(ValidationError, match="UNKNOWN fee"):
        _policy(allowed_fee_models=(FeeModelKind.UNKNOWN,))
    with pytest.raises(ValidationError, match="UNKNOWN funding"):
        _policy(allowed_funding_models=(FundingModelKind.UNKNOWN,))
    with pytest.raises(ValidationError, match="UNKNOWN depth"):
        _policy(allowed_depth_models=(DepthModelKind.UNKNOWN,))
    with pytest.raises(ValidationError, match="allowed_fee_models"):
        _policy(allowed_fee_models=())
    with pytest.raises(ValidationError, match="allowed_funding_models"):
        _policy(allowed_funding_models=())
    with pytest.raises(ValidationError, match="allowed_depth_models"):
        _policy(allowed_depth_models=())


def test_strict_official_and_research_fixture_source_kind_contracts() -> None:
    strict = ExecutionCostPolicy.strict_official(metadata={})
    fixture = ExecutionCostPolicy.research_fixture(metadata={})

    assert ExecutionCostSourceKind.UNKNOWN not in strict.allowed_source_kinds
    assert ExecutionCostSourceKind.TEST_FIXTURE not in strict.allowed_source_kinds
    assert fixture.allowed_source_kinds == (ExecutionCostSourceKind.TEST_FIXTURE,)
    assert fixture.allowed_source_trust == (ExecutionCostSourceTrust.TEST_ONLY,)


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

    assert deterministic_execution_cost_rule_snapshot_id(snapshot) == snapshot.snapshot_id
    assert deterministic_execution_cost_policy_id(policy) == policy.policy_id
    assert (
        deterministic_execution_cost_readiness_decision_id(decision)
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
        _decision(ready=True, reason=ExecutionCostDecisionReason.NOT_READY)
    with pytest.raises(ValidationError, match="READY"):
        _decision(ready=False, reason=ExecutionCostDecisionReason.READY)
    with pytest.raises(ValidationError, match="compatibility"):
        _decision(compatibility=ExecutionCostCompatibility.NOT_COMPATIBLE)


def test_no_stablecoin_or_crypto_equivalence_assumptions() -> None:
    usdt = _snapshot(fee_asset="USDT", funding_asset="USDT")
    usdc = _snapshot(fee_asset="USDC", funding_asset="USDC")
    usd = _snapshot(depth_reference_asset="USD")
    btc = _snapshot(fee_asset="BTC")

    assert usdt.snapshot_id != usdc.snapshot_id
    assert usdt.snapshot_id != usd.snapshot_id
    assert usdt.snapshot_id != btc.snapshot_id
