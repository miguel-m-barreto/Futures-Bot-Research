from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from futures_bot.collateral_valuation.policies import (
    evaluate_collateral_valuation_readiness,
)
from futures_bot.domain.collateral_valuation import (
    CollateralEligibilityRule,
    CollateralEligibilityStatus,
    CollateralHaircutKind,
    CollateralHaircutRule,
    CollateralValuationDecisionReason,
    CollateralValuationHealth,
    CollateralValuationPolicy,
    CollateralValuationSnapshot,
    CollateralValuationSourceKind,
    CollateralValuationTrust,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _policy(**overrides: object) -> CollateralValuationPolicy:
    values = {
        "valuation_required": True,
        "haircut_required": True,
        "eligibility_required": True,
        "max_valuation_age_ms": 60_000,
        "required_reference_asset": "USD",
        "metadata": {},
    }
    values.update(overrides)
    return CollateralValuationPolicy(**values)


def _snapshot(**overrides: object) -> CollateralValuationSnapshot:
    values = {
        "collateral_asset": "ETH",
        "reference_asset": "USD",
        "price": Decimal("3000"),
        "source_kind": CollateralValuationSourceKind.ORACLE_PRICE,
        "trust": CollateralValuationTrust.OFFICIAL,
        "health": CollateralValuationHealth.HEALTHY,
        "observed_at": NOW - timedelta(seconds=1),
        "captured_at": NOW,
        "metadata": {},
    }
    values.update(overrides)
    return CollateralValuationSnapshot(**values)


def _haircut(**overrides: object) -> CollateralHaircutRule:
    values = {
        "collateral_asset": "ETH",
        "reference_asset": "USD",
        "haircut_kind": CollateralHaircutKind.FIXED_PERCENTAGE,
        "haircut_rate": Decimal("0.20"),
        "effective_at": NOW,
        "metadata": {},
    }
    values.update(overrides)
    return CollateralHaircutRule(**values)


def _eligibility(**overrides: object) -> CollateralEligibilityRule:
    values = {
        "collateral_asset": "ETH",
        "eligibility_status": CollateralEligibilityStatus.ELIGIBLE,
        "effective_at": NOW,
        "metadata": {},
    }
    values.update(overrides)
    return CollateralEligibilityRule(**values)


def _evaluate(  # noqa: PLR0913
    *,
    policy: CollateralValuationPolicy | None = None,
    snapshot: CollateralValuationSnapshot | None = None,
    haircut: CollateralHaircutRule | None = None,
    eligibility: CollateralEligibilityRule | None = None,
    collateral_asset: str = "ETH",
    reference_asset: str = "USD",
    checked_at: datetime = NOW,
):
    return evaluate_collateral_valuation_readiness(
        collateral_asset=collateral_asset,
        reference_asset=reference_asset,
        checked_at=checked_at,
        policy=policy or _policy(),
        valuation_snapshot=snapshot,
        haircut_rule=haircut,
        eligibility_rule=eligibility,
    )


def test_missing_valuation_rejected() -> None:
    decision = _evaluate(haircut=_haircut(), eligibility=_eligibility())

    assert decision.reason is CollateralValuationDecisionReason.VALUATION_MISSING


def test_stale_valuation_rejected() -> None:
    snapshot = _snapshot(
        observed_at=NOW - timedelta(minutes=2, seconds=1),
        captured_at=NOW - timedelta(minutes=2),
    )
    decision = _evaluate(snapshot=snapshot, haircut=_haircut(), eligibility=_eligibility())

    assert decision.reason is CollateralValuationDecisionReason.VALUATION_STALE


def test_future_dated_valuation_rejected() -> None:
    snapshot = _snapshot(
        observed_at=NOW + timedelta(seconds=4),
        captured_at=NOW + timedelta(seconds=5),
    )
    decision = _evaluate(snapshot=snapshot, haircut=_haircut(), eligibility=_eligibility())

    assert decision.reason is CollateralValuationDecisionReason.VALUATION_FUTURE_DATED


def test_untrusted_source_rejected() -> None:
    snapshot = _snapshot(trust=CollateralValuationTrust.UNTRUSTED)
    decision = _evaluate(snapshot=snapshot, haircut=_haircut(), eligibility=_eligibility())

    assert decision.reason is CollateralValuationDecisionReason.VALUATION_SOURCE_UNTRUSTED


def test_unknown_source_kind_rejected() -> None:
    snapshot = _snapshot(source_kind=CollateralValuationSourceKind.UNKNOWN)
    decision = _evaluate(snapshot=snapshot, haircut=_haircut(), eligibility=_eligibility())

    assert decision.reason is CollateralValuationDecisionReason.VALUATION_SOURCE_UNTRUSTED


def test_degraded_source_rejected_unless_policy_allows_it() -> None:
    snapshot = _snapshot(health=CollateralValuationHealth.DEGRADED)

    rejected = _evaluate(snapshot=snapshot, haircut=_haircut(), eligibility=_eligibility())
    allowed = _evaluate(
        policy=_policy(allow_degraded_sources=True),
        snapshot=snapshot,
        haircut=_haircut(),
        eligibility=_eligibility(),
    )

    assert rejected.reason is CollateralValuationDecisionReason.VALUATION_SOURCE_UNHEALTHY
    assert allowed.ready


def test_reference_asset_mismatch_rejected() -> None:
    snapshot = _snapshot(reference_asset="USDT")
    decision = _evaluate(snapshot=snapshot, haircut=_haircut(), eligibility=_eligibility())

    assert decision.reason is CollateralValuationDecisionReason.REFERENCE_ASSET_MISMATCH


def test_missing_haircut_rejected_when_required() -> None:
    decision = _evaluate(snapshot=_snapshot(), eligibility=_eligibility())

    assert decision.reason is CollateralValuationDecisionReason.HAIRCUT_RULE_MISSING


def test_unknown_haircut_rejected() -> None:
    decision = _evaluate(
        snapshot=_snapshot(),
        haircut=_haircut(
            haircut_kind=CollateralHaircutKind.UNKNOWN,
            haircut_rate=None,
        ),
        eligibility=_eligibility(),
    )

    assert decision.reason is CollateralValuationDecisionReason.HAIRCUT_RULE_UNKNOWN


def test_future_effective_haircut_rejects_readiness() -> None:
    effective_at = NOW + timedelta(seconds=1)
    decision = _evaluate(
        snapshot=_snapshot(),
        haircut=_haircut(effective_at=effective_at),
        eligibility=_eligibility(),
    )

    assert decision.reason is (
        CollateralValuationDecisionReason.HAIRCUT_RULE_NOT_EFFECTIVE
    )
    assert decision.details["checked_at"] == NOW.isoformat()
    assert decision.details["effective_at"] == effective_at.isoformat()
    assert decision.details["collateral_asset"] == "ETH"
    assert decision.details["reference_asset"] == "USD"


def test_expired_haircut_rejects_readiness() -> None:
    expires_at = NOW - timedelta(seconds=1)
    decision = _evaluate(
        snapshot=_snapshot(),
        haircut=_haircut(
            effective_at=NOW - timedelta(days=1),
            expires_at=expires_at,
        ),
        eligibility=_eligibility(),
    )

    assert decision.reason is (
        CollateralValuationDecisionReason.HAIRCUT_RULE_NOT_EFFECTIVE
    )
    assert decision.details["checked_at"] == NOW.isoformat()
    assert decision.details["expires_at"] == expires_at.isoformat()
    assert decision.details["collateral_asset"] == "ETH"
    assert decision.details["reference_asset"] == "USD"


def test_active_haircut_with_future_expiry_allows_ready() -> None:
    decision = _evaluate(
        snapshot=_snapshot(),
        haircut=_haircut(
            effective_at=NOW - timedelta(seconds=1),
            expires_at=NOW + timedelta(seconds=1),
        ),
        eligibility=_eligibility(),
    )

    assert decision.ready
    assert decision.reason is CollateralValuationDecisionReason.READY


def test_not_eligible_collateral_rejected() -> None:
    decision = _evaluate(
        snapshot=_snapshot(),
        haircut=_haircut(),
        eligibility=_eligibility(
            eligibility_status=CollateralEligibilityStatus.NOT_ELIGIBLE,
        ),
    )

    assert decision.reason is CollateralValuationDecisionReason.COLLATERAL_NOT_ELIGIBLE


def test_future_effective_eligibility_rejects_readiness() -> None:
    effective_at = NOW + timedelta(seconds=1)
    decision = _evaluate(
        snapshot=_snapshot(),
        haircut=_haircut(),
        eligibility=_eligibility(effective_at=effective_at),
    )

    assert decision.reason is (
        CollateralValuationDecisionReason
        .COLLATERAL_ELIGIBILITY_RULE_NOT_EFFECTIVE
    )
    assert decision.details["checked_at"] == NOW.isoformat()
    assert decision.details["effective_at"] == effective_at.isoformat()
    assert decision.details["collateral_asset"] == "ETH"


def test_expired_eligibility_rejects_readiness() -> None:
    expires_at = NOW - timedelta(seconds=1)
    decision = _evaluate(
        snapshot=_snapshot(),
        haircut=_haircut(),
        eligibility=_eligibility(
            effective_at=NOW - timedelta(days=1),
            expires_at=expires_at,
        ),
    )

    assert decision.reason is (
        CollateralValuationDecisionReason
        .COLLATERAL_ELIGIBILITY_RULE_NOT_EFFECTIVE
    )
    assert decision.details["checked_at"] == NOW.isoformat()
    assert decision.details["expires_at"] == expires_at.isoformat()
    assert decision.details["collateral_asset"] == "ETH"


def test_active_eligibility_with_future_expiry_allows_ready() -> None:
    decision = _evaluate(
        snapshot=_snapshot(),
        haircut=_haircut(),
        eligibility=_eligibility(
            effective_at=NOW - timedelta(seconds=1),
            expires_at=NOW + timedelta(seconds=1),
        ),
    )

    assert decision.ready
    assert decision.reason is CollateralValuationDecisionReason.READY


def test_fixed_haircut_produces_multiplier() -> None:
    decision = _evaluate(snapshot=_snapshot(), haircut=_haircut(), eligibility=_eligibility())

    assert decision.ready
    assert decision.effective_value_multiplier == Decimal("0.80")


def test_usdt_usd_no_haircut_ready_case() -> None:
    decision = _evaluate(
        collateral_asset="USDT",
        snapshot=_snapshot(collateral_asset="USDT", price=Decimal("1")),
        haircut=_haircut(
            collateral_asset="USDT",
            haircut_kind=CollateralHaircutKind.NONE,
            haircut_rate=None,
        ),
        eligibility=_eligibility(collateral_asset="USDT"),
    )

    assert decision.ready
    assert decision.effective_value_multiplier == Decimal("1")


def test_eth_usd_fixed_haircut_ready_case() -> None:
    decision = _evaluate(snapshot=_snapshot(), haircut=_haircut(), eligibility=_eligibility())

    assert decision.ready
    assert decision.reason is CollateralValuationDecisionReason.READY


def test_policy_disabled_does_not_require_valuation() -> None:
    policy = CollateralValuationPolicy(
        valuation_required=False,
        haircut_required=True,
        eligibility_required=True,
        max_valuation_age_ms=None,
        required_reference_asset="USD",
        metadata={},
    )
    decision = _evaluate(policy=policy)

    assert decision.ready
    assert decision.details["policy_disabled"] is True
