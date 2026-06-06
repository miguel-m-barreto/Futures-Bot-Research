from __future__ import annotations

import inspect
from datetime import UTC, datetime
from pathlib import Path

import pytest

from futures_bot.db_writer.service import LocalDbWriterService
from futures_bot.domain.broker import (
    KafkaConsumedRecord,
    KafkaPartitionOffset,
    KafkaPublishRecord,
)
from futures_bot.domain.events import EventEnvelope, EventType
from futures_bot.domain.ids import BotId, BrokerTopicId, ConsumerId, EventId, ProducerId, RunId
from futures_bot.domain.journal import JournalRecord, WalOffset
from futures_bot.domain.sidecars import SidecarKind
from futures_bot.infrastructure.checkpoints.in_memory import (
    InMemoryDbWriterCheckpointStore,
    InMemoryRequiredConsumerCheckpointStore,
)
from futures_bot.infrastructure.db_writer.in_memory import InMemoryCommittedEventStore


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


def _journal_record(
    offset: int,
    *,
    run_id: str = "run-1",
    event_id: str | None = None,
) -> JournalRecord:
    return JournalRecord(
        run_id=RunId(run_id),
        producer_id=ProducerId("prod-1"),
        wal_offset=WalOffset(value=offset),
        event=_event(event_id or f"evt-{offset}"),
        recorded_at=_utc(),
        payload_hash=f"hash-{offset}",
        record_size_bytes=64,
    )


def _consumed_record(
    offset: int,
    *,
    run_id: str = "run-1",
    event_id: str | None = None,
    broker_offset: int | None = None,
) -> KafkaConsumedRecord:
    topic = BrokerTopicId("events.topic")
    return KafkaConsumedRecord(
        journal_record=_journal_record(offset, run_id=run_id, event_id=event_id),
        topic=topic,
        key="bot-1",
        kafka_offset=KafkaPartitionOffset(
            topic=topic,
            partition=0,
            offset=offset + 100 if broker_offset is None else broker_offset,
        ),
    )


def _records(*offsets: int, run_id: str = "run-1") -> tuple[KafkaConsumedRecord, ...]:
    return tuple(_consumed_record(offset, run_id=run_id) for offset in offsets)


def _records_with_broker_offsets(
    pairs: tuple[tuple[int, int], ...],
    *,
    run_id: str = "run-1",
    event_id: str | None = None,
) -> tuple[KafkaConsumedRecord, ...]:
    return tuple(
        _consumed_record(
            wal_offset,
            run_id=run_id,
            event_id=event_id,
            broker_offset=broker_offset,
        )
        for wal_offset, broker_offset in pairs
    )


def _raw_publish_record(offset: int) -> KafkaPublishRecord:
    return KafkaPublishRecord(
        journal_record=_journal_record(offset),
        topic=BrokerTopicId("events.topic"),
        key="bot-1",
    )


def _service(
    *,
    db_store: InMemoryCommittedEventStore | None = None,
    checkpoint_store: InMemoryDbWriterCheckpointStore | None = None,
    required_store: InMemoryRequiredConsumerCheckpointStore | None = None,
    is_required_for_wal_gc: bool = True,
) -> tuple[
    LocalDbWriterService,
    InMemoryCommittedEventStore,
    InMemoryDbWriterCheckpointStore,
    InMemoryRequiredConsumerCheckpointStore,
]:
    db_store = db_store or InMemoryCommittedEventStore()
    checkpoint_store = checkpoint_store or InMemoryDbWriterCheckpointStore()
    required_store = required_store or InMemoryRequiredConsumerCheckpointStore()
    service = LocalDbWriterService(
        consumer_id=ConsumerId("consumer-1"),
        db_store=db_store,
        checkpoint_store=checkpoint_store,
        required_checkpoint_writer=required_store,
        is_required_for_wal_gc=is_required_for_wal_gc,
        now=_utc,
    )
    return service, db_store, checkpoint_store, required_store


def test_empty_batch_raises_value_error() -> None:
    service, _, _, _ = _service()
    with pytest.raises(ValueError, match="non-empty"):
        service.commit_consumed_batch(())


def test_raw_publish_batch_api_rejects_kafka_publish_records() -> None:
    service, _, _, _ = _service()
    with pytest.raises(TypeError, match="KafkaConsumedRecord"):
        service.commit_published_batch((_raw_publish_record(0),))


def test_consumed_batch_rejects_raw_kafka_publish_record_input() -> None:
    service, _, _, _ = _service()
    with pytest.raises(TypeError, match="KafkaConsumedRecord"):
        service.commit_consumed_batch(  # type: ignore[arg-type]
            (_raw_publish_record(0),)
        )


def test_first_commit_saves_checkpoint_after_fake_durable_commit() -> None:
    service, db_store, checkpoint_store, _ = _service()
    checkpoint = service.commit_consumed_batch(_records(0, 1, 2))
    assert db_store.has_committed(RunId("run-1"), WalOffset(value=2))
    assert checkpoint_store.load(ConsumerId("consumer-1"), RunId("run-1")) == checkpoint


def test_checkpoint_last_committed_offset_equals_last_record_offset() -> None:
    service, _, _, _ = _service()
    checkpoint = service.commit_consumed_batch(_records(3, 4, 5))
    assert checkpoint is not None
    assert checkpoint.last_committed_wal_offset == WalOffset(value=5)


def test_checkpoint_last_committed_event_id_equals_last_record_event_id() -> None:
    service, _, _, _ = _service()
    checkpoint = service.commit_consumed_batch(_records(0, 1, 2))
    assert checkpoint is not None
    assert checkpoint.last_committed_event_id == EventId("evt-2")


