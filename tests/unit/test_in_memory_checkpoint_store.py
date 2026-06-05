from datetime import UTC, datetime

from futures_bot.domain.broker import KafkaPartitionOffset
from futures_bot.domain.ids import BrokerTopicId, EventId, RunId, SidecarId
from futures_bot.domain.journal import WalOffset
from futures_bot.domain.sidecars import DbWriterCheckpoint, WalRelayCheckpoint
from futures_bot.infrastructure.checkpoints.in_memory import InMemoryWalRelayCheckpointStore
from futures_bot.ports.checkpoint_store import WalRelayCheckpointStorePort


def _utc() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _kafka_offset(offset: int = 0) -> KafkaPartitionOffset:
    return KafkaPartitionOffset(
        topic=BrokerTopicId("events.topic"), partition=0, offset=offset
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


# ── protocol conformance ──────────────────────────────────────────────────────

def test_in_memory_store_implements_port() -> None:
    _: WalRelayCheckpointStorePort = InMemoryWalRelayCheckpointStore()


# ── load / save ───────────────────────────────────────────────────────────────

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


# ── key isolation ─────────────────────────────────────────────────────────────

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


# ── type separation ───────────────────────────────────────────────────────────

def test_store_only_exposes_wal_relay_methods() -> None:
    # InMemoryWalRelayCheckpointStore is for WalRelayCheckpoint only.
    # It must not expose any DbWriterCheckpoint save/load methods.
    store = InMemoryWalRelayCheckpointStore()
    assert not hasattr(store, "save_db_writer_checkpoint")
    assert not hasattr(store, "load_db_writer_checkpoint")
    # The save method accepts WalRelayCheckpoint — DbWriterCheckpoint is a
    # separate type with separate fields (consumer_id, db_transaction_id, batch_id).
    assert not isinstance(_relay_checkpoint(), DbWriterCheckpoint)
