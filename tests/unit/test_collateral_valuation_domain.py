from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from pydantic import ValidationError

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
    deterministic_collateral_eligibility_rule_id,
    deterministic_collateral_haircut_rule_id,
    deterministic_collateral_valuation_decision_id,
    deterministic_collateral_valuation_policy_id,
    deterministic_collateral_valuation_snapshot_id,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _snapshot(**overrides: object) -> CollateralValuationSnapshot:
    values = {
        "collateral_asset": "BTC",
        "reference_asset": "USD",
        "price": Decimal("50000"),
        "source_kind": CollateralValuationSourceKind.ORACLE_PRICE,
        "trust": CollateralValuationTrust.OFFICIAL,
        "health": CollateralValuationHealth.HEALTHY,
        "observed_at": NOW,
        "captured_at": NOW + timedelta(seconds=1),
        "metadata": {"source": "unit-test"},
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


def test_collateral_valuation_snapshot_deterministic_id() -> None:
    assert _snapshot().snapshot_id == _snapshot().snapshot_id


@pytest.mark.parametrize(
    ("collateral", "reference", "price"),
    (
        ("BTC", "USDT", "50000"),
        ("ETH", "USD", "3000"),
        ("BNB", "USDT", "600"),
        ("USDT", "USD", "1"),
        ("USDC", "USD", "1"),
    ),
)
def test_snapshot_accepts_generic_collateral_valuations(
    collateral: str,
    reference: str,
    price: str,
) -> None:
    snapshot = _snapshot(
        collateral_asset=collateral,
        reference_asset=reference,
        price=Decimal(price),
    )

    assert str(snapshot.collateral_asset) == collateral
    assert str(snapshot.reference_asset) == reference


def test_snapshot_rejects_non_positive_price() -> None:
    with pytest.raises(ValidationError, match="positive"):
        _snapshot(price=Decimal("0"))


def test_snapshot_requires_json_metadata() -> None:
    with pytest.raises(ValidationError, match="JSON-compatible"):
        _snapshot(metadata={"bad": object()})


def test_snapshot_nested_metadata_cannot_be_mutated_after_construction() -> None:
    snapshot = _snapshot(metadata={"nested": {"x": [1]}})
    old_id = snapshot.snapshot_id

    with pytest.raises(TypeError):
        cast(Any, snapshot.metadata)["nested"]["new"] = True
    with pytest.raises(AttributeError):
        cast(Any, snapshot.metadata)["nested"]["x"].append(2)

    assert deterministic_collateral_valuation_snapshot_id(snapshot) == old_id


def test_snapshot_rejects_malformed_payload_hash() -> None:
    with pytest.raises(ValidationError, match="sha256"):
        _snapshot(source_payload_hash="sha256:not-hex")


def test_snapshot_rejects_captured_before_observed() -> None:
    with pytest.raises(ValidationError, match="captured_at"):
        _snapshot(observed_at=NOW, captured_at=NOW - timedelta(seconds=1))


def test_haircut_rule_deterministic_id() -> None:
    assert _haircut().rule_id == _haircut().rule_id


def test_haircut_rule_nested_metadata_cannot_be_mutated_after_construction() -> None:
    rule = _haircut(metadata={"nested": {"x": [1]}})
    old_id = rule.rule_id

    with pytest.raises(TypeError):
        cast(Any, rule.metadata)["nested"]["new"] = True
    with pytest.raises(AttributeError):
        cast(Any, rule.metadata)["nested"]["x"].append(2)

    assert deterministic_collateral_haircut_rule_id(rule) == old_id


def test_fixed_haircut_requires_rate() -> None:
    with pytest.raises(ValidationError, match="haircut_rate"):
        _haircut(haircut_rate=None)


@pytest.mark.parametrize("rate", (Decimal("-0.01"), Decimal("1.01")))
def test_haircut_rate_must_be_between_zero_and_one(rate: Decimal) -> None:
    with pytest.raises(ValidationError, match="haircut_rate"):
        _haircut(haircut_rate=rate)


def test_none_haircut_normalizes_to_zero_rate() -> None:
    rule = _haircut(
        haircut_kind=CollateralHaircutKind.NONE,
        haircut_rate=None,
    )

    assert rule.haircut_rate == Decimal("0")


def test_haircut_expiry_must_be_after_effective_at() -> None:
    with pytest.raises(ValidationError, match="expires_at"):
        _haircut(expires_at=NOW)


def test_eligibility_rule_deterministic_id() -> None:
    assert _eligibility().eligibility_rule_id == _eligibility().eligibility_rule_id


def test_eligibility_rule_nested_metadata_cannot_be_mutated_after_construction() -> None:
    rule = _eligibility(metadata={"nested": {"x": [1]}})
    old_id = rule.eligibility_rule_id

    with pytest.raises(TypeError):
        cast(Any, rule.metadata)["nested"]["new"] = True
    with pytest.raises(AttributeError):
        cast(Any, rule.metadata)["nested"]["x"].append(2)

    assert deterministic_collateral_eligibility_rule_id(rule) == old_id


def test_policy_deterministic_id() -> None:
    first = CollateralValuationPolicy.strict(reference_asset="USD")
    second = CollateralValuationPolicy.strict(reference_asset="USD")

    assert first.policy_id == second.policy_id


def test_policy_nested_metadata_cannot_be_mutated_after_construction() -> None:
    policy = CollateralValuationPolicy(
        valuation_required=True,
        haircut_required=True,
        eligibility_required=True,
        max_valuation_age_ms=60_000,
        required_reference_asset="USD",
        metadata={"nested": {"x": [1]}},
    )
    old_id = policy.policy_id

    with pytest.raises(TypeError):
        cast(Any, policy.metadata)["nested"]["new"] = True
    with pytest.raises(AttributeError):
        cast(Any, policy.metadata)["nested"]["x"].append(2)

    assert deterministic_collateral_valuation_policy_id(policy) == old_id


def test_policy_requires_positive_age_when_valuation_required() -> None:
    with pytest.raises(ValidationError, match="max_valuation_age_ms"):
        CollateralValuationPolicy(
            valuation_required=True,
            haircut_required=False,
            eligibility_required=False,
            max_valuation_age_ms=0,
            metadata={},
        )


def test_decision_ready_reason_consistency() -> None:
    with pytest.raises(ValidationError, match="READY"):
        CollateralValuationReadinessDecision(
            collateral_asset="ETH",
            reference_asset="USD",
            ready=True,
            reason=CollateralValuationDecisionReason.NOT_READY,
            checked_at=NOW,
            details={},
        )
    with pytest.raises(ValidationError, match="READY"):
        CollateralValuationReadinessDecision(
            collateral_asset="ETH",
            reference_asset="USD",
            ready=False,
            reason=CollateralValuationDecisionReason.READY,
            checked_at=NOW,
            details={},
        )


@pytest.mark.parametrize(
    "reason",
    (
        CollateralValuationDecisionReason.HAIRCUT_RULE_NOT_EFFECTIVE,
        (
            CollateralValuationDecisionReason
            .COLLATERAL_ELIGIBILITY_RULE_NOT_EFFECTIVE
        ),
    ),
)
def test_rule_not_effective_decision_reasons_are_not_ready(
    reason: CollateralValuationDecisionReason,
) -> None:
    decision = CollateralValuationReadinessDecision(
        collateral_asset="ETH",
        reference_asset="USD",
        ready=False,
        reason=reason,
        checked_at=NOW,
        details={},
    )

    assert not decision.ready
    assert decision.reason is reason


def test_decision_nested_details_cannot_be_mutated_after_construction() -> None:
    decision = CollateralValuationReadinessDecision(
        collateral_asset="ETH",
        reference_asset="USD",
        ready=False,
        reason=CollateralValuationDecisionReason.NOT_READY,
        checked_at=NOW,
        details={"nested": {"x": [1]}},
    )
    old_id = decision.decision_id

    with pytest.raises(TypeError):
        cast(Any, decision.details)["nested"]["new"] = True
    with pytest.raises(AttributeError):
        cast(Any, decision.details)["nested"]["x"].append(2)

    assert deterministic_collateral_valuation_decision_id(decision) == old_id


def test_json_mode_dump_thaws_metadata_and_details() -> None:
    policy = CollateralValuationPolicy(
        valuation_required=True,
        haircut_required=True,
        eligibility_required=True,
        max_valuation_age_ms=60_000,
        required_reference_asset="USD",
        metadata={"nested": {"x": [1]}},
    )
    decision = CollateralValuationReadinessDecision(
        collateral_asset="ETH",
        reference_asset="USD",
        ready=False,
        reason=CollateralValuationDecisionReason.NOT_READY,
        checked_at=NOW,
        details={"nested": {"x": [1]}},
    )
    cases: tuple[tuple[Callable[[], dict[str, Any]], str], ...] = (
        (
            lambda: _snapshot(
                metadata={"nested": {"x": [1]}},
            ).model_dump(mode="json"),
            "metadata",
        ),
        (
            lambda: _haircut(
                metadata={"nested": {"x": [1]}},
            ).model_dump(mode="json"),
            "metadata",
        ),
        (
            lambda: _eligibility(
                metadata={"nested": {"x": [1]}},
            ).model_dump(mode="json"),
            "metadata",
        ),
        (lambda: policy.model_dump(mode="json"), "metadata"),
        (lambda: decision.model_dump(mode="json"), "details"),
    )

    for dump_factory, field_name in cases:
        dumped = dump_factory()

        assert dumped[field_name] == {"nested": {"x": [1]}}
        assert isinstance(dumped[field_name], dict)
        assert isinstance(dumped[field_name]["nested"], dict)
        assert isinstance(dumped[field_name]["nested"]["x"], list)


def test_decision_effective_value_multiplier_bounds() -> None:
    with pytest.raises(ValidationError, match="effective_value_multiplier"):
        CollateralValuationReadinessDecision(
            collateral_asset="ETH",
            reference_asset="USD",
            ready=False,
            reason=CollateralValuationDecisionReason.NOT_READY,
            checked_at=NOW,
            effective_value_multiplier=Decimal("1.01"),
            details={},
        )
