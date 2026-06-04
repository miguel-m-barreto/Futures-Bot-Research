"""Unit tests for LocalJsonlWal.

All file I/O is rooted at pytest's tmp_path; no repository files are touched.
fsync is disabled in test configs to speed up tests on virtual filesystems.
"""

from __future__ import annotations

import importlib
import json as _json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from futures_bot.domain.events import EventEnvelope, EventType, OrderSubmitAttemptedPayload
from futures_bot.domain.execution import OrderSide, OrderType
from futures_bot.domain.ids import (
    BotId,
    EventId,
    ExecutionIntentId,
    InstrumentId,
    OrderIntentId,
    ProducerId,
    RunId,
)
from futures_bot.domain.journal import JournalRecord, WalOffset
from futures_bot.domain.wal import WalAppendStatus, WalSegmentMetadata, WalSegmentStatus
from futures_bot.infrastructure.wal.local_jsonl import (
    LocalJsonlWal,
    LocalJsonlWalConfig,
    LocalWalCorruptionError,
    LocalWalError,
    _compute_payload_hash,
)

# ── Fixtures / helpers ─────────────────────────────────────────────────────────


def _cfg(
    tmp_path: Path,
    run_id: str = "test-run-1",
    **kwargs: object,
) -> LocalJsonlWalConfig:
    return LocalJsonlWalConfig(
        root_dir=tmp_path,
        run_id=RunId(run_id),
        producer_id=ProducerId("test-producer"),
        fsync_on_append=False,
        **kwargs,  # type: ignore[arg-type]
    )


def _event(event_id: str = "evt-1") -> EventEnvelope:
    return EventEnvelope(
        event_id=EventId(event_id),
        event_type=EventType.BOT_CREATED,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        bot_id=BotId("bot-1"),
        schema_version="1.0",
    )


def _order_submit_attempted_event(event_id: str = "evt-order-submit-1") -> EventEnvelope:
    return EventEnvelope(
        event_id=EventId(event_id),
        event_type=EventType.ORDER_SUBMIT_ATTEMPTED,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        bot_id=BotId("bot-1"),
        schema_version="1.0",
        payload=OrderSubmitAttemptedPayload(
            execution_intent_id=ExecutionIntentId("execution-intent-1"),
            order_intent_id=OrderIntentId("order-intent-1"),
            client_order_id="client-order-1",
            instrument_id=InstrumentId("BTC-USDT-PERP"),
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity="0.25",
            reduce_only=False,
            attempted_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )


# ── Config validation ──────────────────────────────────────────────────────────


def test_config_rejects_non_positive_segment_max_bytes(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="segment_max_bytes"):
        _cfg(tmp_path, segment_max_bytes=0)

    with pytest.raises(ValidationError, match="segment_max_bytes"):
        _cfg(tmp_path, segment_max_bytes=-1)


def test_config_rejects_non_positive_segment_max_events(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="segment_max_events"):
        _cfg(tmp_path, segment_max_events=0)


def test_config_rejects_non_positive_segment_max_age_seconds(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="segment_max_age_seconds"):
        _cfg(tmp_path, segment_max_age_seconds=0)


# ── Directory creation ─────────────────────────────────────────────────────────


def test_open_creates_wal_directories(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path))
    wal.close()

    assert (tmp_path / "segments").is_dir()
    assert (tmp_path / "metadata").is_dir()


# ── Append basics ──────────────────────────────────────────────────────────────


def test_first_append_returns_appended_at_offset_zero(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path))
    result = wal.append(_event("evt-1"))
    wal.close()

    assert result.appended is True
    assert result.record is not None
    assert result.record.wal_offset.value == 0


def test_second_append_returns_offset_one(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path))
    wal.append(_event("evt-1"))
    r2 = wal.append(_event("evt-2"))
    wal.close()

    assert r2.record is not None
    assert r2.record.wal_offset.value == 1


def test_payload_hash_is_deterministic_for_same_event(tmp_path: Path) -> None:
    event = _event("evt-1")
    wal = LocalJsonlWal.open(_cfg(tmp_path))
    r1 = wal.append(event)
    wal.close()

    wal2 = LocalJsonlWal.open(_cfg(tmp_path / "run2"))
    r2 = wal2.append(event)
    wal2.close()

    assert r1.record is not None
    assert r2.record is not None
    assert r1.record.payload_hash == r2.record.payload_hash


def test_order_submit_attempted_event_round_trips_through_local_jsonl_wal(
    tmp_path: Path,
) -> None:
    event = _order_submit_attempted_event()
    wal = LocalJsonlWal.open(_cfg(tmp_path))
    append_result = wal.append(event)

    records = list(wal.iter_records())
    wal.close()

    assert append_result.appended is True
    assert append_result.record is not None
    assert len(records) == 1
    record = records[0]
    assert record.payload_hash == append_result.record.payload_hash
    assert record.event.event_type is EventType.ORDER_SUBMIT_ATTEMPTED
    assert record.event.payload["quantity"] == "0.25"
    assert record.event.payload["attempted_at"] == "2026-01-01T00:00:00Z"
    assert record.event.payload["order_type"] == "MARKET"


def test_record_size_bytes_is_positive(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path))
    result = wal.append(_event())
    wal.close()

    assert result.record is not None
    assert result.record.record_size_bytes > 0


def test_append_after_close_returns_rejected_unavailable(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path))
    wal.close()

    result = wal.append(_event())

    assert result.appended is False
    assert result.status is WalAppendStatus.REJECTED_WAL_UNAVAILABLE


# ── Metadata accuracy ──────────────────────────────────────────────────────────


def test_current_metadata_event_count_tracks_appended_records(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path))
    for i in range(4):
        wal.append(_event(f"evt-{i}"))

    meta = wal.current_segment_metadata()
    wal.close()

    assert meta.event_count == 4


def test_current_metadata_offset_range_matches_appended_offsets(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path))
    for i in range(3):
        wal.append(_event(f"evt-{i}"))

    meta = wal.current_segment_metadata()
    wal.close()

    assert meta.offset_range is not None
    assert meta.offset_range.first.value == 0
    assert meta.offset_range.last.value == 2


# ── File format ────────────────────────────────────────────────────────────────


def test_jsonl_file_has_one_line_per_record(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path))
    for i in range(5):
        wal.append(_event(f"evt-{i}"))

    seg_id = wal.current_segment_metadata().segment_id
    wal.close()

    jsonl_path = tmp_path / "segments" / f"{seg_id}.jsonl"
    lines = [ln for ln in jsonl_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 5


def test_jsonl_lines_can_be_parsed_back_into_journal_record(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path))
    wal.append(_event("evt-1"))
    seg_id = wal.current_segment_metadata().segment_id
    wal.close()

    jsonl_path = tmp_path / "segments" / f"{seg_id}.jsonl"
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = JournalRecord.model_validate_json(line)
            assert record.wal_offset.value == 0


