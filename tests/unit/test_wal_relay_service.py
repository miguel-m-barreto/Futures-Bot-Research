from __future__ import annotations

import inspect
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from futures_bot.domain.events import EventEnvelope, EventType
from futures_bot.domain.ids import (
    BotId,
    BrokerTopicId,
    EventId,
    ProducerId,
    RunId,
    SidecarId,
    WalSegmentId,
)
from futures_bot.domain.journal import JournalRecord, WalOffset
from futures_bot.domain.wal import WalAppendResult, WalSegmentMetadata, WalSegmentStatus
from futures_bot.infrastructure.broker.in_memory import InMemoryBrokerPublisher
from futures_bot.infrastructure.checkpoints.in_memory import InMemoryWalRelayCheckpointStore
from futures_bot.infrastructure.wal.local_jsonl import LocalJsonlWal, LocalJsonlWalConfig
from futures_bot.relay.service import LocalWalRelayService

# ── helpers ───────────────────────────────────────────────────────────────────

def _utc() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _event(bot_id: str = "bot-1", event_id: str = "evt-0") -> EventEnvelope:
    return EventEnvelope(
        event_id=EventId(event_id),
        event_type=EventType.BOT_CREATED,
        occurred_at=_utc(),
        bot_id=BotId(bot_id),
        schema_version="1.0",
    )


def _record(offset: int, run_id: str = "run-1") -> JournalRecord:
    return JournalRecord(
        run_id=RunId(run_id),
        producer_id=ProducerId("prod-1"),
        wal_offset=WalOffset(value=offset),
        event=_event(event_id=f"evt-{offset}"),
        recorded_at=_utc(),
        payload_hash="abc123",
        record_size_bytes=64,
    )


def _records(*offsets: int, run_id: str = "run-1") -> list[JournalRecord]:
    return [_record(off, run_id=run_id) for off in offsets]


class FakeJournal:
    """Minimal EventJournalPort implementation for service tests.

    Only iter_records() is used by LocalWalRelayService.  All other methods
    raise NotImplementedError so accidental calls surface clearly.
    """

    def __init__(self, records: list[JournalRecord]) -> None:
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


def _setup(
    records: list[JournalRecord],
    fail_next: bool = False,
) -> tuple[LocalWalRelayService, InMemoryBrokerPublisher, InMemoryWalRelayCheckpointStore]:
    journal = FakeJournal(records)
    publisher = InMemoryBrokerPublisher(fail_next=fail_next)
    store = InMemoryWalRelayCheckpointStore()
    service = LocalWalRelayService(
        journal=journal,
        publisher=publisher,
        checkpoint_store=store,
        relay_id=SidecarId("relay-1"),
        topic=BrokerTopicId("events.topic"),
        now=_utc,
    )
    return service, publisher, store


# ── relay_once ────────────────────────────────────────────────────────────────

def test_relay_once_returns_none_on_empty_journal() -> None:
    service, _, _ = _setup([])
    assert service.relay_once(max_records=10) is None


def test_relay_once_publishes_from_offset_zero() -> None:
    service, publisher, _ = _setup(_records(0, 1, 2))
    result = service.relay_once(max_records=10)
    assert result is not None
    assert result.record_count == 3
    assert result.first_offset == WalOffset(value=0)
    assert result.last_offset == WalOffset(value=2)
    assert result.broker_ack.published is True
    assert len(publisher.published_records) == 3


def test_relay_once_respects_max_records() -> None:
    service, publisher, _ = _setup(_records(0, 1, 2, 3, 4))
    result = service.relay_once(max_records=3)
    assert result is not None
    assert result.record_count == 3
    assert result.last_offset == WalOffset(value=2)
    assert len(publisher.published_records) == 3


def test_relay_once_saves_checkpoint_on_success() -> None:
    service, _, store = _setup(_records(0, 1, 2))
    service.relay_once(max_records=10)
    cp = store.load(SidecarId("relay-1"), RunId("run-1"))
    assert cp is not None
    assert cp.last_published_wal_offset.value == 2
    assert cp.relay_id == SidecarId("relay-1")
    assert cp.run_id == RunId("run-1")


def test_relay_checkpoint_carries_last_event_id() -> None:
    service, _, store = _setup(_records(0, 1, 2))
    service.relay_once(max_records=10)
    cp = store.load(SidecarId("relay-1"), RunId("run-1"))
    assert cp is not None
    assert cp.last_published_event_id == EventId("evt-2")


def test_relay_once_resumes_after_checkpoint() -> None:
    service, publisher, _store = _setup(_records(0, 1, 2, 3, 4))
    # First relay: publishes 0-2
    service.relay_once(max_records=3)
    assert len(publisher.published_records) == 3

    # Second relay: should pick up from offset 3
    result = service.relay_once(max_records=10)
    assert result is not None
    assert result.first_offset == WalOffset(value=3)
    assert result.last_offset == WalOffset(value=4)
    assert result.record_count == 2
    assert len(publisher.published_records) == 5


