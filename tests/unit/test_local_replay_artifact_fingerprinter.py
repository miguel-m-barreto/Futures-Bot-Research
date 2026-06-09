from __future__ import annotations

from datetime import UTC, datetime

import pytest

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


def _event(event_id: str = "ev-1", order_index: int = 0) -> ReplayTimelineEvent:
    return ReplayTimelineEvent(
        event_id=event_id,
        batch_id="batch-1",
        input_dataset_id="ds-1",
        record_id="rec-1",
        kind=ReplayInputKind.MARK_PRICE,
        instrument=_instrument(),
        event_time=_utc(1),
        source_sequence=0,
        order_index=order_index,
    )


def _timeline(
    timeline_id: str = "tl-1",
    replay_plan_id: str = "plan-1",
) -> ReplayTimeline:
    return ReplayTimeline(
        timeline_id=timeline_id,
        replay_plan_id=replay_plan_id,
        temporal_window=_window(),
        ordering_policy=ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
        input_batch_ids=("batch-1",),
        input_dataset_ids=("ds-1",),
        events=(_event(),),
        created_at=_utc(0),
        status=ReplayTimelineStatus.BUILT,
    )


def _empty_diff_summary() -> ReplayTimelineCoverageDiffSummary:
    return ReplayTimelineCoverageDiffSummary(
        total_items=0,
        item_count_by_kind={},
        item_count_by_severity={},
        has_errors=False,
        has_warnings=False,
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
    report_id: str = "rep-1",
    timeline_id: str = "tl-1",
    replay_plan_id: str = "plan-1",
) -> ReplayTimelineCoverageReport:
    return ReplayTimelineCoverageReport(
        report_id=report_id,
        timeline_id=timeline_id,
        replay_plan_id=replay_plan_id,
        temporal_window=_window(),
        generated_at=_utc(0),
        status=ReplayTimelineCoverageStatus.GENERATED,
        summary=_coverage_summary(),
    )


def _diff(
    diff_id: str = "diff-1",
    baseline_report_id: str = "rep-baseline",
    candidate_report_id: str = "rep-candidate",
    baseline_replay_plan_id: str = "plan-1",
    candidate_replay_plan_id: str = "plan-1",
) -> ReplayTimelineCoverageDiff:
    return ReplayTimelineCoverageDiff(
        diff_id=diff_id,
        baseline_report_id=baseline_report_id,
        candidate_report_id=candidate_report_id,
        baseline_timeline_id="tl-base",
        candidate_timeline_id="tl-cand",
        baseline_replay_plan_id=baseline_replay_plan_id,
        candidate_replay_plan_id=candidate_replay_plan_id,
        generated_at=_utc(0),
        status=ReplayTimelineCoverageDiffStatus.GENERATED,
        summary=_empty_diff_summary(),
    )


def _setup() -> tuple[
    InMemoryReplayTimelineStore,
    InMemoryReplayTimelineCoverageReportStore,
    InMemoryReplayTimelineCoverageDiffStore,
    InMemoryReplayArtifactFingerprintStore,
    LocalReplayArtifactFingerprinter,
]:
    tl_store = InMemoryReplayTimelineStore()
    rep_store = InMemoryReplayTimelineCoverageReportStore()
    diff_store = InMemoryReplayTimelineCoverageDiffStore()
    fp_store = InMemoryReplayArtifactFingerprintStore()
    fingerprinter = LocalReplayArtifactFingerprinter(
        timeline_store=tl_store,
        coverage_report_store=rep_store,
        coverage_diff_store=diff_store,
        fingerprint_store=fp_store,
        now=lambda: _utc(5),
    )
    return tl_store, rep_store, diff_store, fp_store, fingerprinter


class TestLocalReplayArtifactFingerprinterTimeline:
    def test_fingerprint_timeline_returns_fingerprint(self) -> None:
        tl_store, _, _, _, fingerprinter = _setup()
        tl = _timeline()
        tl_store.save(tl)
        fp = fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        assert fp.fingerprint_id == "fp-1"
        assert fp.artifact_kind is ReplayArtifactKind.TIMELINE
        assert fp.artifact_id == "tl-1"
        assert fp.replay_plan_id == "plan-1"
        assert len(fp.sha256) == 64

    def test_fingerprint_timeline_persisted_in_store(self) -> None:
        tl_store, _, _, fp_store, fingerprinter = _setup()
        tl_store.save(_timeline())
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        assert fp_store.load("fp-1") is not None

    def test_fingerprint_timeline_not_found_raises(self) -> None:
        _, _, _, _, fingerprinter = _setup()
        with pytest.raises(ValueError, match="not found"):
            fingerprinter.fingerprint_timeline("fp-1", "no-such-timeline")

    def test_fingerprint_timeline_deterministic_sha256(self) -> None:
        tl_store, _, _, _, fingerprinter = _setup()
        tl = _timeline()
        tl_store.save(tl)
        fp1 = fingerprinter.fingerprint_timeline("fp-a", "tl-1")
        fp2 = fingerprinter.fingerprint_timeline("fp-b", "tl-1")
        assert fp1.sha256 == fp2.sha256

    def test_fingerprint_timeline_with_notes(self) -> None:
        tl_store, _, _, _, fingerprinter = _setup()
        tl_store.save(_timeline())
        fp = fingerprinter.fingerprint_timeline("fp-1", "tl-1", notes="a note")
        assert fp.notes == "a note"


