from __future__ import annotations

from typing import Protocol

from futures_bot.domain.execution_capability_gate import (
    ExecutionCapabilityCheck,
    ExecutionCapabilityDecision,
)


class ExecutionCapabilityGatePort(Protocol):
    """Pure interface for deterministic venue capability gate checks."""

    def check(
        self,
        check: ExecutionCapabilityCheck,
    ) -> ExecutionCapabilityDecision:
        """Check whether an order is executable given venue capability constraints."""
        ...
