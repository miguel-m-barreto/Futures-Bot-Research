from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from futures_bot.domain.asset_conversion import (
    AssetConversionCompatibility,
    AssetConversionDecisionReason,
    AssetConversionEvidenceKind,
    AssetConversionPolicy,
    AssetConversionRateSnapshot,
    AssetConversionReadinessDecision,
)
from futures_bot.domain.assets import AssetSymbol
from futures_bot.domain.ids import (
    AssetConversionRateSnapshotId,
    AssetConversionReadinessDecisionId,
)
from futures_bot.domain.time import ensure_aware_utc


def evaluate_asset_conversion_readiness(  # noqa: PLR0911, PLR0913
    *,
    policy: AssetConversionPolicy,
    checked_at: datetime,
    from_asset: AssetSymbol | str | None,
    to_asset: AssetSymbol | str | None,
    rate_snapshot: AssetConversionRateSnapshot | None = None,
    inverse_rate_snapshot: AssetConversionRateSnapshot | None = None,
    leg_decisions: tuple[AssetConversionReadinessDecision, ...] = (),
) -> AssetConversionReadinessDecision:
    checked_at = ensure_aware_utc(checked_at)
    source_asset = _asset_or_none(from_asset)
    target_asset = _asset_or_none(to_asset)

    if _policy_disabled(policy):
        return _decision(
            policy=policy,
            checked_at=checked_at,
            from_asset=source_asset,
            to_asset=target_asset,
            reason=AssetConversionDecisionReason.POLICY_DISABLED,
            compatibility=AssetConversionCompatibility.UNKNOWN,
            details={"policy_disabled": True},
        )
    if source_asset is None:
        return _decision(
            policy=policy,
            checked_at=checked_at,
            from_asset=source_asset,
            to_asset=target_asset,
            reason=AssetConversionDecisionReason.FROM_ASSET_MISSING,
            compatibility=AssetConversionCompatibility.UNKNOWN,
            details={"missing": "from_asset"},
        )
    if target_asset is None:
        return _decision(
            policy=policy,
            checked_at=checked_at,
            from_asset=source_asset,
            to_asset=target_asset,
            reason=AssetConversionDecisionReason.TO_ASSET_MISSING,
            compatibility=AssetConversionCompatibility.UNKNOWN,
            details={"missing": "to_asset"},
        )
    policy_pair_reason = _policy_pair_reason(policy, source_asset, target_asset)
    if policy_pair_reason is not None:
        return _decision(
            policy=policy,
            checked_at=checked_at,
            from_asset=source_asset,
            to_asset=target_asset,
            reason=policy_pair_reason,
            compatibility=AssetConversionCompatibility.NOT_COMPATIBLE,
            details={
                "from_asset": str(source_asset),
                "to_asset": str(target_asset),
            },
        )
    if source_asset == target_asset:
        return _same_asset_decision(
            policy=policy,
            checked_at=checked_at,
            asset=source_asset,
        )
    if rate_snapshot is not None:
        if not isinstance(rate_snapshot, AssetConversionRateSnapshot):
            return _unsupported_evidence_decision(
                policy=policy,
                checked_at=checked_at,
                from_asset=source_asset,
                to_asset=target_asset,
                evidence_name=type(rate_snapshot).__name__,
            )
        return _direct_snapshot_decision(
            policy=policy,
            checked_at=checked_at,
            from_asset=source_asset,
            to_asset=target_asset,
            snapshot=rate_snapshot,
        )
    if inverse_rate_snapshot is not None:
        if not isinstance(inverse_rate_snapshot, AssetConversionRateSnapshot):
            return _unsupported_evidence_decision(
                policy=policy,
                checked_at=checked_at,
                from_asset=source_asset,
                to_asset=target_asset,
                evidence_name=type(inverse_rate_snapshot).__name__,
            )
        return _inverse_snapshot_decision(
            policy=policy,
            checked_at=checked_at,
            from_asset=source_asset,
            to_asset=target_asset,
            snapshot=inverse_rate_snapshot,
        )
    if leg_decisions:
        return _triangulated_decision(
            policy=policy,
            checked_at=checked_at,
            from_asset=source_asset,
            to_asset=target_asset,
            leg_decisions=leg_decisions,
        )
    return _decision(
        policy=policy,
        checked_at=checked_at,
        from_asset=source_asset,
        to_asset=target_asset,
        reason=AssetConversionDecisionReason.CONVERSION_RATE_MISSING,
        compatibility=AssetConversionCompatibility.UNKNOWN,
        details={"from_asset": str(source_asset), "to_asset": str(target_asset)},
    )


