from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.replay import (
    ReplayTimelineCoverageDiff,
    ReplayTimelineCoverageDiffDirection,
    ReplayTimelineCoverageDiffItem,
    ReplayTimelineCoverageDiffKind,
    ReplayTimelineCoverageDiffSeverity,
    ReplayTimelineCoverageDiffStatus,
    ReplayTimelineCoverageDiffSummary,
)
from futures_bot.domain.research import TemporalWindow, TemporalWindowKind


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _window() -> TemporalWindow:
    return TemporalWindow(
        kind=TemporalWindowKind.TEST,
        start_at=_utc(0),
        end_at=_utc(10),
        window_id="tw-1",
    )


def _item(
    item_id: str = "item-1",
    *,
    kind: ReplayTimelineCoverageDiffKind = ReplayTimelineCoverageDiffKind.OTHER,
    severity: ReplayTimelineCoverageDiffSeverity = ReplayTimelineCoverageDiffSeverity.INFO,
    message: str = "test item",
) -> ReplayTimelineCoverageDiffItem:
    return ReplayTimelineCoverageDiffItem(
        item_id=item_id,
        kind=kind,
        severity=severity,
        message=message,
    )


def _empty_summary() -> ReplayTimelineCoverageDiffSummary:
    return ReplayTimelineCoverageDiffSummary(
        total_items=0,
        item_count_by_kind={},
        item_count_by_severity={},
        has_errors=False,
        has_warnings=False,
    )


def _summary_from_items(
    items: tuple[ReplayTimelineCoverageDiffItem, ...],
) -> ReplayTimelineCoverageDiffSummary:
    by_kind: dict[ReplayTimelineCoverageDiffKind, int] = {}
    by_severity: dict[ReplayTimelineCoverageDiffSeverity, int] = {}
    for item in items:
        by_kind[item.kind] = by_kind.get(item.kind, 0) + 1
        by_severity[item.severity] = by_severity.get(item.severity, 0) + 1
    return ReplayTimelineCoverageDiffSummary(
        total_items=len(items),
        item_count_by_kind=by_kind,
        item_count_by_severity=by_severity,
        has_errors=by_severity.get(ReplayTimelineCoverageDiffSeverity.ERROR, 0) > 0,
        has_warnings=by_severity.get(ReplayTimelineCoverageDiffSeverity.WARNING, 0) > 0,
    )


def _diff(
    diff_id: str = "diff-1",
    *,
    baseline_report_id: str = "base-1",
    candidate_report_id: str = "cand-1",
    items: tuple[ReplayTimelineCoverageDiffItem, ...] = (),
    notes: str | None = None,
) -> ReplayTimelineCoverageDiff:
    return ReplayTimelineCoverageDiff(
        diff_id=diff_id,
        baseline_report_id=baseline_report_id,
        candidate_report_id=candidate_report_id,
        baseline_timeline_id="tl-base",
        candidate_timeline_id="tl-cand",
        baseline_replay_plan_id="plan-1",
        candidate_replay_plan_id="plan-1",
        generated_at=_utc(0),
        status=ReplayTimelineCoverageDiffStatus.GENERATED,
        summary=_summary_from_items(items),
        items=items,
        notes=notes,
    )


