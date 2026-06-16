from __future__ import annotations

from typing import Protocol

from futures_bot.domain.decisions import (
    DecisionIntent,
    DecisionSourceKind,
    NoTradeDecision,
)
from futures_bot.domain.ids import BotId
from futures_bot.domain.replay import (
    ReplayDispatchContext,
    ReplayInputKind,
    ReplayTimelineEvent,
)

type DecisionStackOutput = DecisionIntent | NoTradeDecision


class DecisionStackPort(Protocol):
    """Synchronous deterministic DecisionStack boundary for replay dispatch."""

    @property
    def stack_id(self) -> str:
        """Stable DecisionStack identity."""
        ...

    @property
    def stack_version(self) -> str:
        """Stable DecisionStack implementation/configuration version."""
        ...

    @property
    def bot_id(self) -> BotId:
        """Bot identity that owns emitted decisions."""
        ...

    @property
    def source_kind(self) -> DecisionSourceKind:
        """Decision source type used by emitted decisions."""
        ...

    @property
    def supported_event_kinds(self) -> tuple[ReplayInputKind, ...]:
        """Replay event kinds this stack can decide on."""
        ...

    def decide(
        self,
        context: ReplayDispatchContext,
        event: ReplayTimelineEvent,
    ) -> tuple[DecisionStackOutput, ...]:
        """Return one or more explicit deterministic decision outcomes."""
        ...
