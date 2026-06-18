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
from futures_bot.domain.ids import (
    BotId,
    DecisionIntentId,
    MarketFrameId,
    MarketObservationId,
    ReplayDecisionContextId,
    ReplayDecisionMarketContextReferenceId,
    ReplayMarketFrameProjectionId,
    ReplayMarketFrameTimelineId,
    ReplayMarketObservationProjectionId,
)
from futures_bot.domain.replay import (
    ReplayDispatchContext,
    ReplayEventOutputRecord,
    ReplayHandlerOutputProposal,
    ReplayInputKind,
    ReplayTimelineEvent,
    _canonical_json,
    _sha256_text,
    _validate_canonical_output_payload,
    _validate_required_text,
    _validate_strict_int,
)
from futures_bot.domain.replay_market_data import (
    ReplayMarketFrameLookupDescriptor,
    ReplayMarketFrameLookupResult,
)
from futures_bot.domain.time import ensure_aware_utc

_DECISION_STACK_FINGERPRINT_RE = re.compile(r"decision-stack:[0-9a-f]{64}")
_DECISION_HANDLER_FINGERPRINT_RE = re.compile(
    r"replay-decision-handler:[0-9a-f]{64}"
)
_REPLAY_DECISION_CONTEXT_ID_RE = re.compile(r"replay-decision-context:[0-9a-f]{64}")
_REPLAY_DECISION_MARKET_CONTEXT_REFERENCE_ID_RE = re.compile(
    r"replay-decision-market-context-reference:[0-9a-f]{64}"
)
_REPLAY_MARKET_ADAPTER_FINGERPRINT_RE = re.compile(
    r"replay-market-adapter:[0-9a-f]{64}"
)
_REPLAY_MARKET_BINDING_AUTHORITY_FINGERPRINT_RE = re.compile(
    r"replay-market-binding-authority:[0-9a-f]{64}"
)
_REPLAY_MARKET_LOOKUP_AUTHORITY_FINGERPRINT_RE = re.compile(
    r"replay-market-frame-lookup-authority:[0-9a-f]{64}"
)
_REPLAY_MARKET_TIMELINE_ID_RE = re.compile(r"replay-market-frame-timeline:[0-9a-f]{64}")
_REPLAY_MARKET_OBSERVATION_PROJECTION_ID_RE = re.compile(
    r"replay-market-observation-projection:[0-9a-f]{64}"
)
_REPLAY_MARKET_FRAME_PROJECTION_ID_RE = re.compile(
    r"replay-market-frame-projection:[0-9a-f]{64}"
)
_MARKET_FRAME_ID_RE = re.compile(r"market-frame:[0-9a-f]{64}")
_MARKET_OBSERVATION_ID_RE = re.compile(r"market-observation:[0-9a-f]{64}")


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


def build_replay_decision_handler_fingerprint(
    *,
    stack_descriptor: ReplayDecisionStackDescriptor,
    market_lookup_descriptor: ReplayMarketFrameLookupDescriptor,
) -> str:
    stack_descriptor = _revalidate_stack_descriptor(stack_descriptor)
    market_lookup_descriptor = _revalidate_market_lookup_descriptor(
        market_lookup_descriptor
    )
    material = {
        "market_lookup_descriptor": market_lookup_descriptor.model_dump(mode="json"),
        "stack_descriptor": stack_descriptor.model_dump(mode="json"),
    }
    return f"replay-decision-handler:{_sha256_text(_canonical_json(material))}"


def build_replay_decision_intent_id(  # noqa: PLR0913 - explicit deterministic ID material
    *,
    run_id: str,
    event_order_index: int,
    event_id: str,
    decision_handler_fingerprint: str,
    market_context_reference_id: ReplayDecisionMarketContextReferenceId,
    decision_index: int,
) -> DecisionIntentId:
    """Build the deterministic replay identity for a DecisionStack output."""
    market_context_reference_id = _validate_market_context_reference_id(
        market_context_reference_id
    )
    material = {
        "decision_index": _validate_strict_non_negative_int(
            decision_index,
            "decision_index",
        ),
        "decision_handler_fingerprint": _validate_decision_handler_fingerprint(
            decision_handler_fingerprint
        ),
        "event_id": _validate_required_text(event_id, "event_id"),
        "event_order_index": _validate_strict_non_negative_int(
            event_order_index,
            "event_order_index",
        ),
        "market_context_reference_id": market_context_reference_id.model_dump(mode="json"),
        "run_id": _validate_required_text(run_id, "run_id"),
    }
    return DecisionIntentId.from_str(
        f"replay-decision:{_sha256_text(_canonical_json(material))}"
    )


