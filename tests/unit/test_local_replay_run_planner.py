from __future__ import annotations

import ast
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from futures_bot.domain.replay import (
    ReplayArtifactFingerprint,
    ReplayArtifactFingerprintStatus,
    ReplayArtifactFingerprintVerificationBatchItem,
    ReplayArtifactFingerprintVerificationBatchReport,
    ReplayArtifactFingerprintVerificationBatchReportStatus,
    ReplayArtifactFingerprintVerificationBatchScopeKind,
    ReplayArtifactFingerprintVerificationBatchSummary,
    ReplayArtifactFingerprintVerificationStatus,
    ReplayArtifactHashAlgorithm,
    ReplayArtifactKind,
    ReplayReadinessIssue,
    ReplayReadinessIssueKind,
    ReplayReadinessIssueSeverity,
    ReplayReadinessReport,
    ReplayReadinessStatus,
    ReplayReadinessSummary,
    ReplayRunIntentKind,
    ReplayRunManifest,
    ReplayRunManifestStatus,
)
from futures_bot.infrastructure.replay.in_memory import (
    InMemoryReplayArtifactFingerprintStore,
    InMemoryReplayArtifactFingerprintVerificationBatchReportStore,
    InMemoryReplayReadinessReportStore,
    InMemoryReplayRunManifestStore,
)
from futures_bot.replay.integrity import LocalReplayRunPlanner


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _fp(
    fp_id: str, plan_id: str, generated_at: datetime | None = None
) -> ReplayArtifactFingerprint:
    artifact_id = f"tl-{fp_id}"
    artifact: dict[str, object] = {"timeline_id": artifact_id, "replay_plan_id": plan_id}
    data: dict[str, object] = {
        "artifact_kind": ReplayArtifactKind.TIMELINE.value,
        "artifact": artifact,
    }
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    sha = hashlib.sha256(payload.encode()).hexdigest()
    return ReplayArtifactFingerprint(
        fingerprint_id=fp_id,
        replay_plan_id=plan_id,
        artifact_kind=ReplayArtifactKind.TIMELINE,
        artifact_id=artifact_id,
        generated_at=generated_at or _utc(0),
        status=ReplayArtifactFingerprintStatus.GENERATED,
        hash_algorithm=ReplayArtifactHashAlgorithm.SHA256,
        canonical_payload=payload,
        sha256=sha,
    )


def _ready_readiness_report(
    report_id: str,
    plan_id: str,
    batch_id: str,
    total_fingerprints: int = 2,
) -> ReplayReadinessReport:
    return ReplayReadinessReport(
        report_id=report_id,
        replay_plan_id=plan_id,
        checked_at=_utc(5),
        status=ReplayReadinessStatus.READY,
        summary=ReplayReadinessSummary(
            total_fingerprints=total_fingerprints,
            latest_batch_report_id=batch_id,
            latest_batch_all_valid=True,
            latest_batch_total_fingerprints=total_fingerprints,
            latest_batch_total_issues=0,
            blocking_issue_count=0,
            warning_issue_count=0,
            info_issue_count=0,
        ),
    )


def _batch_report(  # noqa: PLR0913
    report_id: str,
    plan_id: str,
    fingerprint_ids: tuple[str, ...],
    *,
    generated_at: datetime | None = None,
    status: ReplayArtifactFingerprintVerificationBatchReportStatus = (
        ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED
    ),
    all_valid: bool = True,
) -> ReplayArtifactFingerprintVerificationBatchReport:
    verification_status = (
        ReplayArtifactFingerprintVerificationStatus.VALID
        if all_valid
        else ReplayArtifactFingerprintVerificationStatus.MISMATCH
    )
    issue_count = 0 if all_valid else 1
    items = tuple(
        ReplayArtifactFingerprintVerificationBatchItem(
            item_id=f"{report_id}:{fp_id}:item",
            fingerprint_id=fp_id,
            verification_id=f"{report_id}:{fp_id}:verification",
            verification_status=verification_status,
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id=f"tl-{fp_id}",
            replay_plan_id=plan_id,
            issue_count=issue_count,
        )
        for fp_id in fingerprint_ids
    )
    count_by_status = ({verification_status: len(fingerprint_ids)} if fingerprint_ids else {})
    summary = ReplayArtifactFingerprintVerificationBatchSummary(
        total_fingerprints=len(fingerprint_ids),
        count_by_status=count_by_status,
        total_issues=issue_count * len(fingerprint_ids),
        all_valid=all_valid,
        has_mismatches=not all_valid and bool(fingerprint_ids),
        has_missing=False,
    )
    return ReplayArtifactFingerprintVerificationBatchReport(
        report_id=report_id,
        scope_kind=ReplayArtifactFingerprintVerificationBatchScopeKind.REPLAY_PLAN,
        replay_plan_id=plan_id,
        generated_at=generated_at or _utc(4),
        status=status,
        summary=summary,
        items=items,
        requested_fingerprint_ids=fingerprint_ids,
    )


