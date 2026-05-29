from __future__ import annotations

from enum import StrEnum


class RunMode(StrEnum):
    REPLAY = "REPLAY"
    PAPER_LIVE = "PAPER_LIVE"
    SHADOW = "SHADOW"
    LIVE = "LIVE"


class CapitalMode(StrEnum):
    SIMULATED = "SIMULATED"
    READ_ONLY_REAL = "READ_ONLY_REAL"
    REAL = "REAL"


class OperationalStatus(StrEnum):
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    SAFE_MODE = "SAFE_MODE"
    BALANCE_DEPLETED = "BALANCE_DEPLETED"


class ResearchStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    PROMOTED = "PROMOTED"
    DEMOTED = "DEMOTED"
    RETIRED = "RETIRED"
    ARCHIVED = "ARCHIVED"


def is_real_execution_mode(run_mode: RunMode, capital_mode: CapitalMode) -> bool:
    return run_mode is RunMode.LIVE and capital_mode is CapitalMode.REAL