class ReplayDecisionOutputKind(StrEnum):
    DECISION_INTENT = "replay.decision-intent.v2"
    NO_TRADE_DECISION = "replay.no-trade-decision.v2"


class ReplayDecisionStackContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    context_id: ReplayDecisionContextId
    dispatch_context: ReplayDispatchContext
    event: ReplayTimelineEvent
    market: ReplayMarketFrameLookupResult

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> object:
        return _validate_schema_version(value, expected=1)

    @field_validator("context_id", mode="before")
    @classmethod
    def _revalidate_context_id(cls, value: object) -> ReplayDecisionContextId:
        return _validate_replay_decision_context_id(value)

    @field_validator("dispatch_context", mode="before")
    @classmethod
    def _revalidate_dispatch_context(cls, value: object) -> ReplayDispatchContext:
        return _revalidate_dispatch_context(value)

    @field_validator("event", mode="before")
    @classmethod
    def _revalidate_event(cls, value: object) -> ReplayTimelineEvent:
        return _revalidate_timeline_event(value)

    @field_validator("market", mode="before")
    @classmethod
    def _revalidate_market(cls, value: object) -> ReplayMarketFrameLookupResult:
        return _revalidate_market_lookup_result(value)

    @model_validator(mode="after")
    def _validate_context(self) -> Self:
        _validate_decision_context_semantics(
            dispatch_context=self.dispatch_context,
            event=self.event,
            market=self.market,
        )
        expected = build_replay_decision_stack_context_id(
            dispatch_context=self.dispatch_context,
            event=self.event,
            market=self.market,
        )
        if self.context_id != expected:
            raise ValueError("context_id must match deterministic decision context ID")
        return self


class ReplayDecisionMarketContextReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    reference_id: ReplayDecisionMarketContextReferenceId
    context_id: ReplayDecisionContextId

    run_id: str
    manifest_id: str
    replay_plan_id: str
    replay_timeline_id: str
    timeline_fingerprint_id: str
    dispatcher_fingerprint: str
    event_id: str
    event_order_index: int
    event_time: datetime
    event_kind: ReplayInputKind

    market_timeline_id: ReplayMarketFrameTimelineId
    lookup_authority_fingerprint: str
    adapter_fingerprint: str
    observation_projection_id: ReplayMarketObservationProjectionId
    frame_projection_id: ReplayMarketFrameProjectionId
    frame_id: MarketFrameId
    triggering_observation_id: MarketObservationId
    binding_authority_fingerprint: str

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> object:
        return _validate_schema_version(value, expected=1)

    @field_validator("reference_id", mode="before")
    @classmethod
    def _revalidate_reference_id(
        cls,
        value: object,
    ) -> ReplayDecisionMarketContextReferenceId:
        return _validate_market_context_reference_id(value)

    @field_validator("context_id", mode="before")
    @classmethod
    def _revalidate_context_id(cls, value: object) -> ReplayDecisionContextId:
        return _validate_replay_decision_context_id(value)

    @field_validator(
        "run_id",
        "manifest_id",
        "replay_plan_id",
        "replay_timeline_id",
        "timeline_fingerprint_id",
        "event_id",
    )
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return _validate_required_text(value, "market context reference text")

    @field_validator("dispatcher_fingerprint")
    @classmethod
    def _validate_dispatcher_fingerprint(cls, value: str) -> str:
        return _validate_required_text(value, "dispatcher_fingerprint")

    @field_validator("event_order_index", mode="before")
    @classmethod
    def _validate_event_order_index(cls, value: object) -> object:
        return _validate_strict_non_negative_int(value, "event_order_index")

    @field_validator("event_time")
    @classmethod
    def _validate_event_time(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("market_timeline_id", mode="before")
    @classmethod
    def _revalidate_market_timeline_id(cls, value: object) -> ReplayMarketFrameTimelineId:
        return _validate_market_timeline_id(value)

    @field_validator("observation_projection_id", mode="before")
    @classmethod
    def _revalidate_observation_projection_id(
        cls,
        value: object,
    ) -> ReplayMarketObservationProjectionId:
        return _validate_observation_projection_id(value)

    @field_validator("frame_projection_id", mode="before")
    @classmethod
    def _revalidate_frame_projection_id(
        cls,
        value: object,
    ) -> ReplayMarketFrameProjectionId:
        return _validate_frame_projection_id(value)

    @field_validator("frame_id", mode="before")
    @classmethod
    def _revalidate_frame_id(cls, value: object) -> MarketFrameId:
        return _validate_market_frame_id(value)

    @field_validator("triggering_observation_id", mode="before")
    @classmethod
    def _revalidate_observation_id(cls, value: object) -> MarketObservationId:
        return _validate_market_observation_id(value)

    @field_validator("adapter_fingerprint")
    @classmethod
    def _validate_adapter_fingerprint(cls, value: str) -> str:
        return _validate_market_adapter_fingerprint(value)

    @field_validator("lookup_authority_fingerprint")
    @classmethod
    def _validate_lookup_authority_fingerprint(cls, value: str) -> str:
        return _validate_lookup_authority_fingerprint(value)

    @field_validator("binding_authority_fingerprint")
    @classmethod
    def _validate_binding_authority_fingerprint(cls, value: str) -> str:
        return _validate_binding_authority_fingerprint(value)

    @model_validator(mode="after")
    def _validate_reference(self) -> Self:
        expected = _build_replay_decision_market_context_reference_id_from_fields(
            context_id=self.context_id,
            run_id=self.run_id,
            manifest_id=self.manifest_id,
            replay_plan_id=self.replay_plan_id,
            replay_timeline_id=self.replay_timeline_id,
            timeline_fingerprint_id=self.timeline_fingerprint_id,
            dispatcher_fingerprint=self.dispatcher_fingerprint,
            event_id=self.event_id,
            event_order_index=self.event_order_index,
            event_time=self.event_time,
            event_kind=self.event_kind,
            market_timeline_id=self.market_timeline_id,
            lookup_authority_fingerprint=self.lookup_authority_fingerprint,
            adapter_fingerprint=self.adapter_fingerprint,
            observation_projection_id=self.observation_projection_id,
            frame_projection_id=self.frame_projection_id,
            frame_id=self.frame_id,
            triggering_observation_id=self.triggering_observation_id,
            binding_authority_fingerprint=self.binding_authority_fingerprint,
        )
        if self.reference_id != expected:
            raise ValueError("reference_id must match deterministic market context reference")
        return self


def build_replay_decision_stack_context_id(
    *,
    dispatch_context: ReplayDispatchContext,
    event: ReplayTimelineEvent,
    market: ReplayMarketFrameLookupResult,
) -> ReplayDecisionContextId:
    dispatch_context = _revalidate_dispatch_context(dispatch_context)
    event = _revalidate_timeline_event(event)
    market = _revalidate_market_lookup_result(market)
    _validate_decision_context_semantics(
        dispatch_context=dispatch_context,
        event=event,
        market=market,
    )
    material = {
        "schema_version": 1,
        "dispatch_context": dispatch_context.model_dump(mode="json"),
        "event": event.model_dump(mode="json"),
        "market": market.model_dump(mode="json"),
    }
    return ReplayDecisionContextId.from_str(
        f"replay-decision-context:{_sha256_text(_canonical_json(material))}"
    )


def build_replay_decision_market_context_reference_id(
    *,
    context_id: ReplayDecisionContextId,
    dispatch_context: ReplayDispatchContext,
    market: ReplayMarketFrameLookupResult,
) -> ReplayDecisionMarketContextReferenceId:
    context_id = _validate_replay_decision_context_id(context_id)
    dispatch_context = _revalidate_dispatch_context(dispatch_context)
    market = _revalidate_market_lookup_result(market)
    _validate_dispatch_context_matches_market(
        dispatch_context=dispatch_context,
        market=market,
    )
    return _build_replay_decision_market_context_reference_id_from_fields(
        context_id=context_id,
        run_id=dispatch_context.run_id,
        manifest_id=dispatch_context.manifest_id,
        replay_plan_id=dispatch_context.replay_plan_id,
        replay_timeline_id=dispatch_context.timeline_id,
        timeline_fingerprint_id=dispatch_context.timeline_fingerprint_id,
        dispatcher_fingerprint=dispatch_context.dispatcher_fingerprint,
        event_id=dispatch_context.event_id,
        event_order_index=dispatch_context.event_order_index,
        event_time=dispatch_context.event_time,
        event_kind=dispatch_context.event_kind,
        market_timeline_id=market.descriptor.market_timeline_id,
        lookup_authority_fingerprint=market.descriptor.lookup_authority_fingerprint,
        adapter_fingerprint=market.descriptor.adapter_fingerprint,
        observation_projection_id=market.observation_projection.projection_id,
        frame_projection_id=market.frame_projection.projection_id,
        frame_id=market.frame_projection.frame.frame_id,
        triggering_observation_id=market.frame_projection.triggering_observation_id,
        binding_authority_fingerprint=(
            market.observation_projection.binding_authority.binding_authority_fingerprint
        ),
    )


def build_replay_decision_stack_context(
    *,
    dispatch_context: ReplayDispatchContext,
    event: ReplayTimelineEvent,
    market: ReplayMarketFrameLookupResult,
) -> ReplayDecisionStackContext:
    context_id = build_replay_decision_stack_context_id(
        dispatch_context=dispatch_context,
        event=event,
        market=market,
    )
    return ReplayDecisionStackContext(
        context_id=context_id,
        dispatch_context=dispatch_context,
        event=event,
        market=market,
    )


def build_replay_decision_market_context_reference(
    context: ReplayDecisionStackContext,
) -> ReplayDecisionMarketContextReference:
    context = ReplayDecisionStackContext.model_validate(context.model_dump())
    market = context.market
    observation_projection = market.observation_projection
    frame_projection = market.frame_projection
    reference_id = build_replay_decision_market_context_reference_id(
        context_id=context.context_id,
        dispatch_context=context.dispatch_context,
        market=market,
    )
    return ReplayDecisionMarketContextReference(
        reference_id=reference_id,
        context_id=context.context_id,
        run_id=context.dispatch_context.run_id,
        manifest_id=context.dispatch_context.manifest_id,
        replay_plan_id=context.dispatch_context.replay_plan_id,
        replay_timeline_id=context.dispatch_context.timeline_id,
        timeline_fingerprint_id=context.dispatch_context.timeline_fingerprint_id,
        dispatcher_fingerprint=context.dispatch_context.dispatcher_fingerprint,
        event_id=context.dispatch_context.event_id,
        event_order_index=context.dispatch_context.event_order_index,
        event_time=context.dispatch_context.event_time,
        event_kind=context.dispatch_context.event_kind,
        market_timeline_id=market.descriptor.market_timeline_id,
        lookup_authority_fingerprint=market.descriptor.lookup_authority_fingerprint,
        adapter_fingerprint=market.descriptor.adapter_fingerprint,
        observation_projection_id=observation_projection.projection_id,
        frame_projection_id=frame_projection.projection_id,
        frame_id=frame_projection.frame.frame_id,
        triggering_observation_id=frame_projection.triggering_observation_id,
        binding_authority_fingerprint=(
            observation_projection.binding_authority.binding_authority_fingerprint
        ),
    )


class ReplayDecisionOutputEnvelope(BaseModel):
    """Typed canonical replay output for one DecisionStack decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[2] = 2

    run_id: str
    manifest_id: str
    replay_plan_id: str
    timeline_id: str
    timeline_fingerprint_id: str
    dispatcher_fingerprint: str
    event_id: str
    event_order_index: int
    event_time: datetime
    event_kind: ReplayInputKind

    stack_descriptor: ReplayDecisionStackDescriptor
    market_lookup_descriptor: ReplayMarketFrameLookupDescriptor
    market_context_reference: ReplayDecisionMarketContextReference
    decision_index: int
    decision_kind: ReplayDecisionOutputKind

    decision_intent: DecisionIntent | None = None
    no_trade_decision: NoTradeDecision | None = None

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> object:
        return _validate_schema_version(value, expected=2)

    @field_validator(
        "run_id",
        "manifest_id",
        "replay_plan_id",
        "timeline_id",
        "timeline_fingerprint_id",
        "event_id",
    )
    @classmethod
    def _validate_ids(cls, value: str) -> str:
        return _validate_required_text(value, "replay decision output id")

    @field_validator("dispatcher_fingerprint")
    @classmethod
    def _validate_dispatcher_fingerprint(cls, value: str) -> str:
        return _validate_required_text(value, "dispatcher_fingerprint")

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
        return _revalidate_stack_descriptor(value)

    @field_validator("market_lookup_descriptor", mode="before")
    @classmethod
    def _revalidate_market_lookup_descriptor(
        cls,
        value: object,
    ) -> ReplayMarketFrameLookupDescriptor:
        return _revalidate_market_lookup_descriptor(value)

    @field_validator("market_context_reference", mode="before")
    @classmethod
    def _revalidate_market_context_reference(
        cls,
        value: object,
    ) -> ReplayDecisionMarketContextReference:
        return _revalidate_market_context_reference(value)

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
    def _validate_envelope(self) -> Self:  # noqa: PLR0912
        if self.event_kind not in self.stack_descriptor.supported_event_kinds:
            raise ValueError("event_kind must be supported by stack_descriptor")
        if self.event_kind not in self.market_lookup_descriptor.supported_event_kinds:
            raise ValueError("event_kind must be supported by market_lookup_descriptor")
        if self.timeline_id != self.market_lookup_descriptor.replay_timeline_id:
            raise ValueError("timeline_id must match market lookup descriptor")
        if self.replay_plan_id != self.market_lookup_descriptor.replay_plan_id:
            raise ValueError("replay_plan_id must match market lookup descriptor")
        reference = self.market_context_reference
        reference_values = {
            "run_id": self.run_id,
            "manifest_id": self.manifest_id,
            "replay_plan_id": self.replay_plan_id,
            "replay_timeline_id": self.timeline_id,
            "timeline_fingerprint_id": self.timeline_fingerprint_id,
            "dispatcher_fingerprint": self.dispatcher_fingerprint,
            "event_id": self.event_id,
            "event_order_index": self.event_order_index,
            "event_time": self.event_time,
            "event_kind": self.event_kind,
        }
        for field_name, expected in reference_values.items():
            if getattr(reference, field_name) != expected:
                raise ValueError(
                    f"market context reference {field_name} must match envelope"
                )
        if (
            reference.market_timeline_id
            != self.market_lookup_descriptor.market_timeline_id
        ):
            raise ValueError("market context reference timeline must match lookup")
        if (
            reference.lookup_authority_fingerprint
            != self.market_lookup_descriptor.lookup_authority_fingerprint
        ):
            raise ValueError("market context reference lookup authority must match lookup")
        if (
            reference.adapter_fingerprint
            != self.market_lookup_descriptor.adapter_fingerprint
        ):
            raise ValueError("market context reference adapter must match lookup")

        decision = _populated_decision_for_kind(
            self.decision_kind,
            self.decision_intent,
            self.no_trade_decision,
        )

        expected_id = build_replay_decision_intent_id(
            run_id=self.run_id,
            event_order_index=self.event_order_index,
            event_id=self.event_id,
            decision_handler_fingerprint=build_replay_decision_handler_fingerprint(
                stack_descriptor=self.stack_descriptor,
                market_lookup_descriptor=self.market_lookup_descriptor,
            ),
            market_context_reference_id=reference.reference_id,
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
        "manifest_id": revalidated.manifest_id,
        "replay_plan_id": revalidated.replay_plan_id,
        "timeline_id": revalidated.timeline_id,
        "timeline_fingerprint_id": revalidated.timeline_fingerprint_id,
        "dispatcher_fingerprint": revalidated.dispatcher_fingerprint,
        "event_id": revalidated.event_id,
        "event_order_index": revalidated.event_order_index,
        "event_time": revalidated.event_time,
        "event_kind": revalidated.event_kind,
    }
    for field_name, expected in expected_values.items():
        if getattr(envelope, field_name) != expected:
            raise ValueError(f"decision envelope {field_name} must match output record")
    if revalidated.handler_id != build_replay_decision_handler_fingerprint(
        stack_descriptor=envelope.stack_descriptor,
        market_lookup_descriptor=envelope.market_lookup_descriptor,
    ):
        raise ValueError("output record handler_id must match decision handler fingerprint")
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


def _validate_schema_version(value: object, *, expected: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"schema_version must be the strict integer {expected}")
    if value != expected:
        raise ValueError(f"schema_version must be {expected}")
    return value


def _revalidate_domain_id[T](model_type: type[T], value: object) -> T:
    if isinstance(value, model_type):
        return model_type.model_validate(value.model_dump())  # type: ignore[attr-defined]
    return model_type.model_validate(value)  # type: ignore[attr-defined]


def _revalidate_stack_descriptor(value: object) -> ReplayDecisionStackDescriptor:
    if isinstance(value, ReplayDecisionStackDescriptor):
        return ReplayDecisionStackDescriptor.model_validate(value.model_dump())
    return ReplayDecisionStackDescriptor.model_validate(value)


def _revalidate_dispatch_context(value: object) -> ReplayDispatchContext:
    if isinstance(value, ReplayDispatchContext):
        return ReplayDispatchContext.model_validate(value.model_dump())
    return ReplayDispatchContext.model_validate(value)


def _revalidate_timeline_event(value: object) -> ReplayTimelineEvent:
    if isinstance(value, ReplayTimelineEvent):
        return ReplayTimelineEvent.model_validate(value.model_dump())
    return ReplayTimelineEvent.model_validate(value)


def _revalidate_market_lookup_descriptor(
    value: object,
) -> ReplayMarketFrameLookupDescriptor:
    if isinstance(value, ReplayMarketFrameLookupDescriptor):
        return ReplayMarketFrameLookupDescriptor.model_validate(value.model_dump())
    return ReplayMarketFrameLookupDescriptor.model_validate(value)


def _revalidate_market_lookup_result(value: object) -> ReplayMarketFrameLookupResult:
    if isinstance(value, ReplayMarketFrameLookupResult):
        return ReplayMarketFrameLookupResult.model_validate(value.model_dump())
    return ReplayMarketFrameLookupResult.model_validate(value)


def _revalidate_market_context_reference(
    value: object,
) -> ReplayDecisionMarketContextReference:
    if isinstance(value, ReplayDecisionMarketContextReference):
        return ReplayDecisionMarketContextReference.model_validate(value.model_dump())
    return ReplayDecisionMarketContextReference.model_validate(value)


def _validate_decision_context_semantics(
    *,
    dispatch_context: ReplayDispatchContext,
    event: ReplayTimelineEvent,
    market: ReplayMarketFrameLookupResult,
) -> None:
    if dispatch_context.event_id != event.event_id:
        raise ValueError("dispatch context event_id must match event")
    if dispatch_context.event_order_index != event.order_index:
        raise ValueError("dispatch context event_order_index must match event")
    if dispatch_context.event_time != event.event_time:
        raise ValueError("dispatch context event_time must match event")
    if dispatch_context.event_kind != event.kind:
        raise ValueError("dispatch context event_kind must match event")
    if dispatch_context.timeline_id != market.descriptor.replay_timeline_id:
        raise ValueError("dispatch context timeline_id must match market descriptor")
    if dispatch_context.replay_plan_id != market.descriptor.replay_plan_id:
        raise ValueError("dispatch context replay_plan_id must match market descriptor")
    observation_projection = market.observation_projection
    if event.event_id != observation_projection.event_id:
        raise ValueError("event_id must match market observation projection")
    if event.order_index != observation_projection.event_order_index:
        raise ValueError("event order_index must match market observation projection")
    if event.event_time != observation_projection.event_time:
        raise ValueError("event_time must match market observation projection")
    if event.kind != observation_projection.event_kind:
        raise ValueError("event kind must match market observation projection")


def _validate_dispatch_context_matches_market(
    *,
    dispatch_context: ReplayDispatchContext,
    market: ReplayMarketFrameLookupResult,
) -> None:
    if dispatch_context.timeline_id != market.descriptor.replay_timeline_id:
        raise ValueError("dispatch context timeline_id must match market descriptor")
    if dispatch_context.replay_plan_id != market.descriptor.replay_plan_id:
        raise ValueError("dispatch context replay_plan_id must match market descriptor")
    observation_projection = market.observation_projection
    if dispatch_context.event_id != observation_projection.event_id:
        raise ValueError("dispatch context event_id must match market projection")
    if dispatch_context.event_order_index != observation_projection.event_order_index:
        raise ValueError("dispatch context order index must match market projection")
    if dispatch_context.event_time != observation_projection.event_time:
        raise ValueError("dispatch context event_time must match market projection")
    if dispatch_context.event_kind != observation_projection.event_kind:
        raise ValueError("dispatch context event_kind must match market projection")


def _build_replay_decision_market_context_reference_id_from_fields(  # noqa: PLR0913
    *,
    context_id: ReplayDecisionContextId,
    run_id: str,
    manifest_id: str,
    replay_plan_id: str,
    replay_timeline_id: str,
    timeline_fingerprint_id: str,
    dispatcher_fingerprint: str,
    event_id: str,
    event_order_index: int,
    event_time: datetime,
    event_kind: ReplayInputKind,
    market_timeline_id: ReplayMarketFrameTimelineId,
    lookup_authority_fingerprint: str,
    adapter_fingerprint: str,
    observation_projection_id: ReplayMarketObservationProjectionId,
    frame_projection_id: ReplayMarketFrameProjectionId,
    frame_id: MarketFrameId,
    triggering_observation_id: MarketObservationId,
    binding_authority_fingerprint: str,
) -> ReplayDecisionMarketContextReferenceId:
    material = {
        "schema_version": 1,
        "adapter_fingerprint": _validate_market_adapter_fingerprint(
            adapter_fingerprint
        ),
        "binding_authority_fingerprint": _validate_binding_authority_fingerprint(
            binding_authority_fingerprint
        ),
        "context_id": _validate_replay_decision_context_id(context_id).model_dump(
            mode="json"
        ),
        "dispatcher_fingerprint": _validate_required_text(
            dispatcher_fingerprint,
            "dispatcher_fingerprint",
        ),
        "event_id": _validate_required_text(event_id, "event_id"),
        "event_kind": ReplayInputKind(event_kind).value,
        "event_order_index": _validate_strict_non_negative_int(
            event_order_index,
            "event_order_index",
        ),
        "event_time": ensure_aware_utc(event_time).isoformat(),
        "frame_id": _validate_market_frame_id(frame_id).model_dump(mode="json"),
        "frame_projection_id": _validate_frame_projection_id(
            frame_projection_id
        ).model_dump(mode="json"),
        "lookup_authority_fingerprint": _validate_lookup_authority_fingerprint(
            lookup_authority_fingerprint
        ),
        "manifest_id": _validate_required_text(manifest_id, "manifest_id"),
        "market_timeline_id": _validate_market_timeline_id(
            market_timeline_id
        ).model_dump(mode="json"),
        "observation_projection_id": _validate_observation_projection_id(
            observation_projection_id
        ).model_dump(mode="json"),
        "replay_plan_id": _validate_required_text(replay_plan_id, "replay_plan_id"),
        "replay_timeline_id": _validate_required_text(
            replay_timeline_id,
            "replay_timeline_id",
        ),
        "run_id": _validate_required_text(run_id, "run_id"),
        "timeline_fingerprint_id": _validate_required_text(
            timeline_fingerprint_id,
            "timeline_fingerprint_id",
        ),
        "triggering_observation_id": _validate_market_observation_id(
            triggering_observation_id
        ).model_dump(mode="json"),
    }
    return ReplayDecisionMarketContextReferenceId.from_str(
        "replay-decision-market-context-reference:"
        f"{_sha256_text(_canonical_json(material))}"
    )


def _validate_replay_decision_context_id(value: object) -> ReplayDecisionContextId:
    context_id = _revalidate_domain_id(ReplayDecisionContextId, value)
    if not _REPLAY_DECISION_CONTEXT_ID_RE.fullmatch(str(context_id)):
        raise ValueError("context_id must match replay-decision-context:<64 hex>")
    return context_id


def _validate_market_context_reference_id(
    value: object,
) -> ReplayDecisionMarketContextReferenceId:
    reference_id = _revalidate_domain_id(ReplayDecisionMarketContextReferenceId, value)
    if not _REPLAY_DECISION_MARKET_CONTEXT_REFERENCE_ID_RE.fullmatch(str(reference_id)):
        raise ValueError(
            "reference_id must match "
            "replay-decision-market-context-reference:<64 hex>"
        )
    return reference_id


def _validate_market_timeline_id(value: object) -> ReplayMarketFrameTimelineId:
    timeline_id = _revalidate_domain_id(ReplayMarketFrameTimelineId, value)
    if not _REPLAY_MARKET_TIMELINE_ID_RE.fullmatch(str(timeline_id)):
        raise ValueError("market_timeline_id must match replay-market-frame-timeline:<64 hex>")
    return timeline_id


def _validate_observation_projection_id(
    value: object,
) -> ReplayMarketObservationProjectionId:
    projection_id = _revalidate_domain_id(ReplayMarketObservationProjectionId, value)
    if not _REPLAY_MARKET_OBSERVATION_PROJECTION_ID_RE.fullmatch(str(projection_id)):
        raise ValueError(
            "observation_projection_id must match "
            "replay-market-observation-projection:<64 hex>"
        )
    return projection_id


def _validate_frame_projection_id(value: object) -> ReplayMarketFrameProjectionId:
    projection_id = _revalidate_domain_id(ReplayMarketFrameProjectionId, value)
    if not _REPLAY_MARKET_FRAME_PROJECTION_ID_RE.fullmatch(str(projection_id)):
        raise ValueError(
            "frame_projection_id must match replay-market-frame-projection:<64 hex>"
        )
    return projection_id


def _validate_market_frame_id(value: object) -> MarketFrameId:
    frame_id = _revalidate_domain_id(MarketFrameId, value)
    if not _MARKET_FRAME_ID_RE.fullmatch(str(frame_id)):
        raise ValueError("frame_id must match market-frame:<64 hex>")
    return frame_id


def _validate_market_observation_id(value: object) -> MarketObservationId:
    observation_id = _revalidate_domain_id(MarketObservationId, value)
    if not _MARKET_OBSERVATION_ID_RE.fullmatch(str(observation_id)):
        raise ValueError("triggering_observation_id must match market-observation:<64 hex>")
    return observation_id


def _validate_decision_handler_fingerprint(value: str) -> str:
    value = _validate_required_text(value, "decision_handler_fingerprint")
    if not _DECISION_HANDLER_FINGERPRINT_RE.fullmatch(value):
        raise ValueError(
            "decision_handler_fingerprint must match "
            "replay-decision-handler:<64 lowercase hex>"
        )
    return value


def _validate_market_adapter_fingerprint(value: str) -> str:
    value = _validate_required_text(value, "adapter_fingerprint")
    if not _REPLAY_MARKET_ADAPTER_FINGERPRINT_RE.fullmatch(value):
        raise ValueError("adapter_fingerprint must match replay-market-adapter:<64 hex>")
    return value


def _validate_binding_authority_fingerprint(value: str) -> str:
    value = _validate_required_text(value, "binding_authority_fingerprint")
    if not _REPLAY_MARKET_BINDING_AUTHORITY_FINGERPRINT_RE.fullmatch(value):
        raise ValueError(
            "binding_authority_fingerprint must match "
            "replay-market-binding-authority:<64 hex>"
        )
    return value


def _validate_lookup_authority_fingerprint(value: str) -> str:
    value = _validate_required_text(value, "lookup_authority_fingerprint")
    if not _REPLAY_MARKET_LOOKUP_AUTHORITY_FINGERPRINT_RE.fullmatch(value):
        raise ValueError(
            "lookup_authority_fingerprint must match "
            "replay-market-frame-lookup-authority:<64 hex>"
        )
    return value


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