def test_iter_records_returns_records_in_offset_order(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path))
    for i in range(6):
        wal.append(_event(f"evt-{i}"))

    records = list(wal.iter_records())
    wal.close()

    offsets = [r.wal_offset.value for r in records]
    assert offsets == list(range(6))


# ── Rollover ───────────────────────────────────────────────────────────────────


def test_rollover_at_max_events_creates_sealed_and_open_segments(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path, segment_max_events=2))

    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    # After the 2nd append, event_count == max_events → rollover triggered.
    r3 = wal.append(_event("evt-3"))
    wal.close()

    meta_list = wal.list_segment_metadata()
    sealed = [m for m in meta_list if m.status is WalSegmentStatus.SEALED]
    open_ = [m for m in meta_list if m.status is WalSegmentStatus.OPEN]

    assert len(sealed) == 1
    assert len(open_) == 1
    assert r3.record is not None
    assert r3.record.wal_offset.value == 2


def test_offsets_do_not_reset_after_rollover(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path, segment_max_events=2))
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    r3 = wal.append(_event("evt-3"))
    wal.close()

    assert r3.record is not None
    assert r3.record.wal_offset.value == 2


def test_sealed_segment_after_rollover_has_sealed_status(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path, segment_max_events=2))
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    wal.append(_event("evt-3"))
    wal.close()

    meta_list = wal.list_segment_metadata()
    sealed = [m for m in meta_list if m.status is WalSegmentStatus.SEALED]
    assert len(sealed) >= 1
    assert all(m.sealed_at is not None for m in sealed)


def test_segment_file_is_not_deleted_after_rollover(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path, segment_max_events=2))
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))

    meta_before_rollover = wal.list_segment_metadata()
    first_seg_id = meta_before_rollover[0].segment_id

    wal.append(_event("evt-3"))
    wal.close()

    assert (tmp_path / "segments" / f"{first_seg_id}.jsonl").exists()


# ── Manual seal ────────────────────────────────────────────────────────────────


def test_manual_seal_marks_segment_sealed(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path))
    wal.append(_event("evt-1"))
    sealed_meta = wal.seal_current_segment()

    assert sealed_meta.status is WalSegmentStatus.SEALED
    assert sealed_meta.sealed_at is not None


def test_append_after_manual_seal_uses_new_open_segment(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path))
    wal.append(_event("evt-1"))
    wal.seal_current_segment()
    r2 = wal.append(_event("evt-2"))
    wal.close()

    assert r2.appended is True
    assert wal.current_segment_metadata().status is WalSegmentStatus.OPEN
    meta_list = wal.list_segment_metadata()
    assert sum(1 for m in meta_list if m.status is WalSegmentStatus.SEALED) == 1


def test_sealed_segment_can_still_be_read(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path))
    wal.append(_event("evt-1"))
    sealed_meta = wal.seal_current_segment()

    records = wal.read_segment(sealed_meta.segment_id)
    wal.close()

    assert len(records) == 1
    assert records[0].wal_offset.value == 0


# ── Recovery ───────────────────────────────────────────────────────────────────


def test_recovery_continues_at_next_offset(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)

    wal1 = LocalJsonlWal.open(cfg)
    wal1.append(_event("evt-1"))
    wal1.append(_event("evt-2"))
    wal1.close()

    wal2 = LocalJsonlWal.open(cfg)
    r = wal2.append(_event("evt-3"))
    wal2.close()

    assert r.record is not None
    assert r.record.wal_offset.value == 2


def test_recovery_iter_records_sees_old_and_new_records(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)

    wal1 = LocalJsonlWal.open(cfg)
    wal1.append(_event("evt-1"))
    wal1.append(_event("evt-2"))
    wal1.close()

    wal2 = LocalJsonlWal.open(cfg)
    wal2.append(_event("evt-3"))

    records = list(wal2.iter_records())
    wal2.close()

    assert len(records) == 3
    assert [r.wal_offset.value for r in records] == [0, 1, 2]


def test_recovery_across_rollover_continues_at_correct_offset(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, segment_max_events=2)

    wal1 = LocalJsonlWal.open(cfg)
    wal1.append(_event("evt-1"))
    wal1.append(_event("evt-2"))
    # rollover triggered: now on segment 2, offset 2 is next
    wal1.close()

    wal2 = LocalJsonlWal.open(cfg)
    r = wal2.append(_event("evt-3"))
    wal2.close()

    assert r.record is not None
    assert r.record.wal_offset.value == 2


# ── Corruption ─────────────────────────────────────────────────────────────────


def test_corrupted_sealed_segment_raises_on_iter_records(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, segment_max_events=2)

    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    # rollover: segment-000001 is sealed, segment-000002 is open
    wal.append(_event("evt-3"))
    sealed_meta = wal.list_segment_metadata()[0]
    wal.close()

    wal2 = LocalJsonlWal.open(cfg)

    # Corrupt the sealed segment AFTER open — verifies lazy read-time detection still fires.
    sealed_path = tmp_path / "segments" / f"{sealed_meta.segment_id}.jsonl"
    sealed_path.write_text(
        sealed_path.read_text(encoding="utf-8") + "not-valid-json\n",
        encoding="utf-8",
    )

    with pytest.raises(LocalWalCorruptionError):
        list(wal2.iter_records())
    wal2.close()


def test_open_segment_stale_event_count_in_metadata_is_corrected_on_open(
    tmp_path: Path,
) -> None:
    # Simulates the crash window: metadata says event_count=99 but the JSONL
    # has only 1 record.  JSONL is ground truth for OPEN segments; recovery
    # must succeed and correct the on-disk metadata rather than raising.
    cfg = _cfg(tmp_path)

    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    seg_id = wal.current_segment_metadata().segment_id
    wal.close()

    meta_path = tmp_path / "metadata" / f"{seg_id}.json"
    data = _json.loads(meta_path.read_text(encoding="utf-8"))
    data["event_count"] = 99
    data["offset_range"] = None
    meta_path.write_text(_json.dumps(data), encoding="utf-8")

    wal2 = LocalJsonlWal.open(cfg)
    meta = wal2.current_segment_metadata()
    assert meta.event_count == 1
    wal2.close()


# ── Safety ─────────────────────────────────────────────────────────────────────


