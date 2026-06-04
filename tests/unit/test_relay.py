from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.broker import (
    BrokerPublishStatus,
    KafkaPartitionOffset,
    KafkaPublishAck,
    KafkaPublishRecord,
)
from futures_bot.domain.events import EventEnvelope, EventType
from futures_bot.domain.ids import (
    BatchId,
    BotId,
    BrokerTopicId,
    ConsumerId,
    EventId,
    ProducerId,
    RunId,
    SidecarId,
)
from futures_bot.domain.journal import JournalRecord, WalOffset
from futures_bot.domain.relay import WalRelayBatch, WalRelayPublishResult
from futures_bot.domain.sidecars import (
    DbWriterCheckpoint,
    RequiredConsumerCheckpointSet,
    SidecarCheckpoint,
    SidecarKind,
    WalRelayCheckpoint,
)
from futures_bot.ports.broker_publisher import BrokerPublisherPort
from futures_bot.ports.checkpoint_store import (
    DbWriterCheckpointStorePort,
    RequiredConsumerCheckpointStorePort,
    WalRelayCheckpointStorePort,
)
from futures_bot.ports.wal_relay import WalRelayPort

# ── helpers ───────────────────────────────────────────────────────────────────

def _utc() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _topic() -> BrokerTopicId:
    return BrokerTopicId("events.topic")


def _event() -> EventEnvelope:
    return EventEnvelope(
        event_id=EventId("evt-1"),
        event_type=EventType.BOT_CREATED,
        occurred_at=_utc(),
        bot_id=BotId("bot-1"),
        schema_version="1.0",
    )


def _journal_record(offset: int, run_id: str = "run-1") -> JournalRecord:
    return JournalRecord(
        run_id=RunId(run_id),
        producer_id=ProducerId("prod-1"),
        wal_offset=WalOffset(value=offset),
        event=_event(),
        recorded_at=_utc(),
        payload_hash="abc123",
        record_size_bytes=64,
    )


def _records(*offsets: int, run_id: str = "run-1") -> tuple[JournalRecord, ...]:
    return tuple(_journal_record(off, run_id=run_id) for off in offsets)


def _kafka_offset(offset: int = 42) -> KafkaPartitionOffset:
    return KafkaPartitionOffset(topic=_topic(), partition=0, offset=offset)


def _ack_published(journal_offset: int) -> KafkaPublishAck:
    return KafkaPublishAck(
        status=BrokerPublishStatus.PUBLISHED,
        published=True,
        journal_offset=WalOffset(value=journal_offset),
        kafka_offset=_kafka_offset(journal_offset),
    )


def _ack_rejected(journal_offset: int = 0) -> KafkaPublishAck:
    return KafkaPublishAck(
        status=BrokerPublishStatus.REJECTED_BROKER_UNAVAILABLE,
        published=False,
        journal_offset=WalOffset(value=journal_offset),
        reason="broker down",
    )


def _relay_checkpoint(offset: int = 5) -> WalRelayCheckpoint:
    return WalRelayCheckpoint(
        relay_id=SidecarId("relay-1"),
        run_id=RunId("run-1"),
        last_published_wal_offset=WalOffset(value=offset),
        last_published_event_id=EventId("evt-1"),
        kafka_offset=_kafka_offset(offset),
        updated_at=_utc(),
    )


def _db_writer_checkpoint(offset: int = 5) -> DbWriterCheckpoint:
    return DbWriterCheckpoint(
        consumer_id=ConsumerId("consumer-1"),
        run_id=RunId("run-1"),
        last_committed_wal_offset=WalOffset(value=offset),
        last_committed_event_id=EventId("evt-1"),
        kafka_offset=_kafka_offset(offset),
        db_transaction_id="txn-abc",
        batch_id=BatchId("batch-1"),
        updated_at=_utc(),
    )


# ── WalRelayBatch ─────────────────────────────────────────────────────────────

def test_wal_relay_batch_accepts_single_record() -> None:
    batch = WalRelayBatch(run_id=RunId("run-1"), records=_records(0))
    assert batch.record_count == 1
    assert batch.first_offset == WalOffset(value=0)
    assert batch.last_offset == WalOffset(value=0)


def test_wal_relay_batch_accepts_contiguous_records() -> None:
    batch = WalRelayBatch(run_id=RunId("run-1"), records=_records(3, 4, 5))
    assert batch.record_count == 3
    assert batch.first_offset == WalOffset(value=3)
    assert batch.last_offset == WalOffset(value=5)


def test_wal_relay_batch_rejects_empty_records() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        WalRelayBatch(run_id=RunId("run-1"), records=())


