from __future__ import annotations

import types
from collections import UserDict
from collections.abc import Mapping
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.replay import (
    ReplayArtifactFingerprintVerificationBatchItem,
    ReplayArtifactFingerprintVerificationBatchReport,
    ReplayArtifactFingerprintVerificationBatchReportStatus,
    ReplayArtifactFingerprintVerificationBatchScopeKind,
    ReplayArtifactFingerprintVerificationBatchSummary,
    ReplayArtifactFingerprintVerificationStatus,
    ReplayArtifactKind,
)


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _make_item(  # noqa: PLR0913
    item_id: str = "item-1",
    fingerprint_id: str = "fp-1",
    verification_id: str = "ver-1",
    *,
    verification_status: ReplayArtifactFingerprintVerificationStatus = (
        ReplayArtifactFingerprintVerificationStatus.VALID
    ),
    issue_count: int = 0,
    artifact_kind: ReplayArtifactKind | None = ReplayArtifactKind.TIMELINE,
    artifact_id: str | None = "tl-1",
    replay_plan_id: str | None = "plan-1",
) -> ReplayArtifactFingerprintVerificationBatchItem:
    return ReplayArtifactFingerprintVerificationBatchItem(
        item_id=item_id,
        fingerprint_id=fingerprint_id,
        verification_id=verification_id,
        verification_status=verification_status,
        issue_count=issue_count,
        artifact_kind=artifact_kind,
        artifact_id=artifact_id,
        replay_plan_id=replay_plan_id,
    )


def _make_summary(
    total_fingerprints: int = 1,
    count_by_status: Mapping[ReplayArtifactFingerprintVerificationStatus, int] | None = None,
    total_issues: int = 0,
) -> ReplayArtifactFingerprintVerificationBatchSummary:
    if count_by_status is None:
        if total_fingerprints > 0:
            count_by_status = {
                ReplayArtifactFingerprintVerificationStatus.VALID: total_fingerprints
            }
        else:
            count_by_status = {}
    valid_count = count_by_status.get(ReplayArtifactFingerprintVerificationStatus.VALID, 0)
    mismatch_count = count_by_status.get(
        ReplayArtifactFingerprintVerificationStatus.MISMATCH, 0
    )
    missing_fp = count_by_status.get(
        ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT, 0
    )
    missing_art = count_by_status.get(
        ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT, 0
    )
    return ReplayArtifactFingerprintVerificationBatchSummary(
        total_fingerprints=total_fingerprints,
        count_by_status=count_by_status,
        total_issues=total_issues,
        all_valid=total_fingerprints > 0 and valid_count == total_fingerprints,
        has_mismatches=mismatch_count > 0,
        has_missing=(missing_fp + missing_art) > 0,
    )


def _make_report(  # noqa: PLR0913
    report_id: str = "rpt-1",
    *,
    items: tuple[ReplayArtifactFingerprintVerificationBatchItem, ...] | None = None,
    summary: ReplayArtifactFingerprintVerificationBatchSummary | None = None,
    status: ReplayArtifactFingerprintVerificationBatchReportStatus = (
        ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED
    ),
    scope_kind: ReplayArtifactFingerprintVerificationBatchScopeKind = (
        ReplayArtifactFingerprintVerificationBatchScopeKind.EXPLICIT_FINGERPRINT_SET
    ),
    replay_plan_id: str | None = None,
    requested_fingerprint_ids: tuple[str, ...] | None = None,
) -> ReplayArtifactFingerprintVerificationBatchReport:
    if items is None:
        items = (_make_item(),)
    if summary is None:
        summary = _make_summary()
    if requested_fingerprint_ids is None:
        requested_fingerprint_ids = tuple(i.fingerprint_id for i in items)
    return ReplayArtifactFingerprintVerificationBatchReport(
        report_id=report_id,
        scope_kind=scope_kind,
        replay_plan_id=replay_plan_id,
        generated_at=_utc(0),
        status=status,
        items=items,
        summary=summary,
        requested_fingerprint_ids=requested_fingerprint_ids,
    )