def test_no_kafka_or_db_imports_in_implementation() -> None:
    mod = importlib.import_module(
        "futures_bot.infrastructure.wal.local_jsonl"
    )
    source_file = mod.__file__ or ""
    source = Path(source_file).read_text(encoding="utf-8")

    for forbidden in ("kafka", "confluent", "postgres", "psycopg", "sqlalchemy", "duckdb"):
        assert forbidden not in source.lower(), f"forbidden import found: {forbidden}"


# ── Strict corruption validation ──────────────────────────────────────────────


def test_non_contiguous_offsets_in_sealed_raises_on_iter_records(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, segment_max_events=2)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    wal.append(_event("evt-3"))
    sealed_meta = next(
        m for m in wal.list_segment_metadata() if m.status is WalSegmentStatus.SEALED
    )
    wal.close()

    # Tamper: replace second record's offset with a non-contiguous value.
    sealed_path = tmp_path / "segments" / f"{sealed_meta.segment_id}.jsonl"
    lines = sealed_path.read_text(encoding="utf-8").splitlines()
    data = _json.loads(lines[1])
    data["wal_offset"]["value"] = 5  # expected 1
    lines[1] = _json.dumps(data)
    sealed_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)


def test_non_contiguous_offsets_in_open_segment_raises_on_open(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    seg_id = wal.current_segment_metadata().segment_id
    wal.close()

    jsonl_path = tmp_path / "segments" / f"{seg_id}.jsonl"
    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    data = _json.loads(lines[1])
    data["wal_offset"]["value"] = 5  # expected 1
    lines[1] = _json.dumps(data)
    jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)


def test_blank_line_in_sealed_raises_on_iter_records(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, segment_max_events=2)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    wal.append(_event("evt-3"))
    sealed_meta = next(
        m for m in wal.list_segment_metadata() if m.status is WalSegmentStatus.SEALED
    )
    wal.close()

    # Append a blank line to the sealed JSONL file.
    sealed_path = tmp_path / "segments" / f"{sealed_meta.segment_id}.jsonl"
    sealed_path.write_text(sealed_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)


def test_sealed_metadata_event_count_mismatch_raises_on_open(tmp_path: Path) -> None:
    # event_count that doesn't match offset_range.count is caught by Pydantic's
    # WalSegmentMetadata model_validator during metadata loading.
    cfg = _cfg(tmp_path, segment_max_events=2)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    wal.append(_event("evt-3"))
    sealed_meta = next(
        m for m in wal.list_segment_metadata() if m.status is WalSegmentStatus.SEALED
    )
    wal.close()

    meta_path = tmp_path / "metadata" / f"{sealed_meta.segment_id}.json"
    data = _json.loads(meta_path.read_text(encoding="utf-8"))
    data["event_count"] = 99  # offset_range.count == 2, so 99 != 2 → invalid
    meta_path.write_text(_json.dumps(data), encoding="utf-8")

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)


def test_open_segment_stale_payload_bytes_in_metadata_is_corrected_on_open(
    tmp_path: Path,
) -> None:
    # Same crash-window scenario: metadata payload_bytes is wrong but JSONL is
    # intact.  Recovery derives byte count from JSONL and corrects metadata.
    cfg = _cfg(tmp_path)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    seg_id = wal.current_segment_metadata().segment_id
    actual_bytes = wal.current_segment_metadata().payload_bytes
    wal.close()

    meta_path = tmp_path / "metadata" / f"{seg_id}.json"
    data = _json.loads(meta_path.read_text(encoding="utf-8"))
    data["payload_bytes"] = data["payload_bytes"] + 9999
    meta_path.write_text(_json.dumps(data), encoding="utf-8")

    wal2 = LocalJsonlWal.open(cfg)
    assert wal2.current_segment_metadata().payload_bytes == actual_bytes
    wal2.close()


def test_run_id_mismatch_raises_on_iter_records(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, segment_max_events=2)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    wal.append(_event("evt-3"))
    sealed_meta = next(
        m for m in wal.list_segment_metadata() if m.status is WalSegmentStatus.SEALED
    )
    wal.close()

    # Replace run_id in the first sealed record with a wrong value.
    sealed_path = tmp_path / "segments" / f"{sealed_meta.segment_id}.jsonl"
    lines = sealed_path.read_text(encoding="utf-8").splitlines()
    data = _json.loads(lines[0])
    data["run_id"] = {"value": "wrong-run-id"}
    lines[0] = _json.dumps(data)
    sealed_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)


def test_producer_id_mismatch_raises_on_iter_records(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, segment_max_events=2)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    wal.append(_event("evt-3"))
    sealed_meta = next(
        m for m in wal.list_segment_metadata() if m.status is WalSegmentStatus.SEALED
    )
    wal.close()

    sealed_path = tmp_path / "segments" / f"{sealed_meta.segment_id}.jsonl"
    lines = sealed_path.read_text(encoding="utf-8").splitlines()
    data = _json.loads(lines[0])
    data["producer_id"] = {"value": "wrong-producer"}
    lines[0] = _json.dumps(data)
    sealed_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)


def test_corrupted_sealed_jsonl_raises_on_open(tmp_path: Path) -> None:
    # Corrupt a sealed segment JSONL before reopening; open() must raise immediately.
    cfg = _cfg(tmp_path, segment_max_events=2)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    wal.append(_event("evt-3"))
    sealed_meta = next(
        m for m in wal.list_segment_metadata() if m.status is WalSegmentStatus.SEALED
    )
    wal.close()

    sealed_path = tmp_path / "segments" / f"{sealed_meta.segment_id}.jsonl"
    sealed_path.write_text(
        sealed_path.read_text(encoding="utf-8") + "not-valid-json\n",
        encoding="utf-8",
    )

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)


def test_sealed_metadata_file_record_count_mismatch_raises_on_open(tmp_path: Path) -> None:
    # Metadata is internally consistent (Pydantic validates it fine) but disagrees
    # with the actual file: metadata says event_count=1 / offset_range=0..0, file
    # has 2 records. open() reads the file and detects the mismatch.
    cfg = _cfg(tmp_path, segment_max_events=2)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    wal.append(_event("evt-3"))
    sealed_meta = next(
        m for m in wal.list_segment_metadata() if m.status is WalSegmentStatus.SEALED
    )
    wal.close()

    meta_path = tmp_path / "metadata" / f"{sealed_meta.segment_id}.json"
    data = _json.loads(meta_path.read_text(encoding="utf-8"))
    # event_count=1, offset_range=0..0 → count=1 == event_count=1 (valid Pydantic)
    # but file still has 2 records at offsets [0, 1].
    data["event_count"] = 1
    data["offset_range"] = {"first": {"value": 0}, "last": {"value": 0}}
    meta_path.write_text(_json.dumps(data), encoding="utf-8")

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)


