from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from tests.unit.replay_decision_market_fixtures import (
    decision_id,
    replay_decision_market_fixture,
)

from futures_bot.domain.assets import AssetAmount
from futures_bot.domain.decisions import (
    DecisionIntent,
    NoTradeDecision,
    NoTradeReasonKind,
    ProposedAction,
    TradeSide,
)
from futures_bot.domain.replay import (
    ReplayEventOutputRecord,
    ReplayInputKind,
    build_replay_event_dispatch_receipt_id,
    build_replay_event_output_record_id,
)
from futures_bot.domain.replay_decisions import (
    ReplayDecisionOutputEnvelope,
    ReplayDecisionOutputKind,
    build_replay_decision_market_context_reference,
    build_replay_decision_output_proposal,
    build_replay_decision_stack_fingerprint,
    decode_replay_decision_output_record,
)


def _decision(  # noqa: PLR0913
    fixture,
    *,
    no_trade: bool = False,
    margin_asset: str = "USDT",
    margin_amount: str = "12.3400",
    include_optionals: bool = False,
    instrument: object = "BTC/USDT",
):
    descriptor = fixture.stack_descriptor
    if no_trade:
        return NoTradeDecision(
            decision_intent_id=decision_id(fixture),
            bot_id=descriptor.bot_id,
            instrument="BTC/USDT",
            source_kind=descriptor.source_kind,
            source_id=descriptor.stack_id,
            created_at=fixture.event.event_time,
            reasons=(NoTradeReasonKind.MARKET_TOO_UNCERTAIN,),
            notes="explicit no-trade",
        )
    optional_kwargs = {}
    if include_optionals:
        optional_kwargs = {
            "valid_until": fixture.event.event_time + timedelta(minutes=5),
            "proposed_margin": AssetAmount(asset=margin_asset, amount=margin_amount),
            "proposed_leverage": Decimal("2.500"),
            "reason_tags": ("alpha", "beta"),
        }
    return DecisionIntent(
        decision_intent_id=decision_id(fixture),
        bot_id=descriptor.bot_id,
        instrument=instrument,
        side=TradeSide.LONG,
        proposed_action=ProposedAction.OPEN_POSITION,
        source_kind=descriptor.source_kind,
        source_id=descriptor.stack_id,
        created_at=fixture.event.event_time,
        confidence="0.6" if not include_optionals else Decimal("0.7500"),
        **optional_kwargs,
    )


def _envelope(
    fixture,
    *,
    no_trade: bool = False,
    decision: DecisionIntent | NoTradeDecision | None = None,
) -> ReplayDecisionOutputEnvelope:
    decision = decision or _decision(fixture, no_trade=no_trade)
    return ReplayDecisionOutputEnvelope(
        run_id=fixture.dispatch_context.run_id,
        manifest_id=fixture.dispatch_context.manifest_id,
        replay_plan_id=fixture.dispatch_context.replay_plan_id,
        timeline_id=fixture.dispatch_context.timeline_id,
        timeline_fingerprint_id=fixture.dispatch_context.timeline_fingerprint_id,
        dispatcher_fingerprint=fixture.dispatch_context.dispatcher_fingerprint,
        event_id=fixture.event.event_id,
        event_order_index=fixture.event.order_index,
        event_time=fixture.event.event_time,
        event_kind=fixture.event.kind,
        stack_descriptor=fixture.stack_descriptor,
        market_lookup_descriptor=fixture.lookup.descriptor,
        market_context_reference=build_replay_decision_market_context_reference(
            fixture.decision_context
        ),
        decision_index=0,
        decision_kind=(
            ReplayDecisionOutputKind.NO_TRADE_DECISION
            if no_trade
            else ReplayDecisionOutputKind.DECISION_INTENT
        ),
        decision_intent=None if no_trade else decision,
        no_trade_decision=decision if no_trade else None,
    )