class TestReplayArtifactFingerprintVerificationBatchItem:
    def test_valid_construction(self) -> None:
        item = _make_item()
        assert item.item_id == "item-1"
        assert item.fingerprint_id == "fp-1"
        assert item.verification_id == "ver-1"
        assert item.verification_status is ReplayArtifactFingerprintVerificationStatus.VALID
        assert item.issue_count == 0

    def test_optional_fields_default_none(self) -> None:
        item = ReplayArtifactFingerprintVerificationBatchItem(
            item_id="item-1",
            fingerprint_id="fp-1",
            verification_id="ver-1",
            verification_status=ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT,
            issue_count=1,
        )
        assert item.artifact_kind is None
        assert item.artifact_id is None
        assert item.replay_plan_id is None

    def test_empty_item_id_raises(self) -> None:
        with pytest.raises(ValidationError, match="item_id"):
            _make_item(item_id="")

    def test_empty_fingerprint_id_raises(self) -> None:
        with pytest.raises(ValidationError, match="fingerprint_id"):
            _make_item(fingerprint_id="")

    def test_empty_verification_id_raises(self) -> None:
        with pytest.raises(ValidationError, match="verification_id"):
            _make_item(verification_id="")

    def test_all_statuses_accepted(self) -> None:
        for vs in ReplayArtifactFingerprintVerificationStatus:
            issue_count = 1 if vs in {
                ReplayArtifactFingerprintVerificationStatus.MISMATCH,
                ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT,
                ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT,
            } else 0
            item = _make_item(verification_status=vs, issue_count=issue_count)
            assert item.verification_status is vs

    def test_frozen(self) -> None:
        item = _make_item()
        with pytest.raises((TypeError, ValidationError)):
            item.item_id = "changed"  # type: ignore[misc]

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprintVerificationBatchItem(
                item_id="item-1",
                fingerprint_id="fp-1",
                verification_id="ver-1",
                verification_status=ReplayArtifactFingerprintVerificationStatus.VALID,
                unknown_field="x",  # type: ignore[call-arg]
            )

    def test_issue_count_default_zero(self) -> None:
        item = _make_item()
        assert item.issue_count == 0

    def test_issue_count_positive_for_mismatch(self) -> None:
        item = _make_item(
            verification_status=ReplayArtifactFingerprintVerificationStatus.MISMATCH,
            issue_count=3,
        )
        assert item.issue_count == 3

    def test_valid_item_with_positive_issue_count_rejected(self) -> None:
        with pytest.raises(ValidationError, match="VALID"):
            _make_item(issue_count=1)

    def test_valid_item_with_zero_issue_count_accepted(self) -> None:
        item = _make_item(issue_count=0)
        assert item.verification_status is ReplayArtifactFingerprintVerificationStatus.VALID
        assert item.issue_count == 0

    def test_mismatch_with_zero_issue_count_rejected(self) -> None:
        with pytest.raises(ValidationError, match="issue_count > 0"):
            _make_item(
                verification_status=ReplayArtifactFingerprintVerificationStatus.MISMATCH,
                issue_count=0,
            )

    def test_missing_fingerprint_with_zero_issue_count_rejected(self) -> None:
        with pytest.raises(ValidationError, match="issue_count > 0"):
            _make_item(
                verification_status=(
                    ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT
                ),
                issue_count=0,
            )

    def test_missing_artifact_with_zero_issue_count_rejected(self) -> None:
        with pytest.raises(ValidationError, match="issue_count > 0"):
            _make_item(
                verification_status=(
                    ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT
                ),
                issue_count=0,
            )

    def test_invalidated_with_zero_issue_count_accepted(self) -> None:
        item = _make_item(
            verification_status=ReplayArtifactFingerprintVerificationStatus.INVALIDATED,
            issue_count=0,
        )
        assert item.issue_count == 0

    def test_issue_count_negative_rejected(self) -> None:
        with pytest.raises(ValidationError, match="issue_count"):
            _make_item(issue_count=-1)

    def test_issue_count_bool_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_item(issue_count=True)  # type: ignore[arg-type]

    def test_artifact_id_empty_rejected(self) -> None:
        with pytest.raises(ValidationError, match="artifact_id"):
            _make_item(artifact_id="")

    def test_replay_plan_id_empty_rejected(self) -> None:
        with pytest.raises(ValidationError, match="replay_plan_id"):
            _make_item(replay_plan_id="")

    def test_issue_count_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_item(issue_count="1")  # type: ignore[arg-type]

    def test_issue_count_float_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_item(issue_count=1.0)  # type: ignore[arg-type]


