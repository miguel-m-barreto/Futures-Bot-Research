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


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _canonical(data: object) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _issue(
    issue_id: str = "iss-1",
    kind: ReplayArtifactFingerprintVerificationIssueKind = (
        ReplayArtifactFingerprintVerificationIssueKind.HASH_MISMATCH
    ),
    severity: ReplayArtifactFingerprintVerificationIssueSeverity = (
        ReplayArtifactFingerprintVerificationIssueSeverity.ERROR
    ),
    message: str = "a test issue",
) -> ReplayArtifactFingerprintVerificationIssue:
    return ReplayArtifactFingerprintVerificationIssue(
        issue_id=issue_id,
        kind=kind,
        severity=severity,
        message=message,
    )


def _make_payloads(
    timeline_id: str = "tl-1",
    replay_plan_id: str | None = None,
) -> tuple[str, str]:
    artifact: dict[str, object] = {"timeline_id": timeline_id}
    if replay_plan_id is not None:
        artifact["replay_plan_id"] = replay_plan_id
    payload = _canonical({"artifact_kind": "TIMELINE", "artifact": artifact})
    return payload, _sha(payload)


def _valid_verification(
    verification_id: str = "ver-1",
    *,
    notes: str | None = None,
) -> ReplayArtifactFingerprintVerification:
    payload, sha = _make_payloads("tl-1", "plan-1")
    return ReplayArtifactFingerprintVerification(
        verification_id=verification_id,
        fingerprint_id="fp-1",
        artifact_kind=ReplayArtifactKind.TIMELINE,
        artifact_id="tl-1",
        replay_plan_id="plan-1",
        verified_at=_utc(0),
        status=ReplayArtifactFingerprintVerificationStatus.VALID,
        stored_sha256=sha,
        recomputed_sha256=sha,
        stored_canonical_payload=payload,
        recomputed_canonical_payload=payload,
        notes=notes,
    )


class TestReplayArtifactFingerprintVerificationStatus:
    def test_valid_value(self) -> None:
        assert ReplayArtifactFingerprintVerificationStatus.VALID == "VALID"

    def test_mismatch_value(self) -> None:
        assert ReplayArtifactFingerprintVerificationStatus.MISMATCH == "MISMATCH"

    def test_missing_fingerprint_value(self) -> None:
        assert (
            ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT
            == "MISSING_FINGERPRINT"
        )

    def test_missing_artifact_value(self) -> None:
        assert (
            ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT == "MISSING_ARTIFACT"
        )

    def test_invalidated_value(self) -> None:
        assert ReplayArtifactFingerprintVerificationStatus.INVALIDATED == "INVALIDATED"


class TestReplayArtifactFingerprintVerificationIssueKind:
    def test_fingerprint_not_found(self) -> None:
        assert (
            ReplayArtifactFingerprintVerificationIssueKind.FINGERPRINT_NOT_FOUND
            == "FINGERPRINT_NOT_FOUND"
        )

    def test_artifact_not_found(self) -> None:
        assert (
            ReplayArtifactFingerprintVerificationIssueKind.ARTIFACT_NOT_FOUND
            == "ARTIFACT_NOT_FOUND"
        )

    def test_hash_mismatch(self) -> None:
        assert ReplayArtifactFingerprintVerificationIssueKind.HASH_MISMATCH == "HASH_MISMATCH"

    def test_canonical_payload_mismatch(self) -> None:
        assert (
            ReplayArtifactFingerprintVerificationIssueKind.CANONICAL_PAYLOAD_MISMATCH
            == "CANONICAL_PAYLOAD_MISMATCH"
        )


class TestReplayArtifactFingerprintVerificationIssueSeverity:
    def test_info_value(self) -> None:
        assert ReplayArtifactFingerprintVerificationIssueSeverity.INFO == "INFO"

    def test_warning_value(self) -> None:
        assert ReplayArtifactFingerprintVerificationIssueSeverity.WARNING == "WARNING"

    def test_error_value(self) -> None:
        assert ReplayArtifactFingerprintVerificationIssueSeverity.ERROR == "ERROR"


