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
from futures_bot.domain.sidecars import SidecarKind, WalGcAction, decide_wal_gc
from futures_bot.domain.wal import WalAppendResult, WalSegmentMetadata, WalSegmentStatus
from futures_bot.infrastructure.broker.in_memory import InMemoryBrokerPublisher
from futures_bot.infrastructure.checkpoints.in_memory import (
    InMemoryBrokerConsumerCursorStore,
    InMemoryDbWriterCheckpointStore,
    InMemoryRequiredConsumerCheckpointStore,
    InMemoryWalRelayCheckpointStore,
)
from futures_bot.infrastructure.db_writer.in_memory import InMemoryCommittedEventStore
from futures_bot.relay.service import LocalWalRelayService


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


def _record(offset: int, run_id: str = "run-1") -> JournalRecord:
    return JournalRecord(
        run_id=RunId(run_id),
        producer_id=ProducerId("prod-1"),
        wal_offset=WalOffset(value=offset),
        event=_event(f"evt-{offset}"),
        recorded_at=_utc(),
        payload_hash=f"hash-{offset}",
        record_size_bytes=64,
    )


def _sealed_segment(first: int, last: int, run_id: str = "run-1") -> WalSegmentMetadata:
    return WalSegmentMetadata(
        segment_id=WalSegmentId(f"seg-{first}-{last}"),
        run_id=RunId(run_id),
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


def test_relay_broker_db_writer_and_gc_authority_flow() -> None:
    journal = FakeJournal((_record(10), _record(11)))
    publisher = InMemoryBrokerPublisher()
    relay_store = InMemoryWalRelayCheckpointStore()
    required_store = InMemoryRequiredConsumerCheckpointStore()
    broker_cursor_store = InMemoryBrokerConsumerCursorStore()

    relay = LocalWalRelayService(
        journal=journal,
        publisher=publisher,
        checkpoint_store=relay_store,
        relay_id=SidecarId("relay-1"),
        topic=BrokerTopicId("events.topic"),
        now=_utc,
    )

    relay_result = relay.relay_once(max_records=10)

    assert relay_result is not None
    assert relay_result.broker_ack.published is True
    assert [record.kafka_offset.offset for record in publisher.consumed_records()] == [
        0,
        1,
    ]

    empty_required = required_store.load_required_checkpoints(RunId("run-1"))
    ack_only_decision = decide_wal_gc(_sealed_segment(10, 11), empty_required, _utc())
    assert ack_only_decision.action is WalGcAction.KEEP
    assert ack_only_decision.eligible is False

    relay_checkpoint = relay_store.load(SidecarId("relay-1"), RunId("run-1"))
    assert relay_checkpoint is not None
    relay_only_decision = decide_wal_gc(_sealed_segment(10, 11), empty_required, _utc())
    assert relay_only_decision.action is WalGcAction.KEEP
    assert relay_only_decision.eligible is False

    db_writer = LocalDbWriterService(
        consumer_id=ConsumerId("consumer-1"),
        db_store=InMemoryCommittedEventStore(),
        checkpoint_store=InMemoryDbWriterCheckpointStore(),
        required_checkpoint_writer=required_store,
        broker_cursor_store=broker_cursor_store,
        now=_utc,
    )
    db_checkpoint = db_writer.commit_consumed_batch(publisher.consumed_records())

    assert db_checkpoint is not None
    assert db_checkpoint.last_committed_wal_offset == WalOffset(value=11)
    assert db_checkpoint.kafka_offset == publisher.consumed_records()[-1].kafka_offset
    assert db_checkpoint.kafka_offset.offset == 1
    cursor = broker_cursor_store.load(
        ConsumerId("consumer-1"), BrokerTopicId("events.topic"), 0
    )
    assert cursor is not None
    assert cursor.kafka_offset == db_checkpoint.kafka_offset
    assert cursor.last_committed_run_id == RunId("run-1")
    assert cursor.last_committed_wal_offset == WalOffset(value=11)

    checkpoint_set = required_store.load_required_checkpoints(RunId("run-1"))
    assert len(checkpoint_set.checkpoints) == 1
    assert checkpoint_set.checkpoints[0].sidecar_kind is SidecarKind.DB_WRITER
    assert checkpoint_set.checkpoints[0].last_committed_wal_offset == WalOffset(value=11)

    behind_decision = decide_wal_gc(_sealed_segment(10, 12), checkpoint_set, _utc())
    assert behind_decision.action is WalGcAction.KEEP
    assert behind_decision.eligible is False

    reached_decision = decide_wal_gc(_sealed_segment(10, 11), checkpoint_set, _utc())
    assert reached_decision.action is WalGcAction.ARCHIVE
    assert reached_decision.eligible is True

    segment = _sealed_segment(10, 11)
    decide_wal_gc(segment, checkpoint_set, _utc())
    assert segment.status is WalSegmentStatus.SEALED


def test_broker_cursor_db_writer_checkpoint_and_gc_authority_across_runs() -> None:
    publisher = InMemoryBrokerPublisher()
    relay_store = InMemoryWalRelayCheckpointStore()
    db_checkpoint_store = InMemoryDbWriterCheckpointStore()
    required_store = InMemoryRequiredConsumerCheckpointStore()
    broker_cursor_store = InMemoryBrokerConsumerCursorStore()
    db_writer = LocalDbWriterService(
        consumer_id=ConsumerId("consumer-1"),
        db_store=InMemoryCommittedEventStore(),
        checkpoint_store=db_checkpoint_store,
        required_checkpoint_writer=required_store,
        broker_cursor_store=broker_cursor_store,
        now=_utc,
    )

    relay_run_1 = LocalWalRelayService(
        journal=FakeJournal((_record(10, run_id="run-1"), _record(11, run_id="run-1"))),
        publisher=publisher,
        checkpoint_store=relay_store,
        relay_id=SidecarId("relay-1"),
        topic=BrokerTopicId("events.topic"),
        now=_utc,
    )
    result_1 = relay_run_1.relay_once(max_records=10)
    assert result_1 is not None
    first_run_consumed = publisher.consumed_records()
    checkpoint_1 = db_writer.commit_consumed_batch(first_run_consumed)

    relay_run_2 = LocalWalRelayService(
        journal=FakeJournal((_record(0, run_id="run-2"), _record(1, run_id="run-2"))),
        publisher=publisher,
        checkpoint_store=relay_store,
        relay_id=SidecarId("relay-1"),
        topic=BrokerTopicId("events.topic"),
        now=_utc,
    )
    result_2 = relay_run_2.relay_once(max_records=10)
    assert result_2 is not None
    second_run_consumed = publisher.consumed_records()[len(first_run_consumed):]
    checkpoint_2 = db_writer.commit_consumed_batch(second_run_consumed)

    assert checkpoint_1 is not None
    assert checkpoint_2 is not None
    assert db_checkpoint_store.load(ConsumerId("consumer-1"), RunId("run-1")) == checkpoint_1
    assert db_checkpoint_store.load(ConsumerId("consumer-1"), RunId("run-2")) == checkpoint_2
    assert checkpoint_1.last_committed_wal_offset == WalOffset(value=11)
    assert checkpoint_2.last_committed_wal_offset == WalOffset(value=1)

    cursor = broker_cursor_store.load(
        ConsumerId("consumer-1"), BrokerTopicId("events.topic"), 0
    )
    assert cursor is not None
    assert cursor.kafka_offset.offset == 3
    assert cursor.last_committed_run_id == RunId("run-2")
    assert cursor.last_committed_wal_offset == WalOffset(value=1)

    run_1_checkpoints = required_store.load_required_checkpoints(RunId("run-1"))
    run_2_checkpoints = required_store.load_required_checkpoints(RunId("run-2"))
    assert run_1_checkpoints.required_min_offset() == WalOffset(value=11)
    assert run_2_checkpoints.required_min_offset() == WalOffset(value=1)
    run_1_gc = decide_wal_gc(
        _sealed_segment(10, 11, run_id="run-1"), run_1_checkpoints, _utc()
    )
    run_2_gc = decide_wal_gc(
        _sealed_segment(0, 1, run_id="run-2"), run_2_checkpoints, _utc()
    )
    assert run_1_gc.action is WalGcAction.ARCHIVE
    assert run_2_gc.action is WalGcAction.ARCHIVE

    empty_required = InMemoryRequiredConsumerCheckpointStore().load_required_checkpoints(
        RunId("run-2")
    )
    cursor_only_decision = decide_wal_gc(
        _sealed_segment(0, 1, run_id="run-2"),
        empty_required,
        _utc(),
    )
    assert cursor_only_decision.action is WalGcAction.KEEP
