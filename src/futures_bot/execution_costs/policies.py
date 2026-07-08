from __future__ import annotations

from datetime import datetime

from futures_bot.domain.assets import AssetSymbol
from futures_bot.domain.execution_costs import (
    DepthModelKind,
    ExecutionCostCompatibility,
    ExecutionCostDecisionReason,
    ExecutionCostPolicy,
    ExecutionCostReadinessDecision,
    ExecutionCostRuleSnapshot,
    ExecutionCostSourceKind,
    FeeModelKind,
    FundingModelKind,
)
from futures_bot.domain.time import ensure_aware_utc


def evaluate_execution_cost_readiness(  # noqa: PLR0911, PLR0912, PLR0913
    *,
    policy: ExecutionCostPolicy,
    checked_at: datetime,
    snapshot: ExecutionCostRuleSnapshot | None = None,
    venue_id: str | None = None,
    instrument_id: str | None = None,
    fee_asset: AssetSymbol | str | None = None,
    funding_asset: AssetSymbol | str | None = None,
    depth_reference_asset: AssetSymbol | str | None = None,
) -> ExecutionCostReadinessDecision:
    checked_at = ensure_aware_utc(checked_at)
    requested_fee_asset = _asset_or_none(fee_asset)
    requested_funding_asset = _asset_or_none(funding_asset)
    requested_depth_reference_asset = _asset_or_none(depth_reference_asset)

    if _policy_disabled(policy):
        return _decision(
            policy=policy,
            checked_at=checked_at,
            reason=ExecutionCostDecisionReason.POLICY_DISABLED,
            compatibility=ExecutionCostCompatibility.UNKNOWN,
            details={"policy_disabled": True},
        )
    if not isinstance(snapshot, ExecutionCostRuleSnapshot):
        return _decision(
            policy=policy,
            checked_at=checked_at,
            reason=ExecutionCostDecisionReason.SNAPSHOT_MISSING,
            compatibility=ExecutionCostCompatibility.UNKNOWN,
            details={"snapshot_type": None if snapshot is None else type(snapshot).__name__},
        )

    common = _common_decision_fields(snapshot)
    if snapshot.observed_at > checked_at or snapshot.captured_at > checked_at:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=ExecutionCostDecisionReason.SNAPSHOT_FUTURE_DATED,
            details=common,
        )
    age_ms = int((checked_at - snapshot.observed_at).total_seconds() * 1000)
    if age_ms > policy.max_snapshot_age:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=ExecutionCostDecisionReason.SNAPSHOT_STALE,
            details=common | {"age_ms": age_ms},
        )
    if policy.require_source_record and snapshot.source_record_id is None:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=ExecutionCostDecisionReason.SOURCE_RECORD_REQUIRED,
            details=common,
        )
    if snapshot.source_kind is ExecutionCostSourceKind.UNKNOWN:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=ExecutionCostDecisionReason.SOURCE_KIND_UNKNOWN,
            details=common,
        )
    if snapshot.source_kind not in policy.allowed_source_kinds:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=ExecutionCostDecisionReason.SOURCE_KIND_UNSUPPORTED,
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
            reason=ExecutionCostDecisionReason.SOURCE_UNTRUSTED,
            details=common,
        )
    if snapshot.source_health not in policy.allowed_source_health:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=ExecutionCostDecisionReason.SOURCE_UNHEALTHY,
            details=common,
        )
    if venue_id is not None and snapshot.venue_id != venue_id:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=ExecutionCostDecisionReason.VENUE_MISMATCH,
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
            reason=ExecutionCostDecisionReason.INSTRUMENT_MISMATCH,
            details=common | {"required_instrument_id": instrument_id},
        )

    model_reason = _model_reason(policy, snapshot)
    if model_reason is not None:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=model_reason,
            compatibility=ExecutionCostCompatibility.MODEL_UNSUPPORTED,
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
        fee_asset=requested_fee_asset,
        funding_asset=requested_funding_asset,
        depth_reference_asset=requested_depth_reference_asset,
    )
    if asset_reason is not None:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=asset_reason,
            compatibility=ExecutionCostCompatibility.ASSET_MISMATCH,
            details=common,
        )
    return _decision(
        policy=policy,
        checked_at=checked_at,
        snapshot=snapshot,
        ready=True,
        reason=ExecutionCostDecisionReason.READY,
        compatibility=ExecutionCostCompatibility.DIRECT_MATCH,
        details=common,
    )


def _model_reason(  # noqa: PLR0911
    policy: ExecutionCostPolicy,
    snapshot: ExecutionCostRuleSnapshot,
) -> ExecutionCostDecisionReason | None:
    if policy.require_fee_model:
        if snapshot.fee_model_kind is FeeModelKind.UNKNOWN:
            return ExecutionCostDecisionReason.FEE_MODEL_UNKNOWN
        if snapshot.fee_model_kind is FeeModelKind.NOT_PROVIDED:
            return ExecutionCostDecisionReason.FEE_MODEL_MISSING
        if snapshot.fee_model_kind not in policy.allowed_fee_models:
            return ExecutionCostDecisionReason.FEE_MODEL_UNSUPPORTED
    if policy.require_funding_model:
        if snapshot.funding_model_kind is FundingModelKind.UNKNOWN:
            return ExecutionCostDecisionReason.FUNDING_MODEL_UNKNOWN
        if snapshot.funding_model_kind is FundingModelKind.NOT_PROVIDED:
            return ExecutionCostDecisionReason.FUNDING_MODEL_MISSING
        if snapshot.funding_model_kind not in policy.allowed_funding_models:
            return ExecutionCostDecisionReason.FUNDING_MODEL_UNSUPPORTED
    if policy.require_depth_model:
        if snapshot.depth_model_kind is DepthModelKind.UNKNOWN:
            return ExecutionCostDecisionReason.DEPTH_MODEL_UNKNOWN
        if snapshot.depth_model_kind is DepthModelKind.NOT_PROVIDED:
            return ExecutionCostDecisionReason.DEPTH_MODEL_MISSING
        if snapshot.depth_model_kind not in policy.allowed_depth_models:
            return ExecutionCostDecisionReason.DEPTH_MODEL_UNSUPPORTED
    return None