def _record(fixture, envelope: ReplayDecisionOutputEnvelope) -> ReplayEventOutputRecord:
    proposal = build_replay_decision_output_proposal(envelope)
    return _record_for_payload(
        fixture=fixture,
        envelope=envelope,
        output_kind=proposal.output_kind,
        canonical_payload=proposal.canonical_payload,
    )


def _record_for_payload(
    *,
    fixture,
    envelope: ReplayDecisionOutputEnvelope,
    output_kind: str,
    canonical_payload: str,
) -> ReplayEventOutputRecord:
    payload_sha256 = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
    return ReplayEventOutputRecord(
        output_record_id=build_replay_event_output_record_id(
            run_id=fixture.dispatch_context.run_id,
            event_order_index=fixture.event.order_index,
            event_id=fixture.event.event_id,
            handler_id=fixture.handler_fingerprint,
            handler_version=fixture.stack_descriptor.stack_version,
            handler_output_index=envelope.decision_index,
            output_kind=output_kind,
            payload_sha256=payload_sha256,
        ),
        dispatch_receipt_id=build_replay_event_dispatch_receipt_id(
            fixture.dispatch_context.run_id,
            fixture.event.order_index,
            fixture.event.event_id,
        ),
        run_id=fixture.dispatch_context.run_id,
        manifest_id=fixture.dispatch_context.manifest_id,
        replay_plan_id=fixture.dispatch_context.replay_plan_id,
        timeline_id=fixture.dispatch_context.timeline_id,
        timeline_fingerprint_id=fixture.dispatch_context.timeline_fingerprint_id,
        dispatcher_fingerprint=fixture.dispatch_context.dispatcher_fingerprint,
        event_id=fixture.event.event_id,
        event_order_index=fixture.event.order_index,
        event_time=fixture.event.event_time,
        event_kind=fixture.event.kind,
        handler_id=fixture.handler_fingerprint,
        handler_version=fixture.stack_descriptor.stack_version,
        handler_output_index=envelope.decision_index,
        output_kind=output_kind,
        canonical_payload=canonical_payload,
        payload_sha256=payload_sha256,
    )


def _constructed_record_for_payload(
    *,
    fixture,
    envelope: ReplayDecisionOutputEnvelope,
    output_kind: str,
    canonical_payload: str,
    **updates,
) -> ReplayEventOutputRecord:
    payload_sha256 = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
    fields = _record_for_payload(
        fixture=fixture,
        envelope=envelope,
        output_kind=output_kind,
        canonical_payload=build_replay_decision_output_proposal(envelope).canonical_payload,
    ).model_dump()
    fields.update(
        {
            "canonical_payload": canonical_payload,
            "payload_sha256": payload_sha256,
            "output_kind": output_kind,
            "output_record_id": build_replay_event_output_record_id(
                run_id=fields["run_id"],
                event_order_index=fields["event_order_index"],
                event_id=fields["event_id"],
                handler_id=fields["handler_id"],
                handler_version=fields["handler_version"],
                handler_output_index=fields["handler_output_index"],
                output_kind=output_kind,
                payload_sha256=payload_sha256,
            ),
        }
    )
    fields.update(updates)
    return ReplayEventOutputRecord.model_construct(**fields)


@pytest.mark.parametrize("no_trade", [False, True])
def test_v2_decision_output_round_trips(no_trade: bool) -> None:
    fixture = replay_decision_market_fixture()
    envelope = _envelope(fixture, no_trade=no_trade)
    proposal = build_replay_decision_output_proposal(envelope)
    decoded = ReplayDecisionOutputEnvelope.model_validate(json.loads(proposal.canonical_payload))

    assert proposal.output_kind == envelope.decision_kind.value
    assert decoded == envelope
    assert decoded.schema_version == 2
    assert "frame" not in decoded.market_context_reference.model_dump(mode="json")


