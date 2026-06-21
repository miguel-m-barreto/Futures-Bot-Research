from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from futures_bot.domain.ids import (
    ClientOrderId,
    ExecutionOrderRecordId,
    ExecutionReconciliationId,
    FillReportId,
    VenueOrderId,
)
from futures_bot.domain.order_lifecycle import (
    ExecutionOrderRecord,
    ExecutionReconciliationMarker,
    FillReport,
    OrderIntent,
    OrderIntentKind,
    OrderLifecycleEvent,
    OrderLifecycleEventKind,
    OrderLifecycleState,
    OrderSide,
    OrderType,
    PositionSide,
    ReconciliationReason,
    canonical_payload_hash,
)
from futures_bot.domain.runtime_control import (
    OrderFlowPermissionReason,
    RuntimeDataScopeKind,
)
from futures_bot.order_lifecycle.in_memory import (
    InMemoryExecutionOrderRecordStore,
    InMemoryExecutionReconciliationStore,
    InMemoryFillReportStore,
    InMemoryOrderIntentJournal,
    InMemoryOrderLifecycleEventStore,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _entry_intent(*, instrument_id: str = "BTC-PERP") -> OrderIntent:
    return OrderIntent(
        intent_kind=OrderIntentKind.ENTRY,
        venue_id="venue-1",
        instrument_id=instrument_id,
        account_id="acct-1",
        side=OrderSide.BUY,
        position_side=PositionSide.LONG,
        order_type=OrderType.MARKET,
        quantity="1",
        reduce_only=False,
        post_only=False,
        close_position=False,
        permission_reason=OrderFlowPermissionReason.OK,
        created_at=NOW,
    )


def _record(
    record_id: str = "record-1",
    *,
    instrument_id: str = "BTC-PERP",
) -> ExecutionOrderRecord:
    intent = _entry_intent(instrument_id=instrument_id)
    assert intent.client_order_id is not None
    return ExecutionOrderRecord(
        record_id=ExecutionOrderRecordId(record_id),
        order_intent=intent,
        lifecycle_state=OrderLifecycleState.CREATED,
        client_order_id=intent.client_order_id,
        cumulative_filled_quantity=Decimal("0"),
        remaining_quantity=Decimal("1"),
        created_at=NOW,
        updated_at=NOW,
    )


def _event(payload: dict[str, str]) -> OrderLifecycleEvent:
    intent = _entry_intent()
    assert intent.client_order_id is not None
    return OrderLifecycleEvent(
        client_order_id=intent.client_order_id,
        event_kind=OrderLifecycleEventKind.INTENT_CREATED,
        previous_state=None,
        next_state=OrderLifecycleState.CREATED,
        occurred_at=NOW,
        payload=payload,
        payload_hash=canonical_payload_hash(payload),
    )


def _fill(fill_report_id: str = "fill-1", *, venue_fill_id: str = "vf-1") -> FillReport:
    return FillReport(
        fill_report_id=FillReportId(fill_report_id),
        record_id=ExecutionOrderRecordId("record-1"),
        client_order_id=ClientOrderId("client-1"),
        venue_order_id=VenueOrderId("venue-order-1"),
        venue_fill_id=venue_fill_id,
        fill_quantity=Decimal("1"),
        fill_price=Decimal("100"),
        occurred_at=NOW,
    )


def _marker() -> ExecutionReconciliationMarker:
    return ExecutionReconciliationMarker(
        reconciliation_id=ExecutionReconciliationId("recon-1"),
        scope_kind=RuntimeDataScopeKind.INSTRUMENT,
        scope_id="BTC-PERP",
        reason=ReconciliationReason.UNKNOWN_ON_VENUE,
        required=True,
        created_at=NOW,
        related_order_record_ids=(ExecutionOrderRecordId("record-1"),),
        related_client_order_ids=(ClientOrderId("client-1"),),
    )


def test_intent_journal_idempotent_same_intent() -> None:
    journal = InMemoryOrderIntentJournal()
    intent = _entry_intent()

    journal.append_order_intent(intent)
    journal.append_order_intent(intent)

    assert intent.intent_id is not None
    assert journal.get_order_intent(intent.intent_id) == intent


def test_intent_journal_rejects_same_id_different_payload() -> None:
    journal = InMemoryOrderIntentJournal()
    intent = _entry_intent()
    changed = intent.model_copy(update={"instrument_id": "ETH-PERP"})

    journal.append_order_intent(intent)
    with pytest.raises(ValueError, match="order intent id collision"):
        journal.append_order_intent(changed)


def test_event_store_append_order_deterministic() -> None:
    store = InMemoryOrderLifecycleEventStore()
    first = _event({"n": "1"})
    second = _event({"n": "2"})

    store.append(first)
    store.append(second)

    assert store.list_events() == (first, second)


def test_record_store_upsert_by_record_id() -> None:
    store = InMemoryExecutionOrderRecordStore()
    first = _record()
    updated = first.model_copy(
        update={"lifecycle_state": OrderLifecycleState.ACCEPTED_BY_EXECUTION}
    )

    store.upsert(first)
    store.upsert(updated)

    assert store.get(ExecutionOrderRecordId("record-1")) == updated


def test_record_store_rejects_same_client_order_id_different_record() -> None:
    store = InMemoryExecutionOrderRecordStore()
    first = _record("record-1")
    second = first.model_copy(update={"record_id": ExecutionOrderRecordId("record-2")})

    store.upsert(first)
    with pytest.raises(ValueError, match="client_order_id"):
        store.upsert(second)


def test_record_store_rejects_same_record_id_different_client_order_id() -> None:
    store = InMemoryExecutionOrderRecordStore()
    first = _record("record-1", instrument_id="BTC-PERP")
    second = _record("record-1", instrument_id="ETH-PERP")

    store.upsert(first)
    with pytest.raises(ValueError, match="record_id"):
        store.upsert(second)


def test_record_store_preserves_old_client_lookup_after_rejected_rebind() -> None:
    store = InMemoryExecutionOrderRecordStore()
    first = _record("record-1", instrument_id="BTC-PERP")
    second = _record("record-1", instrument_id="ETH-PERP")

    store.upsert(first)
    with pytest.raises(ValueError, match="record_id"):
        store.upsert(second)

    first_client_order_id = first.client_order_id
    second_client_order_id = second.client_order_id
    old_lookup = store.get_by_client_order_id(first_client_order_id)

    assert old_lookup is not None
    assert old_lookup.client_order_id == first_client_order_id
    assert store.get_by_client_order_id(second_client_order_id) is None


def test_record_store_allows_same_record_id_same_client_order_id_lifecycle_update() -> None:
    store = InMemoryExecutionOrderRecordStore()
    first = _record("record-1")
    updated = first.model_copy(
        update={
            "lifecycle_state": OrderLifecycleState.ACKNOWLEDGED_BY_VENUE,
            "venue_order_id": VenueOrderId("venue-order-1"),
            "cumulative_filled_quantity": Decimal("0.25"),
            "remaining_quantity": Decimal("0.75"),
            "updated_at": NOW + timedelta(seconds=1),
        }
    )

    store.upsert(first)
    store.upsert(updated)

    assert store.get(first.record_id) == updated
    assert store.get_by_client_order_id(first.client_order_id) == updated


def test_fill_store_idempotent_same_fill() -> None:
    store = InMemoryFillReportStore()
    fill = _fill()

    store.put(fill)
    store.put(fill)

    assert store.get(FillReportId("fill-1")) == fill


def test_fill_store_rejects_duplicate_venue_fill_id_different_payload() -> None:
    store = InMemoryFillReportStore()
    first = _fill("fill-1", venue_fill_id="vf-1")
    second = _fill("fill-2", venue_fill_id="vf-1")

    store.put(first)
    with pytest.raises(ValueError, match="venue_fill_id collision"):
        store.put(second)


def test_reconciliation_store_idempotent_same_marker() -> None:
    store = InMemoryExecutionReconciliationStore()
    marker = _marker()

    store.put(marker)
    store.put(marker)

    assert store.get(ExecutionReconciliationId("recon-1")) == marker
