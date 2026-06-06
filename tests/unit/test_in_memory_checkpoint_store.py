from __future__ import annotations

import inspect
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from futures_bot.domain.broker import BrokerConsumerCursor, KafkaPartitionOffset
from futures_bot.domain.ids import BatchId, BrokerTopicId, ConsumerId, EventId, RunId, SidecarId
from futures_bot.domain.journal import WalOffset
from futures_bot.domain.sidecars import (
    DbWriterCheckpoint,
    RequiredConsumerCheckpointSet,
    SidecarCheckpoint,
    SidecarKind,
    WalRelayCheckpoint,
)
from futures_bot.infrastructure.checkpoints.in_memory import (
    InMemoryBrokerConsumerCursorStore,
    InMemoryDbWriterCheckpointStore,
    InMemoryRequiredConsumerCheckpointStore,
    InMemoryWalRelayCheckpointStore,
)
from futures_bot.ports.checkpoint_store import (
    BrokerConsumerCursorStorePort,
    DbWriterCheckpointStorePort,
    RequiredConsumerCheckpointStorePort,
    RequiredConsumerCheckpointWriterPort,
    WalRelayCheckpointStorePort,
)


def _utc() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _kafka_offset(
    offset: int = 0,
    *,
    topic: str = "events.topic",
    partition: int = 0,
) -> KafkaPartitionOffset:
    return KafkaPartitionOffset(
        topic=BrokerTopicId(topic), partition=partition, offset=offset
    )


def _relay_checkpoint(
    relay_id: str = "relay-1",
    run_id: str = "run-1",
    offset: int = 5,
) -> WalRelayCheckpoint:
    return WalRelayCheckpoint(
        relay_id=SidecarId(relay_id),
        run_id=RunId(run_id),
        last_published_wal_offset=WalOffset(value=offset),
        last_published_event_id=EventId("evt-1"),
        kafka_offset=_kafka_offset(offset),
        updated_at=_utc(),
    )


def _db_writer_checkpoint(
    consumer_id: str = "consumer-1",
    run_id: str = "run-1",
    offset: int = 5,
    event_id: str = "evt-1",
) -> DbWriterCheckpoint:
    return DbWriterCheckpoint(
        consumer_id=ConsumerId(consumer_id),
        run_id=RunId(run_id),
        last_committed_wal_offset=WalOffset(value=offset),
        last_committed_event_id=EventId(event_id),
        kafka_offset=_kafka_offset(offset),
        db_transaction_id=f"txn-{offset}",
        batch_id=BatchId("batch-1"),
        updated_at=_utc(),
    )


def _sidecar_checkpoint(
    sidecar_id: str = "sidecar-1",
    run_id: str = "run-1",
    offset: int = 5,
    required: bool = False,
    kind: SidecarKind = SidecarKind.DB_WRITER,
) -> SidecarCheckpoint:
    return SidecarCheckpoint(
        sidecar_id=SidecarId(sidecar_id),
        sidecar_kind=kind,
        run_id=RunId(run_id),
        last_committed_wal_offset=WalOffset(value=offset),
        updated_at=_utc(),
        is_required_for_wal_gc=required,
    )


def _broker_cursor(  # noqa: PLR0913
    *,
    consumer_id: str = "consumer-1",
    topic: str = "events.topic",
    partition: int = 0,
    broker_offset: int = 5,
    run_id: str = "run-1",
    wal_offset: int = 5,
    event_id: str = "evt-1",
) -> BrokerConsumerCursor:
    return BrokerConsumerCursor(
        consumer_id=ConsumerId(consumer_id),
        kafka_offset=_kafka_offset(
            broker_offset,
            topic=topic,
            partition=partition,
        ),
        last_committed_run_id=RunId(run_id),
        last_committed_wal_offset=WalOffset(value=wal_offset),
        last_committed_event_id=EventId(event_id),
        updated_at=_utc(),
    )


# ── InMemoryWalRelayCheckpointStore ───────────────────────────────────────────

