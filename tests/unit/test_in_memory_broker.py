from datetime import UTC, datetime

from futures_bot.domain.broker import BrokerPublishStatus, KafkaPublishRecord
from futures_bot.domain.events import EventEnvelope, EventType
from futures_bot.domain.ids import BotId, BrokerTopicId, EventId, ProducerId, RunId
from futures_bot.domain.journal import JournalRecord, WalOffset
from futures_bot.infrastructure.broker.in_memory import InMemoryBrokerPublisher
from futures_bot.ports.broker_publisher import BrokerPublisherPort


def _utc() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _topic() -> BrokerTopicId:
    return BrokerTopicId("events.topic")


def _event(event_id: str = "evt-1") -> EventEnvelope:
    return EventEnvelope(
        event_id=EventId(event_id),
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
        event=_event(event_id=f"evt-{offset}"),
        recorded_at=_utc(),
        payload_hash="abc123",
        record_size_bytes=64,
    )


def _kafka_record(offset: int) -> KafkaPublishRecord:
    return KafkaPublishRecord(
        journal_record=_journal_record(offset),
        topic=_topic(),
        key="bot-1",
    )


# ── protocol conformance ──────────────────────────────────────────────────────

def test_in_memory_broker_publisher_implements_port() -> None:
    _: BrokerPublisherPort = InMemoryBrokerPublisher()


# ── publish_batch ─────────────────────────────────────────────────────────────

def test_publish_non_empty_batch_returns_published_ack() -> None:
    pub = InMemoryBrokerPublisher()
    ack = pub.publish_batch((_kafka_record(0),))
    assert ack.published is True
    assert ack.status is BrokerPublishStatus.PUBLISHED
    assert ack.kafka_offset is not None


def test_publish_batch_journal_offset_matches_last_record() -> None:
    pub = InMemoryBrokerPublisher()
    ack = pub.publish_batch((_kafka_record(0), _kafka_record(1), _kafka_record(2)))
    assert ack.journal_offset == WalOffset(value=2)


def test_empty_batch_returns_rejected_invalid_record() -> None:
    pub = InMemoryBrokerPublisher()
    ack = pub.publish_batch(())
    assert ack.published is False
    assert ack.status is BrokerPublishStatus.REJECTED_INVALID_RECORD


def test_fail_next_returns_rejected_broker_unavailable() -> None:
    pub = InMemoryBrokerPublisher(fail_next=True)
    ack = pub.publish_batch((_kafka_record(0),))
    assert ack.published is False
    assert ack.status is BrokerPublishStatus.REJECTED_BROKER_UNAVAILABLE


def test_fail_next_does_not_store_batch() -> None:
    pub = InMemoryBrokerPublisher(fail_next=True)
    pub.publish_batch((_kafka_record(0),))
    assert pub.published_batches == []
    assert pub.published_records == []


def test_fail_next_resets_after_one_failure() -> None:
    pub = InMemoryBrokerPublisher(fail_next=True)
    ack1 = pub.publish_batch((_kafka_record(0),))
    ack2 = pub.publish_batch((_kafka_record(1),))
    assert ack1.published is False
    assert ack2.published is True


# ── published_batches / published_records ────────────────────────────────────

def test_published_batches_stores_successful_batches() -> None:
    pub = InMemoryBrokerPublisher()
    batch = (_kafka_record(0), _kafka_record(1))
    pub.publish_batch(batch)
    assert len(pub.published_batches) == 1
    assert pub.published_batches[0] == batch


def test_published_records_flattens_batches() -> None:
    pub = InMemoryBrokerPublisher()
    pub.publish_batch((_kafka_record(0), _kafka_record(1)))
    pub.publish_batch((_kafka_record(2),))
    records = pub.published_records
    assert len(records) == 3
    assert records[0].journal_record.wal_offset == WalOffset(value=0)
    assert records[2].journal_record.wal_offset == WalOffset(value=2)


def test_failed_batch_not_included_in_published_batches() -> None:
    pub = InMemoryBrokerPublisher()
    pub.publish_batch((_kafka_record(0),))  # succeeds
    pub.fail_next = True
    pub.publish_batch((_kafka_record(1),))  # fails
    pub.publish_batch((_kafka_record(2),))  # succeeds again
    assert len(pub.published_batches) == 2


# ── deterministic offset counter ─────────────────────────────────────────────

def test_kafka_offset_starts_at_zero() -> None:
    pub = InMemoryBrokerPublisher()
    ack = pub.publish_batch((_kafka_record(0),))
    assert ack.kafka_offset is not None
    assert ack.kafka_offset.offset == 0


def test_kafka_offsets_increment_across_batches() -> None:
    pub = InMemoryBrokerPublisher()
    # Batch 1: 3 records → kafka offsets 0,1,2; ack.kafka_offset.offset = 2
    ack1 = pub.publish_batch((_kafka_record(0), _kafka_record(1), _kafka_record(2)))
    # Batch 2: 2 records → kafka offsets 3,4; ack.kafka_offset.offset = 4
    ack2 = pub.publish_batch((_kafka_record(3), _kafka_record(4)))
    assert ack1.kafka_offset is not None
    assert ack2.kafka_offset is not None
    assert ack1.kafka_offset.offset == 2
    assert ack2.kafka_offset.offset == 4


def test_failed_batch_does_not_advance_offset_counter() -> None:
    pub = InMemoryBrokerPublisher()
    pub.publish_batch((_kafka_record(0),))  # kafka offset 0
    pub.fail_next = True
    pub.publish_batch((_kafka_record(1),))  # rejected — no offset advance
    ack = pub.publish_batch((_kafka_record(2),))  # kafka offset 1 (not 2)
    assert ack.kafka_offset is not None
    assert ack.kafka_offset.offset == 1