def _unsupported_evidence_decision(
    *,
    policy: AssetConversionPolicy,
    checked_at: datetime,
    from_asset: AssetSymbol,
    to_asset: AssetSymbol,
    evidence_name: str,
) -> AssetConversionReadinessDecision:
    return _decision(
        policy=policy,
        checked_at=checked_at,
        from_asset=from_asset,
        to_asset=to_asset,
        reason=AssetConversionDecisionReason.CONVERSION_RATE_MISSING,
        compatibility=AssetConversionCompatibility.UNKNOWN,
        details={"unsupported_evidence_type": evidence_name},
    )


def _same_asset_decision(
    *,
    policy: AssetConversionPolicy,
    checked_at: datetime,
    asset: AssetSymbol,
) -> AssetConversionReadinessDecision:
    if policy.allow_same_asset_direct_match:
        return _decision(
            policy=policy,
            checked_at=checked_at,
            from_asset=asset,
            to_asset=asset,
            ready=True,
            reason=AssetConversionDecisionReason.READY,
            compatibility=AssetConversionCompatibility.DIRECT_SAME_ASSET,
            effective_rate=Decimal("1"),
            details={"same_asset_direct_match": str(asset)},
        )
    return _decision(
        policy=policy,
        checked_at=checked_at,
        from_asset=asset,
        to_asset=asset,
        reason=AssetConversionDecisionReason.SAME_ASSET_DIRECT_MATCH,
        compatibility=AssetConversionCompatibility.NOT_COMPATIBLE,
        details={"same_asset_direct_match_allowed": False},
    )


def _direct_snapshot_decision(
    *,
    policy: AssetConversionPolicy,
    checked_at: datetime,
    from_asset: AssetSymbol,
    to_asset: AssetSymbol,
    snapshot: AssetConversionRateSnapshot,
) -> AssetConversionReadinessDecision:
    if str(snapshot.from_asset) != str(from_asset) or str(snapshot.to_asset) != str(
        to_asset
    ):
        return _snapshot_rejected(
            policy=policy,
            checked_at=checked_at,
            from_asset=from_asset,
            to_asset=to_asset,
            snapshot=snapshot,
            reason=AssetConversionDecisionReason.CONVERSION_PAIR_MISMATCH,
        )
    if not _direct_evidence_kind_allowed(snapshot.evidence_kind):
        return _snapshot_rejected(
            policy=policy,
            checked_at=checked_at,
            from_asset=from_asset,
            to_asset=to_asset,
            snapshot=snapshot,
            reason=AssetConversionDecisionReason.CONVERSION_RATE_MISSING,
        )
    reason = _snapshot_rejection_reason(policy, checked_at, snapshot)
    if reason is not None:
        return _snapshot_rejected(
            policy=policy,
            checked_at=checked_at,
            from_asset=from_asset,
            to_asset=to_asset,
            snapshot=snapshot,
            reason=reason,
        )
    return _decision(
        policy=policy,
        checked_at=checked_at,
        from_asset=from_asset,
        to_asset=to_asset,
        ready=True,
        reason=AssetConversionDecisionReason.READY,
        compatibility=AssetConversionCompatibility.DIRECT_RATE,
        snapshot_id=snapshot.snapshot_id,
        effective_rate=snapshot.rate,
        details={"direction": "FROM_TO"},
    )