def test_checkpoint_kafka_offset_uses_consumed_broker_offset_not_wal_offset() -> None:
    service, _, _, _ = _service()
    records = _records_with_broker_offsets(((10, 0), (11, 1), (12, 2)))
    checkpoint = service.commit_consumed_batch(records)
    assert checkpoint is not None
    assert checkpoint.last_committed_wal_offset == WalOffset(value=12)
    assert checkpoint.kafka_offset == records[-1].kafka_offset
    assert checkpoint.kafka_offset.offset == 2


def test_required_checkpoint_writer_receives_db_writer_checkpoint_after_commit() -> None:
    service, _, _, required_store = _service()
    service.commit_consumed_batch(_records(0, 1))
    checkpoint_set = required_store.load_required_checkpoints(RunId("run-1"))
    assert len(checkpoint_set.checkpoints) == 1
    checkpoint = checkpoint_set.checkpoints[0]
    assert checkpoint.sidecar_kind is SidecarKind.DB_WRITER
    assert checkpoint.last_committed_wal_offset == WalOffset(value=1)


def test_required_checkpoint_is_required_for_wal_gc_by_default() -> None:
    service, _, _, required_store = _service()
    service.commit_consumed_batch(_records(0))
    checkpoint_set = required_store.load_required_checkpoints(RunId("run-1"))
    assert checkpoint_set.checkpoints[0].is_required_for_wal_gc is True
    assert checkpoint_set.required_min_offset() == WalOffset(value=0)


def test_optional_required_checkpoint_does_not_authorize_gc() -> None:
    service, _, _, required_store = _service(is_required_for_wal_gc=False)
    service.commit_consumed_batch(_records(0))
    checkpoint_set = required_store.load_required_checkpoints(RunId("run-1"))
    assert checkpoint_set.checkpoints[0].is_required_for_wal_gc is False
    assert checkpoint_set.required_checkpoints() == ()
    assert checkpoint_set.required_min_offset() is None


def test_second_commit_resumes_after_checkpoint() -> None:
    service, db_store, checkpoint_store, _ = _service()
    service.commit_consumed_batch(_records(0, 1))
    checkpoint = service.commit_consumed_batch(_records(2, 3))
    assert checkpoint is not None
    assert checkpoint.last_committed_wal_offset == WalOffset(value=3)
    assert db_store.committed_offsets(RunId("run-1")) == (
        WalOffset(value=0),
        WalOffset(value=1),
        WalOffset(value=2),
        WalOffset(value=3),
    )
    loaded = checkpoint_store.load(ConsumerId("consumer-1"), RunId("run-1"))
    assert loaded == checkpoint


def test_duplicate_already_committed_records_return_existing_checkpoint() -> None:
    service, _, checkpoint_store, _ = _service()
    existing = service.commit_consumed_batch(_records(0, 1))
    duplicate = service.commit_consumed_batch(_records(0, 1))
    assert duplicate == existing
    assert checkpoint_store.load(ConsumerId("consumer-1"), RunId("run-1")) == existing


def test_duplicate_same_event_conflicting_broker_offset_is_rejected() -> None:
    service, _, _, _ = _service()
    service.commit_consumed_batch(_records(0, 1))
    conflicting = _records_with_broker_offsets(((0, 200), (1, 201)))
    with pytest.raises(ValueError, match="kafka_offset"):
        service.commit_consumed_batch(conflicting)


def test_gap_after_checkpoint_raises_and_commits_nothing_new() -> None:
    service, db_store, checkpoint_store, _ = _service()
    service.commit_consumed_batch(_records(0, 1))
    with pytest.raises(ValueError, match="expected next offset 2"):
        service.commit_consumed_batch(_records(3, 4))
    assert db_store.committed_offsets(RunId("run-1")) == (
        WalOffset(value=0),
        WalOffset(value=1),
    )
    checkpoint = checkpoint_store.load(ConsumerId("consumer-1"), RunId("run-1"))
    assert checkpoint is not None
    assert checkpoint.last_committed_wal_offset == WalOffset(value=1)


def test_commit_failure_does_not_save_db_writer_checkpoint() -> None:
    service, _, checkpoint_store, _ = _service(
        db_store=InMemoryCommittedEventStore(fail_next_commit=True)
    )
    with pytest.raises(RuntimeError, match="simulated"):
        service.commit_consumed_batch(_records(0, 1))
    assert checkpoint_store.load(ConsumerId("consumer-1"), RunId("run-1")) is None


def test_commit_failure_does_not_upsert_required_checkpoint() -> None:
    service, _, _, required_store = _service(
        db_store=InMemoryCommittedEventStore(fail_next_commit=True)
    )
    with pytest.raises(RuntimeError, match="simulated"):
        service.commit_consumed_batch(_records(0, 1))
    assert required_store.load_required_checkpoints(RunId("run-1")).checkpoints == ()


def test_service_does_not_import_wal_relay_checkpoint_or_gc_logic() -> None:
    source_path = inspect.getsourcefile(LocalDbWriterService)
    assert source_path is not None
    source = Path(source_path).read_text()
    import_lines = [
        line for line in source.splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    assert not any("WalRelayCheckpoint" in line for line in import_lines)
    assert not any("local_jsonl" in line for line in import_lines)
    assert not any("LocalJsonlWal" in line for line in import_lines)
    assert not any("decide_wal_gc" in line for line in import_lines)
    forbidden = ("sqlalchemy", "psycopg", "asyncpg", "duckdb", "sqlite", "confluent_kafka")
    for name in forbidden:
        assert not any(name in line for line in import_lines), f"found {name!r} import"