def test_empty_open_segment_is_valid_on_open(tmp_path: Path) -> None:
    # An OPEN segment with no records (event_count=0, offset_range=None) must
    # survive close + reopen without triggering a corruption error.
    cfg = _cfg(tmp_path)
    wal = LocalJsonlWal.open(cfg)
    wal.close()

    wal2 = LocalJsonlWal.open(cfg)
    meta = wal2.current_segment_metadata()
    wal2.close()

    assert meta.event_count == 0
    assert meta.offset_range is None


# ── Global offset continuity ───────────────────────────────────────────────────


def _tamper_open_segment_offset(
    tmp_path: Path,
    open_seg_id: object,
    new_offset: int,
) -> None:
    """Helper: replace the first record's wal_offset and update metadata to match."""
    seg_str = str(open_seg_id)
    jsonl_path = tmp_path / "segments" / f"{seg_str}.jsonl"
    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    data = _json.loads(lines[0])
    data["wal_offset"]["value"] = new_offset
    lines[0] = _json.dumps(data)
    new_content = "\n".join(lines) + "\n"
    jsonl_path.write_text(new_content, encoding="utf-8")

    meta_path = tmp_path / "metadata" / f"{seg_str}.json"
    meta_data = _json.loads(meta_path.read_text(encoding="utf-8"))
    meta_data["offset_range"] = {"first": {"value": new_offset}, "last": {"value": new_offset}}
    meta_data["payload_bytes"] = len(new_content.encode("utf-8"))
    meta_path.write_text(_json.dumps(meta_data), encoding="utf-8")


def test_open_rejects_cross_segment_gap(tmp_path: Path) -> None:
    # sealed [0,1] then OPEN starts at 5 — gap of 3 offsets.
    cfg = _cfg(tmp_path, segment_max_events=2)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    wal.append(_event("evt-3"))  # → sealed [0,1], open [2]
    open_seg_id = wal.current_segment_metadata().segment_id
    wal.close()

    _tamper_open_segment_offset(tmp_path, open_seg_id, new_offset=5)

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)


def test_open_rejects_cross_segment_overlap(tmp_path: Path) -> None:
    # sealed [0,1] then OPEN starts at 1 — overlap.
    cfg = _cfg(tmp_path, segment_max_events=2)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    wal.append(_event("evt-3"))  # → sealed [0,1], open [2]
    open_seg_id = wal.current_segment_metadata().segment_id
    wal.close()

    _tamper_open_segment_offset(tmp_path, open_seg_id, new_offset=1)

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)


def test_open_rejects_first_segment_not_starting_at_zero(tmp_path: Path) -> None:
    # Only OPEN segment but it starts at offset 5 instead of 0.
    cfg = _cfg(tmp_path)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))  # → OPEN [0]
    open_seg_id = wal.current_segment_metadata().segment_id
    wal.close()

    _tamper_open_segment_offset(tmp_path, open_seg_id, new_offset=5)

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)


def test_iter_records_rejects_cross_segment_gap_after_open(tmp_path: Path) -> None:
    # A cross-segment gap introduced AFTER open is caught lazily by iter_records().
    cfg = _cfg(tmp_path, segment_max_events=2)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    wal.append(_event("evt-3"))  # → sealed [0,1], open [2]
    wal.close()

    wal2 = LocalJsonlWal.open(cfg)
    open_seg_id = wal2.current_segment_metadata().segment_id

    # Inject gap AFTER open — corrupts the active file without updating in-memory metadata.
    jsonl_path = tmp_path / "segments" / f"{open_seg_id}.jsonl"
    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    data = _json.loads(lines[0])
    data["wal_offset"]["value"] = 5  # creates gap: sealed ends at 1, open starts at 5
    lines[0] = _json.dumps(data)
    jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(LocalWalCorruptionError):
        list(wal2.iter_records())
    wal2.close()


def test_invalid_utf8_in_sealed_raises_on_open(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, segment_max_events=2)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    wal.append(_event("evt-3"))
    sealed_meta = next(
        m for m in wal.list_segment_metadata() if m.status is WalSegmentStatus.SEALED
    )
    wal.close()

    sealed_path = tmp_path / "segments" / f"{sealed_meta.segment_id}.jsonl"
    sealed_path.write_bytes(b"\xff\xfe")

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)


def test_invalid_utf8_after_open_raises_on_iter_records(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, segment_max_events=2)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    wal.append(_event("evt-3"))
    sealed_meta = next(
        m for m in wal.list_segment_metadata() if m.status is WalSegmentStatus.SEALED
    )
    wal.close()

    wal2 = LocalJsonlWal.open(cfg)

    # Inject invalid UTF-8 AFTER open to test lazy detection at iter_records time.
    sealed_path = tmp_path / "segments" / f"{sealed_meta.segment_id}.jsonl"
    sealed_path.write_bytes(b"\xff\xfe")

    with pytest.raises(LocalWalCorruptionError):
        list(wal2.iter_records())
    wal2.close()


def test_normal_multi_segment_wal_offset_continuity_passes(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, segment_max_events=2)
    wal = LocalJsonlWal.open(cfg)
    for i in range(7):
        wal.append(_event(f"evt-{i}"))
    wal.close()

    wal2 = LocalJsonlWal.open(cfg)
    records = list(wal2.iter_records())
    wal2.close()

    assert [r.wal_offset.value for r in records] == list(range(7))


# ── Segment index continuity ───────────────────────────────────────────────────


def _rename_segment(tmp_path: Path, old_seg_id: str, new_seg_id: str) -> None:
    """Rename a segment's JSONL file and update its metadata's segment_id field."""
    (tmp_path / "segments" / f"{old_seg_id}.jsonl").rename(
        tmp_path / "segments" / f"{new_seg_id}.jsonl"
    )
    old_meta_path = tmp_path / "metadata" / f"{old_seg_id}.json"
    data = _json.loads(old_meta_path.read_text(encoding="utf-8"))
    data["segment_id"] = {"value": new_seg_id}
    (tmp_path / "metadata" / f"{new_seg_id}.json").write_text(
        _json.dumps(data), encoding="utf-8"
    )
    old_meta_path.unlink()