def _inverse_snapshot_decision(
    *,
    policy: AssetConversionPolicy,
    checked_at: datetime,
    from_asset: AssetSymbol,
    to_asset: AssetSymbol,
    snapshot: AssetConversionRateSnapshot,
) -> AssetConversionReadinessDecision:
    if not policy.allow_inverse_rate:
        return _snapshot_rejected(
            policy=policy,
            checked_at=checked_at,
            from_asset=from_asset,
            to_asset=to_asset,
            snapshot=snapshot,
            reason=AssetConversionDecisionReason.CONVERSION_DIRECTION_NOT_ALLOWED,
            inverse=True,
        )
    if str(snapshot.from_asset) != str(to_asset) or str(snapshot.to_asset) != str(
        from_asset
    ):
        return _snapshot_rejected(
            policy=policy,
            checked_at=checked_at,
            from_asset=from_asset,
            to_asset=to_asset,
            snapshot=snapshot,
            reason=AssetConversionDecisionReason.CONVERSION_PAIR_MISMATCH,
            inverse=True,
        )
    if not _inverse_evidence_kind_allowed(snapshot.evidence_kind):
        return _snapshot_rejected(
            policy=policy,
            checked_at=checked_at,
            from_asset=from_asset,
            to_asset=to_asset,
            snapshot=snapshot,
            reason=AssetConversionDecisionReason.CONVERSION_RATE_MISSING,
            inverse=True,
        )
    reason = _snapshot_rejection_reason(policy, checked_at, snapshot)
    if reason is not None:
        return _snapshot_rejected(
            policy=policy,
            checked_at=checked_at,
            from_asset=from_asset,
            to_asset=to_asset,
            snapshot=snapshot,
            reason=reason,
            inverse=True,
        )
    return _decision(
        policy=policy,
        checked_at=checked_at,
        from_asset=from_asset,
        to_asset=to_asset,
        ready=True,
        reason=AssetConversionDecisionReason.READY,
        compatibility=AssetConversionCompatibility.INVERSE_RATE,
        inverse_snapshot_id=snapshot.snapshot_id,
        effective_rate=Decimal("1") / snapshot.rate,
        details={"direction": "TO_FROM_INVERTED"},
    )


def _triangulated_decision(  # noqa: PLR0911
    *,
    policy: AssetConversionPolicy,
    checked_at: datetime,
    from_asset: AssetSymbol,
    to_asset: AssetSymbol,
    leg_decisions: tuple[AssetConversionReadinessDecision, ...],
) -> AssetConversionReadinessDecision:
    if not policy.allow_triangulation:
        return _decision(
            policy=policy,
            checked_at=checked_at,
            from_asset=from_asset,
            to_asset=to_asset,
            reason=AssetConversionDecisionReason.TRIANGULATION_NOT_ALLOWED,
            compatibility=AssetConversionCompatibility.NOT_COMPATIBLE,
            leg_decision_ids=_leg_decision_ids(leg_decisions),
            details={"allow_triangulation": False},
        )
    current = from_asset
    effective_rate = Decimal("1")
    for index, leg in enumerate(leg_decisions):
        if not leg.ready:
            return _triangulation_rejected(
                policy=policy,
                checked_at=checked_at,
                from_asset=from_asset,
                to_asset=to_asset,
                leg_decisions=leg_decisions,
                reason=AssetConversionDecisionReason.TRIANGULATION_LEG_NOT_READY,
                details={"leg_index": index},
            )
        if leg.from_asset is None or leg.to_asset is None:
            return _triangulation_rejected(
                policy=policy,
                checked_at=checked_at,
                from_asset=from_asset,
                to_asset=to_asset,
                leg_decisions=leg_decisions,
                reason=AssetConversionDecisionReason.TRIANGULATION_LEG_MISSING,
                details={"leg_index": index},
            )
        if str(leg.from_asset) != str(current):
            return _triangulation_rejected(
                policy=policy,
                checked_at=checked_at,
                from_asset=from_asset,
                to_asset=to_asset,
                leg_decisions=leg_decisions,
                reason=AssetConversionDecisionReason.CONVERSION_PAIR_MISMATCH,
                details={
                    "leg_index": index,
                    "expected_from_asset": str(current),
                    "actual_from_asset": str(leg.from_asset),
                },
            )
        if leg.effective_rate is None:
            return _triangulation_rejected(
                policy=policy,
                checked_at=checked_at,
                from_asset=from_asset,
                to_asset=to_asset,
                leg_decisions=leg_decisions,
                reason=AssetConversionDecisionReason.TRIANGULATION_LEG_MISSING,
                details={"leg_index": index, "missing": "effective_rate"},
            )
        effective_rate *= leg.effective_rate
        current = leg.to_asset
    if str(current) != str(to_asset):
        return _triangulation_rejected(
            policy=policy,
            checked_at=checked_at,
            from_asset=from_asset,
            to_asset=to_asset,
            leg_decisions=leg_decisions,
            reason=AssetConversionDecisionReason.CONVERSION_PAIR_MISMATCH,
            details={"terminal_asset": str(current), "required_asset": str(to_asset)},
        )
    return _decision(
        policy=policy,
        checked_at=checked_at,
        from_asset=from_asset,
        to_asset=to_asset,
        ready=True,
        reason=AssetConversionDecisionReason.READY,
        compatibility=AssetConversionCompatibility.TRIANGULATED_RATE,
        leg_decision_ids=_leg_decision_ids(leg_decisions),
        effective_rate=effective_rate,
        details={"leg_count": len(leg_decisions)},
    )


