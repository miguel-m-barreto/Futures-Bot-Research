from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.replay import (
    ReplayTimelineCoverageDiff,
    ReplayTimelineCoverageDiffItem,
    ReplayTimelineCoverageDiffKind,
    ReplayTimelineCoverageDiffSeverity,
    ReplayTimelineCoverageDiffStatus,
    ReplayTimelineCoverageDiffSummary,
)
from futures_bot.infrastructure.replay.in_memory import (
    InMemoryReplayTimelineCoverageDiffStore,
)
from futures_bot.ports.replay import ReplayTimelineCoverageDiffStorePort


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _empty_summary() -> ReplayTimelineCoverageDiffSummary:
    return ReplayTimelineCoverageDiffSummary(
        total_items=0,
        item_count_by_kind={},
        item_count_by_severity={},
        has_errors=False,
        has_warnings=False,
    )


def _diff(  # noqa: PLR0913
    diff_id: str = "diff-1",
    *,
    baseline_report_id: str = "base-1",
    candidate_report_id: str = "cand-1",
    baseline_replay_plan_id: str = "plan-1",
    candidate_replay_plan_id: str = "plan-1",
    generated_at: datetime | None = None,
) -> ReplayTimelineCoverageDiff:
    return ReplayTimelineCoverageDiff(
        diff_id=diff_id,
        baseline_report_id=baseline_report_id,
        candidate_report_id=candidate_report_id,
        baseline_timeline_id="tl-base",
        candidate_timeline_id="tl-cand",
        baseline_replay_plan_id=baseline_replay_plan_id,
        candidate_replay_plan_id=candidate_replay_plan_id,
        generated_at=generated_at or _utc(0),
        status=ReplayTimelineCoverageDiffStatus.GENERATED,
        summary=_empty_summary(),
    )


class TestInMemoryReplayTimelineCoverageDiffStoreConformance:
    def test_conforms_to_port(self) -> None:
        _: ReplayTimelineCoverageDiffStorePort = InMemoryReplayTimelineCoverageDiffStore()