class TestLocalReplayArtifactFingerprinterCoverageReport:
    def test_fingerprint_coverage_report_returns_fingerprint(self) -> None:
        _, rep_store, _, _, fingerprinter = _setup()
        rep = _coverage_report()
        rep_store.save(rep)
        fp = fingerprinter.fingerprint_coverage_report("fp-1", "rep-1")
        assert fp.artifact_kind is ReplayArtifactKind.COVERAGE_REPORT
        assert fp.artifact_id == "rep-1"
        assert fp.replay_plan_id == "plan-1"

    def test_fingerprint_coverage_report_not_found_raises(self) -> None:
        _, _, _, _, fingerprinter = _setup()
        with pytest.raises(ValueError, match="not found"):
            fingerprinter.fingerprint_coverage_report("fp-1", "no-such-report")

    def test_fingerprint_coverage_report_deterministic(self) -> None:
        _, rep_store, _, _, fingerprinter = _setup()
        rep_store.save(_coverage_report())
        fp1 = fingerprinter.fingerprint_coverage_report("fp-a", "rep-1")
        fp2 = fingerprinter.fingerprint_coverage_report("fp-b", "rep-1")
        assert fp1.sha256 == fp2.sha256


class TestLocalReplayArtifactFingerprinterCoverageDiff:
    def test_fingerprint_diff_same_plan_has_replay_plan_id(self) -> None:
        _, _, diff_store, _, fingerprinter = _setup()
        diff_store.save(_diff(baseline_replay_plan_id="plan-1", candidate_replay_plan_id="plan-1"))
        fp = fingerprinter.fingerprint_coverage_diff("fp-1", "diff-1")
        assert fp.artifact_kind is ReplayArtifactKind.COVERAGE_DIFF
        assert fp.replay_plan_id == "plan-1"

    def test_fingerprint_diff_different_plans_has_no_replay_plan_id(self) -> None:
        _, _, diff_store, _, fingerprinter = _setup()
        diff_store.save(_diff(baseline_replay_plan_id="plan-A", candidate_replay_plan_id="plan-B"))
        fp = fingerprinter.fingerprint_coverage_diff("fp-1", "diff-1")
        assert fp.replay_plan_id is None

    def test_fingerprint_diff_not_found_raises(self) -> None:
        _, _, _, _, fingerprinter = _setup()
        with pytest.raises(ValueError, match="not found"):
            fingerprinter.fingerprint_coverage_diff("fp-1", "no-such-diff")

    def test_fingerprint_diff_deterministic(self) -> None:
        _, _, diff_store, _, fingerprinter = _setup()
        diff_store.save(_diff())
        fp1 = fingerprinter.fingerprint_coverage_diff("fp-a", "diff-1")
        fp2 = fingerprinter.fingerprint_coverage_diff("fp-b", "diff-1")
        assert fp1.sha256 == fp2.sha256


class TestLocalReplayArtifactFingerprinterQueries:
    def test_load_fingerprint_returns_none_for_missing(self) -> None:
        _, _, _, _, fingerprinter = _setup()
        assert fingerprinter.load_fingerprint("no-such") is None

    def test_load_fingerprint_returns_saved(self) -> None:
        tl_store, _, _, _, fingerprinter = _setup()
        tl_store.save(_timeline())
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        assert fingerprinter.load_fingerprint("fp-1") is not None

    def test_fingerprints_for_artifact_returns_matching(self) -> None:
        tl_store, _, _, _, fingerprinter = _setup()
        tl_store.save(_timeline())
        fingerprinter.fingerprint_timeline("fp-a", "tl-1")
        fingerprinter.fingerprint_timeline("fp-b", "tl-1")
        results = fingerprinter.fingerprints_for_artifact(ReplayArtifactKind.TIMELINE, "tl-1")
        assert len(results) == 2

    def test_fingerprints_for_artifact_empty_for_unknown(self) -> None:
        _, _, _, _, fingerprinter = _setup()
        results = fingerprinter.fingerprints_for_artifact(ReplayArtifactKind.TIMELINE, "unknown")
        assert results == ()

    def test_fingerprints_for_replay_plan_returns_matching(self) -> None:
        tl_store, rep_store, _, _, fingerprinter = _setup()
        tl_store.save(_timeline(replay_plan_id="plan-1"))
        rep_store.save(_coverage_report(replay_plan_id="plan-1"))
        fingerprinter.fingerprint_timeline("fp-tl", "tl-1")
        fingerprinter.fingerprint_coverage_report("fp-rep", "rep-1")
        results = fingerprinter.fingerprints_for_replay_plan("plan-1")
        assert len(results) == 2

    def test_no_execution_attributes(self) -> None:
        tl_store, _, _, _, fingerprinter = _setup()
        tl_store.save(_timeline())
        fp = fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        assert not hasattr(fp, "pnl")
        assert not hasattr(fp, "metric_observations")
        assert not hasattr(fp, "evaluation_result")