class TestReplayArtifactFingerprintVerificationBatchSummary:
    def test_valid_all_valid(self) -> None:
        s = _make_summary(total_fingerprints=2)
        assert s.all_valid is True
        assert s.total_fingerprints == 2
        assert s.has_mismatches is False
        assert s.has_missing is False

    def test_valid_all_mismatch(self) -> None:
        s = _make_summary(
            total_fingerprints=2,
            count_by_status={ReplayArtifactFingerprintVerificationStatus.MISMATCH: 2},
        )
        assert s.count_by_status[ReplayArtifactFingerprintVerificationStatus.MISMATCH] == 2
        assert s.has_mismatches is True
        assert s.all_valid is False

    def test_valid_mixed(self) -> None:
        s = _make_summary(
            total_fingerprints=4,
            count_by_status={
                ReplayArtifactFingerprintVerificationStatus.VALID: 1,
                ReplayArtifactFingerprintVerificationStatus.MISMATCH: 1,
                ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT: 1,
                ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT: 1,
            },
        )
        assert s.total_fingerprints == 4
        assert s.has_mismatches is True
        assert s.has_missing is True

    def test_valid_empty_zero_counts(self) -> None:
        s = _make_summary(total_fingerprints=0)
        assert s.total_fingerprints == 0
        assert s.all_valid is False
        assert dict(s.count_by_status) == {}

    def test_has_missing_from_missing_fingerprint(self) -> None:
        s = _make_summary(
            total_fingerprints=1,
            count_by_status={
                ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT: 1
            },
        )
        assert s.has_missing is True
        assert s.has_mismatches is False

    def test_has_missing_from_missing_artifact(self) -> None:
        s = _make_summary(
            total_fingerprints=1,
            count_by_status={
                ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT: 1
            },
        )
        assert s.has_missing is True

    def test_total_issues_field_for_mismatch(self) -> None:
        s = _make_summary(
            total_fingerprints=1,
            count_by_status={ReplayArtifactFingerprintVerificationStatus.MISMATCH: 1},
            total_issues=5,
        )
        assert s.total_issues == 5

    def test_bool_total_fingerprints_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprintVerificationBatchSummary(
                total_fingerprints=True,  # type: ignore[arg-type]
                count_by_status={ReplayArtifactFingerprintVerificationStatus.VALID: 1},
                total_issues=0,
                all_valid=True,
                has_mismatches=False,
                has_missing=False,
            )

    def test_bool_total_issues_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprintVerificationBatchSummary(
                total_fingerprints=1,
                count_by_status={ReplayArtifactFingerprintVerificationStatus.VALID: 1},
                total_issues=True,  # type: ignore[arg-type]
                all_valid=True,
                has_mismatches=False,
                has_missing=False,
            )

    def test_bool_count_by_status_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprintVerificationBatchSummary(
                total_fingerprints=1,
                count_by_status={
                    ReplayArtifactFingerprintVerificationStatus.VALID: True,  # type: ignore[dict-item]
                },
                total_issues=0,
                all_valid=True,
                has_mismatches=False,
                has_missing=False,
            )

    def test_negative_count_by_status_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must be >= 0"):
            ReplayArtifactFingerprintVerificationBatchSummary(
                total_fingerprints=1,
                count_by_status={ReplayArtifactFingerprintVerificationStatus.VALID: -1},
                total_issues=0,
                all_valid=True,
                has_mismatches=False,
                has_missing=False,
            )

    def test_negative_total_fingerprints_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must be >= 0"):
            ReplayArtifactFingerprintVerificationBatchSummary(
                total_fingerprints=-1,
                count_by_status={},
                total_issues=0,
                all_valid=False,
                has_mismatches=False,
                has_missing=False,
            )

    def test_negative_total_issues_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must be >= 0"):
            ReplayArtifactFingerprintVerificationBatchSummary(
                total_fingerprints=1,
                count_by_status={ReplayArtifactFingerprintVerificationStatus.VALID: 1},
                total_issues=-1,
                all_valid=True,
                has_mismatches=False,
                has_missing=False,
            )

    def test_counts_dont_sum_to_total_raises(self) -> None:
        with pytest.raises(ValidationError, match="sum of count_by_status"):
            ReplayArtifactFingerprintVerificationBatchSummary(
                total_fingerprints=5,
                count_by_status={ReplayArtifactFingerprintVerificationStatus.VALID: 2},
                total_issues=0,
                all_valid=False,
                has_mismatches=False,
                has_missing=False,
            )

    def test_count_by_status_nonempty_when_total_zero_raises(self) -> None:
        with pytest.raises(ValidationError, match="empty when total_fingerprints == 0"):
            ReplayArtifactFingerprintVerificationBatchSummary(
                total_fingerprints=0,
                count_by_status={ReplayArtifactFingerprintVerificationStatus.VALID: 0},
                total_issues=0,
                all_valid=False,
                has_mismatches=False,
                has_missing=False,
            )

    def test_all_valid_wrong_raises(self) -> None:
        with pytest.raises(ValidationError, match="all_valid"):
            ReplayArtifactFingerprintVerificationBatchSummary(
                total_fingerprints=2,
                count_by_status={ReplayArtifactFingerprintVerificationStatus.VALID: 2},
                total_issues=0,
                all_valid=False,
                has_mismatches=False,
                has_missing=False,
            )

    def test_all_valid_with_total_issues_rejected(self) -> None:
        with pytest.raises(ValidationError, match="total_issues"):
            ReplayArtifactFingerprintVerificationBatchSummary(
                total_fingerprints=1,
                count_by_status={ReplayArtifactFingerprintVerificationStatus.VALID: 1},
                total_issues=1,
                all_valid=True,
                has_mismatches=False,
                has_missing=False,
            )

    def test_all_valid_true_when_not_all_raises(self) -> None:
        with pytest.raises(ValidationError, match="all_valid"):
            ReplayArtifactFingerprintVerificationBatchSummary(
                total_fingerprints=2,
                count_by_status={
                    ReplayArtifactFingerprintVerificationStatus.VALID: 1,
                    ReplayArtifactFingerprintVerificationStatus.MISMATCH: 1,
                },
                total_issues=0,
                all_valid=True,
                has_mismatches=True,
                has_missing=False,
            )

    def test_has_mismatches_wrong_raises(self) -> None:
        with pytest.raises(ValidationError, match="has_mismatches"):
            ReplayArtifactFingerprintVerificationBatchSummary(
                total_fingerprints=2,
                count_by_status={
                    ReplayArtifactFingerprintVerificationStatus.VALID: 1,
                    ReplayArtifactFingerprintVerificationStatus.MISMATCH: 1,
                },
                total_issues=0,
                all_valid=False,
                has_mismatches=False,
                has_missing=False,
            )

    def test_has_missing_wrong_raises(self) -> None:
        with pytest.raises(ValidationError, match="has_missing"):
            ReplayArtifactFingerprintVerificationBatchSummary(
                total_fingerprints=1,
                count_by_status={
                    ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT: 1
                },
                total_issues=0,
                all_valid=False,
                has_mismatches=False,
                has_missing=False,
            )

    def test_all_valid_false_when_empty(self) -> None:
        s = _make_summary(total_fingerprints=0)
        assert s.all_valid is False

    def test_total_fingerprints_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprintVerificationBatchSummary(
                total_fingerprints="1",  # type: ignore[arg-type]
                count_by_status={ReplayArtifactFingerprintVerificationStatus.VALID: 1},
                total_issues=0,
                all_valid=True,
                has_mismatches=False,
                has_missing=False,
            )

    def test_total_fingerprints_float_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprintVerificationBatchSummary(
                total_fingerprints=1.0,  # type: ignore[arg-type]
                count_by_status={ReplayArtifactFingerprintVerificationStatus.VALID: 1},
                total_issues=0,
                all_valid=True,
                has_mismatches=False,
                has_missing=False,
            )

    def test_total_issues_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprintVerificationBatchSummary(
                total_fingerprints=1,
                count_by_status={ReplayArtifactFingerprintVerificationStatus.VALID: 1},
                total_issues="0",  # type: ignore[arg-type]
                all_valid=True,
                has_mismatches=False,
                has_missing=False,
            )

    def test_count_by_status_string_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprintVerificationBatchSummary(
                total_fingerprints=1,
                count_by_status={
                    ReplayArtifactFingerprintVerificationStatus.VALID: "1",  # type: ignore[dict-item]
                },
                total_issues=0,
                all_valid=True,
                has_mismatches=False,
                has_missing=False,
            )

    def test_count_by_status_userdict_string_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprintVerificationBatchSummary(
                total_fingerprints=1,
                count_by_status=UserDict(
                    {ReplayArtifactFingerprintVerificationStatus.VALID: "1"}  # type: ignore[dict-item]
                ),
                total_issues=0,
                all_valid=True,
                has_mismatches=False,
                has_missing=False,
            )

    def test_count_by_status_mappingproxy_string_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprintVerificationBatchSummary(
                total_fingerprints=1,
                count_by_status=types.MappingProxyType(
                    {ReplayArtifactFingerprintVerificationStatus.VALID: "1"}  # type: ignore[dict-item]
                ),
                total_issues=0,
                all_valid=True,
                has_mismatches=False,
                has_missing=False,
            )

    def test_count_by_status_userdict_float_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprintVerificationBatchSummary(
                total_fingerprints=1,
                count_by_status=UserDict(
                    {ReplayArtifactFingerprintVerificationStatus.VALID: 1.0}  # type: ignore[dict-item]
                ),
                total_issues=0,
                all_valid=True,
                has_mismatches=False,
                has_missing=False,
            )

    def test_count_by_status_userdict_valid_int_accepted(self) -> None:
        s = ReplayArtifactFingerprintVerificationBatchSummary(
            total_fingerprints=1,
            count_by_status=UserDict(
                {ReplayArtifactFingerprintVerificationStatus.VALID: 1}
            ),
            total_issues=0,
            all_valid=True,
            has_mismatches=False,
            has_missing=False,
        )
        assert s.total_fingerprints == 1

    def test_count_by_status_mappingproxy_valid_int_accepted(self) -> None:
        s = ReplayArtifactFingerprintVerificationBatchSummary(
            total_fingerprints=1,
            count_by_status=types.MappingProxyType(
                {ReplayArtifactFingerprintVerificationStatus.VALID: 1}
            ),
            total_issues=0,
            all_valid=True,
            has_mismatches=False,
            has_missing=False,
        )
        assert s.total_fingerprints == 1