def test_open_rejects_missing_segment_index(tmp_path: Path) -> None:
    # Indices [1, 3] — gap at 2.
    cfg = _cfg(tmp_path, segment_max_events=2)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    # → segment-000001 sealed [0,1], segment-000002 OPEN (empty)
    wal.close()

    _rename_segment(
        tmp_path,
        "test-run-1-segment-000002",
        "test-run-1-segment-000003",
    )

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)


def test_open_rejects_segment_indices_not_starting_at_one(tmp_path: Path) -> None:
    # Only index [2] — does not start at 1.
    cfg = _cfg(tmp_path)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.close()

    _rename_segment(
        tmp_path,
        "test-run-1-segment-000001",
        "test-run-1-segment-000002",
    )

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)


def test_corrupt_sealed_no_open_does_not_create_new_metadata(tmp_path: Path) -> None:
    # Global offset continuity fails (sealed starts at 5, not 0) with no OPEN segment;
    # open() must raise without creating any new metadata or segment file.
    cfg = _cfg(tmp_path, segment_max_events=2)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    # → segment-000001 sealed [0,1], segment-000002 OPEN (empty)
    wal.close()

    open_seg = "test-run-1-segment-000002"
    (tmp_path / "metadata" / f"{open_seg}.json").unlink()
    (tmp_path / "segments" / f"{open_seg}.jsonl").unlink()

    # Tamper sealed offsets [0,1] → [5,6] and update metadata to match so that
    # per-segment content validation passes but global continuity fails.
    sealed_jsonl = tmp_path / "segments" / "test-run-1-segment-000001.jsonl"
    lines = sealed_jsonl.read_text(encoding="utf-8").splitlines()
    for i, offset_val in enumerate([5, 6]):
        row = _json.loads(lines[i])
        row["wal_offset"]["value"] = offset_val
        lines[i] = _json.dumps(row)
    new_content = "\n".join(lines) + "\n"
    sealed_jsonl.write_text(new_content, encoding="utf-8")

    sealed_meta = tmp_path / "metadata" / "test-run-1-segment-000001.json"
    meta_data = _json.loads(sealed_meta.read_text(encoding="utf-8"))
    meta_data["offset_range"] = {"first": {"value": 5}, "last": {"value": 6}}
    meta_data["payload_bytes"] = len(new_content.encode("utf-8"))
    sealed_meta.write_text(_json.dumps(meta_data), encoding="utf-8")

    metadata_before = set((tmp_path / "metadata").iterdir())
    segments_before = set((tmp_path / "segments").iterdir())

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)

    assert set((tmp_path / "metadata").iterdir()) == metadata_before
    assert set((tmp_path / "segments").iterdir()) == segments_before


def test_valid_sealed_only_wal_creates_next_open_segment(tmp_path: Path) -> None:
    # After losing the empty OPEN segment, open() must create segment-000002 (max+1).
    cfg = _cfg(tmp_path, segment_max_events=2)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    # → segment-000001 sealed [0,1], segment-000002 OPEN (empty)
    wal.close()

    open_seg = "test-run-1-segment-000002"
    (tmp_path / "metadata" / f"{open_seg}.json").unlink()
    (tmp_path / "segments" / f"{open_seg}.jsonl").unlink()

    wal2 = LocalJsonlWal.open(cfg)
    meta = wal2.current_segment_metadata()
    wal2.close()

    assert str(meta.segment_id) == "test-run-1-segment-000002"
    assert meta.status is WalSegmentStatus.OPEN
    assert meta.event_count == 0
    assert (tmp_path / "metadata" / "test-run-1-segment-000002.json").exists()


def test_segment_index_continuity_passes_for_valid_wal(tmp_path: Path) -> None:
    # Indices [1, 2, 3] — contiguous, no gap, starts at 1.
    cfg = _cfg(tmp_path, segment_max_events=2)
    wal = LocalJsonlWal.open(cfg)
    for i in range(5):
        wal.append(_event(f"evt-{i}"))
    # → segments 000001 [0,1], 000002 [2,3], 000003 [4] (open)
    wal.close()

    wal2 = LocalJsonlWal.open(cfg)
    records = list(wal2.iter_records())
    wal2.close()

    assert [r.wal_offset.value for r in records] == list(range(5))


# ── Orphan file detection ──────────────────────────────────────────────────────


def test_open_rejects_orphan_segment_file_without_metadata(tmp_path: Path) -> None:
    # segment-000002.jsonl present; metadata/segment-000002.json deleted → orphan.
    cfg = _cfg(tmp_path, segment_max_events=2)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    # → segment-000001 sealed, segment-000002 OPEN
    wal.close()

    (tmp_path / "metadata" / "test-run-1-segment-000002.json").unlink()

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)


def test_orphan_segment_file_open_does_not_create_new_metadata(tmp_path: Path) -> None:
    # open() must raise early and not write any new metadata or segment file.
    cfg = _cfg(tmp_path, segment_max_events=2)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    wal.close()

    (tmp_path / "metadata" / "test-run-1-segment-000002.json").unlink()

    metadata_before = set((tmp_path / "metadata").iterdir())
    segments_before = set((tmp_path / "segments").iterdir())

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)

    assert set((tmp_path / "metadata").iterdir()) == metadata_before
    assert set((tmp_path / "segments").iterdir()) == segments_before


def test_open_rejects_orphan_metadata_without_segment_file(tmp_path: Path) -> None:
    # metadata/segment-000002.json present; segment-000002.jsonl deleted → orphan.
    cfg = _cfg(tmp_path, segment_max_events=2)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    wal.close()

    (tmp_path / "segments" / "test-run-1-segment-000002.jsonl").unlink()

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)


def test_orphan_check_ignores_other_run_id_files(tmp_path: Path) -> None:
    # An orphan JSONL from a different run_id must not block open() for this run.
    cfg = _cfg(tmp_path)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.close()

    # Orphan JSONL whose prefix does not match "test-run-1-segment-"
    (tmp_path / "segments" / "other-run-segment-000999.jsonl").write_text(
        "", encoding="utf-8"
    )

    wal2 = LocalJsonlWal.open(cfg)
    records = list(wal2.iter_records())
    wal2.close()

    assert len(records) == 1


def test_brand_new_wal_passes_orphan_check_and_creates_segment_001(
    tmp_path: Path,
) -> None:
    # Empty directory → no orphans → segment-000001 created normally.
    cfg = _cfg(tmp_path)
    wal = LocalJsonlWal.open(cfg)
    meta = wal.current_segment_metadata()
    wal.close()

    assert str(meta.segment_id) == "test-run-1-segment-000001"
    assert (tmp_path / "metadata" / "test-run-1-segment-000001.json").exists()
    assert (tmp_path / "segments" / "test-run-1-segment-000001.jsonl").exists()


