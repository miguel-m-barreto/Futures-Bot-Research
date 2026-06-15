from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from futures_bot.domain.replay import (
    ReplayReadinessStatus,
    ReplayRunIntentKind,
    ReplayRunManifest,
    ReplayRunManifestStatus,
    ReplayRunReadinessBinding,
)

_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _binding(
    *,
    readiness_replay_plan_id: str = "plan-1",
    readiness_status: ReplayReadinessStatus = ReplayReadinessStatus.READY,
    readiness_total_fingerprints: int = 2,
    readiness_latest_batch_report_id: str | None = "batch-1",
    verified_fingerprint_ids: tuple[str, ...] | None = None,
) -> ReplayRunReadinessBinding:
    if verified_fingerprint_ids is None:
        verified_fingerprint_ids = tuple(
            f"fp-{idx}" for idx in range(1, readiness_total_fingerprints + 1)
        )
    return ReplayRunReadinessBinding(
        readiness_report_id="rpt-1",
        readiness_replay_plan_id=readiness_replay_plan_id,
        readiness_status=readiness_status,
        readiness_checked_at=_TS,
        readiness_total_fingerprints=readiness_total_fingerprints,
        readiness_latest_batch_report_id=readiness_latest_batch_report_id,
        verified_fingerprint_ids=verified_fingerprint_ids,
    )


def _planned(  # noqa: PLR0913
    manifest_id: str = "manifest-1",
    *,
    replay_plan_id: str = "plan-1",
    created_at: datetime = _TS,
    fingerprint_ids: tuple[str, ...] = ("fp-1", "fp-2"),
    verification_batch_report_id: str | None = "batch-1",
    readiness: ReplayRunReadinessBinding | None = None,
    notes: str | None = None,
) -> ReplayRunManifest:
    return ReplayRunManifest(
        manifest_id=manifest_id,
        replay_plan_id=replay_plan_id,
        intent_kind=ReplayRunIntentKind.REPLAY_ONLY,
        created_at=created_at,
        status=ReplayRunManifestStatus.PLANNED,
        readiness=readiness or _binding(),
        fingerprint_ids=fingerprint_ids,
        verification_batch_report_id=verification_batch_report_id,
        notes=notes,
    )


def _blocked(
    manifest_id: str = "manifest-1",
    *,
    readiness: ReplayRunReadinessBinding | None = None,
) -> ReplayRunManifest:
    return ReplayRunManifest(
        manifest_id=manifest_id,
        replay_plan_id="plan-1",
        intent_kind=ReplayRunIntentKind.REPLAY_ONLY,
        created_at=_TS,
        status=ReplayRunManifestStatus.BLOCKED,
        readiness=readiness or _binding(readiness_status=ReplayReadinessStatus.BLOCKED),
    )


