from __future__ import annotations

from typing import Protocol

from futures_bot.domain.relay import WalRelayBatch, WalRelayPublishResult


class WalRelayPort(Protocol):
    """Contract for relaying WAL records to a broker.

    A concrete implementation reads from an EventJournalPort and publishes
    via a BrokerPublisherPort.  The relay loop itself is not defined here —
    this port is a contract only.

    LocalJsonlWal is not imported here.  Relay logic depends on
    EventJournalPort, not on any concrete WAL implementation.
    """

    def publish_batch(self, batch: WalRelayBatch) -> WalRelayPublishResult:
        """Publish a WAL relay batch and return the publish result."""
        ...