class TestReplayArtifactFingerprintVerificationIssue:
    def test_valid_issue_accepted(self) -> None:
        iss = _issue()
        assert iss.issue_id == "iss-1"
        assert iss.kind is ReplayArtifactFingerprintVerificationIssueKind.HASH_MISMATCH
        assert iss.severity is ReplayArtifactFingerprintVerificationIssueSeverity.ERROR
        assert iss.expected_value is None
        assert iss.observed_value is None

    def test_expected_and_observed_accepted(self) -> None:
        iss = ReplayArtifactFingerprintVerificationIssue(
            issue_id="iss-1",
            kind=ReplayArtifactFingerprintVerificationIssueKind.HASH_MISMATCH,
            severity=ReplayArtifactFingerprintVerificationIssueSeverity.ERROR,
            message="mismatch",
            expected_value="aaa",
            observed_value="bbb",
        )
        assert iss.expected_value == "aaa"
        assert iss.observed_value == "bbb"

    def test_empty_issue_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprintVerificationIssue(
                issue_id="",
                kind=ReplayArtifactFingerprintVerificationIssueKind.OTHER,
                severity=ReplayArtifactFingerprintVerificationIssueSeverity.INFO,
                message="msg",
            )

    def test_empty_message_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprintVerificationIssue(
                issue_id="iss-1",
                kind=ReplayArtifactFingerprintVerificationIssueKind.OTHER,
                severity=ReplayArtifactFingerprintVerificationIssueSeverity.INFO,
                message="",
            )

    def test_whitespace_expected_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprintVerificationIssue(
                issue_id="iss-1",
                kind=ReplayArtifactFingerprintVerificationIssueKind.OTHER,
                severity=ReplayArtifactFingerprintVerificationIssueSeverity.INFO,
                message="msg",
                expected_value="  ",
            )

    def test_whitespace_observed_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprintVerificationIssue(
                issue_id="iss-1",
                kind=ReplayArtifactFingerprintVerificationIssueKind.OTHER,
                severity=ReplayArtifactFingerprintVerificationIssueSeverity.INFO,
                message="msg",
                observed_value="  ",
            )

    def test_frozen(self) -> None:
        iss = _issue()
        with pytest.raises((AttributeError, ValidationError)):
            iss.issue_id = "new"  # type: ignore[misc]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprintVerificationIssue(  # type: ignore[call-arg]
                issue_id="iss-1",
                kind=ReplayArtifactFingerprintVerificationIssueKind.OTHER,
                severity=ReplayArtifactFingerprintVerificationIssueSeverity.INFO,
                message="msg",
                unexpected="bad",
            )


