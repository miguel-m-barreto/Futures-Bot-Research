from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from futures_bot.domain.assets import AssetAmount, AssetSymbol, StableCollateralAsset
from futures_bot.domain.decisions import (
    DecisionIntent,
    DecisionSourceKind,
    NoTradeDecision,
    NoTradeReasonKind,
    ProposedAction,
    TradeSide,
)
from futures_bot.domain.ids import BotId
from futures_bot.domain.replay import (
    ReplayEventOutputRecord,
    ReplayInputKind,
    build_replay_event_dispatch_receipt_id,
    build_replay_event_output_record_id,
)
from futures_bot.domain.replay_decisions import (
    ReplayDecisionOutputEnvelope,
    ReplayDecisionOutputKind,
    ReplayDecisionStackDescriptor,
    build_replay_decision_intent_id,
    build_replay_decision_output_proposal,
    build_replay_decision_stack_fingerprint,
    decode_replay_decision_output_record,
)


def _utc() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _descriptor() -> ReplayDecisionStackDescriptor:
    return ReplayDecisionStackDescriptor(
        stack_id="stack-1",
        stack_version="1",
        bot_id=BotId("bot-1"),
        source_kind=DecisionSourceKind.ML_MODEL,
        supported_event_kinds=(ReplayInputKind.MARK_PRICE,),
    )


def _decision_id(
    descriptor: ReplayDecisionStackDescriptor,
    decision_index: int,
) -> object:
    return build_replay_decision_intent_id(
        run_id="run-1",
        event_order_index=0,
        event_id="event-1",
        decision_stack_fingerprint=build_replay_decision_stack_fingerprint(descriptor),
        decision_index=decision_index,
    )


def _intent(descriptor: ReplayDecisionStackDescriptor) -> DecisionIntent:
    return DecisionIntent(
        decision_intent_id=_decision_id(descriptor, 0),
        bot_id=descriptor.bot_id,
        instrument="BTCUSDT",
        side=TradeSide.LONG,
        proposed_action=ProposedAction.OPEN_POSITION,
        source_kind=descriptor.source_kind,
        source_id=descriptor.stack_id,
        created_at=_utc(),
        proposed_margin=AssetAmount(asset="USDT", amount="100.0000"),
        proposed_leverage="3",
        confidence="0.25",
    )


def _no_trade(descriptor: ReplayDecisionStackDescriptor) -> NoTradeDecision:
    return NoTradeDecision(
        decision_intent_id=_decision_id(descriptor, 0),
        bot_id=descriptor.bot_id,
        instrument="BTC/USDT",
        source_kind=descriptor.source_kind,
        source_id=descriptor.stack_id,
        created_at=_utc(),
        reasons=(NoTradeReasonKind.MARKET_TOO_UNCERTAIN,),
        confidence="0.50",
    )


def _envelope(
    *,
    no_trade: bool = False,
) -> ReplayDecisionOutputEnvelope:
    descriptor = _descriptor()
    if no_trade:
        return ReplayDecisionOutputEnvelope(
            run_id="run-1",
            event_id="event-1",
            event_order_index=0,
            event_time=_utc(),
            event_kind=ReplayInputKind.MARK_PRICE,
            stack_descriptor=descriptor,
            decision_index=0,
            decision_kind=ReplayDecisionOutputKind.NO_TRADE_DECISION,
            no_trade_decision=_no_trade(descriptor),
        )
    return ReplayDecisionOutputEnvelope(
        run_id="run-1",
        event_id="event-1",
        event_order_index=0,
        event_time=_utc(),
        event_kind=ReplayInputKind.MARK_PRICE,
        stack_descriptor=descriptor,
        decision_index=0,
        decision_kind=ReplayDecisionOutputKind.DECISION_INTENT,
        decision_intent=_intent(descriptor),
    )