class TestInMemoryReplayTimelineCoverageDiffStore:
    def test_save_and_load_round_trip(self) -> None:
        store = InMemoryReplayTimelineCoverageDiffStore()
        d = _diff()
        store.save(d)
        loaded = store.load("diff-1")
        assert loaded == d

    def test_load_returns_none_for_missing(self) -> None:
        store = InMemoryReplayTimelineCoverageDiffStore()
        assert store.load("nonexistent") is None

    def test_idempotent_save_accepted(self) -> None:
        store = InMemoryReplayTimelineCoverageDiffStore()
        d = _diff()
        store.save(d)
        store.save(d)
        assert store.load("diff-1") == d

    def test_conflict_rejected(self) -> None:
        store = InMemoryReplayTimelineCoverageDiffStore()
        d1 = _diff("d-1", baseline_report_id="base-A")
        d2 = _diff("d-1", baseline_report_id="base-B")
        store.save(d1)
        with pytest.raises(ValueError, match="conflict"):
            store.save(d2)

    def test_list_all_deterministic_order(self) -> None:
        store = InMemoryReplayTimelineCoverageDiffStore()
        db = _diff("d-b", generated_at=_utc(2))
        da = _diff("d-a", generated_at=_utc(1))
        store.save(db)
        store.save(da)
        results = store.list_all()
        assert [d.diff_id for d in results] == ["d-a", "d-b"]

    def test_list_all_same_generated_at_sorted_by_id(self) -> None:
        store = InMemoryReplayTimelineCoverageDiffStore()
        dz = _diff("d-z", generated_at=_utc(1))
        da = _diff("d-a", generated_at=_utc(1))
        store.save(dz)
        store.save(da)
        results = store.list_all()
        assert [d.diff_id for d in results] == ["d-a", "d-z"]

    def test_list_for_report_includes_baseline_match(self) -> None:
        store = InMemoryReplayTimelineCoverageDiffStore()
        d = _diff("d-1", baseline_report_id="base-X", candidate_report_id="cand-X")
        store.save(d)
        results = store.list_for_report("base-X")
        assert len(results) == 1
        assert results[0].diff_id == "d-1"

    def test_list_for_report_includes_candidate_match(self) -> None:
        store = InMemoryReplayTimelineCoverageDiffStore()
        d = _diff("d-1", baseline_report_id="base-X", candidate_report_id="cand-X")
        store.save(d)
        results = store.list_for_report("cand-X")
        assert len(results) == 1

    def test_list_for_report_filters_unrelated(self) -> None:
        store = InMemoryReplayTimelineCoverageDiffStore()
        d1 = _diff("d-1", baseline_report_id="base-A", candidate_report_id="cand-A")
        d2 = _diff("d-2", baseline_report_id="base-B", candidate_report_id="cand-B")
        store.save(d1)
        store.save(d2)
        results = store.list_for_report("base-A")
        assert len(results) == 1
        assert results[0].diff_id == "d-1"

    def test_list_for_report_deterministic_order(self) -> None:
        store = InMemoryReplayTimelineCoverageDiffStore()
        d2 = _diff("d-b", baseline_report_id="rep-X", generated_at=_utc(2))
        d1 = _diff("d-a", baseline_report_id="rep-X", generated_at=_utc(1))
        store.save(d2)
        store.save(d1)
        results = store.list_for_report("rep-X")
        assert [d.diff_id for d in results] == ["d-a", "d-b"]

    def test_list_for_unknown_report_returns_empty(self) -> None:
        store = InMemoryReplayTimelineCoverageDiffStore()
        assert store.list_for_report("no-such-report") == ()

    def test_list_for_replay_plan_includes_baseline_match(self) -> None:
        store = InMemoryReplayTimelineCoverageDiffStore()
        d = _diff(baseline_replay_plan_id="plan-A", candidate_replay_plan_id="plan-B")
        store.save(d)
        results = store.list_for_replay_plan("plan-A")
        assert len(results) == 1

    def test_list_for_replay_plan_includes_candidate_match(self) -> None:
        store = InMemoryReplayTimelineCoverageDiffStore()
        d = _diff(baseline_replay_plan_id="plan-A", candidate_replay_plan_id="plan-B")
        store.save(d)
        results = store.list_for_replay_plan("plan-B")
        assert len(results) == 1

    def test_list_for_replay_plan_filters_unrelated(self) -> None:
        store = InMemoryReplayTimelineCoverageDiffStore()
        d1 = _diff("d-1", baseline_replay_plan_id="plan-X", candidate_replay_plan_id="plan-X")
        d2 = _diff("d-2", baseline_replay_plan_id="plan-Y", candidate_replay_plan_id="plan-Y")
        store.save(d1)
        store.save(d2)
        results = store.list_for_replay_plan("plan-X")
        assert len(results) == 1

    def test_list_for_unknown_replay_plan_returns_empty(self) -> None:
        store = InMemoryReplayTimelineCoverageDiffStore()
        assert store.list_for_replay_plan("no-such-plan") == ()

    def test_model_copy_invalid_summary_rejected(self) -> None:
        store = InMemoryReplayTimelineCoverageDiffStore()
        d = _diff("d-base")
        store.save(d)
        # model_copy bypasses validators; create a summary claiming ERROR items
        # when the diff has zero actual items
        valid_summary = _empty_summary()
        lying_summary = valid_summary.model_copy(
            update={"item_count_by_severity": {ReplayTimelineCoverageDiffSeverity.ERROR: 1}}
        )
        tampered = d.model_copy(update={"diff_id": "d-tampered", "summary": lying_summary})
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)

    def test_model_copy_duplicate_item_ids_rejected(self) -> None:
        store = InMemoryReplayTimelineCoverageDiffStore()
        item = ReplayTimelineCoverageDiffItem(
            item_id="i-1",
            kind=ReplayTimelineCoverageDiffKind.OTHER,
            severity=ReplayTimelineCoverageDiffSeverity.INFO,
            message="msg",
        )
        valid_items = (item,)
        summary = ReplayTimelineCoverageDiffSummary(
            total_items=1,
            item_count_by_kind={ReplayTimelineCoverageDiffKind.OTHER: 1},
            item_count_by_severity={ReplayTimelineCoverageDiffSeverity.INFO: 1},
            has_errors=False,
            has_warnings=False,
        )
        d = ReplayTimelineCoverageDiff(
            diff_id="d-valid",
            baseline_report_id="base-1",
            candidate_report_id="cand-1",
            baseline_timeline_id="tl-base",
            candidate_timeline_id="tl-cand",
            baseline_replay_plan_id="plan-1",
            candidate_replay_plan_id="plan-1",
            generated_at=_utc(0),
            status=ReplayTimelineCoverageDiffStatus.GENERATED,
            summary=summary,
            items=valid_items,
        )
        store.save(d)
        tampered = d.model_copy(update={"diff_id": "d-dup", "items": (item, item)})
        with pytest.raises((ValidationError, ValueError)):
            store.save(tampered)
