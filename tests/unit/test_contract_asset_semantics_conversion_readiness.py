from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from futures_bot.asset_conversion.policies import evaluate_asset_conversion_readiness
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
)
from futures_bot.domain.asset_semantics import (
    AssetClass,
    AssetDescriptor,
    AssetSemanticsReadinessReason,
    CollateralMode,
    ContractAssetSemantics,
    ContractPayoffKind,
    SettlementMode,
    validate_contract_asset_semantics_conversion_readiness,
    validate_contract_asset_semantics_objective_readiness,
)
from futures_bot.domain.assets import AssetSymbol
from futures_bot.domain.collateral_valuation import (
    CollateralValuationDecisionReason,
    CollateralValuationReadinessDecision,
)
from futures_bot.domain.objective_assets import (
    ObjectiveAssetCompatibility,
    ObjectiveAssetDecisionReason,
    ObjectiveAssetPolicy,
    ObjectiveAssetReadinessDecision,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _asset(symbol: str, asset_class: AssetClass = AssetClass.CRYPTO) -> AssetDescriptor:
    return AssetDescriptor(symbol=symbol, asset_class=asset_class)


def _stable(symbol: str) -> AssetDescriptor:
    return _asset(symbol, AssetClass.STABLECOIN)


def _fiat(symbol: str) -> AssetDescriptor:
    return _asset(symbol, AssetClass.FIAT)


def _semantics(**overrides: object) -> ContractAssetSemantics:
    policy = ObjectiveAssetPolicy.accumulate("BTC")
    values = {
        "venue_id": "kucoin",
        "instrument_id": "ETHUSDT",
        "base_asset": _asset("ETH"),
        "quote_asset": _stable("USDT"),
        "margin_asset": _asset("ETH"),
        "settlement_asset": _stable("USDT"),
        "pnl_asset": _stable("USDT"),
        "collateral_assets": (_asset("ETH"),),
        "valuation_reference_asset": _fiat("USD"),
        "objective_asset": _asset("BTC"),
        "payoff_kind": ContractPayoffKind.LINEAR,
        "collateral_mode": CollateralMode.MULTI_ASSET,
        "settlement_mode": SettlementMode.SINGLE_ASSET,
        "contract_size": Decimal("1"),
        "requires_collateral_valuation": False,
        "requires_haircut_rules": False,
        "requires_conversion_rules": True,
        "requires_objective_valuation": False,
        "objective_asset_policy_id": policy.policy_id,
        "metadata": {},
    }
    values.update(overrides)
    return ContractAssetSemantics(**values)


def _conversion_policy() -> AssetConversionPolicy:
    return AssetConversionPolicy(
        max_rate_age=60_000,
        require_source_record=True,
        allowed_source_trust=(AssetConversionSourceTrust.OFFICIAL,),
        allowed_source_health=(AssetConversionSourceHealth.HEALTHY,),
        allow_same_asset_direct_match=False,
        allow_inverse_rate=False,
        allow_triangulation=False,
        require_bid_ask=False,
        metadata={},
    )


def _conversion_decision(
    from_asset: str,
    to_asset: str,
    *,
    ready: bool = True,
    evidence_kind: AssetConversionEvidenceKind = (
        AssetConversionEvidenceKind.DIRECT_PAIR_RATE
    ),
) -> AssetConversionReadinessDecision:
    if not ready:
        policy = _conversion_policy()
        if policy.policy_id is None:
            raise AssertionError("policy_id was not assigned")
        return AssetConversionReadinessDecision(
            policy_id=policy.policy_id,
            from_asset=AssetSymbol(from_asset),
            to_asset=AssetSymbol(to_asset),
            ready=False,
            reason=AssetConversionDecisionReason.NOT_READY,
            compatibility=AssetConversionCompatibility.NOT_COMPATIBLE,
            checked_at=NOW,
            details={},
        )
    snapshot = AssetConversionRateSnapshot(
        from_asset=AssetSymbol(from_asset),
        to_asset=AssetSymbol(to_asset),
        rate=Decimal("2"),
        observed_at=NOW - timedelta(seconds=1),
        captured_at=NOW - timedelta(seconds=1),
        source_kind=AssetConversionSourceKind.ORACLE_PRICE,
        source_trust=AssetConversionSourceTrust.OFFICIAL,
        source_health=AssetConversionSourceHealth.HEALTHY,
        evidence_kind=evidence_kind,
        source_record_id=f"{from_asset}-{to_asset}",
        metadata={},
    )
    return evaluate_asset_conversion_readiness(
        policy=_conversion_policy(),
        checked_at=NOW,
        from_asset=from_asset,
        to_asset=to_asset,
        rate_snapshot=snapshot,
    )


def _objective_decision() -> ObjectiveAssetReadinessDecision:
    policy = ObjectiveAssetPolicy.accumulate("BTC")
    if policy.policy_id is None:
        raise AssertionError("policy_id was not assigned")
    return ObjectiveAssetReadinessDecision(
        policy_id=policy.policy_id,
        objective_asset=AssetSymbol("BTC"),
        pnl_asset=AssetSymbol("USDT"),
        settlement_asset=AssetSymbol("USDT"),
        ready=True,
        reason=ObjectiveAssetDecisionReason.READY,
        compatibility=ObjectiveAssetCompatibility.VALUATION_REQUIRED,
        checked_at=NOW,
        details={},
    )


def _collateral_decision() -> CollateralValuationReadinessDecision:
    return CollateralValuationReadinessDecision(
        collateral_asset=AssetSymbol("ETH"),
        reference_asset=AssetSymbol("USD"),
        ready=True,
        reason=CollateralValuationDecisionReason.READY,
        checked_at=NOW,
        effective_value_multiplier=Decimal("0.80"),
        details={},
    )


def test_requires_conversion_rules_rejects_without_conversion_decision() -> None:
    decision = validate_contract_asset_semantics_conversion_readiness(_semantics(), None)

    assert not decision.ready
    assert decision.reason is AssetSemanticsReadinessReason.CONVERSION_RULES_REQUIRED


def test_requires_conversion_rules_accepts_matching_ready_conversion_decision() -> None:
    decision = validate_contract_asset_semantics_conversion_readiness(
        _semantics(),
        _conversion_decision("USDT", "BTC"),
    )

    assert decision.ready


def test_unknown_evidence_kind_does_not_satisfy_contract_conversion() -> None:
    decision = validate_contract_asset_semantics_conversion_readiness(
        _semantics(),
        _conversion_decision(
            "USDT",
            "BTC",
            evidence_kind=AssetConversionEvidenceKind.UNKNOWN,
        ),
    )

    assert not decision.ready
    assert decision.reason is AssetSemanticsReadinessReason.CONVERSION_RULES_REQUIRED


def test_wrong_direction_and_wrong_pair_reject() -> None:
    wrong_direction = validate_contract_asset_semantics_conversion_readiness(
        _semantics(),
        _conversion_decision("BTC", "USDT"),
    )
    wrong_to_asset = validate_contract_asset_semantics_conversion_readiness(
        _semantics(),
        _conversion_decision("USDT", "ETH"),
    )

    assert wrong_direction.reason is AssetSemanticsReadinessReason.CONVERSION_RULES_REQUIRED
    assert wrong_to_asset.reason is AssetSemanticsReadinessReason.CONVERSION_RULES_REQUIRED


def test_not_ready_conversion_decision_rejects() -> None:
    decision = validate_contract_asset_semantics_conversion_readiness(
        _semantics(),
        _conversion_decision("USDT", "BTC", ready=False),
    )

    assert not decision.ready
    assert decision.reason is AssetSemanticsReadinessReason.CONVERSION_RULES_REQUIRED


def test_objective_readiness_alone_cannot_bypass_conversion_rules() -> None:
    decision = validate_contract_asset_semantics_objective_readiness(
        _semantics(requires_objective_valuation=True),
        _objective_decision(),
    )

    assert not decision.ready
    assert decision.reason is AssetSemanticsReadinessReason.CONVERSION_RULES_REQUIRED


def test_collateral_readiness_alone_cannot_bypass_conversion_rules() -> None:
    decision = validate_contract_asset_semantics_conversion_readiness(
        _semantics(),
        None,
    )

    assert _collateral_decision().ready
    assert not decision.ready
    assert decision.reason is AssetSemanticsReadinessReason.CONVERSION_RULES_REQUIRED
