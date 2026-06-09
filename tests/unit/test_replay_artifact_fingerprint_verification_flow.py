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
    plan_id: str = "plan-1",
) -> ReplayTimelineCoverageDiff:
    return ReplayTimelineCoverageDiff(
        diff_id=diff_id,
        baseline_report_id="rep-base",
        candidate_report_id="rep-cand",
        baseline_timeline_id="tl-base",
        candidate_timeline_id="tl-cand",
        baseline_replay_plan_id=plan_id,
        candidate_replay_plan_id=plan_id,
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


class TestFingerprintThenVerifyValidFlow:
    def test_fingerprint_then_verify_timeline_is_valid(self) -> None:
        tl_store, _, _, _, _, fingerprinter, verifier = _setup()
        tl_store.save(_timeline())
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        ver = verifier.verify_fingerprint("ver-1", "fp-1")
        assert ver.status is ReplayArtifactFingerprintVerificationStatus.VALID

    def test_fingerprint_then_verify_coverage_report_is_valid(self) -> None:
        _, rep_store, _, _, _, fingerprinter, verifier = _setup()
        rep_store.save(_coverage_report())
        fingerprinter.fingerprint_coverage_report("fp-rep", "rep-1")
        ver = verifier.verify_fingerprint("ver-1", "fp-rep")
        assert ver.status is ReplayArtifactFingerprintVerificationStatus.VALID

    def test_fingerprint_then_verify_coverage_diff_is_valid(self) -> None:
        _, _, diff_store, _, _, fingerprinter, verifier = _setup()
        diff_store.save(_diff())
        fingerprinter.fingerprint_coverage_diff("fp-diff", "diff-1")
        ver = verifier.verify_fingerprint("ver-1", "fp-diff")
        assert ver.status is ReplayArtifactFingerprintVerificationStatus.VALID

    def test_valid_verification_sha_values_match(self) -> None:
        tl_store, _, _, _, _, fingerprinter, verifier = _setup()
        tl_store.save(_timeline())
        fp = fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        ver = verifier.verify_fingerprint("ver-1", "fp-1")
        assert ver.stored_sha256 == fp.sha256
        assert ver.recomputed_sha256 == fp.sha256

    def test_valid_verification_payloads_match(self) -> None:
        tl_store, _, _, _, _, fingerprinter, verifier = _setup()
        tl_store.save(_timeline())
        fp = fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        ver = verifier.verify_fingerprint("ver-1", "fp-1")
        assert ver.stored_canonical_payload == fp.canonical_payload
        assert ver.recomputed_canonical_payload == fp.canonical_payload

    def test_valid_verification_has_no_issues(self) -> None:
        tl_store, _, _, _, _, fingerprinter, verifier = _setup()
        tl_store.save(_timeline())
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        ver = verifier.verify_fingerprint("ver-1", "fp-1")
        assert ver.issues == ()

    def test_valid_verification_persisted_and_retrievable(self) -> None:
        tl_store, _, _, _, ver_store, fingerprinter, verifier = _setup()
        tl_store.save(_timeline())
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        verifier.verify_fingerprint("ver-1", "fp-1")
        loaded = ver_store.load("ver-1")
        assert loaded is not None
        assert loaded.status is ReplayArtifactFingerprintVerificationStatus.VALID


class TestMissingFingerprintFlow:
    def test_verify_unknown_fingerprint_id_gives_missing_fingerprint(self) -> None:
        *_, verifier = _setup()
        ver = verifier.verify_fingerprint("ver-1", "fp-ghost")
        assert ver.status is ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT

    def test_missing_fingerprint_has_fingerprint_not_found_issue(self) -> None:
        *_, verifier = _setup()
        ver = verifier.verify_fingerprint("ver-1", "fp-ghost")
        kinds = {i.kind for i in ver.issues}
        assert ReplayArtifactFingerprintVerificationIssueKind.FINGERPRINT_NOT_FOUND in kinds

    def test_missing_fingerprint_stored_sha_is_none(self) -> None:
        *_, verifier = _setup()
        ver = verifier.verify_fingerprint("ver-1", "fp-ghost")
        assert ver.stored_sha256 is None
        assert ver.recomputed_sha256 is None


class TestMissingArtifactFlow:
    def test_fingerprint_without_artifact_gives_missing_artifact(self) -> None:
        _, _, _, fp_store, _, _, verifier = _setup()
        _minimal_fingerprint(
            fp_store,
            fingerprint_id="fp-no-tl",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-never-saved",
            id_field="timeline_id",
            replay_plan_id="plan-1",
        )
        ver = verifier.verify_fingerprint("ver-1", "fp-no-tl")
        assert ver.status is ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT

    def test_missing_artifact_has_stored_sha_but_no_recomputed(self) -> None:
        _, _, _, fp_store, _, _, verifier = _setup()
        _minimal_fingerprint(
            fp_store,
            fingerprint_id="fp-no-tl",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-never-saved",
            id_field="timeline_id",
            replay_plan_id="plan-1",
        )
        ver = verifier.verify_fingerprint("ver-1", "fp-no-tl")
        assert ver.stored_sha256 is not None
        assert ver.recomputed_sha256 is None

    def test_missing_artifact_has_artifact_not_found_issue(self) -> None:
        _, _, _, fp_store, _, _, verifier = _setup()
        _minimal_fingerprint(
            fp_store,
            fingerprint_id="fp-no-tl",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-never-saved",
            id_field="timeline_id",
            replay_plan_id="plan-1",
        )
        ver = verifier.verify_fingerprint("ver-1", "fp-no-tl")
        kinds = {i.kind for i in ver.issues}
        assert ReplayArtifactFingerprintVerificationIssueKind.ARTIFACT_NOT_FOUND in kinds


class TestMismatchFlow:
    def test_stale_fingerprint_gives_mismatch(self) -> None:
        tl_store, _, _, fp_store, _, _, verifier = _setup()
        tl_store.save(_timeline())
        _minimal_fingerprint(
            fp_store,
            fingerprint_id="fp-stale",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-1",
            id_field="timeline_id",
            replay_plan_id="plan-1",
        )
        ver = verifier.verify_fingerprint("ver-1", "fp-stale")
        assert ver.status is ReplayArtifactFingerprintVerificationStatus.MISMATCH

    def test_mismatch_has_both_sha_values(self) -> None:
        tl_store, _, _, fp_store, _, _, verifier = _setup()
        tl_store.save(_timeline())
        _minimal_fingerprint(
            fp_store,
            fingerprint_id="fp-stale",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-1",
            id_field="timeline_id",
            replay_plan_id="plan-1",
        )
        ver = verifier.verify_fingerprint("ver-1", "fp-stale")
        assert ver.stored_sha256 is not None
        assert ver.recomputed_sha256 is not None
        assert ver.stored_sha256 != ver.recomputed_sha256

    def test_mismatch_has_hash_mismatch_issue(self) -> None:
        tl_store, _, _, fp_store, _, _, verifier = _setup()
        tl_store.save(_timeline())
        _minimal_fingerprint(
            fp_store,
            fingerprint_id="fp-stale",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-1",
            id_field="timeline_id",
            replay_plan_id="plan-1",
        )
        ver = verifier.verify_fingerprint("ver-1", "fp-stale")
        kinds = {i.kind for i in ver.issues}
        assert ReplayArtifactFingerprintVerificationIssueKind.HASH_MISMATCH in kinds

    def test_mismatch_has_payload_mismatch_issue(self) -> None:
        tl_store, _, _, fp_store, _, _, verifier = _setup()
        tl_store.save(_timeline())
        _minimal_fingerprint(
            fp_store,
            fingerprint_id="fp-stale",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-1",
            id_field="timeline_id",
            replay_plan_id="plan-1",
        )
        ver = verifier.verify_fingerprint("ver-1", "fp-stale")
        kinds = {i.kind for i in ver.issues}
        assert ReplayArtifactFingerprintVerificationIssueKind.CANONICAL_PAYLOAD_MISMATCH in kinds


class TestMultipleVerificationsFlow:
    def test_multiple_verifications_for_same_fingerprint(self) -> None:
        tl_store, _, _, _, ver_store, fingerprinter, verifier = _setup()
        tl_store.save(_timeline())
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        verifier.verify_fingerprint("ver-a", "fp-1")
        verifier.verify_fingerprint("ver-b", "fp-1")
        results = ver_store.list_for_fingerprint("fp-1")
        assert len(results) == 2
        assert all(
            v.status is ReplayArtifactFingerprintVerificationStatus.VALID for v in results
        )

    def test_verifications_queryable_by_artifact(self) -> None:
        tl_store, _, _, _, ver_store, fingerprinter, verifier = _setup()
        tl_store.save(_timeline())
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        verifier.verify_fingerprint("ver-1", "fp-1")
        results = ver_store.list_for_artifact(ReplayArtifactKind.TIMELINE, "tl-1")
        assert len(results) == 1
        assert results[0].artifact_id == "tl-1"

    def test_verifications_queryable_by_replay_plan(self) -> None:
        tl_store, _, _, _, ver_store, fingerprinter, verifier = _setup()
        tl_store.save(_timeline(plan_id="plan-42"))
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        verifier.verify_fingerprint("ver-1", "fp-1")
        results = ver_store.list_for_replay_plan("plan-42")
        assert len(results) == 1
        assert results[0].replay_plan_id == "plan-42"

    def test_verifications_isolated_between_artifacts(self) -> None:
        tl_store, rep_store, _, _, ver_store, fingerprinter, verifier = _setup()
        tl_store.save(_timeline("tl-1"))
        rep_store.save(_coverage_report("rep-1"))
        fingerprinter.fingerprint_timeline("fp-tl", "tl-1")
        fingerprinter.fingerprint_coverage_report("fp-rep", "rep-1")
        verifier.verify_fingerprint("ver-tl", "fp-tl")
        verifier.verify_fingerprint("ver-rep", "fp-rep")
        tl_vers = ver_store.list_for_artifact(ReplayArtifactKind.TIMELINE, "tl-1")
        rep_vers = ver_store.list_for_artifact(ReplayArtifactKind.COVERAGE_REPORT, "rep-1")
        assert len(tl_vers) == 1
        assert len(rep_vers) == 1

    def test_no_execution_attributes_on_verification(self) -> None:
        tl_store, _, _, _, _, fingerprinter, verifier = _setup()
        tl_store.save(_timeline())
        fingerprinter.fingerprint_timeline("fp-1", "tl-1")
        ver = verifier.verify_fingerprint("ver-1", "fp-1")
        assert not hasattr(ver, "pnl")
        assert not hasattr(ver, "metric_observations")
        assert not hasattr(ver, "evaluation_result")
        assert not hasattr(ver, "backtest_result")
