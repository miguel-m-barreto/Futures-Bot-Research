from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from futures_bot.domain.research import (
    ConfigBundle,
    ConfigBundleEntry,
    ConfigSnapshot,
    ConfigSnapshotKind,
)
from futures_bot.infrastructure.research.in_memory import (
    InMemoryConfigBundleStore,
    InMemoryConfigSnapshotStore,
    InMemoryExperimentDefinitionStore,
    InMemoryRunLineageStore,
)
from futures_bot.ports.research import ConfigBundleStorePort
from futures_bot.research.config_fingerprint import CanonicalConfigFingerprinter
from futures_bot.research.registry import LocalExperimentRegistry


def _utc(day: int = 1, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=UTC)


def _sha(canonical_json: str) -> str:
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _snapshot(
    config_id: str = "cfg-a",
    *,
    kind: ConfigSnapshotKind = ConfigSnapshotKind.RUN_CONFIG,
    payload: dict[str, object] | None = None,
    created_at: datetime | None = None,
) -> ConfigSnapshot:
    fingerprinter = CanonicalConfigFingerprinter()
    return fingerprinter.snapshot(
        config_id=config_id,
        kind=kind,
        payload=payload or {"value": config_id},
        created_at=created_at or _utc(),
    )


def _entry(snapshot: ConfigSnapshot) -> ConfigBundleEntry:
    return ConfigBundleEntry(
        config_id=snapshot.config_id,
        kind=snapshot.kind,
        sha256=snapshot.sha256,
    )


def _bundle(
    bundle_id: str = "bundle-1",
    snapshots: tuple[ConfigSnapshot, ...] | None = None,
    *,
    created_at: datetime | None = None,
) -> ConfigBundle:
    fingerprinter = CanonicalConfigFingerprinter()
    return fingerprinter.bundle(
        bundle_id=bundle_id,
        snapshots=snapshots or (_snapshot(),),
        created_at=created_at or _utc(2),
    )


def test_valid_config_bundle_with_one_entry() -> None:
    bundle = _bundle()
    assert bundle.bundle_id == "bundle-1"
    assert len(bundle.entries) == 1
    assert bundle.sha256 == _sha(bundle.canonical_json)


def test_valid_config_bundle_with_multiple_entries() -> None:
    snapshots = (
        _snapshot("cfg-b", kind=ConfigSnapshotKind.EVALUATION_CONFIG),
        _snapshot("cfg-a", kind=ConfigSnapshotKind.DATASET_CONFIG),
    )
    bundle = _bundle(snapshots=snapshots)
    expected_json = (
        '{"entries":[{"config_id":"cfg-a","kind":"DATASET_CONFIG","sha256":"'
        + snapshots[1].sha256
        + '"},{"config_id":"cfg-b","kind":"EVALUATION_CONFIG","sha256":"'
        + snapshots[0].sha256
        + '"}]}'
    )
    assert [entry.config_id for entry in bundle.entries] == ["cfg-a", "cfg-b"]
    assert bundle.canonical_json == expected_json


def test_config_bundle_rejects_duplicate_config_id() -> None:
    snapshot = _snapshot("cfg-a")
    with pytest.raises(ValueError, match="duplicate config_id"):
        CanonicalConfigFingerprinter().bundle(
            bundle_id="bundle-1",
            snapshots=(snapshot, snapshot),
            created_at=_utc(),
        )
    with pytest.raises(ValidationError, match="duplicate config_id"):
        ConfigBundle(
            bundle_id="bundle-1",
            created_at=_utc(),
            entries=(_entry(snapshot), _entry(snapshot)),
            canonical_json='{"entries":[]}',
            sha256=_sha('{"entries":[]}'),
        )


def test_config_bundle_rejects_mismatched_sha_and_noncanonical_json() -> None:
    bundle = _bundle()
    with pytest.raises(ValidationError, match="sha256"):
        ConfigBundle(
            bundle_id=bundle.bundle_id,
            created_at=bundle.created_at,
            entries=bundle.entries,
            canonical_json=bundle.canonical_json,
            sha256=_sha('{"entries":[]}'),
        )
    pretty = '{ "entries": [] }'
    with pytest.raises(ValidationError, match="canonical JSON"):
        ConfigBundle(
            bundle_id="bundle-2",
            created_at=_utc(),
            entries=bundle.entries,
            canonical_json=pretty,
            sha256=_sha(pretty),
        )


def test_config_bundle_rejects_canonical_json_not_matching_entries() -> None:
    bundle = _bundle()
    wrong_json = '{"entries":[]}'
    with pytest.raises(ValidationError, match="entries"):
        ConfigBundle(
            bundle_id=bundle.bundle_id,
            created_at=bundle.created_at,
            entries=bundle.entries,
            canonical_json=wrong_json,
            sha256=_sha(wrong_json),
        )