def test_in_memory_store_implements_port() -> None:
    _: WalRelayCheckpointStorePort = InMemoryWalRelayCheckpointStore()


def test_load_missing_returns_none() -> None:
    store = InMemoryWalRelayCheckpointStore()
    assert store.load(SidecarId("relay-1"), RunId("run-1")) is None


def test_save_load_round_trip() -> None:
    store = InMemoryWalRelayCheckpointStore()
    cp = _relay_checkpoint(offset=10)
    store.save(cp)
    loaded = store.load(SidecarId("relay-1"), RunId("run-1"))
    assert loaded == cp


def test_save_overwrites_previous_checkpoint() -> None:
    store = InMemoryWalRelayCheckpointStore()
    store.save(_relay_checkpoint(offset=5))
    store.save(_relay_checkpoint(offset=15))
    loaded = store.load(SidecarId("relay-1"), RunId("run-1"))
    assert loaded is not None
    assert loaded.last_published_wal_offset.value == 15


def test_different_relay_id_is_isolated() -> None:
    store = InMemoryWalRelayCheckpointStore()
    store.save(_relay_checkpoint(relay_id="relay-A", offset=1))
    store.save(_relay_checkpoint(relay_id="relay-B", offset=2))
    a = store.load(SidecarId("relay-A"), RunId("run-1"))
    b = store.load(SidecarId("relay-B"), RunId("run-1"))
    assert a is not None and a.last_published_wal_offset.value == 1
    assert b is not None and b.last_published_wal_offset.value == 2


def test_different_run_id_is_isolated() -> None:
    store = InMemoryWalRelayCheckpointStore()
    store.save(_relay_checkpoint(run_id="run-A", offset=3))
    store.save(_relay_checkpoint(run_id="run-B", offset=7))
    a = store.load(SidecarId("relay-1"), RunId("run-A"))
    b = store.load(SidecarId("relay-1"), RunId("run-B"))
    assert a is not None and a.last_published_wal_offset.value == 3
    assert b is not None and b.last_published_wal_offset.value == 7


def test_wrong_relay_id_returns_none() -> None:
    store = InMemoryWalRelayCheckpointStore()
    store.save(_relay_checkpoint(relay_id="relay-1"))
    assert store.load(SidecarId("relay-OTHER"), RunId("run-1")) is None


# ── InMemoryWalRelayCheckpointStore type separation ───────────────────────────

def test_store_only_exposes_wal_relay_methods() -> None:
    store = InMemoryWalRelayCheckpointStore()
    assert not hasattr(store, "save_db_writer_checkpoint")
    assert not hasattr(store, "load_db_writer_checkpoint")
    assert not isinstance(_relay_checkpoint(), DbWriterCheckpoint)


# ── InMemoryDbWriterCheckpointStore ───────────────────────────────────────────

def test_db_writer_store_implements_port() -> None:
    _: DbWriterCheckpointStorePort = InMemoryDbWriterCheckpointStore()


def test_db_writer_load_missing_returns_none() -> None:
    store = InMemoryDbWriterCheckpointStore()
    assert store.load(ConsumerId("consumer-1"), RunId("run-1")) is None


def test_db_writer_save_load_round_trip() -> None:
    store = InMemoryDbWriterCheckpointStore()
    cp = _db_writer_checkpoint(offset=10)
    store.save(cp)
    loaded = store.load(ConsumerId("consumer-1"), RunId("run-1"))
    assert loaded == cp


def test_db_writer_different_consumer_id_isolated() -> None:
    store = InMemoryDbWriterCheckpointStore()
    store.save(_db_writer_checkpoint(consumer_id="consumer-A", offset=1))
    store.save(_db_writer_checkpoint(consumer_id="consumer-B", offset=2))
    a = store.load(ConsumerId("consumer-A"), RunId("run-1"))
    b = store.load(ConsumerId("consumer-B"), RunId("run-1"))
    assert a is not None and a.last_committed_wal_offset.value == 1
    assert b is not None and b.last_committed_wal_offset.value == 2


