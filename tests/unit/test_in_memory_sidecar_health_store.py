from __future__ import annotations

import inspect
from datetime import UTC, datetime
from pathlib import Path

import pytest

from futures_bot.domain.ids import SidecarId
from futures_bot.domain.sidecars import (
    SidecarHealthLevel,
    SidecarHealthSnapshot,
    SidecarKind,
    SidecarLifecycleStatus,
)
from futures_bot.infrastructure.sidecars.in_memory import InMemorySidecarHealthStore
from futures_bot.ports.sidecar_runtime import SidecarHealthStorePort


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _snapshot(
    sidecar_id: str,
    *,
    sidecar_kind: SidecarKind = SidecarKind.WAL_RELAY,
    checked_at: datetime | None = None,
) -> SidecarHealthSnapshot:
    return SidecarHealthSnapshot(
        sidecar_id=SidecarId(sidecar_id),
        sidecar_kind=sidecar_kind,
        lifecycle_status=SidecarLifecycleStatus.RUNNING,
        health=SidecarHealthLevel.HEALTHY,
        checked_at=checked_at or _utc(),
    )


def test_in_memory_health_store_implements_port() -> None:
    _: SidecarHealthStorePort = InMemorySidecarHealthStore()


def test_latest_missing_returns_none() -> None:
    store = InMemorySidecarHealthStore()
    assert store.latest(SidecarId("missing")) is None


def test_save_latest_round_trip() -> None:
    store = InMemorySidecarHealthStore()
    snapshot = _snapshot("relay-1")
    store.save(snapshot)
    assert store.latest(SidecarId("relay-1")) == snapshot


def test_second_snapshot_with_newer_timestamp_overwrites() -> None:
    store = InMemorySidecarHealthStore()
    old = _snapshot("relay-1", checked_at=_utc(0))
    new = _snapshot("relay-1", checked_at=_utc(1))
    store.save(old)
    store.save(new)
    assert store.latest(SidecarId("relay-1")) == new


def test_second_snapshot_with_equal_timestamp_overwrites() -> None:
    store = InMemorySidecarHealthStore()
    first = _snapshot("relay-1", checked_at=_utc(0))
    second = _snapshot(
        "relay-1", sidecar_kind=SidecarKind.DB_WRITER, checked_at=_utc(0)
    )
    store.save(first)
    store.save(second)
    assert store.latest(SidecarId("relay-1")) == second


def test_older_timestamp_rejected() -> None:
    store = InMemorySidecarHealthStore()
    store.save(_snapshot("relay-1", checked_at=_utc(1)))
    with pytest.raises(ValueError, match="regression"):
        store.save(_snapshot("relay-1", checked_at=_utc(0)))


def test_list_all_returns_deterministic_sidecar_id_order() -> None:
    store = InMemorySidecarHealthStore()
    store.save(_snapshot("sidecar-b"))
    store.save(_snapshot("sidecar-a"))
    assert [str(snapshot.sidecar_id) for snapshot in store.list_all()] == [
        "sidecar-a",
        "sidecar-b",
    ]


def test_list_by_kind_filters_and_sorts() -> None:
    store = InMemorySidecarHealthStore()
    store.save(_snapshot("relay-b", sidecar_kind=SidecarKind.WAL_RELAY))
    store.save(_snapshot("dbw-1", sidecar_kind=SidecarKind.DB_WRITER))
    store.save(_snapshot("relay-a", sidecar_kind=SidecarKind.WAL_RELAY))
    assert [str(snapshot.sidecar_id) for snapshot in store.list_by_kind(SidecarKind.WAL_RELAY)] == [
        "relay-a",
        "relay-b",
    ]


def test_in_memory_health_store_has_no_forbidden_imports() -> None:
    source_path = inspect.getsourcefile(InMemorySidecarHealthStore)
    assert source_path is not None
    source = Path(source_path).read_text()
    import_lines = [
        line for line in source.splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
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
        assert not any(name in line for line in import_lines), f"found {name!r} import"
