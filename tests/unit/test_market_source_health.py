from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from futures_bot.domain.ids import MarketDataSourceId, VenueInstrumentId
from futures_bot.domain.instruments import VenueId
from futures_bot.domain.market_data import (
    MarketDataSourceDescriptor,
    MarketDataSourceKind,
    MarketObservationKind,
    MarketSourceHealthSnapshot,
    MarketSourceHealthState,
    MarketSourceIssueKind,
    MarketTransportKind,
    VenueInstrumentRef,
    VenueMarketKind,
    build_market_health_snapshot_id,
    build_market_source_health_snapshot,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def source(
    source_id: str = "BINANCE_SPOT_WS_PRIMARY",
    *,
    venue: str | None = "BINANCE",
    kind: MarketDataSourceKind = MarketDataSourceKind.DIRECT_VENUE,
) -> MarketDataSourceDescriptor:
    return MarketDataSourceDescriptor(
        source_id=MarketDataSourceId(source_id),
        source_kind=kind,
        provider="binance",
        transport=MarketTransportKind.WEBSOCKET,
        venue=None if venue is None else VenueId(value=venue),
        source_version="v1",
    )


def instrument(
    instrument_id: str = "binance-spot-btcusdt",
    *,
    venue: str = "BINANCE",
) -> VenueInstrumentRef:
    return VenueInstrumentRef(
        venue_instrument_id=VenueInstrumentId(instrument_id),
        venue=VenueId(value=venue),
        raw_symbol="BTCUSDT",
        logical_instrument="BTC/USDT",
        market_kind=VenueMarketKind.SPOT,
        metadata_version="2026-01",
    )


def health(  # noqa: PLR0913
    *,
    state: MarketSourceHealthState = MarketSourceHealthState.LIVE,
    issues: tuple[MarketSourceIssueKind, ...] = (),
    evaluated_at: datetime = NOW,
    last_received_at: datetime | None = NOW,
    last_source_event_time: datetime | None = NOW,
    last_sequence: int | None = 10,
    instrument_ref: VenueInstrumentRef | None = None,
    observation_kind: MarketObservationKind | None = None,
    source_descriptor: MarketDataSourceDescriptor | None = None,
) -> MarketSourceHealthSnapshot:
    return build_market_source_health_snapshot(
        source=source_descriptor if source_descriptor is not None else source(),
        instrument=instrument_ref,
        observation_kind=observation_kind,
        state=state,
        evaluated_at=evaluated_at,
        last_received_at=last_received_at,
        last_source_event_time=last_source_event_time,
        last_sequence=last_sequence,
        reconnect_generation=0,
        consecutive_failures=0,
        issues=issues,
    )


@pytest.mark.parametrize(
    ("state", "issues", "last_received_at"),
    [
        (MarketSourceHealthState.LIVE, (), NOW),
        (MarketSourceHealthState.DEGRADED, (MarketSourceIssueKind.CLOCK_SKEW,), NOW),
        (MarketSourceHealthState.STALE, (MarketSourceIssueKind.STALE_DATA,), NOW),
        (
            MarketSourceHealthState.GAP_DETECTED,
            (MarketSourceIssueKind.SEQUENCE_GAP,),
            NOW,
        ),
        (
            MarketSourceHealthState.RECONNECTING,
            (MarketSourceIssueKind.RECONNECTING,),
            NOW,
        ),
        (
            MarketSourceHealthState.RECOVERING,
            (MarketSourceIssueKind.TRANSPORT_ERROR,),
            NOW,
        ),
        (
            MarketSourceHealthState.DISCONNECTED,
            (MarketSourceIssueKind.NO_DATA,),
            None,
        ),
        (
            MarketSourceHealthState.UNSUPPORTED,
            (MarketSourceIssueKind.UNSUPPORTED,),
            None,
        ),
    ],
)
def test_health_state_consistency_valid_cases(
    state: MarketSourceHealthState,
    issues: tuple[MarketSourceIssueKind, ...],
    last_received_at: datetime | None,
) -> None:
    snapshot = health(state=state, issues=issues, last_received_at=last_received_at)

    assert snapshot.state is state
    assert snapshot.issues == issues


@pytest.mark.parametrize(
    ("state", "issues", "last_received_at"),
    [
        (MarketSourceHealthState.LIVE, (), None),
        (MarketSourceHealthState.LIVE, (MarketSourceIssueKind.STALE_DATA,), NOW),
        (MarketSourceHealthState.LIVE, (MarketSourceIssueKind.RECONNECTING,), NOW),
        (MarketSourceHealthState.DEGRADED, (), NOW),
        (MarketSourceHealthState.DEGRADED, (MarketSourceIssueKind.UNSUPPORTED,), NOW),
        (MarketSourceHealthState.STALE, (), NOW),
        (MarketSourceHealthState.STALE, (MarketSourceIssueKind.STALE_DATA,), None),
        (MarketSourceHealthState.GAP_DETECTED, (), NOW),
        (MarketSourceHealthState.GAP_DETECTED, (MarketSourceIssueKind.SEQUENCE_GAP,), None),
        (MarketSourceHealthState.RECONNECTING, (), NOW),
        (MarketSourceHealthState.RECOVERING, (), NOW),
        (MarketSourceHealthState.RECOVERING, (MarketSourceIssueKind.NO_DATA,), NOW),
        (MarketSourceHealthState.DISCONNECTED, (), None),
        (MarketSourceHealthState.UNSUPPORTED, (), None),
        (
            MarketSourceHealthState.UNSUPPORTED,
            (MarketSourceIssueKind.CLOCK_SKEW, MarketSourceIssueKind.UNSUPPORTED),
            None,
        ),
    ],
)
def test_health_state_consistency_rejects_invalid_cases(
    state: MarketSourceHealthState,
    issues: tuple[MarketSourceIssueKind, ...],
    last_received_at: datetime | None,
) -> None:
    with pytest.raises((ValidationError, ValueError)):
        health(state=state, issues=issues, last_received_at=last_received_at)


def test_gap_detected_requires_sequence_context() -> None:
    with pytest.raises((ValidationError, ValueError)):
        health(
            state=MarketSourceHealthState.GAP_DETECTED,
            issues=(MarketSourceIssueKind.SEQUENCE_GAP,),
            last_sequence=None,
        )


def test_health_identity_round_trip_and_scope_distinctions() -> None:
    global_health = health()
    scoped_health = health(
        instrument_ref=instrument(),
        observation_kind=MarketObservationKind.TRADE,
    )

    assert global_health.health_snapshot_id != scoped_health.health_snapshot_id
    assert MarketSourceHealthSnapshot.model_validate(
        global_health.model_dump()
    ) == global_health
    assert build_market_health_snapshot_id(
        source=global_health.source,
        instrument=global_health.instrument,
        observation_kind=global_health.observation_kind,
        state=global_health.state,
        evaluated_at=global_health.evaluated_at,
        last_received_at=global_health.last_received_at,
        last_source_event_time=global_health.last_source_event_time,
        last_sequence=global_health.last_sequence,
        reconnect_generation=global_health.reconnect_generation,
        consecutive_failures=global_health.consecutive_failures,
        issues=global_health.issues,
    ) == global_health.health_snapshot_id


def test_health_issues_are_unique_and_canonical() -> None:
    with pytest.raises((ValidationError, ValueError)):
        health(
            state=MarketSourceHealthState.STALE,
            issues=(MarketSourceIssueKind.STALE_DATA, MarketSourceIssueKind.STALE_DATA),
        )
    with pytest.raises((ValidationError, ValueError)):
        health(
            state=MarketSourceHealthState.STALE,
            issues=(MarketSourceIssueKind.STALE_DATA, MarketSourceIssueKind.CLOCK_SKEW),
        )


def test_health_rejects_future_last_received_but_allows_source_clock_skew() -> None:
    with pytest.raises((ValidationError, ValueError)):
        health(last_received_at=NOW + timedelta(seconds=1))

    skewed = health(last_source_event_time=NOW + timedelta(hours=1))
    assert skewed.last_source_event_time == NOW + timedelta(hours=1)


def test_health_rejects_wrong_id_and_nested_model_copy_tampering() -> None:
    snapshot = health()
    payload = snapshot.model_dump()
    payload["health_snapshot_id"] = {"value": "market-health:" + "0" * 64}
    with pytest.raises(ValidationError):
        MarketSourceHealthSnapshot.model_validate(payload)

    tampered_source = snapshot.source.model_copy(update={"provider": " binance"})
    with pytest.raises(ValidationError):
        MarketSourceHealthSnapshot.model_validate(
            snapshot.model_copy(update={"source": tampered_source}).model_dump()
        )


def test_instrument_scoped_health_enforces_direct_venue_consistency() -> None:
    with pytest.raises((ValidationError, ValueError)):
        health(
            source_descriptor=source(venue="BINANCE"),
            instrument_ref=instrument("bybit-spot-btcusdt", venue="BYBIT"),
        )

    accepted = health(
        source_descriptor=source(venue="BINANCE"),
        instrument_ref=instrument("binance-spot-btcusdt", venue="BINANCE"),
    )
    assert accepted.instrument is not None

    aggregator = MarketDataSourceDescriptor(
        source_id=MarketDataSourceId("AGGREGATOR_REFERENCE"),
        source_kind=MarketDataSourceKind.AGGREGATOR,
        provider="aggregator",
        transport=MarketTransportKind.REST,
        venue=None,
        source_version="v1",
    )
    accepted_aggregator = health(
        source_descriptor=aggregator,
        instrument_ref=instrument("bybit-spot-btcusdt", venue="BYBIT"),
    )
    assert accepted_aggregator.source.source_kind is MarketDataSourceKind.AGGREGATOR


# ---------------------------------------------------------------------------
# Full health compatibility matrix — valid combinations
# ---------------------------------------------------------------------------

_I = MarketSourceIssueKind
_S = MarketSourceHealthState


@pytest.mark.parametrize(
    ("state", "issues", "last_received_at"),
    [
        # LIVE: no issues, last_received_at present
        (_S.LIVE, (), NOW),
        # DEGRADED: impaired but usable; allowed soft issues only
        (_S.DEGRADED, (_I.CLOCK_SKEW,), NOW),
        (_S.DEGRADED, (_I.RATE_LIMITED,), NOW),
        (_S.DEGRADED, (_I.OUT_OF_ORDER,), NOW),
        (_S.DEGRADED, (_I.INVALID_PAYLOAD,), NOW),
        (_S.DEGRADED, (_I.CLOCK_SKEW, _I.OUT_OF_ORDER), NOW),
        # STALE: STALE_DATA required; soft modifiers allowed
        (_S.STALE, (_I.STALE_DATA,), NOW),
        (_S.STALE, (_I.CLOCK_SKEW, _I.STALE_DATA), NOW),
        (_S.STALE, (_I.RATE_LIMITED, _I.STALE_DATA), NOW),
        # GAP_DETECTED: SEQUENCE_GAP required; OUT_OF_ORDER allowed alongside
        (_S.GAP_DETECTED, (_I.SEQUENCE_GAP,), NOW),
        (_S.GAP_DETECTED, (_I.OUT_OF_ORDER, _I.SEQUENCE_GAP), NOW),
        (_S.GAP_DETECTED, (_I.CLOCK_SKEW, _I.SEQUENCE_GAP), NOW),
        # RECONNECTING: RECONNECTING required; transport context allowed
        (_S.RECONNECTING, (_I.RECONNECTING,), NOW),
        (_S.RECONNECTING, (_I.RECONNECTING, _I.TRANSPORT_ERROR), NOW),
        (_S.RECONNECTING, (_I.NO_DATA, _I.RECONNECTING), NOW),
        (_S.RECONNECTING, (_I.RATE_LIMITED, _I.RECONNECTING), NOW),
        # RECOVERING: any recovery-related issue; no last_received_at requirement
        (_S.RECOVERING, (_I.TRANSPORT_ERROR,), NOW),
        (_S.RECOVERING, (_I.SEQUENCE_GAP,), NOW),
        (_S.RECOVERING, (_I.STALE_DATA,), NOW),
        (_S.RECOVERING, (_I.RECONNECTING,), NOW),
        (_S.RECOVERING, (_I.CLOCK_SKEW, _I.SEQUENCE_GAP), NOW),
        # DISCONNECTED: NO_DATA or TRANSPORT_ERROR required; nothing else
        (_S.DISCONNECTED, (_I.NO_DATA,), None),
        (_S.DISCONNECTED, (_I.TRANSPORT_ERROR,), None),
        (_S.DISCONNECTED, (_I.NO_DATA, _I.TRANSPORT_ERROR), None),
        # UNSUPPORTED: exactly UNSUPPORTED only
        (_S.UNSUPPORTED, (_I.UNSUPPORTED,), None),
    ],
)
def test_health_compatibility_matrix_valid(
    state: MarketSourceHealthState,
    issues: tuple[MarketSourceIssueKind, ...],
    last_received_at: datetime | None,
) -> None:
    snapshot = health(state=state, issues=issues, last_received_at=last_received_at)
    assert snapshot.state is state
    assert snapshot.issues == issues


# ---------------------------------------------------------------------------
# Full health compatibility matrix — invalid combinations
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("state", "issues", "last_received_at"),
    [
        # LIVE: any issue is invalid
        (_S.LIVE, (_I.CLOCK_SKEW,), NOW),
        (_S.LIVE, (_I.STALE_DATA,), NOW),
        (_S.LIVE, (_I.OUT_OF_ORDER,), NOW),
        # DEGRADED: forbidden stronger-state issues
        (_S.DEGRADED, (_I.STALE_DATA,), NOW),
        (_S.DEGRADED, (_I.SEQUENCE_GAP,), NOW),
        (_S.DEGRADED, (_I.RECONNECTING,), NOW),
        (_S.DEGRADED, (_I.TRANSPORT_ERROR,), NOW),
        (_S.DEGRADED, (_I.NO_DATA,), NOW),
        (_S.DEGRADED, (_I.UNSUPPORTED,), NOW),
        # DEGRADED: last_received_at required
        (_S.DEGRADED, (_I.CLOCK_SKEW,), None),
        # STALE: must have STALE_DATA
        (_S.STALE, (_I.CLOCK_SKEW,), NOW),
        # STALE: forbidden stronger-state issues
        (_S.STALE, (_I.RECONNECTING, _I.STALE_DATA), NOW),
        (_S.STALE, (_I.SEQUENCE_GAP, _I.STALE_DATA), NOW),
        (_S.STALE, (_I.NO_DATA, _I.STALE_DATA), NOW),
        (_S.STALE, (_I.TRANSPORT_ERROR,), NOW),
        # GAP_DETECTED: SEQUENCE_GAP required
        (_S.GAP_DETECTED, (_I.CLOCK_SKEW,), NOW),
        (_S.GAP_DETECTED, (_I.OUT_OF_ORDER,), NOW),
        # GAP_DETECTED: forbidden issues
        (_S.GAP_DETECTED, (_I.SEQUENCE_GAP, _I.STALE_DATA), NOW),
        (_S.GAP_DETECTED, (_I.RECONNECTING, _I.SEQUENCE_GAP), NOW),
        (_S.GAP_DETECTED, (_I.NO_DATA, _I.SEQUENCE_GAP), NOW),
        # GAP_DETECTED: last_received_at and last_sequence required (tested via last_sequence=None)
        # RECONNECTING: RECONNECTING required
        (_S.RECONNECTING, (_I.CLOCK_SKEW,), NOW),
        (_S.RECONNECTING, (_I.STALE_DATA,), NOW),
        # RECONNECTING: forbidden issues when RECONNECTING is present
        (_S.RECONNECTING, (_I.RECONNECTING, _I.STALE_DATA), NOW),
        (_S.RECONNECTING, (_I.RECONNECTING, _I.SEQUENCE_GAP), NOW),
        (_S.RECONNECTING, (_I.CLOCK_SKEW, _I.RECONNECTING), NOW),
        (_S.RECONNECTING, (_I.INVALID_PAYLOAD, _I.RECONNECTING), NOW),
        # RECOVERING: must have at least one issue
        (_S.RECOVERING, (), NOW),
        # RECOVERING: NO_DATA and UNSUPPORTED are forbidden
        (_S.RECOVERING, (_I.NO_DATA,), NOW),
        (_S.RECOVERING, (_I.UNSUPPORTED,), NOW),
        # DISCONNECTED: outage issue required
        (_S.DISCONNECTED, (), None),
        # DISCONNECTED: only NO_DATA and TRANSPORT_ERROR allowed
        (_S.DISCONNECTED, (_I.CLOCK_SKEW, _I.NO_DATA), None),
        (_S.DISCONNECTED, (_I.CLOCK_SKEW,), None),
        (_S.DISCONNECTED, (_I.SEQUENCE_GAP,), None),
        (_S.DISCONNECTED, (_I.STALE_DATA,), None),
        # UNSUPPORTED: must have exactly UNSUPPORTED
        (_S.UNSUPPORTED, (), None),
        (_S.UNSUPPORTED, (_I.CLOCK_SKEW, _I.UNSUPPORTED), None),
        (_S.UNSUPPORTED, (_I.RECONNECTING, _I.UNSUPPORTED), None),
    ],
)
def test_health_compatibility_matrix_invalid(
    state: MarketSourceHealthState,
    issues: tuple[MarketSourceIssueKind, ...],
    last_received_at: datetime | None,
) -> None:
    with pytest.raises((ValidationError, ValueError)):
        health(state=state, issues=issues, last_received_at=last_received_at)


def test_gap_detected_without_last_sequence_rejected() -> None:
    with pytest.raises((ValidationError, ValueError)):
        health(
            state=_S.GAP_DETECTED,
            issues=(_I.SEQUENCE_GAP,),
            last_received_at=NOW,
            last_sequence=None,
        )


def test_degraded_without_last_received_at_rejected() -> None:
    with pytest.raises((ValidationError, ValueError)):
        health(
            state=_S.DEGRADED,
            issues=(_I.CLOCK_SKEW,),
            last_received_at=None,
        )
