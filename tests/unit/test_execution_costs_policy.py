from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from futures_bot.domain.execution_costs import (
    DepthModelKind,
    ExecutionCostDecisionReason,
    ExecutionCostPolicy,
    ExecutionCostRuleSnapshot,
    ExecutionCostSourceHealth,
    ExecutionCostSourceKind,
    ExecutionCostSourceTrust,
    FeeModelKind,
    FundingModelKind,
)
from futures_bot.execution_costs.policies import evaluate_execution_cost_readiness

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
        "observed_at": NOW - timedelta(seconds=1),
        "captured_at": NOW - timedelta(seconds=1),
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
        "allowed_source_kinds": (
            ExecutionCostSourceKind.VENUE_FEE_SCHEDULE,
            ExecutionCostSourceKind.VENUE_FUNDING_RULES,
            ExecutionCostSourceKind.VENUE_DEPTH_RULES,
            ExecutionCostSourceKind.MANUAL_REVIEWED_RULE,
        ),
        "allowed_source_trust": (ExecutionCostSourceTrust.OFFICIAL,),
        "allowed_source_health": (ExecutionCostSourceHealth.HEALTHY,),
        "allowed_fee_models": (
            FeeModelKind.MAKER_TAKER_BPS,
            FeeModelKind.INSTRUMENT_SPECIFIC,
        ),
        "allowed_funding_models": (
            FundingModelKind.PERIODIC_RATE,
            FundingModelKind.VENUE_FUNDING_SCHEDULE,
        ),
        "allowed_depth_models": (
            DepthModelKind.ORDER_BOOK_DEPTH,
            DepthModelKind.DEPTH_CURVE,
        ),
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


def _evaluate(  # noqa: PLR0913
    *,
    snapshot: ExecutionCostRuleSnapshot | None = None,
    policy: ExecutionCostPolicy | None = None,
    venue_id: str = "kucoin",
    instrument_id: str = "BTCUSDTM",
    fee_asset: str = "USDT",
    funding_asset: str = "USDT",
    depth_reference_asset: str = "USDT",
):
    return evaluate_execution_cost_readiness(
        policy=_policy() if policy is None else policy,
        checked_at=NOW,
        snapshot=_snapshot() if snapshot is None else snapshot,
        venue_id=venue_id,
        instrument_id=instrument_id,
        fee_asset=fee_asset,
        funding_asset=funding_asset,
        depth_reference_asset=depth_reference_asset,
    )


def test_strict_official_complete_snapshot_ready() -> None:
    decision = _evaluate(policy=ExecutionCostPolicy.strict_official(metadata={}))

    assert decision.ready
    assert decision.reason is ExecutionCostDecisionReason.READY


def test_missing_future_and_stale_snapshot_reject() -> None:
    missing = evaluate_execution_cost_readiness(
        policy=_policy(),
        checked_at=NOW,
        snapshot=None,
    )
    future_observed = _evaluate(
        snapshot=_snapshot(
            observed_at=NOW + timedelta(milliseconds=1),
            captured_at=NOW + timedelta(milliseconds=1),
        ),
    )
    future_captured = _evaluate(
        snapshot=_snapshot(captured_at=NOW + timedelta(milliseconds=1)),
    )
    stale = _evaluate(
        policy=_policy(max_snapshot_age=500),
        snapshot=_snapshot(observed_at=NOW - timedelta(seconds=2)),
    )

    assert missing.reason is ExecutionCostDecisionReason.SNAPSHOT_MISSING
    assert future_observed.reason is ExecutionCostDecisionReason.SNAPSHOT_FUTURE_DATED
    assert future_captured.reason is ExecutionCostDecisionReason.SNAPSHOT_FUTURE_DATED
    assert stale.reason is ExecutionCostDecisionReason.SNAPSHOT_STALE


def test_source_gates_reject() -> None:
    unknown_kind = _evaluate(
        snapshot=_snapshot(source_kind=ExecutionCostSourceKind.UNKNOWN),
    )
    test_fixture_kind = _evaluate(
        policy=ExecutionCostPolicy.strict_official(metadata={}),
        snapshot=_snapshot(source_kind=ExecutionCostSourceKind.TEST_FIXTURE),
    )
    untrusted = _evaluate(
        snapshot=_snapshot(source_trust=ExecutionCostSourceTrust.UNTRUSTED),
    )
    unhealthy = _evaluate(
        snapshot=_snapshot(source_health=ExecutionCostSourceHealth.UNHEALTHY),
    )
    missing_record = _evaluate(snapshot=_snapshot(source_record_id=None))

    assert unknown_kind.reason is ExecutionCostDecisionReason.SOURCE_KIND_UNKNOWN
    assert test_fixture_kind.reason is ExecutionCostDecisionReason.SOURCE_KIND_UNSUPPORTED
    assert untrusted.reason is ExecutionCostDecisionReason.SOURCE_UNTRUSTED
    assert unhealthy.reason is ExecutionCostDecisionReason.SOURCE_UNHEALTHY
    assert missing_record.reason is ExecutionCostDecisionReason.SOURCE_RECORD_REQUIRED


