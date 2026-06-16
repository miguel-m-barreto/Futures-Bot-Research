from __future__ import annotations

from datetime import datetime
from typing import Protocol

from futures_bot.domain.instruments import InstrumentSymbol
from futures_bot.domain.market_data import (
    MarketSourceHealthSnapshot,
    NormalizedMarketObservation,
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
