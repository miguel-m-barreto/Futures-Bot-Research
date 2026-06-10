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
    source = (
        ROOT / "src/futures_bot/infrastructure/research/in_memory.py"
    ).read_text(encoding="utf-8")
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
        "decide_wal_gc",
        "matplotlib",
        "plotly",
        "seaborn",
    )
    for name in forbidden:
        assert name not in source


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
        ROOT / "src/futures_bot/replay/local.py",
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
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source


def test_replay_ports_do_not_import_infrastructure() -> None:
    lines = _import_lines(ROOT / "src/futures_bot/ports/replay.py")
    assert not any("infrastructure" in line for line in lines)


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
