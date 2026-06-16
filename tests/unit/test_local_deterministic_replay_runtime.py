from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from futures_bot.domain.replay import (
    ReplayArtifactFingerprint,
    ReplayArtifactFingerprintStatus,
    ReplayArtifactHashAlgorithm,
    ReplayArtifactKind,
    ReplayDispatchContext,
    ReplayDispatchHandlerDescriptor,
    ReplayEventDispatchPlan,
    ReplayEventOutputRecord,
    ReplayHandlerOutputProposal,
    ReplayInputKind,
    ReplayInstrumentRef,
    ReplayOrderingPolicy,
    ReplayReadinessStatus,
    ReplayRunIntentKind,
    ReplayRunManifest,
    ReplayRunManifestStatus,
    ReplayRunReadinessBinding,
    ReplayRunState,
    ReplayRunStatus,
    ReplayTimeline,
    ReplayTimelineEvent,
    ReplayTimelineStatus,
    build_replay_dispatcher_fingerprint,
    build_replay_event_dispatch_receipt_id,
    build_replay_event_output_record_id,
)
from futures_bot.domain.research import TemporalWindow, TemporalWindowKind
from futures_bot.infrastructure.replay.in_memory import (
    InMemoryReplayArtifactFingerprintStore,
    InMemoryReplayEventDispatchReceiptStore,
    InMemoryReplayEventOutputRecordStore,
    InMemoryReplayRunManifestStore,
    InMemoryReplayRunStateStore,
    InMemoryReplayTimelineStore,
)
from futures_bot.replay.dispatch import LocalDeterministicReplayDispatcher
from futures_bot.replay.runtime import LocalDeterministicReplayRuntime


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


EMPTY_DISPATCHER_FINGERPRINT = build_replay_dispatcher_fingerprint(())


class _Clock:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        return _utc(10) + timedelta(minutes=self.calls)


class _SequenceClock:
    def __init__(self, values: tuple[datetime, ...]) -> None:
        self._values = values
        self.calls = 0

    def __call__(self) -> datetime:
        value = self._values[self.calls]
        self.calls += 1
        return value


class _AuditHandler:
    def __init__(
        self,
        handler_id: str,
        *,
        version: str = "1",
        kinds: tuple[ReplayInputKind, ...] = (ReplayInputKind.MARK_PRICE,),
        outputs: tuple[str, ...] = ('{"audit":"ok"}',),
        fail_on_order_index: int | None = None,
    ) -> None:
        self.handler_id = handler_id
        self.handler_version = version
        self.supported_event_kinds = kinds
        self.outputs = outputs
        self.fail_on_order_index = fail_on_order_index
        self.calls: list[int] = []

    def handle(
        self,
        context: ReplayDispatchContext,
        event: ReplayTimelineEvent,
    ) -> tuple[ReplayHandlerOutputProposal, ...]:
        self.calls.append(event.order_index)
        if self.fail_on_order_index == event.order_index:
            raise ValueError("handler failure")
        return tuple(
            ReplayHandlerOutputProposal(output_kind="audit", canonical_payload=payload)
            for payload in self.outputs
        )


class _FlippingPlan:
    def __init__(
        self,
        plan: ReplayEventDispatchPlan,
        replacement_records: tuple[ReplayEventOutputRecord, ...],
    ) -> None:
        self.context = plan.context
        self.handler_ids = plan.handler_ids
        self.output_records = plan.output_records
        self._replacement_records = replacement_records

    def model_dump(self) -> dict[str, object]:
        return {
            "context": self.context.model_dump(),
            "handler_ids": self.handler_ids,
            "output_records": tuple(
                record.model_dump() for record in self._replacement_records
            ),
        }


class _FaultyDispatcher(LocalDeterministicReplayDispatcher):
    def __init__(self, mode: str) -> None:
        handlers = (_AuditHandler("handler-a"),)
        if mode in {"unknown_handler", "wrong_order"}:
            handlers = (_AuditHandler("handler-a"), _AuditHandler("handler-b"))
        if mode == "unsupported_included":
            handlers = (
                _AuditHandler("handler-a"),
                _AuditHandler("handler-z", kinds=(ReplayInputKind.TRADE,)),
            )
        super().__init__(handlers)
        self.mode = mode

    def plan_dispatch(  # noqa: PLR0911 - explicit faulty modes for runtime tests
        self,
        context: ReplayDispatchContext,
        event: ReplayTimelineEvent,
        dispatch_receipt_id: str,
    ) -> ReplayEventDispatchPlan:
        plan = super().plan_dispatch(context, event, dispatch_receipt_id)
        record = plan.output_records[0]
        if self.mode == "wrong_output_receipt":
            return ReplayEventDispatchPlan.model_construct(
                context=plan.context,
                handler_ids=plan.handler_ids,
                output_records=(
                    record.model_copy(
                        update={"dispatch_receipt_id": "replay-dispatch:" + "0" * 64}
                    ),
                ),
            )
        if self.mode == "handler_ids":
            return ReplayEventDispatchPlan.model_construct(
                context=plan.context,
                handler_ids=("handler-other",),
                output_records=plan.output_records,
            )
        if self.mode == "omitted_handler":
            return ReplayEventDispatchPlan.model_construct(
                context=plan.context,
                handler_ids=(),
                output_records=(),
            )
        if self.mode == "unknown_handler":
            return ReplayEventDispatchPlan.model_construct(
                context=plan.context,
                handler_ids=("handler-a", "handler-z"),
                output_records=plan.output_records,
            )
        if self.mode == "unsupported_included":
            return ReplayEventDispatchPlan.model_construct(
                context=plan.context,
                handler_ids=("handler-a", "handler-z"),
                output_records=plan.output_records,
            )
        if self.mode == "wrong_order":
            return ReplayEventDispatchPlan.model_construct(
                context=plan.context,
                handler_ids=("handler-b", "handler-a"),
                output_records=plan.output_records,
            )
        if self.mode == "wrong_version":
            payload_sha256 = record.payload_sha256
            output_record_id = build_replay_event_output_record_id(
                run_id=record.run_id,
                event_order_index=record.event_order_index,
                event_id=record.event_id,
                handler_id=record.handler_id,
                handler_version="999",
                handler_output_index=record.handler_output_index,
                output_kind=record.output_kind,
                payload_sha256=payload_sha256,
            )
            return ReplayEventDispatchPlan.model_construct(
                context=plan.context,
                handler_ids=plan.handler_ids,
                output_records=(
                    record.model_copy(
                        update={
                            "handler_version": "999",
                            "output_record_id": output_record_id,
                        }
                    ),
                ),
            )
        if self.mode == "output_ids":
            replacement = record.model_copy(
                update={"output_record_id": "replay-output:" + "0" * 64}
            )
            return _FlippingPlan(plan, (replacement,))  # type: ignore[return-value]
        if self.mode == "binding":
            return ReplayEventDispatchPlan.model_construct(
                context=plan.context.model_copy(update={"run_id": "run-other"}),
                handler_ids=plan.handler_ids,
                output_records=plan.output_records,
            )
        raise AssertionError(f"unknown faulty dispatcher mode {self.mode!r}")


