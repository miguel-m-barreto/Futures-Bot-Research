from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

from futures_bot.db_writer.service import LocalDbWriterService
from futures_bot.domain.events import EventEnvelope, EventType
from futures_bot.domain.ids import (
    BotId,
    BrokerTopicId,
    ConsumerId,
    EventId,
    ProducerId,
    RunId,
    SidecarId,
    WalSegmentId,
)
from futures_bot.domain.journal import JournalRecord, WalOffset, WalOffsetRange
from futures_bot.domain.sidecars import (
    RequiredConsumerCheckpointSet,
    SidecarHealthLevel,
    WalGcAction,
    decide_wal_gc,
)
from futures_bot.domain.wal import WalAppendResult, WalSegmentMetadata, WalSegmentStatus
from futures_bot.infrastructure.broker.in_memory import InMemoryBrokerPublisher
from futures_bot.infrastructure.checkpoints.in_memory import (
    InMemoryBrokerConsumerCursorStore,
    InMemoryDbWriterCheckpointStore,
    InMemoryRequiredConsumerCheckpointStore,
    InMemoryWalRelayCheckpointStore,
)
from futures_bot.infrastructure.db_writer.in_memory import InMemoryCommittedEventStore
from futures_bot.infrastructure.sidecars.in_memory import InMemorySidecarHealthStore
from futures_bot.relay.service import LocalWalRelayService
from futures_bot.sidecars.local import LocalDbWriterSidecar, LocalWalRelaySidecar


def _utc() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _event(event_id: str) -> EventEnvelope:
    return EventEnvelope(
        event_id=EventId(event_id),
        event_type=EventType.BOT_CREATED,
        occurred_at=_utc(),
        bot_id=BotId("bot-1"),
        schema_version="1.0",
    )


def _record(offset: int) -> JournalRecord:
    return JournalRecord(
        run_id=RunId("run-1"),
        producer_id=ProducerId("prod-1"),
        wal_offset=WalOffset(value=offset),
        event=_event(f"evt-{offset}"),
        recorded_at=_utc(),
        payload_hash=f"hash-{offset}",
        record_size_bytes=64,
    )


def _sealed_segment(first: int, last: int) -> WalSegmentMetadata:
    return WalSegmentMetadata(
        segment_id=WalSegmentId("seg-1"),
        run_id=RunId("run-1"),
        status=WalSegmentStatus.SEALED,
        offset_range=WalOffsetRange(
            first=WalOffset(value=first),
            last=WalOffset(value=last),
        ),
        created_at=_utc(),
        sealed_at=_utc(),
        event_count=last - first + 1,
    )


class FakeJournal:
    def __init__(self, records: tuple[JournalRecord, ...]) -> None:
        self._records = records

    def iter_records(self) -> Iterator[JournalRecord]:
        return iter(self._records)

    def append(
        self, event: EventEnvelope, *, recorded_at: datetime | None = None
    ) -> WalAppendResult:
        raise NotImplementedError

    def current_segment_metadata(self) -> WalSegmentMetadata:
        raise NotImplementedError

    def list_segment_metadata(self) -> tuple[WalSegmentMetadata, ...]:
        raise NotImplementedError

    def seal_current_segment(self) -> WalSegmentMetadata:
        raise NotImplementedError

    def read_segment(self, segment_id: WalSegmentId) -> tuple[JournalRecord, ...]:
        raise NotImplementedError

    def close(self) -> None:
        pass


def test_local_one_shot_sidecar_pipeline_keeps_authorities_separate() -> None:
    publisher = InMemoryBrokerPublisher()
    wal_relay_store = InMemoryWalRelayCheckpointStore()
    db_checkpoint_store = InMemoryDbWriterCheckpointStore()
    required_store = InMemoryRequiredConsumerCheckpointStore()
    broker_cursor_store = InMemoryBrokerConsumerCursorStore()
    health_store = InMemorySidecarHealthStore()
    db_store = InMemoryCommittedEventStore()

    relay_service = LocalWalRelayService(
        journal=FakeJournal((_record(0), _record(1), _record(2))),
        publisher=publisher,
        checkpoint_store=wal_relay_store,
        relay_id=SidecarId("relay-1"),
        topic=BrokerTopicId("events.topic"),
        now=_utc,
    )
    relay_sidecar = LocalWalRelaySidecar(
        sidecar_id=SidecarId("relay-1"),
        relay_service=relay_service,
        health_store=health_store,
        now=_utc,
    )

    relay_result = relay_sidecar.run_once(max_records=10)

    assert relay_result is not None
    assert len(publisher.consumed_records()) == 3
    relay_health = health_store.latest(SidecarId("relay-1"))
    assert relay_health is not None
    assert relay_health.health is SidecarHealthLevel.HEALTHY
    assert relay_health.last_processed_wal_offset == WalOffset(value=2)
    assert wal_relay_store.load(SidecarId("relay-1"), RunId("run-1")) is not None

    segment = _sealed_segment(0, 2)
    empty_required = RequiredConsumerCheckpointSet(run_id=RunId("run-1"))
    assert decide_wal_gc(segment, empty_required, _utc()).action is WalGcAction.KEEP

    db_writer_service = LocalDbWriterService(
        consumer_id=ConsumerId("consumer-1"),
        db_store=db_store,
        checkpoint_store=db_checkpoint_store,
        required_checkpoint_writer=required_store,
        broker_cursor_store=broker_cursor_store,
        now=_utc,
    )
    db_writer_sidecar = LocalDbWriterSidecar(
        sidecar_id=SidecarId("dbw-1"),
        db_writer_service=db_writer_service,
        health_store=health_store,
        now=_utc,
    )

    db_checkpoint = db_writer_sidecar.commit_once(publisher.consumed_records())

    assert db_checkpoint is not None
    assert db_store.committed_offsets(RunId("run-1")) == (
        WalOffset(value=0),
        WalOffset(value=1),
        WalOffset(value=2),
    )
    assert db_checkpoint_store.load(ConsumerId("consumer-1"), RunId("run-1")) == db_checkpoint
    broker_cursor = broker_cursor_store.load(
        ConsumerId("consumer-1"), BrokerTopicId("events.topic"), 0
    )
    assert broker_cursor is not None
    dbw_health = health_store.latest(SidecarId("dbw-1"))
    assert dbw_health is not None
    assert dbw_health.health is SidecarHealthLevel.HEALTHY

    required_checkpoints = required_store.load_required_checkpoints(RunId("run-1"))
    assert required_checkpoints.required_min_offset() == WalOffset(value=2)
    assert decide_wal_gc(segment, required_checkpoints, _utc()).action is WalGcAction.ARCHIVE

    cursor_only = RequiredConsumerCheckpointSet(run_id=RunId("run-1"))
    health_only = RequiredConsumerCheckpointSet(run_id=RunId("run-1"))
    assert decide_wal_gc(segment, cursor_only, _utc()).action is WalGcAction.KEEP
    assert decide_wal_gc(segment, health_only, _utc()).action is WalGcAction.KEEP
    assert segment.status is WalSegmentStatus.SEALED
