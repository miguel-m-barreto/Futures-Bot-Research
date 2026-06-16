"""Local deterministic replay runtime stepper.

Metadata-only runtime foundation: no strategy execution, no order execution,
and no ledger mutation.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from futures_bot.domain.replay import (
    ReplayArtifactFingerprintStatus,
    ReplayArtifactKind,
    ReplayDispatchContext,
    ReplayDispatchHandlerDescriptor,
    ReplayEventDispatchPlan,
    ReplayEventDispatchReceipt,
    ReplayEventOutputRecord,
    ReplayRunManifestStatus,
    ReplayRunState,
    ReplayRunStatus,
    ReplayRunStepResult,
    ReplayTimeline,
    ReplayTimelineEvent,
    ReplayTimelineStatus,
    build_replay_dispatcher_fingerprint,
    build_replay_event_dispatch_receipt_id,
)
from futures_bot.ports.replay import (
    ReplayArtifactFingerprintStorePort,
    ReplayEventDispatchReceiptStorePort,
    ReplayEventOutputRecordStorePort,
    ReplayRunManifestStorePort,
    ReplayRunStateStorePort,
    ReplayTimelineStorePort,
)
from futures_bot.replay.dispatch import LocalDeterministicReplayDispatcher


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LocalDeterministicReplayRuntime:
    """Bounded deterministic runtime stepper for replay timelines."""

    def __init__(  # noqa: PLR0913 - explicit runtime dependency boundary
        self,
        *,
        manifest_store: ReplayRunManifestStorePort,
        timeline_store: ReplayTimelineStorePort,
        fingerprint_store: ReplayArtifactFingerprintStorePort,
        run_store: ReplayRunStateStorePort,
        receipt_store: ReplayEventDispatchReceiptStorePort,
        dispatcher: LocalDeterministicReplayDispatcher,
        output_store: ReplayEventOutputRecordStorePort,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._manifest_store = manifest_store
        self._timeline_store = timeline_store
        self._fingerprint_store = fingerprint_store
        self._run_store = run_store
        self._receipt_store = receipt_store
        self._dispatcher = dispatcher
        self._output_store = output_store
        self._now: Callable[[], datetime] = now if now is not None else _utcnow

    def create_run(  # noqa: PLR0912 - explicit binding validation matrix
        self,
        run_id: str,
        manifest_id: str,
        timeline_id: str,
        timeline_fingerprint_id: str,
    ) -> ReplayRunState:
        """Create a runtime run from a PLANNED manifest and exact timeline fingerprint."""
        dispatcher_fingerprint = _validated_dispatcher_fingerprint(self._dispatcher)
        existing = self._run_store.load(run_id)
        if existing is not None:
            _require_existing_run_binding(
                existing,
                manifest_id,
                timeline_id,
                timeline_fingerprint_id,
                dispatcher_fingerprint,
            )
            return existing

        manifest = self._manifest_store.load(manifest_id)
        if manifest is None:
            raise ValueError(f"replay run manifest not found: {manifest_id!r}")
        if manifest.status is not ReplayRunManifestStatus.PLANNED:
            raise ValueError(
                "replay run manifest must be PLANNED, "
                f"got {manifest.status.value!r}"
            )

        timeline = self._timeline_store.load(timeline_id)
        if timeline is None:
            raise ValueError(f"replay timeline not found: {timeline_id!r}")
        if timeline.status is not ReplayTimelineStatus.BUILT:
            raise ValueError(
                f"replay timeline must be BUILT, got {timeline.status.value!r}"
            )
        if timeline.replay_plan_id != manifest.replay_plan_id:
            raise ValueError("timeline replay_plan_id must match manifest replay_plan_id")
        if timeline_fingerprint_id not in manifest.fingerprint_ids:
            raise ValueError(
                "timeline_fingerprint_id must be present in manifest fingerprint_ids"
            )

        fingerprint = self._fingerprint_store.load(timeline_fingerprint_id)
        if fingerprint is None:
            raise ValueError(
                f"replay artifact fingerprint not found: {timeline_fingerprint_id!r}"
            )
        if fingerprint.status is not ReplayArtifactFingerprintStatus.GENERATED:
            raise ValueError(
                "timeline fingerprint must be GENERATED, "
                f"got {fingerprint.status.value!r}"
            )
        if fingerprint.artifact_kind is not ReplayArtifactKind.TIMELINE:
            raise ValueError("timeline fingerprint artifact_kind must be TIMELINE")
        if fingerprint.artifact_id != timeline_id:
            raise ValueError("timeline fingerprint artifact_id must match timeline_id")
        if fingerprint.replay_plan_id != manifest.replay_plan_id:
            raise ValueError(
                "timeline fingerprint replay_plan_id must match manifest replay_plan_id"
            )
        if fingerprint.generated_at > manifest.created_at:
            raise ValueError(
                "timeline fingerprint generated_at must not be after manifest created_at"
            )
        if timeline.created_at > fingerprint.generated_at:
            raise ValueError(
                "timeline created_at must not be after timeline fingerprint generated_at"
            )

        now = self._now()
        if manifest.created_at > now:
            raise ValueError("manifest created_at must not be after replay run created_at")
        state = ReplayRunState(
            run_id=run_id,
            manifest_id=manifest.manifest_id,
            replay_plan_id=manifest.replay_plan_id,
            timeline_id=timeline.timeline_id,
            timeline_fingerprint_id=fingerprint.fingerprint_id,
            dispatcher_fingerprint=dispatcher_fingerprint,
            created_at=now,
            updated_at=now,
            status=ReplayRunStatus.CREATED,
            revision=0,
            total_event_count=len(timeline.events),
            next_event_index=0,
            processed_event_count=0,
        )
        self._run_store.create(state)
        return state

    def start_run(self, run_id: str) -> ReplayRunStepResult:
        """Start a CREATED run, completing immediately when no events exist."""
        state = self._load_state(run_id)
        if state.status is not ReplayRunStatus.CREATED:
            raise ValueError(f"only CREATED runs can start, got {state.status.value!r}")
        _require_matching_dispatcher(self._dispatcher, state)
        now = self._now()
        _require_non_regressing_runtime_time(now, state)
        status = (
            ReplayRunStatus.COMPLETED
            if state.total_event_count == 0
            else ReplayRunStatus.RUNNING
        )
        replacement = _validated_state_copy(
            state,
            {
                "updated_at": now,
                "started_at": now,
                "completed_at": now if status is ReplayRunStatus.COMPLETED else None,
                "status": status,
                "revision": state.revision + 1,
            },
        )
        result = _step_result(state, replacement)
        self._run_store.replace(replacement, expected_revision=state.revision)
        return result

    def step_run(self, run_id: str, max_events: int = 1) -> ReplayRunStepResult:
        """Process at most max_events timeline events from the run's next index."""
        _validate_max_events(max_events)
        state = self._load_state(run_id)
        if state.status is not ReplayRunStatus.RUNNING:
            raise ValueError(f"only RUNNING runs can step, got {state.status.value!r}")
        dispatcher_fingerprint = _require_matching_dispatcher(self._dispatcher, state)
        timeline = self._load_bound_timeline(state)
        remaining = state.total_event_count - state.next_event_index
        if remaining <= 0:
            raise ValueError("RUNNING replay run has no remaining events to process")

        count = min(max_events, remaining)
        events = timeline.events[state.next_event_index : state.next_event_index + count]
        plans = tuple(
            _dispatch_plan(self._dispatcher, state, event)
            for event in events
        )
        receipts = tuple(
            _dispatch_receipt(state, event, plan)
            for event, plan in zip(events, plans, strict=True)
        )
        _plans, receipts, output_records = _validate_dispatch_bundles(
            self._dispatcher,
            dispatcher_fingerprint,
            state,
            events,
            plans,
            receipts,
        )
        last_event = events[-1]
        next_event_index = state.next_event_index + count
        completed = next_event_index == state.total_event_count
        now = self._now()
        _require_non_regressing_runtime_time(now, state)

        replacement = _validated_state_copy(
            state,
            {
                "updated_at": now,
                "completed_at": now if completed else None,
                "status": (
                    ReplayRunStatus.COMPLETED
                    if completed
                    else ReplayRunStatus.RUNNING
                ),
                "revision": state.revision + 1,
                "next_event_index": next_event_index,
                "processed_event_count": next_event_index,
                "last_processed_event_id": last_event.event_id,
            },
        )
        result = _step_result(state, replacement, receipts)
        _preflight_append_only_writes(
            self._output_store,
            self._receipt_store,
            output_records,
            receipts,
        )
        for record in output_records:
            self._output_store.save(record)
        for receipt in receipts:
            self._receipt_store.save(receipt)
        self._run_store.replace(replacement, expected_revision=state.revision)
        return result

    def pause_run(self, run_id: str) -> ReplayRunStepResult:
        """Pause a RUNNING replay run."""
        state = self._load_state(run_id)
        if state.status is not ReplayRunStatus.RUNNING:
            raise ValueError(f"only RUNNING runs can pause, got {state.status.value!r}")
        _require_matching_dispatcher(self._dispatcher, state)
        now = self._now()
        _require_non_regressing_runtime_time(now, state)
        replacement = _validated_state_copy(
            state,
            {
                "updated_at": now,
                "paused_at": now,
                "status": ReplayRunStatus.PAUSED,
                "revision": state.revision + 1,
            },
        )
        result = _step_result(state, replacement)
        self._run_store.replace(replacement, expected_revision=state.revision)
        return result

    def resume_run(self, run_id: str) -> ReplayRunStepResult:
        """Resume a PAUSED replay run."""
        state = self._load_state(run_id)
        if state.status is not ReplayRunStatus.PAUSED:
            raise ValueError(f"only PAUSED runs can resume, got {state.status.value!r}")
        _require_matching_dispatcher(self._dispatcher, state)
        now = self._now()
        _require_non_regressing_runtime_time(now, state)
        replacement = _validated_state_copy(
            state,
            {
                "updated_at": now,
                "paused_at": None,
                "status": ReplayRunStatus.RUNNING,
                "revision": state.revision + 1,
            },
        )
        result = _step_result(state, replacement)
        self._run_store.replace(replacement, expected_revision=state.revision)
        return result

    def load_run(self, run_id: str) -> ReplayRunState | None:
        """Return replay runtime state by run_id, or None."""
        return self._run_store.load(run_id)

    def runs_for_replay_plan(self, replay_plan_id: str) -> tuple[ReplayRunState, ...]:
        """Return runtime runs for replay_plan_id."""
        return self._run_store.list_for_replay_plan(replay_plan_id)

    def receipts_for_run(self, run_id: str) -> tuple[ReplayEventDispatchReceipt, ...]:
        """Return dispatch receipts for run_id."""
        return self._receipt_store.list_for_run(run_id)

    def outputs_for_run(self, run_id: str) -> tuple[ReplayEventOutputRecord, ...]:
        """Return handler output records for run_id."""
        return self._output_store.list_for_run(run_id)

    def outputs_for_event(
        self,
        run_id: str,
        event_order_index: int,
    ) -> tuple[ReplayEventOutputRecord, ...]:
        """Return handler output records for one run event."""
        return self._output_store.list_for_event(run_id, event_order_index)

    def _load_state(self, run_id: str) -> ReplayRunState:
        state = self._run_store.load(run_id)
        if state is None:
            raise ValueError(f"replay run state not found: {run_id!r}")
        return state

    def _load_bound_timeline(self, state: ReplayRunState) -> ReplayTimeline:
        timeline = self._timeline_store.load(state.timeline_id)
        if timeline is None:
            raise ValueError(f"bound replay timeline not found: {state.timeline_id!r}")
        if timeline.status is not ReplayTimelineStatus.BUILT:
            raise ValueError(
                f"bound replay timeline must be BUILT, got {timeline.status.value!r}"
            )
        if timeline.timeline_id != state.timeline_id:
            raise ValueError("loaded replay timeline id does not match run state")
        if timeline.replay_plan_id != state.replay_plan_id:
            raise ValueError("bound replay timeline replay_plan_id does not match run state")
        if len(timeline.events) != state.total_event_count:
            raise ValueError("bound replay timeline event count does not match run state")
        if state.next_event_index > 0:
            previous_event = timeline.events[state.next_event_index - 1]
            if state.last_processed_event_id != previous_event.event_id:
                raise ValueError(
                    "last_processed_event_id must match the bound timeline "
                    "event before next_event_index"
                )
        for position, event in enumerate(timeline.events):
            if event.order_index != position:
                raise ValueError("timeline event order_index must equal tuple position")
        return timeline


