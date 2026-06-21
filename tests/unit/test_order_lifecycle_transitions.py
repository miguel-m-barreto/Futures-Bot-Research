from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.ids import ClientOrderId
from futures_bot.domain.order_lifecycle import (
    OrderLifecycleEvent,
    OrderLifecycleEventKind,
    OrderLifecycleState,
    canonical_payload_hash,
    validate_order_lifecycle_transition,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def test_valid_lifecycle_transitions_accepted() -> None:
    valid_pairs = (
        (OrderLifecycleState.CREATED, OrderLifecycleState.ACCEPTED_BY_EXECUTION),
        (
            OrderLifecycleState.ACCEPTED_BY_EXECUTION,
            OrderLifecycleState.SUBMISSION_REQUESTED,
        ),
        (
            OrderLifecycleState.SUBMISSION_REQUESTED,
            OrderLifecycleState.SUBMITTED_TO_VENUE,
        ),
        (
            OrderLifecycleState.SUBMITTED_TO_VENUE,
            OrderLifecycleState.ACKNOWLEDGED_BY_VENUE,
        ),
        (
            OrderLifecycleState.ACKNOWLEDGED_BY_VENUE,
            OrderLifecycleState.PARTIALLY_FILLED,
        ),
        (OrderLifecycleState.PARTIALLY_FILLED, OrderLifecycleState.FILLED),
        (
            OrderLifecycleState.ACKNOWLEDGED_BY_VENUE,
            OrderLifecycleState.CANCEL_REQUESTED,
        ),
        (
            OrderLifecycleState.CANCEL_REQUESTED,
            OrderLifecycleState.CANCEL_ACKNOWLEDGED,
        ),
        (OrderLifecycleState.CANCEL_ACKNOWLEDGED, OrderLifecycleState.CANCELED),
        (
            OrderLifecycleState.ACKNOWLEDGED_BY_VENUE,
            OrderLifecycleState.REPLACE_REQUESTED,
        ),
        (OrderLifecycleState.REPLACE_REQUESTED, OrderLifecycleState.REPLACED),
        (
            OrderLifecycleState.ACKNOWLEDGED_BY_VENUE,
            OrderLifecycleState.UNKNOWN_ON_VENUE,
        ),
        (
            OrderLifecycleState.UNKNOWN_ON_VENUE,
            OrderLifecycleState.RECONCILIATION_REQUIRED,
        ),
        (OrderLifecycleState.RECONCILIATION_REQUIRED, OrderLifecycleState.CLOSED),
        (OrderLifecycleState.FILLED, OrderLifecycleState.CLOSED),
        (OrderLifecycleState.CANCELED, OrderLifecycleState.CLOSED),
        (OrderLifecycleState.EXPIRED, OrderLifecycleState.CLOSED),
        (OrderLifecycleState.VENUE_REJECTED, OrderLifecycleState.CLOSED),
    )

    validate_order_lifecycle_transition(None, OrderLifecycleState.CREATED)
    for previous_state, next_state in valid_pairs:
        validate_order_lifecycle_transition(previous_state, next_state)


def test_invalid_direct_created_to_filled_rejected() -> None:
    with pytest.raises(ValueError, match="invalid order lifecycle transition"):
        validate_order_lifecycle_transition(
            OrderLifecycleState.CREATED,
            OrderLifecycleState.FILLED,
        )


def test_closed_cannot_transition_to_anything_else() -> None:
    with pytest.raises(ValueError, match="CLOSED cannot transition"):
        validate_order_lifecycle_transition(
            OrderLifecycleState.CLOSED,
            OrderLifecycleState.CANCELED,
        )


def test_lifecycle_event_validates_transition() -> None:
    payload = {"state": "bad"}
    with pytest.raises(ValidationError, match="invalid order lifecycle transition"):
        OrderLifecycleEvent(
            client_order_id=ClientOrderId("client-1"),
            event_kind=OrderLifecycleEventKind.FILLED,
            previous_state=OrderLifecycleState.CREATED,
            next_state=OrderLifecycleState.FILLED,
            occurred_at=NOW,
            payload=payload,
            payload_hash=canonical_payload_hash(payload),
        )