def test_valid_sealed_only_wal_passes_orphan_check(tmp_path: Path) -> None:
    # Sealed-only WAL (no OPEN) → both files present for 000001 → orphan check
    # passes → creates segment-000002 as the new OPEN.
    cfg = _cfg(tmp_path, segment_max_events=2)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    wal.close()

    # Remove the empty OPEN segment (both files) to leave sealed-only state.
    (tmp_path / "metadata" / "test-run-1-segment-000002.json").unlink()
    (tmp_path / "segments" / "test-run-1-segment-000002.jsonl").unlink()

    wal2 = LocalJsonlWal.open(cfg)
    meta = wal2.current_segment_metadata()
    wal2.close()

    assert str(meta.segment_id) == "test-run-1-segment-000002"
    assert meta.status is WalSegmentStatus.OPEN


# ── Run isolation and metadata identity ───────────────────────────────────────


def test_other_run_corrupt_metadata_json_is_ignored(tmp_path: Path) -> None:
    # Invalid JSON for a different run must be skipped entirely — not raise for our run.
    (tmp_path / "metadata").mkdir(parents=True)
    (tmp_path / "segments").mkdir(parents=True)
    (tmp_path / "metadata" / "other-run-segment-000001.json").write_text(
        "not-valid-json", encoding="utf-8"
    )

    wal = LocalJsonlWal.open(_cfg(tmp_path))
    wal.close()


def test_other_run_orphan_metadata_is_ignored(tmp_path: Path) -> None:
    # Metadata for a different run with no JSONL must not block our run.
    (tmp_path / "metadata").mkdir(parents=True)
    (tmp_path / "segments").mkdir(parents=True)
    (tmp_path / "metadata" / "other-run-segment-000001.json").write_text(
        "any-content", encoding="utf-8"
    )

    wal = LocalJsonlWal.open(_cfg(tmp_path))
    wal.close()


def test_other_run_orphan_jsonl_is_ignored(tmp_path: Path) -> None:
    # JSONL for a different run with no metadata must not block our run.
    (tmp_path / "metadata").mkdir(parents=True)
    (tmp_path / "segments").mkdir(parents=True)
    (tmp_path / "segments" / "other-run-segment-000001.jsonl").write_text(
        "", encoding="utf-8"
    )

    wal = LocalJsonlWal.open(_cfg(tmp_path))
    wal.close()


def test_current_run_invalid_metadata_json_raises(tmp_path: Path) -> None:
    # Malformed JSON in a current-run metadata file must raise LocalWalCorruptionError.
    (tmp_path / "metadata").mkdir(parents=True)
    (tmp_path / "segments").mkdir(parents=True)
    (tmp_path / "metadata" / "test-run-1-segment-000001.json").write_text(
        "not-valid-json", encoding="utf-8"
    )

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(_cfg(tmp_path))


def test_current_run_metadata_run_id_mismatch_raises(tmp_path: Path) -> None:
    # Filename says run-A; JSON says run_id = run-B.
    cfg = _cfg(tmp_path)
    wal = LocalJsonlWal.open(cfg)
    wal.close()

    meta_path = tmp_path / "metadata" / "test-run-1-segment-000001.json"
    data = _json.loads(meta_path.read_text(encoding="utf-8"))
    data["run_id"] = {"value": "other-run"}
    meta_path.write_text(_json.dumps(data), encoding="utf-8")

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)


def test_current_run_metadata_segment_id_mismatch_raises(tmp_path: Path) -> None:
    # Filename says segment-000001; JSON says segment_id = segment-000002.
    cfg = _cfg(tmp_path)
    wal = LocalJsonlWal.open(cfg)
    wal.close()

    meta_path = tmp_path / "metadata" / "test-run-1-segment-000001.json"
    data = _json.loads(meta_path.read_text(encoding="utf-8"))
    data["segment_id"] = {"value": "test-run-1-segment-000002"}
    meta_path.write_text(_json.dumps(data), encoding="utf-8")

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)


def test_invalid_current_run_metadata_open_does_not_mutate_directory(
    tmp_path: Path,
) -> None:
    # Failed open due to invalid metadata JSON must not create any file.
    (tmp_path / "metadata").mkdir(parents=True)
    (tmp_path / "segments").mkdir(parents=True)
    (tmp_path / "metadata" / "test-run-1-segment-000001.json").write_text(
        "not-valid-json", encoding="utf-8"
    )

    metadata_before = set((tmp_path / "metadata").iterdir())
    segments_before = set((tmp_path / "segments").iterdir())

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(_cfg(tmp_path))

    assert set((tmp_path / "metadata").iterdir()) == metadata_before
    assert set((tmp_path / "segments").iterdir()) == segments_before


def test_segment_id_mismatch_open_does_not_mutate_directory(tmp_path: Path) -> None:
    # Failed open due to metadata filename/segment_id mismatch must not create files.
    cfg = _cfg(tmp_path)
    wal = LocalJsonlWal.open(cfg)
    wal.close()

    meta_path = tmp_path / "metadata" / "test-run-1-segment-000001.json"
    data = _json.loads(meta_path.read_text(encoding="utf-8"))
    data["segment_id"] = {"value": "test-run-1-segment-000002"}
    meta_path.write_text(_json.dumps(data), encoding="utf-8")

    metadata_before = set((tmp_path / "metadata").iterdir())
    segments_before = set((tmp_path / "segments").iterdir())

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)

    assert set((tmp_path / "metadata").iterdir()) == metadata_before
    assert set((tmp_path / "segments").iterdir()) == segments_before


def test_no_segment_files_are_deleted_on_rollover(tmp_path: Path) -> None:
    # max_events=2: appends 1-2 → seal segment-1; appends 3-4 → seal segment-2;
    # append 5 stays in segment-3 (open). Three files created, none deleted.
    cfg = _cfg(tmp_path, segment_max_events=2)

    wal = LocalJsonlWal.open(cfg)
    for i in range(5):
        wal.append(_event(f"evt-{i}"))

    meta_list = wal.list_segment_metadata()
    wal.close()

    # Every segment referenced in metadata must still have its file on disk.
    for meta in meta_list:
        seg_path = tmp_path / "segments" / f"{meta.segment_id}.jsonl"
        assert seg_path.exists(), f"segment file was deleted: {seg_path}"

    # At least 2 sealed + 1 open demonstrates multiple rollovers occurred.
    assert len(meta_list) >= 3


# ── Payload hash verification ─────────────────────────────────────────────────