class TestReplayArtifactFingerprintVerificationValidStatuses:
    def test_valid_status_accepted(self) -> None:
        v = _valid_verification()
        assert v.status is ReplayArtifactFingerprintVerificationStatus.VALID
        assert v.artifact_kind is ReplayArtifactKind.TIMELINE
        assert v.artifact_id == "tl-1"
        assert v.issues == ()

    def test_mismatch_status_accepted(self) -> None:
        _, sha_a = _make_payloads("tl-1")
        _, sha_b = _make_payloads("tl-2")
        v = ReplayArtifactFingerprintVerification(
            verification_id="ver-1",
            fingerprint_id="fp-1",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-1",
            verified_at=_utc(0),
            status=ReplayArtifactFingerprintVerificationStatus.MISMATCH,
            stored_sha256=sha_a,
            recomputed_sha256=sha_b,
            issues=(_issue(issue_id="iss-hash"),),
        )
        assert v.status is ReplayArtifactFingerprintVerificationStatus.MISMATCH
        assert len(v.issues) == 1

    def test_missing_fingerprint_status_accepted(self) -> None:
        v = ReplayArtifactFingerprintVerification(
            verification_id="ver-1",
            fingerprint_id="fp-missing",
            verified_at=_utc(0),
            status=ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT,
            issues=(
                _issue(
                    issue_id="iss-fp",
                    kind=ReplayArtifactFingerprintVerificationIssueKind.FINGERPRINT_NOT_FOUND,
                ),
            ),
        )
        assert v.status is ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT
        assert v.stored_sha256 is None
        assert v.recomputed_sha256 is None

    def test_missing_artifact_status_accepted(self) -> None:
        _, sha = _make_payloads()
        payload, _ = _make_payloads()
        v = ReplayArtifactFingerprintVerification(
            verification_id="ver-1",
            fingerprint_id="fp-1",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-1",
            verified_at=_utc(0),
            status=ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT,
            stored_sha256=sha,
            stored_canonical_payload=payload,
            issues=(
                _issue(
                    issue_id="iss-art",
                    kind=ReplayArtifactFingerprintVerificationIssueKind.ARTIFACT_NOT_FOUND,
                ),
            ),
        )
        assert v.status is ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT
        assert v.recomputed_sha256 is None

    def test_invalidated_status_accepted(self) -> None:
        v = ReplayArtifactFingerprintVerification(
            verification_id="ver-1",
            fingerprint_id="fp-1",
            verified_at=_utc(0),
            status=ReplayArtifactFingerprintVerificationStatus.INVALIDATED,
        )
        assert v.status is ReplayArtifactFingerprintVerificationStatus.INVALIDATED
        assert v.issues == ()

    def test_notes_accepted(self) -> None:
        v = _valid_verification(notes="audit run")
        assert v.notes == "audit run"

    def test_round_trip_model_dump_validate(self) -> None:
        v = _valid_verification()
        restored = ReplayArtifactFingerprintVerification.model_validate(v.model_dump())
        assert restored == v

    def test_frozen(self) -> None:
        v = _valid_verification()
        with pytest.raises((AttributeError, ValidationError)):
            v.verification_id = "new"  # type: ignore[misc]

    def test_extra_field_rejected(self) -> None:
        payload, sha = _make_payloads()
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprintVerification(  # type: ignore[call-arg]
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.VALID,
                stored_sha256=sha,
                recomputed_sha256=sha,
                stored_canonical_payload=payload,
                recomputed_canonical_payload=payload,
                unexpected_field="bad",
            )


