from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from futures_bot.domain.margin_liquidation import (
    LiquidationModelKind,
    MarginLiquidationDecisionReason,
    MarginLiquidationPolicy,
    MarginLiquidationRuleSnapshot,
    MarginLiquidationSourceHealth,
    MarginLiquidationSourceKind,
    MarginLiquidationSourceTrust,
    MarginMode,
)
from futures_bot.margin_liquidation.policies import (
    evaluate_margin_liquidation_readiness,
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
        "observed_at": NOW - timedelta(seconds=1),
        "captured_at": NOW - timedelta(seconds=1),
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
        "allowed_source_kinds": (
            MarginLiquidationSourceKind.VENUE_RULES,
            MarginLiquidationSourceKind.VENUE_RISK_BRACKET,
            MarginLiquidationSourceKind.MANUAL_REVIEWED_RULE,
        ),
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


def _evaluate(  # noqa: PLR0913
    *,
    snapshot: MarginLiquidationRuleSnapshot | None = None,
    policy: MarginLiquidationPolicy | None = None,
    venue_id: str = "kucoin",
    instrument_id: str = "BTCUSDTM",
    margin_mode: MarginMode = MarginMode.ISOLATED,
    collateral_asset: str = "USDT",
    margin_asset: str = "USDT",
    settlement_asset: str = "USDT",
):
    return evaluate_margin_liquidation_readiness(
        policy=_policy() if policy is None else policy,
        checked_at=NOW,
        snapshot=_snapshot() if snapshot is None else snapshot,
        venue_id=venue_id,
        instrument_id=instrument_id,
        margin_mode=margin_mode,
        collateral_asset=collateral_asset,
        margin_asset=margin_asset,
        settlement_asset=settlement_asset,
    )


def test_strict_official_isolated_snapshot_ready() -> None:
    decision = _evaluate()

    assert decision.ready
    assert decision.reason is MarginLiquidationDecisionReason.READY


def test_missing_future_and_stale_snapshot_reject() -> None:
    missing = evaluate_margin_liquidation_readiness(
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

    assert missing.reason is MarginLiquidationDecisionReason.SNAPSHOT_MISSING
    assert future_observed.reason is (
        MarginLiquidationDecisionReason.SNAPSHOT_FUTURE_DATED
    )
    assert future_captured.reason is (
        MarginLiquidationDecisionReason.SNAPSHOT_FUTURE_DATED
    )
    assert stale.reason is MarginLiquidationDecisionReason.SNAPSHOT_STALE


def test_source_gates_reject() -> None:
    unknown_kind = _evaluate(
        snapshot=_snapshot(source_kind=MarginLiquidationSourceKind.UNKNOWN),
    )
    test_fixture_kind = _evaluate(
        policy=MarginLiquidationPolicy.strict_official(metadata={}),
        snapshot=_snapshot(source_kind=MarginLiquidationSourceKind.TEST_FIXTURE),
    )
    untrusted = _evaluate(
        snapshot=_snapshot(source_trust=MarginLiquidationSourceTrust.UNTRUSTED),
    )
    unhealthy = _evaluate(
        snapshot=_snapshot(source_health=MarginLiquidationSourceHealth.UNHEALTHY),
    )
    missing_record = _evaluate(snapshot=_snapshot(source_record_id=None))

    assert unknown_kind.reason is MarginLiquidationDecisionReason.SOURCE_KIND_UNKNOWN
    assert test_fixture_kind.reason is (
        MarginLiquidationDecisionReason.SOURCE_KIND_UNSUPPORTED
    )
    assert untrusted.reason is MarginLiquidationDecisionReason.SOURCE_UNTRUSTED
    assert unhealthy.reason is MarginLiquidationDecisionReason.SOURCE_UNHEALTHY
    assert missing_record.reason is MarginLiquidationDecisionReason.SOURCE_RECORD_REQUIRED


def test_allowed_source_kinds_can_satisfy_readiness() -> None:
    venue_rules = _evaluate(
        snapshot=_snapshot(source_kind=MarginLiquidationSourceKind.VENUE_RULES),
    )
    manual_reviewed = _evaluate(
        snapshot=_snapshot(source_kind=MarginLiquidationSourceKind.MANUAL_REVIEWED_RULE),
    )

    assert venue_rules.ready
    assert venue_rules.reason is MarginLiquidationDecisionReason.READY
    assert manual_reviewed.ready
    assert manual_reviewed.reason is MarginLiquidationDecisionReason.READY


def test_margin_mode_and_scope_gates_reject() -> None:
    unknown = _evaluate(snapshot=_snapshot(margin_mode=MarginMode.UNKNOWN))
    unsupported = _evaluate(
        policy=_policy(allowed_margin_modes=(MarginMode.CROSS,)),
    )
    requested_mismatch = _evaluate(margin_mode=MarginMode.CROSS)
    venue_mismatch = _evaluate(venue_id="binance")
    instrument_mismatch = _evaluate(instrument_id="ETHUSDTM")

    assert unknown.reason is MarginLiquidationDecisionReason.MARGIN_MODE_UNKNOWN
    assert unsupported.reason is MarginLiquidationDecisionReason.MARGIN_MODE_UNSUPPORTED
    assert requested_mismatch.reason is (
        MarginLiquidationDecisionReason.MARGIN_MODE_UNSUPPORTED
    )
    assert venue_mismatch.reason is MarginLiquidationDecisionReason.VENUE_MISMATCH
    assert instrument_mismatch.reason is (
        MarginLiquidationDecisionReason.INSTRUMENT_MISMATCH
    )


def test_required_field_gates_reject() -> None:
    assert _evaluate(snapshot=_snapshot(initial_margin_rate=None)).reason is (
        MarginLiquidationDecisionReason.INITIAL_MARGIN_MISSING
    )
    assert _evaluate(snapshot=_snapshot(maintenance_margin_rate=None)).reason is (
        MarginLiquidationDecisionReason.MAINTENANCE_MARGIN_MISSING
    )
    assert _evaluate(snapshot=_snapshot(liquidation_fee_rate=None)).reason is (
        MarginLiquidationDecisionReason.LIQUIDATION_FEE_MISSING
    )
    assert _evaluate(snapshot=_snapshot(max_leverage=None)).reason is (
        MarginLiquidationDecisionReason.MAX_LEVERAGE_MISSING
    )
    unknown_model = _evaluate(
        snapshot=_snapshot(liquidation_model_kind=LiquidationModelKind.UNKNOWN),
    )
    assert unknown_model.reason is MarginLiquidationDecisionReason.LIQUIDATION_MODEL_MISSING
    assert _evaluate(
        snapshot=_snapshot(liquidation_model_kind=LiquidationModelKind.NOT_PROVIDED),
    ).reason is MarginLiquidationDecisionReason.LIQUIDATION_MODEL_MISSING
    assert _evaluate(snapshot=_snapshot(risk_tier_id=None)).reason is (
        MarginLiquidationDecisionReason.RISK_TIER_MISSING
    )


def test_asset_path_gates_reject_without_implicit_equivalence() -> None:
    collateral = _evaluate(collateral_asset="USD")
    margin = _evaluate(margin_asset="USDC")
    settlement = _evaluate(settlement_asset="USD")
    crypto = _evaluate(margin_asset="BTC")

    assert collateral.reason is MarginLiquidationDecisionReason.COLLATERAL_ASSET_MISMATCH
    assert margin.reason is MarginLiquidationDecisionReason.MARGIN_ASSET_MISMATCH
    assert settlement.reason is MarginLiquidationDecisionReason.SETTLEMENT_ASSET_MISMATCH
    assert crypto.reason is MarginLiquidationDecisionReason.MARGIN_ASSET_MISMATCH


def test_other_readiness_decisions_are_not_margin_snapshots() -> None:
    decision = evaluate_margin_liquidation_readiness(
        policy=_policy(),
        checked_at=NOW,
        snapshot=object(),  # type: ignore[arg-type]
    )

    assert not decision.ready
    assert decision.reason is MarginLiquidationDecisionReason.SNAPSHOT_MISSING
