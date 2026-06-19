from __future__ import annotations

import pytest
from pydantic import ValidationError
from tests.unit.replay_decision_market_fixtures import replay_decision_market_fixture

from futures_bot.domain.replay_decisions import (
    ReplayDecisionStackContext,
    build_replay_decision_market_context_reference,
    build_replay_decision_stack_context,
)


def test_valid_decision_stack_context_round_trip_and_reference() -> None:
    fixture = replay_decision_market_fixture()
    context = fixture.decision_context
    reference = build_replay_decision_market_context_reference(context)

    assert ReplayDecisionStackContext.model_validate(context.model_dump()) == context
    assert reference.context_id == context.context_id
    assert reference.frame_projection_id == context.market.frame_projection.projection_id
    assert reference.triggering_observation_id == (
        context.market.frame_projection.triggering_observation_id
    )


def test_context_id_changes_with_dispatch_observation_frame_and_market_timeline() -> None:
    base = replay_decision_market_fixture(price="100")
    changed_dispatch = build_replay_decision_stack_context(
        dispatch_context=base.dispatch_context.model_copy(update={"run_id": "run-2"}),
        event=base.event,
        market=base.decision_context.market,
        evidence=base.decision_context.evidence,
    )
    changed_market = replay_decision_market_fixture(price="101")
    changed_timeline = replay_decision_market_fixture(timeline_id="timeline-2")

    assert changed_dispatch.context_id != base.decision_context.context_id
    assert changed_market.decision_context.context_id != base.decision_context.context_id
    assert changed_timeline.decision_context.context_id != base.decision_context.context_id
    assert changed_market.decision_context.market.frame_projection.frame.frame_id != (
        base.decision_context.market.frame_projection.frame.frame_id
    )
    assert changed_market.decision_context.market.observation_projection.observation != (
        base.decision_context.market.observation_projection.observation
    )


def test_context_rejects_nested_tampering() -> None:
    fixture = replay_decision_market_fixture()
    with pytest.raises(ValidationError, match="event_time"):
        ReplayDecisionStackContext.model_validate(
            fixture.decision_context.model_copy(
                update={
                    "event": fixture.event.model_copy(
                        update={"event_time": fixture.event.event_time.replace(hour=13)}
                    )
                }
            ).model_dump()
        )

    with pytest.raises(ValidationError, match="event_id"):
        ReplayDecisionStackContext.model_validate(
            fixture.decision_context.model_copy(
                update={
                    "market": fixture.decision_context.market.model_copy(
                        update={
                            "observation_projection": (
                                fixture.decision_context.market.observation_projection.model_copy(
                                    update={"event_id": "other-event"}
                                )
                            )
                        }
                    )
                }
            ).model_dump()
        )
