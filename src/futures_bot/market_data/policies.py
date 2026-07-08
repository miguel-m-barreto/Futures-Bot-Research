from __future__ import annotations

from datetime import datetime

from futures_bot.domain.assets import AssetSymbol
from futures_bot.domain.market_data import (
    MarketDataCompatibility,
    MarketDataContinuityStatus,
    MarketDataObservationKind,
    MarketDataObservationSnapshot,
    MarketDataReadinessDecision,
    MarketDataReadinessPolicy,
    MarketDataReadinessReason,
    MarketDataSourceKind,
)
from futures_bot.domain.time import ensure_aware_utc


def evaluate_market_data_readiness(  # noqa: PLR0911, PLR0913
    *,
    policy: MarketDataReadinessPolicy,
    checked_at: datetime,
    snapshot: MarketDataObservationSnapshot | None = None,
    venue_id: str | None = None,
    instrument_id: str | None = None,
    observation_kind: MarketDataObservationKind | str | None = None,
    depth_reference_asset: AssetSymbol | str | None = None,
) -> MarketDataReadinessDecision:
    checked_at = ensure_aware_utc(checked_at)
    requested_kind = _kind_or_none(observation_kind)
    requested_depth_reference_asset = _asset_or_none(depth_reference_asset)

    if _policy_disabled(policy):
        return _decision(
            policy=policy,
            checked_at=checked_at,
            reason=MarketDataReadinessReason.POLICY_DISABLED,
            compatibility=MarketDataCompatibility.UNKNOWN,
            details={"policy_disabled": True},
        )
    if not isinstance(snapshot, MarketDataObservationSnapshot):
        return _decision(
            policy=policy,
            checked_at=checked_at,
            reason=MarketDataReadinessReason.SNAPSHOT_MISSING,
            compatibility=MarketDataCompatibility.UNKNOWN,
            details={"snapshot_type": None if snapshot is None else type(snapshot).__name__},
        )

    common = _common_decision_fields(snapshot)
    if snapshot.observed_at > checked_at or snapshot.captured_at > checked_at:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=MarketDataReadinessReason.SNAPSHOT_FUTURE_DATED,
            details=common,
        )
    age_ms = int((checked_at - snapshot.observed_at).total_seconds() * 1000)
    if age_ms > policy.max_observation_age:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=MarketDataReadinessReason.SNAPSHOT_STALE,
            details=common | {"age_ms": age_ms},
        )

    source_reason = _source_reason(policy, snapshot)
    if source_reason is not None:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=source_reason,
            compatibility=(
                MarketDataCompatibility.SOURCE_UNSUPPORTED
                if source_reason
                in {
                    MarketDataReadinessReason.SOURCE_KIND_UNKNOWN,
                    MarketDataReadinessReason.SOURCE_KIND_UNSUPPORTED,
                }
                else MarketDataCompatibility.NOT_COMPATIBLE
            ),
            details=common,
        )

    kind_reason = _kind_reason(policy, snapshot, requested_kind)
    if kind_reason is not None:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=kind_reason,
            compatibility=MarketDataCompatibility.KIND_UNSUPPORTED,
            details=common,
        )

    if venue_id is not None and snapshot.venue_id != venue_id:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=MarketDataReadinessReason.VENUE_MISMATCH,
            compatibility=MarketDataCompatibility.SCOPE_MISMATCH,
            details=common | {"required_venue_id": venue_id},
        )
    if instrument_id is not None and snapshot.instrument_id != instrument_id:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=MarketDataReadinessReason.INSTRUMENT_MISMATCH,
            compatibility=MarketDataCompatibility.SCOPE_MISMATCH,
            details=common | {"required_instrument_id": instrument_id},
        )

    continuity_reason = _continuity_reason(policy, snapshot)
    if continuity_reason is not None:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=continuity_reason,
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
    depth_reason = _depth_reference_reason(
        policy=policy,
        snapshot=snapshot,
        depth_reference_asset=requested_depth_reference_asset,
    )
    if depth_reason is not None:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            snapshot=snapshot,
            reason=depth_reason,
            compatibility=MarketDataCompatibility.SCOPE_MISMATCH,
            details=common,
        )

    return _decision(
        policy=policy,
        checked_at=checked_at,
        snapshot=snapshot,
        ready=True,
        reason=MarketDataReadinessReason.READY,
        compatibility=MarketDataCompatibility.DIRECT_MATCH,
        details=common,
    )