def test_relay_once_returns_none_when_all_records_published() -> None:
    service, _, _ = _setup(_records(0, 1, 2))
    service.relay_once(max_records=10)
    assert service.relay_once(max_records=10) is None


# ── rejected broker ack ───────────────────────────────────────────────────────

def test_rejected_ack_does_not_save_checkpoint() -> None:
    service, _, store = _setup(_records(0, 1, 2), fail_next=True)
    result = service.relay_once(max_records=10)
    assert result is not None
    assert result.broker_ack.published is False
    assert store.load(SidecarId("relay-1"), RunId("run-1")) is None


def test_rejected_ack_result_published_is_false() -> None:
    service, _, _ = _setup(_records(0), fail_next=True)
    result = service.relay_once(max_records=10)
    assert result is not None
    assert result.broker_ack.published is False
    assert "broker" in (result.broker_ack.reason or "").lower()


def test_rejected_ack_does_not_advance_relay_position() -> None:
    service, publisher, _ = _setup(_records(0, 1, 2), fail_next=True)
    # First call: rejected
    service.relay_once(max_records=10)
    assert len(publisher.published_records) == 0

    # Second call: succeeds and re-publishes from offset 0
    result = service.relay_once(max_records=10)
    assert result is not None
    assert result.record_count == 3
    assert result.first_offset == WalOffset(value=0)


# ── build_batch_after_checkpoint ──────────────────────────────────────────────

def test_build_batch_raises_for_zero_max_records() -> None:
    service, _, _ = _setup(_records(0))
    with pytest.raises(ValueError, match="max_records must be > 0"):
        service.build_batch_after_checkpoint(0)


def test_build_batch_raises_for_negative_max_records() -> None:
    service, _, _ = _setup(_records(0))
    with pytest.raises(ValueError, match="max_records must be > 0"):
        service.build_batch_after_checkpoint(-1)


def test_build_batch_returns_none_for_empty_journal() -> None:
    service, _, _ = _setup([])
    assert service.build_batch_after_checkpoint(10) is None


# ── gap detection after checkpoint ───────────────────────────────────────────


def test_build_batch_contiguous_after_checkpoint_succeeds() -> None:
    # Checkpoint at 1; journal has 2, 3 → expected next offset is 2 → ok.
    service, _, _store = _setup(_records(0, 1, 2, 3))
    service.relay_once(max_records=2)  # publishes 0-1; checkpoint saved at 1
    result = service.relay_once(max_records=10)
    assert result is not None
    assert result.first_offset == WalOffset(value=2)
    assert result.last_offset == WalOffset(value=3)


def test_build_batch_raises_on_gap_after_checkpoint() -> None:
    # Checkpoint at 1; journal only has 3, 4 → gap at offset 2.
    service, _, _store = _setup(_records(0, 1, 3, 4))
    service.relay_once(max_records=2)  # publishes 0-1; checkpoint at 1
    # Next call: pending starts at 3, expected 2 → ValueError.
    with pytest.raises(ValueError, match="expected next offset 2"):
        service.build_batch_after_checkpoint(10)


def test_build_batch_gap_error_includes_found_offset() -> None:
    service, _, _store = _setup(_records(0, 1, 3, 4))
    service.relay_once(max_records=2)
    with pytest.raises(ValueError, match="found 3"):
        service.build_batch_after_checkpoint(10)


def test_build_batch_all_consumed_with_checkpoint_returns_none() -> None:
    # Checkpoint at 5; journal has 0, 1, 2 (all <= 5) → None, no gap error.
    service, _, _store = _setup(_records(0, 1, 2))
    service.relay_once(max_records=10)  # publishes 0-2; checkpoint at 2
    # Now journal still has 0-2 but all are <= checkpoint → None.
    assert service.build_batch_after_checkpoint(10) is None


def test_build_batch_no_checkpoint_does_not_require_offset_zero() -> None:
    # No checkpoint; journal starts at 3, 4 → returns batch as-is.
    service, _, _ = _setup(_records(3, 4))
    result = service.relay_once(max_records=10)
    assert result is not None
    assert result.first_offset == WalOffset(value=3)
    assert result.record_count == 2


def test_relay_once_gap_does_not_publish_or_save_checkpoint() -> None:
    # When build_batch raises due to gap, relay_once propagates the error
    # without calling publish_batch, so no record is published and no
    # checkpoint is updated.
    service, publisher, store = _setup(_records(0, 1, 3, 4))
    service.relay_once(max_records=2)  # publishes 0-1
    with pytest.raises(ValueError, match="expected next offset 2"):
        service.relay_once(max_records=10)
    # Checkpoint must still be at offset 1 (not advanced to 3 or 4).
    cp = store.load(SidecarId("relay-1"), RunId("run-1"))
    assert cp is not None
    assert cp.last_published_wal_offset.value == 1
    # No additional records were published.
    assert len(publisher.published_records) == 2


