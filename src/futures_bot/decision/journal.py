from __future__ import annotations

from typing import cast

from futures_bot.domain.replay import _validate_required_text, _validate_strict_int
from futures_bot.domain.replay_decisions import (
    ReplayDecisionOutputEnvelope,
    ReplayDecisionOutputKind,
    decode_replay_decision_output_record,
)
from futures_bot.ports.replay import ReplayEventOutputRecordStorePort


class LocalReplayDecisionJournal:
    """Typed read projection over the generic replay output journal."""

    def __init__(self, output_store: ReplayEventOutputRecordStorePort) -> None:
        self._output_store = output_store

    def decisions_for_run(
        self,
        run_id: str,
    ) -> tuple[ReplayDecisionOutputEnvelope, ...]:
        run_id = _validate_required_text(run_id, "run_id")
        return tuple(
            decode_replay_decision_output_record(record)
            for record in self._output_store.list_for_run(run_id)
            if _is_replay_decision_output_kind(record.output_kind)
        )

    def decisions_for_event(
        self,
        run_id: str,
        event_order_index: int,
    ) -> tuple[ReplayDecisionOutputEnvelope, ...]:
        run_id = _validate_required_text(run_id, "run_id")
        event_order_index = cast(
            int,
            _validate_strict_int(
                event_order_index,
                "event_order_index",
            ),
        )
        if event_order_index < 0:
            raise ValueError("event_order_index must be >= 0")
        return tuple(
            decode_replay_decision_output_record(record)
            for record in self._output_store.list_for_event(run_id, event_order_index)
            if _is_replay_decision_output_kind(record.output_kind)
        )


def _is_replay_decision_output_kind(output_kind: str) -> bool:
    return output_kind in {kind.value for kind in ReplayDecisionOutputKind}
