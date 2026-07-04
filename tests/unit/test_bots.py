from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.assets import AssetAmount, AssetSymbol
from futures_bot.domain.bots import BotBlueprint, BotInstance
from futures_bot.domain.ids import BotBlueprintId, BotId, BucketId, CohortId, ExperimentId
from futures_bot.domain.modes import CapitalMode, OperationalStatus, ResearchStatus, RunMode


def test_bot_blueprint_accepts_eth_initial_capital() -> None:
    blueprint = BotBlueprint(
        blueprint_id=BotBlueprintId("blueprint-1"),
        bot_family="GAUSS",
        run_mode=RunMode.PAPER_LIVE,
        capital_mode=CapitalMode.SIMULATED,
        initial_capital=AssetAmount(asset="ETH", amount="1"),
    )

    assert blueprint.initial_capital == AssetAmount(asset="ETH", amount="1")


def test_bot_blueprint_has_no_positions_or_pnl_fields() -> None:
    BotBlueprint(
        blueprint_id=BotBlueprintId("blueprint-1"),
        bot_family="GAUSS",
        run_mode=RunMode.PAPER_LIVE,
        capital_mode=CapitalMode.SIMULATED,
        initial_capital=AssetAmount(asset="USDT", amount="1000"),
    )

    assert "positions" not in BotBlueprint.model_fields
    assert "pnl" not in BotBlueprint.model_fields
    assert "ledger_state" not in BotBlueprint.model_fields


def test_retired_bot_can_still_be_operationally_running() -> None:
    bot = BotInstance(
        bot_id=BotId("bot-1"),
        blueprint_id=BotBlueprintId("blueprint-1"),
        experiment_id=ExperimentId("experiment-1"),
        cohort_id=CohortId("cohort-1"),
        bucket_id=BucketId("bucket-1"),
        run_mode=RunMode.PAPER_LIVE,
        capital_mode=CapitalMode.SIMULATED,
        operational_status=OperationalStatus.RUNNING,
        research_status=ResearchStatus.RETIRED,
        capital_asset="BTC",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert bot.can_trade_paper_intents()
    assert bot.capital_asset == AssetSymbol("BTC")


def test_paused_operational_status_cannot_trade() -> None:
    bot = BotInstance(
        bot_id=BotId("bot-1"),
        blueprint_id=BotBlueprintId("blueprint-1"),
        experiment_id=ExperimentId("experiment-1"),
        cohort_id=CohortId("cohort-1"),
        bucket_id=BucketId("bucket-1"),
        run_mode=RunMode.PAPER_LIVE,
        capital_mode=CapitalMode.SIMULATED,
        operational_status=OperationalStatus.PAUSED,
        research_status=ResearchStatus.PROMOTED,
        capital_asset="ETH",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert not bot.can_trade_paper_intents()


def _bot(
    run_mode: RunMode,
    capital_mode: CapitalMode,
    operational_status: OperationalStatus,
) -> BotInstance:
    return BotInstance(
        bot_id=BotId("bot-1"),
        blueprint_id=BotBlueprintId("blueprint-1"),
        experiment_id=ExperimentId("experiment-1"),
        cohort_id=CohortId("cohort-1"),
        bucket_id=BucketId("bucket-1"),
        run_mode=run_mode,
        capital_mode=capital_mode,
        operational_status=operational_status,
        research_status=ResearchStatus.PROMOTED,
        capital_asset="USDT",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_live_real_running_bot_cannot_trade_paper_intents() -> None:
    bot = _bot(RunMode.LIVE, CapitalMode.REAL, OperationalStatus.RUNNING)
    assert not bot.can_trade_paper_intents()


def test_paper_live_with_real_capital_cannot_trade_paper_intents() -> None:
    bot = _bot(RunMode.PAPER_LIVE, CapitalMode.REAL, OperationalStatus.RUNNING)
    assert not bot.can_trade_paper_intents()


def test_paper_live_simulated_safe_mode_cannot_trade_paper_intents() -> None:
    bot = _bot(RunMode.PAPER_LIVE, CapitalMode.SIMULATED, OperationalStatus.SAFE_MODE)
    assert not bot.can_trade_paper_intents()


def test_paper_live_simulated_paused_cannot_trade_paper_intents() -> None:
    bot = _bot(RunMode.PAPER_LIVE, CapitalMode.SIMULATED, OperationalStatus.PAUSED)
    assert not bot.can_trade_paper_intents()


def test_bot_instance_created_at_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        BotInstance(
            bot_id=BotId("bot-1"),
            blueprint_id=BotBlueprintId("blueprint-1"),
            experiment_id=ExperimentId("experiment-1"),
            cohort_id=CohortId("cohort-1"),
            bucket_id=BucketId("bucket-1"),
            run_mode=RunMode.PAPER_LIVE,
            capital_mode=CapitalMode.SIMULATED,
            operational_status=OperationalStatus.RUNNING,
            research_status=ResearchStatus.CANDIDATE,
            capital_asset="USDT",
            created_at=datetime(2026, 1, 1),
        )
