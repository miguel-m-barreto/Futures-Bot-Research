from __future__ import annotations

from datetime import datetime

from futures_bot.domain.assets import AssetSymbol
from futures_bot.domain.margin_liquidation import (
    LiquidationModelKind,
    MarginLiquidationCompatibility,
    MarginLiquidationDecisionReason,
    MarginLiquidationPolicy,
    MarginLiquidationReadinessDecision,
    MarginLiquidationRuleSnapshot,
    MarginLiquidationSourceKind,
    MarginMode,
)
from futures_bot.domain.time import ensure_aware_utc


def evaluate_margin_liquidation_readiness(  # noqa: PLR0911, PLR0912, PLR0913
    *,
    policy: MarginLiquidationPolicy,
    checked_at: datetime,
    snapshot: MarginLiquidationRuleSnapshot | None = None,
    venue_id: str | None = None,
    instrument_id: str | None = None,
    margin_mode: MarginMode | str | None = None,
    collateral_asset: AssetSymbol | str | None = None,
    margin_asset: AssetSymbol | str | None = None,
    settlement_asset: AssetSymbol | str | None = None,
) -> MarginLiquidationReadinessDecision:
    checked_at = ensure_aware_utc(checked_at)
    requested_mode = _mode_or_none(margin_mode)
    requested_collateral = _asset_or_none(collateral_asset)
    requested_margin = _asset_or_none(margin_asset)
    requested_settlement = _asset_or_none(settlement_asset)

    if _policy_disabled(policy):
        return _decision(
            policy=policy,
            checked_at=checked_at,
            reason=MarginLiquidationDecisionReason.POLICY_DISABLED,
            compatibility=MarginLiquidationCompatibility.UNKNOWN,
            details={"policy_disabled": True},
        )
    if not isinstance(snapshot, MarginLiquidationRuleSnapshot):
        return _decision(
            policy=policy,
            checked_at=checked_at,
            reason=MarginLiquidationDecisionReason.SNAPSHOT_MISSING,
            compatibility=MarginLiquidationCompatibility.UNKNOWN,
            details={
                "snapshot_type": None if snapshot is None else type(snapshot).__name__,
            },
        )

    common = _common_decision_fields(snapshot)
    if snapshot.observed_at > checked_at or snapshot.captured_at > checked_at:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=MarginLiquidationDecisionReason.SNAPSHOT_FUTURE_DATED,
            details=common,
        )
    age_ms = int((checked_at - snapshot.observed_at).total_seconds() * 1000)
    if age_ms > policy.max_snapshot_age:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=MarginLiquidationDecisionReason.SNAPSHOT_STALE,
            details=common | {"age_ms": age_ms},
        )
    if policy.require_source_record and snapshot.source_record_id is None:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=MarginLiquidationDecisionReason.SOURCE_RECORD_REQUIRED,
            details=common,
        )
    if snapshot.source_kind is MarginLiquidationSourceKind.UNKNOWN:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=MarginLiquidationDecisionReason.SOURCE_KIND_UNKNOWN,
            details=common,
        )
    if snapshot.source_kind not in policy.allowed_source_kinds:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=MarginLiquidationDecisionReason.SOURCE_KIND_UNSUPPORTED,
            details=common
            | {
                "allowed_source_kinds": [
                    kind.value for kind in policy.allowed_source_kinds
                ],
            },
        )
    if snapshot.source_trust not in policy.allowed_source_trust:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=MarginLiquidationDecisionReason.SOURCE_UNTRUSTED,
            details=common,
        )
    if snapshot.source_health not in policy.allowed_source_health:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=MarginLiquidationDecisionReason.SOURCE_UNHEALTHY,
            details=common,
        )
    if venue_id is not None and snapshot.venue_id != venue_id:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=MarginLiquidationDecisionReason.VENUE_MISMATCH,
            details=common | {"required_venue_id": venue_id},
        )
    if (
        instrument_id is not None
        and snapshot.instrument_id is not None
        and snapshot.instrument_id != instrument_id
    ):
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=MarginLiquidationDecisionReason.INSTRUMENT_MISMATCH,
            details=common | {"required_instrument_id": instrument_id},
        )
    if snapshot.margin_mode is MarginMode.UNKNOWN:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=MarginLiquidationDecisionReason.MARGIN_MODE_UNKNOWN,
            compatibility=MarginLiquidationCompatibility.MODE_UNSUPPORTED,
            details=common,
        )
    if requested_mode is not None and snapshot.margin_mode is not requested_mode:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=MarginLiquidationDecisionReason.MARGIN_MODE_UNSUPPORTED,
            compatibility=MarginLiquidationCompatibility.MODE_UNSUPPORTED,
            details=common | {"required_margin_mode": requested_mode.value},
        )
    if snapshot.margin_mode not in policy.allowed_margin_modes:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=MarginLiquidationDecisionReason.MARGIN_MODE_UNSUPPORTED,
            compatibility=MarginLiquidationCompatibility.MODE_UNSUPPORTED,
            details=common,
        )

    field_reason = _required_field_reason(policy, snapshot)
    if field_reason is not None:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=field_reason,
            details=common,
        )
    asset_reason = _asset_path_reason(
        policy=policy,
        snapshot=snapshot,
        collateral_asset=requested_collateral,
        margin_asset=requested_margin,
        settlement_asset=requested_settlement,
    )
    if asset_reason is not None:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=asset_reason,
            compatibility=MarginLiquidationCompatibility.ASSET_MISMATCH,
            details=common,
        )
    return _decision(
        policy=policy,
        checked_at=checked_at,
        snapshot=snapshot,
        ready=True,
        reason=MarginLiquidationDecisionReason.READY,
        compatibility=MarginLiquidationCompatibility.DIRECT_MATCH,
        details=common,
    )