def test_wal_relay_batch_rejects_mixed_run_id() -> None:
    records = (
        _journal_record(0, run_id="run-1"),
        _journal_record(1, run_id="run-OTHER"),
    )
    with pytest.raises(ValidationError, match="run_id"):
        WalRelayBatch(run_id=RunId("run-1"), records=records)


def test_wal_relay_batch_rejects_non_contiguous_offsets() -> None:
    with pytest.raises(ValidationError, match="contiguous"):
        WalRelayBatch(run_id=RunId("run-1"), records=_records(0, 2))


def test_wal_relay_batch_rejects_unsorted_offsets() -> None:
    with pytest.raises(ValidationError, match="ascending"):
        WalRelayBatch(run_id=RunId("run-1"), records=_records(5, 4))


def test_wal_relay_batch_rejects_duplicate_offsets() -> None:
    with pytest.raises(ValidationError, match="ascending"):
        WalRelayBatch(run_id=RunId("run-1"), records=_records(3, 3))


def test_wal_relay_batch_properties() -> None:
    batch = WalRelayBatch(run_id=RunId("run-1"), records=_records(10, 11, 12, 13))
    assert batch.first_offset == WalOffset(value=10)
    assert batch.last_offset == WalOffset(value=13)
    assert batch.record_count == 4


# ── WalRelayPublishResult ─────────────────────────────────────────────────────

def test_wal_relay_publish_result_accepts_valid_published() -> None:
    result = WalRelayPublishResult(
        run_id=RunId("run-1"),
        first_offset=WalOffset(value=0),
        last_offset=WalOffset(value=2),
        record_count=3,
        broker_ack=_ack_published(2),
    )
    assert result.record_count == 3
    assert result.broker_ack.published is True


def test_wal_relay_publish_result_accepts_rejected_ack() -> None:
    result = WalRelayPublishResult(
        run_id=RunId("run-1"),
        first_offset=WalOffset(value=0),
        last_offset=WalOffset(value=2),
        record_count=3,
        broker_ack=_ack_rejected(journal_offset=2),
    )
    assert result.broker_ack.published is False


def test_wal_relay_publish_result_rejects_zero_record_count() -> None:
    with pytest.raises(ValidationError, match="record_count must be > 0"):
        WalRelayPublishResult(
            run_id=RunId("run-1"),
            first_offset=WalOffset(value=0),
            last_offset=WalOffset(value=2),
            record_count=0,
            broker_ack=_ack_published(2),
        )


def test_wal_relay_publish_result_rejects_negative_record_count() -> None:
    with pytest.raises(ValidationError, match="record_count must be > 0"):
        WalRelayPublishResult(
            run_id=RunId("run-1"),
            first_offset=WalOffset(value=0),
            last_offset=WalOffset(value=2),
            record_count=-1,
            broker_ack=_ack_rejected(journal_offset=2),
        )


def test_wal_relay_publish_result_rejects_first_greater_than_last() -> None:
    with pytest.raises(ValidationError, match="first_offset must be <= last_offset"):
        WalRelayPublishResult(
            run_id=RunId("run-1"),
            first_offset=WalOffset(value=5),
            last_offset=WalOffset(value=3),
            record_count=1,
            broker_ack=_ack_published(3),
        )


def test_wal_relay_publish_result_rejects_ack_offset_mismatch() -> None:
    with pytest.raises(ValidationError, match="journal_offset must equal last_offset"):
        WalRelayPublishResult(
            run_id=RunId("run-1"),
            first_offset=WalOffset(value=0),
            last_offset=WalOffset(value=4),
            record_count=5,
            broker_ack=_ack_published(3),  # journal_offset 3 != last_offset 4
        )


def test_wal_relay_publish_result_rejects_record_count_too_low() -> None:
    # first=0, last=2 → expected count=3; supplying 2 must fail
    with pytest.raises(ValidationError, match="record_count must equal"):
        WalRelayPublishResult(
            run_id=RunId("run-1"),
            first_offset=WalOffset(value=0),
            last_offset=WalOffset(value=2),
            record_count=2,
            broker_ack=_ack_published(2),
        )


def test_wal_relay_publish_result_rejects_record_count_too_high() -> None:
    with pytest.raises(ValidationError, match="record_count must equal"):
        WalRelayPublishResult(
            run_id=RunId("run-1"),
            first_offset=WalOffset(value=0),
            last_offset=WalOffset(value=2),
            record_count=99,
            broker_ack=_ack_published(2),
        )


def test_wal_relay_publish_result_single_record_passes() -> None:
    result = WalRelayPublishResult(
        run_id=RunId("run-1"),
        first_offset=WalOffset(value=5),
        last_offset=WalOffset(value=5),
        record_count=1,
        broker_ack=_ack_published(5),
    )
    assert result.record_count == 1


