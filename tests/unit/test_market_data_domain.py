from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from pydantic import ValidationError

from futures_bot.domain.market_data import (
    MarketDataCompatibility,
    MarketDataContinuityStatus,
    MarketDataObservationKind,
    MarketDataObservationSnapshot,
    MarketDataReadinessDecision,
    MarketDataReadinessPolicy,
    MarketDataReadinessReason,
    MarketDataSourceHealth,
    MarketDataSourceKind,
    MarketDataSourceTrust,
    deterministic_market_data_observation_snapshot_id,
    deterministic_market_data_readiness_decision_id,
    deterministic_market_data_readiness_policy_id,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _snapshot(**overrides: object) -> MarketDataObservationSnapshot:
    values = {
        "venue_id": "kucoin",
        "instrument_id": "BTCUSDTM",
        "observation_kind": MarketDataObservationKind.BEST_BID_ASK,
        "best_bid_price": Decimal("100"),
        "best_ask_price": Decimal("101"),
        "mark_price": Decimal("100.5"),
        "index_price": Decimal("100.4"),
        "last_trade_price": Decimal("100.6"),
        "depth_reference_asset": "USDT",
        "depth_notional": Decimal("1000"),
        "spread_bps": Decimal("10"),
        "sequence_number": 101,
        "previous_sequence_number": 100,
        "continuity_status": MarketDataContinuityStatus.CONTINUOUS,
        "observed_at": NOW,
        "captured_at": NOW,
        "source_kind": MarketDataSourceKind.VENUE_PUBLIC_MARKET_DATA,
        "source_trust": MarketDataSourceTrust.OFFICIAL,
        "source_health": MarketDataSourceHealth.HEALTHY,
        "source_record_id": "source-record-1",
        "metadata": {},
    }
    values.update(overrides)
    return MarketDataObservationSnapshot(**values)


def _policy(**overrides: object) -> MarketDataReadinessPolicy:
    values = {
        "max_observation_age": 5_000,
        "require_source_record": True,
        "allowed_source_kinds": (MarketDataSourceKind.VENUE_PUBLIC_MARKET_DATA,),
        "allowed_source_trust": (MarketDataSourceTrust.OFFICIAL,),
        "allowed_source_health": (MarketDataSourceHealth.HEALTHY,),
        "allowed_observation_kinds": (MarketDataObservationKind.BEST_BID_ASK,),
        "allowed_continuity_statuses": (MarketDataContinuityStatus.CONTINUOUS,),
        "require_sequence": True,
        "require_continuous_sequence": True,
        "require_best_bid": True,
        "require_best_ask": True,
        "require_bid_ask_not_crossed": True,
        "require_mark_price": False,
        "require_index_price": False,
        "require_last_trade_price": False,
        "require_depth_notional": False,
        "require_depth_reference_asset_match": False,
        "require_spread_bps": True,
        "metadata": {},
    }
    values.update(overrides)
    return MarketDataReadinessPolicy(**values)


def _decision(**overrides: object) -> MarketDataReadinessDecision:
    policy = _policy()
    if policy.policy_id is None:
        raise AssertionError("policy_id was not assigned")
    values = {
        "policy_id": policy.policy_id,
        "venue_id": "kucoin",
        "instrument_id": "BTCUSDTM",
        "observation_kind": MarketDataObservationKind.BEST_BID_ASK,
        "depth_reference_asset": "USDT",
        "ready": True,
        "reason": MarketDataReadinessReason.READY,
        "compatibility": MarketDataCompatibility.DIRECT_MATCH,
        "checked_at": NOW,
        "details": {},
    }
    values.update(overrides)
    return MarketDataReadinessDecision(**values)


def test_market_data_ids_are_deterministic() -> None:
    assert _snapshot().snapshot_id == _snapshot().snapshot_id
    assert _policy().policy_id == _policy().policy_id
    assert _decision().decision_id == _decision().decision_id


def test_snapshot_rejects_invalid_prices_depth_spread_and_sequence() -> None:
    for field_name in (
        "best_bid_price",
        "best_ask_price",
        "mark_price",
        "index_price",
        "last_trade_price",
    ):
        with pytest.raises(ValidationError, match="positive"):
            _snapshot(**{field_name: Decimal("0")})
    with pytest.raises(ValidationError, match="depth_notional"):
        _snapshot(depth_notional=Decimal("0"))
    with pytest.raises(ValidationError, match="spread_bps"):
        _snapshot(spread_bps=Decimal("-1"))
    with pytest.raises(ValidationError, match="sequence values"):
        _snapshot(sequence_number=-1)
    with pytest.raises(ValidationError, match="sequence_number"):
        _snapshot(sequence_number=1, previous_sequence_number=2)


def test_policy_rejects_invalid_gate_configuration() -> None:
    with pytest.raises(ValidationError, match="max_observation_age"):
        _policy(max_observation_age=0)
    with pytest.raises(ValidationError, match="allowed_source_kinds"):
        _policy(allowed_source_kinds=())
    with pytest.raises(ValidationError, match="UNKNOWN source"):
        _policy(allowed_source_kinds=(MarketDataSourceKind.UNKNOWN,))
    with pytest.raises(ValidationError, match="allowed_source_trust"):
        _policy(allowed_source_trust=())
    with pytest.raises(ValidationError, match="allowed_source_health"):
        _policy(allowed_source_health=())
    with pytest.raises(ValidationError, match="allowed_observation_kinds"):
        _policy(allowed_observation_kinds=())
    with pytest.raises(ValidationError, match="UNKNOWN observation"):
        _policy(allowed_observation_kinds=(MarketDataObservationKind.UNKNOWN,))
    with pytest.raises(ValidationError, match="allowed_continuity_statuses"):
        _policy(allowed_continuity_statuses=())
    with pytest.raises(ValidationError, match="UNKNOWN continuity"):
        _policy(allowed_continuity_statuses=(MarketDataContinuityStatus.UNKNOWN,))
    with pytest.raises(ValidationError, match="max_spread_bps"):
        _policy(max_spread_bps=Decimal("-1"))


def test_strict_official_and_research_fixture_source_contracts() -> None:
    strict = MarketDataReadinessPolicy.strict_official(metadata={})
    fixture = MarketDataReadinessPolicy.research_fixture(metadata={})

    assert MarketDataSourceKind.UNKNOWN not in strict.allowed_source_kinds
    assert MarketDataSourceKind.TEST_FIXTURE not in strict.allowed_source_kinds
    assert MarketDataObservationKind.UNKNOWN not in strict.allowed_observation_kinds
    assert MarketDataContinuityStatus.UNKNOWN not in strict.allowed_continuity_statuses
    assert fixture.allowed_source_kinds == (MarketDataSourceKind.TEST_FIXTURE,)
    assert fixture.allowed_source_trust == (MarketDataSourceTrust.TEST_ONLY,)


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

    assert deterministic_market_data_observation_snapshot_id(snapshot) == snapshot.snapshot_id
    assert deterministic_market_data_readiness_policy_id(policy) == policy.policy_id
    assert deterministic_market_data_readiness_decision_id(decision) == decision.decision_id


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
        _decision(ready=True, reason=MarketDataReadinessReason.NOT_READY)
    with pytest.raises(ValidationError, match="READY"):
        _decision(ready=False, reason=MarketDataReadinessReason.READY)
    with pytest.raises(ValidationError, match="compatibility"):
        _decision(compatibility=MarketDataCompatibility.NOT_COMPATIBLE)


def test_no_stablecoin_equivalence_or_price_substitution_assumptions() -> None:
    usdt = _snapshot(depth_reference_asset="USDT")
    usd = _snapshot(depth_reference_asset="USD")
    mark = _snapshot(observation_kind=MarketDataObservationKind.MARK_PRICE)
    last = _snapshot(observation_kind=MarketDataObservationKind.LAST_TRADE)

    assert usdt.snapshot_id != usd.snapshot_id
    assert mark.snapshot_id != last.snapshot_id