def _require_existing_run_binding(
    existing: ReplayRunState,
    manifest_id: str,
    timeline_id: str,
    timeline_fingerprint_id: str,
    dispatcher_fingerprint: str,
) -> None:
    if (
        existing.manifest_id != manifest_id
        or existing.timeline_id != timeline_id
        or existing.timeline_fingerprint_id != timeline_fingerprint_id
        or existing.dispatcher_fingerprint != dispatcher_fingerprint
    ):
        raise ValueError("replay run_id already exists with a conflicting binding")


def _require_matching_dispatcher(
    dispatcher: LocalDeterministicReplayDispatcher,
    state: ReplayRunState,
) -> str:
    dispatcher_fingerprint = _validated_dispatcher_fingerprint(dispatcher)
    if dispatcher_fingerprint != state.dispatcher_fingerprint:
        raise ValueError("runtime dispatcher fingerprint does not match run state")
    return dispatcher_fingerprint


def _validated_dispatcher_fingerprint(
    dispatcher: LocalDeterministicReplayDispatcher,
) -> str:
    descriptors = _validated_dispatcher_descriptors(dispatcher)
    fingerprint = build_replay_dispatcher_fingerprint(descriptors)
    if fingerprint != dispatcher.dispatcher_fingerprint:
        raise ValueError("dispatcher descriptors do not match dispatcher fingerprint")
    return fingerprint