def test_wal_relay_publish_result_rejected_ack_journal_offset_must_match_last() -> None:
    # Even for a rejected ack, journal_offset must equal last_offset.
    with pytest.raises(ValidationError, match="journal_offset must equal last_offset"):
        WalRelayPublishResult(
            run_id=RunId("run-1"),
            first_offset=WalOffset(value=0),
            last_offset=WalOffset(value=2),
            record_count=3,
            broker_ack=_ack_rejected(journal_offset=0),  # 0 != last_offset 2
        )


def test_wal_relay_publish_result_is_not_a_gc_signal() -> None:
    # A WalRelayPublishResult carries no db_transaction_id, no batch_id,
    # and no DbWriterCheckpoint — confirming it cannot serve as a GC authority.
    result = WalRelayPublishResult(
        run_id=RunId("run-1"),
        first_offset=WalOffset(value=0),
        last_offset=WalOffset(value=0),
        record_count=1,
        broker_ack=_ack_published(0),
    )
    assert not hasattr(result, "db_transaction_id")
    assert not hasattr(result, "batch_id")
    assert not hasattr(result, "last_committed_wal_offset")


# ── BrokerPublisherPort conformance ───────────────────────────────────────────

class FakeBrokerPublisher:
    """In-memory broker publisher. No Kafka client, no network code."""

    def __init__(self) -> None:
        self.published: list[tuple[KafkaPublishRecord, ...]] = []

    def publish_batch(
        self, records: tuple[KafkaPublishRecord, ...]
    ) -> KafkaPublishAck:
        self.published.append(records)
        last = records[-1]
        return _ack_published(last.journal_record.wal_offset.value)


def test_fake_broker_publisher_implements_port() -> None:
    # Structural typing: assigning to BrokerPublisherPort verifies conformance at
    # type-check time without importing any Kafka library.
    _: BrokerPublisherPort = FakeBrokerPublisher()


def test_fake_broker_publisher_records_published_batches() -> None:
    publisher = FakeBrokerPublisher()
    rec = KafkaPublishRecord(
        journal_record=_journal_record(0),
        topic=_topic(),
        key="bot-1",
    )
    ack = publisher.publish_batch((rec,))
    assert ack.published is True
    assert len(publisher.published) == 1


# ── WalRelayPort conformance ──────────────────────────────────────────────────

class FakeWalRelay:
    """In-memory WAL relay. No LocalJsonlWal import, no broker client."""

    def __init__(self) -> None:
        self.results: list[WalRelayPublishResult] = []

    def publish_batch(self, batch: WalRelayBatch) -> WalRelayPublishResult:
        result = WalRelayPublishResult(
            run_id=batch.run_id,
            first_offset=batch.first_offset,
            last_offset=batch.last_offset,
            record_count=batch.record_count,
            broker_ack=_ack_published(batch.last_offset.value),
        )
        self.results.append(result)
        return result


def test_fake_wal_relay_implements_port() -> None:
    _: WalRelayPort = FakeWalRelay()


def test_fake_wal_relay_publish_batch_returns_result() -> None:
    relay = FakeWalRelay()
    batch = WalRelayBatch(run_id=RunId("run-1"), records=_records(0, 1, 2))
    result = relay.publish_batch(batch)
    assert result.record_count == 3
    assert result.first_offset == WalOffset(value=0)
    assert result.last_offset == WalOffset(value=2)
    assert result.broker_ack.published is True


# ── FakeWalRelayCheckpointStore ───────────────────────────────────────────────

class FakeWalRelayCheckpointStore:
    def __init__(self) -> None:
        self._data: dict[tuple[str, str], WalRelayCheckpoint] = {}

    def load(self, relay_id: SidecarId, run_id: RunId) -> WalRelayCheckpoint | None:
        return self._data.get((str(relay_id), str(run_id)))

    def save(self, checkpoint: WalRelayCheckpoint) -> None:
        self._data[(str(checkpoint.relay_id), str(checkpoint.run_id))] = checkpoint


def test_fake_wal_relay_store_implements_port() -> None:
    _: WalRelayCheckpointStorePort = FakeWalRelayCheckpointStore()


def test_fake_wal_relay_store_save_and_load() -> None:
    store: WalRelayCheckpointStorePort = FakeWalRelayCheckpointStore()
    cp = _relay_checkpoint(offset=5)
    store.save(cp)
    loaded = store.load(SidecarId("relay-1"), RunId("run-1"))
    assert loaded == cp


def test_fake_wal_relay_store_returns_none_on_miss() -> None:
    store: WalRelayCheckpointStorePort = FakeWalRelayCheckpointStore()
    assert store.load(SidecarId("relay-1"), RunId("run-1")) is None


# ── FakeDbWriterCheckpointStore ───────────────────────────────────────────────

