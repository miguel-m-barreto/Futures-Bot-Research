from __future__ import annotations

from datetime import UTC, datetime

from futures_bot.domain.assets import StableCollateralAsset
from futures_bot.domain.replay import (
    ReplayArtifactFingerprintVerificationBatchItem,
    ReplayArtifactFingerprintVerificationBatchReport,
    ReplayArtifactFingerprintVerificationBatchReportStatus,
    ReplayArtifactFingerprintVerificationBatchScopeKind,
    ReplayArtifactFingerprintVerificationBatchSummary,
    ReplayArtifactFingerprintVerificationStatus,
    ReplayArtifactKind,
    ReplayInputKind,
    ReplayInstrumentRef,
    ReplayOrderingPolicy,
    ReplayReadinessIssueKind,
    ReplayReadinessStatus,
    ReplayTimeline,
    ReplayTimelineEvent,
    ReplayTimelineStatus,
)
from futures_bot.domain.research import TemporalWindow, TemporalWindowKind
from futures_bot.infrastructure.replay.in_memory import (
    InMemoryReplayArtifactFingerprintStore,
    InMemoryReplayArtifactFingerprintVerificationBatchReportStore,
    InMemoryReplayArtifactFingerprintVerificationStore,
    InMemoryReplayReadinessReportStore,
    InMemoryReplayTimelineCoverageDiffStore,
    InMemoryReplayTimelineCoverageReportStore,
    InMemoryReplayTimelineStore,
)
from futures_bot.replay.integrity import (
    LocalReplayArtifactFingerprintBatchVerifier,
    LocalReplayArtifactFingerprinter,
    LocalReplayArtifactFingerprintVerifier,
    LocalReplayReadinessChecker,
)


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _window() -> TemporalWindow:
    return TemporalWindow(
        kind=TemporalWindowKind.TEST,
        start_at=_utc(0),
        end_at=_utc(10),
        window_id="tw-flow",
    )


def _instrument() -> ReplayInstrumentRef:
    return ReplayInstrumentRef(
        venue="binance",
        symbol="BTCUSDT",
        market_type="stablecoin-collateral-futures",
        settlement_asset=StableCollateralAsset("USDT"),
    )


def _timeline(timeline_id: str, plan_id: str) -> ReplayTimeline:
    event = ReplayTimelineEvent(
        event_id=f"ev-{timeline_id}",
        batch_id="batch-1",
        input_dataset_id="ds-1",
        record_id="rec-1",
        kind=ReplayInputKind.MARK_PRICE,
        instrument=_instrument(),
        event_time=_utc(1),
        source_sequence=0,
        order_index=0,
    )
    return ReplayTimeline(
        timeline_id=timeline_id,
        replay_plan_id=plan_id,
        temporal_window=_window(),
        ordering_policy=ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
        input_batch_ids=("batch-1",),
        input_dataset_ids=("ds-1",),
        events=(event,),
        created_at=_utc(0),
        status=ReplayTimelineStatus.BUILT,
    )


def _setup_full_stack() -> tuple[
    InMemoryReplayTimelineStore,
    InMemoryReplayArtifactFingerprintStore,
    InMemoryReplayArtifactFingerprintVerificationStore,
    InMemoryReplayArtifactFingerprintVerificationBatchReportStore,
    InMemoryReplayReadinessReportStore,
    LocalReplayArtifactFingerprinter,
    LocalReplayArtifactFingerprintBatchVerifier,
    LocalReplayReadinessChecker,
]:
    tl_store = InMemoryReplayTimelineStore()
    cov_store = InMemoryReplayTimelineCoverageReportStore()
    diff_store = InMemoryReplayTimelineCoverageDiffStore()
    fp_store = InMemoryReplayArtifactFingerprintStore()
    ver_store = InMemoryReplayArtifactFingerprintVerificationStore()
    batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
    readiness_store = InMemoryReplayReadinessReportStore()

    fingerprinter = LocalReplayArtifactFingerprinter(
        timeline_store=tl_store,
        coverage_report_store=cov_store,
        coverage_diff_store=diff_store,
        fingerprint_store=fp_store,
        now=lambda: _utc(5),
    )
    verifier = LocalReplayArtifactFingerprintVerifier(
        timeline_store=tl_store,
        coverage_report_store=cov_store,
        coverage_diff_store=diff_store,
        fingerprint_store=fp_store,
        verification_store=ver_store,
        now=lambda: _utc(10),
    )
    batch_verifier = LocalReplayArtifactFingerprintBatchVerifier(
        verifier=verifier,
        fingerprint_store=fp_store,
        batch_report_store=batch_store,
        now=lambda: _utc(20),
    )
    checker = LocalReplayReadinessChecker(
        fingerprint_store=fp_store,
        batch_report_store=batch_store,
        readiness_report_store=readiness_store,
        now=lambda: datetime(2026, 1, 2, 0, tzinfo=UTC),
    )
    return (
        tl_store, fp_store, ver_store, batch_store, readiness_store,
        fingerprinter, batch_verifier, checker,
    )