class TestReplayRunReadinessBinding:
    def test_valid_binding(self) -> None:
        b = _binding()
        assert b.readiness_report_id == "rpt-1"
        assert b.readiness_replay_plan_id == "plan-1"
        assert b.readiness_status is ReplayReadinessStatus.READY
        assert b.readiness_total_fingerprints == 2
        assert b.verified_fingerprint_ids == ("fp-1", "fp-2")

    def test_empty_report_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayRunReadinessBinding(
                readiness_report_id="",
                readiness_replay_plan_id="plan-1",
                readiness_status=ReplayReadinessStatus.READY,
                readiness_checked_at=_TS,
                readiness_total_fingerprints=1,
            )

    def test_empty_readiness_replay_plan_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _binding(readiness_replay_plan_id="")

    def test_whitespace_readiness_replay_plan_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _binding(readiness_replay_plan_id=" plan-1")

    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayRunReadinessBinding(
                readiness_report_id="rpt-1",
                readiness_replay_plan_id="plan-1",
                readiness_status=ReplayReadinessStatus.READY,
                readiness_checked_at=datetime(2026, 1, 1),
                readiness_total_fingerprints=1,
            )

    def test_bool_total_fingerprints_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayRunReadinessBinding(
                readiness_report_id="rpt-1",
                readiness_replay_plan_id="plan-1",
                readiness_status=ReplayReadinessStatus.READY,
                readiness_checked_at=_TS,
                readiness_total_fingerprints=True,  # type: ignore[arg-type]
            )

    def test_string_total_fingerprints_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayRunReadinessBinding(
                readiness_report_id="rpt-1",
                readiness_replay_plan_id="plan-1",
                readiness_status=ReplayReadinessStatus.READY,
                readiness_checked_at=_TS,
                readiness_total_fingerprints="1",  # type: ignore[arg-type]
            )

    def test_negative_total_fingerprints_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _binding(readiness_total_fingerprints=-1)

    def test_empty_latest_batch_report_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _binding(readiness_latest_batch_report_id="")

    def test_whitespace_latest_batch_report_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _binding(readiness_latest_batch_report_id=" b")

    def test_none_latest_batch_report_id_accepted(self) -> None:
        b = _binding(readiness_latest_batch_report_id=None)
        assert b.readiness_latest_batch_report_id is None

    def test_empty_verified_fingerprint_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _binding(verified_fingerprint_ids=("fp-1", ""))

    def test_duplicate_verified_fingerprint_ids_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _binding(verified_fingerprint_ids=("fp-1", "fp-1"))

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            ReplayRunReadinessBinding(
                readiness_report_id="rpt-1",
                readiness_replay_plan_id="plan-1",
                readiness_status=ReplayReadinessStatus.READY,
                readiness_checked_at=_TS,
                readiness_total_fingerprints=1,
                extra_field="x",  # type: ignore[call-arg]
            )

    def test_frozen_immutable(self) -> None:
        b = _binding()
        with pytest.raises((ValidationError, TypeError)):
            b.readiness_report_id = "modified"  # type: ignore[misc]