# ── record key policy ─────────────────────────────────────────────────────────

def test_record_key_uses_bot_id_when_present() -> None:
    rec = _record(0)
    assert rec.event.bot_id is not None
    key = LocalWalRelayService._record_key(rec)
    assert key == "bot-1"


def test_record_key_falls_back_to_run_id_when_no_bot_id() -> None:
    no_bot_event = EventEnvelope(
        event_id=EventId("evt-nb"),
        event_type=EventType.BOT_CREATED,
        occurred_at=_utc(),
        bot_id=None,
        schema_version="1.0",
    )
    rec = JournalRecord(
        run_id=RunId("run-fallback"),
        producer_id=ProducerId("prod-1"),
        wal_offset=WalOffset(value=0),
        event=no_bot_event,
        recorded_at=_utc(),
        payload_hash="abc123",
        record_size_bytes=64,
    )
    key = LocalWalRelayService._record_key(rec)
    assert key == "run-fallback"


# ── service depends on EventJournalPort, not LocalJsonlWal ───────────────────

def test_relay_service_uses_fake_journal_not_local_jsonl_wal() -> None:
    # FakeJournal satisfies EventJournalPort structurally.
    # The service type annotation accepts EventJournalPort — any conforming
    # object works, including a fake that does not touch the filesystem.
    service, _, _ = _setup(_records(0, 1))
    result = service.relay_once(max_records=10)
    assert result is not None
    assert result.record_count == 2


def test_relay_service_does_not_import_local_jsonl_wal() -> None:
    source_path = inspect.getsourcefile(LocalWalRelayService)
    assert source_path is not None
    source = Path(source_path).read_text()
    import_lines = [
        line for line in source.splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    assert not any("local_jsonl" in line for line in import_lines)
    assert not any("LocalJsonlWal" in line for line in import_lines)


def test_relay_service_does_not_reference_decide_wal_gc() -> None:
    source_path = inspect.getsourcefile(LocalWalRelayService)
    assert source_path is not None
    source = Path(source_path).read_text()
    import_lines = [
        line for line in source.splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    non_comment = "\n".join(
        line for line in source.splitlines()
        if not line.strip().startswith("#") and '"""' not in line and "'''" not in line
    )
    assert not any("decide_wal_gc" in line for line in import_lines)
    assert "decide_wal_gc(" not in non_comment
    assert not any("RequiredConsumerCheckpointSet" in line for line in import_lines)


# ── relay does not create DbWriterCheckpoint or GC decisions ─────────────────

def test_relay_does_not_create_db_writer_checkpoint() -> None:
    # The service only writes WalRelayCheckpoint.
    # There is no DbWriterCheckpoint in WalRelayCheckpointStorePort.
    service, _, store = _setup(_records(0, 1, 2))
    service.relay_once(max_records=10)
    cp = store.load(SidecarId("relay-1"), RunId("run-1"))
    assert cp is not None
    # WalRelayCheckpoint has no db_transaction_id, no batch_id.
    assert not hasattr(cp, "db_transaction_id")
    assert not hasattr(cp, "batch_id")


# ── integration: LocalJsonlWal as EventJournalPort ────────────────────────────

def test_relay_with_local_jsonl_wal(tmp_path: Path) -> None:
    """LocalJsonlWal satisfies EventJournalPort; relay_once publishes its records."""
    cfg = LocalJsonlWalConfig(
        root_dir=tmp_path,
        run_id=RunId("run-int"),
        producer_id=ProducerId("prod-int"),
        fsync_on_append=False,
    )

    wal = LocalJsonlWal.open(cfg)
    try:
        for i in range(3):
            wal.append(_event(event_id=f"evt-int-{i}"))

        publisher = InMemoryBrokerPublisher()
        store = InMemoryWalRelayCheckpointStore()
        service = LocalWalRelayService(
            journal=wal,
            publisher=publisher,
            checkpoint_store=store,
            relay_id=SidecarId("relay-int"),
            topic=BrokerTopicId("events.topic"),
            now=_utc,
        )

        result = service.relay_once(max_records=10)

        assert result is not None
        assert result.record_count == 3
        assert result.broker_ack.published is True

        cp = store.load(SidecarId("relay-int"), RunId("run-int"))
        assert cp is not None
        assert cp.last_published_wal_offset.value == 2

        # WAL segments must not be deleted or modified by the relay service.
        for meta in wal.list_segment_metadata():
            assert meta.status is not WalSegmentStatus.DELETED

        # relay_once with nothing new returns None
        assert service.relay_once(max_records=10) is None
    finally:
        wal.close()
