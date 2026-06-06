from __future__ import annotations

import inspect
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from futures_bot.db_writer.service import LocalDbWriterService
from futures_bot.domain.broker import KafkaConsumedRecord
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
from futures_bot.domain.journal import JournalRecord, WalOffset
from futures_bot.domain.sidecars import (
    SidecarHealthLevel,
    SidecarKind,
    SidecarLifecycleStatus,
)
from futures_bot.domain.wal import WalAppendResult, WalSegmentMetadata
from futures_bot.infrastructure.broker.in_memory import InMemoryBrokerPublisher
from futures_bot.infrastructure.checkpoints.in_memory import (
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


def _relay_service(
    records: tuple[JournalRecord, ...],
    publisher: InMemoryBrokerPublisher | None = None,
) -> LocalWalRelayService:
    return LocalWalRelayService(
        journal=FakeJournal(records),
        publisher=publisher or InMemoryBrokerPublisher(),
        checkpoint_store=InMemoryWalRelayCheckpointStore(),
        relay_id=SidecarId("relay-1"),
        topic=BrokerTopicId("events.topic"),
        now=_utc,
    )


def _db_writer_service(
    db_store: InMemoryCommittedEventStore | None = None,
) -> LocalDbWriterService:
    return LocalDbWriterService(
        consumer_id=ConsumerId("consumer-1"),
        db_store=db_store or InMemoryCommittedEventStore(),
        checkpoint_store=InMemoryDbWriterCheckpointStore(),
        required_checkpoint_writer=InMemoryRequiredConsumerCheckpointStore(),
        now=_utc,
    )


def test_relay_sidecar_saves_healthy_snapshot_on_successful_publish() -> None:
    health_store = InMemorySidecarHealthStore()
    publisher = InMemoryBrokerPublisher()
    sidecar = LocalWalRelaySidecar(
        sidecar_id=SidecarId("relay-sidecar"),
        relay_service=_relay_service((_record(0), _record(1)), publisher),
        health_store=health_store,
        now=_utc,
    )
    result = sidecar.run_once(max_records=10)
    snapshot = health_store.latest(SidecarId("relay-sidecar"))
    assert result is not None
    assert snapshot is not None
    assert snapshot.sidecar_kind is SidecarKind.WAL_RELAY
    assert snapshot.lifecycle_status is SidecarLifecycleStatus.RUNNING
    assert snapshot.health is SidecarHealthLevel.HEALTHY
    assert snapshot.last_processed_wal_offset == WalOffset(value=1)


def test_relay_sidecar_saves_healthy_snapshot_when_no_pending_records() -> None:
    health_store = InMemorySidecarHealthStore()
    sidecar = LocalWalRelaySidecar(
        sidecar_id=SidecarId("relay-sidecar"),
        relay_service=_relay_service(()),
        health_store=health_store,
        now=_utc,
    )
    assert sidecar.run_once(max_records=10) is None
    snapshot = health_store.latest(SidecarId("relay-sidecar"))
    assert snapshot is not None
    assert snapshot.health is SidecarHealthLevel.HEALTHY
    assert "no pending records" in (snapshot.message or "")


def test_relay_sidecar_saves_failed_snapshot_and_reraises() -> None:
    health_store = InMemorySidecarHealthStore()
    sidecar = LocalWalRelaySidecar(
        sidecar_id=SidecarId("relay-sidecar"),
        relay_service=_relay_service((_record(0),)),
        health_store=health_store,
        now=_utc,
    )
    with pytest.raises(ValueError, match="max_records"):
        sidecar.run_once(max_records=0)
    snapshot = health_store.latest(SidecarId("relay-sidecar"))
    assert snapshot is not None
    assert snapshot.lifecycle_status is SidecarLifecycleStatus.FAILED
    assert snapshot.health is SidecarHealthLevel.UNHEALTHY
    assert snapshot.error is not None


def test_db_writer_sidecar_saves_healthy_snapshot_on_commit() -> None:
    health_store = InMemorySidecarHealthStore()
    records = _publish_to_broker((_record(0), _record(1)))
    sidecar = LocalDbWriterSidecar(
        sidecar_id=SidecarId("dbw-sidecar"),
        db_writer_service=_db_writer_service(),
        health_store=health_store,
        now=_utc,
    )
    checkpoint = sidecar.commit_once(records)
    snapshot = health_store.latest(SidecarId("dbw-sidecar"))
    assert checkpoint is not None
    assert snapshot is not None
    assert snapshot.sidecar_kind is SidecarKind.DB_WRITER
    assert snapshot.lifecycle_status is SidecarLifecycleStatus.RUNNING
    assert snapshot.health is SidecarHealthLevel.HEALTHY
    assert snapshot.run_id == RunId("run-1")
    assert snapshot.last_processed_wal_offset == WalOffset(value=1)


def test_db_writer_sidecar_saves_failed_snapshot_and_reraises_on_invalid_input() -> None:
    health_store = InMemorySidecarHealthStore()
    sidecar = LocalDbWriterSidecar(
        sidecar_id=SidecarId("dbw-sidecar"),
        db_writer_service=_db_writer_service(),
        health_store=health_store,
        now=_utc,
    )
    with pytest.raises(ValueError, match="non-empty"):
        sidecar.commit_once(())
    snapshot = health_store.latest(SidecarId("dbw-sidecar"))
    assert snapshot is not None
    assert snapshot.lifecycle_status is SidecarLifecycleStatus.FAILED
    assert snapshot.health is SidecarHealthLevel.UNHEALTHY
    assert snapshot.error is not None


def test_db_writer_sidecar_saves_failed_snapshot_and_reraises_on_commit_failure() -> None:
    health_store = InMemorySidecarHealthStore()
    sidecar = LocalDbWriterSidecar(
        sidecar_id=SidecarId("dbw-sidecar"),
        db_writer_service=_db_writer_service(
            db_store=InMemoryCommittedEventStore(fail_next_commit=True)
        ),
        health_store=health_store,
        now=_utc,
    )
    with pytest.raises(RuntimeError, match="simulated"):
        sidecar.commit_once(_publish_to_broker((_record(0), _record(1))))
    snapshot = health_store.latest(SidecarId("dbw-sidecar"))
    assert snapshot is not None
    assert snapshot.lifecycle_status is SidecarLifecycleStatus.FAILED
    assert snapshot.health is SidecarHealthLevel.UNHEALTHY
    assert snapshot.error is not None


def test_local_sidecar_adapters_have_no_forbidden_imports() -> None:
    source_path = inspect.getsourcefile(LocalWalRelaySidecar)
    assert source_path is not None
    source = Path(source_path).read_text()
    forbidden = (
        "LocalJsonlWal",
        "local_jsonl",
        "decide_wal_gc",
        "confluent_kafka",
        "aiokafka",
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "subprocess",
        "threading",
        "asyncio",
        "sleep",
    )
    for name in forbidden:
        assert name not in source


def _publish_to_broker(
    records: tuple[JournalRecord, ...]
) -> tuple[KafkaConsumedRecord, ...]:
    publisher = InMemoryBrokerPublisher()
    relay = _relay_service(records, publisher)
    result = relay.relay_once(max_records=10)
    assert result is not None
    return publisher.consumed_records()
