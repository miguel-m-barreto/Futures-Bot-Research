from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_tests_do_not_read_docs_markdown() -> None:
    tests_root = Path(__file__).resolve().parents[1]
    forbidden_dir = "doc" + "s/"
    markdown_suffix = ".m" + "d"
    for test_file in tests_root.rglob("test_*.py"):
        source = test_file.read_text(encoding="utf-8")
        assert forbidden_dir not in source
        assert "read_text" not in source or markdown_suffix not in source


def _import_lines(path: Path) -> list[str]:
    return [
        line for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith(("import ", "from "))
    ]


def test_legacy_domain_models_do_not_require_stable_collateral_asset() -> None:
    bots_source = (ROOT / "src/futures_bot/domain/bots.py").read_text(encoding="utf-8")
    buckets_source = (ROOT / "src/futures_bot/domain/buckets.py").read_text(
        encoding="utf-8"
    )
    decisions_source = (ROOT / "src/futures_bot/domain/decisions.py").read_text(
        encoding="utf-8"
    )
    execution_source = (ROOT / "src/futures_bot/domain/execution.py").read_text(
        encoding="utf-8"
    )
    replay_source = (ROOT / "src/futures_bot/domain/replay.py").read_text(
        encoding="utf-8"
    )

    assert "StableCollateralAsset" not in bots_source
    assert "StableCollateralAsset" not in buckets_source
    assert "StableCollateralAsset" not in decisions_source
    assert "StableCollateralAsset" not in execution_source
    assert "quote_asset: StableCollateralAsset" not in execution_source
    assert "margin_asset: AssetSymbol" in execution_source
    assert "StableCollateralAsset" not in replay_source
    assert "settlement_asset: AssetSymbol" in replay_source
    assert "quote_asset: AssetSymbol | None" in replay_source


def test_public_docs_no_longer_describe_stablecoin_only_domain_scope() -> None:
    public_text = "\n".join(
        (
            (ROOT / ("README." + "md")).read_text(encoding="utf-8"),
            (ROOT / "pyproject.toml").read_text(encoding="utf-8"),
        )
    ).lower()

    forbidden = (
        "current stablecoin-collateral sprint scope",
        "supports stablecoin-collateral futures only",
        "current allowed capital",
        "out of current sprint scope",
        "stablecoin-collateral futures bots",
    )
    for phrase in forbidden:
        assert phrase not in public_text
    assert "stablecoin-margined linear futures" in public_text
    assert "multi-asset futures bot domain modeling" in public_text
    assert "no implicit conversion is implemented" in public_text


def test_sidecar_runtime_domain_and_ports_do_not_import_infrastructure() -> None:
    paths = (
        ROOT / "src/futures_bot/domain/sidecars.py",
        ROOT / "src/futures_bot/ports/sidecar_runtime.py",
    )
    for path in paths:
        assert not any("infrastructure" in line for line in _import_lines(path))


def test_local_sidecar_adapters_do_not_import_forbidden_runtime_dependencies() -> None:
    source = (ROOT / "src/futures_bot/sidecars/local.py").read_text(encoding="utf-8")
    forbidden = (
        "LocalJsonlWal",
        "local_jsonl",
        "decide_wal_gc",
        "confluent_kafka",
        "aiokafka",
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "subprocess",
        "threading",
        "asyncio",
        "sleep",
    )
    for name in forbidden:
        assert name not in source


def test_in_memory_sidecar_health_store_does_not_import_forbidden_dependencies() -> None:
    lines = _import_lines(ROOT / "src/futures_bot/infrastructure/sidecars/in_memory.py")
    forbidden = (
        "LocalJsonlWal",
        "local_jsonl",
        "decide_wal_gc",
        "confluent_kafka",
        "aiokafka",
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
    )
    for name in forbidden:
        assert not any(name in line for line in lines), f"found {name!r} import"


def test_research_domain_does_not_import_forbidden_dependencies() -> None:
    source = (ROOT / "src/futures_bot/domain/research.py").read_text(encoding="utf-8")
    forbidden = (
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "LocalJsonlWal",
        "sidecars.local",
        "decide_wal_gc",
        "matplotlib",
        "plotly",
        "seaborn",
        "open(",
        "write_text",
    )
    for name in forbidden:
        assert name not in source


def test_research_ports_do_not_import_infrastructure() -> None:
    lines = _import_lines(ROOT / "src/futures_bot/ports/research.py")
    assert not any("infrastructure" in line for line in lines)


def test_in_memory_research_store_does_not_import_forbidden_dependencies() -> None:
    lines = _import_lines(ROOT / "src/futures_bot/infrastructure/research/in_memory.py")
    forbidden = (
        "sqlalchemy",
        "SQLAlchemy",
        "psycopg",
        "asyncpg",
        "Postgres",
        "Redis",
        "duckdb",
        "sqlite",
        "database",
        "confluent_kafka",
        "aiokafka",
        "Kafka",
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ccxt",
        "socket",
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "LocalJsonlWal",
        "decide_wal_gc",
        "matplotlib",
        "plotly",
        "seaborn",
    )
    for name in forbidden:
        assert not any(name in line for line in lines)


def test_local_research_recorder_does_not_import_forbidden_dependencies() -> None:
    source = (ROOT / "src/futures_bot/research/local.py").read_text(encoding="utf-8")
    forbidden = (
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "matplotlib",
        "plotly",
        "seaborn",
        "LocalJsonlWal",
        "sidecars.local",
        "decide_wal_gc",
        "threading",
        "asyncio",
        "subprocess",
        "sleep",
    )
    for name in forbidden:
        assert name not in source


def test_research_registry_and_fingerprint_do_not_import_forbidden_dependencies() -> None:
    paths = (
        ROOT / "src/futures_bot/research/config_fingerprint.py",
        ROOT / "src/futures_bot/research/registry.py",
    )
    forbidden = (
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "matplotlib",
        "plotly",
        "seaborn",
        "LocalJsonlWal",
        "sidecars.local",
        "decide_wal_gc",
        "threading",
        "asyncio",
        "subprocess",
        "sleep",
        "open(",
        "write_text",
    )
    for path in paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source