def _snapshot_rejection_reason(  # noqa: PLR0911
    policy: AssetConversionPolicy,
    checked_at: datetime,
    snapshot: AssetConversionRateSnapshot,
) -> AssetConversionDecisionReason | None:
    if snapshot.observed_at > checked_at or snapshot.captured_at > checked_at:
        return AssetConversionDecisionReason.CONVERSION_RATE_FUTURE_DATED
    age_ms = int((checked_at - snapshot.observed_at).total_seconds() * 1000)
    if age_ms > policy.max_rate_age:
        return AssetConversionDecisionReason.CONVERSION_RATE_STALE
    if snapshot.source_trust not in policy.allowed_source_trust:
        return AssetConversionDecisionReason.CONVERSION_SOURCE_UNTRUSTED
    if snapshot.source_health not in policy.allowed_source_health:
        return AssetConversionDecisionReason.CONVERSION_SOURCE_UNHEALTHY
    if policy.require_source_record and snapshot.source_record_id is None:
        return AssetConversionDecisionReason.CONVERSION_RATE_MISSING
    if policy.require_bid_ask and (snapshot.bid is None or snapshot.ask is None):
        return AssetConversionDecisionReason.CONVERSION_RATE_MISSING
    if (
        policy.max_spread_bps is not None
        and snapshot.spread_bps is not None
        and snapshot.spread_bps > policy.max_spread_bps
    ):
        return AssetConversionDecisionReason.CONVERSION_SPREAD_TOO_WIDE
    return None


def _direct_evidence_kind_allowed(evidence_kind: AssetConversionEvidenceKind) -> bool:
    return evidence_kind in {
        AssetConversionEvidenceKind.DIRECT_PAIR_RATE,
        AssetConversionEvidenceKind.MANUAL_OFFICIAL_RATE,
        AssetConversionEvidenceKind.REFERENCE_INDEX_VALUE,
    }


def _inverse_evidence_kind_allowed(evidence_kind: AssetConversionEvidenceKind) -> bool:
    return evidence_kind in {
        AssetConversionEvidenceKind.DIRECT_PAIR_RATE,
        AssetConversionEvidenceKind.INVERSE_PAIR_RATE,
        AssetConversionEvidenceKind.MANUAL_OFFICIAL_RATE,
        AssetConversionEvidenceKind.REFERENCE_INDEX_VALUE,
    }


