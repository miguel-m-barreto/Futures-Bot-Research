from futures_bot.domain.modes import (
    CapitalMode,
    OperationalStatus,
    ResearchStatus,
    RunMode,
    is_real_execution_mode,
)


def test_retired_research_status_does_not_imply_operational_stop() -> None:
    assert ResearchStatus.RETIRED is not OperationalStatus.PAUSED
    assert ResearchStatus.RETIRED.value == "RETIRED"


def test_real_execution_mode_requires_live_and_real_capital() -> None:
    assert is_real_execution_mode(RunMode.LIVE, CapitalMode.REAL)
    assert not is_real_execution_mode(RunMode.LIVE, CapitalMode.SIMULATED)
    assert not is_real_execution_mode(RunMode.SHADOW, CapitalMode.READ_ONLY_REAL)
