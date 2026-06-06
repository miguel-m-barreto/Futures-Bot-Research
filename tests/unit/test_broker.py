import inspect
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from futures_bot.domain import broker as broker_domain
from futures_bot.domain.broker import (
    BrokerConsumerCursor,
    BrokerPublishStatus,
    KafkaConsumedRecord,
    KafkaPartitionOffset,
    KafkaPublishAck,
    KafkaPublishRecord,
)
from futures_bot.domain.events import EventEnvelope, EventType
from futures_bot.domain.ids import (
    BotId,
    BrokerTopicId,
    ConsumerId,
    EventId,
    ProducerId,
    RunId,
)
from futures_bot.domain.journal import JournalRecord, WalOffset
from futures_bot.domain.sidecars import (
    RequiredConsumerCheckpointSet,
    SidecarCheckpoint,
)


def _utc() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _event() -> EventEnvelope:
    return EventEnvelope(
        event_id=EventId("evt-1"),
        event_type=EventType.BOT_CREATED,
        occurred_at=_utc(),
        bot_id=BotId("bot-1"),
        schema_version="1.0",
    )


def _record() -> JournalRecord:
    return JournalRecord(
        run_id=RunId("run-1"),
        producer_id=ProducerId("producer-1"),
        wal_offset=WalOffset(value=0),
        event=_event(),
        recorded_at=_utc(),
        payload_hash="abc123",
        record_size_bytes=64,
    )


def _topic() -> BrokerTopicId:
    return BrokerTopicId("events.topic")


def _kafka_offset(partition: int = 0, offset: int = 42) -> KafkaPartitionOffset:
    return KafkaPartitionOffset(topic=_topic(), partition=partition, offset=offset)


# ── KafkaPartitionOffset ───────────────────────────────────────────────────────

def test_kafka_partition_offset_accepts_valid_input() -> None:
    kpo = _kafka_offset(partition=2, offset=100)
    assert kpo.partition == 2
    assert kpo.offset == 100


def test_kafka_partition_offset_rejects_negative_partition() -> None:
    with pytest.raises(ValidationError, match="partition"):
        KafkaPartitionOffset(topic=_topic(), partition=-1, offset=0)


def test_kafka_partition_offset_rejects_negative_offset() -> None:
    with pytest.raises(ValidationError, match="offset"):
        KafkaPartitionOffset(topic=_topic(), partition=0, offset=-1)


# ── KafkaPublishRecord ─────────────────────────────────────────────────────────

def test_kafka_publish_record_accepts_valid_input() -> None:
    rec = KafkaPublishRecord(
        journal_record=_record(),
        topic=_topic(),
        key="bot-1:BTC/USDT",
        headers=(("x-schema", "1.0"), ("x-source", "bot-1")),
    )
    assert rec.key == "bot-1:BTC/USDT"
    assert len(rec.headers) == 2


def test_kafka_publish_record_rejects_empty_key() -> None:
    with pytest.raises(ValidationError, match="key"):
        KafkaPublishRecord(
            journal_record=_record(),
            topic=_topic(),
            key="",
        )


def test_kafka_publish_record_rejects_whitespace_key() -> None:
    with pytest.raises(ValidationError, match="key"):
        KafkaPublishRecord(
            journal_record=_record(),
            topic=_topic(),
            key=" key ",
        )


def test_kafka_publish_record_rejects_duplicate_header_names() -> None:
    with pytest.raises(ValidationError, match="duplicate header names"):
        KafkaPublishRecord(
            journal_record=_record(),
            topic=_topic(),
            key="bot-1",
            headers=(("x-schema", "1.0"), ("x-schema", "2.0")),
        )


def test_kafka_publish_record_rejects_empty_header_name() -> None:
    with pytest.raises(ValidationError, match="header name"):
        KafkaPublishRecord(
            journal_record=_record(),
            topic=_topic(),
            key="bot-1",
            headers=(("", "value"),),
        )


# ── KafkaConsumedRecord ───────────────────────────────────────────────────────

