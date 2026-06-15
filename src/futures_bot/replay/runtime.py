"""Local deterministic replay runtime stepper.

Metadata-only runtime foundation: no strategy execution, no order execution,
and no ledger mutation.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from futures_bot.domain.replay import (
    ReplayArtifactFingerprintStatus,
    ReplayArtifactKind,
    ReplayEventDispatchReceipt,
    ReplayRunManifestStatus,
    ReplayRunState,
    ReplayRunStatus,
    ReplayRunStepResult,
    ReplayTimeline,
    ReplayTimelineEvent,
    ReplayTimelineStatus,
    build_replay_event_dispatch_receipt_id,
)
from futures_bot.ports.replay import (
    ReplayArtifactFingerprintStorePort,
    ReplayEventDispatchReceiptStorePort,
    ReplayRunManifestStorePort,
    ReplayRunStateStorePort,
    ReplayTimelineStorePort,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LocalDeterministicReplayRuntime:
    """Bounded deterministic runtime stepper for replay timelines."""

    def __init__(  # noqa: PLR0913 - explicit runtime dependency boundary
        self,
        *,
        manifest_store: ReplayRunManifestStorePort,
        timeline_store: ReplayTimelineStorePort,
        fingerprint_store: ReplayArtifactFingerprintStorePort,
        run_store: ReplayRunStateStorePort,
        receipt_store: ReplayEventDispatchReceiptStorePort,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._manifest_store = manifest_store
        self._timeline_store = timeline_store
        self._fingerprint_store = fingerprint_store
        self._run_store = run_store
        self._receipt_store = receipt_store
        self._now: Callable[[], datetime] = now if now is not None else _utcnow

    def create_run(  # noqa: PLR0912 - explicit binding validation matrix
        self,
        run_id: str,
        manifest_id: str,
        timeline_id: str,
        timeline_fingerprint_id: str,
    ) -> ReplayRunState:
        """Create a runtime run from a PLANNED manifest and exact timeline fingerprint."""
        existing = self._run_store.load(run_id)
        if existing is not None:
            _require_existing_run_binding(
                existing,
                manifest_id,
                timeline_id,
                timeline_fingerprint_id,
            )
            return existing

        manifest = self._manifest_store.load(manifest_id)
        if manifest is None:
            raise ValueError(f"replay run manifest not found: {manifest_id!r}")
        if manifest.status is not ReplayRunManifestStatus.PLANNED:
            raise ValueError(
                "replay run manifest must be PLANNED, "
                f"got {manifest.status.value!r}"
            )

        timeline = self._timeline_store.load(timeline_id)
        if timeline is None:
            raise ValueError(f"replay timeline not found: {timeline_id!r}")
        if timeline.status is not ReplayTimelineStatus.BUILT:
            raise ValueError(
                f"replay timeline must be BUILT, got {timeline.status.value!r}"
            )
        if timeline.replay_plan_id != manifest.replay_plan_id:
            raise ValueError("timeline replay_plan_id must match manifest replay_plan_id")
        if timeline_fingerprint_id not in manifest.fingerprint_ids:
            raise ValueError(
                "timeline_fingerprint_id must be present in manifest fingerprint_ids"
            )

        fingerprint = self._fingerprint_store.load(timeline_fingerprint_id)
        if fingerprint is None:
            raise ValueError(
                f"replay artifact fingerprint not found: {timeline_fingerprint_id!r}"
            )
        if fingerprint.status is not ReplayArtifactFingerprintStatus.GENERATED:
            raise ValueError(
                "timeline fingerprint must be GENERATED, "
                f"got {fingerprint.status.value!r}"
            )
        if fingerprint.artifact_kind is not ReplayArtifactKind.TIMELINE:
            raise ValueError("timeline fingerprint artifact_kind must be TIMELINE")
        if fingerprint.artifact_id != timeline_id:
            raise ValueError("timeline fingerprint artifact_id must match timeline_id")
        if fingerprint.replay_plan_id != manifest.replay_plan_id:
            raise ValueError(
                "timeline fingerprint replay_plan_id must match manifest replay_plan_id"
            )
        if fingerprint.generated_at > manifest.created_at:
            raise ValueError(
                "timeline fingerprint generated_at must not be after manifest created_at"
            )
        if timeline.created_at > fingerprint.generated_at:
            raise ValueError(
                "timeline created_at must not be after timeline fingerprint generated_at"
            )

        now = self._now()
        if manifest.created_at > now:
            raise ValueError("manifest created_at must not be after replay run created_at")
        state = ReplayRunState(
            run_id=run_id,
            manifest_id=manifest.manifest_id,
            replay_plan_id=manifest.replay_plan_id,
            timeline_id=timeline.timeline_id,
            timeline_fingerprint_id=fingerprint.fingerprint_id,
            created_at=now,
            updated_at=now,
            status=ReplayRunStatus.CREATED,
            revision=0,
            total_event_count=len(timeline.events),
            next_event_index=0,
            processed_event_count=0,
        )
        self._run_store.create(state)
        return state

    def start_run(self, run_id: str) -> ReplayRunStepResult:
        """Start a CREATED run, completing immediately when no events exist."""
        state = self._load_state(run_id)
        if state.status is not ReplayRunStatus.CREATED:
            raise ValueError(f"only CREATED runs can start, got {state.status.value!r}")
        now = self._now()
        _require_non_regressing_runtime_time(now, state)
        status = (
            ReplayRunStatus.COMPLETED
            if state.total_event_count == 0
            else ReplayRunStatus.RUNNING
        )
        replacement = _validated_state_copy(
            state,
            {
                "updated_at": now,
                "started_at": now,
                "completed_at": now if status is ReplayRunStatus.COMPLETED else None,
                "status": status,
                "revision": state.revision + 1,
            },
        )
        result = _step_result(state, replacement)
        self._run_store.replace(replacement, expected_revision=state.revision)
        return result

    def step_run(self, run_id: str, max_events: int = 1) -> ReplayRunStepResult:
        """Process at most max_events timeline events from the run's next index."""
        _validate_max_events(max_events)
        state = self._load_state(run_id)
        if state.status is not ReplayRunStatus.RUNNING:
            raise ValueError(f"only RUNNING runs can step, got {state.status.value!r}")
        timeline = self._load_bound_timeline(state)
        remaining = state.total_event_count - state.next_event_index
        if remaining <= 0:
            raise ValueError("RUNNING replay run has no remaining events to process")

        count = min(max_events, remaining)
        events = timeline.events[state.next_event_index : state.next_event_index + count]
        receipts = tuple(_dispatch_receipt(state, event) for event in events)
        last_event = events[-1]
        next_event_index = state.next_event_index + count
        completed = next_event_index == state.total_event_count
        now = self._now()
        _require_non_regressing_runtime_time(now, state)

        replacement = _validated_state_copy(
            state,
            {
                "updated_at": now,
                "completed_at": now if completed else None,
                "status": (
                    ReplayRunStatus.COMPLETED
                    if completed
                    else ReplayRunStatus.RUNNING
                ),
                "revision": state.revision + 1,
                "next_event_index": next_event_index,
                "processed_event_count": next_event_index,
                "last_processed_event_id": last_event.event_id,
            },
        )
        result = _step_result(state, replacement, receipts)
        for receipt in receipts:
            self._receipt_store.save(receipt)
        self._run_store.replace(replacement, expected_revision=state.revision)
        return result

    def pause_run(self, run_id: str) -> ReplayRunStepResult:
        """Pause a RUNNING replay run."""
        state = self._load_state(run_id)
        if state.status is not ReplayRunStatus.RUNNING:
            raise ValueError(f"only RUNNING runs can pause, got {state.status.value!r}")
        now = self._now()
        _require_non_regressing_runtime_time(now, state)
        replacement = _validated_state_copy(
            state,
            {
                "updated_at": now,
                "paused_at": now,
                "status": ReplayRunStatus.PAUSED,
                "revision": state.revision + 1,
            },
        )
        result = _step_result(state, replacement)
        self._run_store.replace(replacement, expected_revision=state.revision)
        return result

    def resume_run(self, run_id: str) -> ReplayRunStepResult:
        """Resume a PAUSED replay run."""
        state = self._load_state(run_id)
        if state.status is not ReplayRunStatus.PAUSED:
            raise ValueError(f"only PAUSED runs can resume, got {state.status.value!r}")
        now = self._now()
        _require_non_regressing_runtime_time(now, state)
        replacement = _validated_state_copy(
            state,
            {
                "updated_at": now,
                "paused_at": None,
                "status": ReplayRunStatus.RUNNING,
                "revision": state.revision + 1,
            },
        )
        result = _step_result(state, replacement)
        self._run_store.replace(replacement, expected_revision=state.revision)
        return result

    def load_run(self, run_id: str) -> ReplayRunState | None:
        """Return replay runtime state by run_id, or None."""
        return self._run_store.load(run_id)

    def runs_for_replay_plan(self, replay_plan_id: str) -> tuple[ReplayRunState, ...]:
        """Return runtime runs for replay_plan_id."""
        return self._run_store.list_for_replay_plan(replay_plan_id)

    def receipts_for_run(self, run_id: str) -> tuple[ReplayEventDispatchReceipt, ...]:
        """Return dispatch receipts for run_id."""
        return self._receipt_store.list_for_run(run_id)

    def _load_state(self, run_id: str) -> ReplayRunState:
        state = self._run_store.load(run_id)
        if state is None:
            raise ValueError(f"replay run state not found: {run_id!r}")
        return state

    def _load_bound_timeline(self, state: ReplayRunState) -> ReplayTimeline:
        timeline = self._timeline_store.load(state.timeline_id)
        if timeline is None:
            raise ValueError(f"bound replay timeline not found: {state.timeline_id!r}")
        if timeline.status is not ReplayTimelineStatus.BUILT:
            raise ValueError(
                f"bound replay timeline must be BUILT, got {timeline.status.value!r}"
            )
        if timeline.timeline_id != state.timeline_id:
            raise ValueError("loaded replay timeline id does not match run state")
        if timeline.replay_plan_id != state.replay_plan_id:
            raise ValueError("bound replay timeline replay_plan_id does not match run state")
        if len(timeline.events) != state.total_event_count:
            raise ValueError("bound replay timeline event count does not match run state")
        if state.next_event_index > 0:
            previous_event = timeline.events[state.next_event_index - 1]
            if state.last_processed_event_id != previous_event.event_id:
                raise ValueError(
                    "last_processed_event_id must match the bound timeline "
                    "event before next_event_index"
                )
        for position, event in enumerate(timeline.events):
            if event.order_index != position:
                raise ValueError("timeline event order_index must equal tuple position")
        return timeline