def _record(  # noqa: PLR0913 - explicit output record mismatch fixture
    envelope: ReplayDecisionOutputEnvelope,
    *,
    output_kind: str | None = None,
    handler_id: str | None = None,
    handler_version: str | None = None,
    handler_output_index: int | None = None,
    canonical_payload: str | None = None,
) -> ReplayEventOutputRecord:
    proposal = build_replay_decision_output_proposal(envelope)
    payload = canonical_payload or proposal.canonical_payload
    kind = output_kind or proposal.output_kind
    stack_fingerprint = build_replay_decision_stack_fingerprint(
        envelope.stack_descriptor
    )
    selected_handler_id = handler_id or stack_fingerprint
    selected_handler_version = handler_version or envelope.stack_descriptor.stack_version
    selected_index = (
        envelope.decision_index if handler_output_index is None else handler_output_index
    )
    payload_sha256 = hashlib.sha256(payload.encode()).hexdigest()
    return ReplayEventOutputRecord(
        output_record_id=build_replay_event_output_record_id(
            run_id=envelope.run_id,
            event_order_index=envelope.event_order_index,
            event_id=envelope.event_id,
            handler_id=selected_handler_id,
            handler_version=selected_handler_version,
            handler_output_index=selected_index,
            output_kind=kind,
            payload_sha256=payload_sha256,
        ),
        dispatch_receipt_id=build_replay_event_dispatch_receipt_id(
            envelope.run_id,
            envelope.event_order_index,
            envelope.event_id,
        ),
        run_id=envelope.run_id,
        manifest_id="manifest-1",
        replay_plan_id="plan-1",
        timeline_id="timeline-1",
        timeline_fingerprint_id="fp-1",
        dispatcher_fingerprint="replay-dispatcher:" + "0" * 64,
        event_id=envelope.event_id,
        event_order_index=envelope.event_order_index,
        event_time=envelope.event_time,
        event_kind=envelope.event_kind,
        handler_id=selected_handler_id,
        handler_version=selected_handler_version,
        handler_output_index=selected_index,
        output_kind=kind,
        canonical_payload=payload,
        payload_sha256=payload_sha256,
    )


@pytest.mark.parametrize("no_trade", [False, True])
def test_decision_output_round_trips(no_trade: bool) -> None:
    envelope = _envelope(no_trade=no_trade)
    record = _record(envelope)

    assert decode_replay_decision_output_record(record) == envelope