class _StaticReadinessReportStore:
    def __init__(self, report: ReplayReadinessReport) -> None:
        self._report = report

    def save(self, report: ReplayReadinessReport) -> None:
        self._report = report

    def load(self, report_id: str) -> ReplayReadinessReport | None:
        if report_id == self._report.report_id:
            return self._report
        return None

    def list_for_replay_plan(
        self, replay_plan_id: str
    ) -> tuple[ReplayReadinessReport, ...]:
        if replay_plan_id == self._report.replay_plan_id:
            return (self._report,)
        return ()

    def list_all(self) -> tuple[ReplayReadinessReport, ...]:
        return (self._report,)


class _StaticBatchReportStore:
    def __init__(self, report: ReplayArtifactFingerprintVerificationBatchReport) -> None:
        self._report = report

    def save(self, report: ReplayArtifactFingerprintVerificationBatchReport) -> None:
        self._report = report

    def load(
        self, report_id: str
    ) -> ReplayArtifactFingerprintVerificationBatchReport | None:
        if report_id == self._report.report_id:
            return self._report
        return None

    def list_for_replay_plan(
        self, replay_plan_id: str
    ) -> tuple[ReplayArtifactFingerprintVerificationBatchReport, ...]:
        if replay_plan_id == self._report.replay_plan_id:
            return (self._report,)
        return ()

    def list_all(self) -> tuple[ReplayArtifactFingerprintVerificationBatchReport, ...]:
        return (self._report,)


