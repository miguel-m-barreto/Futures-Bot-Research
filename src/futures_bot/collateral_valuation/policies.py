from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from futures_bot.domain.assets import AssetSymbol
from futures_bot.domain.collateral_valuation import (
    CollateralEligibilityRule,
    CollateralEligibilityStatus,
    CollateralHaircutKind,
    CollateralHaircutRule,
    CollateralValuationDecisionReason,
    CollateralValuationHealth,
    CollateralValuationPolicy,
    CollateralValuationReadinessDecision,
    CollateralValuationSnapshot,
    CollateralValuationSourceKind,
    CollateralValuationTrust,
)
from futures_bot.domain.time import ensure_aware_utc


def evaluate_collateral_valuation_readiness(  # noqa: PLR0911, PLR0912, PLR0913
    *,
    collateral_asset: AssetSymbol | str,
    reference_asset: AssetSymbol | str,
    checked_at: datetime,
    policy: CollateralValuationPolicy,
    valuation_snapshot: CollateralValuationSnapshot | None = None,
    haircut_rule: CollateralHaircutRule | None = None,
    eligibility_rule: CollateralEligibilityRule | None = None,
) -> CollateralValuationReadinessDecision:
    collateral = _asset(collateral_asset)
    requested_reference = _asset(reference_asset)
    checked_at = ensure_aware_utc(checked_at)
    expected_reference = policy.required_reference_asset or requested_reference
    if requested_reference != expected_reference:
        return _decision(
            collateral_asset=collateral,
            reference_asset=requested_reference,
            checked_at=checked_at,
            reason=CollateralValuationDecisionReason.REFERENCE_ASSET_MISMATCH,
            valuation_snapshot=valuation_snapshot,
            haircut_rule=haircut_rule,
            eligibility_rule=eligibility_rule,
            details={
                "requested_reference_asset": str(requested_reference),
                "required_reference_asset": str(expected_reference),
            },
        )

    if not policy.valuation_required:
        return _decision(
            collateral_asset=collateral,
            reference_asset=requested_reference,
            checked_at=checked_at,
            ready=True,
            reason=CollateralValuationDecisionReason.READY,
            valuation_snapshot=valuation_snapshot,
            haircut_rule=haircut_rule,
            eligibility_rule=eligibility_rule,
            details={"policy_disabled": True},
        )

    if valuation_snapshot is None:
        return _decision(
            collateral_asset=collateral,
            reference_asset=requested_reference,
            checked_at=checked_at,
            reason=CollateralValuationDecisionReason.VALUATION_MISSING,
            details={"missing": "valuation_snapshot"},
        )

    if (
        valuation_snapshot.collateral_asset != collateral
        or valuation_snapshot.reference_asset != expected_reference
    ):
        return _decision(
            collateral_asset=collateral,
            reference_asset=requested_reference,
            checked_at=checked_at,
            reason=CollateralValuationDecisionReason.REFERENCE_ASSET_MISMATCH,
            valuation_snapshot=valuation_snapshot,
            haircut_rule=haircut_rule,
            eligibility_rule=eligibility_rule,
            details={
                "valuation_collateral_asset": str(valuation_snapshot.collateral_asset),
                "valuation_reference_asset": str(valuation_snapshot.reference_asset),
                "required_collateral_asset": str(collateral),
                "required_reference_asset": str(expected_reference),
            },
        )

    if valuation_snapshot.captured_at > checked_at:
        return _decision(
            collateral_asset=collateral,
            reference_asset=requested_reference,
            checked_at=checked_at,
            reason=CollateralValuationDecisionReason.VALUATION_FUTURE_DATED,
            valuation_snapshot=valuation_snapshot,
            details={"captured_at": valuation_snapshot.captured_at.isoformat()},
        )

    max_age_ms = policy.max_valuation_age_ms
    if max_age_ms is None:
        raise ValueError("valuation_required policy must define max_valuation_age_ms")
    if checked_at - valuation_snapshot.captured_at > timedelta(milliseconds=max_age_ms):
        return _decision(
            collateral_asset=collateral,
            reference_asset=requested_reference,
            checked_at=checked_at,
            reason=CollateralValuationDecisionReason.VALUATION_STALE,
            valuation_snapshot=valuation_snapshot,
            details={"max_valuation_age_ms": max_age_ms},
        )

    if not _source_allowed(valuation_snapshot.source_kind, policy) or not _trust_allowed(
        valuation_snapshot.trust,
        policy,
    ):
        return _decision(
            collateral_asset=collateral,
            reference_asset=requested_reference,
            checked_at=checked_at,
            reason=CollateralValuationDecisionReason.VALUATION_SOURCE_UNTRUSTED,
            valuation_snapshot=valuation_snapshot,
            details={"trust": valuation_snapshot.trust.value},
        )

    if not _health_allowed(valuation_snapshot.health, policy):
        return _decision(
            collateral_asset=collateral,
            reference_asset=requested_reference,
            checked_at=checked_at,
            reason=CollateralValuationDecisionReason.VALUATION_SOURCE_UNHEALTHY,
            valuation_snapshot=valuation_snapshot,
            details={"health": valuation_snapshot.health.value},
        )

    if policy.eligibility_required and (
        eligibility_rule is None
        or eligibility_rule.collateral_asset != collateral
        or eligibility_rule.eligibility_status is not CollateralEligibilityStatus.ELIGIBLE
    ):
        return _decision(
            collateral_asset=collateral,
            reference_asset=requested_reference,
            checked_at=checked_at,
            reason=CollateralValuationDecisionReason.COLLATERAL_NOT_ELIGIBLE,
            valuation_snapshot=valuation_snapshot,
            haircut_rule=haircut_rule,
            eligibility_rule=eligibility_rule,
            details={"eligibility_required": True},
        )
    if (
        policy.eligibility_required
        and eligibility_rule is not None
        and not _rule_is_active(
            checked_at=checked_at,
            effective_at=eligibility_rule.effective_at,
            expires_at=eligibility_rule.expires_at,
        )
    ):
        return _decision(
            collateral_asset=collateral,
            reference_asset=requested_reference,
            checked_at=checked_at,
            reason=(
                CollateralValuationDecisionReason
                .COLLATERAL_ELIGIBILITY_RULE_NOT_EFFECTIVE
            ),
            valuation_snapshot=valuation_snapshot,
            haircut_rule=haircut_rule,
            eligibility_rule=eligibility_rule,
            details=_eligibility_rule_window_details(
                checked_at=checked_at,
                rule=eligibility_rule,
            ),
        )

    multiplier: Decimal | None = None
    if policy.haircut_required:
        if haircut_rule is None:
            return _decision(
                collateral_asset=collateral,
                reference_asset=requested_reference,
                checked_at=checked_at,
                reason=CollateralValuationDecisionReason.HAIRCUT_RULE_MISSING,
                valuation_snapshot=valuation_snapshot,
                eligibility_rule=eligibility_rule,
                details={"missing": "haircut_rule"},
            )
        if (
            haircut_rule.collateral_asset != collateral
            or haircut_rule.reference_asset != expected_reference
        ):
            return _decision(
                collateral_asset=collateral,
                reference_asset=requested_reference,
                checked_at=checked_at,
                reason=CollateralValuationDecisionReason.REFERENCE_ASSET_MISMATCH,
                valuation_snapshot=valuation_snapshot,
                haircut_rule=haircut_rule,
                eligibility_rule=eligibility_rule,
                details={
                    "haircut_collateral_asset": str(haircut_rule.collateral_asset),
                    "haircut_reference_asset": str(haircut_rule.reference_asset),
                },
            )
        if not _rule_is_active(
            checked_at=checked_at,
            effective_at=haircut_rule.effective_at,
            expires_at=haircut_rule.expires_at,
        ):
            return _decision(
                collateral_asset=collateral,
                reference_asset=requested_reference,
                checked_at=checked_at,
                reason=CollateralValuationDecisionReason.HAIRCUT_RULE_NOT_EFFECTIVE,
                valuation_snapshot=valuation_snapshot,
                haircut_rule=haircut_rule,
                eligibility_rule=eligibility_rule,
                details=_haircut_rule_window_details(
                    checked_at=checked_at,
                    rule=haircut_rule,
                ),
            )
        if haircut_rule.haircut_kind is CollateralHaircutKind.UNKNOWN:
            return _decision(
                collateral_asset=collateral,
                reference_asset=requested_reference,
                checked_at=checked_at,
                reason=CollateralValuationDecisionReason.HAIRCUT_RULE_UNKNOWN,
                valuation_snapshot=valuation_snapshot,
                haircut_rule=haircut_rule,
                eligibility_rule=eligibility_rule,
                details={"haircut_kind": haircut_rule.haircut_kind.value},
            )
        multiplier = _effective_multiplier(haircut_rule)

    return _decision(
        collateral_asset=collateral,
        reference_asset=requested_reference,
        checked_at=checked_at,
        ready=True,
        reason=CollateralValuationDecisionReason.READY,
        valuation_snapshot=valuation_snapshot,
        haircut_rule=haircut_rule,
        eligibility_rule=eligibility_rule,
        effective_value_multiplier=multiplier,
        details={"required_reference_asset": str(expected_reference)},
    )