class TestReplayReadinessFlow:
    def test_full_flow_two_timelines_ready(self) -> None:
        (
            tl_store, _, _, _, readiness_store,
            fingerprinter, batch_verifier, checker,
        ) = _setup_full_stack()

        tl_store.save(_timeline("tl-1", "plan-flow"))
        tl_store.save(_timeline("tl-2", "plan-flow"))
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        fingerprinter.fingerprint_timeline("fp-2", "tl-2")
        batch_verifier.verify_replay_plan("batch-1", "plan-flow")

        report = checker.check_replay_plan("readiness-1", "plan-flow")

        assert report.status is ReplayReadinessStatus.READY
        assert report.summary.total_fingerprints == 2
        assert report.summary.latest_batch_all_valid is True
        assert report.issues == ()
        persisted = readiness_store.load("readiness-1")
        assert persisted is not None
        assert persisted.status is ReplayReadinessStatus.READY

    def test_no_fingerprints_blocked(self) -> None:
        (
            _, _, _, _, readiness_store,
            _, _, checker,
        ) = _setup_full_stack()

        report = checker.check_replay_plan("readiness-nofp", "plan-no-fps")

        assert report.status is ReplayReadinessStatus.BLOCKED
        assert any(i.kind is ReplayReadinessIssueKind.NO_FINGERPRINTS for i in report.issues)
        assert readiness_store.load("readiness-nofp") is not None

    def test_fingerprints_no_batch_report_blocked(self) -> None:
        (
            tl_store, _, _, _, _,
            fingerprinter, _, checker,
        ) = _setup_full_stack()

        tl_store.save(_timeline("tl-1", "plan-nobatch"))
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")

        report = checker.check_replay_plan("readiness-nobatch", "plan-nobatch")

        assert report.status is ReplayReadinessStatus.BLOCKED
        assert any(
            i.kind is ReplayReadinessIssueKind.NO_VERIFICATION_BATCH_REPORT
            for i in report.issues
        )

    def test_missing_fingerprint_in_batch_blocked(self) -> None:
        (
            tl_store, _, _, _, _,
            fingerprinter, batch_verifier, checker,
        ) = _setup_full_stack()

        tl_store.save(_timeline("tl-1", "plan-miss"))
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        batch_verifier.verify_fingerprints(
            "batch-miss",
            ("fp-1", "fp-does-not-exist"),
        )

        report = checker.check_replay_plan("readiness-miss", "plan-miss")

        assert report.status is ReplayReadinessStatus.BLOCKED
        verifications = batch_verifier.load_report("batch-miss")
        assert verifications is not None
        assert verifications.summary.has_missing is True

    def test_no_replay_execution_artifacts_created(self) -> None:
        (
            tl_store, fp_store, ver_store, batch_store, readiness_store,
            fingerprinter, batch_verifier, checker,
        ) = _setup_full_stack()

        tl_store.save(_timeline("tl-1", "plan-clean"))
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        batch_verifier.verify_replay_plan("batch-clean", "plan-clean")
        checker.check_replay_plan("readiness-clean", "plan-clean")

        assert all(
            fp.artifact_kind is ReplayArtifactKind.TIMELINE
            for fp in fp_store.list_all()
        )
        assert all(
            v.status is ReplayArtifactFingerprintVerificationStatus.VALID
            for v in ver_store.list_all()
        )
        assert len(batch_store.list_all()) == 1
        assert len(readiness_store.list_all()) == 1

    def test_multiple_issues_reported_simultaneously(self) -> None:
        (
            tl_store, _, _, batch_store, _,
            fingerprinter, _, checker,
        ) = _setup_full_stack()

        tl_store.save(_timeline("tl-1", "plan-multi"))
        tl_store.save(_timeline("tl-2", "plan-multi"))
        fingerprinter.fingerprint_timeline("fp-multi-1", "tl-1")
        fingerprinter.fingerprint_timeline("fp-multi-2", "tl-2")

        item = ReplayArtifactFingerprintVerificationBatchItem(
            item_id="batch-multi:fp-multi-1:item",
            fingerprint_id="fp-multi-1",
            verification_id="batch-multi:fp-multi-1:ver",
            verification_status=ReplayArtifactFingerprintVerificationStatus.MISMATCH,
            issue_count=1,
        )
        summary = ReplayArtifactFingerprintVerificationBatchSummary(
            total_fingerprints=1,
            count_by_status={ReplayArtifactFingerprintVerificationStatus.MISMATCH: 1},
            total_issues=1,
            all_valid=False,
            has_mismatches=True,
            has_missing=False,
        )
        batch = ReplayArtifactFingerprintVerificationBatchReport(
            report_id="batch-multi",
            scope_kind=ReplayArtifactFingerprintVerificationBatchScopeKind.REPLAY_PLAN,
            replay_plan_id="plan-multi",
            generated_at=_utc(20),
            status=ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED,
            summary=summary,
            items=(item,),
            requested_fingerprint_ids=("fp-multi-1",),
        )
        batch_store.save(batch)

        report = checker.check_replay_plan("readiness-multi", "plan-multi")

        kinds = {i.kind for i in report.issues}
        assert report.status is ReplayReadinessStatus.BLOCKED
        assert ReplayReadinessIssueKind.BATCH_HAS_MISMATCHES in kinds
        assert ReplayReadinessIssueKind.BATCH_NOT_ALL_VALID in kinds
        assert ReplayReadinessIssueKind.FINGERPRINT_COUNT_MISMATCH in kinds
