from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from futures_bot.decision.journal import LocalReplayDecisionJournal
from futures_bot.decision.replay_adapter import ReplayDecisionStackHandler
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
    ReplayDispatchContext,
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
from futures_bot.domain.replay_decisions import (
    ReplayDecisionStackDescriptor,
    build_replay_decision_intent_id,
    build_replay_decision_stack_fingerprint,
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


class _DecisionFlowStack:
    stack_id = "decision-flow-stack"
    stack_version = "1"
    bot_id = BotId("bot-decision-flow")
    source_kind = DecisionSourceKind.ML_MODEL
    supported_event_kinds = (ReplayInputKind.MARK_PRICE,)

    def __init__(self) -> None:
        self.calls = 0

    def descriptor(self) -> ReplayDecisionStackDescriptor:
        return ReplayDecisionStackDescriptor(
            stack_id=self.stack_id,
            stack_version=self.stack_version,
            bot_id=self.bot_id,
            source_kind=self.source_kind,
            supported_event_kinds=self.supported_event_kinds,
        )

    def _decision_id(
        self,
        context: ReplayDispatchContext,
        decision_index: int,
    ) -> object:
        return build_replay_decision_intent_id(
            run_id=context.run_id,
            event_order_index=context.event_order_index,
            event_id=context.event_id,
            decision_stack_fingerprint=build_replay_decision_stack_fingerprint(
                self.descriptor()
            ),
            decision_index=decision_index,
        )

    def decide(
        self,
        context: ReplayDispatchContext,
        event: ReplayTimelineEvent,
    ) -> tuple[DecisionIntent | NoTradeDecision, ...]:
        self.calls += 1
        return (
            DecisionIntent(
                decision_intent_id=self._decision_id(context, 0),
                bot_id=self.bot_id,
                instrument=f"{event.instrument.symbol}/USDT",
                side=TradeSide.LONG,
                proposed_action=ProposedAction.OPEN_POSITION,
                source_kind=self.source_kind,
                source_id=self.stack_id,
                created_at=context.event_time,
                confidence="0.6",
                reason_tags=(f"event-{context.event_order_index}",),
            ),
            NoTradeDecision(
                decision_intent_id=self._decision_id(context, 1),
                bot_id=self.bot_id,
                instrument=f"{event.instrument.symbol}/USDT",
                source_kind=self.source_kind,
                source_id=self.stack_id,
                created_at=context.event_time,
                reasons=(NoTradeReasonKind.MARKET_TOO_UNCERTAIN,),
                notes="explicit alternate outcome",
            ),
        )


def test_replay_decision_stack_runtime_flow_round_trips_typed_journal() -> None:  # noqa: PLR0915
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
        record_count=2,
    )
    input_dataset_store.save(dataset)
    batch = ReplayInputBatch(
        batch_id="batch-1",
        replay_plan_id="plan-1",
        input_dataset_id="input-ds-1",
        temporal_window=_window(),
        ordering_policy=ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
        records=(_record("record-0", 0), _record("record-1", 1)),
        created_at=_utc(0),
        validation_status=ReplayInputValidationStatus.VALIDATED,
    )
    input_batch_store.save(batch)

    timeline = LocalReplayTimelineBuilder(
        input_batch_store=input_batch_store,
        timeline_store=timeline_store,
        cursor_store=cursor_store,
        now=lambda: _utc(1),
    ).build_timeline(
        timeline_id="timeline-1",
        replay_plan_id="plan-1",
        input_batch_ids=("batch-1",),
        temporal_window=_window(),
        ordering_policy=ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
    )
    fingerprint = LocalReplayArtifactFingerprinter(
        timeline_store=timeline_store,
        coverage_report_store=coverage_report_store,
        coverage_diff_store=coverage_diff_store,
        fingerprint_store=fingerprint_store,
        now=lambda: _utc(2),
    ).fingerprint_timeline("fp-timeline-1", "timeline-1")
    verifier = LocalReplayArtifactFingerprintVerifier(
        timeline_store=timeline_store,
        coverage_report_store=coverage_report_store,
        coverage_diff_store=coverage_diff_store,
        fingerprint_store=fingerprint_store,
        verification_store=verification_store,
        now=lambda: _utc(3),
    )
    verification_batch = LocalReplayArtifactFingerprintBatchVerifier(
        verifier=verifier,
        fingerprint_store=fingerprint_store,
        batch_report_store=batch_report_store,
        now=lambda: _utc(3),
    ).verify_replay_plan("batch-report-1", "plan-1")
    readiness = LocalReplayReadinessChecker(
        fingerprint_store=fingerprint_store,
        batch_report_store=batch_report_store,
        readiness_report_store=readiness_store,
        now=lambda: _utc(4),
    ).check_replay_plan("readiness-1", "plan-1")
    manifest = LocalReplayRunPlanner(
        readiness_report_store=readiness_store,
        fingerprint_store=fingerprint_store,
        batch_report_store=batch_report_store,
        run_manifest_store=manifest_store,
        now=lambda: _utc(5),
    ).plan_replay_run("manifest-1", "readiness-1")

    stack = _DecisionFlowStack()
    handler = ReplayDecisionStackHandler(stack)
    dispatcher = LocalDeterministicReplayDispatcher((handler,))
    runtime = LocalDeterministicReplayRuntime(
        manifest_store=manifest_store,
        timeline_store=timeline_store,
        fingerprint_store=fingerprint_store,
        run_store=run_store,
        receipt_store=receipt_store,
        dispatcher=dispatcher,
        output_store=output_store,
        now=lambda: _utc(6),
    )

    run = runtime.create_run("run-1", "manifest-1", "timeline-1", "fp-timeline-1")
    assert run.dispatcher_fingerprint == dispatcher.dispatcher_fingerprint
    assert runtime.create_run(
        "run-1",
        "manifest-1",
        "timeline-1",
        "fp-timeline-1",
    ) == run
    runtime.start_run("run-1")
    runtime.step_run("run-1", max_events=1)
    runtime.pause_run("run-1")
    runtime.resume_run("run-1")
    runtime.step_run("run-1", max_events=1)

    completed = runtime.load_run("run-1")
    receipts = runtime.receipts_for_run("run-1")
    records = runtime.outputs_for_run("run-1")
    decisions = LocalReplayDecisionJournal(output_store).decisions_for_run("run-1")

    assert completed is not None
    assert completed.status is ReplayRunStatus.COMPLETED
    assert completed.processed_event_count == len(timeline.events)
    assert stack.calls == len(timeline.events)
    assert [receipt.event_id for receipt in receipts] == [
        event.event_id for event in timeline.events
    ]
    assert [record.dispatch_receipt_id for record in records] == [
        receipts[0].receipt_id,
        receipts[0].receipt_id,
        receipts[1].receipt_id,
        receipts[1].receipt_id,
    ]
    assert len(decisions) == len(timeline.events) * 2
    assert [decision.event_order_index for decision in decisions] == [0, 0, 1, 1]
    assert [decision.decision_index for decision in decisions] == [0, 1, 0, 1]
    assert [decision.event_id for decision in decisions] == [
        timeline.events[0].event_id,
        timeline.events[0].event_id,
        timeline.events[1].event_id,
        timeline.events[1].event_id,
    ]
    for decision in decisions:
        if decision.decision_intent is not None:
            typed_decision = decision.decision_intent
        else:
            typed_decision = decision.no_trade_decision
        assert typed_decision is not None
        assert typed_decision.created_at == decision.event_time
        assert str(typed_decision.decision_intent_id).startswith("replay-decision:")

    assert timeline_store.load("timeline-1") == timeline
    assert fingerprint_store.load("fp-timeline-1") == fingerprint
    assert readiness_store.load("readiness-1") == readiness
    assert manifest_store.load("manifest-1") == manifest
    assert batch_report_store.load("batch-report-1") == verification_batch

    for payload in (completed.model_dump(), *(decision.model_dump() for decision in decisions)):
        dumped = str(payload)
        for forbidden in (
            "RiskBehaviorModel",
            "HardRiskGate",
            "ExecutionIntent",
            "OrderIntent",
            "Ledger",
            "PnL",
            "MetricObservation",
            "EvaluationResultSet",
        ):
            assert forbidden not in dumped