def test_db_writer_different_run_id_isolated() -> None:
    store = InMemoryDbWriterCheckpointStore()
    store.save(_db_writer_checkpoint(run_id="run-A", offset=3))
    store.save(_db_writer_checkpoint(run_id="run-B", offset=7))
    a = store.load(ConsumerId("consumer-1"), RunId("run-A"))
    b = store.load(ConsumerId("consumer-1"), RunId("run-B"))
    assert a is not None and a.last_committed_wal_offset.value == 3
    assert b is not None and b.last_committed_wal_offset.value == 7


def test_db_writer_higher_offset_overwrites() -> None:
    store = InMemoryDbWriterCheckpointStore()
    store.save(_db_writer_checkpoint(offset=5, event_id="evt-5"))
    store.save(_db_writer_checkpoint(offset=10, event_id="evt-10"))
    loaded = store.load(ConsumerId("consumer-1"), RunId("run-1"))
    assert loaded is not None
    assert loaded.last_committed_wal_offset.value == 10


def test_db_writer_lower_offset_raises_value_error() -> None:
    store = InMemoryDbWriterCheckpointStore()
    store.save(_db_writer_checkpoint(offset=10, event_id="evt-10"))
    with pytest.raises(ValueError, match="10"):
        store.save(_db_writer_checkpoint(offset=5, event_id="evt-5"))


def test_db_writer_lower_offset_error_mentions_new_offset() -> None:
    store = InMemoryDbWriterCheckpointStore()
    store.save(_db_writer_checkpoint(offset=10, event_id="evt-10"))
    with pytest.raises(ValueError, match="5"):
        store.save(_db_writer_checkpoint(offset=5, event_id="evt-5"))


def test_db_writer_same_offset_same_event_id_idempotent() -> None:
    store = InMemoryDbWriterCheckpointStore()
    cp = _db_writer_checkpoint(offset=10, event_id="evt-10")
    store.save(cp)
    store.save(cp)  # second save must not raise
    loaded = store.load(ConsumerId("consumer-1"), RunId("run-1"))
    assert loaded is not None
    assert loaded.last_committed_wal_offset.value == 10


def test_db_writer_same_offset_different_event_id_raises() -> None:
    store = InMemoryDbWriterCheckpointStore()
    store.save(_db_writer_checkpoint(offset=10, event_id="evt-10"))
    with pytest.raises(ValueError, match="conflict"):
        store.save(_db_writer_checkpoint(offset=10, event_id="evt-CONFLICT"))


def test_db_writer_store_does_not_expose_wal_relay_methods() -> None:
    store = InMemoryDbWriterCheckpointStore()
    assert not hasattr(store, "save_wal_relay_checkpoint")
    assert not hasattr(store, "load_wal_relay_checkpoint")
    assert not hasattr(store, "last_published_wal_offset")


# ── InMemoryBrokerConsumerCursorStore ─────────────────────────────────────────

def test_broker_cursor_store_implements_port() -> None:
    _: BrokerConsumerCursorStorePort = InMemoryBrokerConsumerCursorStore()


def test_broker_cursor_load_missing_returns_none() -> None:
    store = InMemoryBrokerConsumerCursorStore()
    assert store.load(ConsumerId("consumer-1"), BrokerTopicId("events.topic"), 0) is None


def test_broker_cursor_save_load_round_trip() -> None:
    store = InMemoryBrokerConsumerCursorStore()
    cursor = _broker_cursor(broker_offset=10)
    store.save(cursor)
    loaded = store.load(ConsumerId("consumer-1"), BrokerTopicId("events.topic"), 0)
    assert loaded == cursor


