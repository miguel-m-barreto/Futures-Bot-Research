from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from futures_bot.domain.replay import (
    ReplayArtifactFingerprint,
    ReplayArtifactFingerprintStatus,
    ReplayArtifactFingerprintVerificationIssueKind,
    ReplayArtifactFingerprintVerificationStatus,
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
    InMemoryReplayArtifactFingerprintVerificationStore,
    InMemoryReplayTimelineCoverageDiffStore,
    InMemoryReplayTimelineCoverageReportStore,
    InMemoryReplayTimelineStore,
)
from futures_bot.replay.integrity import (
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
    report_id: str = "rep-1",
    timeline_id: str = "tl-1",
    plan_id: str = "plan-1",
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
    diff_id: str = "diff-1",
    baseline_plan: str = "plan-1",
    candidate_plan: str = "plan-1",
) -> ReplayTimelineCoverageDiff:
    return ReplayTimelineCoverageDiff(
        diff_id=diff_id,
        baseline_report_id="rep-baseline",
        candidate_report_id="rep-candidate",
        baseline_timeline_id="tl-base",
        candidate_timeline_id="tl-cand",
        baseline_replay_plan_id=baseline_plan,
        candidate_replay_plan_id=candidate_plan,
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


def _setup() -> tuple[
    InMemoryReplayTimelineStore,
    InMemoryReplayTimelineCoverageReportStore,
    InMemoryReplayTimelineCoverageDiffStore,
    InMemoryReplayArtifactFingerprintStore,
    InMemoryReplayArtifactFingerprintVerificationStore,
    LocalReplayArtifactFingerprinter,
    LocalReplayArtifactFingerprintVerifier,
]:
    tl_store = InMemoryReplayTimelineStore()
    rep_store = InMemoryReplayTimelineCoverageReportStore()
    diff_store = InMemoryReplayTimelineCoverageDiffStore()
    fp_store = InMemoryReplayArtifactFingerprintStore()
    ver_store = InMemoryReplayArtifactFingerprintVerificationStore()
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
    return tl_store, rep_store, diff_store, fp_store, ver_store, fingerprinter, verifier


def _minimal_fingerprint(  # noqa: PLR0913
    fp_store: InMemoryReplayArtifactFingerprintStore,
    *,
    fingerprint_id: str,
    artifact_kind: ReplayArtifactKind,
    artifact_id: str,
    id_field: str,
    replay_plan_id: str | None = None,
) -> None:
    """Save a fingerprint with a minimal (single-field) artifact payload.

    Used to simulate a fingerprint whose payload won't match the real artifact.
    """
    artifact: dict[str, object] = {id_field: artifact_id}
    if replay_plan_id is not None:
        if artifact_kind is ReplayArtifactKind.COVERAGE_DIFF:
            artifact["baseline_replay_plan_id"] = replay_plan_id
            artifact["candidate_replay_plan_id"] = replay_plan_id
        else:
            artifact["replay_plan_id"] = replay_plan_id
    structure: dict[str, object] = {"artifact_kind": artifact_kind.value, "artifact": artifact}
    payload = json.dumps(structure, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    fp = ReplayArtifactFingerprint(
        fingerprint_id=fingerprint_id,
        artifact_kind=artifact_kind,
        artifact_id=artifact_id,
        replay_plan_id=replay_plan_id,
        generated_at=_utc(5),
        status=ReplayArtifactFingerprintStatus.GENERATED,
        canonical_payload=payload,
        sha256=sha,
    )
    fp_store.save(fp)


class TestLocalReplayArtifactFingerprintVerifierMissingFingerprint:
    def test_missing_fingerprint_returns_missing_fingerprint_status(self) -> None:
        *_, verifier = _setup()
        ver = verifier.verify_fingerprint("ver-1", "fp-nonexistent")
        assert ver.status is ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT
        assert ver.stored_sha256 is None
        assert ver.recomputed_sha256 is None

    def test_missing_fingerprint_has_fingerprint_not_found_issue(self) -> None:
        *_, verifier = _setup()
        ver = verifier.verify_fingerprint("ver-1", "fp-nonexistent")
        assert len(ver.issues) == 1
        assert (
            ver.issues[0].kind
            is ReplayArtifactFingerprintVerificationIssueKind.FINGERPRINT_NOT_FOUND
        )

    def test_missing_fingerprint_saved_to_store(self) -> None:
        *_, ver_store, _, verifier = _setup()
        verifier.verify_fingerprint("ver-1", "fp-nonexistent")
        assert ver_store.load("ver-1") is not None


class TestLocalReplayArtifactFingerprintVerifierMissingArtifact:
    def test_missing_timeline_returns_missing_artifact(self) -> None:
        # fingerprint exists but no timeline in store
        _, _, _, fp_store, _, _, verifier = _setup()
        _minimal_fingerprint(
            fp_store,
            fingerprint_id="fp-1",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-missing",
            id_field="timeline_id",
            replay_plan_id="plan-1",
        )
        ver = verifier.verify_fingerprint("ver-1", "fp-1")
        assert ver.status is ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT

    def test_missing_artifact_has_artifact_not_found_issue(self) -> None:
        _, _, _, fp_store, _, _, verifier = _setup()
        _minimal_fingerprint(
            fp_store,
            fingerprint_id="fp-1",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-missing",
            id_field="timeline_id",
            replay_plan_id="plan-1",
        )
        ver = verifier.verify_fingerprint("ver-1", "fp-1")
        assert any(
            i.kind is ReplayArtifactFingerprintVerificationIssueKind.ARTIFACT_NOT_FOUND
            for i in ver.issues
        )

    def test_missing_artifact_has_stored_sha_not_recomputed(self) -> None:
        _, _, _, fp_store, _, _, verifier = _setup()
        _minimal_fingerprint(
            fp_store,
            fingerprint_id="fp-1",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-missing",
            id_field="timeline_id",
            replay_plan_id="plan-1",
        )
        ver = verifier.verify_fingerprint("ver-1", "fp-1")
        assert ver.stored_sha256 is not None
        assert ver.recomputed_sha256 is None

    def test_missing_coverage_report_returns_missing_artifact(self) -> None:
        _, _, _, fp_store, _, _, verifier = _setup()
        _minimal_fingerprint(
            fp_store,
            fingerprint_id="fp-rep",
            artifact_kind=ReplayArtifactKind.COVERAGE_REPORT,
            artifact_id="rep-missing",
            id_field="report_id",
            replay_plan_id="plan-1",
        )
        ver = verifier.verify_fingerprint("ver-1", "fp-rep")
        assert ver.status is ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT

    def test_missing_coverage_diff_returns_missing_artifact(self) -> None:
        _, _, _, fp_store, _, _, verifier = _setup()
        _minimal_fingerprint(
            fp_store,
            fingerprint_id="fp-diff",
            artifact_kind=ReplayArtifactKind.COVERAGE_DIFF,
            artifact_id="diff-missing",
            id_field="diff_id",
            replay_plan_id="plan-1",
        )
        ver = verifier.verify_fingerprint("ver-1", "fp-diff")
        assert ver.status is ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT


class TestLocalReplayArtifactFingerprintVerifierValid:
    def test_valid_timeline_returns_valid(self) -> None:
        tl_store, _, _, _, _, fingerprinter, verifier = _setup()
        tl_store.save(_timeline())
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        ver = verifier.verify_fingerprint("ver-1", "fp-1")
        assert ver.status is ReplayArtifactFingerprintVerificationStatus.VALID
        assert ver.stored_sha256 == ver.recomputed_sha256
        assert ver.issues == ()

    def test_valid_coverage_report_returns_valid(self) -> None:
        _, rep_store, _, _, _, fingerprinter, verifier = _setup()
        rep_store.save(_coverage_report())
        fingerprinter.fingerprint_coverage_report("fp-rep", "rep-1")
        ver = verifier.verify_fingerprint("ver-1", "fp-rep")
        assert ver.status is ReplayArtifactFingerprintVerificationStatus.VALID

    def test_valid_coverage_diff_returns_valid(self) -> None:
        _, _, diff_store, _, _, fingerprinter, verifier = _setup()
        diff_store.save(_diff())
        fingerprinter.fingerprint_coverage_diff("fp-diff", "diff-1")
        ver = verifier.verify_fingerprint("ver-1", "fp-diff")
        assert ver.status is ReplayArtifactFingerprintVerificationStatus.VALID

    def test_valid_has_artifact_metadata(self) -> None:
        tl_store, _, _, _, _, fingerprinter, verifier = _setup()
        tl_store.save(_timeline())
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        ver = verifier.verify_fingerprint("ver-1", "fp-1")
        assert ver.artifact_kind is ReplayArtifactKind.TIMELINE
        assert ver.artifact_id == "tl-1"
        assert ver.replay_plan_id == "plan-1"

    def test_valid_persisted_to_store(self) -> None:
        tl_store, _, _, _, ver_store, fingerprinter, verifier = _setup()
        tl_store.save(_timeline())
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        verifier.verify_fingerprint("ver-1", "fp-1")
        assert ver_store.load("ver-1") is not None

    def test_valid_notes_propagated(self) -> None:
        tl_store, _, _, _, _, fingerprinter, verifier = _setup()
        tl_store.save(_timeline())
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        ver = verifier.verify_fingerprint("ver-1", "fp-1", notes="manual audit")
        assert ver.notes == "manual audit"

    def test_valid_payloads_match(self) -> None:
        tl_store, _, _, _, _, fingerprinter, verifier = _setup()
        tl_store.save(_timeline())
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        ver = verifier.verify_fingerprint("ver-1", "fp-1")
        assert ver.stored_canonical_payload == ver.recomputed_canonical_payload


class TestLocalReplayArtifactFingerprintVerifierMismatch:
    def test_mismatched_timeline_returns_mismatch(self) -> None:
        tl_store, _, _, fp_store, _, _, verifier = _setup()
        tl_store.save(_timeline())
        _minimal_fingerprint(
            fp_store,
            fingerprint_id="fp-wrong",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-1",
            id_field="timeline_id",
            replay_plan_id="plan-1",
        )
        ver = verifier.verify_fingerprint("ver-1", "fp-wrong")
        assert ver.status is ReplayArtifactFingerprintVerificationStatus.MISMATCH

    def test_mismatch_has_hash_mismatch_issue(self) -> None:
        tl_store, _, _, fp_store, _, _, verifier = _setup()
        tl_store.save(_timeline())
        _minimal_fingerprint(
            fp_store,
            fingerprint_id="fp-wrong",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-1",
            id_field="timeline_id",
            replay_plan_id="plan-1",
        )
        ver = verifier.verify_fingerprint("ver-1", "fp-wrong")
        assert any(
            i.kind is ReplayArtifactFingerprintVerificationIssueKind.HASH_MISMATCH
            for i in ver.issues
        )

    def test_mismatch_has_payload_mismatch_issue(self) -> None:
        tl_store, _, _, fp_store, _, _, verifier = _setup()
        tl_store.save(_timeline())
        _minimal_fingerprint(
            fp_store,
            fingerprint_id="fp-wrong",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-1",
            id_field="timeline_id",
            replay_plan_id="plan-1",
        )
        ver = verifier.verify_fingerprint("ver-1", "fp-wrong")
        assert any(
            i.kind is ReplayArtifactFingerprintVerificationIssueKind.CANONICAL_PAYLOAD_MISMATCH
            for i in ver.issues
        )

    def test_mismatch_coverage_report(self) -> None:
        _, rep_store, _, fp_store, _, _, verifier = _setup()
        rep_store.save(_coverage_report())
        _minimal_fingerprint(
            fp_store,
            fingerprint_id="fp-wrong",
            artifact_kind=ReplayArtifactKind.COVERAGE_REPORT,
            artifact_id="rep-1",
            id_field="report_id",
            replay_plan_id="plan-1",
        )
        ver = verifier.verify_fingerprint("ver-1", "fp-wrong")
        assert ver.status is ReplayArtifactFingerprintVerificationStatus.MISMATCH

    def test_mismatch_coverage_diff(self) -> None:
        _, _, diff_store, fp_store, _, _, verifier = _setup()
        diff_store.save(_diff())
        _minimal_fingerprint(
            fp_store,
            fingerprint_id="fp-wrong",
            artifact_kind=ReplayArtifactKind.COVERAGE_DIFF,
            artifact_id="diff-1",
            id_field="diff_id",
            replay_plan_id="plan-1",
        )
        ver = verifier.verify_fingerprint("ver-1", "fp-wrong")
        assert ver.status is ReplayArtifactFingerprintVerificationStatus.MISMATCH


class TestLocalReplayArtifactFingerprintVerifierQueries:
    def test_load_verification_returns_none_for_missing(self) -> None:
        *_, verifier = _setup()
        assert verifier.load_verification("no-such") is None

    def test_load_verification_returns_saved(self) -> None:
        tl_store, _, _, _, _, fingerprinter, verifier = _setup()
        tl_store.save(_timeline())
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        verifier.verify_fingerprint("ver-1", "fp-1")
        assert verifier.load_verification("ver-1") is not None

    def test_verifications_for_fingerprint(self) -> None:
        tl_store, _, _, _, _, fingerprinter, verifier = _setup()
        tl_store.save(_timeline())
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        verifier.verify_fingerprint("ver-a", "fp-1")
        verifier.verify_fingerprint("ver-b", "fp-1")
        results = verifier.verifications_for_fingerprint("fp-1")
        assert len(results) == 2

    def test_verifications_for_artifact(self) -> None:
        tl_store, _, _, _, _, fingerprinter, verifier = _setup()
        tl_store.save(_timeline())
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        verifier.verify_fingerprint("ver-1", "fp-1")
        results = verifier.verifications_for_artifact(ReplayArtifactKind.TIMELINE, "tl-1")
        assert len(results) == 1

    def test_verifications_for_replay_plan(self) -> None:
        tl_store, _, _, _, _, fingerprinter, verifier = _setup()
        tl_store.save(_timeline())
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        verifier.verify_fingerprint("ver-1", "fp-1")
        results = verifier.verifications_for_replay_plan("plan-1")
        assert len(results) == 1

    def test_no_execution_attributes(self) -> None:
        tl_store, _, _, _, _, fingerprinter, verifier = _setup()
        tl_store.save(_timeline())
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        ver = verifier.verify_fingerprint("ver-1", "fp-1")
        assert not hasattr(ver, "pnl")
        assert not hasattr(ver, "metric_observations")
        assert not hasattr(ver, "evaluation_result")
        assert not hasattr(ver, "backtest_result")
