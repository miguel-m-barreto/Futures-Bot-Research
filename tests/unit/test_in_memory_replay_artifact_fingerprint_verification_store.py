from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.replay import (
    ReplayArtifactFingerprintVerification,
    ReplayArtifactFingerprintVerificationIssue,
    ReplayArtifactFingerprintVerificationIssueKind,
    ReplayArtifactFingerprintVerificationIssueSeverity,
    ReplayArtifactFingerprintVerificationStatus,
    ReplayArtifactKind,
)
from futures_bot.infrastructure.replay.in_memory import (
    InMemoryReplayArtifactFingerprintVerificationStore,
)
from futures_bot.ports.replay import ReplayArtifactFingerprintVerificationStorePort


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _canonical(data: object) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _make_payloads(
    timeline_id: str = "tl-1",
    replay_plan_id: str | None = None,
) -> tuple[str, str]:
    artifact: dict[str, object] = {"timeline_id": timeline_id}
    if replay_plan_id is not None:
        artifact["replay_plan_id"] = replay_plan_id
    payload = _canonical({"artifact_kind": "TIMELINE", "artifact": artifact})
    return payload, _sha(payload)


def _fp_not_found_issue() -> ReplayArtifactFingerprintVerificationIssue:
    return ReplayArtifactFingerprintVerificationIssue(
        issue_id="iss-fp-not-found",
        kind=ReplayArtifactFingerprintVerificationIssueKind.FINGERPRINT_NOT_FOUND,
        severity=ReplayArtifactFingerprintVerificationIssueSeverity.ERROR,
        message="fingerprint not found",
    )


def _art_not_found_issue() -> ReplayArtifactFingerprintVerificationIssue:
    return ReplayArtifactFingerprintVerificationIssue(
        issue_id="iss-art-not-found",
        kind=ReplayArtifactFingerprintVerificationIssueKind.ARTIFACT_NOT_FOUND,
        severity=ReplayArtifactFingerprintVerificationIssueSeverity.ERROR,
        message="artifact not found",
    )


def _hash_mismatch_issue() -> ReplayArtifactFingerprintVerificationIssue:
    return ReplayArtifactFingerprintVerificationIssue(
        issue_id="iss-hash-mismatch",
        kind=ReplayArtifactFingerprintVerificationIssueKind.HASH_MISMATCH,
        severity=ReplayArtifactFingerprintVerificationIssueSeverity.ERROR,
        message="hash mismatch",
    )


def _valid_ver(
    verification_id: str = "ver-1",
    *,
    artifact_id: str = "tl-1",
    replay_plan_id: str | None = "plan-1",
    verified_at: datetime | None = None,
) -> ReplayArtifactFingerprintVerification:
    payload, sha = _make_payloads(artifact_id, replay_plan_id)
    return ReplayArtifactFingerprintVerification(
        verification_id=verification_id,
        fingerprint_id="fp-1",
        artifact_kind=ReplayArtifactKind.TIMELINE,
        artifact_id=artifact_id,
        replay_plan_id=replay_plan_id,
        verified_at=verified_at or _utc(0),
        status=ReplayArtifactFingerprintVerificationStatus.VALID,
        stored_sha256=sha,
        recomputed_sha256=sha,
        stored_canonical_payload=payload,
        recomputed_canonical_payload=payload,
    )


def _missing_fp_ver(
    verification_id: str = "ver-missing",
    *,
    verified_at: datetime | None = None,
) -> ReplayArtifactFingerprintVerification:
    return ReplayArtifactFingerprintVerification(
        verification_id=verification_id,
        fingerprint_id="fp-missing",
        verified_at=verified_at or _utc(0),
        status=ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT,
        issues=(_fp_not_found_issue(),),
    )


class TestInMemoryReplayArtifactFingerprintVerificationStoreConformance:
    def test_conforms_to_port(self) -> None:
        _: ReplayArtifactFingerprintVerificationStorePort = (
            InMemoryReplayArtifactFingerprintVerificationStore()
        )