def _validated_dispatcher_descriptors(
    dispatcher: LocalDeterministicReplayDispatcher,
) -> tuple[ReplayDispatchHandlerDescriptor, ...]:
    return tuple(
        ReplayDispatchHandlerDescriptor.model_validate(descriptor.model_dump())
        for descriptor in dispatcher.descriptors
    )


def _validated_selected_descriptors_for(
    dispatcher: LocalDeterministicReplayDispatcher,
    event: ReplayTimelineEvent,
) -> tuple[ReplayDispatchHandlerDescriptor, ...]:
    descriptors = _validated_dispatcher_descriptors(dispatcher)
    expected = tuple(
        descriptor
        for descriptor in descriptors
        if event.kind in descriptor.supported_event_kinds
    )
    selected = tuple(
        ReplayDispatchHandlerDescriptor.model_validate(descriptor.model_dump())
        for descriptor in dispatcher.selected_descriptors_for(event.kind)
    )
    if selected != expected:
        raise ValueError(
            "selected dispatcher descriptors must match dispatcher registry"
        )
    return expected


def _require_non_regressing_runtime_time(
    captured_now: datetime,
    state: ReplayRunState,
) -> None:
    if captured_now < state.updated_at:
        raise ValueError("runtime clock regression: captured time is before state updated_at")


