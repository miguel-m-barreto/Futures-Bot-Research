from __future__ import annotations

from futures_bot.domain.execution_capability_gate import (
    ExecutionCapabilityCheck,
    ExecutionCapabilityDecision,
    ExecutionCapabilityDecisionReason,
)
from futures_bot.venue_capabilities.freshness import validate_venue_capability_freshness
from futures_bot.venue_capabilities.validator import validate_order_against_venue_capabilities


class DeterministicExecutionCapabilityGate:
    """Deterministic local capability gate. No API calls, no clock reads."""

    def check(
        self,
        check: ExecutionCapabilityCheck,
    ) -> ExecutionCapabilityDecision:
        if check.check_id is None:
            raise ValueError("check_id must be set before calling gate.check()")
        # Mismatch guard (check constructor already validates, but guard defensively)
        if check.venue_validation_context.order_intent != check.order_intent:
            return ExecutionCapabilityDecision(
                check_id=check.check_id,
                order_intent_id=check.order_intent.intent_id,
                client_order_id=check.order_intent.client_order_id,
                executable=False,
                reason=ExecutionCapabilityDecisionReason.VALIDATION_CONTEXT_MISMATCH,
                venue_validation_reason="VALIDATION_CONTEXT_MISMATCH",
                venue_validation_details={"message": "order_intent mismatch with context"},
                decided_at=check.requested_at,
            )
        if check.require_fresh_capability_snapshot:
            if check.freshness_check is None:
                return ExecutionCapabilityDecision(
                    check_id=check.check_id,
                    order_intent_id=check.order_intent.intent_id,
                    client_order_id=check.order_intent.client_order_id,
                    executable=False,
                    reason=ExecutionCapabilityDecisionReason.FRESHNESS_CONTEXT_REQUIRED,
                    freshness_checked=False,
                    decided_at=check.requested_at,
                )
            if _freshness_context_mismatch(check):
                return ExecutionCapabilityDecision(
                    check_id=check.check_id,
                    order_intent_id=check.order_intent.intent_id,
                    client_order_id=check.order_intent.client_order_id,
                    executable=False,
                    reason=ExecutionCapabilityDecisionReason.FRESHNESS_CONTEXT_MISMATCH,
                    freshness_checked=False,
                    freshness_details={"message": "freshness context mismatch"},
                    decided_at=check.requested_at,
                )
            freshness = validate_venue_capability_freshness(check.freshness_check)
            if not freshness.fresh:
                return ExecutionCapabilityDecision(
                    check_id=check.check_id,
                    order_intent_id=check.order_intent.intent_id,
                    client_order_id=check.order_intent.client_order_id,
                    executable=False,
                    reason=ExecutionCapabilityDecisionReason.REJECTED_BY_CAPABILITY_FRESHNESS,
                    freshness_reason=freshness.reason.value,
                    freshness_details=freshness.details,
                    freshness_checked=True,
                    decided_at=check.requested_at,
                )
            accepted_freshness_reason = freshness.reason.value
            accepted_freshness_details = freshness.details
        else:
            accepted_freshness_reason = None
            accepted_freshness_details = None

        result = validate_order_against_venue_capabilities(check.venue_validation_context)
        if result.valid:
            return ExecutionCapabilityDecision(
                check_id=check.check_id,
                order_intent_id=check.order_intent.intent_id,
                client_order_id=check.order_intent.client_order_id,
                executable=True,
                reason=ExecutionCapabilityDecisionReason.EXECUTABLE,
                venue_validation_reason=result.reason.value,
                venue_validation_details=result.details,
                freshness_reason=accepted_freshness_reason,
                freshness_details=accepted_freshness_details,
                freshness_checked=check.require_fresh_capability_snapshot,
                decided_at=check.requested_at,
            )
        return ExecutionCapabilityDecision(
            check_id=check.check_id,
            order_intent_id=check.order_intent.intent_id,
            client_order_id=check.order_intent.client_order_id,
            executable=False,
            reason=ExecutionCapabilityDecisionReason.REJECTED_BY_VENUE_CAPABILITY,
            venue_validation_reason=result.reason.value,
            venue_validation_details=result.details,
            freshness_reason=accepted_freshness_reason,
            freshness_details=accepted_freshness_details,
            freshness_checked=check.require_fresh_capability_snapshot,
            decided_at=check.requested_at,
        )


def _freshness_context_mismatch(check: ExecutionCapabilityCheck) -> bool:
    freshness = check.freshness_check
    if freshness is None:
        return True
    context = check.venue_validation_context
    return (
        freshness.venue_id != check.order_intent.venue_id
        or freshness.instrument_id != check.order_intent.instrument_id
        or freshness.venue_snapshot != context.venue_snapshot
        or freshness.instrument_rules != context.instrument_rules
    )