def test_broker_cursor_higher_broker_offset_overwrites() -> None:
    store = InMemoryBrokerConsumerCursorStore()
    store.save(_broker_cursor(broker_offset=5, wal_offset=5, event_id="evt-5"))
    store.save(_broker_cursor(broker_offset=10, wal_offset=10, event_id="evt-10"))
    loaded = store.load(ConsumerId("consumer-1"), BrokerTopicId("events.topic"), 0)
    assert loaded is not None
    assert loaded.kafka_offset.offset == 10
    assert loaded.last_committed_wal_offset == WalOffset(value=10)


def test_broker_cursor_lower_broker_offset_raises() -> None:
    store = InMemoryBrokerConsumerCursorStore()
    store.save(_broker_cursor(broker_offset=10, wal_offset=10, event_id="evt-10"))
    with pytest.raises(ValueError, match="regression"):
        store.save(_broker_cursor(broker_offset=5, wal_offset=5, event_id="evt-5"))


def test_broker_cursor_same_offset_same_metadata_is_idempotent() -> None:
    store = InMemoryBrokerConsumerCursorStore()
    cursor = _broker_cursor(broker_offset=10, wal_offset=10, event_id="evt-10")
    store.save(cursor)
    store.save(cursor)
    assert store.load(ConsumerId("consumer-1"), BrokerTopicId("events.topic"), 0) == cursor


def test_broker_cursor_same_offset_different_run_id_raises() -> None:
    store = InMemoryBrokerConsumerCursorStore()
    store.save(_broker_cursor(broker_offset=10, run_id="run-1"))
    with pytest.raises(ValueError, match="conflict"):
        store.save(_broker_cursor(broker_offset=10, run_id="run-2"))


def test_broker_cursor_same_offset_different_wal_offset_raises() -> None:
    store = InMemoryBrokerConsumerCursorStore()
    store.save(_broker_cursor(broker_offset=10, wal_offset=10))
    with pytest.raises(ValueError, match="conflict"):
        store.save(_broker_cursor(broker_offset=10, wal_offset=11))


def test_broker_cursor_same_offset_different_event_id_raises() -> None:
    store = InMemoryBrokerConsumerCursorStore()
    store.save(_broker_cursor(broker_offset=10, event_id="evt-10"))
    with pytest.raises(ValueError, match="conflict"):
        store.save(_broker_cursor(broker_offset=10, event_id="evt-other"))


def test_broker_cursor_same_consumer_different_topic_isolated() -> None:
    store = InMemoryBrokerConsumerCursorStore()
    store.save(_broker_cursor(topic="topic-a", broker_offset=1))
    store.save(_broker_cursor(topic="topic-b", broker_offset=2))
    a = store.load(ConsumerId("consumer-1"), BrokerTopicId("topic-a"), 0)
    b = store.load(ConsumerId("consumer-1"), BrokerTopicId("topic-b"), 0)
    assert a is not None and a.kafka_offset.offset == 1
    assert b is not None and b.kafka_offset.offset == 2


def test_broker_cursor_same_consumer_topic_different_partition_isolated() -> None:
    store = InMemoryBrokerConsumerCursorStore()
    store.save(_broker_cursor(partition=0, broker_offset=1))
    store.save(_broker_cursor(partition=1, broker_offset=2))
    a = store.load(ConsumerId("consumer-1"), BrokerTopicId("events.topic"), 0)
    b = store.load(ConsumerId("consumer-1"), BrokerTopicId("events.topic"), 1)
    assert a is not None and a.kafka_offset.offset == 1
    assert b is not None and b.kafka_offset.offset == 2


def test_broker_cursor_same_topic_partition_different_consumer_isolated() -> None:
    store = InMemoryBrokerConsumerCursorStore()
    store.save(_broker_cursor(consumer_id="consumer-a", broker_offset=1))
    store.save(_broker_cursor(consumer_id="consumer-b", broker_offset=2))
    a = store.load(ConsumerId("consumer-a"), BrokerTopicId("events.topic"), 0)
    b = store.load(ConsumerId("consumer-b"), BrokerTopicId("events.topic"), 0)
    assert a is not None and a.kafka_offset.offset == 1
    assert b is not None and b.kafka_offset.offset == 2


