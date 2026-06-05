"""One-shot local WAL relay service.

No Kafka. No DB. No background loop. No threads. No network.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from futures_bot.domain.broker import KafkaPublishRecord
from futures_bot.domain.ids import BrokerTopicId, SidecarId
from futures_bot.domain.journal import JournalRecord
from futures_bot.domain.relay import WalRelayBatch, WalRelayPublishResult
from futures_bot.domain.sidecars import WalRelayCheckpoint
from futures_bot.ports.broker_publisher import BrokerPublisherPort
from futures_bot.ports.checkpoint_store import WalRelayCheckpointStorePort
from futures_bot.ports.event_journal import EventJournalPort


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LocalWalRelayService:
    """One-shot local WAL relay service.

    Reads unpublished records from an EventJournalPort, publishes them via
    a BrokerPublisherPort, and tracks broker-side progress in a
    WalRelayCheckpointStorePort.

    Depends on EventJournalPort — not on any concrete WAL implementation.
    No LocalJsonlWal reference. No async. No threads. No retries. No network.

    Usage:
        result = service.relay_once(max_records=500)
        # result is None if no unpublished records remain.
    """

    def __init__(  # noqa: PLR0913
        self,
        journal: EventJournalPort,
        publisher: BrokerPublisherPort,
        checkpoint_store: WalRelayCheckpointStorePort,
        relay_id: SidecarId,
        topic: BrokerTopicId,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._journal = journal
        self._publisher = publisher
        self._checkpoint_store = checkpoint_store
        self._relay_id = relay_id
        self._topic = topic
        self._now: Callable[[], datetime] = now if now is not None else _utcnow

    # ── public API ────────────────────────────────────────────────────────────

    def build_batch_after_checkpoint(self, max_records: int) -> WalRelayBatch | None:
        """Return the next batch of unpublished WAL records, or None.

        Derives run_id from the first record in the journal.  Loads the relay
        checkpoint for (relay_id, run_id) to determine the resume offset.
        If the journal is empty or all records are already published, returns None.

        Raises ValueError if max_records <= 0.
        """
        if max_records <= 0:
            raise ValueError(f"max_records must be > 0; got {max_records}")

        all_records = list(self._journal.iter_records())
        if not all_records:
            return None

        run_id = all_records[0].run_id
        checkpoint = self._checkpoint_store.load(self._relay_id, run_id)

        if checkpoint is None:
            pending = all_records
        else:
            threshold = checkpoint.last_published_wal_offset.value
            pending = [r for r in all_records if r.wal_offset.value > threshold]

        if not pending:
            return None

        # Guard against silent offset gaps between checkpoint and the next
        # available record.  WalRelayBatch only validates internal contiguity;
        # it cannot detect a missing leading offset relative to the checkpoint.
        if checkpoint is not None:
            expected = checkpoint.last_published_wal_offset.value + 1
            found = pending[0].wal_offset.value
            if found != expected:
                raise ValueError(
                    f"WAL relay gap detected: expected next offset {expected}, "
                    f"found {found}"
                )

        batch_records = tuple(pending[:max_records])
        # WalRelayBatch validates run_id consistency and internal offset contiguity.
        return WalRelayBatch(run_id=run_id, records=batch_records)

    def publish_batch(self, batch: WalRelayBatch) -> WalRelayPublishResult:
        """Publish a relay batch and return the result.

        On success (broker ack published=True): saves a WalRelayCheckpoint.
        On rejection: returns the result without saving any checkpoint.

        Does NOT create or update DbWriterCheckpoint.
        Does NOT call decide_wal_gc.
        Does NOT modify or delete WAL segments.

        The publisher is required to set broker_ack.journal_offset equal to the
        last record's WAL offset; WalRelayPublishResult validates this invariant.
        """
        kafka_records = tuple(
            KafkaPublishRecord(
                journal_record=rec,
                topic=self._topic,
                key=self._record_key(rec),
            )
            for rec in batch.records
        )

        ack = self._publisher.publish_batch(kafka_records)

        result = WalRelayPublishResult(
            run_id=batch.run_id,
            first_offset=batch.first_offset,
            last_offset=batch.last_offset,
            record_count=batch.record_count,
            broker_ack=ack,
        )

        if ack.published:
            kafka_offset = ack.kafka_offset
            assert kafka_offset is not None  # guaranteed by KafkaPublishAck validator
            self._checkpoint_store.save(
                WalRelayCheckpoint(
                    relay_id=self._relay_id,
                    run_id=batch.run_id,
                    last_published_wal_offset=batch.last_offset,
                    last_published_event_id=batch.records[-1].event.event_id,
                    kafka_offset=kafka_offset,
                    updated_at=self._now(),
                )
            )

        return result

    def relay_once(self, max_records: int) -> WalRelayPublishResult | None:
        """Build the next pending batch and publish it.

        Returns None if there are no unpublished records in the journal.
        Raises ValueError if max_records <= 0.
        """
        batch = self.build_batch_after_checkpoint(max_records)
        if batch is None:
            return None
        return self.publish_batch(batch)

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _record_key(record: JournalRecord) -> str:
        # Prefer bot_id for deterministic per-bot routing.
        # This is a local/in-memory key policy, not a Kafka partitioning guarantee.
        if record.event.bot_id is not None:
            return str(record.event.bot_id)
        return str(record.run_id)
