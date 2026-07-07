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
from futures_bot.domain.collateral_valuation import (
    CollateralValuationDecisionReason,
    CollateralValuationReadinessDecision,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _snapshot(**overrides: object) -> AssetConversionRateSnapshot:
    values = {
        "from_asset": "BTC",
        "to_asset": "USDT",
        "rate": Decimal("50000"),
        "observed_at": NOW - timedelta(seconds=1),
        "captured_at": NOW - timedelta(seconds=1),
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


def _evaluate(  # noqa: PLR0913
    *,
    policy: AssetConversionPolicy | None = None,
    from_asset: str = "BTC",
    to_asset: str = "USDT",
    rate_snapshot: AssetConversionRateSnapshot | None = None,
    inverse_rate_snapshot: AssetConversionRateSnapshot | None = None,
    leg_decisions: tuple[AssetConversionReadinessDecision, ...] = (),
) -> AssetConversionReadinessDecision:
    return evaluate_asset_conversion_readiness(
        policy=_policy() if policy is None else policy,
        checked_at=NOW,
        from_asset=from_asset,
        to_asset=to_asset,
        rate_snapshot=rate_snapshot,
        inverse_rate_snapshot=inverse_rate_snapshot,
        leg_decisions=leg_decisions,
    )


def test_direct_btc_usdt_rate_ready() -> None:
    decision = _evaluate(rate_snapshot=_snapshot())

    assert decision.ready
    assert decision.compatibility is AssetConversionCompatibility.DIRECT_RATE
    assert decision.effective_rate == Decimal("50000")


def test_direct_route_rejects_unknown_and_triangulated_evidence_kind() -> None:
    unknown = _evaluate(
        rate_snapshot=_snapshot(evidence_kind=AssetConversionEvidenceKind.UNKNOWN),
    )
    triangulated = _evaluate(
        rate_snapshot=_snapshot(
            evidence_kind=AssetConversionEvidenceKind.TRIANGULATED_RATE,
        ),
    )

    assert not unknown.ready
    assert unknown.reason is AssetConversionDecisionReason.CONVERSION_RATE_MISSING
    assert not triangulated.ready
    assert triangulated.reason is AssetConversionDecisionReason.CONVERSION_RATE_MISSING


def test_stale_and_future_dated_rates_reject() -> None:
    stale = _evaluate(
        policy=_policy(max_rate_age=500),
        rate_snapshot=_snapshot(observed_at=NOW - timedelta(seconds=2)),
    )
    future_observed = _evaluate(
        rate_snapshot=_snapshot(
            observed_at=NOW + timedelta(milliseconds=1),
            captured_at=NOW + timedelta(milliseconds=1),
        ),
    )
    future_captured = _evaluate(
        rate_snapshot=_snapshot(captured_at=NOW + timedelta(milliseconds=1)),
    )

    assert stale.reason is AssetConversionDecisionReason.CONVERSION_RATE_STALE
    assert future_observed.reason is (
        AssetConversionDecisionReason.CONVERSION_RATE_FUTURE_DATED
    )
    assert future_captured.reason is (
        AssetConversionDecisionReason.CONVERSION_RATE_FUTURE_DATED
    )


def test_untrusted_unhealthy_and_missing_source_record_reject() -> None:
    untrusted = _evaluate(
        rate_snapshot=_snapshot(source_trust=AssetConversionSourceTrust.UNTRUSTED),
    )
    unhealthy = _evaluate(
        rate_snapshot=_snapshot(source_health=AssetConversionSourceHealth.UNAVAILABLE),
    )
    missing_source = _evaluate(rate_snapshot=_snapshot(source_record_id=None))

    assert untrusted.reason is AssetConversionDecisionReason.CONVERSION_SOURCE_UNTRUSTED
    assert unhealthy.reason is AssetConversionDecisionReason.CONVERSION_SOURCE_UNHEALTHY
    assert missing_source.reason is AssetConversionDecisionReason.CONVERSION_RATE_MISSING


def test_bid_ask_required_and_spread_too_wide_reject() -> None:
    missing_bid_ask = _evaluate(
        policy=_policy(require_bid_ask=True),
        rate_snapshot=_snapshot(),
    )
    spread_too_wide = _evaluate(
        policy=_policy(max_spread_bps=Decimal("10")),
        rate_snapshot=_snapshot(spread_bps=Decimal("11")),
    )

    assert missing_bid_ask.reason is AssetConversionDecisionReason.CONVERSION_RATE_MISSING
    assert spread_too_wide.reason is (
        AssetConversionDecisionReason.CONVERSION_SPREAD_TOO_WIDE
    )


def test_inverse_rate_only_works_when_enabled() -> None:
    inverse_snapshot = _snapshot(from_asset="USDT", to_asset="BTC", rate=Decimal("0.00002"))

    disabled = _evaluate(inverse_rate_snapshot=inverse_snapshot)
    enabled = _evaluate(
        policy=_policy(allow_inverse_rate=True),
        inverse_rate_snapshot=inverse_snapshot,
    )

    assert disabled.reason is (
        AssetConversionDecisionReason.CONVERSION_DIRECTION_NOT_ALLOWED
    )
    assert enabled.ready
    assert enabled.compatibility is AssetConversionCompatibility.INVERSE_RATE
    assert enabled.effective_rate == Decimal("5E+4")


def test_inverse_route_rejects_unknown_and_triangulated_evidence_kind() -> None:
    unknown = _evaluate(
        policy=_policy(allow_inverse_rate=True),
        inverse_rate_snapshot=_snapshot(
            from_asset="USDT",
            to_asset="BTC",
            rate=Decimal("0.00002"),
            evidence_kind=AssetConversionEvidenceKind.UNKNOWN,
        ),
    )
    triangulated = _evaluate(
        policy=_policy(allow_inverse_rate=True),
        inverse_rate_snapshot=_snapshot(
            from_asset="USDT",
            to_asset="BTC",
            rate=Decimal("0.00002"),
            evidence_kind=AssetConversionEvidenceKind.TRIANGULATED_RATE,
        ),
    )

    assert not unknown.ready
    assert unknown.reason is AssetConversionDecisionReason.CONVERSION_RATE_MISSING
    assert not triangulated.ready
    assert triangulated.reason is AssetConversionDecisionReason.CONVERSION_RATE_MISSING


def test_triangulation_only_works_when_enabled_and_connected() -> None:
    btc_usd = _evaluate(
        from_asset="BTC",
        to_asset="USD",
        rate_snapshot=_snapshot(to_asset="USD", rate=Decimal("50000")),
    )
    usd_usdt = _evaluate(
        from_asset="USD",
        to_asset="USDT",
        rate_snapshot=_snapshot(from_asset="USD", to_asset="USDT", rate=Decimal("1")),
    )
    disabled = _evaluate(leg_decisions=(btc_usd, usd_usdt))
    enabled = _evaluate(
        policy=_policy(allow_triangulation=True),
        leg_decisions=(btc_usd, usd_usdt),
    )
    disconnected = _evaluate(
        policy=_policy(allow_triangulation=True),
        leg_decisions=(usd_usdt, btc_usd),
    )

    assert disabled.reason is AssetConversionDecisionReason.TRIANGULATION_NOT_ALLOWED
    assert enabled.ready
    assert enabled.compatibility is AssetConversionCompatibility.TRIANGULATED_RATE
    assert disconnected.reason is AssetConversionDecisionReason.CONVERSION_PAIR_MISMATCH


def test_same_asset_direct_match_only_when_policy_allows() -> None:
    rejected = _evaluate(from_asset="BTC", to_asset="BTC")
    ready = _evaluate(
        policy=_policy(allow_same_asset_direct_match=True),
        from_asset="BTC",
        to_asset="BTC",
    )

    assert not rejected.ready
    assert ready.ready
    assert ready.compatibility is AssetConversionCompatibility.DIRECT_SAME_ASSET


def test_no_implicit_asset_equivalence() -> None:
    usdt_usd = _evaluate(from_asset="USDT", to_asset="USD")
    usdc_usdt = _evaluate(from_asset="USDC", to_asset="USDT")
    eth_btc = _evaluate(from_asset="ETH", to_asset="BTC")

    assert usdt_usd.reason is AssetConversionDecisionReason.CONVERSION_RATE_MISSING
    assert usdc_usdt.reason is AssetConversionDecisionReason.CONVERSION_RATE_MISSING
    assert eth_btc.reason is AssetConversionDecisionReason.CONVERSION_RATE_MISSING


def test_collateral_valuation_decision_is_not_conversion_evidence() -> None:
    collateral_decision = CollateralValuationReadinessDecision(
        collateral_asset="BTC",
        reference_asset="USDT",
        ready=True,
        reason=CollateralValuationDecisionReason.READY,
        checked_at=NOW,
        effective_value_multiplier=Decimal("1"),
        details={},
    )

    decision = evaluate_asset_conversion_readiness(
        policy=_policy(),
        checked_at=NOW,
        from_asset="BTC",
        to_asset="USDT",
        rate_snapshot=collateral_decision,  # type: ignore[arg-type]
    )

    assert not decision.ready
    assert decision.reason is AssetConversionDecisionReason.CONVERSION_RATE_MISSING