def test_broker_cursor_store_rejects_db_writer_checkpoint() -> None:
    store = InMemoryBrokerConsumerCursorStore()
    with pytest.raises(TypeError, match="BrokerConsumerCursor"):
        store.save(_db_writer_checkpoint())  # type: ignore[arg-type]


def test_broker_cursor_store_rejects_wal_relay_checkpoint() -> None:
    store = InMemoryBrokerConsumerCursorStore()
    with pytest.raises(TypeError, match="BrokerConsumerCursor"):
        store.save(_relay_checkpoint())  # type: ignore[arg-type]


def test_broker_cursor_store_rejects_sidecar_checkpoint() -> None:
    store = InMemoryBrokerConsumerCursorStore()
    with pytest.raises(TypeError, match="BrokerConsumerCursor"):
        store.save(_sidecar_checkpoint())  # type: ignore[arg-type]


def test_broker_cursor_store_does_not_expose_checkpoint_methods() -> None:
    store = InMemoryBrokerConsumerCursorStore()
    assert not hasattr(store, "save_wal_relay_checkpoint")
    assert not hasattr(store, "load_wal_relay_checkpoint")
    assert not hasattr(store, "save_db_writer_checkpoint")
    assert not hasattr(store, "load_db_writer_checkpoint")
    assert not hasattr(store, "upsert")
    assert not hasattr(store, "load_required_checkpoints")


# ── InMemoryRequiredConsumerCheckpointStore ───────────────────────────────────

def test_required_store_implements_port() -> None:
    _: RequiredConsumerCheckpointStorePort = InMemoryRequiredConsumerCheckpointStore()


def test_required_store_implements_writer_port() -> None:
    _: RequiredConsumerCheckpointWriterPort = InMemoryRequiredConsumerCheckpointStore()


def test_required_writer_port_accepts_db_writer_sidecar_checkpoint() -> None:
    store: RequiredConsumerCheckpointWriterPort = InMemoryRequiredConsumerCheckpointStore()
    store.upsert(
        _sidecar_checkpoint(
            sidecar_id="db-writer-consumer-1",
            run_id="run-1",
            offset=10,
            required=True,
            kind=SidecarKind.DB_WRITER,
        )
    )


def test_required_store_empty_returns_empty_set() -> None:
    store = InMemoryRequiredConsumerCheckpointStore()
    result = store.load_required_checkpoints(RunId("run-1"))
    assert isinstance(result, RequiredConsumerCheckpointSet)
    assert result.checkpoints == ()
    assert result.required_checkpoints() == ()


def test_required_store_filters_by_run_id() -> None:
    store = InMemoryRequiredConsumerCheckpointStore(
        checkpoints=(
            _sidecar_checkpoint(sidecar_id="s-1", run_id="run-1", offset=10),
            _sidecar_checkpoint(sidecar_id="s-2", run_id="run-OTHER", offset=20),
        )
    )
    result = store.load_required_checkpoints(RunId("run-1"))
    assert len(result.checkpoints) == 1
    assert str(result.checkpoints[0].sidecar_id) == "s-1"


def test_required_store_includes_both_required_and_optional() -> None:
    store = InMemoryRequiredConsumerCheckpointStore(
        checkpoints=(
            _sidecar_checkpoint(sidecar_id="s-required", run_id="run-1", required=True),
            _sidecar_checkpoint(sidecar_id="s-optional", run_id="run-1", required=False),
        )
    )
    result = store.load_required_checkpoints(RunId("run-1"))
    assert len(result.checkpoints) == 2
    # required_checkpoints() filters to only the required ones
    assert len(result.required_checkpoints()) == 1
    assert str(result.required_checkpoints()[0].sidecar_id) == "s-required"