def _validated_state_copy(
    state: ReplayRunState,
    update: dict[str, object],
) -> ReplayRunState:
    return ReplayRunState.model_validate(state.model_copy(update=update).model_dump())


def _validate_max_events(max_events: object) -> None:
    if isinstance(max_events, bool) or not isinstance(max_events, int):
        raise ValueError("max_events must be a strict positive integer")
    if max_events <= 0:
        raise ValueError("max_events must be > 0")


def _dispatch_plan(
    dispatcher: LocalDeterministicReplayDispatcher,
    state: ReplayRunState,
    event: ReplayTimelineEvent,
) -> ReplayEventDispatchPlan:
    receipt_id = build_replay_event_dispatch_receipt_id(
        state.run_id,
        event.order_index,
        event.event_id,
    )
    context = ReplayDispatchContext(
        run_id=state.run_id,
        manifest_id=state.manifest_id,
        replay_plan_id=state.replay_plan_id,
        timeline_id=state.timeline_id,
        timeline_fingerprint_id=state.timeline_fingerprint_id,
        dispatcher_fingerprint=state.dispatcher_fingerprint,
        event_id=event.event_id,
        event_order_index=event.order_index,
        event_time=event.event_time,
        event_kind=event.kind,
    )
    return dispatcher.plan_dispatch(context, event, receipt_id)