def _tamper_payload_hash_in_segment(
    jsonl_path: Path,
    meta_path: Path,
    line_index: int = 0,
) -> None:
    """Replace payload_hash with an all-zeros hex string; update metadata bytes."""
    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    data = _json.loads(lines[line_index])
    data["payload_hash"] = "0" * 64  # wrong but valid-length SHA-256 hex
    lines[line_index] = _json.dumps(data)
    new_content = "\n".join(lines) + "\n"
    jsonl_path.write_text(new_content, encoding="utf-8")
    # Update metadata payload_bytes so that check does not fire before the hash check.
    meta_data = _json.loads(meta_path.read_text(encoding="utf-8"))
    meta_data["payload_bytes"] = len(new_content.encode("utf-8"))
    meta_path.write_text(_json.dumps(meta_data), encoding="utf-8")


def test_payload_hash_mismatch_in_sealed_raises_on_open(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, segment_max_events=2)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    wal.append(_event("evt-3"))  # rollover: segment-1 sealed, segment-2 open
    sealed_meta = next(
        m for m in wal.list_segment_metadata() if m.status is WalSegmentStatus.SEALED
    )
    wal.close()

    sealed_path = tmp_path / "segments" / f"{sealed_meta.segment_id}.jsonl"
    meta_path = tmp_path / "metadata" / f"{sealed_meta.segment_id}.json"
    _tamper_payload_hash_in_segment(sealed_path, meta_path)

    with pytest.raises(LocalWalCorruptionError, match="payload_hash"):
        LocalJsonlWal.open(cfg)


def test_payload_hash_mismatch_in_open_segment_raises_on_open(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    seg_id = wal.current_segment_metadata().segment_id
    wal.close()

    jsonl_path = tmp_path / "segments" / f"{seg_id}.jsonl"
    meta_path = tmp_path / "metadata" / f"{seg_id}.json"
    _tamper_payload_hash_in_segment(jsonl_path, meta_path)

    with pytest.raises(LocalWalCorruptionError, match="payload_hash"):
        LocalJsonlWal.open(cfg)


def test_payload_hash_mismatch_after_open_raises_on_iter_records(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, segment_max_events=2)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    wal.append(_event("evt-3"))  # rollover: sealed, open
    sealed_meta = next(
        m for m in wal.list_segment_metadata() if m.status is WalSegmentStatus.SEALED
    )
    wal.close()

    wal2 = LocalJsonlWal.open(cfg)

    # Corrupt the sealed segment AFTER open — must be caught lazily by iter_records.
    sealed_path = tmp_path / "segments" / f"{sealed_meta.segment_id}.jsonl"
    meta_path = tmp_path / "metadata" / f"{sealed_meta.segment_id}.json"
    _tamper_payload_hash_in_segment(sealed_path, meta_path)

    with pytest.raises(LocalWalCorruptionError, match="payload_hash"):
        list(wal2.iter_records())
    wal2.close()


# ── Atomic metadata writes ────────────────────────────────────────────────────


def test_no_metadata_tmp_files_remain_after_successful_append(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path))
    wal.append(_event("evt-1"))
    wal.close()

    tmp_files = list((tmp_path / "metadata").glob("*.tmp"))
    assert tmp_files == [], f"leftover .tmp files: {tmp_files}"


def test_no_metadata_tmp_files_remain_after_rollover(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path, segment_max_events=2))
    wal.append(_event("evt-1"))
    wal.append(_event("evt-2"))
    wal.append(_event("evt-3"))  # triggers rollover
    wal.close()

    tmp_files = list((tmp_path / "metadata").glob("*.tmp"))
    assert tmp_files == [], f"leftover .tmp files: {tmp_files}"


def test_no_metadata_tmp_files_remain_after_seal(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path))
    wal.append(_event("evt-1"))
    wal.seal_current_segment()
    wal.close()

    tmp_files = list((tmp_path / "metadata").glob("*.tmp"))
    assert tmp_files == [], f"leftover .tmp files: {tmp_files}"


# ── close() error handling ────────────────────────────────────────────────────


class _FlushFailFile:
    """Fake file object whose flush always raises."""

    def flush(self) -> None:
        raise OSError("simulated disk full")

    def fileno(self) -> int:
        return -1

    def close(self) -> None:
        pass

    def write(self, s: str) -> int:
        return len(s)


def test_close_raises_local_wal_error_on_flush_failure(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path))
    wal.append(_event("evt-1"))

    wal._active_file = _FlushFailFile()  # type: ignore[assignment]

    with pytest.raises(LocalWalError):
        wal.close()


def test_close_is_idempotent(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path))
    wal.append(_event("evt-1"))
    wal.close()
    wal.close()  # second call must not raise


# ── _do_seal error handling ───────────────────────────────────────────────────


def test_append_after_failed_seal_returns_rejected_unavailable(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path))
    wal.append(_event("evt-1"))

    wal._active_file = _FlushFailFile()  # type: ignore[assignment]

    with pytest.raises(LocalWalError):
        wal.seal_current_segment()

    # WAL must be marked unavailable; append must not raise a raw I/O error.
    result = wal.append(_event("evt-2"))
    assert result.status is WalAppendStatus.REJECTED_WAL_UNAVAILABLE


def test_close_after_failed_seal_is_idempotent(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path))
    wal.append(_event("evt-1"))

    wal._active_file = _FlushFailFile()  # type: ignore[assignment]

    with pytest.raises(LocalWalError):
        wal.seal_current_segment()

    wal.close()   # must not raise
    wal.close()   # second call must also not raise


def test_seal_raises_local_wal_error_on_flush_failure(tmp_path: Path) -> None:
    wal = LocalJsonlWal.open(_cfg(tmp_path))
    wal.append(_event("evt-1"))

    wal._active_file = _FlushFailFile()  # type: ignore[assignment]

    with pytest.raises(LocalWalError):
        wal.seal_current_segment()