class TestReplayArtifactFingerprintVerificationBatchReport:
    def test_valid_construction(self) -> None:
        report = _make_report()
        assert report.report_id == "rpt-1"
        assert report.status is ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED
        assert len(report.items) == 1

    def test_empty_report_id_raises(self) -> None:
        with pytest.raises(ValidationError, match="report_id"):
            _make_report(report_id="")

    def test_generated_at_naive_raises(self) -> None:
        with pytest.raises((ValidationError, ValueError)):
            ReplayArtifactFingerprintVerificationBatchReport(
                report_id="rpt-1",
                scope_kind=ReplayArtifactFingerprintVerificationBatchScopeKind.EXPLICIT_FINGERPRINT_SET,
                generated_at=datetime(2026, 1, 1, 0),
                status=ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED,
                items=(_make_item(),),
                summary=_make_summary(),
            )

    def test_generated_at_aware_accepted(self) -> None:
        report = _make_report()
        assert report.generated_at.tzinfo is not None

    def test_duplicate_item_ids_raises(self) -> None:
        items = (
            _make_item("item-dup", "fp-1", "ver-1"),
            _make_item("item-dup", "fp-2", "ver-2"),
        )
        summary = _make_summary(
            total_fingerprints=2,
            count_by_status={ReplayArtifactFingerprintVerificationStatus.VALID: 2},
        )
        with pytest.raises(ValidationError, match="duplicate item_id"):
            ReplayArtifactFingerprintVerificationBatchReport(
                report_id="rpt-1",
                scope_kind=ReplayArtifactFingerprintVerificationBatchScopeKind.EXPLICIT_FINGERPRINT_SET,
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED,
                items=items,
                summary=summary,
            )

    def test_duplicate_verification_ids_raises(self) -> None:
        items = (
            _make_item("item-1", "fp-1", "ver-dup"),
            _make_item("item-2", "fp-2", "ver-dup"),
        )
        summary = _make_summary(
            total_fingerprints=2,
            count_by_status={ReplayArtifactFingerprintVerificationStatus.VALID: 2},
        )
        with pytest.raises(ValidationError, match="duplicate verification_id"):
            ReplayArtifactFingerprintVerificationBatchReport(
                report_id="rpt-1",
                scope_kind=ReplayArtifactFingerprintVerificationBatchScopeKind.EXPLICIT_FINGERPRINT_SET,
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED,
                items=items,
                summary=summary,
            )

    def test_duplicate_fingerprint_ids_in_items_raises(self) -> None:
        items = (
            _make_item("item-1", "fp-dup", "ver-1"),
            _make_item("item-2", "fp-dup", "ver-2"),
        )
        summary = _make_summary(
            total_fingerprints=2,
            count_by_status={ReplayArtifactFingerprintVerificationStatus.VALID: 2},
        )
        with pytest.raises(ValidationError, match="duplicate fingerprint_id"):
            ReplayArtifactFingerprintVerificationBatchReport(
                report_id="rpt-1",
                scope_kind=ReplayArtifactFingerprintVerificationBatchScopeKind.EXPLICIT_FINGERPRINT_SET,
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED,
                items=items,
                summary=summary,
            )

    def test_summary_total_fingerprints_mismatch_raises(self) -> None:
        with pytest.raises(ValidationError, match="total_fingerprints"):
            ReplayArtifactFingerprintVerificationBatchReport(
                report_id="rpt-1",
                scope_kind=ReplayArtifactFingerprintVerificationBatchScopeKind.EXPLICIT_FINGERPRINT_SET,
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED,
                items=(_make_item(),),
                summary=_make_summary(
                    total_fingerprints=2,
                    count_by_status={ReplayArtifactFingerprintVerificationStatus.VALID: 2},
                ),
            )

    def test_summary_count_by_status_mismatch_raises(self) -> None:
        items = (
            _make_item("item-1", "fp-1", "ver-1"),
            _make_item(
                "item-2",
                "fp-2",
                "ver-2",
                verification_status=ReplayArtifactFingerprintVerificationStatus.MISMATCH,
                issue_count=1,
            ),
        )
        bad_summary = _make_summary(
            total_fingerprints=2,
            count_by_status={
                ReplayArtifactFingerprintVerificationStatus.VALID: 1,
                ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT: 1,
            },
        )
        with pytest.raises(ValidationError, match="count_by_status"):
            ReplayArtifactFingerprintVerificationBatchReport(
                report_id="rpt-1",
                scope_kind=ReplayArtifactFingerprintVerificationBatchScopeKind.EXPLICIT_FINGERPRINT_SET,
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED,
                items=items,
                summary=bad_summary,
                requested_fingerprint_ids=("fp-1", "fp-2"),
            )

    def test_summary_total_issues_mismatch_raises(self) -> None:
        items = (
            _make_item(
                verification_status=ReplayArtifactFingerprintVerificationStatus.MISMATCH,
                issue_count=2,
            ),
        )
        bad_summary = _make_summary(
            total_fingerprints=1,
            count_by_status={ReplayArtifactFingerprintVerificationStatus.MISMATCH: 1},
            total_issues=0,
        )
        with pytest.raises(ValidationError, match="total_issues"):
            ReplayArtifactFingerprintVerificationBatchReport(
                report_id="rpt-1",
                scope_kind=ReplayArtifactFingerprintVerificationBatchScopeKind.EXPLICIT_FINGERPRINT_SET,
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED,
                items=items,
                summary=bad_summary,
            )

    def test_empty_items_valid(self) -> None:
        report = ReplayArtifactFingerprintVerificationBatchReport(
            report_id="rpt-empty",
            scope_kind=ReplayArtifactFingerprintVerificationBatchScopeKind.REPLAY_PLAN,
            replay_plan_id="plan-1",
            generated_at=_utc(0),
            status=ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED,
            items=(),
            summary=_make_summary(total_fingerprints=0),
        )
        assert len(report.items) == 0
        assert report.summary.all_valid is False

    def test_invalidated_status_accepted(self) -> None:
        report = _make_report(
            status=ReplayArtifactFingerprintVerificationBatchReportStatus.INVALIDATED
        )
        assert report.status is ReplayArtifactFingerprintVerificationBatchReportStatus.INVALIDATED

    def test_replay_plan_id_optional(self) -> None:
        report = _make_report(replay_plan_id=None)
        assert report.replay_plan_id is None

    def test_replay_plan_id_set(self) -> None:
        report = _make_report(
            scope_kind=ReplayArtifactFingerprintVerificationBatchScopeKind.REPLAY_PLAN,
            replay_plan_id="plan-1",
        )
        assert report.replay_plan_id == "plan-1"

    def test_all_scope_kinds_accepted(self) -> None:
        for kind in ReplayArtifactFingerprintVerificationBatchScopeKind:
            rp_id = (
                "plan-1"
                if kind is ReplayArtifactFingerprintVerificationBatchScopeKind.REPLAY_PLAN
                else None
            )
            report = _make_report(scope_kind=kind, replay_plan_id=rp_id)
            assert report.scope_kind is kind

    def test_notes_stored(self) -> None:
        report = ReplayArtifactFingerprintVerificationBatchReport(
            report_id="rpt-1",
            scope_kind=ReplayArtifactFingerprintVerificationBatchScopeKind.EXPLICIT_FINGERPRINT_SET,
            generated_at=_utc(0),
            status=ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED,
            items=(_make_item(),),
            summary=_make_summary(),
            requested_fingerprint_ids=("fp-1",),
            notes="batch verification run",
        )
        assert report.notes == "batch verification run"

    def test_notes_empty_rejected(self) -> None:
        with pytest.raises(ValidationError, match="notes"):
            ReplayArtifactFingerprintVerificationBatchReport(
                report_id="rpt-1",
                scope_kind=ReplayArtifactFingerprintVerificationBatchScopeKind.EXPLICIT_FINGERPRINT_SET,
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED,
                items=(_make_item(),),
                summary=_make_summary(),
                notes="",
            )

    def test_notes_leading_whitespace_rejected(self) -> None:
        with pytest.raises(ValidationError, match="notes"):
            ReplayArtifactFingerprintVerificationBatchReport(
                report_id="rpt-1",
                scope_kind=ReplayArtifactFingerprintVerificationBatchScopeKind.EXPLICIT_FINGERPRINT_SET,
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED,
                items=(_make_item(),),
                summary=_make_summary(),
                notes=" leading",
            )

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            ReplayArtifactFingerprintVerificationBatchReport(
                report_id="rpt-1",
                scope_kind=ReplayArtifactFingerprintVerificationBatchScopeKind.EXPLICIT_FINGERPRINT_SET,
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED,
                items=(_make_item(),),
                summary=_make_summary(),
                unknown="x",  # type: ignore[call-arg]
            )

    def test_replay_plan_id_empty_rejected(self) -> None:
        with pytest.raises(ValidationError, match="replay_plan_id"):
            _make_report(replay_plan_id="")

    def test_replay_plan_scope_requires_replay_plan_id(self) -> None:
        with pytest.raises(ValidationError, match="REPLAY_PLAN"):
            _make_report(
                scope_kind=ReplayArtifactFingerprintVerificationBatchScopeKind.REPLAY_PLAN,
                replay_plan_id=None,
            )

    def test_requested_fingerprint_ids_default_empty(self) -> None:
        report = ReplayArtifactFingerprintVerificationBatchReport(
            report_id="rpt-1",
            scope_kind=ReplayArtifactFingerprintVerificationBatchScopeKind.EXPLICIT_FINGERPRINT_SET,
            generated_at=_utc(0),
            status=ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED,
            items=(),
            summary=_make_summary(total_fingerprints=0),
        )
        assert report.requested_fingerprint_ids == ()

    def test_requested_fingerprint_ids_stored(self) -> None:
        report = _make_report(requested_fingerprint_ids=("fp-1",))
        assert report.requested_fingerprint_ids == ("fp-1",)

    def test_duplicate_requested_fingerprint_ids_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate fingerprint_id"):
            _make_report(requested_fingerprint_ids=("fp-1", "fp-1"))

    def test_empty_requested_fp_id_rejected(self) -> None:
        with pytest.raises(ValidationError, match="requested_fingerprint_ids"):
            _make_report(requested_fingerprint_ids=("",))

    def test_requested_fp_ids_mismatch_items_rejected(self) -> None:
        items = (_make_item("item-1", "fp-1", "ver-1"),)
        summary = _make_summary()
        with pytest.raises(ValidationError, match="requested_fingerprint_ids"):
            ReplayArtifactFingerprintVerificationBatchReport(
                report_id="rpt-1",
                scope_kind=ReplayArtifactFingerprintVerificationBatchScopeKind.EXPLICIT_FINGERPRINT_SET,
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED,
                items=items,
                summary=summary,
                requested_fingerprint_ids=("fp-2",),
            )

    def test_summary_missing_fp_mismatch_raises(self) -> None:
        items = (
            _make_item(
                "item-1",
                "fp-1",
                "ver-1",
                verification_status=ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT,
                artifact_kind=None,
                artifact_id=None,
                replay_plan_id=None,
                issue_count=1,
            ),
        )
        bad_summary = _make_summary(
            total_fingerprints=1,
            count_by_status={
                ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT: 1
            },
        )
        with pytest.raises(ValidationError, match="count_by_status"):
            ReplayArtifactFingerprintVerificationBatchReport(
                report_id="rpt-1",
                scope_kind=ReplayArtifactFingerprintVerificationBatchScopeKind.EXPLICIT_FINGERPRINT_SET,
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED,
                items=items,
                summary=bad_summary,
            )

    def test_requested_fp_ids_wrong_order_rejected(self) -> None:
        items = (
            _make_item("item-1", "fp-1", "ver-1"),
            _make_item("item-2", "fp-2", "ver-2"),
        )
        summary = _make_summary(
            total_fingerprints=2,
            count_by_status={ReplayArtifactFingerprintVerificationStatus.VALID: 2},
        )
        with pytest.raises(ValidationError, match="requested_fingerprint_ids"):
            ReplayArtifactFingerprintVerificationBatchReport(
                report_id="rpt-1",
                scope_kind=ReplayArtifactFingerprintVerificationBatchScopeKind.EXPLICIT_FINGERPRINT_SET,
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED,
                items=items,
                summary=summary,
                requested_fingerprint_ids=("fp-2", "fp-1"),
            )

    def test_summary_missing_artifact_mismatch_raises(self) -> None:
        items = (
            _make_item(
                "item-1",
                "fp-1",
                "ver-1",
                verification_status=ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT,
                issue_count=1,
            ),
        )
        bad_summary = _make_summary(
            total_fingerprints=1,
            count_by_status={
                ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT: 1
            },
        )
        with pytest.raises(ValidationError, match="count_by_status"):
            ReplayArtifactFingerprintVerificationBatchReport(
                report_id="rpt-1",
                scope_kind=ReplayArtifactFingerprintVerificationBatchScopeKind.EXPLICIT_FINGERPRINT_SET,
                generated_at=_utc(0),
                status=ReplayArtifactFingerprintVerificationBatchReportStatus.GENERATED,
                items=items,
                summary=bad_summary,
            )
