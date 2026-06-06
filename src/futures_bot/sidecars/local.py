"""One-shot local sidecar adapters.

No processes. No loops. No threads. No async runtime. No retries.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from futures_bot.db_writer.service import LocalDbWriterService
from futures_bot.domain import broker as broker_domain
from futures_bot.domain.ids import SidecarId
from futures_bot.domain.relay import WalRelayPublishResult
from futures_bot.domain.sidecars import (
    DbWriterCheckpoint,
    SidecarHealthLevel,
    SidecarHealthSnapshot,
    SidecarKind,
    SidecarLifecycleStatus,
)
from futures_bot.ports.sidecar_runtime import SidecarHealthStorePort
from futures_bot.relay.service import LocalWalRelayService


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LocalWalRelaySidecar:
    """One-shot local WAL relay sidecar adapter."""

    def __init__(
        self,
        *,
        sidecar_id: SidecarId,
        relay_service: LocalWalRelayService,
        health_store: SidecarHealthStorePort | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._sidecar_id = sidecar_id
        self._relay_service = relay_service
        self._health_store = health_store
        self._now: Callable[[], datetime] = now if now is not None else _utcnow

    def run_once(self, max_records: int) -> WalRelayPublishResult | None:
        """Run one relay pass and record an observability snapshot."""
        try:
            result = self._relay_service.relay_once(max_records)
        except Exception as exc:
            self._save_snapshot(
                SidecarHealthSnapshot(
                    sidecar_id=self._sidecar_id,
                    sidecar_kind=SidecarKind.WAL_RELAY,
                    lifecycle_status=SidecarLifecycleStatus.FAILED,
                    health=SidecarHealthLevel.UNHEALTHY,
                    checked_at=self._now(),
                    error=str(exc),
                )
            )
            raise

        if result is None:
            self._save_snapshot(
                SidecarHealthSnapshot(
                    sidecar_id=self._sidecar_id,
                    sidecar_kind=SidecarKind.WAL_RELAY,
                    lifecycle_status=SidecarLifecycleStatus.RUNNING,
                    health=SidecarHealthLevel.HEALTHY,
                    checked_at=self._now(),
                    message="relay_once completed: no pending records",
                )
            )
            return None

        self._save_snapshot(
            SidecarHealthSnapshot(
                sidecar_id=self._sidecar_id,
                sidecar_kind=SidecarKind.WAL_RELAY,
                lifecycle_status=SidecarLifecycleStatus.RUNNING,
                health=SidecarHealthLevel.HEALTHY,
                checked_at=self._now(),
                run_id=result.run_id,
                last_processed_wal_offset=result.last_offset,
                message="relay_once completed",
            )
        )
        return result

    def _save_snapshot(self, snapshot: SidecarHealthSnapshot) -> None:
        if self._health_store is None:
            return
        self._health_store.save(snapshot)


class LocalDbWriterSidecar:
    """One-shot local DB writer sidecar adapter."""

    def __init__(
        self,
        *,
        sidecar_id: SidecarId,
        db_writer_service: LocalDbWriterService,
        health_store: SidecarHealthStorePort | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._sidecar_id = sidecar_id
        self._db_writer_service = db_writer_service
        self._health_store = health_store
        self._now: Callable[[], datetime] = now if now is not None else _utcnow

    def commit_once(
        self, records: tuple[broker_domain.KafkaConsumedRecord, ...]
    ) -> DbWriterCheckpoint | None:
        """Commit one consumed-record batch and record an observability snapshot."""
        try:
            checkpoint = self._db_writer_service.commit_consumed_batch(records)
        except Exception as exc:
            self._save_snapshot(
                SidecarHealthSnapshot(
                    sidecar_id=self._sidecar_id,
                    sidecar_kind=SidecarKind.DB_WRITER,
                    lifecycle_status=SidecarLifecycleStatus.FAILED,
                    health=SidecarHealthLevel.UNHEALTHY,
                    checked_at=self._now(),
                    error=str(exc),
                )
            )
            raise

        if checkpoint is None:
            self._save_snapshot(
                SidecarHealthSnapshot(
                    sidecar_id=self._sidecar_id,
                    sidecar_kind=SidecarKind.DB_WRITER,
                    lifecycle_status=SidecarLifecycleStatus.RUNNING,
                    health=SidecarHealthLevel.HEALTHY,
                    checked_at=self._now(),
                    message="commit_once completed",
                )
            )
            return None

        self._save_snapshot(
            SidecarHealthSnapshot(
                sidecar_id=self._sidecar_id,
                sidecar_kind=SidecarKind.DB_WRITER,
                lifecycle_status=SidecarLifecycleStatus.RUNNING,
                health=SidecarHealthLevel.HEALTHY,
                checked_at=self._now(),
                run_id=checkpoint.run_id,
                last_processed_wal_offset=checkpoint.last_committed_wal_offset,
                message="commit_once completed",
            )
        )
        return checkpoint

    def _save_snapshot(self, snapshot: SidecarHealthSnapshot) -> None:
        if self._health_store is None:
            return
        self._health_store.save(snapshot)