class TestReplayRunManifestPlanned:
    def test_valid_planned(self) -> None:
        m = _planned()
        assert m.status is ReplayRunManifestStatus.PLANNED
        assert m.fingerprint_ids == ("fp-1", "fp-2")
        assert m.verification_batch_report_id == "batch-1"

    def test_planned_non_ready_readiness_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _planned(readiness=_binding(readiness_status=ReplayReadinessStatus.BLOCKED))

    def test_planned_zero_total_fingerprints_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _planned(readiness=_binding(readiness_total_fingerprints=0))

    def test_planned_empty_fingerprint_ids_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _planned(fingerprint_ids=())

    def test_planned_no_verification_batch_report_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _planned(verification_batch_report_id=None)

    def test_planned_batch_id_mismatch_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _planned(
                verification_batch_report_id="batch-other",
                readiness=_binding(readiness_latest_batch_report_id="batch-1"),
            )

    def test_planned_replay_plan_id_mismatch_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _planned(
                replay_plan_id="plan-B",
                readiness=_binding(readiness_replay_plan_id="plan-A"),
            )

    def test_planned_same_count_different_fingerprint_ids_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _planned(
                fingerprint_ids=("fp-current",),
                readiness=_binding(
                    readiness_total_fingerprints=1,
                    verified_fingerprint_ids=("fp-verified",),
                ),
            )

    def test_planned_wrong_fingerprint_order_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _planned(
                fingerprint_ids=("fp-1", "fp-2"),
                readiness=_binding(verified_fingerprint_ids=("fp-2", "fp-1")),
            )

    def test_planned_with_notes(self) -> None:
        m = _planned(notes="initial plan")
        assert m.notes == "initial plan"

    def test_planned_notes_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _planned(notes="")

    def test_planned_notes_whitespace_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _planned(notes=" note")

    def test_planned_too_few_fingerprint_ids_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _planned(
                fingerprint_ids=("fp-1",),
                readiness=_binding(readiness_total_fingerprints=2),
            )

    def test_planned_too_many_fingerprint_ids_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _planned(
                fingerprint_ids=("fp-1", "fp-2"),
                readiness=_binding(readiness_total_fingerprints=1),
            )

    def test_planned_exact_count_match_accepted(self) -> None:
        m = _planned(
            fingerprint_ids=("fp-1", "fp-2", "fp-3"),
            readiness=_binding(readiness_total_fingerprints=3),
        )
        assert len(m.fingerprint_ids) == 3
        assert m.status is ReplayRunManifestStatus.PLANNED

    def test_planned_exact_plan_and_fingerprint_tuple_match_accepted(self) -> None:
        m = _planned(
            replay_plan_id="plan-exact",
            fingerprint_ids=("fp-a", "fp-b"),
            readiness=_binding(
                readiness_replay_plan_id="plan-exact",
                verified_fingerprint_ids=("fp-a", "fp-b"),
            ),
        )

        assert m.replay_plan_id == m.readiness.readiness_replay_plan_id
        assert m.fingerprint_ids == m.readiness.verified_fingerprint_ids

    def test_planned_created_before_readiness_rejected(self) -> None:
        readiness_checked_at = datetime(2026, 1, 1, 2, tzinfo=UTC)
        with pytest.raises(ValidationError, match="created_at"):
            _planned(
                created_at=datetime(2026, 1, 1, 1, tzinfo=UTC),
                readiness=_binding().model_copy(
                    update={"readiness_checked_at": readiness_checked_at}
                ),
            )

    def test_planned_created_equal_to_readiness_accepted(self) -> None:
        ts = datetime(2026, 1, 1, 2, tzinfo=UTC)
        m = _planned(
            created_at=ts,
            readiness=_binding().model_copy(update={"readiness_checked_at": ts}),
        )
        assert m.created_at == m.readiness.readiness_checked_at

    def test_planned_created_after_readiness_accepted(self) -> None:
        readiness_checked_at = datetime(2026, 1, 1, 2, tzinfo=UTC)
        m = _planned(
            created_at=datetime(2026, 1, 1, 3, tzinfo=UTC),
            readiness=_binding().model_copy(
                update={"readiness_checked_at": readiness_checked_at}
            ),
        )
        assert m.created_at > m.readiness.readiness_checked_at


class TestReplayRunManifestBlocked:
    def test_valid_blocked(self) -> None:
        m = _blocked()
        assert m.status is ReplayRunManifestStatus.BLOCKED

    def test_blocked_accepts_warning_readiness(self) -> None:
        m = _blocked(readiness=_binding(readiness_status=ReplayReadinessStatus.WARNING))
        assert m.status is ReplayRunManifestStatus.BLOCKED

    def test_blocked_accepts_invalidated_readiness(self) -> None:
        m = _blocked(readiness=_binding(readiness_status=ReplayReadinessStatus.INVALIDATED))
        assert m.status is ReplayRunManifestStatus.BLOCKED

    def test_blocked_rejects_ready_readiness(self) -> None:
        with pytest.raises(ValidationError):
            _blocked(readiness=_binding(readiness_status=ReplayReadinessStatus.READY))


class TestReplayRunManifestInvalidated:
    def test_invalidated_with_ready_readiness(self) -> None:
        m = ReplayRunManifest(
            manifest_id="m-1",
            replay_plan_id="plan-1",
            intent_kind=ReplayRunIntentKind.REPLAY_ONLY,
            created_at=_TS,
            status=ReplayRunManifestStatus.INVALIDATED,
            readiness=_binding(readiness_status=ReplayReadinessStatus.READY),
        )
        assert m.status is ReplayRunManifestStatus.INVALIDATED

    def test_invalidated_with_blocked_readiness(self) -> None:
        m = ReplayRunManifest(
            manifest_id="m-1",
            replay_plan_id="plan-1",
            intent_kind=ReplayRunIntentKind.REPLAY_ONLY,
            created_at=_TS,
            status=ReplayRunManifestStatus.INVALIDATED,
            readiness=_binding(readiness_status=ReplayReadinessStatus.BLOCKED),
        )
        assert m.status is ReplayRunManifestStatus.INVALIDATED


