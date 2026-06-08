from __future__ import annotations

import hashlib
import inspect
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from futures_bot.domain.research import ConfigSnapshot, ConfigSnapshotKind
from futures_bot.research.config_fingerprint import CanonicalConfigFingerprinter


def _utc() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _sha(canonical_json: str) -> str:
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def test_config_snapshot_accepts_matching_sha() -> None:
    canonical_json = '{"a":1}'
    snapshot = ConfigSnapshot(
        config_id="cfg-1",
        kind=ConfigSnapshotKind.RUN_CONFIG,
        created_at=_utc(),
        canonical_json=canonical_json,
        sha256=_sha(canonical_json),
    )
    assert snapshot.sha256 == _sha(canonical_json)


def test_config_snapshot_accepts_exact_canonical_json_from_fingerprinter() -> None:
    fingerprinter = CanonicalConfigFingerprinter()
    canonical_json = fingerprinter.canonicalize(
        {"nested": {"b": 2, "a": 1}, "items": ("x", "y")}
    )
    snapshot = ConfigSnapshot(
        config_id="cfg-1",
        kind=ConfigSnapshotKind.RUN_CONFIG,
        created_at=_utc(),
        canonical_json=canonical_json,
        sha256=_sha(canonical_json),
    )
    assert snapshot.canonical_json == '{"items":["x","y"],"nested":{"a":1,"b":2}}'


def test_config_snapshot_rejects_mismatched_lowercase_hex_sha() -> None:
    canonical_json = '{"a":1}'
    wrong_sha = _sha('{"a":2}')
    with pytest.raises(ValidationError, match="canonical_json"):
        ConfigSnapshot(
            config_id="cfg-1",
            kind=ConfigSnapshotKind.RUN_CONFIG,
            created_at=_utc(),
            canonical_json=canonical_json,
            sha256=wrong_sha,
        )


def test_config_snapshot_rejects_pretty_json_even_with_matching_sha() -> None:
    pretty_json = '{ "a": 1 }'
    with pytest.raises(ValidationError, match="canonical JSON"):
        ConfigSnapshot(
            config_id="cfg-1",
            kind=ConfigSnapshotKind.RUN_CONFIG,
            created_at=_utc(),
            canonical_json=pretty_json,
            sha256=_sha(pretty_json),
        )


def test_config_snapshot_rejects_unsorted_json_even_with_matching_sha() -> None:
    unsorted_json = '{"b":2,"a":1}'
    with pytest.raises(ValidationError, match="canonical JSON"):
        ConfigSnapshot(
            config_id="cfg-1",
            kind=ConfigSnapshotKind.RUN_CONFIG,
            created_at=_utc(),
            canonical_json=unsorted_json,
            sha256=_sha(unsorted_json),
        )


def test_config_snapshot_rejects_json_float_even_with_matching_sha() -> None:
    float_json = '{"threshold":1.2}'
    with pytest.raises(ValidationError, match="float"):
        ConfigSnapshot(
            config_id="cfg-1",
            kind=ConfigSnapshotKind.RUN_CONFIG,
            created_at=_utc(),
            canonical_json=float_json,
            sha256=_sha(float_json),
        )


def test_config_snapshot_accepts_integer_json_values() -> None:
    canonical_json = '{"threshold":1}'
    snapshot = ConfigSnapshot(
        config_id="cfg-1",
        kind=ConfigSnapshotKind.RUN_CONFIG,
        created_at=_utc(),
        canonical_json=canonical_json,
        sha256=_sha(canonical_json),
    )
    assert snapshot.canonical_json == canonical_json


def test_config_snapshot_rejects_hash_for_different_json_bytes() -> None:
    canonical_json = '{"a":1}'
    pretty_json = '{ "a": 1 }'
    with pytest.raises(ValidationError, match="canonical_json"):
        ConfigSnapshot(
            config_id="cfg-1",
            kind=ConfigSnapshotKind.RUN_CONFIG,
            created_at=_utc(),
            canonical_json=canonical_json,
            sha256=_sha(pretty_json),
        )


