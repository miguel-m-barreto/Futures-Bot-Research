from __future__ import annotations

from datetime import UTC, datetime

from futures_bot.domain.replay import (
    ReplayArtifactKind,
    ReplayInputKind,
    ReplayInstrumentRef,
    ReplayOrderingPolicy,
    ReplayTimeline,
    ReplayTimelineCoverageDiff,
    ReplayTimelineCoverageDiffStatus,
    ReplayTimelineCoverageDiffSummary,
    ReplayTimelineCoverageReport,
    ReplayTimelineCoverageStatus,
    ReplayTimelineCoverageSummary,
    ReplayTimelineEvent,
    ReplayTimelineStatus,
)
from futures_bot.domain.research import TemporalWindow, TemporalWindowKind
from futures_bot.infrastructure.replay.in_memory import (
    InMemoryReplayArtifactFingerprintStore,
    InMemoryReplayTimelineCoverageDiffStore,
    InMemoryReplayTimelineCoverageReportStore,
    InMemoryReplayTimelineStore,
)
from futures_bot.replay.integrity import LocalReplayArtifactFingerprinter


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _window() -> TemporalWindow:
    return TemporalWindow(
        kind=TemporalWindowKind.TEST,
        start_at=_utc(0),
        end_at=_utc(10),
        window_id="tw-1",
    )


def _instrument() -> ReplayInstrumentRef:
    return ReplayInstrumentRef(
        venue="binance",
        symbol="BTCUSDT",
        market_type="stablecoin-collateral-futures",
        settlement_asset="USDT",
    )


def _event(order_index: int = 0) -> ReplayTimelineEvent:
    return ReplayTimelineEvent(
        event_id=f"ev-{order_index}",
        batch_id="batch-1",
        input_dataset_id="ds-1",
        record_id="rec-1",
        kind=ReplayInputKind.MARK_PRICE,
        instrument=_instrument(),
        event_time=_utc(1),
        source_sequence=order_index,
        order_index=order_index,
    )


def _timeline(timeline_id: str = "tl-1", plan_id: str = "plan-1") -> ReplayTimeline:
    return ReplayTimeline(
        timeline_id=timeline_id,
        replay_plan_id=plan_id,
        temporal_window=_window(),
        ordering_policy=ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
        input_batch_ids=("batch-1",),
        input_dataset_ids=("ds-1",),
        events=(_event(0),),
        created_at=_utc(0),
        status=ReplayTimelineStatus.BUILT,
    )


def _coverage_summary() -> ReplayTimelineCoverageSummary:
    return ReplayTimelineCoverageSummary(
        total_events=1,
        first_event_at=_utc(1),
        last_event_at=_utc(1),
        event_count_by_kind={ReplayInputKind.MARK_PRICE: 1},
        event_count_by_instrument={"binance:BTCUSDT:USDT": 1},
        event_count_by_dataset={"ds-1": 1},
        issue_count_by_severity={},
    )


def _coverage_report(
    report_id: str, timeline_id: str, plan_id: str
) -> ReplayTimelineCoverageReport:
    return ReplayTimelineCoverageReport(
        report_id=report_id,
        timeline_id=timeline_id,
        replay_plan_id=plan_id,
        temporal_window=_window(),
        generated_at=_utc(0),
        status=ReplayTimelineCoverageStatus.GENERATED,
        summary=_coverage_summary(),
    )


def _diff(
    diff_id: str,
    baseline_report_id: str,
    candidate_report_id: str,
    baseline_plan_id: str,
    candidate_plan_id: str,
) -> ReplayTimelineCoverageDiff:
    return ReplayTimelineCoverageDiff(
        diff_id=diff_id,
        baseline_report_id=baseline_report_id,
        candidate_report_id=candidate_report_id,
        baseline_timeline_id="tl-base",
        candidate_timeline_id="tl-cand",
        baseline_replay_plan_id=baseline_plan_id,
        candidate_replay_plan_id=candidate_plan_id,
        generated_at=_utc(0),
        status=ReplayTimelineCoverageDiffStatus.GENERATED,
        summary=ReplayTimelineCoverageDiffSummary(
            total_items=0,
            item_count_by_kind={},
            item_count_by_severity={},
            has_errors=False,
            has_warnings=False,
        ),
    )