def _required_field_reason(
    policy: ExecutionCostPolicy,
    snapshot: ExecutionCostRuleSnapshot,
) -> ExecutionCostDecisionReason | None:
    checks = (
        (
            policy.require_maker_fee and snapshot.maker_fee_rate is None,
            ExecutionCostDecisionReason.MAKER_FEE_MISSING,
        ),
        (
            policy.require_taker_fee and snapshot.taker_fee_rate is None,
            ExecutionCostDecisionReason.TAKER_FEE_MISSING,
        ),
        (
            policy.require_funding_interval and snapshot.funding_interval_ms is None,
            ExecutionCostDecisionReason.FUNDING_INTERVAL_MISSING,
        ),
        (
            policy.require_min_depth_notional and snapshot.min_depth_notional is None,
            ExecutionCostDecisionReason.MIN_DEPTH_NOTIONAL_MISSING,
        ),
        (
            policy.require_max_spread_bps and snapshot.max_spread_bps is None,
            ExecutionCostDecisionReason.MAX_SPREAD_MISSING,
        ),
    )
    for failed, reason in checks:
        if failed:
            return reason
    return None


def _asset_path_reason(  # noqa: PLR0911
    *,
    policy: ExecutionCostPolicy,
    snapshot: ExecutionCostRuleSnapshot,
    fee_asset: AssetSymbol | None,
    funding_asset: AssetSymbol | None,
    depth_reference_asset: AssetSymbol | None,
) -> ExecutionCostDecisionReason | None:
    if policy.require_fee_asset_match:
        if fee_asset is None or snapshot.fee_asset is None:
            return ExecutionCostDecisionReason.FEE_ASSET_MISSING
        if str(snapshot.fee_asset) != str(fee_asset):
            return ExecutionCostDecisionReason.FEE_ASSET_MISMATCH
    if policy.require_funding_asset_match:
        if funding_asset is None or snapshot.funding_asset is None:
            return ExecutionCostDecisionReason.FUNDING_ASSET_MISSING
        if str(snapshot.funding_asset) != str(funding_asset):
            return ExecutionCostDecisionReason.FUNDING_ASSET_MISMATCH
    if policy.require_depth_reference_asset_match:
        if depth_reference_asset is None or snapshot.depth_reference_asset is None:
            return ExecutionCostDecisionReason.DEPTH_REFERENCE_ASSET_MISSING
        if str(snapshot.depth_reference_asset) != str(depth_reference_asset):
            return ExecutionCostDecisionReason.DEPTH_REFERENCE_ASSET_MISMATCH
    return None


def _not_ready(  # noqa: PLR0913
    *,
    policy: ExecutionCostPolicy,
    checked_at: datetime,
    snapshot: ExecutionCostRuleSnapshot,
    reason: ExecutionCostDecisionReason,
    details: object,
    compatibility: ExecutionCostCompatibility = ExecutionCostCompatibility.NOT_COMPATIBLE,
) -> ExecutionCostReadinessDecision:
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
    policy: ExecutionCostPolicy,
    checked_at: datetime,
    reason: ExecutionCostDecisionReason,
    compatibility: ExecutionCostCompatibility,
    details: object,
    snapshot: ExecutionCostRuleSnapshot | None = None,
    ready: bool = False,
) -> ExecutionCostReadinessDecision:
    if policy.policy_id is None:
        raise ValueError("execution cost policy must have policy_id")
    return ExecutionCostReadinessDecision(
        policy_id=policy.policy_id,
        venue_id=None if snapshot is None else snapshot.venue_id,
        instrument_id=None if snapshot is None else snapshot.instrument_id,
        fee_asset=None if snapshot is None else snapshot.fee_asset,
        funding_asset=None if snapshot is None else snapshot.funding_asset,
        depth_reference_asset=None if snapshot is None else snapshot.depth_reference_asset,
        ready=ready,
        reason=reason,
        compatibility=compatibility,
        snapshot_id=None if snapshot is None else snapshot.snapshot_id,
        checked_at=checked_at,
        details=details,
    )


def _common_decision_fields(snapshot: ExecutionCostRuleSnapshot) -> dict[str, object]:
    return {
        "venue_id": snapshot.venue_id,
        "instrument_id": snapshot.instrument_id,
        "source_kind": snapshot.source_kind.value,
        "fee_model_kind": snapshot.fee_model_kind.value,
        "funding_model_kind": snapshot.funding_model_kind.value,
        "depth_model_kind": snapshot.depth_model_kind.value,
    }


def _policy_disabled(policy: ExecutionCostPolicy) -> bool:
    disabled = policy.metadata.get("policy_disabled")
    return disabled is True


def _asset_or_none(value: AssetSymbol | str | None) -> AssetSymbol | None:
    if value is None:
        return None
    return value if isinstance(value, AssetSymbol) else AssetSymbol(value)