def test_canonical_payload_is_exact_and_decimal_values_are_strings() -> None:
    proposal = build_replay_decision_output_proposal(_envelope())
    parsed = json.loads(proposal.canonical_payload)

    assert proposal.canonical_payload == json.dumps(
        parsed,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert parsed["decision_intent"]["confidence"] == "0.25"
    assert parsed["decision_intent"]["proposed_leverage"] == "3"
    assert parsed["decision_intent"]["proposed_margin"]["amount"] == "100.0000"
    assert parsed["decision_intent"]["proposed_margin"]["asset"]["value"] == "USDT"
    assert parsed["decision_intent"]["instrument"]["value"] == "BTC/USDT"


def test_malformed_recognized_decision_output_raises() -> None:
    envelope = _envelope()
    payload = '{"schema_version":1}'
    record = _record(envelope, canonical_payload=payload)

    with pytest.raises(ValidationError):
        decode_replay_decision_output_record(record)


def test_decode_rejects_wrong_output_kind_and_record_mismatches() -> None:
    envelope = _envelope()
    with pytest.raises(ValueError, match="not a replay decision"):
        decode_replay_decision_output_record(_record(envelope, output_kind="audit"))
    with pytest.raises(ValueError, match="output_kind"):
        decode_replay_decision_output_record(
            _record(
                envelope,
                output_kind=ReplayDecisionOutputKind.NO_TRADE_DECISION.value,
            )
        )
    with pytest.raises(ValueError, match="handler_id"):
        decode_replay_decision_output_record(
            _record(envelope, handler_id="decision-stack:" + "1" * 64)
        )
    with pytest.raises(ValueError, match="handler_version"):
        decode_replay_decision_output_record(_record(envelope, handler_version="2"))
    with pytest.raises(ValueError, match="handler_output_index"):
        decode_replay_decision_output_record(_record(envelope, handler_output_index=1))


def test_decode_rejects_semantic_but_non_official_typed_encoding() -> None:
    envelope = _envelope()
    proposal = build_replay_decision_output_proposal(envelope)
    parsed = json.loads(proposal.canonical_payload)
    parsed["event_time"] = "2025-12-31T19:00:00-05:00"
    payload = json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    with pytest.raises(ValueError, match="canonical_payload"):
        decode_replay_decision_output_record(_record(envelope, canonical_payload=payload))


def test_decode_rejects_alternate_nested_decision_timestamp_encoding() -> None:
    envelope = _envelope()
    proposal = build_replay_decision_output_proposal(envelope)
    parsed = json.loads(proposal.canonical_payload)
    parsed["decision_intent"]["created_at"] = "2025-12-31T19:00:00-05:00"
    payload = json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    with pytest.raises(ValueError, match="canonical_payload"):
        decode_replay_decision_output_record(_record(envelope, canonical_payload=payload))


def test_external_instrument_spelling_converges_to_same_payload_and_decision_id() -> None:
    descriptor = _descriptor()
    first = _envelope()
    second_intent = DecisionIntent(
        decision_intent_id=_decision_id(descriptor, 0),
        bot_id=descriptor.bot_id,
        instrument="BTC/USDT",
        side=TradeSide.LONG,
        proposed_action=ProposedAction.OPEN_POSITION,
        source_kind=descriptor.source_kind,
        source_id=descriptor.stack_id,
        created_at=_utc(),
        proposed_margin=AssetAmount(asset="USDT", amount="100.0000"),
        proposed_leverage="3",
        confidence="0.25",
    )
    second = ReplayDecisionOutputEnvelope(
        run_id="run-1",
        event_id="event-1",
        event_order_index=0,
        event_time=_utc(),
        event_kind=ReplayInputKind.MARK_PRICE,
        stack_descriptor=descriptor,
        decision_index=0,
        decision_kind=ReplayDecisionOutputKind.DECISION_INTENT,
        decision_intent=second_intent,
    )

    assert first.decision_intent is not None
    assert second.decision_intent is not None
    assert first.decision_intent.decision_intent_id == second.decision_intent.decision_intent_id
    assert build_replay_decision_output_proposal(first) == (
        build_replay_decision_output_proposal(second)
    )


def test_decision_intent_margin_with_stable_collateral_round_trips() -> None:
    descriptor = _descriptor()
    intent = DecisionIntent(
        decision_intent_id=_decision_id(descriptor, 0),
        bot_id=descriptor.bot_id,
        instrument="BTCUSDT",
        side=TradeSide.LONG,
        proposed_action=ProposedAction.OPEN_POSITION,
        source_kind=descriptor.source_kind,
        source_id=descriptor.stack_id,
        created_at=_utc(),
        proposed_margin=AssetAmount(
            asset=StableCollateralAsset("USDT"),
            amount="100.0000",
        ),
        proposed_leverage="3",
        confidence="0.25",
    )
    envelope = ReplayDecisionOutputEnvelope(
        run_id="run-1",
        event_id="event-1",
        event_order_index=0,
        event_time=_utc(),
        event_kind=ReplayInputKind.MARK_PRICE,
        stack_descriptor=descriptor,
        decision_index=0,
        decision_kind=ReplayDecisionOutputKind.DECISION_INTENT,
        decision_intent=intent,
    )

    decoded = decode_replay_decision_output_record(_record(envelope))

    assert decoded == envelope
    assert decoded.decision_intent is not None
    assert decoded.decision_intent.proposed_margin == AssetAmount(
        asset="USDT",
        amount="100.0000",
    )


def test_decision_intent_proposed_margin_decimal_scale_preserved_through_codec() -> None:
    descriptor = _descriptor()
    intent = DecisionIntent(
        decision_intent_id=_decision_id(descriptor, 0),
        bot_id=descriptor.bot_id,
        instrument="BTCUSDT",
        side=TradeSide.LONG,
        proposed_action=ProposedAction.OPEN_POSITION,
        source_kind=descriptor.source_kind,
        source_id=descriptor.stack_id,
        created_at=_utc(),
        proposed_margin=AssetAmount(asset="USDT", amount="250.5000"),
    )
    envelope = ReplayDecisionOutputEnvelope(
        run_id="run-1",
        event_id="event-1",
        event_order_index=0,
        event_time=_utc(),
        event_kind=ReplayInputKind.MARK_PRICE,
        stack_descriptor=descriptor,
        decision_index=0,
        decision_kind=ReplayDecisionOutputKind.DECISION_INTENT,
        decision_intent=intent,
    )
    decoded = decode_replay_decision_output_record(_record(envelope))

    assert decoded.decision_intent is not None
    margin = decoded.decision_intent.proposed_margin
    assert margin is not None
    assert margin.amount == Decimal("250.5000")
    assert margin.amount.as_tuple().exponent == -4


def test_decision_intent_rejects_tampered_proposed_margin_in_codec_context() -> None:
    descriptor = _descriptor()
    bad_stable = StableCollateralAsset("USDT").model_copy(
        update={"symbol": AssetSymbol("USD")}
    )
    bad_amount = AssetAmount(asset="USDT", amount="100.0000").model_copy(
        update={"asset": bad_stable}
    )
    with pytest.raises(ValidationError):
        DecisionIntent(
            decision_intent_id=_decision_id(descriptor, 0),
            bot_id=descriptor.bot_id,
            instrument="BTCUSDT",
            side=TradeSide.LONG,
            proposed_action=ProposedAction.OPEN_POSITION,
            source_kind=descriptor.source_kind,
            source_id=descriptor.stack_id,
            created_at=_utc(),
            proposed_margin=bad_amount,
        )


def test_payload_hash_or_output_id_tampering_is_rejected_by_output_record() -> None:
    record = _record(_envelope())
    with pytest.raises(ValidationError, match="payload_sha256"):
        ReplayEventOutputRecord.model_validate(
            {**record.model_dump(), "payload_sha256": "0" * 64}
        )
    with pytest.raises(ValidationError, match="output_record_id"):
        ReplayEventOutputRecord.model_validate(
            {**record.model_dump(), "output_record_id": "replay-output:" + "1" * 64}
        )