class TestReplayArtifactFingerprintFlow:
    def test_full_fingerprint_flow(self) -> None:
        tl_store = InMemoryReplayTimelineStore()
        rep_store = InMemoryReplayTimelineCoverageReportStore()
        diff_store = InMemoryReplayTimelineCoverageDiffStore()
        fp_store = InMemoryReplayArtifactFingerprintStore()
        fingerprinter = LocalReplayArtifactFingerprinter(
            timeline_store=tl_store,
            coverage_report_store=rep_store,
            coverage_diff_store=diff_store,
            fingerprint_store=fp_store,
            now=lambda: _utc(10),
        )

        tl = _timeline("tl-1", "plan-1")
        tl_store.save(tl)
        rep = _coverage_report("rep-1", "tl-1", "plan-1")
        rep_store.save(rep)
        same_plan_diff = _diff("diff-same", "rep-1", "rep-2", "plan-1", "plan-1")
        diff_plan_diff = _diff("diff-cross", "rep-1", "rep-3", "plan-A", "plan-B")
        diff_store.save(same_plan_diff)
        diff_store.save(diff_plan_diff)

        fp_tl = fingerprinter.fingerprint_timeline("fp-tl", "tl-1")
        fp_rep = fingerprinter.fingerprint_coverage_report("fp-rep", "rep-1")
        fp_same = fingerprinter.fingerprint_coverage_diff("fp-same", "diff-same")
        fp_cross = fingerprinter.fingerprint_coverage_diff("fp-cross", "diff-cross")

        assert fp_tl.artifact_kind is ReplayArtifactKind.TIMELINE
        assert fp_tl.artifact_id == "tl-1"
        assert fp_tl.replay_plan_id == "plan-1"

        assert fp_rep.artifact_kind is ReplayArtifactKind.COVERAGE_REPORT
        assert fp_rep.artifact_id == "rep-1"
        assert fp_rep.replay_plan_id == "plan-1"

        assert fp_same.artifact_kind is ReplayArtifactKind.COVERAGE_DIFF
        assert fp_same.replay_plan_id == "plan-1"

        assert fp_cross.artifact_kind is ReplayArtifactKind.COVERAGE_DIFF
        assert fp_cross.replay_plan_id is None

        assert fp_store.load("fp-tl") == fp_tl
        assert fp_store.load("fp-rep") == fp_rep
        assert fp_store.load("fp-same") == fp_same
        assert fp_store.load("fp-cross") == fp_cross

    def test_same_timeline_same_sha256(self) -> None:
        tl_store = InMemoryReplayTimelineStore()
        fp_store = InMemoryReplayArtifactFingerprintStore()
        fingerprinter = LocalReplayArtifactFingerprinter(
            timeline_store=tl_store,
            coverage_report_store=InMemoryReplayTimelineCoverageReportStore(),
            coverage_diff_store=InMemoryReplayTimelineCoverageDiffStore(),
            fingerprint_store=fp_store,
            now=lambda: _utc(0),
        )
        tl_store.save(_timeline())
        fp1 = fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        fp2 = fingerprinter.fingerprint_timeline("fp-2", "tl-1")
        assert fp1.sha256 == fp2.sha256

    def test_different_timelines_different_sha256(self) -> None:
        tl_store = InMemoryReplayTimelineStore()
        fp_store = InMemoryReplayArtifactFingerprintStore()
        fingerprinter = LocalReplayArtifactFingerprinter(
            timeline_store=tl_store,
            coverage_report_store=InMemoryReplayTimelineCoverageReportStore(),
            coverage_diff_store=InMemoryReplayTimelineCoverageDiffStore(),
            fingerprint_store=fp_store,
            now=lambda: _utc(0),
        )
        tl1 = _timeline("tl-1", "plan-1")
        tl2 = _timeline("tl-2", "plan-2")
        tl_store.save(tl1)
        tl_store.save(tl2)
        fp1 = fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        fp2 = fingerprinter.fingerprint_timeline("fp-2", "tl-2")
        assert fp1.sha256 != fp2.sha256

    def test_fingerprints_for_plan_aggregates_across_kinds(self) -> None:
        tl_store = InMemoryReplayTimelineStore()
        rep_store = InMemoryReplayTimelineCoverageReportStore()
        fp_store = InMemoryReplayArtifactFingerprintStore()
        fingerprinter = LocalReplayArtifactFingerprinter(
            timeline_store=tl_store,
            coverage_report_store=rep_store,
            coverage_diff_store=InMemoryReplayTimelineCoverageDiffStore(),
            fingerprint_store=fp_store,
            now=lambda: _utc(0),
        )
        tl_store.save(_timeline("tl-1", "plan-X"))
        rep_store.save(_coverage_report("rep-1", "tl-1", "plan-X"))
        fingerprinter.fingerprint_timeline("fp-tl", "tl-1")
        fingerprinter.fingerprint_coverage_report("fp-rep", "rep-1")
        results = fingerprinter.fingerprints_for_replay_plan("plan-X")
        assert len(results) == 2

    def test_fingerprint_has_no_execution_attributes(self) -> None:
        tl_store = InMemoryReplayTimelineStore()
        fp_store = InMemoryReplayArtifactFingerprintStore()
        fingerprinter = LocalReplayArtifactFingerprinter(
            timeline_store=tl_store,
            coverage_report_store=InMemoryReplayTimelineCoverageReportStore(),
            coverage_diff_store=InMemoryReplayTimelineCoverageDiffStore(),
            fingerprint_store=fp_store,
            now=lambda: _utc(0),
        )
        tl_store.save(_timeline())
        fp = fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        assert not hasattr(fp, "pnl")
        assert not hasattr(fp, "metric_observations")
        assert not hasattr(fp, "evaluation_result")
        assert not hasattr(fp, "backtest_result")
