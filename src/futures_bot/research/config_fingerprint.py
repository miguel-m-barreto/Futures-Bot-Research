"""Deterministic config fingerprinting for metadata-only research records."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from futures_bot.domain.research import ConfigSnapshot, ConfigSnapshotKind


class CanonicalConfigFingerprinter:
    """Create deterministic JSON and hashes for research config payloads."""

    def canonicalize(self, payload: Mapping[str, object]) -> str:
        """Return deterministic canonical JSON for a JSON-object-like payload."""
        normalized = _normalize_mapping(payload)
        return json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

    def sha256(self, canonical_json: str) -> str:
        """Return sha256 hex digest for canonical JSON text."""
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    def snapshot(
        self,
        *,
        config_id: str,
        kind: ConfigSnapshotKind,
        payload: Mapping[str, object],
        created_at: datetime,
        description: str | None = None,
    ) -> ConfigSnapshot:
        """Build a metadata-only ConfigSnapshot from a payload."""
        canonical_json = self.canonicalize(payload)
        return ConfigSnapshot(
            config_id=config_id,
            kind=kind,
            created_at=created_at,
            canonical_json=canonical_json,
            sha256=self.sha256(canonical_json),
            description=description,
        )


def _normalize_mapping(payload: Mapping[str, object]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key, value in payload.items():
        if not isinstance(key, str):
            raise ValueError("config mapping keys must be strings")
        normalized[key] = _normalize_value(value)
    return normalized


def _normalize_value(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("config payloads must not contain floats")
    if isinstance(value, Decimal):
        return _normalize_decimal(value)
    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, Mapping):
        return _normalize_mapping(value)
    if isinstance(value, tuple | list):
        return [_normalize_value(item) for item in value]
    raise TypeError(f"unsupported config value type: {type(value).__name__}")


def _normalize_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("Decimal config values must be finite")
    normalized = value.normalize()
    if normalized == Decimal("-0"):
        normalized = Decimal("0")
    return format(normalized, "f")
