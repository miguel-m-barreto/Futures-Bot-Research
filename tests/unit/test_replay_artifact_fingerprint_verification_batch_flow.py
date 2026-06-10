from __future__ import annotations

from datetime import UTC, datetime

from futures_bot.domain.replay import (
    ReplayArtifactFingerprintVerificationBatchReportStatus,
    ReplayArtifactFingerprintVerificationBatchScopeKind,
    ReplayArtifactFingerprintVerificationStatus,
    ReplayArtifactKind,
    ReplayInputKind,
    ReplayInstrumentRef,
    ReplayOrderingPolicy,
    ReplayTimeline,
    ReplayTimelineEvent,
    ReplayTimelineStatus,
)
from futures_bot.domain.research import TemporalWindow, TemporalWindowKind
from futures_bot.infrastructure.replay.in_memory import (
    InMemoryReplayArtifactFingerprintStore,
    InMemoryReplayArtifactFingerprintVerificationBatchReportStore,
    InMemoryReplayArtifactFingerprintVerificationStore,
    InMemoryReplayTimelineCoverageDiffStore,
    InMemoryReplayTimelineCoverageReportStore,
    InMemoryReplayTimelineStore,
)
from futures_bot.replay.integrity import (
    LocalReplayArtifactFingerprintBatchVerifier,
    LocalReplayArtifactFingerprinter,
    LocalReplayArtifactFingerprintVerifier,
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
        settlement_asset="USDT",
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


def _setup() -> tuple[
    InMemoryReplayTimelineStore,
    InMemoryReplayArtifactFingerprintStore,
    InMemoryReplayArtifactFingerprintVerificationStore,
    InMemoryReplayArtifactFingerprintVerificationBatchReportStore,
    LocalReplayArtifactFingerprinter,
    LocalReplayArtifactFingerprintVerifier,
    LocalReplayArtifactFingerprintBatchVerifier,
]:
    tl_store = InMemoryReplayTimelineStore()
    rep_store = InMemoryReplayTimelineCoverageReportStore()
    diff_store = InMemoryReplayTimelineCoverageDiffStore()
    fp_store = InMemoryReplayArtifactFingerprintStore()
    ver_store = InMemoryReplayArtifactFingerprintVerificationStore()
    batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
    fingerprinter = LocalReplayArtifactFingerprinter(
        timeline_store=tl_store,
        coverage_report_store=rep_store,
        coverage_diff_store=diff_store,
        fingerprint_store=fp_store,
        now=lambda: _utc(5),
    )
    verifier = LocalReplayArtifactFingerprintVerifier(
        timeline_store=tl_store,
        coverage_report_store=rep_store,
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
    return tl_store, fp_store, ver_store, batch_store, fingerprinter, verifier, batch_verifier


class TestReplayArtifactFingerprintVerificationBatchFlow:
    def test_batch_verify_all_valid(self) -> None:
        tl_store, _, _, _, fingerprinter, _, batch_verifier = _setup()
        tl_store.save(_timeline("tl-1", "plan-1"))
        tl_store.save(_timeline("tl-2", "plan-1"))
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        fingerprinter.fingerprint_timeline("fp-2", "tl-2")

        report = batch_verifier.verify_fingerprints("rpt-all-valid", ("fp-1", "fp-2"))

        assert report.summary.total_fingerprints == 2
        assert (
            report.summary.count_by_status.get(
                ReplayArtifactFingerprintVerificationStatus.VALID, 0
            )
            == 2
        )
        assert report.summary.all_valid is True
        assert (
            report.summary.count_by_status.get(
                ReplayArtifactFingerprintVerificationStatus.MISMATCH, 0
            )
            == 0
        )
        assert report.status is ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED

    def test_batch_verify_with_missing_fingerprint(self) -> None:
        tl_store, _, _, _, fingerprinter, _, batch_verifier = _setup()
        tl_store.save(_timeline("tl-1", "plan-1"))
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")

        report = batch_verifier.verify_fingerprints(
            "rpt-mix",
            ("fp-1", "fp-does-not-exist"),
        )

        assert report.summary.total_fingerprints == 2
        assert (
            report.summary.count_by_status.get(
                ReplayArtifactFingerprintVerificationStatus.VALID, 0
            )
            == 1
        )
        assert (
            report.summary.count_by_status.get(
                ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT, 0
            )
            == 1
        )
        assert report.summary.all_valid is False

    def test_batch_verify_replay_plan_flow(self) -> None:
        tl_store, _, _, _, fingerprinter, _, batch_verifier = _setup()
        for i in range(3):
            tl_store.save(_timeline(f"tl-{i}", "plan-batch"))
            fingerprinter.fingerprint_timeline(f"fp-{i}", f"tl-{i}")

        report = batch_verifier.verify_replay_plan("rpt-plan-batch", "plan-batch")

        assert report.replay_plan_id == "plan-batch"
        assert (
            report.scope_kind
            is ReplayArtifactFingerprintVerificationBatchScopeKind.REPLAY_PLAN
        )
        assert report.summary.total_fingerprints == 3
        assert (
            report.summary.count_by_status.get(
                ReplayArtifactFingerprintVerificationStatus.VALID, 0
            )
            == 3
        )
        assert report.summary.all_valid is True

    def test_report_stored_and_retrievable(self) -> None:
        tl_store, _, _, batch_store, fingerprinter, _, batch_verifier = _setup()
        tl_store.save(_timeline("tl-1", "plan-1"))
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")

        report = batch_verifier.verify_fingerprints("rpt-stored", ("fp-1",))

        assert batch_store.load("rpt-stored") == report

    def test_verifications_saved_in_verification_store(self) -> None:
        tl_store, _, ver_store, _, fingerprinter, _, batch_verifier = _setup()
        tl_store.save(_timeline("tl-1", "plan-1"))
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")

        batch_verifier.verify_fingerprints("rpt-ver", ("fp-1",))

        ver_id = "rpt-ver:fp-1:verification"
        loaded_ver = ver_store.load(ver_id)
        assert loaded_ver is not None
        assert loaded_ver.status is ReplayArtifactFingerprintVerificationStatus.VALID

    def test_item_artifact_kind_and_id_copied(self) -> None:
        tl_store, _, _, _, fingerprinter, _, batch_verifier = _setup()
        tl_store.save(_timeline("tl-xyz", "plan-1"))
        fingerprinter.fingerprint_timeline("fp-xyz", "tl-xyz")

        report = batch_verifier.verify_fingerprints("rpt-copy", ("fp-xyz",))

        item = report.items[0]
        assert item.artifact_kind is ReplayArtifactKind.TIMELINE
        assert item.artifact_id == "tl-xyz"
        assert item.replay_plan_id == "plan-1"

    def test_empty_batch_report_all_valid_false(self) -> None:
        _, _, _, _, _, _, batch_verifier = _setup()
        report = batch_verifier.verify_replay_plan("rpt-empty", "plan-none")
        assert report.summary.all_valid is False
        assert report.summary.total_fingerprints == 0

    def test_verify_fingerprints_infers_replay_plan_id(self) -> None:
        tl_store, _, _, _, fingerprinter, _, batch_verifier = _setup()
        tl_store.save(_timeline("tl-1", "plan-infer"))
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")

        report = batch_verifier.verify_fingerprints("rpt-infer", ("fp-1",))
        assert report.replay_plan_id == "plan-infer"