class TestReplayTimelineCoverageDiffItem:
    def test_valid_minimal_item(self) -> None:
        item = _item()
        assert item.item_id == "item-1"
        assert item.kind is ReplayTimelineCoverageDiffKind.OTHER
        assert item.severity is ReplayTimelineCoverageDiffSeverity.INFO
        assert item.message == "test item"
        assert item.key is None
        assert item.baseline_value is None
        assert item.candidate_value is None
        assert item.numeric_delta is None

    def test_valid_full_item(self) -> None:
        item = ReplayTimelineCoverageDiffItem(
            item_id="item-full",
            kind=ReplayTimelineCoverageDiffKind.KIND_COUNT_CHANGED,
            severity=ReplayTimelineCoverageDiffSeverity.WARNING,
            message="Count changed",
            key="MARK_PRICE",
            baseline_value="5",
            candidate_value="3",
            numeric_delta=-2,
        )
        assert item.numeric_delta == -2
        assert item.key == "MARK_PRICE"

    def test_empty_item_id_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty"):
            _item(item_id="")

    def test_whitespace_item_id_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty"):
            _item(item_id="   ")

    def test_empty_message_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty"):
            _item(message="")

    def test_whitespace_message_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty"):
            _item(message="  ")

    def test_bool_numeric_delta_rejected(self) -> None:
        with pytest.raises(ValidationError, match="strict integer"):
            ReplayTimelineCoverageDiffItem(
                item_id="i-1",
                kind=ReplayTimelineCoverageDiffKind.OTHER,
                severity=ReplayTimelineCoverageDiffSeverity.INFO,
                message="msg",
                numeric_delta=True,  # type: ignore[arg-type]
            )

    def test_string_numeric_delta_rejected(self) -> None:
        with pytest.raises(ValidationError, match="strict integer"):
            ReplayTimelineCoverageDiffItem(
                item_id="i-1",
                kind=ReplayTimelineCoverageDiffKind.OTHER,
                severity=ReplayTimelineCoverageDiffSeverity.INFO,
                message="msg",
                numeric_delta="5",  # type: ignore[arg-type]
            )

    def test_whitespace_key_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty"):
            ReplayTimelineCoverageDiffItem(
                item_id="i-1",
                kind=ReplayTimelineCoverageDiffKind.OTHER,
                severity=ReplayTimelineCoverageDiffSeverity.INFO,
                message="msg",
                key="  ",
            )

    def test_leading_whitespace_baseline_value_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty"):
            ReplayTimelineCoverageDiffItem(
                item_id="i-1",
                kind=ReplayTimelineCoverageDiffKind.OTHER,
                severity=ReplayTimelineCoverageDiffSeverity.INFO,
                message="msg",
                baseline_value=" value",
            )

    def test_frozen(self) -> None:
        item = _item()
        with pytest.raises((AttributeError, ValidationError)):
            item.item_id = "changed"  # type: ignore[misc]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayTimelineCoverageDiffItem(
                item_id="i-1",
                kind=ReplayTimelineCoverageDiffKind.OTHER,
                severity=ReplayTimelineCoverageDiffSeverity.INFO,
                message="msg",
                unexpected="nope",  # type: ignore[call-arg]
            )

    def test_all_kinds_valid(self) -> None:
        for kind in ReplayTimelineCoverageDiffKind:
            item = _item(kind=kind)
            assert item.kind is kind

    def test_all_severities_valid(self) -> None:
        for sev in ReplayTimelineCoverageDiffSeverity:
            item = _item(severity=sev)
            assert item.severity is sev


class TestReplayTimelineCoverageDiffSummary:
    def test_valid_empty_summary(self) -> None:
        s = _empty_summary()
        assert s.total_items == 0
        assert not s.has_errors
        assert not s.has_warnings

    def test_valid_summary_with_counts(self) -> None:
        s = ReplayTimelineCoverageDiffSummary(
            total_items=3,
            item_count_by_kind={
                ReplayTimelineCoverageDiffKind.KIND_COUNT_CHANGED: 1,
                ReplayTimelineCoverageDiffKind.TOTAL_EVENT_COUNT_CHANGED: 2,
            },
            item_count_by_severity={
                ReplayTimelineCoverageDiffSeverity.INFO: 1,
                ReplayTimelineCoverageDiffSeverity.WARNING: 1,
                ReplayTimelineCoverageDiffSeverity.ERROR: 1,
            },
            has_errors=True,
            has_warnings=True,
        )
        assert s.total_items == 3
        assert s.has_errors
        assert s.has_warnings

    def test_kind_count_sum_mismatch_rejected(self) -> None:
        with pytest.raises(ValidationError, match="item_count_by_kind"):
            ReplayTimelineCoverageDiffSummary(
                total_items=2,
                item_count_by_kind={ReplayTimelineCoverageDiffKind.OTHER: 3},
                item_count_by_severity={ReplayTimelineCoverageDiffSeverity.INFO: 2},
                has_errors=False,
                has_warnings=False,
            )

    def test_severity_count_sum_mismatch_rejected(self) -> None:
        with pytest.raises(ValidationError, match="item_count_by_severity"):
            ReplayTimelineCoverageDiffSummary(
                total_items=2,
                item_count_by_kind={ReplayTimelineCoverageDiffKind.OTHER: 2},
                item_count_by_severity={ReplayTimelineCoverageDiffSeverity.INFO: 3},
                has_errors=False,
                has_warnings=False,
            )

    def test_zero_items_non_empty_kind_mapping_rejected(self) -> None:
        with pytest.raises(ValidationError, match="empty when total_items is 0"):
            ReplayTimelineCoverageDiffSummary(
                total_items=0,
                item_count_by_kind={ReplayTimelineCoverageDiffKind.OTHER: 1},
                item_count_by_severity={},
                has_errors=False,
                has_warnings=False,
            )

    def test_has_errors_mismatch_rejected(self) -> None:
        with pytest.raises(ValidationError, match="has_errors"):
            ReplayTimelineCoverageDiffSummary(
                total_items=1,
                item_count_by_kind={ReplayTimelineCoverageDiffKind.OTHER: 1},
                item_count_by_severity={ReplayTimelineCoverageDiffSeverity.INFO: 1},
                has_errors=True,
                has_warnings=False,
            )

    def test_has_warnings_mismatch_rejected(self) -> None:
        with pytest.raises(ValidationError, match="has_warnings"):
            ReplayTimelineCoverageDiffSummary(
                total_items=1,
                item_count_by_kind={ReplayTimelineCoverageDiffKind.OTHER: 1},
                item_count_by_severity={ReplayTimelineCoverageDiffSeverity.WARNING: 1},
                has_errors=False,
                has_warnings=False,
            )

    def test_zero_items_has_errors_true_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayTimelineCoverageDiffSummary(
                total_items=0,
                item_count_by_kind={},
                item_count_by_severity={},
                has_errors=True,
                has_warnings=False,
            )

    def test_bool_total_items_rejected(self) -> None:
        with pytest.raises(ValidationError, match="strict integer"):
            ReplayTimelineCoverageDiffSummary(
                total_items=True,  # type: ignore[arg-type]
                item_count_by_kind={},
                item_count_by_severity={},
                has_errors=False,
                has_warnings=False,
            )