def _source_reason(
    policy: MarketDataReadinessPolicy,
    snapshot: MarketDataObservationSnapshot,
) -> MarketDataReadinessReason | None:
    if policy.require_source_record and snapshot.source_record_id is None:
        return MarketDataReadinessReason.SOURCE_RECORD_REQUIRED
    if snapshot.source_kind is MarketDataSourceKind.UNKNOWN:
        return MarketDataReadinessReason.SOURCE_KIND_UNKNOWN
    if snapshot.source_kind not in policy.allowed_source_kinds:
        return MarketDataReadinessReason.SOURCE_KIND_UNSUPPORTED
    if snapshot.source_trust not in policy.allowed_source_trust:
        return MarketDataReadinessReason.SOURCE_UNTRUSTED
    if snapshot.source_health not in policy.allowed_source_health:
        return MarketDataReadinessReason.SOURCE_UNHEALTHY
    return None


def _kind_reason(
    policy: MarketDataReadinessPolicy,
    snapshot: MarketDataObservationSnapshot,
    requested_kind: MarketDataObservationKind | None,
) -> MarketDataReadinessReason | None:
    if snapshot.observation_kind is MarketDataObservationKind.UNKNOWN:
        return MarketDataReadinessReason.OBSERVATION_KIND_UNKNOWN
    if snapshot.observation_kind not in policy.allowed_observation_kinds:
        return MarketDataReadinessReason.OBSERVATION_KIND_UNSUPPORTED
    if requested_kind is not None and snapshot.observation_kind is not requested_kind:
        return MarketDataReadinessReason.OBSERVATION_KIND_UNSUPPORTED
    return None


def _continuity_reason(  # noqa: PLR0911
    policy: MarketDataReadinessPolicy,
    snapshot: MarketDataObservationSnapshot,
) -> MarketDataReadinessReason | None:
    if snapshot.continuity_status is MarketDataContinuityStatus.UNKNOWN:
        return MarketDataReadinessReason.CONTINUITY_UNKNOWN
    if snapshot.continuity_status not in policy.allowed_continuity_statuses:
        return MarketDataReadinessReason.CONTINUITY_GAPPED
    if policy.require_continuous_sequence:
        if snapshot.continuity_status is not MarketDataContinuityStatus.CONTINUOUS:
            return MarketDataReadinessReason.CONTINUITY_GAPPED
        if (
            snapshot.sequence_number is None
            or snapshot.previous_sequence_number is None
        ):
            return MarketDataReadinessReason.SEQUENCE_REQUIRED
        allowed = {
            snapshot.previous_sequence_number,
            snapshot.previous_sequence_number + 1,
        }
        if snapshot.sequence_number not in allowed:
            return MarketDataReadinessReason.SEQUENCE_GAP_DECLARED
    elif policy.require_sequence and snapshot.sequence_number is None:
        return MarketDataReadinessReason.SEQUENCE_REQUIRED
    return None


