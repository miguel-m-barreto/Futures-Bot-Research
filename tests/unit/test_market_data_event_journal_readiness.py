from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from futures_bot.domain.event_journal import (
    EventJournalCheckpoint,
    EventJournalReadinessPolicy,
    EventJournalReadinessReason,
    EventJournalRecordKind,
    EventJournalSourceHealth,
    EventJournalSourceKind,
    EventJournalSourceTrust,
    EventJournalStreamId,
)
from futures_bot.domain.ids import MarketDataReadinessPolicyId
from futures_bot.domain.market_data import (
    MarketDataCompatibility,
    MarketDataContinuityStatus,
    MarketDataObservationKind,
    MarketDataObservationSnapshot,
    MarketDataReadinessDecision,
    MarketDataReadinessReason,
    MarketDataSourceHealth,
    MarketDataSourceKind,
    MarketDataSourceTrust,
    market_data_observation_event_journal_stream_id,
    market_data_snapshot_to_event_journal_record,
)
from futures_bot.event_journal.policies import evaluate_event_journal_readiness

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _snapshot(**overrides: object) -> MarketDataObservationSnapshot:
    values = {
        "venue_id": "kucoin",
        "instrument_id": "BTCUSDTM",
        "observation_kind": MarketDataObservationKind.BEST_BID_ASK,
        "best_bid_price": Decimal("100"),
        "best_ask_price": Decimal("101"),
        "depth_reference_asset": "USDT",
        "depth_notional": Decimal("1000"),
        "spread_bps": Decimal("10"),
        "sequence_number": 101,
        "previous_sequence_number": 100,
        "continuity_status": MarketDataContinuityStatus.CONTINUOUS,
        "observed_at": NOW - timedelta(seconds=1),
        "captured_at": NOW - timedelta(seconds=1),
        "source_kind": MarketDataSourceKind.VENUE_PUBLIC_MARKET_DATA,
        "source_trust": MarketDataSourceTrust.OFFICIAL,
        "source_health": MarketDataSourceHealth.HEALTHY,
        "source_record_id": "source-record-1",
        "metadata": {},
    }
    values.update(overrides)
    return MarketDataObservationSnapshot(**values)


def _policy(**overrides: object) -> EventJournalReadinessPolicy:
    values = {
        "max_record_age": 5_000,
        "require_source_record": True,
        "allowed_source_kinds": (EventJournalSourceKind.SYSTEM_GENERATED_RECORD,),
        "allowed_source_trust": (EventJournalSourceTrust.SYSTEM_GENERATED,),
        "allowed_source_health": (EventJournalSourceHealth.HEALTHY,),
        "allowed_record_kinds": (EventJournalRecordKind.MARKET_DATA_OBSERVATION,),
        "allowed_continuity_statuses": ("CONTINUOUS",),
        "require_sequence": True,
        "require_previous_sequence": True,
        "require_contiguous_sequence": True,
        "require_checkpoint": True,
        "require_payload_hash": True,
        "require_idempotency_key": True,
        "metadata": {},
    }
    values.update(overrides)
    return EventJournalReadinessPolicy(**values)


def _checkpoint(stream_id: EventJournalStreamId) -> EventJournalCheckpoint:
    return EventJournalCheckpoint(
        stream_id=stream_id,
        last_sequence_number=100,
        checkpointed_at=NOW - timedelta(seconds=1),
        source_kind=EventJournalSourceKind.SYSTEM_GENERATED_RECORD,
        source_trust=EventJournalSourceTrust.SYSTEM_GENERATED,
        source_health=EventJournalSourceHealth.HEALTHY,
        source_record_id="checkpoint-source-1",
        metadata={},
    )


def test_market_data_snapshot_to_journal_record_is_deterministic() -> None:
    snapshot = _snapshot()
    first = market_data_snapshot_to_event_journal_record(snapshot)
    second = market_data_snapshot_to_event_journal_record(_snapshot())

    assert first == second
    assert first.record_kind is EventJournalRecordKind.MARKET_DATA_OBSERVATION
    assert first.payload_type == "MarketDataObservationSnapshot"
    assert first.occurred_at == snapshot.observed_at
    assert first.recorded_at == snapshot.captured_at
    assert first.idempotency_key == str(snapshot.snapshot_id)


def test_different_snapshot_identity_changes_journal_record() -> None:
    base = market_data_snapshot_to_event_journal_record(_snapshot())
    changed = market_data_snapshot_to_event_journal_record(
        _snapshot(best_bid_price=Decimal("99")),
    )

    assert base.record_id != changed.record_id
    assert base.payload_hash != changed.payload_hash


def test_journal_stream_scope_includes_venue_instrument_and_observation_kind() -> None:
    base = _snapshot()
    wrong_venue = _snapshot(venue_id="binance")
    wrong_instrument = _snapshot(instrument_id="ETHUSDTM")
    wrong_kind = _snapshot(observation_kind=MarketDataObservationKind.MARK_PRICE)

    assert market_data_observation_event_journal_stream_id(base) != (
        market_data_observation_event_journal_stream_id(wrong_venue)
    )
    assert market_data_observation_event_journal_stream_id(base) != (
        market_data_observation_event_journal_stream_id(wrong_instrument)
    )
    assert market_data_observation_event_journal_stream_id(base) != (
        market_data_observation_event_journal_stream_id(wrong_kind)
    )


def test_wrong_stream_rejects_market_data_journal_readiness() -> None:
    snapshot = _snapshot()
    record = market_data_snapshot_to_event_journal_record(snapshot)
    wrong_stream = EventJournalStreamId("event-journal-stream:" + "f" * 64)

    decision = evaluate_event_journal_readiness(
        policy=_policy(),
        checked_at=NOW,
        record=record,
        checkpoint=_checkpoint(record.stream_id),
        stream_id=wrong_stream,
        record_kind=EventJournalRecordKind.MARKET_DATA_OBSERVATION,
        expected_payload_hash=record.payload_hash,
    )

    assert decision.reason is EventJournalReadinessReason.STREAM_ID_MISMATCH


def test_market_data_readiness_decision_cannot_replace_event_journal_record() -> None:
    policy = _policy()
    market_data_decision = MarketDataReadinessDecision(
        policy_id=MarketDataReadinessPolicyId("market-data-policy:" + "a" * 64),
        venue_id="kucoin",
        instrument_id="BTCUSDTM",
        observation_kind=MarketDataObservationKind.BEST_BID_ASK,
        ready=True,
        reason=MarketDataReadinessReason.READY,
        compatibility=MarketDataCompatibility.DIRECT_MATCH,
        checked_at=NOW,
        details={},
    )

    decision = evaluate_event_journal_readiness(
        policy=policy,
        checked_at=NOW,
        record=cast(Any, market_data_decision),
    )

    assert decision.reason is EventJournalReadinessReason.RECORD_MISSING