def test_same_payload_with_different_key_order_has_same_hash() -> None:
    fingerprinter = CanonicalConfigFingerprinter()
    first = fingerprinter.canonicalize({"b": 2, "a": 1})
    second = fingerprinter.canonicalize({"a": 1, "b": 2})

    assert first == '{"a":1,"b":2}'
    assert first == second
    assert fingerprinter.sha256(first) == fingerprinter.sha256(second)


def test_different_payload_produces_different_hash() -> None:
    fingerprinter = CanonicalConfigFingerprinter()
    first = fingerprinter.canonicalize({"threshold": "1.0"})
    second = fingerprinter.canonicalize({"threshold": "2.0"})
    assert fingerprinter.sha256(first) != fingerprinter.sha256(second)


def test_nested_payload_canonicalizes_deterministically() -> None:
    fingerprinter = CanonicalConfigFingerprinter()
    canonical = fingerprinter.canonicalize(
        {
            "z": {"b": [2, 1], "a": True},
            "a": None,
        }
    )
    assert canonical == '{"a":null,"z":{"a":true,"b":[2,1]}}'


def test_canonicalize_output_has_no_whitespace_and_sorted_nested_keys() -> None:
    fingerprinter = CanonicalConfigFingerprinter()
    canonical = fingerprinter.canonicalize({"z": {"z": 2, "a": 1}, "a": "x"})
    assert canonical == '{"a":"x","z":{"a":1,"z":2}}'
    assert " " not in canonical


def test_decimal_and_tuple_normalize_deterministically() -> None:
    fingerprinter = CanonicalConfigFingerprinter()
    canonical = fingerprinter.canonicalize(
        {
            "fees": (Decimal("1.2300"), Decimal("0.00")),
            "labels": ["a", "b"],
        }
    )
    assert canonical == '{"fees":["1.23","0"],"labels":["a","b"]}'
    assert '["1.23","0"]' in canonical


def test_tuple_and_list_payloads_normalize_to_same_json_array() -> None:
    fingerprinter = CanonicalConfigFingerprinter()
    assert fingerprinter.canonicalize({"items": ("a", "b")}) == fingerprinter.canonicalize(
        {"items": ["a", "b"]}
    )


def test_float_inputs_are_rejected() -> None:
    fingerprinter = CanonicalConfigFingerprinter()
    with pytest.raises(ValueError, match="floats"):
        fingerprinter.canonicalize({"threshold": 1.2})
    with pytest.raises(ValueError, match="floats"):
        fingerprinter.canonicalize({"nested": {"threshold": 1.2}})


def test_non_string_mapping_key_rejected() -> None:
    fingerprinter = CanonicalConfigFingerprinter()
    with pytest.raises(ValueError, match="keys"):
        fingerprinter.canonicalize({1: "bad"})  # type: ignore[dict-item]


def test_unsupported_object_rejected() -> None:
    fingerprinter = CanonicalConfigFingerprinter()
    with pytest.raises(TypeError, match="unsupported"):
        fingerprinter.canonicalize({"created_at": _utc()})


def test_snapshot_produces_valid_config_snapshot() -> None:
    fingerprinter = CanonicalConfigFingerprinter()
    snapshot = fingerprinter.snapshot(
        config_id="cfg-1",
        kind=ConfigSnapshotKind.EVALUATION_CONFIG,
        payload={"metric": "pnl_after_costs"},
        created_at=_utc(),
        description="Evaluation config.",
    )

    assert snapshot.canonical_json == '{"metric":"pnl_after_costs"}'
    assert len(snapshot.sha256) == 64
    assert snapshot.sha256 == fingerprinter.sha256(snapshot.canonical_json)


def test_fingerprinter_has_no_filesystem_writes_or_forbidden_imports() -> None:
    source_path = inspect.getsourcefile(CanonicalConfigFingerprinter)
    assert source_path is not None
    source = Path(source_path).read_text(encoding="utf-8")
    forbidden = (
        "open(",
        "write_text",
        "Path(",
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "sqlalchemy",
        "confluent_kafka",
        "aiokafka",
    )
    for name in forbidden:
        assert name not in source
