from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest

from futures_bot.domain.replay import (
    ReplayArtifactFingerprint,
    ReplayArtifactFingerprintStatus,
    ReplayArtifactFingerprintVerificationBatchReportStatus,
    ReplayArtifactFingerprintVerificationBatchScopeKind,
    ReplayArtifactFingerprintVerificationStatus,
    ReplayArtifactHashAlgorithm,
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
        window_id="tw-1",
    )


def _timeline(timeline_id: str = "tl-1", plan_id: str = "plan-1") -> ReplayTimeline:
    event = ReplayTimelineEvent(
        event_id="ev-0",
        batch_id="batch-1",
        input_dataset_id="ds-1",
        record_id="rec-1",
        kind=ReplayInputKind.MARK_PRICE,
        instrument=ReplayInstrumentRef(
            venue="binance",
            symbol="BTCUSDT",
            market_type="stablecoin-collateral-futures",
            settlement_asset="USDT",
        ),
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


def _save_fingerprint_for_missing_artifact(  # noqa: PLR0913
    fp_store: InMemoryReplayArtifactFingerprintStore,
    *,
    fingerprint_id: str,
    artifact_kind: ReplayArtifactKind,
    artifact_id: str,
    id_field: str,
    replay_plan_id: str | None = None,
) -> None:
    artifact: dict[str, object] = {id_field: artifact_id}
    if replay_plan_id is not None:
        artifact["replay_plan_id"] = replay_plan_id
    payload = json.dumps(
        {"artifact_kind": artifact_kind.value, "artifact": artifact},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    fp = ReplayArtifactFingerprint(
        fingerprint_id=fingerprint_id,
        artifact_kind=artifact_kind,
        artifact_id=artifact_id,
        replay_plan_id=replay_plan_id,
        generated_at=_utc(5),
        status=ReplayArtifactFingerprintStatus.GENERATED,
        hash_algorithm=ReplayArtifactHashAlgorithm.SHA256,
        canonical_payload=payload,
        sha256=sha,
    )
    fp_store.save(fp)


class TestLocalReplayArtifactFingerprintBatchVerifierSmoke:
    def test_verify_fingerprints_smoke(self) -> None:
        _, _, _, _, _, _, batch_verifier = _setup()
        report = batch_verifier.verify_fingerprints("batch-1", ("fp-1", "fp-2"))
        assert report.report_id == "batch-1"
        assert len(report.items) == 2

    def test_duplicate_fingerprint_ids_rejected(self) -> None:
        _, _, _, _, _, _, batch_verifier = _setup()
        with pytest.raises(ValueError, match="duplicate"):
            batch_verifier.verify_fingerprints("rpt-dup", ("fp-1", "fp-1"))


class TestLocalReplayArtifactFingerprintBatchVerifierEmptySet:
    def test_verify_fingerprints_empty_returns_empty_report(self) -> None:
        _, _, _, _, _, _, batch_verifier = _setup()
        report = batch_verifier.verify_fingerprints("rpt-1", ())
        assert report.report_id == "rpt-1"
        assert len(report.items) == 0
        assert report.summary.total_fingerprints == 0
        assert report.summary.all_valid is False
        assert report.status is ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED

    def test_verify_fingerprints_empty_replay_plan_id_none(self) -> None:
        _, _, _, _, _, _, batch_verifier = _setup()
        report = batch_verifier.verify_fingerprints("rpt-1", ())
        assert report.replay_plan_id is None

    def test_verify_replay_plan_empty(self) -> None:
        _, _, _, _, _, _, batch_verifier = _setup()
        report = batch_verifier.verify_replay_plan("rpt-empty", "plan-no-fps")
        assert report.summary.total_fingerprints == 0
        assert report.summary.all_valid is False
        assert report.replay_plan_id == "plan-no-fps"
        assert (
            report.scope_kind
            is ReplayArtifactFingerprintVerificationBatchScopeKind.REPLAY_PLAN
        )


class TestLocalReplayArtifactFingerprintBatchVerifierSingleValid:
    def test_verify_single_valid_fingerprint(self) -> None:
        tl_store, _, _, _, fingerprinter, _, batch_verifier = _setup()
        tl_store.save(_timeline("tl-1", "plan-1"))
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")

        report = batch_verifier.verify_fingerprints("rpt-1", ("fp-1",))

        assert report.summary.total_fingerprints == 1
        assert (
            report.summary.count_by_status.get(
                ReplayArtifactFingerprintVerificationStatus.VALID, 0
            )
            == 1
        )
        assert (
            report.summary.count_by_status.get(
                ReplayArtifactFingerprintVerificationStatus.MISMATCH, 0
            )
            == 0
        )
        assert report.summary.all_valid is True
        assert len(report.items) == 1
        assert (
            report.items[0].verification_status
            is ReplayArtifactFingerprintVerificationStatus.VALID
        )

    def test_verify_single_valid_infers_replay_plan_id(self) -> None:
        tl_store, _, _, _, fingerprinter, _, batch_verifier = _setup()
        tl_store.save(_timeline("tl-1", "plan-1"))
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")

        report = batch_verifier.verify_fingerprints("rpt-1", ("fp-1",))
        assert report.replay_plan_id == "plan-1"

    def test_deterministic_item_id(self) -> None:
        tl_store, _, _, _, fingerprinter, _, batch_verifier = _setup()
        tl_store.save(_timeline("tl-1", "plan-1"))
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")

        report = batch_verifier.verify_fingerprints("rpt-abc", ("fp-1",))
        assert report.items[0].item_id == "rpt-abc:fp-1:item"

    def test_deterministic_verification_id(self) -> None:
        tl_store, _, _, _, fingerprinter, _, batch_verifier = _setup()
        tl_store.save(_timeline("tl-1", "plan-1"))
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")

        report = batch_verifier.verify_fingerprints("rpt-abc", ("fp-1",))
        assert report.items[0].verification_id == "rpt-abc:fp-1:verification"


class TestLocalReplayArtifactFingerprintBatchVerifierMixedStatuses:
    def test_missing_fingerprint_in_batch(self) -> None:
        _, _, _, _, _, _, batch_verifier = _setup()
        report = batch_verifier.verify_fingerprints("rpt-1", ("fp-missing",))
        assert report.summary.total_fingerprints == 1
        assert (
            report.summary.count_by_status.get(
                ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT, 0
            )
            == 1
        )
        assert report.summary.all_valid is False
        assert (
            report.items[0].verification_status
            is ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT
        )

    def test_missing_artifact_in_batch(self) -> None:
        _, fp_store, _, _, _, _, batch_verifier = _setup()
        _save_fingerprint_for_missing_artifact(
            fp_store,
            fingerprint_id="fp-no-art",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-gone",
            id_field="timeline_id",
        )

        report = batch_verifier.verify_fingerprints("rpt-1", ("fp-no-art",))
        assert (
            report.summary.count_by_status.get(
                ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT, 0
            )
            == 1
        )
        assert (
            report.items[0].verification_status
            is ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT
        )

    def test_mixed_statuses_summary(self) -> None:
        tl_store, fp_store, _, _, fingerprinter, _, batch_verifier = _setup()
        tl_store.save(_timeline("tl-1", "plan-1"))
        fingerprinter.fingerprint_timeline("fp-valid", "tl-1")
        _save_fingerprint_for_missing_artifact(
            fp_store,
            fingerprint_id="fp-no-art",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-gone",
            id_field="timeline_id",
        )

        report = batch_verifier.verify_fingerprints(
            "rpt-mix",
            ("fp-valid", "fp-missing", "fp-no-art"),
        )
        assert report.summary.total_fingerprints == 3
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
        assert (
            report.summary.count_by_status.get(
                ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT, 0
            )
            == 1
        )
        assert report.summary.all_valid is False

    def test_multiple_plans_replay_plan_id_none(self) -> None:
        tl_store, _, _, _, fingerprinter, _, batch_verifier = _setup()
        tl_store.save(_timeline("tl-a", "plan-A"))
        tl_store.save(_timeline("tl-b", "plan-B"))
        fingerprinter.fingerprint_timeline("fp-a", "tl-a")
        fingerprinter.fingerprint_timeline("fp-b", "tl-b")

        report = batch_verifier.verify_fingerprints("rpt-cross", ("fp-a", "fp-b"))
        assert report.replay_plan_id is None

    def test_missing_fingerprint_replay_plan_id_none(self) -> None:
        _, _, _, _, _, _, batch_verifier = _setup()
        report = batch_verifier.verify_fingerprints("rpt-1", ("fp-missing",))
        assert report.replay_plan_id is None


class TestLocalReplayArtifactFingerprintBatchVerifierReplayPlan:
    def test_verify_replay_plan_scope_kind(self) -> None:
        tl_store, _, _, _, fingerprinter, _, batch_verifier = _setup()
        tl_store.save(_timeline("tl-1", "plan-1"))
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")

        report = batch_verifier.verify_replay_plan("rpt-plan", "plan-1")
        assert (
            report.scope_kind
            is ReplayArtifactFingerprintVerificationBatchScopeKind.REPLAY_PLAN
        )

    def test_verify_replay_plan_sets_replay_plan_id(self) -> None:
        tl_store, _, _, _, fingerprinter, _, batch_verifier = _setup()
        tl_store.save(_timeline("tl-1", "plan-1"))
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")

        report = batch_verifier.verify_replay_plan("rpt-plan", "plan-1")
        assert report.replay_plan_id == "plan-1"

    def test_verify_replay_plan_verifies_all_fingerprints(self) -> None:
        tl_store, _, _, _, fingerprinter, _, batch_verifier = _setup()
        tl_store.save(_timeline("tl-1", "plan-1"))
        tl_store.save(_timeline("tl-2", "plan-1"))
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        fingerprinter.fingerprint_timeline("fp-2", "tl-2")

        report = batch_verifier.verify_replay_plan("rpt-plan", "plan-1")
        assert report.summary.total_fingerprints == 2
        assert (
            report.summary.count_by_status.get(
                ReplayArtifactFingerprintVerificationStatus.VALID, 0
            )
            == 2
        )
        assert report.summary.all_valid is True

    def test_report_saved_in_batch_store(self) -> None:
        tl_store, _, _, batch_store, fingerprinter, _, batch_verifier = _setup()
        tl_store.save(_timeline("tl-1", "plan-1"))
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")

        report = batch_verifier.verify_fingerprints("rpt-store", ("fp-1",))
        loaded = batch_store.load("rpt-store")
        assert loaded == report

    def test_load_report(self) -> None:
        tl_store, _, _, _, fingerprinter, _, batch_verifier = _setup()
        tl_store.save(_timeline("tl-1", "plan-1"))
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")

        batch_verifier.verify_fingerprints("rpt-load", ("fp-1",))
        loaded = batch_verifier.load_report("rpt-load")
        assert loaded is not None
        assert loaded.report_id == "rpt-load"

    def test_load_report_none_for_missing(self) -> None:
        _, _, _, _, _, _, batch_verifier = _setup()
        assert batch_verifier.load_report("no-such-report") is None

    def test_reports_for_replay_plan(self) -> None:
        tl_store, _, _, _, fingerprinter, _, batch_verifier = _setup()
        tl_store.save(_timeline("tl-1", "plan-1"))
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")

        batch_verifier.verify_replay_plan("rpt-plan-1", "plan-1")
        reports = batch_verifier.reports_for_replay_plan("plan-1")
        assert len(reports) == 1
        assert reports[0].report_id == "rpt-plan-1"
