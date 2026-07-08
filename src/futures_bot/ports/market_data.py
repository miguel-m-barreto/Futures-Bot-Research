from __future__ import annotations

from datetime import datetime
from typing import Protocol

from futures_bot.domain.ids import (
    MarketDataObservationSnapshotId,
    MarketDataReadinessPolicyId,
)
from futures_bot.domain.market_data import (
    MarketDataObservationKind,
    MarketDataObservationSnapshot,
    MarketDataReadinessPolicy,
)
from futures_bot.domain.replay import ReplayDispatchContext, ReplayTimelineEvent
from futures_bot.domain.replay_market_data import (
    ReplayMarketFrameLookupAuthority,
    ReplayMarketFrameLookupDescriptor,
    ReplayMarketFrameLookupResult,
)


class MarketDataObservationSnapshotStorePort(Protocol):
    """Pure market-data observation snapshot store interface."""

    def put(self, snapshot: MarketDataObservationSnapshot) -> None:
        """Store a market-data observation snapshot idempotently."""
        ...

    def get(
        self,
        snapshot_id: MarketDataObservationSnapshotId,
    ) -> MarketDataObservationSnapshot | None:
        """Return a market-data observation snapshot by ID."""
        ...

    def latest_for_scope(
        self,
        venue_id: str,
        instrument_id: str,
        observation_kind: MarketDataObservationKind | str,
        checked_at: datetime,
    ) -> MarketDataObservationSnapshot | None:
        """Return the latest deterministic snapshot for a scope at checked_at."""
        ...

    def list_snapshots(self) -> tuple[MarketDataObservationSnapshot, ...]:
        """Return all snapshots in deterministic ID order."""
        ...


class MarketDataReadinessPolicyStorePort(Protocol):
    """Pure market-data readiness policy store interface."""

    def put(self, policy: MarketDataReadinessPolicy) -> None:
        """Store a market-data readiness policy idempotently."""
        ...

    def get(
        self,
        policy_id: MarketDataReadinessPolicyId,
    ) -> MarketDataReadinessPolicy | None:
        """Return a market-data readiness policy by ID."""
        ...

    def list_policies(self) -> tuple[MarketDataReadinessPolicy, ...]:
        """Return all policies in deterministic ID order."""
        ...


class ReplayMarketFrameLookupPort(Protocol):
    """Synchronous read-only lookup over a replay market-frame timeline."""

    @property
    def authority(self) -> ReplayMarketFrameLookupAuthority:
        """Return the deterministic replay market frame lookup authority."""
        ...

    @property
    def descriptor(self) -> ReplayMarketFrameLookupDescriptor:
        """Return the compact replay market frame lookup descriptor."""
        ...

    def lookup(
        self,
        context: ReplayDispatchContext,
        event: ReplayTimelineEvent,
    ) -> ReplayMarketFrameLookupResult:
        """Lookup the market frame for one exact replay event."""
        ...