class TestInMemoryReplayArtifactFingerprintVerificationStore:
    def test_save_and_load_round_trip(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationStore()
        ver = _valid_ver()
        store.save(ver)
        assert store.load("ver-1") == ver

    def test_load_returns_none_for_missing(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationStore()
        assert store.load("nonexistent") is None

    def test_idempotent_save_accepted(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationStore()
        ver = _valid_ver()
        store.save(ver)
        store.save(ver)
        assert store.load("ver-1") == ver

    def test_conflict_rejected(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationStore()
        ver1 = _valid_ver("ver-1", artifact_id="tl-A")
        ver2 = _valid_ver("ver-1", artifact_id="tl-B")
        store.save(ver1)
        with pytest.raises(ValueError, match="conflict"):
            store.save(ver2)

    def test_list_all_empty(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationStore()
        assert store.list_all() == ()

    def test_list_all_deterministic_order(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationStore()
        vb = _valid_ver("ver-b", artifact_id="tl-b", verified_at=_utc(2))
        va = _valid_ver("ver-a", artifact_id="tl-a", verified_at=_utc(1))
        store.save(vb)
        store.save(va)
        results = store.list_all()
        assert [v.verification_id for v in results] == ["ver-a", "ver-b"]

    def test_list_all_same_time_sorted_by_id(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationStore()
        vz = _valid_ver("ver-z", artifact_id="tl-z", verified_at=_utc(1))
        va = _valid_ver("ver-a", artifact_id="tl-a", verified_at=_utc(1))
        store.save(vz)
        store.save(va)
        results = store.list_all()
        assert [v.verification_id for v in results] == ["ver-a", "ver-z"]

    def test_list_for_fingerprint_filters(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationStore()
        ver_a = _valid_ver("ver-a")
        # ver-b with a different fingerprint_id
        payload, sha = _make_payloads("tl-2")
        ver_b = ReplayArtifactFingerprintVerification(
            verification_id="ver-b",
            fingerprint_id="fp-other",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-2",
            verified_at=_utc(0),
            status=ReplayArtifactFingerprintVerificationStatus.VALID,
            stored_sha256=sha,
            recomputed_sha256=sha,
            stored_canonical_payload=payload,
            recomputed_canonical_payload=payload,
        )
        store.save(ver_a)
        store.save(ver_b)
        results = store.list_for_fingerprint("fp-1")
        assert len(results) == 1
        assert results[0].verification_id == "ver-a"

    def test_list_for_fingerprint_deterministic_order(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationStore()
        payload, sha = _make_payloads()
        vb = ReplayArtifactFingerprintVerification(
            verification_id="ver-b",
            fingerprint_id="fp-1",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-1",
            verified_at=_utc(2),
            status=ReplayArtifactFingerprintVerificationStatus.VALID,
            stored_sha256=sha,
            recomputed_sha256=sha,
            stored_canonical_payload=payload,
            recomputed_canonical_payload=payload,
        )
        va = ReplayArtifactFingerprintVerification(
            verification_id="ver-a",
            fingerprint_id="fp-1",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-1",
            verified_at=_utc(1),
            status=ReplayArtifactFingerprintVerificationStatus.VALID,
            stored_sha256=sha,
            recomputed_sha256=sha,
            stored_canonical_payload=payload,
            recomputed_canonical_payload=payload,
        )
        store.save(vb)
        store.save(va)
        results = store.list_for_fingerprint("fp-1")
        assert [v.verification_id for v in results] == ["ver-a", "ver-b"]

    def test_list_for_artifact_filters_by_kind_and_id(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationStore()
        ver_tl = _valid_ver("ver-tl", artifact_id="tl-1")
        # Build a COVERAGE_REPORT verification
        payload_rep2 = _canonical(
            {"artifact_kind": "COVERAGE_REPORT", "artifact": {"report_id": "rep-1"}}
        )
        sha_rep2 = _sha(payload_rep2)
        ver_rep = ReplayArtifactFingerprintVerification(
            verification_id="ver-rep",
            fingerprint_id="fp-rep",
            artifact_kind=ReplayArtifactKind.COVERAGE_REPORT,
            artifact_id="rep-1",
            verified_at=_utc(0),
            status=ReplayArtifactFingerprintVerificationStatus.VALID,
            stored_sha256=sha_rep2,
            recomputed_sha256=sha_rep2,
            stored_canonical_payload=payload_rep2,
            recomputed_canonical_payload=payload_rep2,
        )
        store.save(ver_tl)
        store.save(ver_rep)
        results = store.list_for_artifact(ReplayArtifactKind.TIMELINE, "tl-1")
        assert len(results) == 1
        assert results[0].verification_id == "ver-tl"

    def test_list_for_replay_plan_filters(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationStore()
        va = _valid_ver("ver-a", replay_plan_id="plan-A")
        vb = _valid_ver("ver-b", artifact_id="tl-2", replay_plan_id="plan-B")
        store.save(va)
        store.save(vb)
        results = store.list_for_replay_plan("plan-A")
        assert len(results) == 1
        assert results[0].verification_id == "ver-a"

    def test_list_for_replay_plan_excludes_none(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationStore()
        ver = _missing_fp_ver()
        store.save(ver)
        assert store.list_for_replay_plan("plan-1") == ()

    def test_model_copy_invalid_status_rejected(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationStore()
        ver = _valid_ver()
        store.save(ver)
        # VALID with issues should be rejected
        tampered = ver.model_copy(
            update={"verification_id": "ver-tamper", "issues": (_hash_mismatch_issue(),)}
        )
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_duplicate_issue_ids_rejected(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationStore()
        _, sha_a = _make_payloads("tl-1")
        _, sha_b = _make_payloads("tl-2")
        ver = ReplayArtifactFingerprintVerification(
            verification_id="ver-mismatch",
            fingerprint_id="fp-1",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-1",
            verified_at=_utc(0),
            status=ReplayArtifactFingerprintVerificationStatus.MISMATCH,
            stored_sha256=sha_a,
            recomputed_sha256=sha_b,
            issues=(_hash_mismatch_issue(),),
        )
        store.save(ver)
        # model_copy introduces duplicate issue_ids
        dup_issue = ReplayArtifactFingerprintVerificationIssue(
            issue_id="iss-hash-mismatch",  # same id
            kind=ReplayArtifactFingerprintVerificationIssueKind.CANONICAL_PAYLOAD_MISMATCH,
            severity=ReplayArtifactFingerprintVerificationIssueSeverity.ERROR,
            message="another issue with same id",
        )
        tampered = ver.model_copy(
            update={"verification_id": "ver-dup", "issues": (_hash_mismatch_issue(), dup_issue)}
        )
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_arbitrary_payload_rejected_by_revalidation(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationStore()
        ver = _valid_ver()
        store.save(ver)
        # Replace payloads with arbitrary JSON that doesn't encode artifact identity
        bad_payload = _canonical({"x": 1})
        bad_sha = _sha(bad_payload)
        tampered = ver.model_copy(
            update={
                "verification_id": "ver-tamper",
                "stored_sha256": bad_sha,
                "recomputed_sha256": bad_sha,
                "stored_canonical_payload": bad_payload,
                "recomputed_canonical_payload": bad_payload,
            }
        )
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_mismatched_artifact_id_rejected_by_revalidation(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationStore()
        ver = _valid_ver()
        store.save(ver)
        # Change artifact_id while payload still encodes old artifact_id
        tampered = ver.model_copy(
            update={"verification_id": "ver-tamper", "artifact_id": "tl-different"}
        )
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_stored_sha256_tampered_rejected(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationStore()
        ver = _valid_ver()
        store.save(ver)
        tampered = ver.model_copy(
            update={"verification_id": "ver-tamper", "stored_sha256": "0" * 64}
        )
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_recomputed_sha256_tampered_rejected(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationStore()
        ver = _valid_ver()
        store.save(ver)
        tampered = ver.model_copy(
            update={"verification_id": "ver-tamper", "recomputed_sha256": "0" * 64}
        )
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_mismatch_sha_payload_inconsistent_rejected(self) -> None:
        store = InMemoryReplayArtifactFingerprintVerificationStore()
        payload_a, sha_a = _make_payloads("tl-1")
        payload_b = _canonical(
            {"artifact_kind": "TIMELINE", "artifact": {"timeline_id": "tl-1", "v": "b"}}
        )
        sha_b = _sha(payload_b)
        ver = ReplayArtifactFingerprintVerification(
            verification_id="ver-mm",
            fingerprint_id="fp-1",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-1",
            verified_at=_utc(0),
            status=ReplayArtifactFingerprintVerificationStatus.MISMATCH,
            stored_sha256=sha_a,
            recomputed_sha256=sha_b,
            stored_canonical_payload=payload_a,
            recomputed_canonical_payload=payload_b,
            issues=(_hash_mismatch_issue(),),
        )
        store.save(ver)
        # Tamper: stored sha no longer matches stored payload
        tampered = ver.model_copy(
            update={"verification_id": "ver-tamper", "stored_sha256": "0" * 64}
        )
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)
