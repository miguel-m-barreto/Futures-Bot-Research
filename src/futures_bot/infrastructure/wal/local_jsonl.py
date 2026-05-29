"""Local segmented JSONL WAL implementation.

Directory layout under config.root_dir:

    segments/   - JSONL files for every segment ({segment_id}.jsonl)
    metadata/   - JSON metadata for every segment ({segment_id}.json)

Segment IDs follow the pattern "{run_id}-segment-{N:06d}" (N starting at 1).
Offsets are globally monotonic across segments and never reset on rollover.
Segment files are never deleted or moved; status is tracked in metadata only.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

from pydantic import BaseModel, ConfigDict, field_validator

from futures_bot.domain.events import EventEnvelope
from futures_bot.domain.ids import ProducerId, RunId, WalSegmentId
from futures_bot.domain.journal import JournalRecord, WalOffset, WalOffsetRange
from futures_bot.domain.time import ensure_aware_utc
from futures_bot.domain.wal import (
    WalAppendResult,
    WalAppendStatus,
    WalSegmentMetadata,
    WalSegmentStatus,
)

# ── Exceptions ────────────────────────────────────────────────────────────────


class LocalWalError(Exception):
    """Base exception for local WAL errors."""


class LocalWalCorruptionError(LocalWalError):
    """Raised when WAL files or metadata are inconsistent or malformed."""


# ── Config ────────────────────────────────────────────────────────────────────


class LocalJsonlWalConfig(BaseModel):
    """Immutable configuration for a local JSONL WAL instance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    root_dir: Path
    run_id: RunId
    producer_id: ProducerId
    segment_max_bytes: int = 256 * 1024 * 1024
    segment_max_events: int = 1_000_000
    segment_max_age_seconds: int = 300
    fsync_on_append: bool = True

    @field_validator("segment_max_bytes")
    @classmethod
    def _validate_segment_max_bytes(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("segment_max_bytes must be > 0")
        return v

    @field_validator("segment_max_events")
    @classmethod
    def _validate_segment_max_events(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("segment_max_events must be > 0")
        return v

    @field_validator("segment_max_age_seconds")
    @classmethod
    def _validate_segment_max_age_seconds(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("segment_max_age_seconds must be > 0")
        return v


# ── Helpers ───────────────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _segment_id_for(run_id: RunId, index: int) -> WalSegmentId:
    return WalSegmentId(value=f"{run_id}-segment-{index:06d}")


def _segment_index_from_id(segment_id: WalSegmentId, run_id: RunId) -> int:
    prefix = f"{run_id}-segment-"
    sid = str(segment_id)
    if not sid.startswith(prefix):
        raise LocalWalCorruptionError(
            f"unexpected segment_id {sid!r} for run_id {run_id!r}"
        )
    suffix = sid[len(prefix):]
    try:
        return int(suffix)
    except ValueError as exc:
        raise LocalWalCorruptionError(
            f"cannot parse segment index from {sid!r}"
        ) from exc


def _compute_payload_hash(event: EventEnvelope) -> str:
    """SHA-256 of canonical (sorted-keys, compact) event JSON."""
    raw = json.loads(event.model_dump_json())
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _load_metadata_for_run(
    metadata_dir: Path, run_id: RunId
) -> list[WalSegmentMetadata]:
    result: list[WalSegmentMetadata] = []
    for path in metadata_dir.glob("*.json"):
        try:
            meta = WalSegmentMetadata.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise LocalWalCorruptionError(
                f"failed to parse metadata file {path}"
            ) from exc
        if str(meta.run_id) == str(run_id):
            result.append(meta)
    return result


# ── WAL implementation ────────────────────────────────────────────────────────


class LocalJsonlWal:
    """Local append-only JSONL WAL.

    Construct exclusively via ``LocalJsonlWal.open(config)``.
    """

    # Instance attribute declarations for type checkers.
    _config: LocalJsonlWalConfig
    _closed: bool
    _segments_dir: Path
    _metadata_dir: Path
    _sealed_meta: list[WalSegmentMetadata]
    _next_offset: int
    _current_segment_index: int
    _active_segment_id: WalSegmentId
    _active_segment_created_at: datetime
    _active_event_count: int
    _active_byte_count: int
    _active_first_offset: int | None
    _active_last_offset: int | None
    _active_file: IO[str]

    # ── Construction ──────────────────────────────────────────────────────────

    @classmethod
    def open(cls, config: LocalJsonlWalConfig) -> LocalJsonlWal:
        """Open or create a WAL rooted at config.root_dir.

        If existing segments belonging to config.run_id are found, the WAL
        resumes from the next offset.  An existing OPEN segment is recovered
        by replaying its JSONL file.
        """
        self = object.__new__(cls)
        self._config = config
        self._closed = False

        segments_dir = config.root_dir / "segments"
        metadata_dir = config.root_dir / "metadata"
        segments_dir.mkdir(parents=True, exist_ok=True)
        metadata_dir.mkdir(parents=True, exist_ok=True)
        self._segments_dir = segments_dir
        self._metadata_dir = metadata_dir

        all_meta = _load_metadata_for_run(metadata_dir, config.run_id)
        open_segs = [m for m in all_meta if m.status is WalSegmentStatus.OPEN]
        sealed = [m for m in all_meta if m.status is not WalSegmentStatus.OPEN]

        if len(open_segs) > 1:
            raise LocalWalCorruptionError(
                f"multiple OPEN segments for run_id={config.run_id}"
            )

        sealed_sorted = sorted(
            sealed,
            key=lambda m: _segment_index_from_id(m.segment_id, config.run_id),
        )
        self._sealed_meta = sealed_sorted

        last_sealed_offset: int | None = None
        if sealed_sorted and sealed_sorted[-1].offset_range is not None:
            last_sealed_offset = sealed_sorted[-1].offset_range.last.value

        all_indices = [
            _segment_index_from_id(m.segment_id, config.run_id) for m in all_meta
        ]
        next_index = max(all_indices) + 1 if all_indices else 1

        # Initialize mutable active-segment state to defaults; may be
        # overwritten by _recover_open_segment below.
        self._active_first_offset = None
        self._active_last_offset = None
        self._active_event_count = 0
        self._active_byte_count = 0
        self._next_offset = 0 if last_sealed_offset is None else last_sealed_offset + 1

        if open_segs:
            active_meta = open_segs[0]
            self._current_segment_index = _segment_index_from_id(
                active_meta.segment_id, config.run_id
            )
            self._active_segment_id = active_meta.segment_id
            self._active_segment_created_at = active_meta.created_at
            self._recover_open_segment(active_meta)
        else:
            self._current_segment_index = next_index
            self._active_segment_id = _segment_id_for(config.run_id, next_index)
            self._active_segment_created_at = _utcnow()
            self._save_metadata(self.current_segment_metadata())

        self._active_file = self._segment_path(
            self._active_segment_id
        ).open("a", encoding="utf-8")
        return self

    def _recover_open_segment(self, meta: WalSegmentMetadata) -> None:
        path = self._segment_path(meta.segment_id)
        if not path.exists():
            raise LocalWalCorruptionError(f"OPEN segment file missing: {path}")

        text = path.read_text(encoding="utf-8")
        records: list[JournalRecord] = []
        total_bytes = 0

        for line_num, raw_line in enumerate(text.splitlines(), 1):
            if not raw_line.strip():
                continue
            try:
                record = JournalRecord.model_validate_json(raw_line)
            except Exception as exc:
                raise LocalWalCorruptionError(
                    f"malformed record at line {line_num} in {path}"
                ) from exc
            records.append(record)
            total_bytes += len(raw_line.encode()) + 1  # +1 for trailing \n

        self._active_event_count = len(records)
        self._active_byte_count = total_bytes

        if records:
            self._active_first_offset = records[0].wal_offset.value
            self._active_last_offset = records[-1].wal_offset.value
            self._next_offset = self._active_last_offset + 1

        if meta.event_count != self._active_event_count:
            raise LocalWalCorruptionError(
                f"metadata event_count={meta.event_count} but {path} "
                f"contains {self._active_event_count} records"
            )

    # ── Path helpers ──────────────────────────────────────────────────────────

    def _segment_path(self, segment_id: WalSegmentId) -> Path:
        return self._segments_dir / f"{segment_id}.jsonl"

    def _metadata_path(self, segment_id: WalSegmentId) -> Path:
        return self._metadata_dir / f"{segment_id}.json"

    def _save_metadata(self, meta: WalSegmentMetadata) -> None:
        self._metadata_path(meta.segment_id).write_text(
            meta.model_dump_json(), encoding="utf-8"
        )

    # ── Public interface ──────────────────────────────────────────────────────

    def current_segment_metadata(self) -> WalSegmentMetadata:
        offset_range: WalOffsetRange | None = None
        if self._active_first_offset is not None and self._active_last_offset is not None:
            offset_range = WalOffsetRange(
                first=WalOffset(value=self._active_first_offset),
                last=WalOffset(value=self._active_last_offset),
            )
        return WalSegmentMetadata(
            segment_id=self._active_segment_id,
            run_id=self._config.run_id,
            status=WalSegmentStatus.OPEN,
            offset_range=offset_range,
            created_at=self._active_segment_created_at,
            event_count=self._active_event_count,
            payload_bytes=self._active_byte_count,
        )

    def list_segment_metadata(self) -> tuple[WalSegmentMetadata, ...]:
        return (*self._sealed_meta, self.current_segment_metadata())

    def append(
        self,
        event: EventEnvelope,
        *,
        recorded_at: datetime | None = None,
    ) -> WalAppendResult:
        if self._closed:
            return WalAppendResult.rejected(
                WalAppendStatus.REJECTED_WAL_UNAVAILABLE, "WAL is closed"
            )

        ts = ensure_aware_utc(recorded_at) if recorded_at is not None else _utcnow()
        payload_hash = _compute_payload_hash(event)
        event_json = event.model_dump_json()
        record_size_bytes = len(event_json.encode())

        record = JournalRecord(
            run_id=self._config.run_id,
            producer_id=self._config.producer_id,
            wal_offset=WalOffset(value=self._next_offset),
            event=event,
            recorded_at=ts,
            payload_hash=payload_hash,
            record_size_bytes=record_size_bytes,
        )

        line = record.model_dump_json() + "\n"
        encoded_len = len(line.encode())
        self._active_file.write(line)
        self._active_file.flush()
        if self._config.fsync_on_append:
            os.fsync(self._active_file.fileno())

        # Update active-segment state.
        self._next_offset += 1
        self._active_event_count += 1
        self._active_byte_count += encoded_len
        if self._active_first_offset is None:
            self._active_first_offset = record.wal_offset.value
        self._active_last_offset = record.wal_offset.value

        self._save_metadata(self.current_segment_metadata())

        if self._should_rollover(ts):
            self._rollover(ts)

        return WalAppendResult.ok(record)

    def seal_current_segment(self) -> WalSegmentMetadata:
        """Seal the active segment and start a fresh OPEN segment.

        Safe to call before close(); the new segment will have zero events.
        """
        if self._closed:
            raise LocalWalError("cannot seal: WAL is closed")

        sealed_at = _utcnow()
        sealed_meta = self._do_seal(sealed_at)

        # Start new OPEN segment.
        self._current_segment_index += 1
        new_id = _segment_id_for(self._config.run_id, self._current_segment_index)
        self._active_segment_id = new_id
        self._active_segment_created_at = _utcnow()
        self._active_event_count = 0
        self._active_byte_count = 0
        self._active_first_offset = None
        self._active_last_offset = None
        self._save_metadata(self.current_segment_metadata())
        self._active_file = self._segment_path(new_id).open("a", encoding="utf-8")
        return sealed_meta

    def iter_records(self) -> Iterator[JournalRecord]:
        """Yield every record across all segments in WAL offset order."""
        if not self._closed:
            self._active_file.flush()
        for meta in self.list_segment_metadata():
            yield from self.read_segment(meta.segment_id)

    def read_segment(self, segment_id: WalSegmentId) -> tuple[JournalRecord, ...]:
        """Read and return all records from the named segment.

        Raises LocalWalCorruptionError if the file is missing or malformed.
        """
        path = self._segment_path(segment_id)
        if not path.exists():
            raise LocalWalCorruptionError(f"segment file not found: {path}")

        text = path.read_text(encoding="utf-8")
        records: list[JournalRecord] = []
        for line_num, raw_line in enumerate(text.splitlines(), 1):
            if not raw_line.strip():
                continue
            try:
                record = JournalRecord.model_validate_json(raw_line)
            except Exception as exc:
                raise LocalWalCorruptionError(
                    f"malformed record at line {line_num} in {path}"
                ) from exc
            records.append(record)
        return tuple(records)

    def close(self) -> None:
        """Flush and release the active file handle.

        Subsequent appends return REJECTED_WAL_UNAVAILABLE.
        The active segment is left OPEN in metadata; recovery can resume it.
        """
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(Exception):
            self._active_file.flush()
            if self._config.fsync_on_append:
                with contextlib.suppress(OSError):
                    os.fsync(self._active_file.fileno())
            self._active_file.close()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _should_rollover(self, now: datetime) -> bool:
        if self._active_byte_count >= self._config.segment_max_bytes:
            return True
        if self._active_event_count >= self._config.segment_max_events:
            return True
        age = (now - self._active_segment_created_at).total_seconds()
        return age >= self._config.segment_max_age_seconds

    def _do_seal(self, sealed_at: datetime) -> WalSegmentMetadata:
        """Flush, close, and finalize metadata for the active segment."""
        self._active_file.flush()
        if self._config.fsync_on_append:
            with contextlib.suppress(OSError):
                os.fsync(self._active_file.fileno())
        self._active_file.close()

        # Guarantee sealed_at >= created_at even under clock skew.
        safe_sealed_at = max(sealed_at, self._active_segment_created_at)

        offset_range: WalOffsetRange | None = None
        if self._active_first_offset is not None and self._active_last_offset is not None:
            offset_range = WalOffsetRange(
                first=WalOffset(value=self._active_first_offset),
                last=WalOffset(value=self._active_last_offset),
            )

        sealed_meta = WalSegmentMetadata(
            segment_id=self._active_segment_id,
            run_id=self._config.run_id,
            status=WalSegmentStatus.SEALED,
            offset_range=offset_range,
            created_at=self._active_segment_created_at,
            sealed_at=safe_sealed_at,
            event_count=self._active_event_count,
            payload_bytes=self._active_byte_count,
        )
        self._save_metadata(sealed_meta)
        self._sealed_meta.append(sealed_meta)
        return sealed_meta

    def _rollover(self, sealed_at: datetime) -> None:
        """Seal the current segment and open a new one (called after append)."""
        self._do_seal(sealed_at)

        self._current_segment_index += 1
        new_id = _segment_id_for(self._config.run_id, self._current_segment_index)
        # New segment created_at must be >= sealed_at.
        new_created_at = max(_utcnow(), sealed_at)

        self._active_segment_id = new_id
        self._active_segment_created_at = new_created_at
        self._active_event_count = 0
        self._active_byte_count = 0
        self._active_first_offset = None
        self._active_last_offset = None

        self._save_metadata(self.current_segment_metadata())
        self._active_file = self._segment_path(new_id).open("a", encoding="utf-8")
