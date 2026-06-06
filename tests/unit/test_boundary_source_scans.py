from __future__ import annotations

from pathlib import Path


def test_tests_do_not_read_docs_markdown() -> None:
    tests_root = Path(__file__).resolve().parents[1]
    forbidden_dir = "doc" + "s/"
    markdown_suffix = ".m" + "d"
    for test_file in tests_root.rglob("test_*.py"):
        source = test_file.read_text(encoding="utf-8")
        assert forbidden_dir not in source
        assert "read_text" not in source or markdown_suffix not in source
