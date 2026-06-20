from __future__ import annotations

import hashlib

from futures_bot.domain.ids import StitchedStateSliceId
from futures_bot.domain.live_state import (
    HistoricalStateSlice,
    LiveStateFreshnessPolicy,
    LiveTailSlice,
    StitchedStateSlice,
    StitchFailureReason,
    StreamEventEnvelope,
    event_identity_matches,
)


class DeterministicStateStitcher:
    """Stitch DB history and live tail without hiding gaps or stale state."""

    def stitch(
        self,
        historical: HistoricalStateSlice,
        live_tail: LiveTailSlice | None,
        policy: LiveStateFreshnessPolicy,
    ) -> StitchedStateSlice:
        if live_tail is not None and (
            live_tail.stream_id != historical.stream_id
            or live_tail.partition_id != historical.partition_id
        ):
            raise ValueError(StitchFailureReason.STREAM_PARTITION_MISMATCH)

        events, has_gap = _merge_events(historical, live_tail)
        reason = _reason(historical, live_tail, policy, has_gap)
        tradable = reason is None
        is_complete = reason is None or reason not in {
            StitchFailureReason.LIVE_HISTORY_GAP,
            StitchFailureReason.INCOMPLETE_HISTORY,
        }
        is_gap_free = historical.is_gap_free and not has_gap
        if live_tail is not None:
            is_gap_free = is_gap_free and live_tail.freshness.gap_free

        return StitchedStateSlice(
            slice_id=_stitched_slice_id(historical, live_tail, events),
            stream_id=historical.stream_id,
            partition_id=historical.partition_id,
            historical=historical,
            live_tail=live_tail,
            events=events,
            from_offset=_from_offset(historical, live_tail, events),
            to_offset=_to_offset(historical, live_tail, events),
            is_complete=is_complete and is_gap_free,
            is_gap_free=is_gap_free,
            tradable=tradable,
            reason=reason,
        )


def _merge_events(
    historical: HistoricalStateSlice,
    live_tail: LiveTailSlice | None,
) -> tuple[tuple[StreamEventEnvelope, ...], bool]:
    merged = list(historical.events)
    if live_tail is None or not live_tail.events:
        return tuple(merged), False
    boundary = _historical_continuity_boundary(historical)
    has_gap = live_tail.from_offset > boundary + 1
    historical_by_offset = {
        event.stream_position.offset: event for event in historical.events
    }
    for tail_event in live_tail.events:
        offset = tail_event.stream_position.offset
        if offset <= boundary:
            historical_event = historical_by_offset.get(offset)
            if historical_event is None or not event_identity_matches(
                historical_event,
                tail_event,
            ):
                raise ValueError(StitchFailureReason.INVALID_OVERLAP)
            continue
        merged.append(tail_event)
    return tuple(merged), has_gap


def _reason(
    historical: HistoricalStateSlice,
    live_tail: LiveTailSlice | None,
    policy: LiveStateFreshnessPolicy,
    has_gap: bool,
) -> StitchFailureReason | None:
    reason: StitchFailureReason | None = None
    if not historical.is_gap_free:
        reason = StitchFailureReason.INCOMPLETE_HISTORY
    elif has_gap:
        reason = StitchFailureReason.LIVE_HISTORY_GAP
    elif not historical.events and live_tail is None:
        reason = StitchFailureReason.INCOMPLETE_HISTORY
    elif live_tail is not None:
        freshness = live_tail.freshness
        if freshness.staleness_ms > policy.max_staleness_ms:
            reason = StitchFailureReason.STALE_LIVE_STATE
        elif freshness.is_speculative and not policy.allow_speculative:
            reason = StitchFailureReason.SPECULATIVE_NOT_ALLOWED
        elif not freshness.is_tradable_for_policy(
            max_staleness_ms=policy.max_staleness_ms,
            allow_speculative=policy.allow_speculative,
            require_gap_free=policy.require_gap_free,
            require_complete=policy.require_complete,
            minimum_durability_status=policy.minimum_durability_status,
        ):
            reason = StitchFailureReason.INCOMPLETE_HISTORY
    return reason


def _historical_continuity_boundary(historical: HistoricalStateSlice) -> int:
    if historical.events:
        return historical.to_offset
    return historical.persisted_until_position.offset


def _stitched_slice_id(
    historical: HistoricalStateSlice,
    live_tail: LiveTailSlice | None,
    events: tuple[StreamEventEnvelope, ...],
) -> StitchedStateSliceId:
    seed_parts = [
        str(historical.slice_id),
        str(live_tail.slice_id) if live_tail is not None else "no-live-tail",
    ]
    seed_parts.extend(str(event.event_id) for event in events)
    digest = hashlib.sha256("|".join(seed_parts).encode("utf-8")).hexdigest()
    return StitchedStateSliceId(value=f"stitched-state:{digest}")


def _from_offset(
    historical: HistoricalStateSlice,
    live_tail: LiveTailSlice | None,
    events: tuple[StreamEventEnvelope, ...],
) -> int:
    if events:
        return events[0].stream_position.offset
    if live_tail is not None and live_tail.events:
        return live_tail.from_offset
    return historical.from_offset


def _to_offset(
    historical: HistoricalStateSlice,
    live_tail: LiveTailSlice | None,
    events: tuple[StreamEventEnvelope, ...],
) -> int:
    if events:
        return events[-1].stream_position.offset
    if live_tail is not None and live_tail.events:
        return live_tail.to_offset
    return historical.to_offset
