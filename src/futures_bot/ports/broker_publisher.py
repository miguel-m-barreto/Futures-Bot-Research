from __future__ import annotations

from typing import Protocol

from futures_bot.domain.broker import KafkaPublishAck, KafkaPublishRecord


class BrokerPublisherPort(Protocol):
    """Contract for publishing a batch of records to a broker.

    Implementations provide broker-backed transport (e.g. Kafka) without
    leaking transport details into domain or relay logic.  No Kafka client,
    no network code, no async runtime in this port definition.
    """

    def publish_batch(
        self, records: tuple[KafkaPublishRecord, ...]
    ) -> KafkaPublishAck:
        """Publish a batch of records. Returns the ack for the last record."""
        ...
