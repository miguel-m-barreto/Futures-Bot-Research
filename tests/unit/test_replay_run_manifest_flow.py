from __future__ import annotations

from datetime import UTC, datetime

import pytest

from futures_bot.domain.assets import StableCollateralAsset
from futures_bot.domain.replay import (
    ReplayArtifactFingerprint,
    ReplayArtifactFingerprintVerificationStatus,
    ReplayArtifactKind,
    ReplayInputKind,
    ReplayInstrumentRef,
    ReplayOrderingPolicy,
    ReplayReadinessIssue,
    ReplayReadinessIssueKind,
    ReplayReadinessIssueSeverity,
    ReplayReadinessReport,
    ReplayReadinessStatus,
    ReplayReadinessSummary,
    ReplayRunIntentKind,
    ReplayRunManifestStatus,
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
    InMemoryReplayRunManifestStore,
    InMemoryReplayTimelineCoverageDiffStore,
    InMemoryReplayTimelineCoverageReportStore,
    InMemoryReplayTimelineStore,
)
from futures_bot.replay.integrity import (
    LocalReplayArtifactFingerprintBatchVerifier,
    LocalReplayArtifactFingerprinter,
    LocalReplayArtifactFingerprintVerifier,
    LocalReplayReadinessChecker,
    LocalReplayRunPlanner,
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
    InMemoryReplayRunManifestStore,
    LocalReplayArtifactFingerprinter,
    LocalReplayArtifactFingerprintBatchVerifier,
    LocalReplayReadinessChecker,
    LocalReplayRunPlanner,
]:
    tl_store = InMemoryReplayTimelineStore()
    cov_store = InMemoryReplayTimelineCoverageReportStore()
    diff_store = InMemoryReplayTimelineCoverageDiffStore()
    fp_store = InMemoryReplayArtifactFingerprintStore()
    ver_store = InMemoryReplayArtifactFingerprintVerificationStore()
    batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
    readiness_store = InMemoryReplayReadinessReportStore()
    manifest_store = InMemoryReplayRunManifestStore()

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
    planner = LocalReplayRunPlanner(
        readiness_report_store=readiness_store,
        fingerprint_store=fp_store,
        batch_report_store=batch_store,
        run_manifest_store=manifest_store,
        now=lambda: datetime(2026, 1, 2, 1, tzinfo=UTC),
    )
    return (
        tl_store, fp_store, ver_store, batch_store,
        readiness_store, manifest_store,
        fingerprinter, batch_verifier, checker, planner,
    )


class _ControlledFingerprintStore:
    def __init__(self, fingerprints: tuple[ReplayArtifactFingerprint, ...]) -> None:
        self._fingerprints = fingerprints

    def save(self, fingerprint: ReplayArtifactFingerprint) -> None:
        self._fingerprints = (*self._fingerprints, fingerprint)

    def load(self, fingerprint_id: str) -> ReplayArtifactFingerprint | None:
        return next(
            (fp for fp in self._fingerprints if fp.fingerprint_id == fingerprint_id),
            None,
        )

    def list_for_artifact(
        self, artifact_kind: ReplayArtifactKind, artifact_id: str
    ) -> tuple[ReplayArtifactFingerprint, ...]:
        return tuple(
            fp
            for fp in self._fingerprints
            if fp.artifact_kind is artifact_kind and fp.artifact_id == artifact_id
        )

    def list_for_replay_plan(
        self, replay_plan_id: str
    ) -> tuple[ReplayArtifactFingerprint, ...]:
        return tuple(
            fp for fp in self._fingerprints if fp.replay_plan_id == replay_plan_id
        )

    def list_all(self) -> tuple[ReplayArtifactFingerprint, ...]:
        return self._fingerprints