class TestReplayArtifactFingerprintVerificationRejections:
    def test_valid_with_sha_mismatch_rejected(self) -> None:
        payload_a, sha_a = _make_payloads("tl-1")
        _, sha_b = _make_payloads("tl-2")
        with pytest.raises(ValidationError, match="recomputed_sha256"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.VALID,
                stored_sha256=sha_a,
                recomputed_sha256=sha_b,  # mismatch
                stored_canonical_payload=payload_a,
                recomputed_canonical_payload=payload_a,
            )

    def test_valid_with_payload_mismatch_rejected(self) -> None:
        payload_a, sha_a = _make_payloads("tl-1")
        payload_b, _ = _make_payloads("tl-2")
        with pytest.raises(ValidationError, match="recomputed_canonical_payload"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.VALID,
                stored_sha256=sha_a,
                recomputed_sha256=sha_a,
                stored_canonical_payload=payload_a,
                recomputed_canonical_payload=payload_b,  # mismatch
            )

    def test_valid_with_issues_rejected(self) -> None:
        payload, sha = _make_payloads()
        with pytest.raises(ValidationError, match="no issues"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.VALID,
                stored_sha256=sha,
                recomputed_sha256=sha,
                stored_canonical_payload=payload,
                recomputed_canonical_payload=payload,
                issues=(_issue(),),
            )

    def test_valid_missing_artifact_kind_rejected(self) -> None:
        payload, sha = _make_payloads()
        with pytest.raises(ValidationError, match="artifact_kind"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.VALID,
                stored_sha256=sha,
                recomputed_sha256=sha,
                stored_canonical_payload=payload,
                recomputed_canonical_payload=payload,
            )

    def test_valid_missing_stored_sha256_rejected(self) -> None:
        payload, sha = _make_payloads()
        with pytest.raises(ValidationError, match="stored_sha256"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.VALID,
                recomputed_sha256=sha,
                stored_canonical_payload=payload,
                recomputed_canonical_payload=payload,
            )

    def test_mismatch_without_issues_rejected(self) -> None:
        _, sha_a = _make_payloads("tl-1")
        _, sha_b = _make_payloads("tl-2")
        with pytest.raises(ValidationError, match="at least one issue"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.MISMATCH,
                stored_sha256=sha_a,
                recomputed_sha256=sha_b,
            )

    def test_mismatch_missing_stored_sha256_rejected(self) -> None:
        _, sha_b = _make_payloads("tl-2")
        with pytest.raises(ValidationError, match="stored_sha256"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.MISMATCH,
                recomputed_sha256=sha_b,
                issues=(_issue(),),
            )

    def test_mismatch_missing_artifact_kind_rejected(self) -> None:
        sha_a = _sha(_canonical({"a": 1}))
        sha_b = _sha(_canonical({"b": 2}))
        with pytest.raises(ValidationError, match="artifact_kind"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.MISMATCH,
                stored_sha256=sha_a,
                recomputed_sha256=sha_b,
                issues=(_issue(),),
            )

    def test_missing_fingerprint_with_stored_sha_rejected(self) -> None:
        _, sha = _make_payloads()
        with pytest.raises(ValidationError, match="stored_sha256"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-missing",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT,
                stored_sha256=sha,
                issues=(
                    _issue(
                        issue_id="iss-fp",
                        kind=ReplayArtifactFingerprintVerificationIssueKind.FINGERPRINT_NOT_FOUND,
                    ),
                ),
            )

    def test_missing_fingerprint_without_fp_not_found_issue_rejected(self) -> None:
        with pytest.raises(ValidationError, match="FINGERPRINT_NOT_FOUND"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-missing",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT,
                issues=(_issue(issue_id="iss-other"),),
            )

    def test_missing_artifact_without_stored_sha256_rejected(self) -> None:
        with pytest.raises(ValidationError, match="stored_sha256"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT,
                issues=(
                    _issue(
                        issue_id="iss-art",
                        kind=ReplayArtifactFingerprintVerificationIssueKind.ARTIFACT_NOT_FOUND,
                    ),
                ),
            )

    def test_missing_artifact_with_recomputed_sha256_rejected(self) -> None:
        payload, sha = _make_payloads()
        with pytest.raises(ValidationError, match="recomputed_sha256"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT,
                stored_sha256=sha,
                recomputed_sha256=sha,  # must be None
                stored_canonical_payload=payload,
                issues=(
                    _issue(
                        issue_id="iss-art",
                        kind=ReplayArtifactFingerprintVerificationIssueKind.ARTIFACT_NOT_FOUND,
                    ),
                ),
            )

    def test_missing_artifact_without_artifact_not_found_issue_rejected(self) -> None:
        payload, sha = _make_payloads()
        with pytest.raises(ValidationError, match="ARTIFACT_NOT_FOUND"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT,
                stored_sha256=sha,
                stored_canonical_payload=payload,
                issues=(_issue(issue_id="iss-other"),),
            )

    def test_duplicate_issue_ids_rejected(self) -> None:
        _, sha_a = _make_payloads("tl-1")
        _, sha_b = _make_payloads("tl-2")
        with pytest.raises(ValidationError, match="duplicate issue_id"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.MISMATCH,
                stored_sha256=sha_a,
                recomputed_sha256=sha_b,
                issues=(
                    _issue(issue_id="same-id"),
                    _issue(
                        issue_id="same-id",
                        kind=ReplayArtifactFingerprintVerificationIssueKind.CANONICAL_PAYLOAD_MISMATCH,
                    ),
                ),
            )

    def test_bad_sha256_rejected(self) -> None:
        payload, _ = _make_payloads()
        with pytest.raises(ValidationError, match="sha256"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.VALID,
                stored_sha256="not-a-valid-sha",
                recomputed_sha256="not-a-valid-sha",
                stored_canonical_payload=payload,
                recomputed_canonical_payload=payload,
            )

    def test_non_canonical_stored_payload_rejected(self) -> None:
        _, sha = _make_payloads()
        with pytest.raises(ValidationError, match="canonical"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.VALID,
                stored_sha256=sha,
                recomputed_sha256=sha,
                stored_canonical_payload='{"key": "value"}',  # pretty, not canonical
                recomputed_canonical_payload='{"key": "value"}',
            )

    def test_whitespace_notes_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _valid_verification(notes="   ")

    def test_naive_verified_at_rejected(self) -> None:
        payload, sha = _make_payloads()
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=datetime(2026, 1, 1, 0),  # no tzinfo
                status=ReplayArtifactFingerprintVerificationStatus.VALID,
                stored_sha256=sha,
                recomputed_sha256=sha,
                stored_canonical_payload=payload,
                recomputed_canonical_payload=payload,
            )

    def test_empty_verification_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _valid_verification(verification_id="")