def test_scope_gates_reject() -> None:
    venue_mismatch = _evaluate(venue_id="binance")
    instrument_mismatch = _evaluate(instrument_id="ETHUSDT")

    assert venue_mismatch.reason is ExecutionCostDecisionReason.VENUE_MISMATCH
    assert instrument_mismatch.reason is ExecutionCostDecisionReason.INSTRUMENT_MISMATCH


def test_fee_model_and_required_fee_gates_reject() -> None:
    assert _evaluate(snapshot=_snapshot(fee_model_kind=FeeModelKind.UNKNOWN)).reason is (
        ExecutionCostDecisionReason.FEE_MODEL_UNKNOWN
    )
    assert _evaluate(
        snapshot=_snapshot(fee_model_kind=FeeModelKind.NOT_PROVIDED),
    ).reason is ExecutionCostDecisionReason.FEE_MODEL_MISSING
    assert _evaluate(snapshot=_snapshot(fee_model_kind=FeeModelKind.FLAT_BPS)).reason is (
        ExecutionCostDecisionReason.FEE_MODEL_UNSUPPORTED
    )
    assert _evaluate(snapshot=_snapshot(maker_fee_rate=None)).reason is (
        ExecutionCostDecisionReason.MAKER_FEE_MISSING
    )
    assert _evaluate(snapshot=_snapshot(taker_fee_rate=None)).reason is (
        ExecutionCostDecisionReason.TAKER_FEE_MISSING
    )
    assert _evaluate(fee_asset="USD").reason is (
        ExecutionCostDecisionReason.FEE_ASSET_MISMATCH
    )


def test_funding_model_and_required_funding_gates_reject() -> None:
    assert _evaluate(
        snapshot=_snapshot(funding_model_kind=FundingModelKind.UNKNOWN),
    ).reason is ExecutionCostDecisionReason.FUNDING_MODEL_UNKNOWN
    assert _evaluate(
        snapshot=_snapshot(funding_model_kind=FundingModelKind.NOT_PROVIDED),
    ).reason is ExecutionCostDecisionReason.FUNDING_MODEL_MISSING
    assert _evaluate(
        snapshot=_snapshot(funding_model_kind=FundingModelKind.NOT_APPLICABLE),
    ).reason is ExecutionCostDecisionReason.FUNDING_MODEL_UNSUPPORTED
    assert _evaluate(snapshot=_snapshot(funding_interval_ms=None)).reason is (
        ExecutionCostDecisionReason.FUNDING_INTERVAL_MISSING
    )
    assert _evaluate(funding_asset="USDC").reason is (
        ExecutionCostDecisionReason.FUNDING_ASSET_MISMATCH
    )


def test_depth_model_and_required_depth_gates_reject() -> None:
    assert _evaluate(
        snapshot=_snapshot(depth_model_kind=DepthModelKind.UNKNOWN),
    ).reason is ExecutionCostDecisionReason.DEPTH_MODEL_UNKNOWN
    assert _evaluate(
        snapshot=_snapshot(depth_model_kind=DepthModelKind.NOT_PROVIDED),
    ).reason is ExecutionCostDecisionReason.DEPTH_MODEL_MISSING
    assert _evaluate(
        snapshot=_snapshot(depth_model_kind=DepthModelKind.TOP_OF_BOOK_ONLY),
    ).reason is ExecutionCostDecisionReason.DEPTH_MODEL_UNSUPPORTED
    assert _evaluate(snapshot=_snapshot(min_depth_notional=None)).reason is (
        ExecutionCostDecisionReason.MIN_DEPTH_NOTIONAL_MISSING
    )
    assert _evaluate(snapshot=_snapshot(max_spread_bps=None)).reason is (
        ExecutionCostDecisionReason.MAX_SPREAD_MISSING
    )
    assert _evaluate(depth_reference_asset="USD").reason is (
        ExecutionCostDecisionReason.DEPTH_REFERENCE_ASSET_MISMATCH
    )


def test_no_implicit_asset_equivalence() -> None:
    usdt_usd = _evaluate(fee_asset="USD")
    usdc_usdt = _evaluate(funding_asset="USDC")
    btc_eth = _evaluate(
        snapshot=_snapshot(fee_asset="BTC", funding_asset="BTC"),
        fee_asset="ETH",
        funding_asset="ETH",
    )

    assert usdt_usd.reason is ExecutionCostDecisionReason.FEE_ASSET_MISMATCH
    assert usdc_usdt.reason is ExecutionCostDecisionReason.FUNDING_ASSET_MISMATCH
    assert btc_eth.reason is ExecutionCostDecisionReason.FEE_ASSET_MISMATCH


def test_other_readiness_decisions_are_not_execution_cost_snapshots() -> None:
    decision = evaluate_execution_cost_readiness(
        policy=_policy(),
        checked_at=NOW,
        snapshot=object(),  # type: ignore[arg-type]
    )

    assert not decision.ready
    assert decision.reason is ExecutionCostDecisionReason.SNAPSHOT_MISSING
