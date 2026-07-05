from __future__ import annotations

from typing import Any

from futures_bot.domain.asset_semantics import validate_contract_asset_semantics_readiness
from futures_bot.domain.execution_capability_gate import ExecutionCapabilityDecision
from futures_bot.domain.execution_manager import ExecutionAdmissionRequest
from futures_bot.domain.execution_readiness import (
    ExecutionReadinessGate,
    ExecutionReadinessGateEvidence,
    ExecutionReadinessGateStatus,
    ExecutionReadinessProof,
    ExecutionReadinessProofReason,
)
from futures_bot.domain.order_lifecycle import OrderIntent, ReplaceOrderIntent
from futures_bot.domain.venue_capabilities import VenueOrderValidationContext
from futures_bot.order_lifecycle.policies import OrderIntentPermissionDecision


def build_order_execution_readiness_proof(  # noqa: PLR0913
    *,
    request: ExecutionAdmissionRequest,
    order_intent: OrderIntent,
    permission_decision: OrderIntentPermissionDecision,
    capability_decision: ExecutionCapabilityDecision | None,
    lifecycle_event_ids: tuple[Any, ...],
    created_at: Any,
) -> ExecutionReadinessProof:
    return ExecutionReadinessProof(
        order_intent_id=order_intent.intent_id,
        client_order_id=order_intent.client_order_id,
        request_id=request.request_id,
        lifecycle_event_ids=lifecycle_event_ids,
        gates=(
            _runtime_permission_gate(permission_decision),
            _venue_capability_gate(request, capability_decision),
            _capability_freshness_gate(request, capability_decision),
            _source_provenance_gate(request),
            _asset_semantics_gate(request.venue_validation_context),
            _idempotency_gate(),
        ),
        ready=True,
        reason=ExecutionReadinessProofReason.READY,
        created_at=created_at,
        details={
            "request_kind": request.request_kind.value,
            "venue_id": order_intent.venue_id,
            "instrument_id": order_intent.instrument_id,
            "local_acceptance_only": True,
        },
    )


def build_replace_execution_readiness_proof(  # noqa: PLR0913
    *,
    request: ExecutionAdmissionRequest,
    replace_intent: ReplaceOrderIntent,
    permission_decision: OrderIntentPermissionDecision,
    capability_decision: ExecutionCapabilityDecision | None,
    lifecycle_event_ids: tuple[Any, ...],
    created_at: Any,
) -> ExecutionReadinessProof:
    replacement = replace_intent.replacement_order
    return ExecutionReadinessProof(
        order_intent_id=replacement.intent_id,
        replace_intent_id=replace_intent.replace_intent_id,
        client_order_id=replacement.client_order_id,
        replacement_client_order_id=replacement.client_order_id,
        request_id=request.request_id,
        lifecycle_event_ids=lifecycle_event_ids,
        gates=(
            _runtime_permission_gate(permission_decision),
            _venue_capability_gate(request, capability_decision),
            _capability_freshness_gate(request, capability_decision),
            _source_provenance_gate(request),
            _asset_semantics_gate(request.venue_validation_context),
            ExecutionReadinessGateEvidence(
                gate=ExecutionReadinessGate.ORDER_SCOPE,
                status=ExecutionReadinessGateStatus.PASSED,
                required=True,
                reason="replacement_scope_matches_target",
                details={
                    "target_intent_kind": replace_intent.target_intent_kind.value,
                    "replacement_venue_id": replacement.venue_id,
                    "replacement_instrument_id": replacement.instrument_id,
                    "replacement_account_id": replacement.account_id,
                },
            ),
            ExecutionReadinessGateEvidence(
                gate=ExecutionReadinessGate.REPLACE_TARGET,
                status=ExecutionReadinessGateStatus.PASSED,
                required=True,
                reason="target_active",
                details={
                    "target_order_intent_id": _string_or_none(
                        replace_intent.target_order_intent_id
                    ),
                    "target_client_order_id": _string_or_none(
                        replace_intent.target_client_order_id
                    ),
                    "target_venue_order_id": _string_or_none(
                        replace_intent.target_venue_order_id
                    ),
                },
            ),
            _idempotency_gate(),
        ),
        ready=True,
        reason=ExecutionReadinessProofReason.READY,
        created_at=created_at,
        details={
            "request_kind": request.request_kind.value,
            "venue_id": replacement.venue_id,
            "instrument_id": replacement.instrument_id,
            "local_acceptance_only": True,
        },
    )


def _runtime_permission_gate(
    permission_decision: OrderIntentPermissionDecision,
) -> ExecutionReadinessGateEvidence:
    return ExecutionReadinessGateEvidence(
        gate=ExecutionReadinessGate.RUNTIME_PERMISSION,
        status=(
            ExecutionReadinessGateStatus.PASSED
            if permission_decision.allowed
            else ExecutionReadinessGateStatus.FAILED
        ),
        required=True,
        reason=permission_decision.reason.value,
        details={
            "requires_guardian": permission_decision.requires_guardian,
            "requires_reconciliation": permission_decision.requires_reconciliation,
        },
    )


