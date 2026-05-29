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

from futures_bot.domain.events import EventEnvelope, EventType
from futures_bot.domain.ids import BotId, EventId, ProducerId, RunId
from futures_bot.domain.journal import JournalRecord
from futures_bot.domain.wal import WalAppendStatus, WalSegmentStatus
from futures_bot.infrastructure.wal.local_jsonl import (
    LocalJsonlWal,
    LocalJsonlWalConfig,
    LocalWalCorruptionError,
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

    # Corrupt the sealed segment
    sealed_path = tmp_path / "segments" / f"{sealed_meta.segment_id}.jsonl"
    sealed_path.write_text(
        sealed_path.read_text(encoding="utf-8") + "not-valid-json\n",
        encoding="utf-8",
    )

    wal2 = LocalJsonlWal.open(cfg)
    with pytest.raises(LocalWalCorruptionError):
        list(wal2.iter_records())
    wal2.close()


def test_metadata_event_count_mismatch_raises_on_open(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)

    wal = LocalJsonlWal.open(cfg)
    wal.append(_event("evt-1"))
    seg_id = wal.current_segment_metadata().segment_id
    wal.close()

    # Tamper with the metadata to report a wrong event_count.
    meta_path = tmp_path / "metadata" / f"{seg_id}.json"
    data = _json.loads(meta_path.read_text(encoding="utf-8"))
    data["event_count"] = 99
    # Must also clear offset_range to avoid event_count != range.count conflict.
    data["offset_range"] = None
    meta_path.write_text(_json.dumps(data), encoding="utf-8")

    with pytest.raises(LocalWalCorruptionError):
        LocalJsonlWal.open(cfg)


# ── Safety ─────────────────────────────────────────────────────────────────────


def test_no_kafka_or_db_imports_in_implementation() -> None:
    mod = importlib.import_module(
        "futures_bot.infrastructure.wal.local_jsonl"
    )
    source_file = mod.__file__ or ""
    source = Path(source_file).read_text(encoding="utf-8")

    for forbidden in ("kafka", "confluent", "postgres", "psycopg", "sqlalchemy", "duckdb"):
        assert forbidden not in source.lower(), f"forbidden import found: {forbidden}"


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
