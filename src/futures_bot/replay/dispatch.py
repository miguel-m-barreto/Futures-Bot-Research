"""Deterministic local replay event dispatcher."""
from __future__ import annotations

import hashlib

from futures_bot.domain.replay import (
    ReplayDispatchContext,
    ReplayDispatchHandlerDescriptor,
    ReplayEventDispatchPlan,
    ReplayEventOutputRecord,
    ReplayHandlerOutputProposal,
    ReplayInputKind,
    ReplayTimelineEvent,
    build_replay_dispatcher_fingerprint,
    build_replay_event_dispatch_receipt_id,
    build_replay_event_output_record_id,
)
from futures_bot.ports.replay import ReplayEventHandlerPort


class LocalDeterministicReplayDispatcher:
    """Synchronous deterministic registry for replay event handlers."""

    def __init__(self, handlers: tuple[ReplayEventHandlerPort, ...]) -> None:
        descriptors = tuple(_descriptor_for_handler(handler) for handler in handlers)
        handler_ids = [descriptor.handler_id for descriptor in descriptors]
        if len(handler_ids) != len(set(handler_ids)):
            raise ValueError("duplicate replay handler IDs are not allowed")
        ordered_pairs = sorted(
            zip(descriptors, handlers, strict=True),
            key=lambda pair: (pair[0].handler_id, pair[0].handler_version),
        )
        self._descriptors = tuple(pair[0] for pair in ordered_pairs)
        self._handlers = tuple(pair[1] for pair in ordered_pairs)
        self._dispatcher_fingerprint = build_replay_dispatcher_fingerprint(
            self._descriptors
        )

    @property
    def dispatcher_fingerprint(self) -> str:
        """Stable fingerprint for this handler registry."""
        return self._dispatcher_fingerprint

    @property
    def descriptors(self) -> tuple[ReplayDispatchHandlerDescriptor, ...]:
        """Return deterministic handler descriptors."""
        return tuple(
            ReplayDispatchHandlerDescriptor.model_validate(descriptor.model_dump())
            for descriptor in self._descriptors
        )

    def selected_descriptors_for(
        self,
        event_kind: ReplayInputKind,
    ) -> tuple[ReplayDispatchHandlerDescriptor, ...]:
        """Return registry descriptors selected for event_kind in execution order."""
        return tuple(
            ReplayDispatchHandlerDescriptor.model_validate(descriptor.model_dump())
            for descriptor in self._descriptors
            if event_kind in descriptor.supported_event_kinds
        )

    def plan_dispatch(
        self,
        context: ReplayDispatchContext,
        event: ReplayTimelineEvent,
        dispatch_receipt_id: str,
    ) -> ReplayEventDispatchPlan:
        """Plan deterministic handler output records for one event without writing."""
        context = _revalidate_context(context)
        event = _revalidate_event(event)
        _validate_context_matches_event(context, event)
        if context.dispatcher_fingerprint != self._dispatcher_fingerprint:
            raise ValueError("dispatch context dispatcher_fingerprint does not match dispatcher")
        expected_receipt_id = build_replay_event_dispatch_receipt_id(
            context.run_id,
            context.event_order_index,
            context.event_id,
        )
        if dispatch_receipt_id != expected_receipt_id:
            raise ValueError("dispatch_receipt_id must match deterministic replay dispatch ID")
        selected_descriptors = self.selected_descriptors_for(context.event_kind)
        selected_ids = {descriptor.handler_id for descriptor in selected_descriptors}
        selected = tuple(
            (descriptor, handler)
            for descriptor, handler in zip(self._descriptors, self._handlers, strict=True)
            if descriptor.handler_id in selected_ids
        )
        output_records: list[ReplayEventOutputRecord] = []
        for descriptor, handler in selected:
            try:
                proposals = handler.handle(context, event)
            except Exception as exc:
                raise RuntimeError(
                    f"replay handler {descriptor.handler_id!r} failed"
                ) from exc
            if not isinstance(proposals, tuple):
                raise ValueError(
                    f"replay handler {descriptor.handler_id!r} must return a tuple"
                )
            revalidated = tuple(
                _revalidate_proposal(descriptor.handler_id, proposal)
                for proposal in proposals
            )
            for output_index, proposal in enumerate(revalidated):
                payload_sha256 = _sha256_payload(proposal.canonical_payload)
                output_records.append(
                    ReplayEventOutputRecord(
                        output_record_id=build_replay_event_output_record_id(
                            run_id=context.run_id,
                            event_order_index=context.event_order_index,
                            event_id=context.event_id,
                            handler_id=descriptor.handler_id,
                            handler_version=descriptor.handler_version,
                            handler_output_index=output_index,
                            output_kind=proposal.output_kind,
                            payload_sha256=payload_sha256,
                        ),
                        dispatch_receipt_id=dispatch_receipt_id,
                        run_id=context.run_id,
                        manifest_id=context.manifest_id,
                        replay_plan_id=context.replay_plan_id,
                        timeline_id=context.timeline_id,
                        timeline_fingerprint_id=context.timeline_fingerprint_id,
                        dispatcher_fingerprint=context.dispatcher_fingerprint,
                        event_id=context.event_id,
                        event_order_index=context.event_order_index,
                        event_time=context.event_time,
                        event_kind=context.event_kind,
                        handler_id=descriptor.handler_id,
                        handler_version=descriptor.handler_version,
                        handler_output_index=output_index,
                        output_kind=proposal.output_kind,
                        canonical_payload=proposal.canonical_payload,
                        payload_sha256=payload_sha256,
                    )
                )
        return ReplayEventDispatchPlan(
            context=context,
            handler_ids=tuple(descriptor.handler_id for descriptor, _ in selected),
            output_records=tuple(output_records),
        )


def _descriptor_for_handler(
    handler: ReplayEventHandlerPort,
) -> ReplayDispatchHandlerDescriptor:
    return ReplayDispatchHandlerDescriptor(
        handler_id=handler.handler_id,
        handler_version=handler.handler_version,
        supported_event_kinds=handler.supported_event_kinds,
    )


def _revalidate_context(context: object) -> ReplayDispatchContext:
    if isinstance(context, ReplayDispatchContext):
        return ReplayDispatchContext.model_validate(context.model_dump())
    return ReplayDispatchContext.model_validate(context)


def _revalidate_event(event: object) -> ReplayTimelineEvent:
    if isinstance(event, ReplayTimelineEvent):
        return ReplayTimelineEvent.model_validate(event.model_dump())
    return ReplayTimelineEvent.model_validate(event)


def _revalidate_proposal(
    handler_id: str,
    proposal: object,
) -> ReplayHandlerOutputProposal:
    try:
        if isinstance(proposal, ReplayHandlerOutputProposal):
            return ReplayHandlerOutputProposal.model_validate(proposal.model_dump())
        return ReplayHandlerOutputProposal.model_validate(proposal)
    except Exception as exc:
        raise ValueError(
            f"replay handler {handler_id!r} returned invalid output proposal"
        ) from exc


def _validate_context_matches_event(
    context: ReplayDispatchContext,
    event: ReplayTimelineEvent,
) -> None:
    if context.event_id != event.event_id:
        raise ValueError("dispatch context event_id does not match event")
    if context.event_order_index != event.order_index:
        raise ValueError("dispatch context event_order_index does not match event")
    if context.event_time != event.event_time:
        raise ValueError("dispatch context event_time does not match event")
    if context.event_kind != event.kind:
        raise ValueError("dispatch context event_kind does not match event")


def _sha256_payload(canonical_payload: str) -> str:
    return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