def _preflight_append_only_writes(
    output_store: ReplayEventOutputRecordStorePort,
    receipt_store: ReplayEventDispatchReceiptStorePort,
    output_records: tuple[ReplayEventOutputRecord, ...],
    receipts: tuple[ReplayEventDispatchReceipt, ...],
) -> None:
    for receipt in receipts:
        existing = receipt_store.load(receipt.receipt_id)
        if existing is not None and existing != receipt:
            raise ValueError(f"receipt_id conflict for {receipt.receipt_id!r}")
    for record in output_records:
        existing = output_store.load(record.output_record_id)
        if existing is not None and existing != record:
            raise ValueError(f"output_record_id conflict for {record.output_record_id!r}")


def _validate_dispatch_bundles(  # noqa: PLR0913 - explicit bundle validation inputs
    dispatcher: LocalDeterministicReplayDispatcher,
    dispatcher_fingerprint: str,
    state: ReplayRunState,
    events: tuple[ReplayTimelineEvent, ...],
    plans: tuple[ReplayEventDispatchPlan, ...],
    receipts: tuple[ReplayEventDispatchReceipt, ...],
) -> tuple[
    tuple[ReplayEventDispatchPlan, ...],
    tuple[ReplayEventDispatchReceipt, ...],
    tuple[ReplayEventOutputRecord, ...],
]:
    if len(events) != len(plans) or len(events) != len(receipts):
        raise ValueError("dispatch bundle counts must match selected events")
    revalidated_plans = tuple(
        ReplayEventDispatchPlan.model_validate(plan.model_dump())
        for plan in plans
    )
    revalidated_receipts = tuple(
        ReplayEventDispatchReceipt.model_validate(receipt.model_dump())
        for receipt in receipts
    )
    for event, plan, receipt in zip(
        events,
        revalidated_plans,
        revalidated_receipts,
        strict=True,
    ):
        _validate_dispatch_bundle(
            dispatcher,
            dispatcher_fingerprint,
            state,
            event,
            plan,
            receipt,
        )
    output_records = tuple(
        record
        for plan in revalidated_plans
        for record in plan.output_records
    )
    return revalidated_plans, revalidated_receipts, output_records


def _validate_dispatch_bundle(  # noqa: PLR0913 - explicit bundle validation inputs
    dispatcher: LocalDeterministicReplayDispatcher,
    dispatcher_fingerprint: str,
    state: ReplayRunState,
    event: ReplayTimelineEvent,
    plan: ReplayEventDispatchPlan,
    receipt: ReplayEventDispatchReceipt,
) -> None:
    expected_descriptors = _validated_selected_descriptors_for(dispatcher, event)
    expected_handler_ids = tuple(
        descriptor.handler_id for descriptor in expected_descriptors
    )
    if plan.handler_ids != expected_handler_ids:
        raise ValueError(
            "dispatch plan handler_ids must match selected dispatcher handlers"
        )
    expected_by_id = {
        descriptor.handler_id: descriptor for descriptor in expected_descriptors
    }
    context = plan.context
    _require_context_matches_state_event(context, state, event)
    _require_receipt_matches_state_event(receipt, state, event)
    if context.dispatcher_fingerprint != dispatcher_fingerprint:
        raise ValueError("dispatch plan context dispatcher_fingerprint must match dispatcher")
    if receipt.dispatcher_fingerprint != dispatcher_fingerprint:
        raise ValueError("dispatch receipt dispatcher_fingerprint must match run state")
    if receipt.handler_ids != plan.handler_ids:
        raise ValueError("dispatch receipt handler_ids must match dispatch plan")
    plan_output_record_ids = tuple(
        record.output_record_id for record in plan.output_records
    )
    if receipt.output_record_ids != plan_output_record_ids:
        raise ValueError(
            "dispatch receipt output_record_ids must match dispatch plan output records"
        )
    for record in plan.output_records:
        expected_descriptor = expected_by_id.get(record.handler_id)
        if expected_descriptor is None:
            raise ValueError("output record handler_id must match dispatcher descriptor")
        if record.handler_version != expected_descriptor.handler_version:
            raise ValueError(
                "output record handler_version must match dispatcher descriptor"
            )
        if record.dispatch_receipt_id != receipt.receipt_id:
            raise ValueError(
                "output record dispatch_receipt_id must match dispatch receipt"
            )
        _require_output_record_matches_receipt(record, receipt)