class _CorruptMetadataDispatcher(LocalDeterministicReplayDispatcher):
    @property
    def dispatcher_fingerprint(self) -> str:
        return "replay-dispatcher:" + "0" * 64


class _CorruptSelectionDispatcher(LocalDeterministicReplayDispatcher):
    def selected_descriptors_for(
        self,
        event_kind: ReplayInputKind,
    ) -> tuple[ReplayDispatchHandlerDescriptor, ...]:
        return ()


def _instrument() -> ReplayInstrumentRef:
    return ReplayInstrumentRef(
        venue="binance",
        symbol="BTCUSDT",
        market_type="stablecoin-collateral-futures",
        settlement_asset="USDT",
    )


def _window() -> TemporalWindow:
    return TemporalWindow(
        kind=TemporalWindowKind.TEST,
        start_at=_utc(0),
        end_at=_utc(5),
        window_id="tw-1",
    )


def _event(index: int) -> ReplayTimelineEvent:
    return ReplayTimelineEvent(
        event_id=f"batch-1:record-{index}",
        batch_id="batch-1",
        input_dataset_id="input-ds-1",
        record_id=f"record-{index}",
        kind=ReplayInputKind.MARK_PRICE,
        instrument=_instrument(),
        event_time=_utc(1) + timedelta(minutes=index),
        source_sequence=index,
        order_index=index,
    )


def _timeline(
    *,
    timeline_id: str = "timeline-1",
    replay_plan_id: str = "plan-1",
    status: ReplayTimelineStatus = ReplayTimelineStatus.BUILT,
    event_count: int = 3,
) -> ReplayTimeline:
    events = tuple(_event(i) for i in range(event_count))
    return ReplayTimeline(
        timeline_id=timeline_id,
        replay_plan_id=replay_plan_id,
        temporal_window=_window(),
        ordering_policy=ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
        input_batch_ids=("batch-1",) if event_count else (),
        input_dataset_ids=("input-ds-1",) if event_count else (),
        events=events,
        created_at=_utc(1),
        status=status,
    )