def test_decode_validates_record_fields_and_composite_handler_id() -> None:
    fixture = replay_decision_market_fixture()
    envelope = _envelope(fixture)
    record = _record(fixture, envelope)

    assert decode_replay_decision_output_record(record) == envelope

    wrong_plan = record.model_copy(update={"replay_plan_id": "other-plan"})
    with pytest.raises(ValueError, match="replay_plan_id"):
        decode_replay_decision_output_record(wrong_plan)

    stale_stack_only = record.model_copy(
        update={
            "handler_id": build_replay_decision_stack_fingerprint(
                fixture.stack_descriptor
            ),
            "output_record_id": build_replay_event_output_record_id(
                run_id=record.run_id,
                event_order_index=record.event_order_index,
                event_id=record.event_id,
                handler_id=build_replay_decision_stack_fingerprint(
                    fixture.stack_descriptor
                ),
                handler_version=record.handler_version,
                handler_output_index=record.handler_output_index,
                output_kind=record.output_kind,
                payload_sha256=record.payload_sha256,
            ),
        }
    )
    with pytest.raises(ValueError, match="handler_id"):
        decode_replay_decision_output_record(stale_stack_only)


def test_decoder_rejects_old_v1_output_kind_and_tampered_market_reference() -> None:
    fixture = replay_decision_market_fixture()
    envelope = _envelope(fixture)
    record = _record(fixture, envelope)

    with pytest.raises(ValueError):
        decode_replay_decision_output_record(
            record.model_copy(update={"output_kind": "replay.decision-intent.v1"})
        )

    payload = json.loads(record.canonical_payload)
    payload["market_context_reference"]["frame_id"] = "bad-frame"
    tampered = record.model_copy(
        update={"canonical_payload": json.dumps(payload, sort_keys=True)}
    )
    with pytest.raises(ValidationError):
        decode_replay_decision_output_record(tampered)


def test_decision_id_changes_when_market_context_changes() -> None:
    first = replay_decision_market_fixture(price="100")
    changed = replay_decision_market_fixture(price="101")

    assert decision_id(first) != decision_id(changed)
    assert _envelope(first).model_dump(mode="json") != _envelope(changed).model_dump(
        mode="json"
    )


def test_market_context_reference_contains_ids_only() -> None:
    fixture = replay_decision_market_fixture()
    reference = build_replay_decision_market_context_reference(fixture.decision_context)
    dumped = reference.model_dump(mode="json")

    assert set(dumped) == {
        "schema_version",
        "reference_id",
        "context_id",
        "run_id",
        "manifest_id",
        "replay_plan_id",
        "replay_timeline_id",
        "timeline_fingerprint_id",
        "dispatcher_fingerprint",
        "event_id",
        "event_order_index",
        "event_time",
        "event_kind",
        "market_timeline_id",
        "lookup_authority_fingerprint",
        "adapter_fingerprint",
        "observation_projection_id",
        "frame_projection_id",
        "frame_id",
        "triggering_observation_id",
        "binding_authority_fingerprint",
    }