def _require_context_matches_state_event(
    context: ReplayDispatchContext,
    state: ReplayRunState,
    event: ReplayTimelineEvent,
) -> None:
    comparisons = {
        "run_id": state.run_id,
        "manifest_id": state.manifest_id,
        "replay_plan_id": state.replay_plan_id,
        "timeline_id": state.timeline_id,
        "timeline_fingerprint_id": state.timeline_fingerprint_id,
        "dispatcher_fingerprint": state.dispatcher_fingerprint,
        "event_id": event.event_id,
        "event_order_index": event.order_index,
        "event_time": event.event_time,
        "event_kind": event.kind,
    }
    for field_name, expected in comparisons.items():
        if getattr(context, field_name) != expected:
            raise ValueError(f"dispatch plan context {field_name} must match run event")


def _require_receipt_matches_state_event(
    receipt: ReplayEventDispatchReceipt,
    state: ReplayRunState,
    event: ReplayTimelineEvent,
) -> None:
    comparisons = {
        "run_id": state.run_id,
        "manifest_id": state.manifest_id,
        "replay_plan_id": state.replay_plan_id,
        "timeline_id": state.timeline_id,
        "timeline_fingerprint_id": state.timeline_fingerprint_id,
        "dispatcher_fingerprint": state.dispatcher_fingerprint,
        "event_id": event.event_id,
        "event_order_index": event.order_index,
        "event_time": event.event_time,
        "event_kind": event.kind,
    }
    for field_name, expected in comparisons.items():
        if getattr(receipt, field_name) != expected:
            raise ValueError(f"dispatch receipt {field_name} must match run event")


def _require_output_record_matches_receipt(
    record: ReplayEventOutputRecord,
    receipt: ReplayEventDispatchReceipt,
) -> None:
    comparisons = {
        "run_id": receipt.run_id,
        "manifest_id": receipt.manifest_id,
        "replay_plan_id": receipt.replay_plan_id,
        "timeline_id": receipt.timeline_id,
        "timeline_fingerprint_id": receipt.timeline_fingerprint_id,
        "dispatcher_fingerprint": receipt.dispatcher_fingerprint,
        "event_id": receipt.event_id,
        "event_order_index": receipt.event_order_index,
        "event_time": receipt.event_time,
        "event_kind": receipt.event_kind,
    }
    for field_name, expected in comparisons.items():
        if getattr(record, field_name) != expected:
            raise ValueError(f"output record {field_name} must match dispatch receipt")


def _dispatch_receipt(
    state: ReplayRunState,
    event: ReplayTimelineEvent,
    plan: ReplayEventDispatchPlan,
) -> ReplayEventDispatchReceipt:
    return ReplayEventDispatchReceipt(
        receipt_id=build_replay_event_dispatch_receipt_id(
            state.run_id,
            event.order_index,
            event.event_id,
        ),
        run_id=state.run_id,
        manifest_id=state.manifest_id,
        replay_plan_id=state.replay_plan_id,
        timeline_id=state.timeline_id,
        timeline_fingerprint_id=state.timeline_fingerprint_id,
        dispatcher_fingerprint=state.dispatcher_fingerprint,
        event_id=event.event_id,
        event_order_index=event.order_index,
        event_time=event.event_time,
        event_kind=event.kind,
        handler_ids=plan.handler_ids,
        output_record_ids=tuple(record.output_record_id for record in plan.output_records),
    )


def _step_result(
    previous: ReplayRunState,
    current: ReplayRunState,
    receipts: tuple[ReplayEventDispatchReceipt, ...] = (),
) -> ReplayRunStepResult:
    return ReplayRunStepResult(
        run_id=current.run_id,
        previous_status=previous.status,
        current_status=current.status,
        previous_revision=previous.revision,
        current_revision=current.revision,
        previous_next_event_index=previous.next_event_index,
        previous_processed_event_count=previous.processed_event_count,
        processed_receipts=receipts,
        next_event_index=current.next_event_index,
        processed_event_count=current.processed_event_count,
        total_event_count=current.total_event_count,
        completed=current.status is ReplayRunStatus.COMPLETED,
    )