def _canonical_payload(kind: ReplayArtifactKind, artifact: dict[str, object]) -> str:
    return json.dumps(
        {"artifact_kind": kind.value, "artifact": artifact},
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(  # noqa: PLR0913 - compact test fixture builder
    *,
    fingerprint_id: str = "fp-1",
    artifact_kind: ReplayArtifactKind = ReplayArtifactKind.TIMELINE,
    artifact_id: str = "timeline-1",
    replay_plan_id: str | None = "plan-1",
    status: ReplayArtifactFingerprintStatus = ReplayArtifactFingerprintStatus.GENERATED,
    generated_at: datetime | None = None,
) -> ReplayArtifactFingerprint:
    id_field = {
        ReplayArtifactKind.TIMELINE: "timeline_id",
        ReplayArtifactKind.COVERAGE_REPORT: "report_id",
        ReplayArtifactKind.COVERAGE_DIFF: "diff_id",
    }[artifact_kind]
    artifact: dict[str, object] = {id_field: artifact_id}
    if replay_plan_id is not None:
        artifact["replay_plan_id"] = replay_plan_id
    payload = _canonical_payload(artifact_kind, artifact)
    return ReplayArtifactFingerprint(
        fingerprint_id=fingerprint_id,
        artifact_kind=artifact_kind,
        artifact_id=artifact_id,
        replay_plan_id=replay_plan_id,
        generated_at=generated_at or _utc(4),
        status=status,
        hash_algorithm=ReplayArtifactHashAlgorithm.SHA256,
        canonical_payload=payload,
        sha256=hashlib.sha256(payload.encode()).hexdigest(),
    )


def _manifest(
    *,
    manifest_id: str = "manifest-1",
    replay_plan_id: str = "plan-1",
    status: ReplayRunManifestStatus = ReplayRunManifestStatus.PLANNED,
    fingerprint_ids: tuple[str, ...] = ("fp-1",),
    created_at: datetime | None = None,
) -> ReplayRunManifest:
    readiness_status = (
        ReplayReadinessStatus.READY
        if status is ReplayRunManifestStatus.PLANNED
        else ReplayReadinessStatus.BLOCKED
    )
    binding = ReplayRunReadinessBinding(
        readiness_report_id="readiness-1",
        readiness_replay_plan_id=replay_plan_id,
        readiness_status=readiness_status,
        readiness_checked_at=_utc(5),
        readiness_total_fingerprints=len(fingerprint_ids),
        readiness_latest_batch_report_id=(
            "batch-report-1"
            if status is ReplayRunManifestStatus.PLANNED
            else None
        ),
        verified_fingerprint_ids=(
            fingerprint_ids if status is ReplayRunManifestStatus.PLANNED else ()
        ),
    )
    return ReplayRunManifest(
        manifest_id=manifest_id,
        replay_plan_id=replay_plan_id,
        intent_kind=ReplayRunIntentKind.REPLAY_ONLY,
        created_at=created_at or _utc(6),
        status=status,
        readiness=binding,
        fingerprint_ids=fingerprint_ids,
        verification_batch_report_id=(
            "batch-report-1"
            if status is ReplayRunManifestStatus.PLANNED
            else None
        ),
    )


def _runtime(
    *,
    manifest: ReplayRunManifest | None = None,
    timeline: ReplayTimeline | None = None,
    fingerprint: ReplayArtifactFingerprint | None = None,
    clock: _Clock | None = None,
) -> tuple[
    LocalDeterministicReplayRuntime,
    InMemoryReplayRunStateStore,
    InMemoryReplayEventDispatchReceiptStore,
]:
    manifest_store = InMemoryReplayRunManifestStore()
    timeline_store = InMemoryReplayTimelineStore()
    fingerprint_store = InMemoryReplayArtifactFingerprintStore()
    run_store = InMemoryReplayRunStateStore()
    receipt_store = InMemoryReplayEventDispatchReceiptStore()
    output_store = InMemoryReplayEventOutputRecordStore()
    if manifest is not None:
        manifest_store.save(manifest)
    if timeline is not None:
        timeline_store.save(timeline)
    if fingerprint is not None:
        fingerprint_store.save(fingerprint)
    runtime = LocalDeterministicReplayRuntime(
        manifest_store=manifest_store,
        timeline_store=timeline_store,
        fingerprint_store=fingerprint_store,
        run_store=run_store,
        receipt_store=receipt_store,
        dispatcher=LocalDeterministicReplayDispatcher(()),
        output_store=output_store,
        now=clock,
    )
    return runtime, run_store, receipt_store


def _runtime_with_dispatcher(
    dispatcher: LocalDeterministicReplayDispatcher,
    *,
    clock: _Clock | _SequenceClock | None = None,
) -> tuple[
    LocalDeterministicReplayRuntime,
    InMemoryReplayRunStateStore,
    InMemoryReplayEventDispatchReceiptStore,
    InMemoryReplayEventOutputRecordStore,
]:
    manifest_store = InMemoryReplayRunManifestStore()
    timeline_store = InMemoryReplayTimelineStore()
    fingerprint_store = InMemoryReplayArtifactFingerprintStore()
    run_store = InMemoryReplayRunStateStore()
    receipt_store = InMemoryReplayEventDispatchReceiptStore()
    output_store = InMemoryReplayEventOutputRecordStore()
    manifest_store.save(_manifest())
    timeline_store.save(_timeline())
    fingerprint_store.save(_fingerprint())
    runtime = LocalDeterministicReplayRuntime(
        manifest_store=manifest_store,
        timeline_store=timeline_store,
        fingerprint_store=fingerprint_store,
        run_store=run_store,
        receipt_store=receipt_store,
        dispatcher=dispatcher,
        output_store=output_store,
        now=clock,
    )
    return runtime, run_store, receipt_store, output_store


def _shared_runtime(
    dispatcher: LocalDeterministicReplayDispatcher,
    *,
    run_store: InMemoryReplayRunStateStore,
    receipt_store: InMemoryReplayEventDispatchReceiptStore,
    output_store: InMemoryReplayEventOutputRecordStore,
    clock: _SequenceClock | None = None,
) -> LocalDeterministicReplayRuntime:
    manifest_store = InMemoryReplayRunManifestStore()
    timeline_store = InMemoryReplayTimelineStore()
    fingerprint_store = InMemoryReplayArtifactFingerprintStore()
    manifest_store.save(_manifest())
    timeline_store.save(_timeline())
    fingerprint_store.save(_fingerprint())
    return LocalDeterministicReplayRuntime(
        manifest_store=manifest_store,
        timeline_store=timeline_store,
        fingerprint_store=fingerprint_store,
        run_store=run_store,
        receipt_store=receipt_store,
        dispatcher=dispatcher,
        output_store=output_store,
        now=clock,
    )


class _StaticRunStateStore:
    def __init__(self, state: ReplayRunState) -> None:
        self._state = state
        self.replaced = False

    def create(self, state: ReplayRunState) -> None:
        self._state = state

    def load(self, run_id: str) -> ReplayRunState | None:
        if run_id == self._state.run_id:
            return self._state
        return None

    def replace(self, state: ReplayRunState, expected_revision: int) -> None:
        self.replaced = True
        self._state = state

    def list_for_replay_plan(
        self,
        replay_plan_id: str,
    ) -> tuple[ReplayRunState, ...]:
        if replay_plan_id == self._state.replay_plan_id:
            return (self._state,)
        return ()

    def list_all(self) -> tuple[ReplayRunState, ...]:
        return (self._state,)


class _FailNextReplaceRunStateStore(InMemoryReplayRunStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next_replace = False

    def replace(self, state: ReplayRunState, expected_revision: int) -> None:
        if self.fail_next_replace:
            self.fail_next_replace = False
            raise ValueError("simulated state CAS failure")
        super().replace(state, expected_revision)


def _runtime_with_loaded_state(
    state: ReplayRunState,
    *,
    timeline: ReplayTimeline,
    clock: _SequenceClock,
) -> tuple[
    LocalDeterministicReplayRuntime,
    _StaticRunStateStore,
    InMemoryReplayEventDispatchReceiptStore,
]:
    manifest_store = InMemoryReplayRunManifestStore()
    timeline_store = InMemoryReplayTimelineStore()
    fingerprint_store = InMemoryReplayArtifactFingerprintStore()
    receipt_store = InMemoryReplayEventDispatchReceiptStore()
    output_store = InMemoryReplayEventOutputRecordStore()
    run_store = _StaticRunStateStore(state)
    manifest_store.save(_manifest())
    timeline_store.save(timeline)
    fingerprint_store.save(_fingerprint())
    runtime = LocalDeterministicReplayRuntime(
        manifest_store=manifest_store,
        timeline_store=timeline_store,
        fingerprint_store=fingerprint_store,
        run_store=run_store,
        receipt_store=receipt_store,
        dispatcher=LocalDeterministicReplayDispatcher(()),
        output_store=output_store,
        now=clock,
    )
    return runtime, run_store, receipt_store


def _valid_runtime(
    event_count: int = 3,
    clock: _Clock | None = None,
) -> tuple[
    LocalDeterministicReplayRuntime,
    InMemoryReplayRunStateStore,
    InMemoryReplayEventDispatchReceiptStore,
]:
    return _runtime(
        manifest=_manifest(),
        timeline=_timeline(event_count=event_count),
        fingerprint=_fingerprint(),
        clock=clock,
    )


def _running_state(
    *,
    next_event_index: int = 0,
    last_processed_event_id: str | None = None,
    revision: int = 1,
    updated_at: datetime | None = None,
) -> ReplayRunState:
    if updated_at is None:
        updated_at = _utc(6)
    return ReplayRunState(
        run_id="run-1",
        manifest_id="manifest-1",
        replay_plan_id="plan-1",
        timeline_id="timeline-1",
        timeline_fingerprint_id="fp-1",
        dispatcher_fingerprint=EMPTY_DISPATCHER_FINGERPRINT,
        created_at=_utc(6),
        updated_at=updated_at,
        started_at=_utc(6),
        status=ReplayRunStatus.RUNNING,
        revision=revision,
        total_event_count=3,
        next_event_index=next_event_index,
        processed_event_count=next_event_index,
        last_processed_event_id=last_processed_event_id,
    )


class TestCreateRunBinding:
    def test_missing_manifest_rejected(self) -> None:
        runtime, _, _ = _runtime(timeline=_timeline(), fingerprint=_fingerprint())
        with pytest.raises(ValueError, match="manifest not found"):
            runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")

    @pytest.mark.parametrize(
        "status",
        [ReplayRunManifestStatus.BLOCKED, ReplayRunManifestStatus.INVALIDATED],
    )
    def test_blocked_or_invalidated_manifest_rejected(
        self, status: ReplayRunManifestStatus
    ) -> None:
        runtime, _, _ = _runtime(
            manifest=_manifest(status=status),
            timeline=_timeline(),
            fingerprint=_fingerprint(),
        )
        with pytest.raises(ValueError, match="PLANNED"):
            runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")

    def test_missing_timeline_rejected(self) -> None:
        runtime, _, _ = _runtime(manifest=_manifest(), fingerprint=_fingerprint())
        with pytest.raises(ValueError, match="timeline not found"):
            runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")

    def test_wrong_replay_plan_rejected(self) -> None:
        runtime, _, _ = _runtime(
            manifest=_manifest(),
            timeline=_timeline(replay_plan_id="plan-2"),
            fingerprint=_fingerprint(),
        )
        with pytest.raises(ValueError, match="replay_plan_id"):
            runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")

    def test_fingerprint_absent_from_manifest_rejected(self) -> None:
        runtime, _, _ = _runtime(
            manifest=_manifest(fingerprint_ids=("fp-other",)),
            timeline=_timeline(),
            fingerprint=_fingerprint(),
        )
        with pytest.raises(ValueError, match="manifest fingerprint_ids"):
            runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")

    def test_missing_fingerprint_rejected(self) -> None:
        runtime, _, _ = _runtime(manifest=_manifest(), timeline=_timeline())
        with pytest.raises(ValueError, match="fingerprint not found"):
            runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")

    def test_non_timeline_fingerprint_rejected(self) -> None:
        runtime, _, _ = _runtime(
            manifest=_manifest(),
            timeline=_timeline(),
            fingerprint=_fingerprint(
                artifact_kind=ReplayArtifactKind.COVERAGE_REPORT,
                artifact_id="report-1",
            ),
        )
        with pytest.raises(ValueError, match="TIMELINE"):
            runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")

    def test_fingerprint_artifact_id_mismatch_rejected(self) -> None:
        runtime, _, _ = _runtime(
            manifest=_manifest(),
            timeline=_timeline(),
            fingerprint=_fingerprint(artifact_id="timeline-other"),
        )
        with pytest.raises(ValueError, match="artifact_id"):
            runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")

    def test_future_fingerprint_rejected(self) -> None:
        runtime, _, _ = _runtime(
            manifest=_manifest(created_at=_utc(6)),
            timeline=_timeline(),
            fingerprint=_fingerprint(generated_at=_utc(7)),
        )
        with pytest.raises(ValueError, match="generated_at"):
            runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")

    def test_fingerprint_before_timeline_creation_rejected(self) -> None:
        runtime, _, _ = _runtime(
            manifest=_manifest(),
            timeline=_timeline(),
            fingerprint=_fingerprint(generated_at=_utc(0)),
        )
        with pytest.raises(ValueError, match="timeline created_at"):
            runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")

    def test_run_creation_before_manifest_rejected(self) -> None:
        clock = _SequenceClock((_utc(5),))
        runtime, _, _ = _runtime(
            manifest=_manifest(created_at=_utc(6)),
            timeline=_timeline(),
            fingerprint=_fingerprint(),
            clock=clock,
        )
        with pytest.raises(ValueError, match="manifest created_at"):
            runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        assert clock.calls == 1

    def test_create_valid_run(self) -> None:
        runtime, _, _ = _valid_runtime()
        state = runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        assert state.status is ReplayRunStatus.CREATED
        assert state.timeline_fingerprint_id == "fp-1"
        assert state.total_event_count == 3
        assert state.dispatcher_fingerprint == EMPTY_DISPATCHER_FINGERPRINT

    def test_create_run_retry_returns_existing_without_calling_now(self) -> None:
        clock = _Clock()
        runtime, _, _ = _valid_runtime(clock=clock)
        first = runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        second = runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        assert second == first
        assert clock.calls == 1

    def test_create_run_retry_conflicting_binding_rejected(self) -> None:
        clock = _Clock()
        runtime, _, _ = _valid_runtime(clock=clock)
        runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        with pytest.raises(ValueError, match="conflicting binding"):
            runtime.create_run("run-1", "manifest-other", "timeline-1", "fp-1")
        assert clock.calls == 1

    def test_create_run_retry_with_different_dispatcher_rejected(self) -> None:
        clock = _Clock()
        manifest_store = InMemoryReplayRunManifestStore()
        timeline_store = InMemoryReplayTimelineStore()
        fingerprint_store = InMemoryReplayArtifactFingerprintStore()
        run_store = InMemoryReplayRunStateStore()
        receipt_store = InMemoryReplayEventDispatchReceiptStore()
        output_store = InMemoryReplayEventOutputRecordStore()
        manifest_store.save(_manifest())
        timeline_store.save(_timeline())
        fingerprint_store.save(_fingerprint())
        first = LocalDeterministicReplayRuntime(
            manifest_store=manifest_store,
            timeline_store=timeline_store,
            fingerprint_store=fingerprint_store,
            run_store=run_store,
            receipt_store=receipt_store,
            dispatcher=LocalDeterministicReplayDispatcher(()),
            output_store=output_store,
            now=clock,
        )
        first.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        second = LocalDeterministicReplayRuntime(
            manifest_store=manifest_store,
            timeline_store=timeline_store,
            fingerprint_store=fingerprint_store,
            run_store=run_store,
            receipt_store=receipt_store,
            dispatcher=LocalDeterministicReplayDispatcher((_AuditHandler("handler-a"),)),
            output_store=output_store,
            now=clock,
        )
        with pytest.raises(ValueError, match="conflicting binding"):
            second.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        assert clock.calls == 1


class TestRuntimeTransitions:
    def test_start_non_empty_timeline(self) -> None:
        runtime, run_store, _ = _valid_runtime()
        runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        result = runtime.start_run("run-1")
        assert result.current_status is ReplayRunStatus.RUNNING
        assert run_store.load("run-1").started_at is not None  # type: ignore[union-attr]

    def test_start_empty_timeline_completes(self) -> None:
        runtime, _, _ = _valid_runtime(event_count=0)
        runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        result = runtime.start_run("run-1")
        assert result.current_status is ReplayRunStatus.COMPLETED
        assert result.completed is True

    def test_step_one_event(self) -> None:
        runtime, _, _ = _valid_runtime()
        runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        runtime.start_run("run-1")
        result = runtime.step_run("run-1")
        assert result.next_event_index == 1
        assert [r.event_order_index for r in result.processed_receipts] == [0]

    def test_step_multiple_events_and_final_completion(self) -> None:
        runtime, _, receipt_store = _valid_runtime()
        runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        runtime.start_run("run-1")
        first = runtime.step_run("run-1", max_events=2)
        final = runtime.step_run("run-1", max_events=5)
        assert [r.event_order_index for r in first.processed_receipts] == [0, 1]
        assert [r.event_order_index for r in final.processed_receipts] == [2]
        assert final.current_status is ReplayRunStatus.COMPLETED
        assert [r.event_order_index for r in receipt_store.list_for_run("run-1")] == [0, 1, 2]

    def test_event_order_and_receipt_ids_are_deterministic(self) -> None:
        runtime, _, receipt_store = _valid_runtime()
        runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        runtime.start_run("run-1")
        result = runtime.step_run("run-1", max_events=2)
        assert [r.receipt_id for r in result.processed_receipts] == [
            build_replay_event_dispatch_receipt_id(
                "run-1",
                0,
                "batch-1:record-0",
            ),
            build_replay_event_dispatch_receipt_id(
                "run-1",
                1,
                "batch-1:record-1",
            ),
        ]
        receipt_store.save(result.processed_receipts[0])
        assert len(receipt_store.list_for_run("run-1")) == 2

    def test_pause_and_resume(self) -> None:
        runtime, _, _ = _valid_runtime()
        runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        runtime.start_run("run-1")
        paused = runtime.pause_run("run-1")
        resumed = runtime.resume_run("run-1")
        assert paused.current_status is ReplayRunStatus.PAUSED
        assert resumed.current_status is ReplayRunStatus.RUNNING
        assert runtime.load_run("run-1").paused_at is None  # type: ignore[union-attr]

    def test_invalid_transitions_rejected(self) -> None:
        runtime, _, _ = _valid_runtime()
        runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        with pytest.raises(ValueError, match="RUNNING"):
            runtime.step_run("run-1")
        runtime.start_run("run-1")
        with pytest.raises(ValueError, match="CREATED"):
            runtime.start_run("run-1")

    @pytest.mark.parametrize("value", [True, 0, -1, "1", 1.5])
    def test_max_events_validation(self, value: object) -> None:
        runtime, _, _ = _valid_runtime()
        runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        runtime.start_run("run-1")
        with pytest.raises(ValueError, match="max_events"):
            runtime.step_run("run-1", max_events=value)  # type: ignore[arg-type]

    def test_no_progress_beyond_total(self) -> None:
        runtime, _, _ = _valid_runtime(event_count=1)
        runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        runtime.start_run("run-1")
        runtime.step_run("run-1")
        with pytest.raises(ValueError, match="RUNNING"):
            runtime.step_run("run-1")

    def test_now_called_once_per_state_transition(self) -> None:
        clock = _Clock()
        runtime, _, _ = _valid_runtime(clock=clock)
        runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        runtime.start_run("run-1")
        runtime.step_run("run-1")
        runtime.pause_run("run-1")
        runtime.resume_run("run-1")
        assert clock.calls == 5

    def test_equal_timestamps_accepted(self) -> None:
        clock = _SequenceClock((_utc(6), _utc(6), _utc(6), _utc(6), _utc(6)))
        runtime, _, _ = _valid_runtime(clock=clock)
        runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        runtime.start_run("run-1")
        runtime.step_run("run-1")
        runtime.pause_run("run-1")
        runtime.resume_run("run-1")
        assert clock.calls == 5

    def test_start_clock_regression_rejected(self) -> None:
        clock = _SequenceClock((_utc(6), _utc(5)))
        runtime, run_store, _ = _valid_runtime(clock=clock)
        created = runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        with pytest.raises(ValueError, match="clock regression"):
            runtime.start_run("run-1")
        assert run_store.load("run-1") == created
        assert clock.calls == 2

    def test_step_clock_regression_rejected_before_receipt_writes(self) -> None:
        clock = _SequenceClock((_utc(6), _utc(6), _utc(5)))
        runtime, run_store, receipt_store = _valid_runtime(clock=clock)
        runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        runtime.start_run("run-1")
        before = run_store.load("run-1")
        with pytest.raises(ValueError, match="clock regression"):
            runtime.step_run("run-1")
        assert receipt_store.list_for_run("run-1") == ()
        assert run_store.load("run-1") == before

    def test_pause_clock_regression_rejected(self) -> None:
        clock = _SequenceClock((_utc(6), _utc(6), _utc(5)))
        runtime, run_store, _ = _valid_runtime(clock=clock)
        runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        runtime.start_run("run-1")
        before = run_store.load("run-1")
        with pytest.raises(ValueError, match="clock regression"):
            runtime.pause_run("run-1")
        assert run_store.load("run-1") == before

    def test_resume_clock_regression_rejected(self) -> None:
        clock = _SequenceClock((_utc(6), _utc(6), _utc(6), _utc(5)))
        runtime, run_store, _ = _valid_runtime(clock=clock)
        runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        runtime.start_run("run-1")
        runtime.pause_run("run-1")
        before = run_store.load("run-1")
        with pytest.raises(ValueError, match="clock regression"):
            runtime.resume_run("run-1")
        assert run_store.load("run-1") == before

    def test_tampered_last_processed_event_id_rejected_before_dispatch(self) -> None:
        runtime, run_store, receipt_store = _runtime_with_loaded_state(
            _running_state(next_event_index=1, last_processed_event_id="wrong"),
            timeline=_timeline(),
            clock=_SequenceClock((_utc(7),)),
        )
        with pytest.raises(ValueError, match="last_processed_event_id"):
            runtime.step_run("run-1")
        assert receipt_store.list_for_run("run-1") == ()
        assert run_store.replaced is False

    def test_non_built_bound_timeline_rejected_before_dispatch(self) -> None:
        runtime, run_store, receipt_store = _runtime_with_loaded_state(
            _running_state(),
            timeline=_timeline(status=ReplayTimelineStatus.PLANNED),
            clock=_SequenceClock((_utc(7),)),
        )
        with pytest.raises(ValueError, match="must be BUILT"):
            runtime.step_run("run-1")
        assert receipt_store.list_for_run("run-1") == ()
        assert run_store.replaced is False

    def test_no_strategy_order_ledger_or_evaluation_outputs(self) -> None:
        runtime, _, _ = _valid_runtime()
        state = runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        runtime.start_run("run-1")
        result = runtime.step_run("run-1")
        forbidden = (
            "strategy",
            "decision_stack",
            "order",
            "fill",
            "ledger",
            "pnl",
            "evaluation",
            "metric",
        )
        for model in (state, result, *result.processed_receipts):
            dumped = model.model_dump()
            for name in forbidden:
                assert name not in dumped


class TestRuntimeDispatcherIntegration:
    def test_empty_dispatcher_still_records_dispatcher_on_receipt(self) -> None:
        runtime, _, receipt_store = _valid_runtime()
        runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        runtime.start_run("run-1")
        result = runtime.step_run("run-1")
        receipt = result.processed_receipts[0]
        assert receipt.dispatcher_fingerprint == EMPTY_DISPATCHER_FINGERPRINT
        assert receipt.handler_ids == ()
        assert receipt.output_record_ids == ()
        assert receipt_store.list_for_run("run-1") == (receipt,)

    def test_one_handler_outputs_are_journaled_and_linked_from_receipt(self) -> None:
        handler = _AuditHandler("handler-a")
        dispatcher = LocalDeterministicReplayDispatcher((handler,))
        runtime, _, receipt_store, output_store = _runtime_with_dispatcher(dispatcher)
        state = runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        runtime.start_run("run-1")
        result = runtime.step_run("run-1")
        outputs = output_store.list_for_run("run-1")
        receipt = result.processed_receipts[0]
        assert state.dispatcher_fingerprint == dispatcher.dispatcher_fingerprint
        assert handler.calls == [0]
        assert len(outputs) == 1
        assert receipt.handler_ids == ("handler-a",)
        assert receipt.output_record_ids == (outputs[0].output_record_id,)
        assert outputs[0].dispatch_receipt_id == receipt.receipt_id
        assert runtime.outputs_for_run("run-1") == outputs
        assert runtime.outputs_for_event("run-1", 0) == outputs
        assert receipt_store.list_for_run("run-1") == (receipt,)

    def test_multiple_handlers_and_outputs_are_deterministic(self) -> None:
        handler_b = _AuditHandler("handler-b", outputs=('{"b":1}',))
        handler_a = _AuditHandler("handler-a", outputs=('{"a":1}', '{"a":2}'))
        dispatcher = LocalDeterministicReplayDispatcher((handler_b, handler_a))
        runtime, _, _, output_store = _runtime_with_dispatcher(dispatcher)
        runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        runtime.start_run("run-1")
        result = runtime.step_run("run-1")
        outputs = output_store.list_for_run("run-1")
        assert [record.handler_id for record in outputs] == [
            "handler-a",
            "handler-a",
            "handler-b",
        ]
        assert result.processed_receipts[0].output_record_ids == tuple(
            record.output_record_id for record in outputs
        )

    def test_handler_failure_on_later_event_writes_nothing_for_step(self) -> None:
        handler = _AuditHandler("handler-a", fail_on_order_index=1)
        dispatcher = LocalDeterministicReplayDispatcher((handler,))
        runtime, run_store, receipt_store, output_store = _runtime_with_dispatcher(
            dispatcher
        )
        runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        runtime.start_run("run-1")
        before = run_store.load("run-1")
        with pytest.raises(RuntimeError, match="failed"):
            runtime.step_run("run-1", max_events=2)
        assert receipt_store.list_for_run("run-1") == ()
        assert output_store.list_for_run("run-1") == ()
        assert run_store.load("run-1") == before

    def test_dispatcher_fingerprint_mismatch_rejected_before_writes(self) -> None:
        mismatched_fingerprint = LocalDeterministicReplayDispatcher(
            (_AuditHandler("handler-a"),)
        ).dispatcher_fingerprint
        state = _running_state().model_copy(
            update={"dispatcher_fingerprint": mismatched_fingerprint}
        )
        runtime, run_store, receipt_store = _runtime_with_loaded_state(
            state,
            timeline=_timeline(),
            clock=_SequenceClock((_utc(7),)),
        )
        with pytest.raises(ValueError, match="dispatcher fingerprint"):
            runtime.step_run("run-1")
        assert receipt_store.list_for_run("run-1") == ()
        assert run_store.replaced is False

    @pytest.mark.parametrize("operation", ["start", "step", "pause", "resume"])
    def test_wrong_dispatcher_cannot_mutate_lifecycle(
        self,
        operation: str,
    ) -> None:
        run_store = InMemoryReplayRunStateStore()
        receipt_store = InMemoryReplayEventDispatchReceiptStore()
        output_store = InMemoryReplayEventOutputRecordStore()
        creator = _shared_runtime(
            LocalDeterministicReplayDispatcher(()),
            run_store=run_store,
            receipt_store=receipt_store,
            output_store=output_store,
            clock=_SequenceClock((_utc(6), _utc(6), _utc(6), _utc(6))),
        )
        creator.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        if operation in {"step", "pause", "resume"}:
            creator.start_run("run-1")
        if operation == "resume":
            creator.pause_run("run-1")
        before = run_store.load("run-1")

        wrong_clock = _SequenceClock((_utc(7),))
        wrong_runtime = _shared_runtime(
            LocalDeterministicReplayDispatcher((_AuditHandler("handler-a"),)),
            run_store=run_store,
            receipt_store=receipt_store,
            output_store=output_store,
            clock=wrong_clock,
        )
        with pytest.raises(ValueError, match="dispatcher fingerprint"):
            if operation == "start":
                wrong_runtime.start_run("run-1")
            elif operation == "step":
                wrong_runtime.step_run("run-1")
            elif operation == "pause":
                wrong_runtime.pause_run("run-1")
            else:
                wrong_runtime.resume_run("run-1")
        assert wrong_clock.calls == 0
        assert run_store.load("run-1") == before
        assert receipt_store.list_for_run("run-1") == ()
        assert output_store.list_for_run("run-1") == ()

    def test_corrupt_dispatcher_metadata_rejected_for_create_and_lifecycle(self) -> None:
        corrupt = _CorruptMetadataDispatcher((_AuditHandler("handler-a"),))
        runtime, run_store, receipt_store, output_store = _runtime_with_dispatcher(corrupt)
        with pytest.raises(ValueError, match="dispatcher descriptors"):
            runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        assert run_store.load("run-1") is None

        valid_runtime, run_store, receipt_store, output_store = _runtime_with_dispatcher(
            LocalDeterministicReplayDispatcher((_AuditHandler("handler-a"),))
        )
        valid_runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        corrupt_runtime = _shared_runtime(
            corrupt,
            run_store=run_store,
            receipt_store=receipt_store,
            output_store=output_store,
            clock=_SequenceClock((_utc(7),)),
        )
        before = run_store.load("run-1")
        with pytest.raises(ValueError, match="dispatcher descriptors"):
            corrupt_runtime.start_run("run-1")
        assert run_store.load("run-1") == before
        assert receipt_store.list_for_run("run-1") == ()

    def test_corrupt_dispatcher_metadata_rejected_for_idempotent_retry(self) -> None:
        valid_runtime, run_store, receipt_store, output_store = _runtime_with_dispatcher(
            LocalDeterministicReplayDispatcher((_AuditHandler("handler-a"),))
        )
        valid_runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        corrupt_runtime = _shared_runtime(
            _CorruptMetadataDispatcher((_AuditHandler("handler-a"),)),
            run_store=run_store,
            receipt_store=receipt_store,
            output_store=output_store,
            clock=_SequenceClock((_utc(7),)),
        )
        with pytest.raises(ValueError, match="dispatcher descriptors"):
            corrupt_runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")

    def test_corrupt_dispatcher_selection_rejected_before_writes(self) -> None:
        dispatcher = _CorruptSelectionDispatcher((_AuditHandler("handler-a"),))
        runtime, run_store, receipt_store, output_store = _runtime_with_dispatcher(
            dispatcher
        )
        runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        runtime.start_run("run-1")
        before = run_store.load("run-1")
        with pytest.raises(ValueError, match="selected dispatcher descriptors"):
            runtime.step_run("run-1")
        assert run_store.load("run-1") == before
        assert receipt_store.list_for_run("run-1") == ()
        assert output_store.list_for_run("run-1") == ()

    def test_retry_after_state_cas_failure_is_idempotent(self) -> None:
        handler = _AuditHandler("handler-a")
        dispatcher = LocalDeterministicReplayDispatcher((handler,))
        manifest_store = InMemoryReplayRunManifestStore()
        timeline_store = InMemoryReplayTimelineStore()
        fingerprint_store = InMemoryReplayArtifactFingerprintStore()
        run_store = _FailNextReplaceRunStateStore()
        receipt_store = InMemoryReplayEventDispatchReceiptStore()
        output_store = InMemoryReplayEventOutputRecordStore()
        manifest_store.save(_manifest())
        timeline_store.save(_timeline())
        fingerprint_store.save(_fingerprint())
        runtime = LocalDeterministicReplayRuntime(
            manifest_store=manifest_store,
            timeline_store=timeline_store,
            fingerprint_store=fingerprint_store,
            run_store=run_store,
            receipt_store=receipt_store,
            dispatcher=dispatcher,
            output_store=output_store,
            now=_SequenceClock((_utc(6), _utc(6), _utc(6), _utc(6))),
        )
        runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        runtime.start_run("run-1")

        run_store.fail_next_replace = True
        with pytest.raises(ValueError, match="simulated state CAS failure"):
            runtime.step_run("run-1")
        assert len(receipt_store.list_for_run("run-1")) == 1
        assert len(output_store.list_for_run("run-1")) == 1
        assert run_store.load("run-1").next_event_index == 0  # type: ignore[union-attr]

        result = runtime.step_run("run-1")
        assert result.next_event_index == 1
        assert len(receipt_store.list_for_run("run-1")) == 1
        assert len(output_store.list_for_run("run-1")) == 1

    def test_changed_output_retry_conflicts_before_new_output_write(self) -> None:
        handler = _AuditHandler("handler-a", outputs=('{"audit":"first"}',))
        dispatcher = LocalDeterministicReplayDispatcher((handler,))
        manifest_store = InMemoryReplayRunManifestStore()
        timeline_store = InMemoryReplayTimelineStore()
        fingerprint_store = InMemoryReplayArtifactFingerprintStore()
        run_store = _FailNextReplaceRunStateStore()
        receipt_store = InMemoryReplayEventDispatchReceiptStore()
        output_store = InMemoryReplayEventOutputRecordStore()
        manifest_store.save(_manifest())
        timeline_store.save(_timeline())
        fingerprint_store.save(_fingerprint())
        runtime = LocalDeterministicReplayRuntime(
            manifest_store=manifest_store,
            timeline_store=timeline_store,
            fingerprint_store=fingerprint_store,
            run_store=run_store,
            receipt_store=receipt_store,
            dispatcher=dispatcher,
            output_store=output_store,
            now=_SequenceClock((_utc(6), _utc(6), _utc(6), _utc(6))),
        )
        runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        runtime.start_run("run-1")
        run_store.fail_next_replace = True
        with pytest.raises(ValueError, match="simulated state CAS failure"):
            runtime.step_run("run-1")

        handler.outputs = ('{"audit":"changed"}',)
        before_outputs = output_store.list_for_run("run-1")
        with pytest.raises(ValueError, match="receipt_id conflict"):
            runtime.step_run("run-1")
        assert output_store.list_for_run("run-1") == before_outputs

    @pytest.mark.parametrize(
        ("mode", "message"),
        [
            ("wrong_output_receipt", "dispatch_receipt_id"),
            ("handler_ids", "handler_id"),
            ("omitted_handler", "handler_ids"),
            ("unknown_handler", "handler_ids"),
            ("unsupported_included", "handler_ids"),
            ("wrong_order", "handler_ids"),
            ("wrong_version", "handler_version"),
            ("output_ids", "output_record_id"),
            ("binding", "run_id"),
        ],
    )
    def test_faulty_dispatch_bundle_rejected_before_writes(
        self,
        mode: str,
        message: str,
    ) -> None:
        runtime, run_store, receipt_store, output_store = _runtime_with_dispatcher(
            _FaultyDispatcher(mode)
        )
        runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-1")
        runtime.start_run("run-1")
        before = run_store.load("run-1")
        with pytest.raises(ValueError, match=message):
            runtime.step_run("run-1")
        assert output_store.list_for_run("run-1") == ()
        assert receipt_store.list_for_run("run-1") == ()
        assert run_store.load("run-1") == before


def test_cas_stale_revision_rejected() -> None:
    _, run_store, _ = _valid_runtime()
    state = run_store.load("run-1")
    assert state is None
    created = _valid_runtime()[0].create_run("run-1", "manifest-1", "timeline-1", "fp-1")
    run_store.create(created)
    replacement = created.model_copy(
        update={
            "status": ReplayRunStatus.RUNNING,
            "revision": 1,
            "started_at": created.created_at,
            "updated_at": created.created_at,
        }
    )
    with pytest.raises(ValueError, match="stale"):
        run_store.replace(replacement, expected_revision=1)