def test_required_store_upsert_adds_checkpoint() -> None:
    store = InMemoryRequiredConsumerCheckpointStore()
    cp = _sidecar_checkpoint(sidecar_id="s-1", run_id="run-1", offset=5)
    store.upsert(cp)
    result = store.load_required_checkpoints(RunId("run-1"))
    assert len(result.checkpoints) == 1


def test_required_store_upsert_higher_offset_overwrites() -> None:
    store = InMemoryRequiredConsumerCheckpointStore()
    store.upsert(_sidecar_checkpoint(sidecar_id="s-1", run_id="run-1", offset=5))
    store.upsert(_sidecar_checkpoint(sidecar_id="s-1", run_id="run-1", offset=10))
    result = store.load_required_checkpoints(RunId("run-1"))
    assert result.checkpoints[0].last_committed_wal_offset.value == 10


def test_required_store_upsert_lower_offset_raises() -> None:
    store = InMemoryRequiredConsumerCheckpointStore()
    store.upsert(_sidecar_checkpoint(sidecar_id="s-1", run_id="run-1", offset=10))
    with pytest.raises(ValueError, match="regression"):
        store.upsert(_sidecar_checkpoint(sidecar_id="s-1", run_id="run-1", offset=5))


def test_required_store_replace_resets_state() -> None:
    store = InMemoryRequiredConsumerCheckpointStore(
        checkpoints=(_sidecar_checkpoint(sidecar_id="old", run_id="run-1"),)
    )
    store.replace((_sidecar_checkpoint(sidecar_id="new", run_id="run-1"),))
    result = store.load_required_checkpoints(RunId("run-1"))
    assert len(result.checkpoints) == 1
    assert str(result.checkpoints[0].sidecar_id) == "new"


def test_required_store_does_not_expose_db_writer_methods() -> None:
    store = InMemoryRequiredConsumerCheckpointStore()
    assert not hasattr(store, "save_db_writer_checkpoint")
    assert not hasattr(store, "load_db_writer_checkpoint")
    assert not hasattr(store, "last_committed_wal_offset")


def test_required_store_wal_relay_required_rejected_by_model() -> None:
    # The SidecarCheckpoint model validator rejects WAL_RELAY + is_required=True.
    # This protects the store from ever holding a WAL_RELAY required checkpoint.
    with pytest.raises(ValidationError, match="WAL_RELAY"):
        _sidecar_checkpoint(
            sidecar_id="relay-1",
            run_id="run-1",
            kind=SidecarKind.WAL_RELAY,
            required=True,
        )


# ── infrastructure boundary: no forbidden imports ─────────────────────────────

def _checkpoints_mod_source() -> str:
    source_path = inspect.getsourcefile(InMemoryWalRelayCheckpointStore)
    assert source_path is not None
    return Path(source_path).read_text()


def _import_lines(source: str) -> list[str]:
    return [
        line for line in source.splitlines()
        if line.strip().startswith(("import ", "from "))
    ]


def test_in_memory_checkpoints_do_not_import_db_libraries() -> None:
    lines = _import_lines(_checkpoints_mod_source())
    forbidden = ("sqlalchemy", "psycopg", "asyncpg", "duckdb", "sqlite", "postgres")
    for lib in forbidden:
        assert not any(lib in line for line in lines), f"found {lib!r} import"


def test_in_memory_checkpoints_do_not_import_kafka_libraries() -> None:
    lines = _import_lines(_checkpoints_mod_source())
    forbidden = ("confluent_kafka", "kafka", "aiokafka")
    for lib in forbidden:
        assert not any(lib in line for line in lines), f"found {lib!r} import"


def test_in_memory_checkpoints_do_not_import_local_jsonl_wal() -> None:
    lines = _import_lines(_checkpoints_mod_source())
    assert not any("local_jsonl" in line for line in lines)
    assert not any("LocalJsonlWal" in line for line in lines)


def test_in_memory_checkpoints_do_not_import_decide_wal_gc() -> None:
    lines = _import_lines(_checkpoints_mod_source())
    assert not any("decide_wal_gc" in line for line in lines)