class FakeDbWriterCheckpointStore:
    def __init__(self) -> None:
        self._data: dict[tuple[str, str], DbWriterCheckpoint] = {}

    def load(self, consumer_id: ConsumerId, run_id: RunId) -> DbWriterCheckpoint | None:
        return self._data.get((str(consumer_id), str(run_id)))

    def save(self, checkpoint: DbWriterCheckpoint) -> None:
        self._data[(str(checkpoint.consumer_id), str(checkpoint.run_id))] = checkpoint


def test_fake_db_writer_store_implements_port() -> None:
    _: DbWriterCheckpointStorePort = FakeDbWriterCheckpointStore()


def test_fake_db_writer_store_save_and_load() -> None:
    store: DbWriterCheckpointStorePort = FakeDbWriterCheckpointStore()
    cp = _db_writer_checkpoint(offset=10)
    store.save(cp)
    loaded = store.load(ConsumerId("consumer-1"), RunId("run-1"))
    assert loaded == cp


def test_fake_db_writer_store_returns_none_on_miss() -> None:
    store: DbWriterCheckpointStorePort = FakeDbWriterCheckpointStore()
    assert store.load(ConsumerId("consumer-1"), RunId("run-1")) is None


# ── FakeRequiredConsumerCheckpointStore ───────────────────────────────────────

class FakeRequiredConsumerCheckpointStore:
    def __init__(self, cs: RequiredConsumerCheckpointSet) -> None:
        self._cs = cs

    def load_required_checkpoints(self, run_id: RunId) -> RequiredConsumerCheckpointSet:
        return self._cs


def test_fake_required_consumer_store_implements_port() -> None:
    cs = RequiredConsumerCheckpointSet(run_id=RunId("run-1"))
    _: RequiredConsumerCheckpointStorePort = FakeRequiredConsumerCheckpointStore(cs)


def test_fake_required_consumer_store_returns_checkpoint_set() -> None:
    db_cp = SidecarCheckpoint(
        sidecar_id=SidecarId("db-1"),
        sidecar_kind=SidecarKind.DB_WRITER,
        run_id=RunId("run-1"),
        last_committed_wal_offset=WalOffset(value=10),
        updated_at=_utc(),
        is_required_for_wal_gc=True,
    )
    cs = RequiredConsumerCheckpointSet(run_id=RunId("run-1"), checkpoints=(db_cp,))
    store: RequiredConsumerCheckpointStorePort = FakeRequiredConsumerCheckpointStore(cs)
    loaded = store.load_required_checkpoints(RunId("run-1"))
    assert len(loaded.required_checkpoints()) == 1


# ── Type separation ───────────────────────────────────────────────────────────

def test_relay_checkpoint_is_not_a_db_writer_checkpoint() -> None:
    # WalRelayCheckpoint and DbWriterCheckpoint are distinct types.
    # A relay checkpoint must never be accepted as a DB writer checkpoint.
    relay_cp = _relay_checkpoint()
    assert not isinstance(relay_cp, DbWriterCheckpoint)


def test_relay_store_and_db_writer_store_hold_different_types() -> None:
    relay_store = FakeWalRelayCheckpointStore()
    db_store = FakeDbWriterCheckpointStore()

    relay_cp = _relay_checkpoint(offset=3)
    db_cp = _db_writer_checkpoint(offset=3)

    relay_store.save(relay_cp)
    db_store.save(db_cp)

    # Each store only knows about its own type.
    assert relay_store.load(SidecarId("relay-1"), RunId("run-1")) == relay_cp
    assert db_store.load(ConsumerId("consumer-1"), RunId("run-1")) == db_cp
    assert relay_store.load(SidecarId("consumer-1"), RunId("run-1")) is None
    assert db_store.load(ConsumerId("relay-1"), RunId("run-1")) is None


def test_required_consumer_store_does_not_include_wal_relay_in_required() -> None:
    # WAL_RELAY cannot have is_required_for_wal_gc=True — the SidecarCheckpoint
    # model validator prevents it.  A checkpoint set containing a WAL_RELAY
    # sidecar produces zero required checkpoints.
    relay_cp = SidecarCheckpoint(
        sidecar_id=SidecarId("relay-1"),
        sidecar_kind=SidecarKind.WAL_RELAY,
        run_id=RunId("run-1"),
        last_committed_wal_offset=WalOffset(value=9999),
        updated_at=_utc(),
        is_required_for_wal_gc=False,
    )
    cs = RequiredConsumerCheckpointSet(run_id=RunId("run-1"), checkpoints=(relay_cp,))
    store: RequiredConsumerCheckpointStorePort = FakeRequiredConsumerCheckpointStore(cs)
    loaded = store.load_required_checkpoints(RunId("run-1"))
    assert len(loaded.required_checkpoints()) == 0