def test_kafka_consumed_record_accepts_matching_topic() -> None:
    consumed = KafkaConsumedRecord(
        journal_record=_record(),
        topic=_topic(),
        key="bot-1",
        kafka_offset=_kafka_offset(partition=3, offset=12),
    )
    assert consumed.kafka_offset.partition == 3
    assert consumed.kafka_offset.offset == 12


def test_kafka_consumed_record_rejects_mismatched_topic() -> None:
    with pytest.raises(ValidationError, match=r"kafka_offset\.topic"):
        KafkaConsumedRecord(
            journal_record=_record(),
            topic=BrokerTopicId("other.topic"),
            key="bot-1",
            kafka_offset=_kafka_offset(),
        )


def test_kafka_consumed_record_preserves_journal_record() -> None:
    journal_record = _record()
    consumed = KafkaConsumedRecord(
        journal_record=journal_record,
        topic=_topic(),
        key=None,
        kafka_offset=_kafka_offset(offset=99),
    )
    assert consumed.journal_record == journal_record
    assert consumed.key is None


def test_kafka_consumed_record_has_no_db_or_checkpoint_fields() -> None:
    consumed = KafkaConsumedRecord(
        journal_record=_record(),
        topic=_topic(),
        key="bot-1",
        kafka_offset=_kafka_offset(),
    )
    assert not hasattr(consumed, "db_transaction_id")
    assert not hasattr(consumed, "batch_id")
    assert not hasattr(consumed, "last_committed_wal_offset")


# ── BrokerConsumerCursor ─────────────────────────────────────────────────────

def _broker_cursor(
    *,
    partition: int = 0,
    broker_offset: int = 42,
) -> BrokerConsumerCursor:
    return BrokerConsumerCursor(
        consumer_id=ConsumerId("consumer-1"),
        kafka_offset=_kafka_offset(partition=partition, offset=broker_offset),
        last_committed_run_id=RunId("run-1"),
        last_committed_wal_offset=WalOffset(value=5),
        last_committed_event_id=EventId("evt-1"),
        updated_at=_utc(),
    )


def test_broker_consumer_cursor_accepts_valid_input() -> None:
    cursor = _broker_cursor(partition=2, broker_offset=99)
    assert cursor.consumer_id == ConsumerId("consumer-1")
    assert cursor.kafka_offset.topic == _topic()
    assert cursor.kafka_offset.partition == 2
    assert cursor.kafka_offset.offset == 99
    assert cursor.last_committed_run_id == RunId("run-1")
    assert cursor.last_committed_wal_offset == WalOffset(value=5)
    assert cursor.last_committed_event_id == EventId("evt-1")


def test_broker_consumer_cursor_rejects_negative_partition() -> None:
    with pytest.raises(ValidationError, match="partition"):
        BrokerConsumerCursor(
            consumer_id=ConsumerId("consumer-1"),
            kafka_offset=KafkaPartitionOffset(topic=_topic(), partition=-1, offset=0),
            last_committed_run_id=RunId("run-1"),
            last_committed_wal_offset=WalOffset(value=0),
            last_committed_event_id=EventId("evt-1"),
            updated_at=_utc(),
        )


def test_broker_consumer_cursor_rejects_negative_offset() -> None:
    with pytest.raises(ValidationError, match="offset"):
        BrokerConsumerCursor(
            consumer_id=ConsumerId("consumer-1"),
            kafka_offset=KafkaPartitionOffset(topic=_topic(), partition=0, offset=-1),
            last_committed_run_id=RunId("run-1"),
            last_committed_wal_offset=WalOffset(value=0),
            last_committed_event_id=EventId("evt-1"),
            updated_at=_utc(),
        )


def test_broker_consumer_cursor_rejects_naive_updated_at() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        BrokerConsumerCursor(
            consumer_id=ConsumerId("consumer-1"),
            kafka_offset=_kafka_offset(),
            last_committed_run_id=RunId("run-1"),
            last_committed_wal_offset=WalOffset(value=0),
            last_committed_event_id=EventId("evt-1"),
            updated_at=datetime(2026, 1, 1),
        )


