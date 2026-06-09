from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.replay import (
    ReplayArtifactFingerprint,
    ReplayArtifactFingerprintStatus,
    ReplayArtifactHashAlgorithm,
    ReplayArtifactKind,
)


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _make_payload(data: object) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _make_sha(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _make_canonical(artifact_kind: str, artifact: object) -> tuple[str, str]:
    data: dict[str, object] = {"artifact_kind": artifact_kind, "artifact": artifact}
    payload = _make_payload(data)
    return payload, _make_sha(payload)


_BASE_DATA: dict[str, object] = {
    "artifact_kind": "TIMELINE",
    "artifact": {"timeline_id": "tl-1"},
}
_PAYLOAD = _make_payload(_BASE_DATA)
_SHA = _make_sha(_PAYLOAD)


def _fingerprint(
    fingerprint_id: str = "fp-1",
    *,
    notes: str | None = None,
    replay_plan_id: str | None = None,
) -> ReplayArtifactFingerprint:
    return ReplayArtifactFingerprint(
        fingerprint_id=fingerprint_id,
        artifact_kind=ReplayArtifactKind.TIMELINE,
        artifact_id="tl-1",
        replay_plan_id=replay_plan_id,
        generated_at=_utc(0),
        status=ReplayArtifactFingerprintStatus.GENERATED,
        canonical_payload=_PAYLOAD,
        sha256=_SHA,
        notes=notes,
    )


class TestReplayArtifactKind:
    def test_timeline_value(self) -> None:
        assert ReplayArtifactKind.TIMELINE == "TIMELINE"

    def test_coverage_report_value(self) -> None:
        assert ReplayArtifactKind.COVERAGE_REPORT == "COVERAGE_REPORT"

    def test_coverage_diff_value(self) -> None:
        assert ReplayArtifactKind.COVERAGE_DIFF == "COVERAGE_DIFF"


class TestReplayArtifactFingerprintStatus:
    def test_generated_value(self) -> None:
        assert ReplayArtifactFingerprintStatus.GENERATED == "GENERATED"

    def test_invalidated_value(self) -> None:
        assert ReplayArtifactFingerprintStatus.INVALIDATED == "INVALIDATED"


class TestReplayArtifactHashAlgorithm:
    def test_sha256_value(self) -> None:
        assert ReplayArtifactHashAlgorithm.SHA256 == "SHA256"


class TestReplayArtifactFingerprintValid:
    def test_valid_fingerprint_accepted(self) -> None:
        fp = _fingerprint()
        assert fp.fingerprint_id == "fp-1"
        assert fp.artifact_kind is ReplayArtifactKind.TIMELINE
        assert fp.artifact_id == "tl-1"
        assert fp.replay_plan_id is None
        assert fp.status is ReplayArtifactFingerprintStatus.GENERATED
        assert fp.hash_algorithm is ReplayArtifactHashAlgorithm.SHA256
        assert fp.canonical_payload == _PAYLOAD
        assert fp.sha256 == _SHA

    def test_replay_plan_id_optional_none(self) -> None:
        fp = _fingerprint(replay_plan_id=None)
        assert fp.replay_plan_id is None

    def test_replay_plan_id_string_accepted(self) -> None:
        payload, sha = _make_canonical(
            "TIMELINE",
            {"timeline_id": "tl-1", "replay_plan_id": "plan-1"},
        )
        fp = ReplayArtifactFingerprint(
            fingerprint_id="fp-1",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-1",
            replay_plan_id="plan-1",
            generated_at=_utc(0),
            status=ReplayArtifactFingerprintStatus.GENERATED,
            canonical_payload=payload,
            sha256=sha,
        )
        assert fp.replay_plan_id == "plan-1"

    def test_notes_none_accepted(self) -> None:
        fp = _fingerprint(notes=None)
        assert fp.notes is None

    def test_notes_string_accepted(self) -> None:
        fp = _fingerprint(notes="a note")
        assert fp.notes == "a note"

    def test_generated_at_aware_accepted(self) -> None:
        fp = ReplayArtifactFingerprint(
            fingerprint_id="fp-1",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-1",
            generated_at=datetime(2026, 1, 1, 0, tzinfo=UTC),
            status=ReplayArtifactFingerprintStatus.GENERATED,
            canonical_payload=_PAYLOAD,
            sha256=_SHA,
        )
        assert fp.generated_at.tzinfo is not None

    def test_hash_algorithm_defaults_to_sha256(self) -> None:
        fp = _fingerprint()
        assert fp.hash_algorithm is ReplayArtifactHashAlgorithm.SHA256

    def test_frozen(self) -> None:
        fp = _fingerprint()
        with pytest.raises((AttributeError, ValidationError)):
            fp.fingerprint_id = "new-id"  # type: ignore[misc]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprint(  # type: ignore[call-arg]
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=_PAYLOAD,
                sha256=_SHA,
                unexpected_field="bad",
            )

    def test_round_trip_model_dump_validate(self) -> None:
        fp = _fingerprint()
        dumped = fp.model_dump()
        restored = ReplayArtifactFingerprint.model_validate(dumped)
        assert restored == fp

    def test_canonical_payload_accepts_nested_objects(self) -> None:
        payload, sha = _make_canonical(
            "COVERAGE_REPORT",
            {"report_id": "rep-1", "nested": {"key": "value"}},
        )
        fp = ReplayArtifactFingerprint(
            fingerprint_id="fp-2",
            artifact_kind=ReplayArtifactKind.COVERAGE_REPORT,
            artifact_id="rep-1",
            generated_at=_utc(0),
            status=ReplayArtifactFingerprintStatus.GENERATED,
            canonical_payload=payload,
            sha256=sha,
        )
        assert fp.sha256 == sha


