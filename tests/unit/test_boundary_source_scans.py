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