def _venue_capability_gate(
    request: ExecutionAdmissionRequest,
    capability_decision: ExecutionCapabilityDecision | None,
) -> ExecutionReadinessGateEvidence:
    if not request.require_venue_capability_validation:
        return ExecutionReadinessGateEvidence(
            gate=ExecutionReadinessGate.VENUE_CAPABILITY,
            status=ExecutionReadinessGateStatus.NOT_REQUIRED,
            required=False,
            reason="venue_capability_validation_not_required",
            details={},
        )
    return ExecutionReadinessGateEvidence(
        gate=ExecutionReadinessGate.VENUE_CAPABILITY,
        status=(
            ExecutionReadinessGateStatus.PASSED
            if capability_decision is not None and capability_decision.executable
            else ExecutionReadinessGateStatus.FAILED
        ),
        required=True,
        reason=(
            capability_decision.venue_validation_reason
            if capability_decision is not None
            else "capability_decision_missing"
        ),
        details=(
            capability_decision.venue_validation_details
            if capability_decision is not None
            else {}
        ),
    )


def _capability_freshness_gate(
    request: ExecutionAdmissionRequest,
    capability_decision: ExecutionCapabilityDecision | None,
) -> ExecutionReadinessGateEvidence:
    if not request.require_fresh_capability_snapshot:
        return ExecutionReadinessGateEvidence(
            gate=ExecutionReadinessGate.CAPABILITY_FRESHNESS,
            status=ExecutionReadinessGateStatus.NOT_REQUIRED,
            required=False,
            reason="fresh_capability_snapshot_not_required",
            details={},
        )
    return ExecutionReadinessGateEvidence(
        gate=ExecutionReadinessGate.CAPABILITY_FRESHNESS,
        status=(
            ExecutionReadinessGateStatus.PASSED
            if capability_decision is not None and capability_decision.freshness_checked
            else ExecutionReadinessGateStatus.FAILED
        ),
        required=True,
        reason=(
            capability_decision.freshness_reason
            if capability_decision is not None
            else "freshness_decision_missing"
        ),
        details=(
            capability_decision.freshness_details
            if capability_decision is not None
            else {}
        ),
    )


def _source_provenance_gate(
    request: ExecutionAdmissionRequest,
) -> ExecutionReadinessGateEvidence:
    required = request.source_provenance_required or request.source_provenance_checked
    if request.source_provenance_passed:
        return ExecutionReadinessGateEvidence(
            gate=ExecutionReadinessGate.SOURCE_PROVENANCE,
            status=ExecutionReadinessGateStatus.PASSED,
            required=required,
            reason=request.source_provenance_reason or "source_provenance_checked",
            details=request.source_provenance_details or {},
        )
    if request.source_provenance_checked:
        return ExecutionReadinessGateEvidence(
            gate=ExecutionReadinessGate.SOURCE_PROVENANCE,
            status=ExecutionReadinessGateStatus.FAILED,
            required=True,
            reason=request.source_provenance_reason or "source_provenance_failed",
            details=request.source_provenance_details or {},
        )
    return ExecutionReadinessGateEvidence(
        gate=ExecutionReadinessGate.SOURCE_PROVENANCE,
        status=ExecutionReadinessGateStatus.NOT_REQUIRED,
        required=False,
        reason="source_provenance_not_required",
        details={},
    )


def _asset_semantics_gate(
    context: VenueOrderValidationContext | None,
) -> ExecutionReadinessGateEvidence:
    semantics = None if context is None else context.instrument_rules.asset_semantics
    if semantics is None:
        return ExecutionReadinessGateEvidence(
            gate=ExecutionReadinessGate.ASSET_SEMANTICS,
            status=ExecutionReadinessGateStatus.NOT_REQUIRED,
            required=False,
            reason="asset_semantics_absent",
            details={},
        )
    decision = validate_contract_asset_semantics_readiness(semantics)
    return ExecutionReadinessGateEvidence(
        gate=ExecutionReadinessGate.ASSET_SEMANTICS,
        status=(
            ExecutionReadinessGateStatus.PASSED
            if decision.ready
            else ExecutionReadinessGateStatus.FAILED
        ),
        required=True,
        reason=decision.reason.value,
        details=decision.details,
    )


def _idempotency_gate() -> ExecutionReadinessGateEvidence:
    return ExecutionReadinessGateEvidence(
        gate=ExecutionReadinessGate.IDEMPOTENCY,
        status=ExecutionReadinessGateStatus.PASSED,
        required=True,
        reason="client_order_id_available_and_not_conflicting",
        details={},
    )


def _string_or_none(value: object | None) -> str | None:
    return None if value is None else str(value)