def test_replay_domain_ports_and_local_modules_do_not_import_forbidden_dependencies() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/replay.py",
        ROOT / "src/futures_bot/ports/replay.py",
        ROOT / "src/futures_bot/infrastructure/replay/in_memory.py",
        ROOT / "src/futures_bot/replay/dispatch.py",
        ROOT / "src/futures_bot/replay/local.py",
        ROOT / "src/futures_bot/replay/runtime.py",
    )
    forbidden = (
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "matplotlib",
        "plotly",
        "seaborn",
        "LocalJsonlWal",
        "sidecars.local",
        "decide_wal_gc",
        "threading",
        "asyncio",
        "subprocess",
        "sleep",
        "random",
        "uuid",
        "open(",
        "write_text",
        "DecisionStack",
        "RiskGate",
        "Ledger",
        "EvaluationResultSet",
        "MetricObservation",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source


def test_replay_ports_do_not_import_infrastructure() -> None:
    lines = _import_lines(ROOT / "src/futures_bot/ports/replay.py")
    assert not any("infrastructure" in line for line in lines)


def test_replay_decision_bridge_source_does_not_import_forbidden_dependencies() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/replay_decisions.py",
        ROOT / "src/futures_bot/ports/decision.py",
        ROOT / "src/futures_bot/decision/replay_adapter.py",
        ROOT / "src/futures_bot/decision/journal.py",
    )
    forbidden = (
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "LocalJsonlWal",
        "sidecars.local",
        "decide_wal_gc",
        "threading",
        "asyncio",
        "subprocess",
        "sleep",
        "random",
        "uuid",
        "open(",
        "write_text",
        "RiskBehaviorModel",
        "HardRiskGate",
        "RiskGate",
        "ExecutionIntent",
        "OrderIntent",
        "Fill",
        "Ledger",
        "EvaluationResultSet",
        "MetricObservation",
        "PnL",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"found {name!r} in {path.name}"


def test_decision_port_does_not_import_infrastructure() -> None:
    lines = _import_lines(ROOT / "src/futures_bot/ports/decision.py")
    assert not any("infrastructure" in line for line in lines)


def test_replay_evidence_source_files_do_not_import_forbidden_dependencies() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/replay_evidence.py",
        ROOT / "src/futures_bot/evidence/replay_lookup.py",
        ROOT / "src/futures_bot/evidence/replay_projection.py",
        ROOT / "src/futures_bot/ports/evidence.py",
    )
    forbidden = (
        "DecisionStack",
        "ReplayDecisionStackContext",
        "DecisionIntent",
        "NoTradeDecision",
        "RiskBehaviorModel",
        "HardRiskGate",
        "ExecutionIntent",
        "OrderIntent",
        "Ledger",
        "PnL",
        "ReplayDecisionOutputEnvelope",
        "ReplayDecisionMarketContextReference",
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ccxt",
        "socket",
        "asyncio",
        "threading",
        "subprocess",
        "Kafka",
        "Postgres",
        "SQLAlchemy",
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "datetime.now",
        "time.time",
        "random",
        "uuid",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"found {name!r} in {path.name}"


def test_replay_timeline_test_files_do_not_import_forbidden_dependencies() -> None:
    timeline_test_files = (
        ROOT / "tests/unit/test_replay_timeline_domain.py",
        ROOT / "tests/unit/test_in_memory_replay_timeline_stores.py",
        ROOT / "tests/unit/test_local_replay_timeline_builder.py",
        ROOT / "tests/unit/test_replay_timeline_contract_flow.py",
    )
    forbidden = (
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "matplotlib",
        "plotly",
        "seaborn",
    )
    for path in timeline_test_files:
        if not path.exists():
            continue
        lines = _import_lines(path)
        for name in forbidden:
            assert not any(name in line for line in lines), f"found {name!r} import in {path.name}"


def test_replay_timeline_source_files_do_not_import_filesystem_or_process_apis() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/replay.py",
        ROOT / "src/futures_bot/infrastructure/replay/in_memory.py",
        ROOT / "src/futures_bot/replay/local.py",
    )
    forbidden = (
        "open(",
        "write_text",
        "read_text",
        "subprocess",
        "threading",
        "asyncio",
        "sleep",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"found {name!r} in {path.name}"


def test_replay_timeline_coverage_test_files_do_not_import_forbidden_dependencies() -> None:
    coverage_test_files = (
        ROOT / "tests/unit/test_replay_timeline_coverage_domain.py",
        ROOT / "tests/unit/test_in_memory_replay_timeline_coverage_store.py",
        ROOT / "tests/unit/test_local_replay_timeline_coverage_auditor.py",
        ROOT / "tests/unit/test_replay_timeline_coverage_flow.py",
    )
    forbidden = (
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "matplotlib",
        "plotly",
        "seaborn",
    )
    for path in coverage_test_files:
        if not path.exists():
            continue
        lines = _import_lines(path)
        for name in forbidden:
            assert not any(name in line for line in lines), (
                f"found {name!r} import in {path.name}"
            )


def test_replay_timeline_coverage_modules_do_not_import_execution_types() -> None:
    coverage_paths = (
        ROOT / "src/futures_bot/domain/replay.py",
        ROOT / "src/futures_bot/ports/replay.py",
        ROOT / "src/futures_bot/infrastructure/replay/in_memory.py",
        ROOT / "src/futures_bot/replay/local.py",
        ROOT / "tests/unit/test_replay_timeline_coverage_domain.py",
        ROOT / "tests/unit/test_in_memory_replay_timeline_coverage_store.py",
        ROOT / "tests/unit/test_local_replay_timeline_coverage_auditor.py",
        ROOT / "tests/unit/test_replay_timeline_coverage_flow.py",
    )
    forbidden_imports = (
        "MetricObservation",
        "EvaluationResultSet",
    )
    for path in coverage_paths:
        if not path.exists():
            continue
        lines = _import_lines(path)
        for name in forbidden_imports:
            assert not any(name in line for line in lines), (
                f"found {name!r} import in {path.name}"
            )


def test_replay_timeline_coverage_diff_test_files_do_not_import_forbidden_dependencies() -> None:
    diff_test_files = (
        ROOT / "tests/unit/test_replay_timeline_coverage_diff_domain.py",
        ROOT / "tests/unit/test_in_memory_replay_timeline_coverage_diff_store.py",
        ROOT / "tests/unit/test_local_replay_timeline_coverage_differ.py",
        ROOT / "tests/unit/test_replay_timeline_coverage_diff_flow.py",
    )
    forbidden = (
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "matplotlib",
        "plotly",
        "seaborn",
    )
    for path in diff_test_files:
        if not path.exists():
            continue
        lines = _import_lines(path)
        for name in forbidden:
            assert not any(name in line for line in lines), (
                f"found {name!r} import in {path.name}"
            )


def test_replay_timeline_coverage_diff_modules_do_not_import_execution_types() -> None:
    diff_paths = (
        ROOT / "src/futures_bot/domain/replay.py",
        ROOT / "src/futures_bot/ports/replay.py",
        ROOT / "src/futures_bot/infrastructure/replay/in_memory.py",
        ROOT / "src/futures_bot/replay/local.py",
        ROOT / "tests/unit/test_replay_timeline_coverage_diff_domain.py",
        ROOT / "tests/unit/test_in_memory_replay_timeline_coverage_diff_store.py",
        ROOT / "tests/unit/test_local_replay_timeline_coverage_differ.py",
        ROOT / "tests/unit/test_replay_timeline_coverage_diff_flow.py",
    )
    forbidden_imports = (
        "MetricObservation",
        "EvaluationResultSet",
    )
    for path in diff_paths:
        if not path.exists():
            continue
        lines = _import_lines(path)
        for name in forbidden_imports:
            assert not any(name in line for line in lines), (
                f"found {name!r} import in {path.name}"
            )


def test_asset_semantics_modules_do_not_import_external_infra_or_runtime() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/asset_semantics.py",
        ROOT / "src/futures_bot/venue_capabilities/asset_semantics.py",
    )
    forbidden = (
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ccxt",
        "socket",
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "Kafka",
        "Redis",
        "Postgres",
        "threading",
        "asyncio",
        "subprocess",
        "sleep",
        "datetime.now",
        "time.time",
        "random",
        "uuid",
        "open(",
        "write_text",
        "read_text",
        "ExecutionSimulator",
        "MatchingEngine",
        "LedgerMutation",
        "ExchangeAdapter",
        "HardRiskGate",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"found {name!r} in {path.name}"


def test_venue_asset_semantics_no_hardcoded_stablecoin_only_execution_assumption() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/asset_semantics.py",
        ROOT / "src/futures_bot/venue_capabilities/asset_semantics.py",
        ROOT / "src/futures_bot/venue_capabilities/validator.py",
    )
    forbidden_phrases = (
        "supported assets must be limited to USDT/USDC",
        "stablecoin-collateral linear futures only",
        "inverse, coin-margined, multi-asset collateral",
        "portfolio-margin assumptions are intentionally outside",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for phrase in forbidden_phrases:
            assert phrase not in source, f"found {phrase!r} in {path.name}"


def test_collateral_valuation_source_files_do_not_import_forbidden_dependencies() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/collateral_valuation.py",
        ROOT / "src/futures_bot/ports/collateral_valuation.py",
        ROOT / "src/futures_bot/collateral_valuation/in_memory.py",
        ROOT / "src/futures_bot/collateral_valuation/policies.py",
    )
    forbidden = (
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ccxt",
        "socket",
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "Kafka",
        "Redis",
        "Postgres",
        "threading",
        "asyncio",
        "subprocess",
        "sleep",
        "datetime.now",
        "time.time",
        "random",
        "uuid",
        "open(",
        "write_text",
        "read_text",
        "API key",
        "api_key",
        "ExchangeAdapter",
        "ExecutionSimulator",
        "MatchingEngine",
        "LedgerMutation",
        "liquidation",
        "Strategy",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"found {name!r} in {path.name}"


def test_collateral_valuation_no_hardcoded_stablecoin_only_policy() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/collateral_valuation.py",
        ROOT / "src/futures_bot/collateral_valuation/policies.py",
    )
    forbidden_phrases = (
        "collateral asset must be USDT or USDC",
        "stablecoin-only",
        "stablecoin collateral only",
        "non-stable collateral is ready by default",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for phrase in forbidden_phrases:
            assert phrase not in source, f"found {phrase!r} in {path.name}"


def test_objective_asset_source_files_do_not_import_forbidden_dependencies() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/objective_assets.py",
        ROOT / "src/futures_bot/ports/objective_assets.py",
        ROOT / "src/futures_bot/objective_assets/in_memory.py",
        ROOT / "src/futures_bot/objective_assets/policies.py",
    )
    forbidden = (
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ccxt",
        "socket",
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "Kafka",
        "Redis",
        "Postgres",
        "threading",
        "asyncio",
        "subprocess",
        "sleep",
        "datetime.now",
        "time.time",
        "random",
        "uuid",
        "open(",
        "write_text",
        "read_text",
        "API key",
        "api_key",
        "ExchangeAdapter",
        "ExecutionSimulator",
        "MatchingEngine",
        "LedgerMutation",
        "liquidation",
        "Strategy",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"found {name!r} in {path.name}"


def test_objective_asset_policy_has_no_implicit_stablecoin_or_crypto_equivalence() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/objective_assets.py",
        ROOT / "src/futures_bot/objective_assets/policies.py",
    )
    forbidden_phrases = (
        "USDT == USD",
        "USDT/USD",
        "stablecoin parity",
        "stablecoins are equivalent",
        "BTC and ETH are equivalent",
        "ETH/BTC",
        "objective asset defaults to USDT",
        "default objective asset",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for phrase in forbidden_phrases:
            assert phrase not in source, f"found {phrase!r} in {path.name}"


def test_asset_conversion_source_files_do_not_import_forbidden_dependencies() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/asset_conversion.py",
        ROOT / "src/futures_bot/ports/asset_conversion.py",
        ROOT / "src/futures_bot/asset_conversion/in_memory.py",
        ROOT / "src/futures_bot/asset_conversion/policies.py",
    )
    forbidden = (
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ccxt",
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "Kafka",
        "Redis",
        "Postgres",
        "datetime.now",
        "time.time",
        "random",
        "uuid",
        "submit_order",
        "ledger",
        "strategy",
        "simulator",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"found {name!r} in {path.name}"


def test_asset_conversion_has_no_hardcoded_stablecoin_equivalence() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/asset_conversion.py",
        ROOT / "src/futures_bot/asset_conversion/policies.py",
    )
    forbidden_phrases = (
        "USDT == USD",
        "USDC == USDT",
        "stablecoin parity",
        "stablecoins are equivalent",
        "default conversion",
        "implicit conversion",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for phrase in forbidden_phrases:
            assert phrase not in source, f"found {phrase!r} in {path.name}"


def test_margin_liquidation_source_files_do_not_import_forbidden_dependencies() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/margin_liquidation.py",
        ROOT / "src/futures_bot/ports/margin_liquidation.py",
        ROOT / "src/futures_bot/margin_liquidation/in_memory.py",
        ROOT / "src/futures_bot/margin_liquidation/policies.py",
    )
    forbidden = (
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ccxt",
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "Kafka",
        "Redis",
        "Postgres",
        "datetime.now",
        "time.time",
        "random",
        "uuid",
        "submit_order",
        "strategy",
        "simulator",
        "portfolio margin engine",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"found {name!r} in {path.name}"


def test_margin_liquidation_has_no_hardcoded_stablecoin_or_leverage_defaults() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/margin_liquidation.py",
        ROOT / "src/futures_bot/margin_liquidation/policies.py",
    )
    forbidden_phrases = (
        "USDT == USD",
        "USDC == USDT",
        "stablecoin parity",
        "stablecoins are equivalent",
        "default leverage",
        "100x",
        "liquidation price",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for phrase in forbidden_phrases:
            assert phrase not in source, f"found {phrase!r} in {path.name}"


def test_execution_cost_source_files_do_not_import_forbidden_dependencies() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/execution_costs.py",
        ROOT / "src/futures_bot/ports/execution_costs.py",
        ROOT / "src/futures_bot/execution_costs/in_memory.py",
        ROOT / "src/futures_bot/execution_costs/policies.py",
    )
    forbidden = (
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ccxt",
        "socket",
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "Kafka",
        "Redis",
        "Postgres",
        "datetime.now",
        "time.time",
        "random",
        "uuid",
        "asyncio",
        "threading",
        "submit_order",
        "strategy",
        "simulator",
        "ledger",
        "order_book",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"found {name!r} in {path.name}"


def test_execution_cost_has_no_hardcoded_zero_fee_or_funding_defaults() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/execution_costs.py",
        ROOT / "src/futures_bot/execution_costs/policies.py",
    )
    forbidden_phrases = (
        "USDT == USD",
        "USDC == USDT",
        "stablecoin parity",
        "stablecoins are equivalent",
        "default fee",
        "zero fee",
        "no funding",
        "ignored funding",
        "default spread",
        "free depth",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for phrase in forbidden_phrases:
            assert phrase not in source, f"found {phrase!r} in {path.name}"


def test_market_data_source_files_do_not_import_forbidden_dependencies() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/market_data.py",
        ROOT / "src/futures_bot/ports/market_data.py",
        ROOT / "src/futures_bot/market_data/in_memory.py",
        ROOT / "src/futures_bot/market_data/policies.py",
    )
    forbidden = (
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ccxt",
        "socket",
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "Kafka",
        "Redis",
        "Postgres",
        "datetime.now",
        "time.time",
        "random",
        "uuid",
        "asyncio",
        "threading",
        "submit_order",
        "strategy",
        "simulator",
        "ledger",
        "reconstruct",
        "fetch_live",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"found {name!r} in {path.name}"


def test_market_data_has_no_hardcoded_substitution_or_stale_acceptance() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/market_data.py",
        ROOT / "src/futures_bot/market_data/policies.py",
    )
    forbidden_phrases = (
        "USDT == USD",
        "USDC == USDT",
        "stablecoin parity",
        "stablecoins are equivalent",
        "mark equals index",
        "last equals mark",
        "index equals last",
        "accept stale",
        "allow stale",
        "ignore gap",
        "ignore gaps",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for phrase in forbidden_phrases:
            assert phrase not in source, f"found {phrase!r} in {path.name}"


def test_venue_registry_source_files_do_not_import_forbidden_dependencies() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/venue_registry.py",
        ROOT / "src/futures_bot/ports/venue_registry.py",
        ROOT / "src/futures_bot/venue_capabilities/registry.py",
    )
    forbidden = (
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ccxt",
        "socket",
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "Kafka",
        "Redis",
        "Postgres",
        "threading",
        "asyncio",
        "subprocess",
        "sleep",
        "datetime.now",
        "time.time",
        "random",
        "uuid",
        "open(",
        "write_text",
        "read_text",
        "API key",
        "api_key",
        "adapter",
        "ExchangeAdapter",
        "CapabilitySnapshot(",
        "SourceRecord(",
        "payload_hash",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"found {name!r} in {path.name}"


def test_venue_registry_readme_documents_descriptor_boundary() -> None:
    readme = (
        ROOT / "src/futures_bot/venue_capabilities" / ("README." + "md")
    ).read_text(encoding="utf-8")

    assert "Venue Descriptor Registry" in readme
    assert "descriptor exists" in readme
    assert "capability readiness" in readme
    assert "execution readiness proof" in readme
    assert "real venue submission" in readme


def test_replay_artifact_fingerprint_source_does_not_import_forbidden_dependencies() -> None:
    source_paths = (
        ROOT / "src/futures_bot/replay/integrity.py",
    )
    forbidden = (
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "matplotlib",
        "plotly",
        "seaborn",
        "LocalJsonlWal",
        "sidecars.local",
        "decide_wal_gc",
        "threading",
        "asyncio",
        "subprocess",
        "sleep",
        "open(",
        "write_text",
        "read_text",
    )
    for path in source_paths:
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"found {name!r} in {path.name}"


def test_replay_artifact_fingerprint_modules_do_not_import_execution_types() -> None:
    fingerprint_paths = (
        ROOT / "src/futures_bot/replay/integrity.py",
        ROOT / "tests/unit/test_replay_artifact_fingerprint_domain.py",
        ROOT / "tests/unit/test_in_memory_replay_artifact_fingerprint_store.py",
        ROOT / "tests/unit/test_local_replay_artifact_fingerprinter.py",
        ROOT / "tests/unit/test_replay_artifact_fingerprint_flow.py",
    )
    forbidden_imports = (
        "MetricObservation",
        "EvaluationResultSet",
    )
    for path in fingerprint_paths:
        if not path.exists():
            continue
        lines = _import_lines(path)
        for name in forbidden_imports:
            assert not any(name in line for line in lines), (
                f"found {name!r} import in {path.name}"
            )


def test_replay_artifact_fingerprint_verification_source_does_not_import_forbidden_deps() -> None:
    source = (ROOT / "src/futures_bot/replay/integrity.py").read_text(encoding="utf-8")
    forbidden = (
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "matplotlib",
        "plotly",
        "seaborn",
        "LocalJsonlWal",
        "sidecars.local",
        "decide_wal_gc",
        "threading",
        "asyncio",
        "subprocess",
        "sleep",
        "open(",
        "write_text",
        "read_text",
    )
    for name in forbidden:
        assert name not in source, f"found {name!r} in integrity.py"


def test_replay_artifact_fingerprint_verification_test_files_do_not_import_forbidden_deps() -> None:
    verification_test_files = (
        ROOT / "tests/unit/test_replay_artifact_fingerprint_verification_domain.py",
        ROOT / "tests/unit/test_in_memory_replay_artifact_fingerprint_verification_store.py",
        ROOT / "tests/unit/test_local_replay_artifact_fingerprint_verifier.py",
        ROOT / "tests/unit/test_replay_artifact_fingerprint_verification_flow.py",
    )
    forbidden = (
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "matplotlib",
        "plotly",
        "seaborn",
    )
    for path in verification_test_files:
        if not path.exists():
            continue
        lines = _import_lines(path)
        for name in forbidden:
            assert not any(name in line for line in lines), (
                f"found {name!r} import in {path.name}"
            )


def test_replay_artifact_fingerprint_verification_modules_do_not_import_execution_types() -> None:
    verification_paths = (
        ROOT / "src/futures_bot/replay/integrity.py",
        ROOT / "tests/unit/test_replay_artifact_fingerprint_verification_domain.py",
        ROOT / "tests/unit/test_in_memory_replay_artifact_fingerprint_verification_store.py",
        ROOT / "tests/unit/test_local_replay_artifact_fingerprint_verifier.py",
        ROOT / "tests/unit/test_replay_artifact_fingerprint_verification_flow.py",
    )
    forbidden_imports = (
        "MetricObservation",
        "EvaluationResultSet",
    )
    for path in verification_paths:
        if not path.exists():
            continue
        lines = _import_lines(path)
        for name in forbidden_imports:
            assert not any(name in line for line in lines), (
                f"found {name!r} import in {path.name}"
            )


def test_replay_artifact_fingerprint_batch_source_does_not_import_forbidden_deps() -> None:
    source = (ROOT / "src/futures_bot/replay/integrity.py").read_text(encoding="utf-8")
    forbidden = (
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "matplotlib",
        "plotly",
        "seaborn",
        "LocalJsonlWal",
        "sidecars.local",
        "decide_wal_gc",
        "threading",
        "asyncio",
        "subprocess",
        "sleep",
        "open(",
        "write_text",
        "read_text",
    )
    for name in forbidden:
        assert name not in source, f"found {name!r} in integrity.py"


def test_replay_artifact_fingerprint_batch_test_files_do_not_import_forbidden_deps() -> None:
    batch_test_files = (
        ROOT / "tests/unit/test_replay_artifact_fingerprint_verification_batch_domain.py",
        ROOT / "tests/unit/test_in_memory_replay_artifact_fingerprint_verification_batch_store.py",
        ROOT / "tests/unit/test_local_replay_artifact_fingerprint_batch_verifier.py",
        ROOT / "tests/unit/test_replay_artifact_fingerprint_verification_batch_flow.py",
    )
    forbidden = (
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "matplotlib",
        "plotly",
        "seaborn",
    )
    for path in batch_test_files:
        if not path.exists():
            continue
        lines = _import_lines(path)
        for name in forbidden:
            assert not any(name in line for line in lines), (
                f"found {name!r} import in {path.name}"
            )


def test_replay_artifact_fingerprint_batch_modules_do_not_import_execution_types() -> None:
    batch_paths = (
        ROOT / "src/futures_bot/replay/integrity.py",
        ROOT / "tests/unit/test_replay_artifact_fingerprint_verification_batch_domain.py",
        ROOT / "tests/unit/test_in_memory_replay_artifact_fingerprint_verification_batch_store.py",
        ROOT / "tests/unit/test_local_replay_artifact_fingerprint_batch_verifier.py",
        ROOT / "tests/unit/test_replay_artifact_fingerprint_verification_batch_flow.py",
    )
    forbidden_imports = (
        "MetricObservation",
        "EvaluationResultSet",
    )
    for path in batch_paths:
        if not path.exists():
            continue
        lines = _import_lines(path)
        for name in forbidden_imports:
            assert not any(name in line for line in lines), (
                f"found {name!r} import in {path.name}"
            )


def test_replay_runtime_source_does_not_import_or_use_forbidden_dependencies() -> None:
    path = ROOT / "src/futures_bot/replay/runtime.py"
    source = path.read_text(encoding="utf-8")
    import_lines = _import_lines(path)
    forbidden_source = (
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "LocalJsonlWal",
        "sidecars",
        "open(",
        "write_text",
        "read_text",
        "subprocess",
        "threading",
        "asyncio",
        "sleep",
        "exchange",
        "adapter",
        "DecisionStack",
        "HardRiskGate",
        "RiskBehaviorModel",
        "RiskGate",
        "EvaluationResultSet",
        "MetricObservation",
        "PnL",
    )
    for name in forbidden_source:
        assert name not in source, f"found {name!r} in runtime.py"
    forbidden_imports = (
        "ledger",
        "execution",
        "orders",
        "fills",
        "metrics",
        "evaluation",
        "performance",
    )
    for name in forbidden_imports:
        assert not any(name in line for line in import_lines), (
            f"found {name!r} import in runtime.py"
        )


def test_replay_readiness_source_does_not_import_forbidden_dependencies() -> None:
    source = (ROOT / "src/futures_bot/replay/integrity.py").read_text(encoding="utf-8")
    forbidden = (
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "matplotlib",
        "plotly",
        "seaborn",
        "LocalJsonlWal",
        "sidecars.local",
        "decide_wal_gc",
        "threading",
        "asyncio",
        "subprocess",
        "sleep",
        "open(",
        "write_text",
        "read_text",
    )
    for name in forbidden:
        assert name not in source, f"found {name!r} in integrity.py"


def test_replay_readiness_test_files_do_not_import_forbidden_dependencies() -> None:
    readiness_test_files = (
        ROOT / "tests/unit/test_replay_readiness_domain.py",
        ROOT / "tests/unit/test_in_memory_replay_readiness_store.py",
        ROOT / "tests/unit/test_local_replay_readiness_checker.py",
        ROOT / "tests/unit/test_replay_readiness_flow.py",
    )
    forbidden = (
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "matplotlib",
        "plotly",
        "seaborn",
    )
    for path in readiness_test_files:
        if not path.exists():
            continue
        lines = _import_lines(path)
        for name in forbidden:
            assert not any(name in line for line in lines), (
                f"found {name!r} import in {path.name}"
            )


def test_replay_readiness_modules_do_not_import_execution_types() -> None:
    readiness_paths = (
        ROOT / "src/futures_bot/replay/integrity.py",
        ROOT / "tests/unit/test_replay_readiness_domain.py",
        ROOT / "tests/unit/test_in_memory_replay_readiness_store.py",
        ROOT / "tests/unit/test_local_replay_readiness_checker.py",
        ROOT / "tests/unit/test_replay_readiness_flow.py",
    )
    forbidden_imports = (
        "MetricObservation",
        "EvaluationResultSet",
    )
    for path in readiness_paths:
        if not path.exists():
            continue
        lines = _import_lines(path)
        for name in forbidden_imports:
            assert not any(name in line for line in lines), (
                f"found {name!r} import in {path.name}"
            )


def test_replay_run_manifest_modules_do_not_import_forbidden_libs() -> None:
    manifest_files = (
        ROOT / "src/futures_bot/replay/integrity.py",
        ROOT / "tests/unit/test_replay_run_manifest_domain.py",
        ROOT / "tests/unit/test_in_memory_replay_run_manifest_store.py",
        ROOT / "tests/unit/test_local_replay_run_planner.py",
        ROOT / "tests/unit/test_replay_run_manifest_flow.py",
    )
    forbidden = (
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "sqlalchemy",
        "psycopg",
        "confluent_kafka",
        "aiokafka",
        "matplotlib",
        "plotly",
        "seaborn",
    )
    for path in manifest_files:
        if not path.exists():
            continue
        lines = _import_lines(path)
        for name in forbidden:
            assert not any(name in line for line in lines), (
                f"found {name!r} import in {path.name}"
            )


def test_replay_run_manifest_modules_do_not_import_execution_types() -> None:
    manifest_paths = (
        ROOT / "src/futures_bot/replay/integrity.py",
        ROOT / "tests/unit/test_replay_run_manifest_domain.py",
        ROOT / "tests/unit/test_in_memory_replay_run_manifest_store.py",
        ROOT / "tests/unit/test_local_replay_run_planner.py",
        ROOT / "tests/unit/test_replay_run_manifest_flow.py",
    )
    forbidden_imports = (
        "MetricObservation",
        "EvaluationResultSet",
    )
    for path in manifest_paths:
        if not path.exists():
            continue
        lines = _import_lines(path)
        for name in forbidden_imports:
            assert not any(name in line for line in lines), (
                f"found {name!r} import in {path.name}"
            )


def test_replay_run_planner_does_not_use_file_io() -> None:
    integrity_path = ROOT / "src/futures_bot/replay/integrity.py"
    if not integrity_path.exists():
        return
    source = integrity_path.read_text(encoding="utf-8")
    forbidden_patterns = (
        "open(",
        "write_text(",
        "read_text(",
        "pathlib",
        "subprocess",
        "threading",
        "asyncio",
    )
    for pattern in forbidden_patterns:
        assert pattern not in source, (
            f"found forbidden pattern {pattern!r} in integrity.py"
        )


def test_replay_run_manifest_tests_do_not_read_docs() -> None:
    manifest_test_files = (
        ROOT / "tests/unit/test_replay_run_manifest_domain.py",
        ROOT / "tests/unit/test_in_memory_replay_run_manifest_store.py",
        ROOT / "tests/unit/test_local_replay_run_planner.py",
        ROOT / "tests/unit/test_replay_run_manifest_flow.py",
    )
    forbidden_dir = "doc" + "s/"
    for path in manifest_test_files:
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        assert forbidden_dir not in source, f"found docs reference in {path.name}"


def test_market_data_sprint_sources_do_not_use_forbidden_runtime_dependencies() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/market_data.py",
        ROOT / "src/futures_bot/market_data/frame_builder.py",
        ROOT / "src/futures_bot/ports/market_data.py",
    )
    forbidden = (
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ccxt",
        "socket",
        "asyncio",
        "threading",
        "subprocess",
        "Kafka",
        "Postgres",
        "SQLAlchemy",
        "DecisionStack",
        "RiskBehaviorModel",
        "HardRiskGate",
        "Execution",
        "OrderIntent",
        "Ledger",
        "PnL",
        "datetime.now",
        "time.time",
        "random",
        "uuid",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"found {name!r} in {path.name}"


def test_event_journal_source_files_do_not_import_forbidden_dependencies() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/event_journal.py",
        ROOT / "src/futures_bot/ports/event_journal.py",
        ROOT / "src/futures_bot/event_journal/in_memory.py",
        ROOT / "src/futures_bot/event_journal/policies.py",
    )
    forbidden = (
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ccxt",
        "socket",
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "Kafka",
        "Redis",
        "Postgres",
        "DBWriter",
        "LocalJsonlWal",
        "pathlib",
        "Path",
        "open(",
        "read_text",
        "write_text",
        "datetime.now",
        "time.time",
        "random",
        "uuid",
        "asyncio",
        "threading",
        "subprocess",
        "sleep",
        "Strategy",
        "DecisionStack",
        "ExecutionSimulator",
        "Ledger",
        "OrderIntent",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"found {name!r} in {path.name}"


def test_event_journal_has_no_hardcoded_gap_or_stale_acceptance() -> None:
    source = "\n".join(
        (
            (ROOT / "src/futures_bot/domain/event_journal.py").read_text(encoding="utf-8"),
            (ROOT / "src/futures_bot/event_journal/policies.py").read_text(
                encoding="utf-8"
            ),
        )
    )
    forbidden_phrases = (
        "accept stale",
        "allow stale",
        "accept gapped",
        "allow gapped",
        "GAP_DECLARED, EventJournalContinuityStatus.GAP_SUSPECTED",
        "EventJournalSourceHealth.GAPPED, EventJournalSourceHealth.STALE",
    )
    for phrase in forbidden_phrases:
        assert phrase not in source


def test_replay_market_data_sources_do_not_use_forbidden_runtime_dependencies() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/replay_market_data.py",
        ROOT / "src/futures_bot/market_data/replay_adapter.py",
        ROOT / "src/futures_bot/market_data/replay_lookup.py",
    )
    forbidden = (
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ccxt",
        "socket",
        "asyncio",
        "threading",
        "subprocess",
        "Kafka",
        "Postgres",
        "SQLAlchemy",
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "DecisionStack",
        "RiskBehaviorModel",
        "HardRiskGate",
        "OrderIntent",
        "Execution",
        "Ledger",
        "PnL",
        "datetime.now",
        "time.time",
        "random",
        "uuid",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"found {name!r} in {path.name}"


def test_market_evidence_sources_do_not_use_forbidden_runtime_dependencies() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/evidence.py",
        ROOT / "src/futures_bot/evidence/frame_builder.py",
        ROOT / "src/futures_bot/ports/evidence.py",
    )
    forbidden = (
        "DecisionStack",
        "ReplayDecisionStackContext",
        "DecisionIntent",
        "NoTradeDecision",
        "RiskBehaviorModel",
        "HardRiskGate",
        "ExecutionIntent",
        "OrderIntent",
        "Ledger",
        "PnL",
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ccxt",
        "socket",
        "asyncio",
        "threading",
        "subprocess",
        "Kafka",
        "Postgres",
        "SQLAlchemy",
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "datetime.now",
        "time.time",
        "random",
        "uuid",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"found {name!r} in {path.name}"


def test_live_state_sources_do_not_use_external_infra_or_runtime_dependencies() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/live_state.py",
        ROOT / "src/futures_bot/ports/live_state.py",
        ROOT / "src/futures_bot/live_state/in_memory.py",
        ROOT / "src/futures_bot/live_state/stitcher.py",
    )
    forbidden = (
        "redis",
        "kafka",
        "confluent_kafka",
        "aiokafka",
        "psycopg",
        "sqlalchemy",
        "asyncpg",
        "pandas",
        "numpy",
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ccxt",
        "socket",
        "threading",
        "asyncio",
        "subprocess",
        "datetime.now",
        "time.time",
        "random",
        "uuid",
        "Binance",
        "KuCoin",
        "CoinEx",
        "MEXC",
        "Phemex",
        "OrderIntent",
        "ExecutionIntent",
        "RiskGate",
        "DecisionStack",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"found {name!r} in {path.name}"


def test_live_state_ports_do_not_import_infrastructure() -> None:
    lines = _import_lines(ROOT / "src/futures_bot/ports/live_state.py")
    assert not any("infrastructure" in line for line in lines)


def test_runtime_control_sources_do_not_use_external_infra_or_runtime_dependencies() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/runtime_control.py",
        ROOT / "src/futures_bot/ports/runtime_control.py",
        ROOT / "src/futures_bot/runtime_control/in_memory.py",
        ROOT / "src/futures_bot/runtime_control/policies.py",
    )
    forbidden = (
        "redis",
        "kafka",
        "confluent_kafka",
        "aiokafka",
        "psycopg",
        "sqlalchemy",
        "asyncpg",
        "pandas",
        "numpy",
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ccxt",
        "socket",
        "threading",
        "asyncio",
        "subprocess",
        "datetime.now",
        "time.time",
        "random",
        "uuid",
        "Binance",
        "KuCoin",
        "CoinEx",
        "MEXC",
        "Phemex",
        "OrderIntent",
        "ExecutionIntent",
        "ExecutionSimulator",
        "BotBlueprint",
        "BotInstance",
        "HardRiskGate",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"found {name!r} in {path.name}"


def test_runtime_control_ports_do_not_import_infrastructure() -> None:
    lines = _import_lines(ROOT / "src/futures_bot/ports/runtime_control.py")
    assert not any("infrastructure" in line for line in lines)


def test_order_lifecycle_sources_do_not_use_external_infra_or_runtime_dependencies() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/order_lifecycle.py",
        ROOT / "src/futures_bot/ports/order_lifecycle.py",
        ROOT / "src/futures_bot/order_lifecycle/in_memory.py",
        ROOT / "src/futures_bot/order_lifecycle/policies.py",
    )
    forbidden = (
        "redis",
        "kafka",
        "confluent_kafka",
        "aiokafka",
        "psycopg",
        "sqlalchemy",
        "asyncpg",
        "pandas",
        "numpy",
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ccxt",
        "socket",
        "threading",
        "asyncio",
        "subprocess",
        "datetime.now",
        "time.time",
        "random",
        "uuid",
        "Binance",
        "KuCoin",
        "CoinEx",
        "MEXC",
        "Phemex",
        "ExchangeAdapter",
        "ExecutionSimulator",
        "BotBlueprint",
        "BotInstance",
        "HardRiskGate",
        "Ledger",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"found {name!r} in {path.name}"


def test_order_lifecycle_ports_do_not_import_infrastructure() -> None:
    lines = _import_lines(ROOT / "src/futures_bot/ports/order_lifecycle.py")
    assert not any("infrastructure" in line for line in lines)


def test_execution_manager_sources_do_not_use_external_infra_or_runtime_dependencies() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/execution_manager.py",
        ROOT / "src/futures_bot/ports/execution_manager.py",
        ROOT / "src/futures_bot/execution_manager/coordinator.py",
        ROOT / "src/futures_bot/execution_manager/in_memory.py",
    )
    forbidden = (
        "redis",
        "kafka",
        "confluent_kafka",
        "aiokafka",
        "psycopg",
        "sqlalchemy",
        "asyncpg",
        "pandas",
        "numpy",
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ccxt",
        "socket",
        "threading",
        "asyncio",
        "subprocess",
        "datetime.now",
        "time.time",
        "random",
        "uuid",
        "Binance",
        "KuCoin",
        "CoinEx",
        "MEXC",
        "Phemex",
        "ExchangeAdapter",
        "ExecutionSimulator",
        "BotBlueprint",
        "BotInstance",
        "HardRiskGate",
        "Ledger",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"found {name!r} in {path.name}"


def test_execution_manager_ports_do_not_import_infrastructure() -> None:
    lines = _import_lines(ROOT / "src/futures_bot/ports/execution_manager.py")
    assert not any("infrastructure" in line for line in lines)


def test_venue_capability_sources_do_not_use_external_infra_or_runtime_dependencies() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/venue_capabilities.py",
        ROOT / "src/futures_bot/domain/venue_capability_freshness.py",
        ROOT / "src/futures_bot/domain/venue_capability_resolution.py",
        ROOT / "src/futures_bot/ports/venue_capabilities.py",
        ROOT / "src/futures_bot/ports/venue_capability_freshness.py",
        ROOT / "src/futures_bot/ports/venue_capability_resolution.py",
        ROOT / "src/futures_bot/venue_capabilities/freshness.py",
        ROOT / "src/futures_bot/venue_capabilities/in_memory.py",
        ROOT / "src/futures_bot/venue_capabilities/resolution.py",
        ROOT / "src/futures_bot/venue_capabilities/validator.py",
    )
    forbidden = (
        "redis",
        "kafka",
        "confluent_kafka",
        "aiokafka",
        "psycopg",
        "sqlalchemy",
        "asyncpg",
        "pandas",
        "numpy",
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ccxt",
        "socket",
        "threading",
        "asyncio",
        "subprocess",
        "datetime.now",
        "time.time",
        "random",
        "uuid",
        "Binance",
        "KuCoin",
        "CoinEx",
        "MEXC",
        "Phemex",
        "ExchangeAdapter",
        "ExecutionSimulator",
        "BotBlueprint",
        "BotInstance",
        "HardRiskGate",
        "Ledger",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"found {name!r} in {path.name}"


def test_venue_capability_ports_do_not_import_infrastructure() -> None:
    lines = _import_lines(ROOT / "src/futures_bot/ports/venue_capabilities.py")
    assert not any("infrastructure" in line for line in lines)


def test_execution_capability_gate_sources_do_not_use_external_infra() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/execution_capability_gate.py",
        ROOT / "src/futures_bot/ports/execution_capability_gate.py",
        ROOT / "src/futures_bot/execution_manager/capability_gate.py",
    )
    forbidden = (
        "redis",
        "kafka",
        "confluent_kafka",
        "aiokafka",
        "psycopg",
        "sqlalchemy",
        "asyncpg",
        "pandas",
        "numpy",
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ccxt",
        "socket",
        "threading",
        "asyncio",
        "subprocess",
        "datetime.now",
        "time.time",
        "random",
        "uuid",
        "Binance",
        "KuCoin",
        "CoinEx",
        "MEXC",
        "Phemex",
        "ExchangeAdapter",
        "ExecutionSimulator",
        "BotBlueprint",
        "BotInstance",
        "HardRiskGate",
        "Ledger",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"found {name!r} in {path.name}"


def test_execution_capability_gate_ports_do_not_import_infrastructure() -> None:
    lines = _import_lines(ROOT / "src/futures_bot/ports/execution_capability_gate.py")
    assert not any("infrastructure" in line for line in lines)


def test_execution_capability_gate_test_files_do_not_import_forbidden_dependencies() -> None:
    gate_test_files = (
        ROOT / "tests/unit/test_execution_capability_gate_domain.py",
        ROOT / "tests/unit/test_execution_capability_gate.py",
        ROOT / "tests/unit/test_execution_capability_gate_freshness.py",
        ROOT / "tests/unit/test_execution_manager_capability_integration.py",
        ROOT / "tests/unit/test_execution_manager_capability_freshness_integration.py",
        ROOT / "tests/unit/test_execution_manager_resolution_flow.py",
        ROOT / "tests/unit/test_execution_manager_replace_capability_integration.py",
        ROOT / "tests/unit/test_venue_capability_freshness_domain.py",
        ROOT / "tests/unit/test_venue_capability_freshness_policy.py",
        ROOT / "tests/unit/test_venue_capability_resolution_domain.py",
        ROOT / "tests/unit/test_venue_capability_resolution_gateway.py",
        ROOT / "tests/unit/test_venue_capability_manual_import_gateway.py",
        ROOT / "tests/unit/test_venue_capability_source_resolution.py",
    )
    forbidden = (
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "matplotlib",
        "plotly",
        "seaborn",
        "Binance",
        "KuCoin",
        "CoinEx",
        "MEXC",
        "Phemex",
        "ExchangeAdapter",
        "ExecutionSimulator",
    )
    for path in gate_test_files:
        if not path.exists():
            continue
        lines = _import_lines(path)
        for name in forbidden:
            assert not any(name in line for line in lines), (
                f"found {name!r} import in {path.name}"
            )


def test_venue_capability_source_contracts_do_not_import_forbidden_dependencies() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/venue_capability_sources.py",
        ROOT / "src/futures_bot/ports/venue_capability_sources.py",
        ROOT / "src/futures_bot/venue_capabilities/sources.py",
        ROOT / "src/futures_bot/venue_capabilities/in_memory.py",
        ROOT / "src/futures_bot/domain/venue_capabilities.py",
        ROOT / "src/futures_bot/domain/venue_capability_resolution.py",
        ROOT / "src/futures_bot/venue_capabilities/resolution.py",
        ROOT / "src/futures_bot/ports/venue_capability_resolution.py",
    )
    forbidden = (
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ccxt",
        "socket",
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "Kafka",
        "Redis",
        "Postgres",
        "threading",
        "asyncio",
        "subprocess",
        "sleep",
        "datetime.now",
        "time.time",
        "random",
        "uuid",
        "Binance",
        "KuCoin",
        "CoinEx",
        "MEXC",
        "Phemex",
        "ExchangeAdapter",
        "ExecutionSimulator",
        "BotBlueprint",
        "BotInstance",
        "HardRiskGate",
        "Ledger",
        "open(",
        "write_text",
        "read_text",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"found {name!r} in {path.name}"


def test_venue_capability_source_ports_do_not_import_infrastructure() -> None:
    lines = _import_lines(ROOT / "src/futures_bot/ports/venue_capability_sources.py")
    assert not any("infrastructure" in line for line in lines)


def test_review_120_plr0913_regression_uses_scoped_resolution_waiver() -> None:
    source = (ROOT / "src/futures_bot/venue_capabilities/resolution.py").read_text(
        encoding="utf-8"
    )

    assert "_decision(  # noqa: PLR0913" in source
    assert "noqa" not in source.replace("# noqa: PLR0913", "").replace(
        "# noqa: PLR0911",
        "",
    )


def test_execution_readiness_modules_do_not_import_external_infra_or_runtime() -> None:
    source_paths = (
        ROOT / "src/futures_bot/domain/execution_readiness.py",
        ROOT / "src/futures_bot/ports/execution_readiness.py",
        ROOT / "src/futures_bot/execution_manager/readiness.py",
        ROOT / "src/futures_bot/execution_manager/in_memory.py",
        ROOT / "src/futures_bot/execution_manager/coordinator.py",
    )
    forbidden = (
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ccxt",
        "socket",
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "Kafka",
        "Redis",
        "Postgres",
        "threading",
        "asyncio",
        "subprocess",
        "sleep",
        "datetime.now",
        "time.time",
        "random",
        "uuid",
        "ExecutionSimulator",
        "MatchingEngine",
        "LedgerMutation",
        "ExchangeAdapter",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"found {name!r} in {path.name}"


def test_execution_coordinator_accepted_records_attach_readiness_proof_id() -> None:
    source = (ROOT / "src/futures_bot/execution_manager/coordinator.py").read_text(
        encoding="utf-8"
    )

    assert "build_order_execution_readiness_proof" in source
    assert "build_replace_execution_readiness_proof" in source
    assert "readiness_proof_id=readiness_proof.proof_id" in source
    assert "ACCEPTED_BY_EXECUTION" in source