class TestReplayArtifactFingerprintRejections:
    def test_empty_fingerprint_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprint(
                fingerprint_id="",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=_PAYLOAD,
                sha256=_SHA,
            )

    def test_whitespace_fingerprint_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprint(
                fingerprint_id="  ",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=_PAYLOAD,
                sha256=_SHA,
            )

    def test_empty_artifact_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="",
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=_PAYLOAD,
                sha256=_SHA,
            )

    def test_whitespace_replay_plan_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                replay_plan_id="  ",
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=_PAYLOAD,
                sha256=_SHA,
            )

    def test_naive_generated_at_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                generated_at=datetime(2026, 1, 1, 0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=_PAYLOAD,
                sha256=_SHA,
            )

    def test_empty_canonical_payload_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload="",
                sha256="a" * 64,
            )

    def test_whitespace_canonical_payload_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload="   ",
                sha256="a" * 64,
            )

    def test_invalid_json_canonical_payload_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload="not json at all",
                sha256="a" * 64,
            )

    def test_pretty_json_canonical_payload_rejected(self) -> None:
        pretty = '{"key": "value"}'
        with pytest.raises(ValidationError, match="compact sorted JSON"):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=pretty,
                sha256="a" * 64,
            )

    def test_unsorted_keys_canonical_payload_rejected(self) -> None:
        unsorted = '{"b":"2","a":"1"}'
        with pytest.raises(ValidationError, match="compact sorted JSON"):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=unsorted,
                sha256="a" * 64,
            )

    def test_float_in_canonical_payload_rejected(self) -> None:
        data = {"artifact": 1.5}
        payload = json.dumps(data, separators=(",", ":"))
        sha = _make_sha(payload)
        with pytest.raises(ValidationError, match="float"):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=payload,
                sha256=sha,
            )

    def test_sha256_mismatch_rejected(self) -> None:
        wrong_sha = "a" * 64
        with pytest.raises(ValidationError, match="does not match"):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=_PAYLOAD,
                sha256=wrong_sha,
            )

    def test_sha256_wrong_length_rejected(self) -> None:
        with pytest.raises(ValidationError, match="sha256"):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=_PAYLOAD,
                sha256="abc123",
            )

    def test_sha256_uppercase_rejected(self) -> None:
        upper = _SHA.upper()
        with pytest.raises(ValidationError, match="sha256"):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=_PAYLOAD,
                sha256=upper,
            )

    def test_sha256_non_hex_rejected(self) -> None:
        non_hex = "z" * 64
        with pytest.raises(ValidationError, match="sha256"):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=_PAYLOAD,
                sha256=non_hex,
            )

    def test_whitespace_notes_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _fingerprint(notes="  ")


