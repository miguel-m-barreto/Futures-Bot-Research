"""In-memory broker publisher for tests and local contract validation.

No Kafka client. No network. No async.
"""
from __future__ import annotations

from futures_bot.domain.broker import (
    BrokerPublishStatus,
    KafkaConsumedRecord,
    KafkaPartitionOffset,
    KafkaPublishAck,
    KafkaPublishRecord,
)
from futures_bot.domain.journal import WalOffset


class InMemoryBrokerPublisher:
    """In-memory BrokerPublisherPort implementation.

    Stores published batches for test inspection.  Offsets increment
    deterministically starting from 0.  Supports a fail_next flag to
    simulate broker unavailability.

    No Kafka import. No network code.
    """

    def __init__(self, fail_next: bool = False) -> None:
        self._published_batches: list[tuple[KafkaPublishRecord, ...]] = []
        self._consumed_batches: list[tuple[KafkaConsumedRecord, ...]] = []
        self._offset_counter: int = 0
        self.fail_next: bool = fail_next

    # ── BrokerPublisherPort ───────────────────────────────────────────────────

    def publish_batch(
        self, records: tuple[KafkaPublishRecord, ...]
    ) -> KafkaPublishAck:
        """Publish a batch. Returns PUBLISHED ack or a rejection ack."""
        if not records:
            return KafkaPublishAck(
                status=BrokerPublishStatus.REJECTED_INVALID_RECORD,
                published=False,
                journal_offset=WalOffset(value=0),
                reason="batch must be non-empty",
            )

        last = records[-1]
        journal_offset = last.journal_record.wal_offset

        if self.fail_next:
            self.fail_next = False
            return KafkaPublishAck(
                status=BrokerPublishStatus.REJECTED_BROKER_UNAVAILABLE,
                published=False,
                journal_offset=journal_offset,
                reason="simulated broker unavailable",
            )

        # Assign monotonically increasing Kafka partition offsets for this
        # local fake broker partition. The consumed record is the broker-side
        # contract DBWriter may consume.
        batch_start = self._offset_counter
        self._offset_counter += len(records)
        consumed_records = tuple(
            KafkaConsumedRecord(
                journal_record=record.journal_record,
                topic=record.topic,
                key=record.key,
                kafka_offset=KafkaPartitionOffset(
                    topic=record.topic,
                    partition=0,
                    offset=batch_start + index,
                ),
            )
            for index, record in enumerate(records)
        )
        kafka_offset = KafkaPartitionOffset(
            topic=last.topic,
            partition=0,
            offset=batch_start + len(records) - 1,
        )

        self._published_batches.append(records)
        self._consumed_batches.append(consumed_records)

        return KafkaPublishAck(
            status=BrokerPublishStatus.PUBLISHED,
            published=True,
            journal_offset=journal_offset,
            kafka_offset=kafka_offset,
        )

    # ── test accessors ────────────────────────────────────────────────────────

    @property
    def published_batches(self) -> list[tuple[KafkaPublishRecord, ...]]:
        """Snapshot of all successfully published batches."""
        return list(self._published_batches)

    @property
    def published_records(self) -> list[KafkaPublishRecord]:
        """Flat list of all successfully published records in order."""
        return [rec for batch in self._published_batches for rec in batch]

    def consumed_records(self) -> tuple[KafkaConsumedRecord, ...]:
        """Flat tuple of broker-assigned records in publish order."""
        return tuple(rec for batch in self._consumed_batches for rec in batch)