def _required_field_reason(
    policy: MarketDataReadinessPolicy,
    snapshot: MarketDataObservationSnapshot,
) -> MarketDataReadinessReason | None:
    checks = (
        (
            policy.require_best_bid and snapshot.best_bid_price is None,
            MarketDataReadinessReason.BID_MISSING,
        ),
        (
            policy.require_best_ask and snapshot.best_ask_price is None,
            MarketDataReadinessReason.ASK_MISSING,
        ),
        (
            policy.require_bid_ask_not_crossed
            and (
                snapshot.best_bid_price is None
                or snapshot.best_ask_price is None
                or snapshot.best_bid_price > snapshot.best_ask_price
            ),
            MarketDataReadinessReason.BID_ASK_CROSSED,
        ),
        (
            policy.require_mark_price and snapshot.mark_price is None,
            MarketDataReadinessReason.MARK_PRICE_MISSING,
        ),
        (
            policy.require_index_price and snapshot.index_price is None,
            MarketDataReadinessReason.INDEX_PRICE_MISSING,
        ),
        (
            policy.require_last_trade_price and snapshot.last_trade_price is None,
            MarketDataReadinessReason.LAST_PRICE_MISSING,
        ),
        (
            policy.require_depth_notional and snapshot.depth_notional is None,
            MarketDataReadinessReason.DEPTH_NOTIONAL_MISSING,
        ),
        (
            policy.require_spread_bps and snapshot.spread_bps is None,
            MarketDataReadinessReason.SPREAD_MISSING,
        ),
        (
            policy.max_spread_bps is not None
            and (
                snapshot.spread_bps is None
                or snapshot.spread_bps > policy.max_spread_bps
            ),
            MarketDataReadinessReason.SPREAD_TOO_WIDE,
        ),
    )
    for failed, reason in checks:
        if failed:
            return reason
    return None


def _depth_reference_reason(
    *,
    policy: MarketDataReadinessPolicy,
    snapshot: MarketDataObservationSnapshot,
    depth_reference_asset: AssetSymbol | None,
) -> MarketDataReadinessReason | None:
    if not policy.require_depth_reference_asset_match:
        return None
    if depth_reference_asset is None or snapshot.depth_reference_asset is None:
        return MarketDataReadinessReason.DEPTH_REFERENCE_ASSET_MISSING
    if str(snapshot.depth_reference_asset) != str(depth_reference_asset):
        return MarketDataReadinessReason.DEPTH_REFERENCE_ASSET_MISMATCH
    return None


def _not_ready(  # noqa: PLR0913
    *,
    policy: MarketDataReadinessPolicy,
    checked_at: datetime,
    snapshot: MarketDataObservationSnapshot,
    reason: MarketDataReadinessReason,
    details: object,
    compatibility: MarketDataCompatibility = MarketDataCompatibility.NOT_COMPATIBLE,
) -> MarketDataReadinessDecision:
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
    policy: MarketDataReadinessPolicy,
    checked_at: datetime,
    reason: MarketDataReadinessReason,
    compatibility: MarketDataCompatibility,
    details: object,
    snapshot: MarketDataObservationSnapshot | None = None,
    ready: bool = False,
) -> MarketDataReadinessDecision:
    if policy.policy_id is None:
        raise ValueError("market data policy must have policy_id")
    return MarketDataReadinessDecision(
        policy_id=policy.policy_id,
        venue_id=None if snapshot is None else snapshot.venue_id,
        instrument_id=None if snapshot is None else snapshot.instrument_id,
        observation_kind=None if snapshot is None else snapshot.observation_kind,
        depth_reference_asset=None if snapshot is None else snapshot.depth_reference_asset,
        ready=ready,
        reason=reason,
        compatibility=compatibility,
        snapshot_id=None if snapshot is None else snapshot.snapshot_id,
        checked_at=checked_at,
        details=details,
    )


def _common_decision_fields(snapshot: MarketDataObservationSnapshot) -> dict[str, object]:
    return {
        "venue_id": snapshot.venue_id,
        "instrument_id": snapshot.instrument_id,
        "observation_kind": snapshot.observation_kind.value,
        "source_kind": snapshot.source_kind.value,
        "continuity_status": snapshot.continuity_status.value,
    }


def _policy_disabled(policy: MarketDataReadinessPolicy) -> bool:
    disabled = policy.metadata.get("policy_disabled")
    return disabled is True


def _kind_or_none(
    value: MarketDataObservationKind | str | None,
) -> MarketDataObservationKind | None:
    if value is None:
        return None
    return (
        value
        if isinstance(value, MarketDataObservationKind)
        else MarketDataObservationKind(value)
    )


def _asset_or_none(value: AssetSymbol | str | None) -> AssetSymbol | None:
    if value is None:
        return None
    return value if isinstance(value, AssetSymbol) else AssetSymbol(value)