def _decision(  # noqa: PLR0913
    *,
    collateral_asset: AssetSymbol,
    reference_asset: AssetSymbol,
    checked_at: datetime,
    reason: CollateralValuationDecisionReason,
    ready: bool = False,
    valuation_snapshot: CollateralValuationSnapshot | None = None,
    haircut_rule: CollateralHaircutRule | None = None,
    eligibility_rule: CollateralEligibilityRule | None = None,
    effective_value_multiplier: Decimal | None = None,
    details: Any,
) -> CollateralValuationReadinessDecision:
    return CollateralValuationReadinessDecision(
        collateral_asset=collateral_asset,
        reference_asset=reference_asset,
        ready=ready,
        reason=reason,
        valuation_snapshot=valuation_snapshot,
        haircut_rule=haircut_rule,
        eligibility_rule=eligibility_rule,
        checked_at=checked_at,
        effective_value_multiplier=effective_value_multiplier,
        details=details,
    )


def _trust_allowed(
    trust: CollateralValuationTrust,
    policy: CollateralValuationPolicy,
) -> bool:
    if trust is CollateralValuationTrust.OFFICIAL:
        return True
    if trust is CollateralValuationTrust.MANUAL_REVIEW_REQUIRED:
        return policy.allow_manual_review_sources
    if trust is CollateralValuationTrust.TEST_ONLY:
        return policy.allow_test_fixture_sources
    if trust is CollateralValuationTrust.UNTRUSTED:
        return policy.allow_untrusted_sources
    return False