def test_canonical_payload_preserves_decimal_scale_and_official_utc_encoding() -> None:
    fixture = replay_decision_market_fixture()
    decision = _decision(fixture, include_optionals=True, instrument="btcusdt")
    envelope = _envelope(fixture, decision=decision)
    proposal = build_replay_decision_output_proposal(envelope)
    parsed = json.loads(proposal.canonical_payload)
    encoded_decision = parsed["decision_intent"]

    assert proposal.canonical_payload == json.dumps(
        parsed,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert parsed["event_time"] == "2026-01-01T12:00:00Z"
    assert "+00:00" not in proposal.canonical_payload
    assert encoded_decision["instrument"] == {"value": "BTC/USDT"}
    assert encoded_decision["proposed_margin"]["amount"] == "12.3400"
    assert encoded_decision["proposed_leverage"] == "2.500"
    assert encoded_decision["confidence"] == "0.7500"


@pytest.mark.parametrize(
    "tamper",
    (
        "additional_whitespace",
        "different_key_ordering",
        "event_timestamp_offset",
        "nested_timestamp_offset",
        "decimal_json_number",
        "instrument_string",
    ),
)
def test_decode_rejects_semantically_equivalent_non_official_encodings(tamper: str) -> None:
    fixture = replay_decision_market_fixture()
    envelope = _envelope(
        fixture,
        decision=_decision(fixture, include_optionals=True, instrument="btcusdt"),
    )
    proposal = build_replay_decision_output_proposal(envelope)
    parsed = json.loads(proposal.canonical_payload)
    if tamper == "additional_whitespace":
        payload = json.dumps(parsed, sort_keys=True, indent=2)
    elif tamper == "different_key_ordering":
        payload = json.dumps(
            dict(reversed(tuple(parsed.items()))),
            separators=(",", ":"),
            ensure_ascii=False,
        )
    else:
        if tamper == "event_timestamp_offset":
            parsed["event_time"] = "2026-01-01T12:00:00+00:00"
        elif tamper == "nested_timestamp_offset":
            parsed["decision_intent"]["created_at"] = "2026-01-01T12:00:00+00:00"
        elif tamper == "decimal_json_number":
            parsed["decision_intent"]["proposed_margin"]["amount"] = 12.34
        elif tamper == "instrument_string":
            parsed["decision_intent"]["instrument"] = "btcusdt"
        payload = json.dumps(
            parsed,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    record = _constructed_record_for_payload(
        fixture=fixture,
        envelope=envelope,
        output_kind=proposal.output_kind,
        canonical_payload=payload,
    )

    with pytest.raises((ValidationError, ValueError)):
        decode_replay_decision_output_record(record)


@pytest.mark.parametrize(
    ("asset", "amount"),
    (("USDT", "12.3400"), ("USDC", "0.0100")),
)
def test_stable_collateral_margin_round_trips_with_lexical_scale(
    asset: str,
    amount: str,
) -> None:
    fixture = replay_decision_market_fixture()
    envelope = _envelope(
        fixture,
        decision=_decision(
            fixture,
            include_optionals=True,
            margin_asset=asset,
            margin_amount=amount,
        ),
    )
    record = _record(fixture, envelope)

    assert ReplayDecisionOutputEnvelope.model_validate(envelope.model_dump()) == envelope
    decoded = decode_replay_decision_output_record(record)
    assert decoded.decision_intent is not None
    assert decoded.decision_intent.proposed_margin is not None
    assert str(decoded.decision_intent.proposed_margin.asset) == asset
    assert str(decoded.decision_intent.proposed_margin.amount) == amount
    payload = json.loads(record.canonical_payload)
    assert payload["decision_intent"]["proposed_margin"]["amount"] == amount


@pytest.mark.parametrize(
    "proposed_margin",
    (
        {"asset": {"value": "BTC"}, "amount": "12.3400"},
        {"asset": {"value": "ETH"}, "amount": "12.3400"},
        {"asset": {"value": "BNB"}, "amount": "12.3400"},
        {"asset": {"value": "USDT"}, "amount": 1.25},
        {"asset": {"value": "USDT"}, "amount": True},
        {"asset": {"value": "USDT"}, "amount": {"value": "1"}},
        {"amount": "12.3400"},
        {"asset": {"value": "USDT"}},
    ),
)
def test_stable_collateral_margin_rejects_nested_tampering(proposed_margin) -> None:
    fixture = replay_decision_market_fixture()
    envelope = _envelope(
        fixture,
        decision=_decision(fixture, include_optionals=True),
    )
    payload = envelope.model_dump()
    payload["decision_intent"]["proposed_margin"] = proposed_margin
    with pytest.raises(ValidationError):
        ReplayDecisionOutputEnvelope.model_validate(payload)

    canonical = json.loads(build_replay_decision_output_proposal(envelope).canonical_payload)
    canonical["decision_intent"]["proposed_margin"] = proposed_margin
    record = _constructed_record_for_payload(
        fixture=fixture,
        envelope=envelope,
        output_kind=envelope.decision_kind.value,
        canonical_payload=json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ),
    )
    with pytest.raises((ValidationError, ValueError)):
        decode_replay_decision_output_record(record)


@pytest.mark.parametrize(
    "bad_margin",
    (
        AssetAmount(asset="USDT", amount="12.3400").model_copy(update={"asset": "BTC"}),
        AssetAmount(asset="USDT", amount="12.3400").model_copy(update={"amount": 1.25}),
    ),
)
def test_stable_collateral_margin_rejects_model_copy_tampering(bad_margin) -> None:
    fixture = replay_decision_market_fixture()

    with pytest.raises(ValidationError):
        _envelope(
            fixture,
            decision=DecisionIntent(
                decision_intent_id=decision_id(fixture),
                bot_id=fixture.stack_descriptor.bot_id,
                instrument="BTC/USDT",
                side=TradeSide.LONG,
                proposed_action=ProposedAction.OPEN_POSITION,
                source_kind=fixture.stack_descriptor.source_kind,
                source_id=fixture.stack_descriptor.stack_id,
                created_at=fixture.event.event_time,
                proposed_margin=bad_margin,
            ),
        )


def test_decision_intent_optional_fields_round_trip_and_may_be_absent() -> None:
    fixture = replay_decision_market_fixture()
    full = _envelope(
        fixture,
        decision=_decision(fixture, include_optionals=True),
    )
    minimal = _envelope(fixture, decision=_decision(fixture))

    decoded_full = decode_replay_decision_output_record(_record(fixture, full))
    assert decoded_full.decision_intent is not None
    assert decoded_full.decision_intent.proposed_margin == AssetAmount(
        asset="USDT",
        amount="12.3400",
    )
    assert decoded_full.decision_intent.proposed_leverage == Decimal("2.500")
    assert decoded_full.decision_intent.confidence == Decimal("0.7500")
    assert decoded_full.decision_intent.valid_until == (
        fixture.event.event_time + timedelta(minutes=5)
    )
    assert decoded_full.decision_intent.reason_tags == ("alpha", "beta")

    decoded_minimal = decode_replay_decision_output_record(_record(fixture, minimal))
    assert decoded_minimal.decision_intent is not None
    assert decoded_minimal.decision_intent.proposed_margin is None
    assert decoded_minimal.decision_intent.proposed_leverage is None
    assert decoded_minimal.decision_intent.valid_until is None
    assert decoded_minimal.decision_intent.reason_tags == ()


@pytest.mark.parametrize(
    "field_name",
    (
        "canonical_payload",
        "payload_sha256",
        "output_record_id",
        "dispatch_receipt_id",
        "handler_id",
        "handler_version",
        "handler_output_index",
        "output_kind",
        "run_id",
        "manifest_id",
        "replay_plan_id",
        "timeline_id",
        "timeline_fingerprint_id",
        "dispatcher_fingerprint",
        "event_id",
        "event_order_index",
        "event_time",
        "event_kind",
    ),
)
def test_decode_rejects_output_record_field_tampering(field_name: str) -> None:
    fixture = replay_decision_market_fixture()
    envelope = _envelope(fixture, decision=_decision(fixture, include_optionals=True))
    record = _record(fixture, envelope)
    updates = _record_tamper_updates(record, field_name)
    tampered = record.model_copy(update=updates)
    if field_name in {"canonical_payload", "payload_sha256", "output_record_id"}:
        tampered = ReplayEventOutputRecord.model_construct(
            **{**record.model_dump(), **updates}
        )

    with pytest.raises((ValidationError, ValueError)):
        decode_replay_decision_output_record(tampered)


def _record_tamper_updates(  # noqa: PLR0911, PLR0912
    record: ReplayEventOutputRecord,
    field_name: str,
) -> dict[str, object]:
    if field_name == "canonical_payload":
        payload = json.loads(record.canonical_payload)
        payload["manifest_id"] = "manifest-tampered"
        canonical_payload = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        payload_sha256 = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
        return {
            "canonical_payload": canonical_payload,
            "payload_sha256": payload_sha256,
            "output_record_id": build_replay_event_output_record_id(
                run_id=record.run_id,
                event_order_index=record.event_order_index,
                event_id=record.event_id,
                handler_id=record.handler_id,
                handler_version=record.handler_version,
                handler_output_index=record.handler_output_index,
                output_kind=record.output_kind,
                payload_sha256=payload_sha256,
            ),
        }
    if field_name == "payload_sha256":
        return {"payload_sha256": "0" * 64}
    if field_name == "output_record_id":
        return {"output_record_id": "replay-output:" + "0" * 64}
    if field_name == "dispatch_receipt_id":
        return {"dispatch_receipt_id": "replay-dispatch:" + "0" * 64}
    if field_name == "handler_id":
        handler_id = "replay-decision-handler:" + "0" * 64
        return {
            "handler_id": handler_id,
            "output_record_id": build_replay_event_output_record_id(
                run_id=record.run_id,
                event_order_index=record.event_order_index,
                event_id=record.event_id,
                handler_id=handler_id,
                handler_version=record.handler_version,
                handler_output_index=record.handler_output_index,
                output_kind=record.output_kind,
                payload_sha256=record.payload_sha256,
            ),
        }
    if field_name == "handler_version":
        return _record_id_update(record, handler_version="handler-v2")
    if field_name == "handler_output_index":
        return _record_id_update(record, handler_output_index=record.handler_output_index + 1)
    if field_name == "output_kind":
        return _record_id_update(
            record,
            output_kind=ReplayDecisionOutputKind.NO_TRADE_DECISION.value,
        )
    if field_name == "run_id":
        return _record_id_update(record, run_id="run-tampered")
    if field_name == "manifest_id":
        return {"manifest_id": "manifest-tampered"}
    if field_name == "replay_plan_id":
        return {"replay_plan_id": "plan-tampered"}
    if field_name == "timeline_id":
        return {"timeline_id": "timeline-tampered"}
    if field_name == "timeline_fingerprint_id":
        return {"timeline_fingerprint_id": "fp-tampered"}
    if field_name == "dispatcher_fingerprint":
        return {"dispatcher_fingerprint": "replay-dispatcher:" + "0" * 64}
    if field_name == "event_id":
        return _record_id_update(record, event_id="event-tampered")
    if field_name == "event_order_index":
        return _record_id_update(record, event_order_index=record.event_order_index + 1)
    if field_name == "event_time":
        return {"event_time": record.event_time + timedelta(seconds=1)}
    if field_name == "event_kind":
        return {"event_kind": ReplayInputKind.TRADE}
    raise AssertionError(f"unhandled field: {field_name}")


def _record_id_update(record: ReplayEventOutputRecord, **updates) -> dict[str, object]:
    values = record.model_dump()
    values.update(updates)
    if {"run_id", "event_order_index", "event_id"} & updates.keys():
        values["dispatch_receipt_id"] = build_replay_event_dispatch_receipt_id(
            values["run_id"],
            values["event_order_index"],
            values["event_id"],
        )
    values["output_record_id"] = build_replay_event_output_record_id(
        run_id=values["run_id"],
        event_order_index=values["event_order_index"],
        event_id=values["event_id"],
        handler_id=values["handler_id"],
        handler_version=values["handler_version"],
        handler_output_index=values["handler_output_index"],
        output_kind=values["output_kind"],
        payload_sha256=values["payload_sha256"],
    )
    return values