class TestReplayArtifactFingerprintConsistency:
    def test_non_object_payload_rejected(self) -> None:
        raw = '"just-a-string"'
        sha = _make_sha(raw)
        with pytest.raises(ValidationError, match="JSON object"):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=raw,
                sha256=sha,
            )

    def test_missing_artifact_kind_in_payload_rejected(self) -> None:
        payload, sha = _make_canonical_raw({"artifact": {"timeline_id": "tl-1"}})
        with pytest.raises(ValidationError, match="artifact_kind"):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=payload,
                sha256=sha,
            )

    def test_missing_artifact_in_payload_rejected(self) -> None:
        payload, sha = _make_canonical_raw({"artifact_kind": "TIMELINE"})
        with pytest.raises(ValidationError, match="artifact"):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=payload,
                sha256=sha,
            )

    def test_artifact_kind_mismatch_rejected(self) -> None:
        payload, sha = _make_canonical("COVERAGE_REPORT", {"report_id": "rep-1"})
        with pytest.raises(ValidationError, match="artifact_kind"):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,  # mismatch
                artifact_id="rep-1",
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=payload,
                sha256=sha,
            )

    def test_artifact_not_object_rejected(self) -> None:
        payload, sha = _make_canonical("TIMELINE", "not-an-object")
        with pytest.raises(ValidationError, match="JSON object"):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=payload,
                sha256=sha,
            )

    def test_timeline_missing_timeline_id_rejected(self) -> None:
        payload, sha = _make_canonical("TIMELINE", {"other_field": "value"})
        with pytest.raises(ValidationError, match="timeline_id"):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=payload,
                sha256=sha,
            )

    def test_timeline_artifact_id_mismatch_rejected(self) -> None:
        payload, sha = _make_canonical("TIMELINE", {"timeline_id": "tl-real"})
        with pytest.raises(ValidationError, match="artifact_id"):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-fake",  # mismatch
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=payload,
                sha256=sha,
            )

    def test_coverage_report_missing_report_id_rejected(self) -> None:
        payload, sha = _make_canonical("COVERAGE_REPORT", {"other": "value"})
        with pytest.raises(ValidationError, match="report_id"):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.COVERAGE_REPORT,
                artifact_id="rep-1",
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=payload,
                sha256=sha,
            )

    def test_coverage_report_artifact_id_mismatch_rejected(self) -> None:
        payload, sha = _make_canonical("COVERAGE_REPORT", {"report_id": "rep-real"})
        with pytest.raises(ValidationError, match="artifact_id"):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.COVERAGE_REPORT,
                artifact_id="rep-fake",  # mismatch
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=payload,
                sha256=sha,
            )

    def test_coverage_diff_missing_diff_id_rejected(self) -> None:
        payload, sha = _make_canonical("COVERAGE_DIFF", {"other": "value"})
        with pytest.raises(ValidationError, match="diff_id"):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.COVERAGE_DIFF,
                artifact_id="diff-1",
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=payload,
                sha256=sha,
            )

    def test_coverage_diff_artifact_id_mismatch_rejected(self) -> None:
        payload, sha = _make_canonical("COVERAGE_DIFF", {"diff_id": "diff-real"})
        with pytest.raises(ValidationError, match="artifact_id"):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.COVERAGE_DIFF,
                artifact_id="diff-fake",  # mismatch
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=payload,
                sha256=sha,
            )

    def test_timeline_replay_plan_id_mismatch_rejected(self) -> None:
        payload, sha = _make_canonical(
            "TIMELINE",
            {"timeline_id": "tl-1", "replay_plan_id": "plan-A"},
        )
        with pytest.raises(ValidationError, match="replay_plan_id"):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.TIMELINE,
                artifact_id="tl-1",
                replay_plan_id="plan-B",  # mismatch
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=payload,
                sha256=sha,
            )

    def test_coverage_report_replay_plan_id_mismatch_rejected(self) -> None:
        payload, sha = _make_canonical(
            "COVERAGE_REPORT",
            {"report_id": "rep-1", "replay_plan_id": "plan-A"},
        )
        with pytest.raises(ValidationError, match="replay_plan_id"):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.COVERAGE_REPORT,
                artifact_id="rep-1",
                replay_plan_id="plan-B",  # mismatch
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=payload,
                sha256=sha,
            )

    def test_coverage_diff_replay_plan_id_mismatch_rejected(self) -> None:
        payload, sha = _make_canonical(
            "COVERAGE_DIFF",
            {
                "diff_id": "diff-1",
                "baseline_replay_plan_id": "plan-A",
                "candidate_replay_plan_id": "plan-A",
            },
        )
        with pytest.raises(ValidationError, match="replay_plan_id"):
            ReplayArtifactFingerprint(
                fingerprint_id="fp-1",
                artifact_kind=ReplayArtifactKind.COVERAGE_DIFF,
                artifact_id="diff-1",
                replay_plan_id="plan-B",  # mismatch with plan-A
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintStatus.GENERATED,
                canonical_payload=payload,
                sha256=sha,
            )

    def test_coverage_diff_cross_plan_replay_plan_id_none_accepted(self) -> None:
        payload, sha = _make_canonical(
            "COVERAGE_DIFF",
            {
                "diff_id": "diff-1",
                "baseline_replay_plan_id": "plan-A",
                "candidate_replay_plan_id": "plan-B",
            },
        )
        fp = ReplayArtifactFingerprint(
            fingerprint_id="fp-1",
            artifact_kind=ReplayArtifactKind.COVERAGE_DIFF,
            artifact_id="diff-1",
            replay_plan_id=None,
            generated_at=_utc(0),
            status=ReplayArtifactFingerprintStatus.GENERATED,
            canonical_payload=payload,
            sha256=sha,
        )
        assert fp.replay_plan_id is None


def _make_canonical_raw(data: object) -> tuple[str, str]:
    payload = _make_payload(data)
    return payload, _make_sha(payload)
