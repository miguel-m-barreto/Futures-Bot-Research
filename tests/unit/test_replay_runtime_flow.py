from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from futures_bot.domain.replay import (
    ReplayDispatchContext,
    ReplayHandlerOutputProposal,
    ReplayInputBatch,
    ReplayInputDataset,
    ReplayInputKind,
    ReplayInputQuality,
    ReplayInputRecord,
    ReplayInputSourceKind,
    ReplayInputValidationStatus,
    ReplayInstrumentRef,
    ReplayOrderingPolicy,
    ReplayRunStatus,
    ReplayTimelineEvent,
)
from futures_bot.domain.research import TemporalWindow, TemporalWindowKind
from futures_bot.infrastructure.replay.in_memory import (
    InMemoryReplayArtifactFingerprintStore,
    InMemoryReplayArtifactFingerprintVerificationBatchReportStore,
    InMemoryReplayArtifactFingerprintVerificationStore,
    InMemoryReplayEventDispatchReceiptStore,
    InMemoryReplayEventOutputRecordStore,
    InMemoryReplayInputBatchStore,
    InMemoryReplayInputDatasetStore,
    InMemoryReplayReadinessReportStore,
    InMemoryReplayRunManifestStore,
    InMemoryReplayRunStateStore,
    InMemoryReplayTimelineCoverageDiffStore,
    InMemoryReplayTimelineCoverageReportStore,
    InMemoryReplayTimelineCursorStore,
    InMemoryReplayTimelineStore,
)
from futures_bot.replay.dispatch import LocalDeterministicReplayDispatcher
from futures_bot.replay.integrity import (
    LocalReplayArtifactFingerprintBatchVerifier,
    LocalReplayArtifactFingerprinter,
    LocalReplayArtifactFingerprintVerifier,
    LocalReplayReadinessChecker,
    LocalReplayRunPlanner,
)
from futures_bot.replay.local import LocalReplayTimelineBuilder
from futures_bot.replay.runtime import LocalDeterministicReplayRuntime


def _utc(hour: int = 0, minute: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, minute, tzinfo=UTC)


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
        end_at=_utc(4),
        window_id="tw-1",
    )


def _record(record_id: str, index: int) -> ReplayInputRecord:
    price = Decimal("42000") + Decimal(index)
    return ReplayInputRecord(
        record_id=record_id,
        kind=ReplayInputKind.MARK_PRICE,
        instrument=_instrument(),
        event_time=_utc(1, index),
        source_sequence=index,
        payload={"price": price},
        content_hash=f"hash-{record_id}",
    )


class _FlowAuditHandler:
    handler_id = "flow-audit"
    handler_version = "1"
    supported_event_kinds = (ReplayInputKind.MARK_PRICE,)

    def handle(
        self,
        context: ReplayDispatchContext,
        event: ReplayTimelineEvent,
    ) -> tuple[ReplayHandlerOutputProposal, ...]:
        assert event.event_id == context.event_id
        return (
            ReplayHandlerOutputProposal(
                output_kind="audit",
                canonical_payload=(
                    '{"event_id":"'
                    + context.event_id
                    + '","order_index":'
                    + str(context.event_order_index)
                    + "}"
                ),
            ),
        )