class TestReplayRunManifestValidation:
    def test_empty_manifest_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayRunManifest(
                manifest_id="",
                replay_plan_id="plan-1",
                intent_kind=ReplayRunIntentKind.REPLAY_ONLY,
                created_at=_TS,
                status=ReplayRunManifestStatus.INVALIDATED,
                readiness=_binding(),
            )

    def test_empty_replay_plan_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayRunManifest(
                manifest_id="m-1",
                replay_plan_id="",
                intent_kind=ReplayRunIntentKind.REPLAY_ONLY,
                created_at=_TS,
                status=ReplayRunManifestStatus.INVALIDATED,
                readiness=_binding(),
            )

    def test_naive_created_at_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayRunManifest(
                manifest_id="m-1",
                replay_plan_id="plan-1",
                intent_kind=ReplayRunIntentKind.REPLAY_ONLY,
                created_at=datetime(2026, 1, 1),
                status=ReplayRunManifestStatus.INVALIDATED,
                readiness=_binding(),
            )

    def test_duplicate_fingerprint_ids_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayRunManifest(
                manifest_id="m-1",
                replay_plan_id="plan-1",
                intent_kind=ReplayRunIntentKind.REPLAY_ONLY,
                created_at=_TS,
                status=ReplayRunManifestStatus.INVALIDATED,
                readiness=_binding(),
                fingerprint_ids=("fp-1", "fp-1"),
            )

    def test_empty_fingerprint_id_in_tuple_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayRunManifest(
                manifest_id="m-1",
                replay_plan_id="plan-1",
                intent_kind=ReplayRunIntentKind.REPLAY_ONLY,
                created_at=_TS,
                status=ReplayRunManifestStatus.INVALIDATED,
                readiness=_binding(),
                fingerprint_ids=("fp-1", ""),
            )

    def test_empty_verification_batch_report_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayRunManifest(
                manifest_id="m-1",
                replay_plan_id="plan-1",
                intent_kind=ReplayRunIntentKind.REPLAY_ONLY,
                created_at=_TS,
                status=ReplayRunManifestStatus.INVALIDATED,
                readiness=_binding(),
                verification_batch_report_id="",
            )

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            ReplayRunManifest(
                manifest_id="m-1",
                replay_plan_id="plan-1",
                intent_kind=ReplayRunIntentKind.REPLAY_ONLY,
                created_at=_TS,
                status=ReplayRunManifestStatus.INVALIDATED,
                readiness=_binding(),
                extra_field="x",  # type: ignore[call-arg]
            )

    def test_frozen_immutable(self) -> None:
        m = _planned()
        with pytest.raises((ValidationError, TypeError)):
            m.manifest_id = "modified"  # type: ignore[misc]

    def test_intent_kinds_accepted(self) -> None:
        for kind in ReplayRunIntentKind:
            m = ReplayRunManifest(
                manifest_id="m-1",
                replay_plan_id="plan-1",
                intent_kind=kind,
                created_at=_TS,
                status=ReplayRunManifestStatus.INVALIDATED,
                readiness=_binding(),
            )
            assert m.intent_kind is kind


class TestReplayRunManifestNoForbiddenImports:
    def test_no_forbidden_imports(self) -> None:
        src = Path(__file__).parent.parent.parent / "src/futures_bot/domain/replay.py"
        tree = ast.parse(src.read_text())
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.append(node.module or "")
        forbidden = ("pandas", "numpy", "sklearn", "torch", "sqlalchemy", "psycopg",
                     "confluent_kafka", "aiokafka", "subprocess", "threading", "asyncio")
        for name in forbidden:
            assert not any(name in n for n in names), f"forbidden import {name!r} in domain"
