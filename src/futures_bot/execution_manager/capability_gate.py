from __future__ import annotations

from futures_bot.domain.execution_capability_gate import (
    ExecutionCapabilityCheck,
    ExecutionCapabilityDecision,
    ExecutionCapabilityDecisionReason,
)
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
            decided_at=check.requested_at,
        )