def test_full_replay_runtime_flow_is_metadata_only_and_deterministic() -> None:  # noqa: PLR0915
    input_dataset_store = InMemoryReplayInputDatasetStore()
    input_batch_store = InMemoryReplayInputBatchStore()
    timeline_store = InMemoryReplayTimelineStore()
    cursor_store = InMemoryReplayTimelineCursorStore()
    coverage_report_store = InMemoryReplayTimelineCoverageReportStore()
    coverage_diff_store = InMemoryReplayTimelineCoverageDiffStore()
    fingerprint_store = InMemoryReplayArtifactFingerprintStore()
    verification_store = InMemoryReplayArtifactFingerprintVerificationStore()
    batch_report_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
    readiness_store = InMemoryReplayReadinessReportStore()
    manifest_store = InMemoryReplayRunManifestStore()
    run_store = InMemoryReplayRunStateStore()
    receipt_store = InMemoryReplayEventDispatchReceiptStore()
    output_store = InMemoryReplayEventOutputRecordStore()

    dataset = ReplayInputDataset(
        input_dataset_id="input-ds-1",
        dataset_id="dataset-1",
        source_kind=ReplayInputSourceKind.SYNTHETIC_FIXTURE,
        quality=ReplayInputQuality.SYNTHETIC_FIXTURE,
        instruments=(_instrument(),),
        start_at=_utc(0),
        end_at=_utc(4),
        created_at=_utc(0),
        record_count=3,
    )
    input_dataset_store.save(dataset)
    batch = ReplayInputBatch(
        batch_id="batch-1",
        replay_plan_id="plan-1",
        input_dataset_id="input-ds-1",
        temporal_window=_window(),
        ordering_policy=ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
        records=(_record("record-0", 0), _record("record-1", 1), _record("record-2", 2)),
        created_at=_utc(0),
        validation_status=ReplayInputValidationStatus.VALIDATED,
    )
    input_batch_store.save(batch)

    builder = LocalReplayTimelineBuilder(
        input_batch_store=input_batch_store,
        timeline_store=timeline_store,
        cursor_store=cursor_store,
        now=lambda: _utc(1),
    )
    timeline = builder.build_timeline(
        timeline_id="timeline-1",
        replay_plan_id="plan-1",
        input_batch_ids=("batch-1",),
        temporal_window=_window(),
        ordering_policy=ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
    )

    fingerprinter = LocalReplayArtifactFingerprinter(
        timeline_store=timeline_store,
        coverage_report_store=coverage_report_store,
        coverage_diff_store=coverage_diff_store,
        fingerprint_store=fingerprint_store,
        now=lambda: _utc(2),
    )
    fingerprint = fingerprinter.fingerprint_timeline("fp-timeline-1", "timeline-1")
    verifier = LocalReplayArtifactFingerprintVerifier(
        timeline_store=timeline_store,
        coverage_report_store=coverage_report_store,
        coverage_diff_store=coverage_diff_store,
        fingerprint_store=fingerprint_store,
        verification_store=verification_store,
        now=lambda: _utc(3),
    )
    batch_verifier = LocalReplayArtifactFingerprintBatchVerifier(
        verifier=verifier,
        fingerprint_store=fingerprint_store,
        batch_report_store=batch_report_store,
        now=lambda: _utc(3),
    )
    verification_batch = batch_verifier.verify_replay_plan("batch-report-1", "plan-1")
    readiness_checker = LocalReplayReadinessChecker(
        fingerprint_store=fingerprint_store,
        batch_report_store=batch_report_store,
        readiness_report_store=readiness_store,
        now=lambda: _utc(4),
    )
    readiness = readiness_checker.check_replay_plan("readiness-1", "plan-1")
    planner = LocalReplayRunPlanner(
        readiness_report_store=readiness_store,
        fingerprint_store=fingerprint_store,
        batch_report_store=batch_report_store,
        run_manifest_store=manifest_store,
        now=lambda: _utc(5),
    )
    manifest = planner.plan_replay_run("manifest-1", "readiness-1")

    timeline_before = timeline_store.load("timeline-1")
    fingerprint_before = fingerprint_store.load("fp-timeline-1")
    readiness_before = readiness_store.load("readiness-1")
    manifest_before = manifest_store.load("manifest-1")
    verification_batch_before = batch_report_store.load("batch-report-1")

    runtime = LocalDeterministicReplayRuntime(
        manifest_store=manifest_store,
        timeline_store=timeline_store,
        fingerprint_store=fingerprint_store,
        run_store=run_store,
        receipt_store=receipt_store,
        dispatcher=LocalDeterministicReplayDispatcher((_FlowAuditHandler(),)),
        output_store=output_store,
        now=lambda: _utc(6),
    )
    run = runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-timeline-1")
    assert run.status is ReplayRunStatus.CREATED
    runtime.start_run("run-1")
    runtime.step_run("run-1", max_events=1)
    runtime.pause_run("run-1")
    runtime.resume_run("run-1")
    runtime.step_run("run-1", max_events=2)

    completed = runtime.load_run("run-1")
    receipts = runtime.receipts_for_run("run-1")
    outputs = runtime.outputs_for_run("run-1")
    assert completed is not None
    assert completed.status is ReplayRunStatus.COMPLETED
    assert completed.processed_event_count == completed.total_event_count == len(timeline.events)
    assert [r.event_order_index for r in receipts] == [e.order_index for e in timeline.events]
    assert [r.event_id for r in receipts] == [e.event_id for e in timeline.events]
    assert len(receipts) == len(timeline.events)
    assert len(outputs) == len(timeline.events)
    assert [o.event_order_index for o in outputs] == [
        e.order_index for e in timeline.events
    ]
    assert [o.event_id for o in outputs] == [e.event_id for e in timeline.events]
    assert [o.handler_id for o in outputs] == ["flow-audit"] * len(timeline.events)
    assert [r.output_record_ids for r in receipts] == [
        (output.output_record_id,) for output in outputs
    ]
    assert {r.dispatcher_fingerprint for r in receipts} == {
        completed.dispatcher_fingerprint
    }

    assert timeline_before == timeline
    assert fingerprint_before == fingerprint
    assert readiness_before == readiness
    assert manifest_before == manifest
    assert verification_batch_before == verification_batch
    assert timeline_store.load("timeline-1") == timeline_before
    assert fingerprint_store.load("fp-timeline-1") == fingerprint_before
    assert readiness_store.load("readiness-1") == readiness_before
    assert manifest_store.load("manifest-1") == manifest_before
    assert batch_report_store.load("batch-report-1") == verification_batch_before

    for model in (completed, *receipts):
        dumped = model.model_dump()
        for forbidden in (
            "DecisionStack",
            "RiskGate",
            "Execution",
            "Ledger",
            "PnL",
            "MetricObservation",
            "EvaluationResultSet",
        ):
            assert forbidden not in dumped