def test_fingerprinter_bundle_is_order_independent_and_changes_with_child_sha() -> None:
    fingerprinter = CanonicalConfigFingerprinter()
    first = _snapshot("cfg-a", payload={"fee": Decimal("1.0")})
    second = _snapshot("cfg-b", payload={"fee": Decimal("2.0")})
    bundle_a = fingerprinter.bundle(
        bundle_id="bundle-1",
        snapshots=(first, second),
        created_at=_utc(),
    )
    bundle_b = fingerprinter.bundle(
        bundle_id="bundle-1",
        snapshots=(second, first),
        created_at=_utc(),
    )
    changed = _snapshot("cfg-b", payload={"fee": Decimal("3.0")})
    bundle_changed = fingerprinter.bundle(
        bundle_id="bundle-1",
        snapshots=(first, changed),
        created_at=_utc(),
    )

    assert bundle_a.canonical_json == bundle_b.canonical_json
    assert bundle_a.sha256 == bundle_b.sha256
    assert bundle_a.sha256 != bundle_changed.sha256


def test_config_bundle_store_round_trip_conflicts_and_revalidation() -> None:
    _: ConfigBundleStorePort = InMemoryConfigBundleStore()
    store = InMemoryConfigBundleStore()
    first = _bundle("bundle-b", created_at=_utc(2, 1))
    second = _bundle("bundle-a", created_at=_utc(2, 0))
    same_hash = _bundle(
        "bundle-same-hash",
        snapshots=(_snapshot(),),
        created_at=_utc(2, 2),
    )
    store.save(first)
    store.save(first)
    store.save(second)
    store.save(same_hash)
    assert store.load("bundle-b") == first
    assert [bundle.bundle_id for bundle in store.list_all()] == [
        "bundle-a",
        "bundle-b",
        "bundle-same-hash",
    ]

    with pytest.raises(ValueError, match="bundle_id conflict"):
        store.save(_bundle("bundle-b", snapshots=(_snapshot("cfg-other"),)))

    invalid_json = first.model_copy(update={"canonical_json": '{ "entries": [] }'})
    with pytest.raises(ValidationError, match="canonical JSON"):
        store.save(invalid_json)

    invalid_sha = first.model_copy(update={"sha256": _sha('{"entries":[]}')})
    with pytest.raises(ValidationError, match="sha256"):
        store.save(invalid_sha)


def test_registry_composes_and_loads_config_bundle() -> None:
    config_store = InMemoryConfigSnapshotStore()
    bundle_store = InMemoryConfigBundleStore()
    registry = LocalExperimentRegistry(
        experiment_store=InMemoryExperimentDefinitionStore(),
        config_store=config_store,
        lineage_store=InMemoryRunLineageStore(),
        config_bundle_store=bundle_store,
        now=lambda: _utc(4),
    )
    first = _snapshot("cfg-a")
    second = _snapshot("cfg-b")
    config_store.save(first)
    config_store.save(second)

    bundle = registry.compose_config_bundle(
        bundle_id="bundle-1",
        config_ids=("cfg-b", "cfg-a"),
        description="Composed config.",
    )
    reversed_bundle = registry.compose_config_bundle(
        bundle_id="bundle-2",
        config_ids=("cfg-a", "cfg-b"),
    )

    assert registry.load_config_bundle("bundle-1") == bundle
    assert bundle.sha256 == reversed_bundle.sha256
    assert [entry.config_id for entry in bundle.entries] == ["cfg-a", "cfg-b"]


def test_registry_bundle_errors_and_prebuilt_registration() -> None:
    registry_without_store = LocalExperimentRegistry(
        experiment_store=InMemoryExperimentDefinitionStore(),
        config_store=InMemoryConfigSnapshotStore(),
        lineage_store=InMemoryRunLineageStore(),
    )
    with pytest.raises(ValueError, match="config_bundle_store"):
        registry_without_store.compose_config_bundle(
            bundle_id="bundle-1",
            config_ids=("cfg-a",),
        )

    config_store = InMemoryConfigSnapshotStore()
    bundle_store = InMemoryConfigBundleStore()
    registry = LocalExperimentRegistry(
        experiment_store=InMemoryExperimentDefinitionStore(),
        config_store=config_store,
        lineage_store=InMemoryRunLineageStore(),
        config_bundle_store=bundle_store,
    )
    snapshot = _snapshot("cfg-a")
    config_store.save(snapshot)
    with pytest.raises(KeyError, match="config snapshot"):
        registry.compose_config_bundle(bundle_id="bundle-1", config_ids=("missing",))
    with pytest.raises(ValueError, match="duplicate config_id"):
        registry.compose_config_bundle(bundle_id="bundle-1", config_ids=("cfg-a", "cfg-a"))

    bundle = _bundle(snapshots=(snapshot,))
    registry.register_config_bundle(bundle)
    assert bundle_store.load(bundle.bundle_id) == bundle

    invalid = bundle.model_copy(update={"sha256": _sha('{"entries":[]}')})
    with pytest.raises(ValidationError, match="sha256"):
        registry.register_config_bundle(invalid)