class TestReplayTimelineCoverageDiff:
    def test_valid_diff_no_items(self) -> None:
        d = _diff()
        assert d.diff_id == "diff-1"
        assert d.baseline_report_id == "base-1"
        assert d.candidate_report_id == "cand-1"
        assert d.status is ReplayTimelineCoverageDiffStatus.GENERATED
        assert d.direction is ReplayTimelineCoverageDiffDirection.BASELINE_TO_CANDIDATE
        assert d.items == ()
        assert d.notes is None

    def test_valid_diff_with_items(self) -> None:
        items = (
            _item("i-1", severity=ReplayTimelineCoverageDiffSeverity.WARNING),
            _item("i-2", severity=ReplayTimelineCoverageDiffSeverity.ERROR),
        )
        d = _diff(items=items)
        assert len(d.items) == 2
        assert d.summary.has_errors
        assert d.summary.has_warnings

    def test_same_baseline_candidate_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must differ"):
            _diff(baseline_report_id="same", candidate_report_id="same")

    def test_duplicate_item_ids_rejected(self) -> None:
        items = (_item("same-id"), _item("same-id"))
        with pytest.raises(ValidationError, match="duplicate item_id"):
            _diff(items=items)

    def test_summary_mismatch_total_items_rejected(self) -> None:
        wrong_summary = _empty_summary()
        with pytest.raises(ValidationError, match="total_items"):
            ReplayTimelineCoverageDiff(
                diff_id="d-1",
                baseline_report_id="base-1",
                candidate_report_id="cand-1",
                baseline_timeline_id="tl-base",
                candidate_timeline_id="tl-cand",
                baseline_replay_plan_id="plan-1",
                candidate_replay_plan_id="plan-1",
                generated_at=_utc(0),
                status=ReplayTimelineCoverageDiffStatus.GENERATED,
                summary=wrong_summary,
                items=(_item("i-1"),),
            )

    def test_notes_accepted(self) -> None:
        d = _diff(notes="comparison notes")
        assert d.notes == "comparison notes"

    def test_whitespace_notes_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty"):
            _diff(notes="   ")

    def test_naive_generated_at_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayTimelineCoverageDiff(
                diff_id="d-1",
                baseline_report_id="base-1",
                candidate_report_id="cand-1",
                baseline_timeline_id="tl-base",
                candidate_timeline_id="tl-cand",
                baseline_replay_plan_id="plan-1",
                candidate_replay_plan_id="plan-1",
                generated_at=datetime(2026, 1, 1),  # naive
                status=ReplayTimelineCoverageDiffStatus.GENERATED,
                summary=_empty_summary(),
            )

    def test_frozen(self) -> None:
        d = _diff()
        with pytest.raises((AttributeError, ValidationError)):
            d.diff_id = "changed"  # type: ignore[misc]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReplayTimelineCoverageDiff(
                diff_id="d-1",
                baseline_report_id="base-1",
                candidate_report_id="cand-1",
                baseline_timeline_id="tl-base",
                candidate_timeline_id="tl-cand",
                baseline_replay_plan_id="plan-1",
                candidate_replay_plan_id="plan-1",
                generated_at=_utc(0),
                status=ReplayTimelineCoverageDiffStatus.GENERATED,
                summary=_empty_summary(),
                unexpected="nope",  # type: ignore[call-arg]
            )

    def test_all_statuses_valid(self) -> None:
        for status in ReplayTimelineCoverageDiffStatus:
            d = _diff()
            d = ReplayTimelineCoverageDiff(
                diff_id="d-1",
                baseline_report_id="base-1",
                candidate_report_id="cand-1",
                baseline_timeline_id="tl-base",
                candidate_timeline_id="tl-cand",
                baseline_replay_plan_id="plan-1",
                candidate_replay_plan_id="plan-1",
                generated_at=_utc(0),
                status=status,
                summary=_empty_summary(),
            )
            assert d.status is status

    def test_no_execution_attributes(self) -> None:
        d = _diff()
        assert not hasattr(d, "pnl")
        assert not hasattr(d, "metric_observations")
        assert not hasattr(d, "evaluation_result")
        assert not hasattr(d, "strategy_result")