class TestReplayRunManifestFlow:
    def test_full_flow_two_timelines_planned(self) -> None:
        (
            tl_store, fp_store, _, batch_store, _, manifest_store,
            fingerprinter, batch_verifier, checker, planner,
        ) = _setup_full_stack()

        tl_store.save(_timeline("tl-1", "plan-flow"))
        tl_store.save(_timeline("tl-2", "plan-flow"))
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        fingerprinter.fingerprint_timeline("fp-2", "tl-2")
        batch_verifier.verify_replay_plan("batch-flow", "plan-flow")
        readiness_report = checker.check_replay_plan("rpt-flow", "plan-flow")

        assert readiness_report.status is ReplayReadinessStatus.READY

        manifest = planner.plan_replay_run("manifest-flow", "rpt-flow")

        assert manifest.status is ReplayRunManifestStatus.PLANNED
        assert manifest.replay_plan_id == "plan-flow"
        assert manifest.readiness.readiness_status is ReplayReadinessStatus.READY
        assert manifest.fingerprint_ids == ("fp-1", "fp-2")
        assert manifest.fingerprint_ids == manifest.readiness.verified_fingerprint_ids
        assert manifest.replay_plan_id == manifest.readiness.readiness_replay_plan_id
        expected_batch_id = readiness_report.summary.latest_batch_report_id
        assert manifest.verification_batch_report_id == expected_batch_id
        assert expected_batch_id is not None
        batch = batch_store.load(expected_batch_id)
        assert batch is not None
        fingerprints = fp_store.list_for_replay_plan("plan-flow")
        assert all(fp.generated_at <= batch.generated_at for fp in fingerprints)
        assert batch.generated_at <= readiness_report.checked_at
        assert readiness_report.checked_at <= manifest.created_at
        persisted = manifest_store.load("manifest-flow")
        assert persisted is not None
        assert persisted.status is ReplayRunManifestStatus.PLANNED

    def test_blocked_readiness_creates_blocked_manifest(self) -> None:
        (
            _, _, _, _, readiness_store, manifest_store,
            _, _, _, planner,
        ) = _setup_full_stack()

        blocked_report = checker_only_blocked(readiness_store, "plan-blocked")

        manifest = planner.plan_replay_run("manifest-blocked", blocked_report.report_id)

        assert manifest.status is ReplayRunManifestStatus.BLOCKED
        assert manifest_store.load("manifest-blocked") is not None

    def test_no_replay_execution_artifacts_created(self) -> None:
        (
            tl_store, fp_store, ver_store, batch_store,
            readiness_store, manifest_store,
            fingerprinter, batch_verifier, checker, planner,
        ) = _setup_full_stack()

        tl_store.save(_timeline("tl-1", "plan-clean"))
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        batch_verifier.verify_replay_plan("batch-clean", "plan-clean")
        checker.check_replay_plan("rpt-clean", "plan-clean")
        planner.plan_replay_run("manifest-clean", "rpt-clean")

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
        assert len(manifest_store.list_all()) == 1

    def test_intent_kind_backtest_accepted(self) -> None:
        (
            tl_store, _, _, _, _, _,
            fingerprinter, batch_verifier, checker, planner,
        ) = _setup_full_stack()

        tl_store.save(_timeline("tl-1", "plan-bt"))
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        batch_verifier.verify_replay_plan("batch-bt", "plan-bt")
        checker.check_replay_plan("rpt-bt", "plan-bt")

        manifest = planner.plan_replay_run(
            "manifest-bt", "rpt-bt", intent_kind=ReplayRunIntentKind.BACKTEST
        )

        assert manifest.intent_kind is ReplayRunIntentKind.BACKTEST

    def test_no_evaluation_result_set_produced(self) -> None:
        (
            tl_store, _, _, _, _, _,
            fingerprinter, batch_verifier, checker, planner,
        ) = _setup_full_stack()

        tl_store.save(_timeline("tl-1", "plan-eval"))
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        batch_verifier.verify_replay_plan("batch-eval", "plan-eval")
        checker.check_replay_plan("rpt-eval", "plan-eval")
        manifest = planner.plan_replay_run("manifest-eval", "rpt-eval")

        assert not hasattr(manifest, "evaluation_result_set")
        assert not hasattr(manifest, "metric_observations")
        assert not hasattr(manifest, "pnl")

    def test_stale_readiness_raises_after_new_fingerprint(self) -> None:
        (
            tl_store, _, _, _, _, manifest_store,
            fingerprinter, batch_verifier, checker, planner,
        ) = _setup_full_stack()

        tl_store.save(_timeline("tl-stale-1", "plan-stale"))
        fingerprinter.fingerprint_timeline("fp-stale-1", "tl-stale-1")
        batch_verifier.verify_replay_plan("batch-stale", "plan-stale")
        readiness_report = checker.check_replay_plan("rpt-stale", "plan-stale")

        assert readiness_report.status is ReplayReadinessStatus.READY
        assert readiness_report.summary.total_fingerprints == 1

        # Add a second fingerprint after readiness was generated
        tl_store.save(_timeline("tl-stale-2", "plan-stale"))
        fingerprinter.fingerprint_timeline("fp-stale-2", "tl-stale-2")

        with pytest.raises(ValueError, match="stale"):
            planner.plan_replay_run("manifest-stale", "rpt-stale")

        assert manifest_store.load("manifest-stale") is None

    def test_stale_readiness_rejects_same_count_different_fingerprint_id_flow(
        self,
    ) -> None:
        (
            tl_store, _, _, batch_store,
            readiness_store, manifest_store,
            fingerprinter, batch_verifier, checker, _,
        ) = _setup_full_stack()

        tl_store.save(_timeline("tl-original", "plan-identity"))
        original = fingerprinter.fingerprint_timeline("fp-original", "tl-original")
        batch_verifier.verify_replay_plan("batch-identity", "plan-identity")
        readiness_report = checker.check_replay_plan("rpt-identity", "plan-identity")
        different = original.model_copy(update={"fingerprint_id": "fp-different"})
        planner = LocalReplayRunPlanner(
            readiness_report_store=readiness_store,
            fingerprint_store=_ControlledFingerprintStore((different,)),
            batch_report_store=batch_store,
            run_manifest_store=manifest_store,
            now=lambda: datetime(2026, 1, 2, 1, tzinfo=UTC),
        )

        assert readiness_report.status is ReplayReadinessStatus.READY
        assert readiness_report.summary.total_fingerprints == 1

        with pytest.raises(ValueError, match=r"stale|fingerprint identity"):
            planner.plan_replay_run("manifest-identity", "rpt-identity")

        assert manifest_store.load("manifest-identity") is None


def checker_only_blocked(
    readiness_store: InMemoryReplayReadinessReportStore,
    plan_id: str,
) -> ReplayReadinessReport:
    issue = ReplayReadinessIssue(
        issue_id="iss-blocked",
        kind=ReplayReadinessIssueKind.NO_FINGERPRINTS,
        severity=ReplayReadinessIssueSeverity.ERROR,
        message="no fingerprints found",
    )
    report = ReplayReadinessReport(
        report_id=f"rpt-{plan_id}",
        replay_plan_id=plan_id,
        checked_at=datetime(2026, 1, 2, 0, tzinfo=UTC),
        status=ReplayReadinessStatus.BLOCKED,
        summary=ReplayReadinessSummary(
            total_fingerprints=0,
            latest_batch_report_id=None,
            latest_batch_all_valid=None,
            blocking_issue_count=1,
            warning_issue_count=0,
            info_issue_count=0,
        ),
        issues=(issue,),
    )
    readiness_store.save(report)
    return report
