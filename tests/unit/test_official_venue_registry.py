from __future__ import annotations

from futures_bot.domain.asset_semantics import CollateralMode, ContractPayoffKind
from futures_bot.domain.venue_capabilities import VenueCapabilitySnapshot
from futures_bot.domain.venue_registry import (
    VenueOperatingEnvironment,
    VenueProductFamily,
    VenueSupportStatus,
)
from futures_bot.venue_capabilities.registry import (
    build_default_official_venue_descriptor_registry,
)


def test_binance_has_mainnet_product_descriptors() -> None:
    registry = build_default_official_venue_descriptor_registry()

    products = registry.list_product_descriptors(
        "BINANCE",
        environment=VenueOperatingEnvironment.MAINNET,
    )

    assert products
    assert {product.product_family for product in products} >= {
        VenueProductFamily.LINEAR_PERPETUAL,
        VenueProductFamily.INVERSE_PERPETUAL,
        VenueProductFamily.COIN_MARGINED_PERPETUAL,
    }


def test_linear_and_coin_or_inverse_products_are_represented() -> None:
    registry = build_default_official_venue_descriptor_registry()
    products = registry.list_product_descriptors("BINANCE")

    linear = next(
        product
        for product in products
        if product.product_family is VenueProductFamily.LINEAR_PERPETUAL
    )
    coin_or_inverse = tuple(
        product
        for product in products
        if product.product_family
        in {
            VenueProductFamily.INVERSE_PERPETUAL,
            VenueProductFamily.COIN_MARGINED_PERPETUAL,
        }
    )

    assert ContractPayoffKind.LINEAR in linear.supported_contract_payoff_kinds
    assert coin_or_inverse
    assert any(
        ContractPayoffKind.INVERSE in product.supported_contract_payoff_kinds
        for product in coin_or_inverse
    )
    assert any(
        CollateralMode.CROSS_COLLATERAL in product.supported_collateral_modes
        for product in coin_or_inverse
    )


def test_youhodler_if_present_is_deferred_not_execution_ready() -> None:
    registry = build_default_official_venue_descriptor_registry()
    descriptor = registry.get("youhodler")

    assert descriptor is not None
    assert descriptor.support_status in {
        VenueSupportStatus.DEFERRED,
        VenueSupportStatus.NEEDS_HUMAN_REVIEW,
        VenueSupportStatus.MODELLED_NOT_EXECUTION_READY,
    }
    assert descriptor.products == ()
    assert descriptor.metadata["execution_ready"] is False


def test_registry_does_not_create_capability_snapshots() -> None:
    registry = build_default_official_venue_descriptor_registry()

    assert not any(
        isinstance(descriptor, VenueCapabilitySnapshot)
        for descriptor in registry.list_all()
    )
    assert all(
        descriptor.metadata["capability_snapshot_created"] is False
        for descriptor in registry.list_all()
        if descriptor.venue_id != "YOUHODLER"
    )


def test_registry_descriptors_are_known_without_being_executable() -> None:
    registry = build_default_official_venue_descriptor_registry()

    for venue_id in ("BINANCE", "KUCOIN", "COINEX", "MEXC", "PHEMEX"):
        descriptor = registry.require(venue_id)

        assert descriptor.support_status is VenueSupportStatus.SUPPORTED_FOR_RESEARCH
        assert descriptor.metadata["execution_ready"] is False


def test_default_registry_has_no_unknown_modes_under_supported_products() -> None:
    registry = build_default_official_venue_descriptor_registry()

    for descriptor in registry.list_all():
        for product in descriptor.products:
            if product.support_status is not VenueSupportStatus.SUPPORTED_FOR_RESEARCH:
                continue
            assert ContractPayoffKind.UNKNOWN not in product.supported_contract_payoff_kinds
            assert CollateralMode.UNKNOWN not in product.supported_collateral_modes
