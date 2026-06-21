from __future__ import annotations

from futures_bot.domain.ids import (
    ClientOrderId,
    ExecutionOrderRecordId,
    ExecutionReconciliationId,
    FillReportId,
    OrderIntentId,
    OrderLifecycleEventId,
)
from futures_bot.domain.order_lifecycle import (
    CancelOrderIntent,
    ExecutionOrderRecord,
    ExecutionReconciliationMarker,
    FillReport,
    OrderIntent,
    OrderLifecycleEvent,
    ReplaceOrderIntent,
)


class InMemoryOrderIntentJournal:
    """Deterministic intent journal test double."""

    def __init__(self) -> None:
        self._orders: dict[str, OrderIntent] = {}
        self._cancels: dict[str, CancelOrderIntent] = {}
        self._replaces: dict[str, ReplaceOrderIntent] = {}

    def append_order_intent(self, intent: OrderIntent) -> None:
        if intent.intent_id is None:
            raise ValueError("order intent_id is required")
        _put_idempotent(self._orders, str(intent.intent_id), intent, "order intent")

    def append_cancel_intent(self, intent: CancelOrderIntent) -> None:
        if intent.cancel_intent_id is None:
            raise ValueError("cancel_intent_id is required")
        _put_idempotent(
            self._cancels,
            str(intent.cancel_intent_id),
            intent,
            "cancel intent",
        )

    def append_replace_intent(self, intent: ReplaceOrderIntent) -> None:
        if intent.replace_intent_id is None:
            raise ValueError("replace_intent_id is required")
        _put_idempotent(
            self._replaces,
            str(intent.replace_intent_id),
            intent,
            "replace intent",
        )

    def get_order_intent(self, intent_id: OrderIntentId) -> OrderIntent | None:
        return self._orders.get(str(intent_id))


class InMemoryOrderLifecycleEventStore:
    """Append-order-preserving lifecycle event store test double."""

    def __init__(self) -> None:
        self._events_by_id: dict[str, OrderLifecycleEvent] = {}
        self._event_ids: list[str] = []

    def append(self, event: OrderLifecycleEvent) -> None:
        if event.event_id is None:
            raise ValueError("event_id is required")
        key = str(event.event_id)
        existing = self._events_by_id.get(key)
        if existing is not None:
            if existing != event:
                raise ValueError("order lifecycle event id collision")
            return
        self._events_by_id[key] = event
        self._event_ids.append(key)

    def list_events(self) -> tuple[OrderLifecycleEvent, ...]:
        return tuple(self._events_by_id[event_id] for event_id in self._event_ids)

    def get(self, event_id: OrderLifecycleEventId) -> OrderLifecycleEvent | None:
        return self._events_by_id.get(str(event_id))


class InMemoryExecutionOrderRecordStore:
    """Deterministic execution order record store test double."""

    def __init__(self) -> None:
        self._records_by_id: dict[str, ExecutionOrderRecord] = {}
        self._record_id_by_client_id: dict[str, str] = {}

    def upsert(self, record: ExecutionOrderRecord) -> None:
        record_key = str(record.record_id)
        client_key = str(record.client_order_id)
        existing_record = self._records_by_id.get(record_key)
        if (
            existing_record is not None
            and str(existing_record.client_order_id) != client_key
        ):
            raise ValueError("record_id is already bound to a different client_order_id")
        existing_record_id = self._record_id_by_client_id.get(client_key)
        if existing_record_id is not None and existing_record_id != record_key:
            raise ValueError("client_order_id is already bound to a different record")
        self._records_by_id[record_key] = record
        self._record_id_by_client_id[client_key] = record_key

    def get(self, record_id: ExecutionOrderRecordId) -> ExecutionOrderRecord | None:
        return self._records_by_id.get(str(record_id))

    def get_by_client_order_id(
        self,
        client_order_id: ClientOrderId,
    ) -> ExecutionOrderRecord | None:
        record_id = self._record_id_by_client_id.get(str(client_order_id))
        if record_id is None:
            return None
        return self._records_by_id[record_id]


class InMemoryFillReportStore:
    """Deterministic fill report store test double."""

    def __init__(self) -> None:
        self._fills_by_id: dict[str, FillReport] = {}
        self._fill_id_by_venue_fill_id: dict[str, str] = {}

    def put(self, fill_report: FillReport) -> None:
        key = str(fill_report.fill_report_id)
        existing = self._fills_by_id.get(key)
        if existing is not None:
            if existing != fill_report:
                raise ValueError("fill_report_id collision")
            return
        if fill_report.venue_fill_id is not None:
            venue_key = fill_report.venue_fill_id
            existing_fill_id = self._fill_id_by_venue_fill_id.get(venue_key)
            if existing_fill_id is not None:
                existing_fill = self._fills_by_id[existing_fill_id]
                if existing_fill != fill_report:
                    raise ValueError("venue_fill_id collision")
                return
            self._fill_id_by_venue_fill_id[venue_key] = key
        self._fills_by_id[key] = fill_report

    def get(self, fill_report_id: FillReportId) -> FillReport | None:
        return self._fills_by_id.get(str(fill_report_id))


class InMemoryExecutionReconciliationStore:
    """Deterministic reconciliation marker store test double."""

    def __init__(self) -> None:
        self._markers: dict[str, ExecutionReconciliationMarker] = {}

    def put(self, marker: ExecutionReconciliationMarker) -> None:
        _put_idempotent(
            self._markers,
            str(marker.reconciliation_id),
            marker,
            "reconciliation marker",
        )

    def get(
        self,
        reconciliation_id: ExecutionReconciliationId,
    ) -> ExecutionReconciliationMarker | None:
        return self._markers.get(str(reconciliation_id))


def _put_idempotent[T](
    store: dict[str, T],
    key: str,
    value: T,
    name: str,
) -> None:
    existing = store.get(key)
    if existing is not None:
        if existing != value:
            raise ValueError(f"{name} id collision")
        return
    store[key] = value
