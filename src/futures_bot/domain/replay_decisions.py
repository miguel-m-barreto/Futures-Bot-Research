from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self, cast

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.decisions import (
    DecisionIntent,
    DecisionIntentStatus,
    DecisionSourceKind,
    NoTradeDecision,
)
from futures_bot.domain.ids import BotId, DecisionIntentId
from futures_bot.domain.replay import (
    ReplayEventOutputRecord,
    ReplayHandlerOutputProposal,
    ReplayInputKind,
    _canonical_json,
    _sha256_text,
    _validate_canonical_output_payload,
    _validate_required_text,
    _validate_strict_int,
)
from futures_bot.domain.time import ensure_aware_utc

_DECISION_STACK_FINGERPRINT_RE = re.compile(r"decision-stack:[0-9a-f]{64}")


class ReplayDecisionStackDescriptor(BaseModel):
    """Deterministic replay identity and event capability for one DecisionStack."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stack_id: str
    stack_version: str
    bot_id: BotId
    source_kind: DecisionSourceKind
    supported_event_kinds: tuple[ReplayInputKind, ...]

    @field_validator("stack_id", "stack_version")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return _validate_required_text(value, "decision stack descriptor field")

    @field_validator("bot_id", mode="before")
    @classmethod
    def _revalidate_bot_id(cls, value: object) -> object:
        if isinstance(value, BotId):
            return BotId.model_validate(value.model_dump())
        return BotId.model_validate(value)

    @field_validator("supported_event_kinds")
    @classmethod
    def _validate_supported_event_kinds(
        cls,
        value: tuple[ReplayInputKind, ...],
    ) -> tuple[ReplayInputKind, ...]:
        if not value:
            raise ValueError("supported_event_kinds must be non-empty")
        if len(value) != len(set(value)):
            raise ValueError("duplicate supported_event_kinds are not allowed")
        if value != tuple(sorted(value, key=lambda kind: kind.value)):
            raise ValueError("supported_event_kinds must be sorted by enum value")
        return value


def build_replay_decision_stack_fingerprint(
    descriptor: ReplayDecisionStackDescriptor,
) -> str:
    """Build a deterministic fingerprint for a replay DecisionStack descriptor."""
    revalidated = ReplayDecisionStackDescriptor.model_validate(descriptor.model_dump())
    material = {
        "bot_id": revalidated.bot_id.model_dump(mode="json"),
        "source_kind": revalidated.source_kind.value,
        "stack_id": revalidated.stack_id,
        "stack_version": revalidated.stack_version,
        "supported_event_kinds": [
            kind.value for kind in revalidated.supported_event_kinds
        ],
    }
    return f"decision-stack:{_sha256_text(_canonical_json(material))}"


def build_replay_decision_intent_id(
    *,
    run_id: str,
    event_order_index: int,
    event_id: str,
    decision_stack_fingerprint: str,
    decision_index: int,
) -> DecisionIntentId:
    """Build the deterministic replay identity for a DecisionStack output."""
    material = {
        "decision_index": _validate_strict_non_negative_int(
            decision_index,
            "decision_index",
        ),
        "decision_stack_fingerprint": _validate_decision_stack_fingerprint(
            decision_stack_fingerprint
        ),
        "event_id": _validate_required_text(event_id, "event_id"),
        "event_order_index": _validate_strict_non_negative_int(
            event_order_index,
            "event_order_index",
        ),
        "run_id": _validate_required_text(run_id, "run_id"),
    }
    return DecisionIntentId.from_str(
        f"replay-decision:{_sha256_text(_canonical_json(material))}"
    )


class ReplayDecisionOutputKind(StrEnum):
    DECISION_INTENT = "replay.decision-intent.v1"
    NO_TRADE_DECISION = "replay.no-trade-decision.v1"


class ReplayDecisionOutputEnvelope(BaseModel):
    """Typed canonical replay output for one DecisionStack decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1

    run_id: str
    event_id: str
    event_order_index: int
    event_time: datetime
    event_kind: ReplayInputKind

    stack_descriptor: ReplayDecisionStackDescriptor
    decision_index: int
    decision_kind: ReplayDecisionOutputKind

    decision_intent: DecisionIntent | None = None
    no_trade_decision: NoTradeDecision | None = None

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("schema_version must be the strict integer 1")
        if value != 1:
            raise ValueError("schema_version must be 1")
        return value

    @field_validator("run_id", "event_id")
    @classmethod
    def _validate_ids(cls, value: str) -> str:
        return _validate_required_text(value, "replay decision output id")

    @field_validator("event_order_index", "decision_index", mode="before")
    @classmethod
    def _validate_indexes(cls, value: object) -> object:
        return _validate_strict_non_negative_int(value, "replay decision output index")

    @field_validator("event_time")
    @classmethod
    def _validate_event_time(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("stack_descriptor", mode="before")
    @classmethod
    def _revalidate_stack_descriptor(cls, value: object) -> object:
        if isinstance(value, ReplayDecisionStackDescriptor):
            return ReplayDecisionStackDescriptor.model_validate(value.model_dump())
        return ReplayDecisionStackDescriptor.model_validate(value)

    @field_validator("decision_intent", mode="before")
    @classmethod
    def _revalidate_decision_intent(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, DecisionIntent):
            return DecisionIntent.model_validate(_decision_model_data(value))
        return DecisionIntent.model_validate(_normalize_decision_data(value))

    @field_validator("no_trade_decision", mode="before")
    @classmethod
    def _revalidate_no_trade_decision(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, NoTradeDecision):
            return NoTradeDecision.model_validate(_decision_model_data(value))
        return NoTradeDecision.model_validate(_normalize_decision_data(value))

    @model_validator(mode="after")
    def _validate_envelope(self) -> Self:
        if self.event_kind not in self.stack_descriptor.supported_event_kinds:
            raise ValueError("event_kind must be supported by stack_descriptor")

        decision = _populated_decision_for_kind(
            self.decision_kind,
            self.decision_intent,
            self.no_trade_decision,
        )

        expected_id = build_replay_decision_intent_id(
            run_id=self.run_id,
            event_order_index=self.event_order_index,
            event_id=self.event_id,
            decision_stack_fingerprint=build_replay_decision_stack_fingerprint(
                self.stack_descriptor
            ),
            decision_index=self.decision_index,
        )
        if decision.decision_intent_id != expected_id:
            raise ValueError("decision_intent_id must match deterministic replay decision ID")
        if decision.bot_id != self.stack_descriptor.bot_id:
            raise ValueError("decision bot_id must match stack_descriptor bot_id")
        if decision.source_kind is not self.stack_descriptor.source_kind:
            raise ValueError("decision source_kind must match stack_descriptor source_kind")
        if decision.source_id != self.stack_descriptor.stack_id:
            raise ValueError("decision source_id must match stack_descriptor stack_id")
        if decision.created_at != self.event_time:
            raise ValueError("decision created_at must match replay event_time")
        return self


def build_replay_decision_output_proposal(
    envelope: ReplayDecisionOutputEnvelope,
) -> ReplayHandlerOutputProposal:
    """Encode a typed replay decision envelope as a canonical handler output."""
    revalidated = ReplayDecisionOutputEnvelope.model_validate(
        envelope.model_dump(mode="json")
    )
    payload = _canonical_json(revalidated.model_dump(mode="json"))
    _validate_canonical_output_payload(payload)
    return ReplayHandlerOutputProposal(
        output_kind=revalidated.decision_kind.value,
        canonical_payload=payload,
    )


def decode_replay_decision_output_record(
    record: ReplayEventOutputRecord,
) -> ReplayDecisionOutputEnvelope:
    """Decode a typed replay decision output journal record."""
    revalidated = ReplayEventOutputRecord.model_validate(record.model_dump())
    try:
        output_kind = ReplayDecisionOutputKind(revalidated.output_kind)
    except ValueError as exc:
        raise ValueError("output record is not a replay decision output kind") from exc
    payload = json.loads(revalidated.canonical_payload)
    envelope = ReplayDecisionOutputEnvelope.model_validate(payload)
    expected_values = {
        "run_id": revalidated.run_id,
        "event_id": revalidated.event_id,
        "event_order_index": revalidated.event_order_index,
        "event_time": revalidated.event_time,
        "event_kind": revalidated.event_kind,
    }
    for field_name, expected in expected_values.items():
        if getattr(envelope, field_name) != expected:
            raise ValueError(f"decision envelope {field_name} must match output record")
    if revalidated.handler_id != build_replay_decision_stack_fingerprint(
        envelope.stack_descriptor
    ):
        raise ValueError("output record handler_id must match decision stack fingerprint")
    if revalidated.handler_version != envelope.stack_descriptor.stack_version:
        raise ValueError("output record handler_version must match stack_version")
    if revalidated.handler_output_index != envelope.decision_index:
        raise ValueError("output record handler_output_index must match decision_index")
    if output_kind is not envelope.decision_kind:
        raise ValueError("output record output_kind must match decision_kind")
    expected_proposal = build_replay_decision_output_proposal(envelope)
    if revalidated.output_kind != expected_proposal.output_kind:
        raise ValueError("output_kind must match canonical replay decision encoding")
    if revalidated.canonical_payload != expected_proposal.canonical_payload:
        raise ValueError(
            "canonical_payload must match canonical replay decision encoding"
        )
    return envelope


def _validate_decision_stack_fingerprint(value: str) -> str:
    value = _validate_required_text(value, "decision_stack_fingerprint")
    if not _DECISION_STACK_FINGERPRINT_RE.fullmatch(value):
        raise ValueError(
            "decision_stack_fingerprint must match decision-stack:<64 lowercase hex>"
        )
    return value


def _validate_strict_non_negative_int(value: object, field_name: str) -> int:
    parsed = cast(int, _validate_strict_int(value, field_name))
    if parsed < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return parsed


def _decision_model_data(value: DecisionIntent | NoTradeDecision) -> dict[str, object]:
    normalized = _normalize_decision_data(value.model_dump(mode="json"))
    if not isinstance(normalized, dict):
        raise ValueError("decision model data must be a mapping")
    return normalized


def _normalize_decision_data(value: object) -> object:
    if not isinstance(value, dict):
        return value
    normalized = dict(value)
    instrument = normalized.get("instrument")
    if isinstance(instrument, dict) and set(instrument) == {"value"}:
        normalized["instrument"] = instrument["value"]
    proposed_margin = normalized.get("proposed_margin")
    if isinstance(proposed_margin, Mapping):
        normalized["proposed_margin"] = _normalize_proposed_margin_data(
            proposed_margin
        )
    return normalized


def _normalize_proposed_margin_data(
    proposed_margin: Mapping[object, object],
) -> dict[object, object]:
    normalized = dict(proposed_margin)
    asset = normalized.get("asset")
    if isinstance(asset, Mapping) and set(asset) == {"value"}:
        normalized["asset"] = asset["value"]
    return normalized


def _populated_decision_for_kind(
    decision_kind: ReplayDecisionOutputKind,
    decision_intent: DecisionIntent | None,
    no_trade_decision: NoTradeDecision | None,
) -> DecisionIntent | NoTradeDecision:
    populated = [
        decision is not None for decision in (decision_intent, no_trade_decision)
    ]
    if populated.count(True) != 1:
        raise ValueError("exactly one replay decision output must be populated")
    if decision_intent is not None:
        if decision_kind is not ReplayDecisionOutputKind.DECISION_INTENT:
            raise ValueError("decision_kind must match decision_intent")
        if decision_intent.status is not DecisionIntentStatus.PROPOSED:
            raise ValueError("DecisionStack may only emit PROPOSED DecisionIntent")
        return decision_intent
    if decision_kind is not ReplayDecisionOutputKind.NO_TRADE_DECISION:
        raise ValueError("decision_kind must match no_trade_decision")
    if no_trade_decision is None:
        raise ValueError("no_trade_decision is required")
    return no_trade_decision