def _make_valid_payload(
    artifact_kind_str: str,
    artifact: dict[str, object],
) -> tuple[str, str]:
    payload = _canonical({"artifact_kind": artifact_kind_str, "artifact": artifact})
    return payload, _sha(payload)


def _art_not_found_issue() -> ReplayArtifactFingerprintVerificationIssue:
    return ReplayArtifactFingerprintVerificationIssue(
        issue_id="iss-art",
        kind=ReplayArtifactFingerprintVerificationIssueKind.ARTIFACT_NOT_FOUND,
        severity=ReplayArtifactFingerprintVerificationIssueSeverity.ERROR,
        message="artifact not found",
    )


class TestReplayArtifactFingerprintVerificationPayloadIdentity:
    def test_valid_payload_without_artifact_kind_rejected(self) -> None:
        bad_payload = _canonical({"artifact": {"timeline_id": "tl-1"}})
        bad_sha = _sha(bad_payload)
        with pytest.raises(ValidationError, match="artifact_kind"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.VALID,
                stored_sha256=bad_sha,
                recomputed_sha256=bad_sha,
                stored_canonical_payload=bad_payload,
                recomputed_canonical_payload=bad_payload,
            )

    def test_valid_payload_artifact_kind_mismatch_rejected(self) -> None:
        bad_payload = _canonical(
            {"artifact_kind": "COVERAGE_REPORT", "artifact": {"timeline_id": "tl-1"}}
        )
        bad_sha = _sha(bad_payload)
        with pytest.raises(ValidationError, match="artifact_kind"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.VALID,
                stored_sha256=bad_sha,
                recomputed_sha256=bad_sha,
                stored_canonical_payload=bad_payload,
                recomputed_canonical_payload=bad_payload,
            )

    def test_valid_payload_without_artifact_key_rejected(self) -> None:
        bad_payload = _canonical({"artifact_kind": "TIMELINE"})
        bad_sha = _sha(bad_payload)
        with pytest.raises(ValidationError, match="artifact"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.VALID,
                stored_sha256=bad_sha,
                recomputed_sha256=bad_sha,
                stored_canonical_payload=bad_payload,
                recomputed_canonical_payload=bad_payload,
            )

    def test_valid_payload_artifact_not_object_rejected(self) -> None:
        bad_payload = _canonical({"artifact_kind": "TIMELINE", "artifact": "not-a-dict"})
        bad_sha = _sha(bad_payload)
        with pytest.raises(ValidationError, match="artifact"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.VALID,
                stored_sha256=bad_sha,
                recomputed_sha256=bad_sha,
                stored_canonical_payload=bad_payload,
                recomputed_canonical_payload=bad_payload,
            )

    def test_valid_timeline_payload_missing_timeline_id_rejected(self) -> None:
        bad_payload = _canonical({"artifact_kind": "TIMELINE", "artifact": {"other": "val"}})
        bad_sha = _sha(bad_payload)
        with pytest.raises(ValidationError, match="timeline_id"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.VALID,
                stored_sha256=bad_sha,
                recomputed_sha256=bad_sha,
                stored_canonical_payload=bad_payload,
                recomputed_canonical_payload=bad_payload,
            )

    def test_valid_timeline_payload_artifact_id_mismatch_rejected(self) -> None:
        bad_payload, bad_sha = _make_payloads("tl-WRONG")
        with pytest.raises(ValidationError, match="timeline_id"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.VALID,
                stored_sha256=bad_sha,
                recomputed_sha256=bad_sha,
                stored_canonical_payload=bad_payload,
                recomputed_canonical_payload=bad_payload,
            )

    def test_valid_coverage_report_payload_report_id_mismatch_rejected(self) -> None:
        bad_payload, bad_sha = _make_valid_payload(
            "COVERAGE_REPORT", {"report_id": "rep-WRONG"}
        )
        with pytest.raises(ValidationError, match="report_id"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.COVERAGE_REPORT,
                artifact_id="rep-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.VALID,
                stored_sha256=bad_sha,
                recomputed_sha256=bad_sha,
                stored_canonical_payload=bad_payload,
                recomputed_canonical_payload=bad_payload,
            )

    def test_valid_coverage_diff_payload_diff_id_mismatch_rejected(self) -> None:
        bad_payload, bad_sha = _make_valid_payload(
            "COVERAGE_DIFF", {"diff_id": "diff-WRONG"}
        )
        with pytest.raises(ValidationError, match="diff_id"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.COVERAGE_DIFF,
                artifact_id="diff-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.VALID,
                stored_sha256=bad_sha,
                recomputed_sha256=bad_sha,
                stored_canonical_payload=bad_payload,
                recomputed_canonical_payload=bad_payload,
            )

    def test_valid_timeline_replay_plan_id_mismatch_rejected(self) -> None:
        bad_payload, bad_sha = _make_payloads("tl-1", "wrong-plan")
        with pytest.raises(ValidationError, match="replay_plan_id"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                replay_plan_id="plan-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.VALID,
                stored_sha256=bad_sha,
                recomputed_sha256=bad_sha,
                stored_canonical_payload=bad_payload,
                recomputed_canonical_payload=bad_payload,
            )

    def test_valid_coverage_report_replay_plan_id_mismatch_rejected(self) -> None:
        bad_payload, bad_sha = _make_valid_payload(
            "COVERAGE_REPORT", {"report_id": "rep-1", "replay_plan_id": "wrong-plan"}
        )
        with pytest.raises(ValidationError, match="replay_plan_id"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.COVERAGE_REPORT,
                artifact_id="rep-1",
                replay_plan_id="plan-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.VALID,
                stored_sha256=bad_sha,
                recomputed_sha256=bad_sha,
                stored_canonical_payload=bad_payload,
                recomputed_canonical_payload=bad_payload,
            )

    def test_valid_same_plan_diff_replay_plan_id_mismatch_rejected(self) -> None:
        bad_payload, bad_sha = _make_valid_payload(
            "COVERAGE_DIFF",
            {
                "diff_id": "diff-1",
                "baseline_replay_plan_id": "wrong-plan",
                "candidate_replay_plan_id": "wrong-plan",
            },
        )
        with pytest.raises(ValidationError, match="replay_plan_id"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.COVERAGE_DIFF,
                artifact_id="diff-1",
                replay_plan_id="plan-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.VALID,
                stored_sha256=bad_sha,
                recomputed_sha256=bad_sha,
                stored_canonical_payload=bad_payload,
                recomputed_canonical_payload=bad_payload,
            )

    def test_valid_cross_plan_diff_with_replay_plan_id_none_accepted(self) -> None:
        payload, sha = _make_valid_payload(
            "COVERAGE_DIFF",
            {
                "baseline_replay_plan_id": "plan-A",
                "candidate_replay_plan_id": "plan-B",
                "diff_id": "diff-1",
            },
        )
        v = ReplayArtifactFingerprintVerification(
            verification_id="ver-1",
            fingerprint_id="fp-1",
            artifact_kind=ReplayArtifactKind.COVERAGE_DIFF,
            artifact_id="diff-1",
            replay_plan_id=None,
            verified_at=_utc(0),
            status=ReplayArtifactFingerprintVerificationStatus.VALID,
            stored_sha256=sha,
            recomputed_sha256=sha,
            stored_canonical_payload=payload,
            recomputed_canonical_payload=payload,
        )
        assert v.status is ReplayArtifactFingerprintVerificationStatus.VALID

    def test_mismatch_stored_payload_artifact_id_mismatch_rejected(self) -> None:
        bad_stored, bad_sha = _make_payloads("tl-WRONG")
        good_payload, good_sha = _make_payloads("tl-1")
        with pytest.raises(ValidationError, match="timeline_id"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.MISMATCH,
                stored_sha256=bad_sha,
                recomputed_sha256=good_sha,
                stored_canonical_payload=bad_stored,
                recomputed_canonical_payload=good_payload,
                issues=(_issue(),),
            )

    def test_mismatch_identity_consistent_payloads_accepted(self) -> None:
        payload_a = _canonical(
            {"artifact_kind": "TIMELINE", "artifact": {"timeline_id": "tl-1", "v": "a"}}
        )
        sha_a = _sha(payload_a)
        payload_b = _canonical(
            {"artifact_kind": "TIMELINE", "artifact": {"timeline_id": "tl-1", "v": "b"}}
        )
        sha_b = _sha(payload_b)
        v = ReplayArtifactFingerprintVerification(
            verification_id="ver-1",
            fingerprint_id="fp-1",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-1",
            verified_at=_utc(0),
            status=ReplayArtifactFingerprintVerificationStatus.MISMATCH,
            stored_sha256=sha_a,
            recomputed_sha256=sha_b,
            stored_canonical_payload=payload_a,
            recomputed_canonical_payload=payload_b,
            issues=(_issue(),),
        )
        assert v.status is ReplayArtifactFingerprintVerificationStatus.MISMATCH

    def test_missing_artifact_identity_consistent_stored_payload_accepted(self) -> None:
        payload, sha = _make_payloads("tl-1")
        v = ReplayArtifactFingerprintVerification(
            verification_id="ver-1",
            fingerprint_id="fp-1",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-1",
            verified_at=_utc(0),
            status=ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT,
            stored_sha256=sha,
            stored_canonical_payload=payload,
            issues=(_art_not_found_issue(),),
        )
        assert v.status is ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT

    def test_missing_artifact_stored_payload_artifact_id_mismatch_rejected(self) -> None:
        bad_payload, bad_sha = _make_payloads("tl-DIFFERENT")
        with pytest.raises(ValidationError, match="timeline_id"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT,
                stored_sha256=bad_sha,
                stored_canonical_payload=bad_payload,
                issues=(_art_not_found_issue(),),
            )