def _snapshot_rejected(  # noqa: PLR0913
    *,
    policy: AssetConversionPolicy,
    checked_at: datetime,
    from_asset: AssetSymbol,
    to_asset: AssetSymbol,
    snapshot: AssetConversionRateSnapshot,
    reason: AssetConversionDecisionReason,
    inverse: bool = False,
) -> AssetConversionReadinessDecision:
    return _decision(
        policy=policy,
        checked_at=checked_at,
        from_asset=from_asset,
        to_asset=to_asset,
        reason=reason,
        compatibility=AssetConversionCompatibility.NOT_COMPATIBLE,
        snapshot_id=None if inverse else snapshot.snapshot_id,
        inverse_snapshot_id=snapshot.snapshot_id if inverse else None,
        details={
            "snapshot_from_asset": str(snapshot.from_asset),
            "snapshot_to_asset": str(snapshot.to_asset),
        },
    )


def _triangulation_rejected(  # noqa: PLR0913
    *,
    policy: AssetConversionPolicy,
    checked_at: datetime,
    from_asset: AssetSymbol,
    to_asset: AssetSymbol,
    leg_decisions: tuple[AssetConversionReadinessDecision, ...],
    reason: AssetConversionDecisionReason,
    details: dict[str, object],
) -> AssetConversionReadinessDecision:
    return _decision(
        policy=policy,
        checked_at=checked_at,
        from_asset=from_asset,
        to_asset=to_asset,
        reason=reason,
        compatibility=AssetConversionCompatibility.NOT_COMPATIBLE,
        leg_decision_ids=_leg_decision_ids(leg_decisions),
        details=details,
    )


def _decision(  # noqa: PLR0913
    *,
    policy: AssetConversionPolicy,
    checked_at: datetime,
    from_asset: AssetSymbol | None,
    to_asset: AssetSymbol | None,
    reason: AssetConversionDecisionReason,
    compatibility: AssetConversionCompatibility,
    details: object,
    ready: bool = False,
    snapshot_id: AssetConversionRateSnapshotId | None = None,
    inverse_snapshot_id: AssetConversionRateSnapshotId | None = None,
    leg_decision_ids: tuple[AssetConversionReadinessDecisionId, ...] = (),
    effective_rate: Decimal | None = None,
) -> AssetConversionReadinessDecision:
    if policy.policy_id is None:
        raise ValueError("asset conversion policy must have policy_id")
    return AssetConversionReadinessDecision(
        policy_id=policy.policy_id,
        from_asset=from_asset,
        to_asset=to_asset,
        ready=ready,
        reason=reason,
        compatibility=compatibility,
        snapshot_id=snapshot_id,
        inverse_snapshot_id=inverse_snapshot_id,
        leg_decision_ids=leg_decision_ids,
        checked_at=checked_at,
        effective_rate=effective_rate,
        details=details,
    )


def _policy_pair_reason(
    policy: AssetConversionPolicy,
    from_asset: AssetSymbol,
    to_asset: AssetSymbol,
) -> AssetConversionDecisionReason | None:
    if policy.from_asset is not None and str(policy.from_asset) != str(from_asset):
        return AssetConversionDecisionReason.CONVERSION_PAIR_MISMATCH
    if policy.to_asset is not None and str(policy.to_asset) != str(to_asset):
        return AssetConversionDecisionReason.CONVERSION_PAIR_MISMATCH
    return None


def _policy_disabled(policy: AssetConversionPolicy) -> bool:
    disabled = policy.metadata.get("policy_disabled")
    return disabled is True


def _asset_or_none(value: AssetSymbol | str | None) -> AssetSymbol | None:
    if value is None:
        return None
    return value if isinstance(value, AssetSymbol) else AssetSymbol(value)


def _leg_decision_ids(
    leg_decisions: tuple[AssetConversionReadinessDecision, ...],
) -> tuple[AssetConversionReadinessDecisionId, ...]:
    return tuple(
        decision.decision_id
        for decision in leg_decisions
        if decision.decision_id is not None
    )