def test_broker_consumer_cursor_is_independent_from_db_writer_checkpoint() -> None:
    cursor = _broker_cursor()
    assert not hasattr(cursor, "db_transaction_id")
    assert not hasattr(cursor, "batch_id")
    assert not hasattr(cursor, "run_id")
    assert cursor.last_committed_run_id == RunId("run-1")


def test_broker_consumer_cursor_is_not_sidecar_checkpoint() -> None:
    cursor = _broker_cursor()
    assert not isinstance(cursor, SidecarCheckpoint)


def test_broker_consumer_cursor_cannot_appear_in_required_checkpoint_set() -> None:
    with pytest.raises(ValidationError):
        RequiredConsumerCheckpointSet(
            run_id=RunId("run-1"),
            checkpoints=(_broker_cursor(),),  # type: ignore[arg-type]
        )


# ── KafkaPublishAck ────────────────────────────────────────────────────────────

def test_kafka_publish_ack_published_requires_kafka_offset() -> None:
    ack = KafkaPublishAck(
        status=BrokerPublishStatus.PUBLISHED,
        published=True,
        journal_offset=WalOffset(value=5),
        kafka_offset=_kafka_offset(),
    )
    assert ack.published is True
    assert ack.kafka_offset is not None


def test_kafka_publish_ack_published_without_kafka_offset_rejected() -> None:
    with pytest.raises(ValidationError, match="requires kafka_offset"):
        KafkaPublishAck(
            status=BrokerPublishStatus.PUBLISHED,
            published=True,
            journal_offset=WalOffset(value=5),
        )


def test_kafka_publish_ack_rejected_requires_reason() -> None:
    ack = KafkaPublishAck(
        status=BrokerPublishStatus.REJECTED_BROKER_UNAVAILABLE,
        published=False,
        journal_offset=WalOffset(value=5),
        reason="broker down",
    )
    assert ack.published is False
    assert ack.reason == "broker down"


def test_kafka_publish_ack_rejected_without_reason_raises() -> None:
    with pytest.raises(ValidationError, match="non-empty trimmed reason"):
        KafkaPublishAck(
            status=BrokerPublishStatus.REJECTED_BROKER_UNAVAILABLE,
            published=False,
            journal_offset=WalOffset(value=5),
        )


def test_kafka_publish_ack_rejected_must_not_carry_kafka_offset() -> None:
    with pytest.raises(ValidationError, match="must not have kafka_offset"):
        KafkaPublishAck(
            status=BrokerPublishStatus.REJECTED_BROKER_UNAVAILABLE,
            published=False,
            journal_offset=WalOffset(value=5),
            kafka_offset=_kafka_offset(),
            reason="broker down",
        )


def test_kafka_publish_ack_does_not_imply_db_commit() -> None:
    # A PUBLISHED ack only means the broker accepted the message.
    # It carries no db_transaction_id, no batch_id, and no DbWriterCheckpoint.
    # Verifying the model has no such fields is the contract test.
    ack = KafkaPublishAck(
        status=BrokerPublishStatus.PUBLISHED,
        published=True,
        journal_offset=WalOffset(value=10),
        kafka_offset=_kafka_offset(),
    )
    assert not hasattr(ack, "db_transaction_id")
    assert not hasattr(ack, "batch_id")
    assert not hasattr(ack, "last_committed_wal_offset")


def test_broker_domain_does_not_import_db_writer_checkpoint_store_wal_or_gc() -> None:
    source_path = inspect.getsourcefile(broker_domain)
    assert source_path is not None
    source = Path(source_path).read_text()
    import_lines = [
        line for line in source.splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    forbidden = (
        "db_writer",
        "checkpoint",
        "LocalJsonlWal",
        "local_jsonl",
        "decide_wal_gc",
    )
    for name in forbidden:
        assert not any(name in line for line in import_lines), f"found {name!r} import"