_WRONG_SHA = "0" * 64


class TestReplayArtifactFingerprintVerificationShaPairConsistency:
    def test_valid_sha_pair_mismatch_rejected(self) -> None:
        payload, _ = _make_payloads("tl-1", "plan-1")
        with pytest.raises(ValidationError, match="sha256"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                replay_plan_id="plan-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.VALID,
                stored_sha256=_WRONG_SHA,
                recomputed_sha256=_WRONG_SHA,
                stored_canonical_payload=payload,
                recomputed_canonical_payload=payload,
            )

    def test_valid_sha_matching_payload_accepted(self) -> None:
        v = _valid_verification()
        assert v.stored_sha256 == v.recomputed_sha256
        assert v.stored_canonical_payload == v.recomputed_canonical_payload

    def test_mismatch_stored_sha_not_matching_stored_payload_rejected(self) -> None:
        payload_a = _canonical(
            {"artifact_kind": "TIMELINE", "artifact": {"timeline_id": "tl-1", "v": "a"}}
        )
        sha_b = _sha(
            _canonical(
                {"artifact_kind": "TIMELINE", "artifact": {"timeline_id": "tl-1", "v": "b"}}
            )
        )
        payload_b = _canonical(
            {"artifact_kind": "TIMELINE", "artifact": {"timeline_id": "tl-1", "v": "b"}}
        )
        with pytest.raises(ValidationError, match="stored_sha256"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.MISMATCH,
                stored_sha256=_WRONG_SHA,
                recomputed_sha256=sha_b,
                stored_canonical_payload=payload_a,
                recomputed_canonical_payload=payload_b,
                issues=(_issue(),),
            )

    def test_mismatch_recomputed_sha_not_matching_recomputed_payload_rejected(self) -> None:
        payload_a = _canonical(
            {"artifact_kind": "TIMELINE", "artifact": {"timeline_id": "tl-1", "v": "a"}}
        )
        sha_a = _sha(payload_a)
        payload_b = _canonical(
            {"artifact_kind": "TIMELINE", "artifact": {"timeline_id": "tl-1", "v": "b"}}
        )
        with pytest.raises(ValidationError, match="recomputed_sha256"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.MISMATCH,
                stored_sha256=sha_a,
                recomputed_sha256=_WRONG_SHA,
                stored_canonical_payload=payload_a,
                recomputed_canonical_payload=payload_b,
                issues=(_issue(),),
            )

    def test_mismatch_internally_correct_pairs_but_different_accepted(self) -> None:
        payload_a = _canonical(
            {"artifact_kind": "TIMELINE", "artifact": {"timeline_id": "tl-1", "v": "a"}}
        )
        sha_a = _sha(payload_a)
        payload_b = _canonical(
            {"artifact_kind": "TIMELINE", "artifact": {"timeline_id": "tl-1", "v": "b"}}
        )
        sha_b = _sha(payload_b)
        v = ReplayArtifactFingerprintVerification(
            verification_id="ver-1",
            fingerprint_id="fp-1",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-1",
            verified_at=_utc(0),
            status=ReplayArtifactFingerprintVerificationStatus.MISMATCH,
            stored_sha256=sha_a,
            recomputed_sha256=sha_b,
            stored_canonical_payload=payload_a,
            recomputed_canonical_payload=payload_b,
            issues=(_issue(),),
        )
        assert v.status is ReplayArtifactFingerprintVerificationStatus.MISMATCH

    def test_missing_artifact_stored_sha_not_matching_stored_payload_rejected(self) -> None:
        payload, _ = _make_payloads("tl-1")
        with pytest.raises(ValidationError, match="stored_sha256"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT,
                stored_sha256=_WRONG_SHA,
                stored_canonical_payload=payload,
                issues=(_art_not_found_issue(),),
            )

    def test_missing_artifact_correct_sha_payload_pair_accepted(self) -> None:
        payload, sha = _make_payloads("tl-1")
        v = ReplayArtifactFingerprintVerification(
            verification_id="ver-1",
            fingerprint_id="fp-1",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-1",
            verified_at=_utc(0),
            status=ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT,
            stored_sha256=sha,
            stored_canonical_payload=payload,
            issues=(_art_not_found_issue(),),
        )
        assert v.status is ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT

    def test_missing_fingerprint_constructible_without_sha_payload_pairs(self) -> None:
        v = ReplayArtifactFingerprintVerification(
            verification_id="ver-1",
            fingerprint_id="fp-missing",
            verified_at=_utc(0),
            status=ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT,
            issues=(
                _issue(
                    issue_id="iss-fp",
                    kind=ReplayArtifactFingerprintVerificationIssueKind.FINGERPRINT_NOT_FOUND,
                ),
            ),
        )
        assert v.stored_sha256 is None
        assert v.stored_canonical_payload is None

    def test_invalidated_with_mismatched_sha_payload_rejected(self) -> None:
        payload, _ = _make_payloads("tl-1")
        with pytest.raises(ValidationError, match="stored_sha256"):
            ReplayArtifactFingerprintVerification(
                verification_id="ver-1",
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                verified_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationStatus.INVALIDATED,
                stored_sha256=_WRONG_SHA,
                stored_canonical_payload=payload,
            )