def _source_allowed(
    source_kind: CollateralValuationSourceKind,
    policy: CollateralValuationPolicy,
) -> bool:
    if source_kind is CollateralValuationSourceKind.UNKNOWN:
        return False
    if source_kind is CollateralValuationSourceKind.TEST_FIXTURE:
        return policy.allow_test_fixture_sources
    return True


def _health_allowed(
    health: CollateralValuationHealth,
    policy: CollateralValuationPolicy,
) -> bool:
    if health is CollateralValuationHealth.HEALTHY:
        return True
    if health is CollateralValuationHealth.DEGRADED:
        return policy.allow_degraded_sources
    return False


def _effective_multiplier(rule: CollateralHaircutRule) -> Decimal | None:
    if rule.haircut_kind is CollateralHaircutKind.NONE:
        return Decimal("1")
    if rule.haircut_kind is CollateralHaircutKind.FIXED_PERCENTAGE:
        if rule.haircut_rate is None:
            raise ValueError("fixed haircut rule must define haircut_rate")
        return Decimal("1") - rule.haircut_rate
    return None


def _rule_is_active(
    *,
    checked_at: datetime,
    effective_at: datetime,
    expires_at: datetime | None,
) -> bool:
    return effective_at <= checked_at and (expires_at is None or expires_at > checked_at)


def _haircut_rule_window_details(
    *,
    checked_at: datetime,
    rule: CollateralHaircutRule,
) -> dict[str, str | None]:
    return {
        "checked_at": checked_at.isoformat(),
        "effective_at": rule.effective_at.isoformat(),
        "expires_at": None if rule.expires_at is None else rule.expires_at.isoformat(),
        "collateral_asset": str(rule.collateral_asset),
        "reference_asset": str(rule.reference_asset),
    }


def _eligibility_rule_window_details(
    *,
    checked_at: datetime,
    rule: CollateralEligibilityRule,
) -> dict[str, str | None]:
    return {
        "checked_at": checked_at.isoformat(),
        "effective_at": rule.effective_at.isoformat(),
        "expires_at": None if rule.expires_at is None else rule.expires_at.isoformat(),
        "collateral_asset": str(rule.collateral_asset),
    }


def _asset(value: AssetSymbol | str) -> AssetSymbol:
    return value if isinstance(value, AssetSymbol) else AssetSymbol(value)