def _required_field_reason(
    policy: MarginLiquidationPolicy,
    snapshot: MarginLiquidationRuleSnapshot,
) -> MarginLiquidationDecisionReason | None:
    checks = (
        (
            policy.require_initial_margin and snapshot.initial_margin_rate is None,
            MarginLiquidationDecisionReason.INITIAL_MARGIN_MISSING,
        ),
        (
            policy.require_maintenance_margin
            and snapshot.maintenance_margin_rate is None,
            MarginLiquidationDecisionReason.MAINTENANCE_MARGIN_MISSING,
        ),
        (
            policy.require_liquidation_fee and snapshot.liquidation_fee_rate is None,
            MarginLiquidationDecisionReason.LIQUIDATION_FEE_MISSING,
        ),
        (
            policy.require_max_leverage and snapshot.max_leverage is None,
            MarginLiquidationDecisionReason.MAX_LEVERAGE_MISSING,
        ),
        (
            policy.require_liquidation_model
            and snapshot.liquidation_model_kind
            in {LiquidationModelKind.UNKNOWN, LiquidationModelKind.NOT_PROVIDED},
            MarginLiquidationDecisionReason.LIQUIDATION_MODEL_MISSING,
        ),
        (
            policy.require_risk_tier and snapshot.risk_tier_id is None,
            MarginLiquidationDecisionReason.RISK_TIER_MISSING,
        ),
    )
    for failed, reason in checks:
        if failed:
            return reason
    return None


def _asset_path_reason(  # noqa: PLR0911
    *,
    policy: MarginLiquidationPolicy,
    snapshot: MarginLiquidationRuleSnapshot,
    collateral_asset: AssetSymbol | None,
    margin_asset: AssetSymbol | None,
    settlement_asset: AssetSymbol | None,
) -> MarginLiquidationDecisionReason | None:
    if policy.require_collateral_asset_match:
        if collateral_asset is None or snapshot.collateral_asset is None:
            return MarginLiquidationDecisionReason.COLLATERAL_ASSET_MISSING
        if str(snapshot.collateral_asset) != str(collateral_asset):
            return MarginLiquidationDecisionReason.COLLATERAL_ASSET_MISMATCH
    if policy.require_margin_asset_match:
        if margin_asset is None or snapshot.margin_asset is None:
            return MarginLiquidationDecisionReason.MARGIN_ASSET_MISSING
        if str(snapshot.margin_asset) != str(margin_asset):
            return MarginLiquidationDecisionReason.MARGIN_ASSET_MISMATCH
    if policy.require_settlement_asset_match:
        if settlement_asset is None or snapshot.settlement_asset is None:
            return MarginLiquidationDecisionReason.SETTLEMENT_ASSET_MISSING
        if str(snapshot.settlement_asset) != str(settlement_asset):
            return MarginLiquidationDecisionReason.SETTLEMENT_ASSET_MISMATCH
    return None


def _not_ready(  # noqa: PLR0913
    *,
    policy: MarginLiquidationPolicy,
    checked_at: datetime,
    snapshot: MarginLiquidationRuleSnapshot,
    reason: MarginLiquidationDecisionReason,
    details: object,
    compatibility: MarginLiquidationCompatibility = (
        MarginLiquidationCompatibility.NOT_COMPATIBLE
    ),
) -> MarginLiquidationReadinessDecision:
    return _decision(
        policy=policy,
        checked_at=checked_at,
        snapshot=snapshot,
        reason=reason,
        compatibility=compatibility,
        details=details,
    )


def _decision(  # noqa: PLR0913
    *,
    policy: MarginLiquidationPolicy,
    checked_at: datetime,
    reason: MarginLiquidationDecisionReason,
    compatibility: MarginLiquidationCompatibility,
    details: object,
    snapshot: MarginLiquidationRuleSnapshot | None = None,
    ready: bool = False,
) -> MarginLiquidationReadinessDecision:
    if policy.policy_id is None:
        raise ValueError("margin/liquidation policy must have policy_id")
    return MarginLiquidationReadinessDecision(
        policy_id=policy.policy_id,
        venue_id=None if snapshot is None else snapshot.venue_id,
        instrument_id=None if snapshot is None else snapshot.instrument_id,
        margin_mode=None if snapshot is None else snapshot.margin_mode,
        collateral_asset=None if snapshot is None else snapshot.collateral_asset,
        margin_asset=None if snapshot is None else snapshot.margin_asset,
        settlement_asset=None if snapshot is None else snapshot.settlement_asset,
        ready=ready,
        reason=reason,
        compatibility=compatibility,
        snapshot_id=None if snapshot is None else snapshot.snapshot_id,
        checked_at=checked_at,
        details=details,
    )


def _common_decision_fields(snapshot: MarginLiquidationRuleSnapshot) -> dict[str, object]:
    return {
        "venue_id": snapshot.venue_id,
        "instrument_id": snapshot.instrument_id,
        "margin_mode": snapshot.margin_mode.value,
        "source_kind": snapshot.source_kind.value,
    }


def _policy_disabled(policy: MarginLiquidationPolicy) -> bool:
    disabled = policy.metadata.get("policy_disabled")
    return disabled is True


def _mode_or_none(value: MarginMode | str | None) -> MarginMode | None:
    if value is None:
        return None
    return value if isinstance(value, MarginMode) else MarginMode(value)


def _asset_or_none(value: AssetSymbol | str | None) -> AssetSymbol | None:
    if value is None:
        return None
    return value if isinstance(value, AssetSymbol) else AssetSymbol(value)
