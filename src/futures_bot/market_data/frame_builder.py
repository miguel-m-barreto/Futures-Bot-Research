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
    observation_stream_key,
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

    selected_observations = _latest_observations(
        frame_instrument,
        frame_as_of,
        revalidated_observations,
    )
    selected_health = _latest_health(frame_instrument, frame_as_of, revalidated_health)
    ordered_observations = tuple(sorted(selected_observations, key=observation_stream_key))
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


def _latest_observations(
    frame_instrument: InstrumentSymbol,
    as_of: datetime,
    observations: tuple[NormalizedMarketObservation, ...],
) -> tuple[NormalizedMarketObservation, ...]:
    selected: dict[tuple[str, str, str], NormalizedMarketObservation] = {}
    for observation in observations:
        if observation.instrument.logical_instrument != frame_instrument:
            raise ValueError("observation logical instrument differs from frame instrument")
        if observation.provenance.received_at > as_of:
            raise ValueError("observation contains future information")
        key = observation_stream_key(observation)
        current = selected.get(key)
        if current is None:
            selected[key] = observation
            continue
        comparison = _compare_observations(observation, current)
        if comparison > 0:
            selected[key] = observation
    return tuple(selected.values())


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



def _compare_observations(
    candidate: NormalizedMarketObservation,
    current: NormalizedMarketObservation,
) -> int:
    if candidate.observation_id == current.observation_id:
        return 0

    candidate_provenance = candidate.provenance
    current_provenance = current.provenance
    same_session = (
        candidate_provenance.connection_id == current_provenance.connection_id
        and candidate_provenance.reconnect_generation
        == current_provenance.reconnect_generation
    )
    if same_session:
        candidate_sequence = candidate_provenance.source_sequence
        current_sequence = current_provenance.source_sequence
        if candidate_sequence is not None and current_sequence is not None:
            if candidate_sequence > current_sequence:
                return 1
            if candidate_sequence < current_sequence:
                return -1
            raise ValueError("ambiguous latest observation for equal source sequence")
        if candidate_sequence is not None or current_sequence is not None:
            raise ValueError("ambiguous latest observation with inconsistent sequence availability")
        return _compare_unsequenced_same_session(candidate, current)

    if candidate_provenance.received_at > current_provenance.received_at:
        return 1
    if candidate_provenance.received_at < current_provenance.received_at:
        return -1
    raise ValueError("ambiguous latest observation across incomparable sessions")


def _compare_unsequenced_same_session(
    candidate: NormalizedMarketObservation,
    current: NormalizedMarketObservation,
) -> int:
    candidate_provenance = candidate.provenance
    current_provenance = current.provenance
    if candidate_provenance.received_at > current_provenance.received_at:
        return 1
    if candidate_provenance.received_at < current_provenance.received_at:
        return -1
    if candidate_provenance.received_monotonic_ns > current_provenance.received_monotonic_ns:
        return 1
    if candidate_provenance.received_monotonic_ns < current_provenance.received_monotonic_ns:
        return -1
    raise ValueError("ambiguous latest observation for equal same-session ordering position")
