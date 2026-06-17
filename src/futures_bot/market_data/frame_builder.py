from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from futures_bot.domain.instruments import InstrumentSymbol, normalize_instrument_symbol
from futures_bot.domain.market_data import (
    CrossVenueMarketFrame,
    MarketSourceHealthSnapshot,
    NormalizedMarketObservation,
    build_market_frame_id,
    health_scope_key,
    select_latest_market_observations,
    validate_market_frame_authority_consistency,
)
from futures_bot.domain.time import ensure_aware_utc


def build_cross_venue_market_frame(
    *,
    logical_instrument: InstrumentSymbol | str | Mapping[str, object],
    as_of: datetime,
    observations: tuple[NormalizedMarketObservation, ...],
    source_health: tuple[MarketSourceHealthSnapshot, ...],
) -> CrossVenueMarketFrame:
    frame_instrument = normalize_instrument_symbol(logical_instrument)
    frame_as_of = ensure_aware_utc(as_of)
    revalidated_observations = tuple(
        NormalizedMarketObservation.model_validate(observation.model_dump())
        if isinstance(observation, NormalizedMarketObservation)
        else NormalizedMarketObservation.model_validate(observation)
        for observation in observations
    )
    revalidated_health = tuple(
        MarketSourceHealthSnapshot.model_validate(snapshot.model_dump())
        if isinstance(snapshot, MarketSourceHealthSnapshot)
        else MarketSourceHealthSnapshot.model_validate(snapshot)
        for snapshot in source_health
    )

    validate_market_frame_authority_consistency(
        observations=revalidated_observations,
        source_health=revalidated_health,
    )

    ordered_observations = select_latest_market_observations(
        logical_instrument=frame_instrument,
        as_of=frame_as_of,
        observations=revalidated_observations,
    )
    selected_health = _latest_health(frame_instrument, frame_as_of, revalidated_health)
    ordered_health = tuple(sorted(selected_health, key=health_scope_key))
    frame_id = build_market_frame_id(
        logical_instrument=frame_instrument,
        as_of=frame_as_of,
        observations=ordered_observations,
        source_health=ordered_health,
    )
    return CrossVenueMarketFrame(
        frame_id=frame_id,
        logical_instrument=frame_instrument,
        as_of=frame_as_of,
        observations=ordered_observations,
        source_health=ordered_health,
    )


def _latest_health(
    frame_instrument: InstrumentSymbol,
    as_of: datetime,
    source_health: tuple[MarketSourceHealthSnapshot, ...],
) -> tuple[MarketSourceHealthSnapshot, ...]:
    selected: dict[tuple[str, str, str, str, str], MarketSourceHealthSnapshot] = {}
    for snapshot in source_health:
        if (
            snapshot.instrument is not None
            and snapshot.instrument.logical_instrument != frame_instrument
        ):
            raise ValueError("health snapshot logical instrument differs from frame instrument")
        if snapshot.evaluated_at > as_of:
            raise ValueError("health snapshot contains future information")
        key = health_scope_key(snapshot)
        current = selected.get(key)
        if current is None:
            selected[key] = snapshot
            continue
        if snapshot.evaluated_at > current.evaluated_at:
            selected[key] = snapshot
        elif (
            snapshot.evaluated_at == current.evaluated_at
            and snapshot.health_snapshot_id != current.health_snapshot_id
        ):
            raise ValueError("ambiguous latest health snapshot for scope key")
    return tuple(selected.values())
