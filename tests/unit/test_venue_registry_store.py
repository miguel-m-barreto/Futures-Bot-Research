from __future__ import annotations

import pytest

from futures_bot.domain.venue_registry import (
    VenueDescriptorNotFoundError,
    VenueOperatingEnvironment,
    VenueProductFamily,
    VenueSupportStatus,
)
from futures_bot.venue_capabilities.registry import (
    DeterministicVenueDescriptorRegistry,
    build_default_official_venue_descriptor_registry,
)


def test_default_registry_contains_target_venues() -> None:
    registry = build_default_official_venue_descriptor_registry()

    venue_ids = {descriptor.venue_id for descriptor in registry.list_all()}

    assert {"BINANCE", "KUCOIN", "COINEX", "MEXC", "PHEMEX"}.issubset(venue_ids)


def test_duplicate_exact_venue_descriptors_are_rejected() -> None:
    registry = build_default_official_venue_descriptor_registry()
    descriptor = registry.require("BINANCE")

    with pytest.raises(ValueError, match="duplicate venue descriptors"):
        DeterministicVenueDescriptorRegistry((descriptor, descriptor))


def test_venue_lookups_are_case_insensitive() -> None:
    registry = build_default_official_venue_descriptor_registry()

    assert registry.get("binance") == registry.get("BINANCE")
    assert registry.require("KuCoin").venue_id == "KUCOIN"


def test_list_all_is_deterministic() -> None:
    registry = build_default_official_venue_descriptor_registry()

    venue_ids = tuple(descriptor.venue_id for descriptor in registry.list_all())

    assert venue_ids == tuple(sorted(venue_ids))


def test_unknown_venue_lookup_and_require_are_deterministic() -> None:
    registry = build_default_official_venue_descriptor_registry()

    assert registry.get("missing") is None
    with pytest.raises(VenueDescriptorNotFoundError, match="MISSING"):
        registry.require("missing")


def test_filters_by_support_status_and_environment() -> None:
    registry = build_default_official_venue_descriptor_registry()

    research = registry.list_by_support_status(VenueSupportStatus.SUPPORTED_FOR_RESEARCH)
    mainnet = registry.list_by_environment(VenueOperatingEnvironment.MAINNET)

    assert {descriptor.venue_id for descriptor in research} >= {
        "BINANCE",
        "KUCOIN",
        "COINEX",
        "MEXC",
        "PHEMEX",
    }
    assert {descriptor.venue_id for descriptor in mainnet} >= {
        "BINANCE",
        "KUCOIN",
        "COINEX",
        "MEXC",
        "PHEMEX",
    }


def test_list_product_descriptors_filters_by_environment_and_family() -> None:
    registry = build_default_official_venue_descriptor_registry()

    products = registry.list_product_descriptors(
        "binance",
        environment=VenueOperatingEnvironment.MAINNET,
        product_family=VenueProductFamily.LINEAR_PERPETUAL,
    )

    assert len(products) == 1
    assert products[0].venue_id == "BINANCE"
    assert products[0].product_family is VenueProductFamily.LINEAR_PERPETUAL


def test_list_source_templates_filters_by_environment_and_family() -> None:
    registry = build_default_official_venue_descriptor_registry()

    templates = registry.list_source_templates(
        "binance",
        environment=VenueOperatingEnvironment.MAINNET,
        product_family=VenueProductFamily.LINEAR_PERPETUAL,
    )

    assert templates
    assert all(template.venue_id == "BINANCE" for template in templates)
    assert all(template.requires_human_review for template in templates)
