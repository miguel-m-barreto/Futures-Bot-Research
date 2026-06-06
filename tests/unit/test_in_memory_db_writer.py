from __future__ import annotations

import inspect
from datetime import UTC, datetime
from pathlib import Path

import pytest

from futures_bot.domain.broker import KafkaPublishRecord
from futures_bot.domain.events import EventEnvelope, EventType
from futures_bot.domain.ids import BotId, BrokerTopicId, EventId, ProducerId, RunId
from futures_bot.domain.journal import JournalRecord, WalOffset
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


def _kafka_record(
    offset: int,
    *,
    run_id: str = "run-1",
    event_id: str | None = None,
) -> KafkaPublishRecord:
    return KafkaPublishRecord(
        journal_record=_journal_record(offset, run_id=run_id, event_id=event_id),
        topic=BrokerTopicId("events.topic"),
        key="bot-1",
    )


def _records(*offsets: int, run_id: str = "run-1") -> tuple[KafkaPublishRecord, ...]:
    return tuple(_kafka_record(offset, run_id=run_id) for offset in offsets)


def test_commit_contiguous_batch_stores_records() -> None:
    store = InMemoryCommittedEventStore()
    committed = store.commit_records(_records(0, 1, 2))
    assert len(committed) == 3
    assert store.has_committed(RunId("run-1"), WalOffset(value=2))


def test_committed_records_returns_offset_order() -> None:
    store = InMemoryCommittedEventStore()
    store.commit_records(_records(3, 4))
    store.commit_records(_records(1, 2))
    assert [record.wal_offset.value for record in store.committed_records(RunId("run-1"))] == [
        1,
        2,
        3,
        4,
    ]


def test_committed_offsets_returns_offset_order() -> None:
    store = InMemoryCommittedEventStore()
    store.commit_records(_records(5, 6))
    assert store.committed_offsets(RunId("run-1")) == (
        WalOffset(value=5),
        WalOffset(value=6),
    )


def test_empty_batch_raises_value_error() -> None:
    store = InMemoryCommittedEventStore()
    with pytest.raises(ValueError, match="non-empty"):
        store.commit_records(())


def test_mixed_run_id_raises_value_error() -> None:
    store = InMemoryCommittedEventStore()
    records = (_kafka_record(0, run_id="run-1"), _kafka_record(1, run_id="run-2"))
    with pytest.raises(ValueError, match="same run_id"):
        store.commit_records(records)


def test_unsorted_offsets_raises_value_error() -> None:
    store = InMemoryCommittedEventStore()
    with pytest.raises(ValueError, match="sorted"):
        store.commit_records(_records(2, 1))


def test_non_contiguous_offsets_raises_value_error() -> None:
    store = InMemoryCommittedEventStore()
    with pytest.raises(ValueError, match="contiguous"):
        store.commit_records(_records(0, 2))


def test_fail_next_commit_raises_and_stores_nothing() -> None:
    store = InMemoryCommittedEventStore(fail_next_commit=True)
    with pytest.raises(RuntimeError, match="simulated"):
        store.commit_records(_records(0, 1))
    assert store.committed_records(RunId("run-1")) == ()


def test_same_offset_same_event_id_is_idempotent() -> None:
    store = InMemoryCommittedEventStore()
    record = _kafka_record(7, event_id="evt-same")
    store.commit_records((record,))
    store.commit_records((record,))
    assert store.committed_offsets(RunId("run-1")) == (WalOffset(value=7),)


def test_same_offset_different_event_id_raises_value_error() -> None:
    store = InMemoryCommittedEventStore()
    store.commit_records((_kafka_record(7, event_id="evt-a"),))
    with pytest.raises(ValueError, match="conflict"):
        store.commit_records((_kafka_record(7, event_id="evt-b"),))


def _source() -> str:
    source_path = inspect.getsourcefile(InMemoryCommittedEventStore)
    assert source_path is not None
    return Path(source_path).read_text()


def _import_lines(source: str) -> list[str]:
    return [
        line for line in source.splitlines()
        if line.strip().startswith(("import ", "from "))
    ]


def test_in_memory_db_writer_store_does_not_import_db_libraries() -> None:
    lines = _import_lines(_source())
    forbidden = ("sqlalchemy", "psycopg", "asyncpg", "duckdb", "sqlite", "postgres")
    for lib in forbidden:
        assert not any(lib in line for line in lines), f"found {lib!r} import"


def test_in_memory_db_writer_store_does_not_import_kafka_clients() -> None:
    lines = _import_lines(_source())
    forbidden = ("confluent_kafka", "aiokafka")
    for lib in forbidden:
        assert not any(lib in line for line in lines), f"found {lib!r} import"


def test_in_memory_db_writer_store_does_not_import_wal_or_gc_logic() -> None:
    lines = _import_lines(_source())
    assert not any("local_jsonl" in line for line in lines)
    assert not any("LocalJsonlWal" in line for line in lines)
    assert not any("decide_wal_gc" in line for line in lines)