def _require_existing_run_binding(
    existing: ReplayRunState,
    manifest_id: str,
    timeline_id: str,
    timeline_fingerprint_id: str,
) -> None:
    if (
        existing.manifest_id != manifest_id
        or existing.timeline_id != timeline_id
        or existing.timeline_fingerprint_id != timeline_fingerprint_id
    ):
        raise ValueError("replay run_id already exists with a conflicting binding")


def _require_non_regressing_runtime_time(
    captured_now: datetime,
    state: ReplayRunState,
) -> None:
    if captured_now < state.updated_at:
        raise ValueError("runtime clock regression: captured time is before state updated_at")


def _validated_state_copy(
    state: ReplayRunState,
    update: dict[str, object],
) -> ReplayRunState:
    return ReplayRunState.model_validate(state.model_copy(update=update).model_dump())


def _validate_max_events(max_events: object) -> None:
    if isinstance(max_events, bool) or not isinstance(max_events, int):
        raise ValueError("max_events must be a strict positive integer")
    if max_events <= 0:
        raise ValueError("max_events must be > 0")


def _dispatch_receipt(
    state: ReplayRunState,
    event: ReplayTimelineEvent,
) -> ReplayEventDispatchReceipt:
    return ReplayEventDispatchReceipt(
        receipt_id=build_replay_event_dispatch_receipt_id(
            state.run_id,
            event.order_index,
            event.event_id,
        ),
        run_id=state.run_id,
        manifest_id=state.manifest_id,
        replay_plan_id=state.replay_plan_id,
        timeline_id=state.timeline_id,
        timeline_fingerprint_id=state.timeline_fingerprint_id,
        event_id=event.event_id,
        event_order_index=event.order_index,
        event_time=event.event_time,
        event_kind=event.kind,
    )


def _step_result(
    previous: ReplayRunState,
    current: ReplayRunState,
    receipts: tuple[ReplayEventDispatchReceipt, ...] = (),
) -> ReplayRunStepResult:
    return ReplayRunStepResult(
        run_id=current.run_id,
        previous_status=previous.status,
        current_status=current.status,
        previous_revision=previous.revision,
        current_revision=current.revision,
        previous_next_event_index=previous.next_event_index,
        previous_processed_event_count=previous.processed_event_count,
        processed_receipts=receipts,
        next_event_index=current.next_event_index,
        processed_event_count=current.processed_event_count,
        total_event_count=current.total_event_count,
        completed=current.status is ReplayRunStatus.COMPLETED,
    )