def test_seal_does_not_write_sealed_metadata_on_flush_failure(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    seg_id = wal.current_segment_metadata().segment_id

    wal._active_file = _FlushFailFile()  # type: ignore[assignment]

    with pytest.raises(LocalWalError):
        wal.seal_current_segment()

    meta_path = tmp_path / "metadata" / f"{seg_id}.json"
    saved = WalSegmentMetadata.model_validate_json(meta_path.read_text(encoding="utf-8"))
    assert saved.status is WalSegmentStatus.OPEN


# ── OPEN segment JSONL-ahead-of-metadata recovery ────────────────────────────


def _append_extra_record_to_jsonl(
    cfg: LocalJsonlWalConfig,
    seg_id: object,
    offset: int,
    event_id: str,
    tmp_path: Path,
) -> None:
    """Write a valid extra JournalRecord line directly to the JSONL file."""
    evt = _event(event_id)
    record = JournalRecord(
        run_id=cfg.run_id,
        producer_id=cfg.producer_id,
        wal_offset=WalOffset(value=offset),
        event=evt,
        recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
        payload_hash=_compute_payload_hash(evt),
        record_size_bytes=len(evt.model_dump_json().encode()),
    )
    jsonl_path = tmp_path / "segments" / f"{seg_id}.jsonl"
    with jsonl_path.open("a", encoding="utf-8") as fh:
        fh.write(record.model_dump_json() + "\n")


def test_open_segment_jsonl_ahead_of_metadata_recovers_successfully(
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    seg_id = wal.current_segment_metadata().segment_id
    wal.close()

    # Simulate crash: extra record in JSONL but metadata still shows 1 record.
    _append_extra_record_to_jsonl(cfg, seg_id, offset=1, event_id="evt-2", tmp_path=tmp_path)

    wal2 = LocalJsonlWal.open(cfg)
    meta = wal2.current_segment_metadata()
    assert meta.event_count == 2
    assert meta.offset_range is not None
    assert meta.offset_range.first.value == 0
    assert meta.offset_range.last.value == 1
    wal2.close()


def test_open_segment_jsonl_ahead_corrects_metadata_on_disk(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    seg_id = wal.current_segment_metadata().segment_id
    wal.close()

    _append_extra_record_to_jsonl(cfg, seg_id, offset=1, event_id="evt-2", tmp_path=tmp_path)

    LocalJsonlWal.open(cfg).close()

    meta_path = tmp_path / "metadata" / f"{seg_id}.json"
    saved = WalSegmentMetadata.model_validate_json(meta_path.read_text(encoding="utf-8"))
    assert saved.event_count == 2
    assert saved.offset_range is not None
    assert saved.offset_range.last.value == 1


def test_append_after_jsonl_ahead_recovery_uses_next_offset(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    seg_id = wal.current_segment_metadata().segment_id
    wal.close()

    _append_extra_record_to_jsonl(cfg, seg_id, offset=1, event_id="evt-2", tmp_path=tmp_path)

    wal2 = LocalJsonlWal.open(cfg)
    result = wal2.append(_event("evt-3"))
    wal2.close()

    assert result.record is not None
    assert result.record.wal_offset.value == 2


def test_open_segment_corrupt_extra_record_in_jsonl_raises(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    seg_id = wal.current_segment_metadata().segment_id
    wal.close()

    jsonl_path = tmp_path / "segments" / f"{seg_id}.jsonl"
    with jsonl_path.open("a", encoding="utf-8") as fh:
        fh.write("not-valid-json\n")

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)


def test_open_segment_jsonl_ahead_globally_contiguous_with_sealed_recovers(
    tmp_path: Path,
) -> None:
    # Sprint scenario: sealed segment covers offset 0; OPEN segment JSONL has
    # a record at offset 1 but its metadata is stale/empty (crash window).
    # The global offset stream is contiguous, so open() must succeed.
    cfg = _cfg(tmp_path, segment_max_events=1)

    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-0"))  # offset 0; max_events=1 triggers rollover
    seg2_id = wal.current_segment_metadata().segment_id
    wal.close()

    # Simulate crash: record at offset 1 in segment-2 JSONL, metadata still empty.
    _append_extra_record_to_jsonl(cfg, seg2_id, offset=1, event_id="evt-1", tmp_path=tmp_path)

    wal2 = LocalJsonlWal.open(cfg)
    meta = wal2.current_segment_metadata()
    assert meta.event_count == 1
    assert meta.offset_range is not None
    assert meta.offset_range.first.value == 1
    assert meta.offset_range.last.value == 1

    result = wal2.append(_event("evt-2"))
    wal2.close()
    assert result.record is not None
    assert result.record.wal_offset.value == 2


def test_globally_invalid_open_segment_does_not_mutate_metadata(tmp_path: Path) -> None:
    # Sprint scenario: sealed segment covers offset 0; OPEN segment JSONL has
    # a record at offset 5 (gap, should be 1).  open() must raise and leave
    # ALL metadata files byte-for-byte unchanged.
    cfg = _cfg(tmp_path, segment_max_events=1)

    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-0"))  # offset 0; rollover → segment-1 sealed
    seg2_id = wal.current_segment_metadata().segment_id
    wal.close()

    meta_dir = tmp_path / "metadata"
    before = {p.name: p.read_bytes() for p in sorted(meta_dir.glob("*.json"))}

    # Append a valid-looking record at wrong global offset 5.
    _append_extra_record_to_jsonl(cfg, seg2_id, offset=5, event_id="evt-bad", tmp_path=tmp_path)

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)

    after = {p.name: p.read_bytes() for p in sorted(meta_dir.glob("*.json"))}
    assert before == after, "metadata files were mutated despite a failed open()"


def test_corrupt_open_segment_jsonl_does_not_mutate_metadata(tmp_path: Path) -> None:
    # A corrupt extra JSONL line must raise LocalWalCorruptionError without
    # overwriting any metadata file.
    cfg = _cfg(tmp_path)
    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    seg_id = wal.current_segment_metadata().segment_id
    wal.close()

    meta_dir = tmp_path / "metadata"
    before = {p.name: p.read_bytes() for p in sorted(meta_dir.glob("*.json"))}

    jsonl_path = tmp_path / "segments" / f"{seg_id}.jsonl"
    with jsonl_path.open("a", encoding="utf-8") as fh:
        fh.write("not-valid-json\n")

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)

    after = {p.name: p.read_bytes() for p in sorted(meta_dir.glob("*.json"))}
    assert before == after, "metadata files were mutated despite a corrupt OPEN segment"


# ── EventJournalPort conformance ──────────────────────────────────────────────


def test_local_jsonl_wal_conforms_to_event_journal_port(tmp_path: Path) -> None:
    from futures_bot.ports.event_journal import EventJournalPort  # noqa: PLC0415

    wal = LocalJsonlWal.open(_cfg(tmp_path))
    required = (
        "append",
        "current_segment_metadata",
        "list_segment_metadata",
        "seal_current_segment",
        "iter_records",
        "read_segment",
        "close",
    )
    for method in required:
        assert callable(getattr(wal, method, None)), f"missing port method: {method}"
    wal.close()

    # Pyright verifies this assignment statically; keep as a reference.
    _journal: EventJournalPort = wal  # type: ignore[assignment]
