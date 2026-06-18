from __future__ import annotations

from datetime import datetime
from typing import Protocol

from futures_bot.domain.instruments import InstrumentSymbol
from futures_bot.domain.market_data import (
    MarketSourceHealthSnapshot,
    NormalizedMarketObservation,
)
from futures_bot.domain.replay import ReplayDispatchContext, ReplayTimelineEvent
from futures_bot.domain.replay_market_data import (
    ReplayMarketFrameLookupAuthority,
    ReplayMarketFrameLookupDescriptor,
    ReplayMarketFrameLookupResult,
)


class MarketDataReadPort(Protocol):
    def observations_for_instrument(
        self,
        instrument: InstrumentSymbol,
        *,
        as_of: datetime,
    ) -> tuple[NormalizedMarketObservation, ...]:
        ...

    def source_health_for_instrument(
        self,
        instrument: InstrumentSymbol,
        *,
        as_of: datetime,
    ) -> tuple[MarketSourceHealthSnapshot, ...]:
        ...


class ReplayMarketFrameLookupPort(Protocol):
    """Synchronous read-only lookup for deterministic replay market frames."""

    @property
    def descriptor(self) -> ReplayMarketFrameLookupDescriptor:
        ...

    @property
    def authority(self) -> ReplayMarketFrameLookupAuthority:
        ...

    def lookup(
        self,
        context: ReplayDispatchContext,
        event: ReplayTimelineEvent,
    ) -> ReplayMarketFrameLookupResult:
        ...