def _blocked_readiness_report(report_id: str, plan_id: str) -> ReplayReadinessReport:
    issue = ReplayReadinessIssue(
        issue_id="iss-1",
        kind=ReplayReadinessIssueKind.NO_FINGERPRINTS,
        severity=ReplayReadinessIssueSeverity.ERROR,
        message="no fingerprints",
    )
    return ReplayReadinessReport(
        report_id=report_id,
        replay_plan_id=plan_id,
        checked_at=_utc(5),
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


def _setup() -> tuple[
    InMemoryReplayReadinessReportStore,
    InMemoryReplayArtifactFingerprintStore,
    InMemoryReplayArtifactFingerprintVerificationBatchReportStore,
    InMemoryReplayRunManifestStore,
    LocalReplayRunPlanner,
]:
    readiness_store = InMemoryReplayReadinessReportStore()
    fp_store = InMemoryReplayArtifactFingerprintStore()
    batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
    manifest_store = InMemoryReplayRunManifestStore()
    planner = LocalReplayRunPlanner(
        readiness_report_store=readiness_store,
        fingerprint_store=fp_store,
        batch_report_store=batch_store,
        run_manifest_store=manifest_store,
        now=lambda: _utc(10),
    )
    return readiness_store, fp_store, batch_store, manifest_store, planner


class TestLocalReplayRunPlannerPlanned:
    def test_ready_readiness_creates_planned_manifest(self) -> None:
        readiness_store, fp_store, batch_store, _, planner = _setup()
        fp_store.save(_fp("fp-1", "plan-x"))
        fp_store.save(_fp("fp-2", "plan-x"))
        batch_store.save(_batch_report("batch-1", "plan-x", ("fp-1", "fp-2")))
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-x", "batch-1"))

        manifest = planner.plan_replay_run("m-1", "rpt-1")

        assert manifest.status is ReplayRunManifestStatus.PLANNED

    def test_planned_manifest_copies_readiness_fields(self) -> None:
        readiness_store, fp_store, batch_store, _, planner = _setup()
        fp_store.save(_fp("fp-1", "plan-x"))
        fp_store.save(_fp("fp-2", "plan-x"))
        batch_store.save(_batch_report("batch-1", "plan-x", ("fp-1", "fp-2")))
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-x", "batch-1"))

        manifest = planner.plan_replay_run("m-1", "rpt-1")

        assert manifest.readiness.readiness_report_id == "rpt-1"
        assert manifest.readiness.readiness_replay_plan_id == "plan-x"
        assert manifest.readiness.readiness_status is ReplayReadinessStatus.READY
        assert manifest.readiness.readiness_checked_at == _utc(5)
        assert manifest.readiness.readiness_total_fingerprints == 2
        assert manifest.readiness.readiness_latest_batch_report_id == "batch-1"
        assert manifest.readiness.verified_fingerprint_ids == ("fp-1", "fp-2")

    def test_planned_manifest_includes_fingerprint_ids_from_batch(self) -> None:
        readiness_store, fp_store, batch_store, _, planner = _setup()
        fp_store.save(_fp("fp-1", "plan-x"))
        fp_store.save(_fp("fp-2", "plan-x"))
        batch_store.save(_batch_report("batch-1", "plan-x", ("fp-1", "fp-2")))
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-x", "batch-1"))

        manifest = planner.plan_replay_run("m-1", "rpt-1")

        assert manifest.fingerprint_ids == ("fp-1", "fp-2")

    def test_planned_manifest_verification_batch_report_id_matches_readiness(self) -> None:
        readiness_store, fp_store, batch_store, _, planner = _setup()
        fp_store.save(_fp("fp-1", "plan-x"))
        batch_store.save(_batch_report("batch-abc", "plan-x", ("fp-1",)))
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-x", "batch-abc", 1))

        manifest = planner.plan_replay_run("m-1", "rpt-1")

        assert manifest.verification_batch_report_id == "batch-abc"

    def test_planned_manifest_replay_plan_id_matches(self) -> None:
        readiness_store, fp_store, batch_store, _, planner = _setup()
        fp_store.save(_fp("fp-1", "plan-xyz"))
        batch_store.save(_batch_report("batch-1", "plan-xyz", ("fp-1",)))
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-xyz", "batch-1", 1))

        manifest = planner.plan_replay_run("m-1", "rpt-1")

        assert manifest.replay_plan_id == "plan-xyz"

    def test_intent_kind_propagated(self) -> None:
        readiness_store, fp_store, batch_store, _, planner = _setup()
        fp_store.save(_fp("fp-1", "plan-x"))
        batch_store.save(_batch_report("batch-1", "plan-x", ("fp-1",)))
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-x", "batch-1", 1))

        manifest = planner.plan_replay_run(
            "m-1", "rpt-1", intent_kind=ReplayRunIntentKind.BACKTEST
        )

        assert manifest.intent_kind is ReplayRunIntentKind.BACKTEST

    def test_notes_propagated(self) -> None:
        readiness_store, fp_store, batch_store, _, planner = _setup()
        fp_store.save(_fp("fp-1", "plan-x"))
        batch_store.save(_batch_report("batch-1", "plan-x", ("fp-1",)))
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-x", "batch-1", 1))

        manifest = planner.plan_replay_run("m-1", "rpt-1", notes="first run")

        assert manifest.notes == "first run"

    def test_ready_readiness_zero_fingerprints_raises(self) -> None:
        readiness_store, _, batch_store, _, planner = _setup()
        batch_store.save(_batch_report("batch-1", "plan-empty", ("fp-1",)))
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-empty", "batch-1", 1))

        with pytest.raises(ValueError, match="no fingerprints"):
            planner.plan_replay_run("m-1", "rpt-1")

    def test_ready_report_1_fp_store_has_2_raises(self) -> None:
        readiness_store, fp_store, batch_store, manifest_store, planner = _setup()
        fp_store.save(_fp("fp-1", "plan-x"))
        fp_store.save(_fp("fp-2", "plan-x"))
        batch_store.save(_batch_report("batch-1", "plan-x", ("fp-1",)))
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-x", "batch-1", 1))

        with pytest.raises(ValueError, match="stale"):
            planner.plan_replay_run("m-1", "rpt-1")
        assert manifest_store.load("m-1") is None

    def test_ready_report_2_fps_store_has_1_raises(self) -> None:
        readiness_store, fp_store, batch_store, manifest_store, planner = _setup()
        fp_store.save(_fp("fp-1", "plan-x"))
        batch_store.save(_batch_report("batch-1", "plan-x", ("fp-1", "fp-2")))
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-x", "batch-1", 2))

        with pytest.raises(ValueError, match="stale"):
            planner.plan_replay_run("m-1", "rpt-1")
        assert manifest_store.load("m-1") is None

    def test_deterministic_fingerprint_order_preserved(self) -> None:
        readiness_store, fp_store, batch_store, _, planner = _setup()
        # fp-b has earlier generated_at than fp-a, so it appears first in store order.
        fp_store.save(_fp("fp-b", "plan-order", _utc(1)))
        fp_store.save(_fp("fp-a", "plan-order", _utc(2)))
        batch_store.save(_batch_report("batch-1", "plan-order", ("fp-b", "fp-a")))
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-order", "batch-1"))

        manifest = planner.plan_replay_run("m-1", "rpt-1")

        store_order = tuple(
            fp.fingerprint_id for fp in fp_store.list_for_replay_plan("plan-order")
        )
        assert manifest.fingerprint_ids == store_order
        assert manifest.fingerprint_ids == ("fp-b", "fp-a")

    def test_manifest_persisted(self) -> None:
        readiness_store, fp_store, batch_store, manifest_store, planner = _setup()
        fp_store.save(_fp("fp-1", "plan-x"))
        batch_store.save(_batch_report("batch-1", "plan-x", ("fp-1",)))
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-x", "batch-1", 1))

        planner.plan_replay_run("m-1", "rpt-1")

        assert manifest_store.load("m-1") is not None

    def test_same_count_different_fingerprint_ids_raises_without_persisting(self) -> None:
        readiness_store, fp_store, batch_store, manifest_store, planner = _setup()
        fp_store.save(_fp("fp-different", "plan-x"))
        batch_store.save(_batch_report("batch-1", "plan-x", ("fp-original",)))
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-x", "batch-1", 1))

        with pytest.raises(ValueError, match=r"stale|fingerprint identity"):
            planner.plan_replay_run("m-1", "rpt-1")

        assert manifest_store.load("m-1") is None

    def test_same_ids_wrong_order_raises_without_persisting(self) -> None:
        readiness_store, fp_store, batch_store, manifest_store, planner = _setup()
        fp_store.save(_fp("fp-2", "plan-x", _utc(1)))
        fp_store.save(_fp("fp-1", "plan-x", _utc(2)))
        batch_store.save(_batch_report("batch-1", "plan-x", ("fp-1", "fp-2")))
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-x", "batch-1", 2))

        with pytest.raises(ValueError, match=r"stale|fingerprint identity"):
            planner.plan_replay_run("m-1", "rpt-1")

        assert manifest_store.load("m-1") is None

    def test_referenced_batch_missing_raises_without_persisting(self) -> None:
        readiness_store, fp_store, _, manifest_store, planner = _setup()
        fp_store.save(_fp("fp-1", "plan-x"))
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-x", "batch-1", 1))

        with pytest.raises(ValueError, match="missing verification batch"):
            planner.plan_replay_run("m-1", "rpt-1")

        assert manifest_store.load("m-1") is None

    def test_referenced_batch_other_plan_raises_without_persisting(self) -> None:
        readiness_store, fp_store, batch_store, manifest_store, planner = _setup()
        fp_store.save(_fp("fp-1", "plan-x"))
        batch_store.save(_batch_report("batch-1", "plan-y", ("fp-1",)))
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-x", "batch-1", 1))

        with pytest.raises(ValueError, match="another replay plan"):
            planner.plan_replay_run("m-1", "rpt-1")

        assert manifest_store.load("m-1") is None

    def test_referenced_batch_invalidated_raises_without_persisting(self) -> None:
        readiness_store, fp_store, batch_store, manifest_store, planner = _setup()
        fp_store.save(_fp("fp-1", "plan-x"))
        batch_store.save(
            _batch_report(
                "batch-1",
                "plan-x",
                ("fp-1",),
                status=ReplayArtifactFingerprintVerificationBatchReportStatus.INVALIDATED,
            )
        )
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-x", "batch-1", 1))

        with pytest.raises(ValueError, match="not GENERATED"):
            planner.plan_replay_run("m-1", "rpt-1")

        assert manifest_store.load("m-1") is None

    def test_referenced_batch_not_all_valid_raises_without_persisting(self) -> None:
        readiness_store, fp_store, batch_store, manifest_store, planner = _setup()
        fp_store.save(_fp("fp-1", "plan-x"))
        batch_store.save(
            _batch_report("batch-1", "plan-x", ("fp-1",), all_valid=False)
        )
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-x", "batch-1", 1))

        with pytest.raises(ValueError, match="not all valid"):
            planner.plan_replay_run("m-1", "rpt-1")

        assert manifest_store.load("m-1") is None

    def test_batch_requested_ids_exactly_match_current_store_creates_planned(self) -> None:
        readiness_store, fp_store, batch_store, _, planner = _setup()
        fp_store.save(_fp("fp-1", "plan-x", _utc(1)))
        fp_store.save(_fp("fp-2", "plan-x", _utc(2)))
        batch_store.save(_batch_report("batch-1", "plan-x", ("fp-1", "fp-2")))
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-x", "batch-1", 2))

        manifest = planner.plan_replay_run("m-1", "rpt-1")

        assert manifest.status is ReplayRunManifestStatus.PLANNED
        assert manifest.readiness.readiness_replay_plan_id == "plan-x"
        assert manifest.readiness.verified_fingerprint_ids == ("fp-1", "fp-2")
        assert manifest.fingerprint_ids == ("fp-1", "fp-2")


class TestLocalReplayRunPlannerBlocked:
    def test_non_ready_readiness_creates_blocked_manifest(self) -> None:
        readiness_store, _, _, _, planner = _setup()
        readiness_store.save(_blocked_readiness_report("rpt-blocked", "plan-b"))

        manifest = planner.plan_replay_run("m-blocked", "rpt-blocked")

        assert manifest.status is ReplayRunManifestStatus.BLOCKED

    def test_blocked_manifest_persisted(self) -> None:
        readiness_store, _, _, manifest_store, planner = _setup()
        readiness_store.save(_blocked_readiness_report("rpt-blocked", "plan-b"))

        planner.plan_replay_run("m-blocked", "rpt-blocked")

        assert manifest_store.load("m-blocked") is not None

    def test_blocked_manifest_readiness_fields_copied(self) -> None:
        readiness_store, _, _, _, planner = _setup()
        readiness_store.save(_blocked_readiness_report("rpt-blocked", "plan-b"))

        manifest = planner.plan_replay_run("m-blocked", "rpt-blocked")

        assert manifest.readiness.readiness_report_id == "rpt-blocked"
        assert manifest.readiness.readiness_status is ReplayReadinessStatus.BLOCKED


class TestLocalReplayRunPlannerErrors:
    def test_missing_readiness_report_raises(self) -> None:
        _, _, _, _, planner = _setup()

        with pytest.raises(ValueError, match="readiness report not found"):
            planner.plan_replay_run("m-1", "nonexistent")


class TestLocalReplayRunPlannerStaleReadiness:
    def test_latest_batch_total_fingerprints_none_raises(self) -> None:
        _, _, batch_store, manifest_store, _ = _setup()
        batch_store.save(_batch_report("batch-1", "plan-x", ("fp-1",)))
        readiness = _ready_readiness_report("rpt-1", "plan-x", "batch-1", 1)
        tampered_summary = readiness.summary.model_copy(
            update={"latest_batch_total_fingerprints": None}
        )
        tampered_readiness = readiness.model_copy(update={"summary": tampered_summary})
        planner = LocalReplayRunPlanner(
            readiness_report_store=_StaticReadinessReportStore(tampered_readiness),
            fingerprint_store=InMemoryReplayArtifactFingerprintStore(),
            batch_report_store=batch_store,
            run_manifest_store=manifest_store,
            now=lambda: _utc(10),
        )

        with pytest.raises(ValueError, match="latest batch count"):
            planner.plan_replay_run("m-1", "rpt-1")
        assert manifest_store.load("m-1") is None

    def test_latest_batch_total_mismatch_raises(self) -> None:
        _, _, batch_store, manifest_store, _ = _setup()
        batch_store.save(_batch_report("batch-1", "plan-x", ("fp-1", "fp-2")))
        readiness = _ready_readiness_report("rpt-1", "plan-x", "batch-1", 2)
        tampered_summary = readiness.summary.model_copy(
            update={"latest_batch_total_fingerprints": 1}
        )
        tampered_readiness = readiness.model_copy(update={"summary": tampered_summary})
        planner = LocalReplayRunPlanner(
            readiness_report_store=_StaticReadinessReportStore(tampered_readiness),
            fingerprint_store=InMemoryReplayArtifactFingerprintStore(),
            batch_report_store=batch_store,
            run_manifest_store=manifest_store,
            now=lambda: _utc(10),
        )

        with pytest.raises(ValueError, match="latest batch count"):
            planner.plan_replay_run("m-1", "rpt-1")
        assert manifest_store.load("m-1") is None

    def test_batch_all_valid_positive_total_issues_rejected(self) -> None:
        readiness = _ready_readiness_report("rpt-1", "plan-x", "batch-1", 1)
        batch = _batch_report("batch-1", "plan-x", ("fp-1",))
        tampered_summary = batch.summary.model_copy(update={"total_issues": 1})
        tampered_batch = batch.model_copy(update={"summary": tampered_summary})
        fp_store = InMemoryReplayArtifactFingerprintStore()
        fp_store.save(_fp("fp-1", "plan-x"))
        manifest_store = InMemoryReplayRunManifestStore()
        planner = LocalReplayRunPlanner(
            readiness_report_store=_StaticReadinessReportStore(readiness),
            fingerprint_store=fp_store,
            batch_report_store=_StaticBatchReportStore(tampered_batch),
            run_manifest_store=manifest_store,
            now=lambda: _utc(10),
        )

        with pytest.raises(ValueError, match="zero issues"):
            planner.plan_replay_run("m-1", "rpt-1")

        assert manifest_store.load("m-1") is None

    def test_readiness_latest_batch_total_issues_mismatch_rejected(self) -> None:
        readiness = _ready_readiness_report("rpt-1", "plan-x", "batch-1", 1)
        tampered_summary = readiness.summary.model_copy(
            update={"latest_batch_total_issues": 1}
        )
        tampered_readiness = readiness.model_copy(update={"summary": tampered_summary})
        fp_store = InMemoryReplayArtifactFingerprintStore()
        fp_store.save(_fp("fp-1", "plan-x"))
        manifest_store = InMemoryReplayRunManifestStore()
        planner = LocalReplayRunPlanner(
            readiness_report_store=_StaticReadinessReportStore(tampered_readiness),
            fingerprint_store=fp_store,
            batch_report_store=_StaticBatchReportStore(
                _batch_report("batch-1", "plan-x", ("fp-1",))
            ),
            run_manifest_store=manifest_store,
            now=lambda: _utc(10),
        )

        with pytest.raises(ValueError, match="issue count"):
            planner.plan_replay_run("m-1", "rpt-1")

        assert manifest_store.load("m-1") is None

    def test_batch_generated_after_readiness_rejected(self) -> None:
        readiness_store, fp_store, batch_store, manifest_store, planner = _setup()
        fp_store.save(_fp("fp-1", "plan-x", _utc(1)))
        batch_store.save(
            _batch_report("batch-1", "plan-x", ("fp-1",), generated_at=_utc(6))
        )
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-x", "batch-1", 1))

        with pytest.raises(ValueError, match="temporal inconsistency"):
            planner.plan_replay_run("m-1", "rpt-1")

        assert manifest_store.load("m-1") is None

    def test_fingerprint_generated_after_batch_rejected(self) -> None:
        readiness_store, fp_store, batch_store, manifest_store, planner = _setup()
        fp_store.save(_fp("fp-1", "plan-x", _utc(5)))
        batch_store.save(
            _batch_report("batch-1", "plan-x", ("fp-1",), generated_at=_utc(4))
        )
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-x", "batch-1", 1))

        with pytest.raises(ValueError, match="fp-1"):
            planner.plan_replay_run("m-1", "rpt-1")

        assert manifest_store.load("m-1") is None

    def test_manifest_created_before_readiness_rejected(self) -> None:
        readiness_store = InMemoryReplayReadinessReportStore()
        fp_store = InMemoryReplayArtifactFingerprintStore()
        batch_store = InMemoryReplayArtifactFingerprintVerificationBatchReportStore()
        manifest_store = InMemoryReplayRunManifestStore()
        fp_store.save(_fp("fp-1", "plan-x", _utc(1)))
        batch_store.save(
            _batch_report("batch-1", "plan-x", ("fp-1",), generated_at=_utc(4))
        )
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-x", "batch-1", 1))
        planner = LocalReplayRunPlanner(
            readiness_report_store=readiness_store,
            fingerprint_store=fp_store,
            batch_report_store=batch_store,
            run_manifest_store=manifest_store,
            now=lambda: _utc(4),
        )

        with pytest.raises(ValueError, match="temporal inconsistency"):
            planner.plan_replay_run("m-1", "rpt-1")

        assert manifest_store.load("m-1") is None

    def test_valid_temporal_chain_creates_planned(self) -> None:
        readiness_store, fp_store, batch_store, _, planner = _setup()
        fp_store.save(_fp("fp-1", "plan-x", _utc(1)))
        batch_store.save(
            _batch_report("batch-1", "plan-x", ("fp-1",), generated_at=_utc(4))
        )
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-x", "batch-1", 1))

        manifest = planner.plan_replay_run("m-1", "rpt-1")

        assert manifest.status is ReplayRunManifestStatus.PLANNED
        assert _utc(1) <= _utc(4) <= manifest.readiness.readiness_checked_at
        assert manifest.readiness.readiness_checked_at <= manifest.created_at


class TestLocalReplayRunPlannerDelegation:
    def test_load_manifest_delegates_to_store(self) -> None:
        readiness_store, fp_store, batch_store, _, planner = _setup()
        fp_store.save(_fp("fp-1", "plan-x"))
        batch_store.save(_batch_report("batch-1", "plan-x", ("fp-1",)))
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-x", "batch-1", 1))
        planner.plan_replay_run("m-1", "rpt-1")

        result = planner.load_manifest("m-1")

        assert result is not None
        assert result.manifest_id == "m-1"

    def test_load_manifest_returns_none_for_missing(self) -> None:
        _, _, _, _, planner = _setup()
        assert planner.load_manifest("nonexistent") is None

    def test_manifests_for_replay_plan_delegates_to_store(self) -> None:
        readiness_store, fp_store, batch_store, _, planner = _setup()
        fp_store.save(_fp("fp-1", "plan-x"))
        fp_store.save(_fp("fp-2", "plan-x"))
        batch_store.save(_batch_report("batch-1", "plan-x", ("fp-1", "fp-2")))
        readiness_store.save(_ready_readiness_report("rpt-1", "plan-x", "batch-1"))
        planner.plan_replay_run("m-1", "rpt-1")

        results = planner.manifests_for_replay_plan("plan-x")

        assert len(results) == 1
        assert results[0].manifest_id == "m-1"


class TestLocalReplayRunPlannerNoExecutionArtifacts:
    def test_planner_has_no_replay_execution_method(self) -> None:
        assert not hasattr(LocalReplayRunPlanner, "execute_replay")
        assert not hasattr(LocalReplayRunPlanner, "run_backtest")
        assert not hasattr(LocalReplayRunPlanner, "evaluate")

    def test_manifest_has_no_performance_fields(self) -> None:
        assert not hasattr(ReplayRunManifest, "pnl")
        assert not hasattr(ReplayRunManifest, "metric_observations")
        assert not hasattr(ReplayRunManifest, "evaluation_result_set")

    def test_no_evaluation_result_set_import(self) -> None:
        src = Path(__file__).parent.parent.parent / "src/futures_bot/replay/integrity.py"
        tree = ast.parse(src.read_text())
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names.append(node.module or "")
                names.extend(a.name for a in node.names)
        assert not any("EvaluationResultSet" in n for n in names)
        assert not any("MetricObservation" in n for n in names)
