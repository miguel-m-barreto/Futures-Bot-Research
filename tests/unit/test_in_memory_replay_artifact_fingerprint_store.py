from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.replay import (
    ReplayArtifactFingerprint,
    ReplayArtifactFingerprintStatus,
    ReplayArtifactKind,
)
from futures_bot.infrastructure.replay.in_memory import (
    InMemoryReplayArtifactFingerprintStore,
)
from futures_bot.ports.replay import ReplayArtifactFingerprintStorePort

_KIND_TO_ID_FIELD: dict[ReplayArtifactKind, str] = {
    ReplayArtifactKind.TIMELINE: "timeline_id",
    ReplayArtifactKind.COVERAGE_REPORT: "report_id",
    ReplayArtifactKind.COVERAGE_DIFF: "diff_id",
}


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _make_payload(data: object) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _make_sha(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fp(  # noqa: PLR0913
    fingerprint_id: str = "fp-1",
    *,
    artifact_kind: ReplayArtifactKind = ReplayArtifactKind.TIMELINE,
    artifact_id: str = "tl-1",
    replay_plan_id: str | None = "plan-1",
    generated_at: datetime | None = None,
    notes: str | None = None,
) -> ReplayArtifactFingerprint:
    id_field = _KIND_TO_ID_FIELD[artifact_kind]
    artifact: dict[str, object] = {id_field: artifact_id}
    if replay_plan_id is not None:
        if artifact_kind == ReplayArtifactKind.COVERAGE_DIFF:
            artifact["baseline_replay_plan_id"] = replay_plan_id
            artifact["candidate_replay_plan_id"] = replay_plan_id
        else:
            artifact["replay_plan_id"] = replay_plan_id
    data: dict[str, object] = {"artifact_kind": artifact_kind.value, "artifact": artifact}
    payload = _make_payload(data)
    sha = _make_sha(payload)
    return ReplayArtifactFingerprint(
        fingerprint_id=fingerprint_id,
        artifact_kind=artifact_kind,
        artifact_id=artifact_id,
        replay_plan_id=replay_plan_id,
        generated_at=generated_at or _utc(0),
        status=ReplayArtifactFingerprintStatus.GENERATED,
        canonical_payload=payload,
        sha256=sha,
        notes=notes,
    )


class TestInMemoryReplayArtifactFingerprintStoreConformance:
    def test_conforms_to_port(self) -> None:
        _: ReplayArtifactFingerprintStorePort = InMemoryReplayArtifactFingerprintStore()


class TestInMemoryReplayArtifactFingerprintStore:
    def test_save_and_load_round_trip(self) -> None:
        store = InMemoryReplayArtifactFingerprintStore()
        fp = _fp()
        store.save(fp)
        loaded = store.load("fp-1")
        assert loaded == fp

    def test_load_returns_none_for_missing(self) -> None:
        store = InMemoryReplayArtifactFingerprintStore()
        assert store.load("nonexistent") is None

    def test_idempotent_save_accepted(self) -> None:
        store = InMemoryReplayArtifactFingerprintStore()
        fp = _fp()
        store.save(fp)
        store.save(fp)
        assert store.load("fp-1") == fp

    def test_conflict_rejected(self) -> None:
        store = InMemoryReplayArtifactFingerprintStore()
        fp1 = _fp("fp-1", artifact_id="tl-A")
        fp2 = _fp("fp-1", artifact_id="tl-B")
        store.save(fp1)
        with pytest.raises(ValueError, match="conflict"):
            store.save(fp2)

    def test_list_all_empty(self) -> None:
        store = InMemoryReplayArtifactFingerprintStore()
        assert store.list_all() == ()

    def test_list_all_deterministic_order(self) -> None:
        store = InMemoryReplayArtifactFingerprintStore()
        fb = _fp("fp-b", generated_at=_utc(2))
        fa = _fp("fp-a", generated_at=_utc(1))
        store.save(fb)
        store.save(fa)
        results = store.list_all()
        assert [f.fingerprint_id for f in results] == ["fp-a", "fp-b"]

    def test_list_all_same_time_sorted_by_id(self) -> None:
        store = InMemoryReplayArtifactFingerprintStore()
        fz = _fp("fp-z", generated_at=_utc(1))
        fa = _fp("fp-a", generated_at=_utc(1))
        store.save(fz)
        store.save(fa)
        results = store.list_all()
        assert [f.fingerprint_id for f in results] == ["fp-a", "fp-z"]

    def test_list_for_artifact_filters_by_kind_and_id(self) -> None:
        store = InMemoryReplayArtifactFingerprintStore()
        fp_tl = _fp("fp-tl", artifact_kind=ReplayArtifactKind.TIMELINE, artifact_id="tl-1")
        fp_rep = _fp(
            "fp-rep",
            artifact_kind=ReplayArtifactKind.COVERAGE_REPORT,
            artifact_id="rep-1",
        )
        fp_other = _fp(
            "fp-other",
            artifact_kind=ReplayArtifactKind.TIMELINE,
            artifact_id="tl-2",
        )
        store.save(fp_tl)
        store.save(fp_rep)
        store.save(fp_other)
        results = store.list_for_artifact(ReplayArtifactKind.TIMELINE, "tl-1")
        assert len(results) == 1
        assert results[0].fingerprint_id == "fp-tl"

    def test_list_for_artifact_deterministic_order(self) -> None:
        store = InMemoryReplayArtifactFingerprintStore()
        fp2 = _fp("fp-b", artifact_kind=ReplayArtifactKind.TIMELINE, generated_at=_utc(2))
        fp1 = _fp("fp-a", artifact_kind=ReplayArtifactKind.TIMELINE, generated_at=_utc(1))
        store.save(fp2)
        store.save(fp1)
        results = store.list_for_artifact(ReplayArtifactKind.TIMELINE, "tl-1")
        assert [f.fingerprint_id for f in results] == ["fp-a", "fp-b"]

    def test_list_for_artifact_unknown_returns_empty(self) -> None:
        store = InMemoryReplayArtifactFingerprintStore()
        assert store.list_for_artifact(ReplayArtifactKind.TIMELINE, "no-such") == ()

    def test_list_for_replay_plan_filters_by_plan_id(self) -> None:
        store = InMemoryReplayArtifactFingerprintStore()
        fp_a = _fp("fp-a", replay_plan_id="plan-A")
        fp_b = _fp("fp-b", replay_plan_id="plan-B")
        store.save(fp_a)
        store.save(fp_b)
        results = store.list_for_replay_plan("plan-A")
        assert len(results) == 1
        assert results[0].fingerprint_id == "fp-a"

    def test_list_for_replay_plan_excludes_none_plan_id(self) -> None:
        store = InMemoryReplayArtifactFingerprintStore()
        fp_none = _fp("fp-none", replay_plan_id=None)
        store.save(fp_none)
        results = store.list_for_replay_plan("plan-1")
        assert results == ()

    def test_list_for_unknown_replay_plan_returns_empty(self) -> None:
        store = InMemoryReplayArtifactFingerprintStore()
        assert store.list_for_replay_plan("no-such-plan") == ()

    def test_list_for_replay_plan_deterministic_order(self) -> None:
        store = InMemoryReplayArtifactFingerprintStore()
        fb = _fp("fp-b", generated_at=_utc(2), replay_plan_id="plan-1")
        fa = _fp("fp-a", generated_at=_utc(1), replay_plan_id="plan-1")
        store.save(fb)
        store.save(fa)
        results = store.list_for_replay_plan("plan-1")
        assert [f.fingerprint_id for f in results] == ["fp-a", "fp-b"]

    def test_model_copy_tampered_sha256_rejected(self) -> None:
        store = InMemoryReplayArtifactFingerprintStore()
        fp = _fp("fp-tamper")
        store.save(fp)
        tampered = fp.model_copy(update={"fingerprint_id": "fp-t2", "sha256": "a" * 64})
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_tampered_payload_rejected(self) -> None:
        store = InMemoryReplayArtifactFingerprintStore()
        fp = _fp("fp-base")
        store.save(fp)
        alt_data: dict[str, object] = {
            "artifact_kind": "TIMELINE",
            "artifact": {"timeline_id": "other"},
        }
        alt_payload = _make_payload(alt_data)
        tampered = fp.model_copy(
            update={"fingerprint_id": "fp-t3", "canonical_payload": alt_payload}
        )
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_mismatched_artifact_id_rejected(self) -> None:
        store = InMemoryReplayArtifactFingerprintStore()
        fp = _fp("fp-1")  # artifact_id="tl-1", payload has timeline_id="tl-1"
        store.save(fp)
        # model_copy changes artifact_id to "tl-2" but canonical_payload still says "tl-1"
        tampered = fp.model_copy(update={"fingerprint_id": "fp-tamper", "artifact_id": "tl-2"})
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)
