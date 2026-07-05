from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from futures_bot.domain.asset_semantics import CollateralMode, ContractPayoffKind
from futures_bot.domain.venue_capability_sources import VenueCapabilitySourceTrust
from futures_bot.domain.venue_registry import (
    VenueDescriptor,
    VenueDescriptorNotFoundError,
    VenueOperatingEnvironment,
    VenueProductDescriptor,
    VenueProductFamily,
    VenueSourceTemplate,
    VenueSourceTemplateKind,
    VenueSupportStatus,
    canonical_venue_id,
)


class DeterministicVenueDescriptorRegistry:
    """Static read-only registry of known venue/product descriptor metadata."""

    def __init__(self, descriptors: Iterable[VenueDescriptor]) -> None:
        ordered = tuple(sorted(descriptors, key=lambda item: (item.venue_id, item.display_name)))
        by_venue_id: dict[str, VenueDescriptor] = {}
        for descriptor in ordered:
            if descriptor.venue_id in by_venue_id:
                raise ValueError("duplicate venue descriptors are not allowed")
            by_venue_id[descriptor.venue_id] = descriptor
        self._descriptors = tuple(by_venue_id[key] for key in sorted(by_venue_id))
        self._by_venue_id = dict(by_venue_id)

    def get(self, venue_id: str) -> VenueDescriptor | None:
        return self._by_venue_id.get(canonical_venue_id(venue_id))

    def require(self, venue_id: str) -> VenueDescriptor:
        descriptor = self.get(venue_id)
        if descriptor is None:
            raise VenueDescriptorNotFoundError(
                f"venue descriptor not found: {canonical_venue_id(venue_id)}"
            )
        return descriptor

    def list_all(self) -> tuple[VenueDescriptor, ...]:
        return self._descriptors

    def list_by_support_status(
        self,
        support_status: VenueSupportStatus,
    ) -> tuple[VenueDescriptor, ...]:
        return tuple(
            descriptor
            for descriptor in self._descriptors
            if descriptor.support_status is support_status
        )

    def list_by_environment(
        self,
        environment: VenueOperatingEnvironment,
    ) -> tuple[VenueDescriptor, ...]:
        return tuple(
            descriptor
            for descriptor in self._descriptors
            if environment in descriptor.environments
        )

    def list_product_descriptors(
        self,
        venue_id: str,
        *,
        environment: VenueOperatingEnvironment | None = None,
        product_family: VenueProductFamily | None = None,
    ) -> tuple[VenueProductDescriptor, ...]:
        descriptor = self.get(venue_id)
        if descriptor is None:
            return ()
        products = descriptor.products
        if environment is not None:
            products = tuple(
                product for product in products if product.environment is environment
            )
        if product_family is not None:
            products = tuple(
                product
                for product in products
                if product.product_family is product_family
            )
        return products

    def list_source_templates(
        self,
        venue_id: str,
        *,
        environment: VenueOperatingEnvironment | None = None,
        product_family: VenueProductFamily | None = None,
    ) -> tuple[VenueSourceTemplate, ...]:
        descriptor = self.get(venue_id)
        if descriptor is None:
            return ()
        templates = descriptor.source_templates
        if environment is not None:
            templates = tuple(
                template for template in templates if template.environment is environment
            )
        if product_family is not None:
            templates = tuple(
                template
                for template in templates
                if template.product_family in {None, product_family}
            )
        return templates


OfficialVenueDescriptorRegistry = DeterministicVenueDescriptorRegistry


def build_default_official_venue_descriptor_registry() -> (
    DeterministicVenueDescriptorRegistry
):
    return DeterministicVenueDescriptorRegistry(
        (
            _venue_descriptor(
                venue_id="BINANCE",
                display_name="Binance",
                products=(
                    _linear_perpetual("BINANCE"),
                    _inverse_perpetual("BINANCE"),
                    _coin_margined_perpetual("BINANCE"),
                ),
            ),
            _venue_descriptor(
                venue_id="COINEX",
                display_name="CoinEx",
                products=(_linear_perpetual("COINEX"),),
            ),
            _venue_descriptor(
                venue_id="KUCOIN",
                display_name="KuCoin",
                products=(_linear_perpetual("KUCOIN"),),
            ),
            _venue_descriptor(
                venue_id="MEXC",
                display_name="MEXC",
                products=(_linear_perpetual("MEXC"),),
            ),
            _venue_descriptor(
                venue_id="PHEMEX",
                display_name="Phemex",
                products=(_linear_perpetual("PHEMEX"),),
            ),
            VenueDescriptor(
                venue_id="YOUHODLER",
                display_name="YouHodler",
                support_status=VenueSupportStatus.DEFERRED,
                environments=(VenueOperatingEnvironment.UNKNOWN,),
                products=(),
                source_templates=(
                    VenueSourceTemplate(
                        venue_id="YOUHODLER",
                        environment=VenueOperatingEnvironment.UNKNOWN,
                        template_kind=VenueSourceTemplateKind.HUMAN_REVIEW_NOTE,
                        source_trust=VenueCapabilitySourceTrust.MANUAL_REVIEW_REQUIRED,
                        reference_label="Human review of execution venue status",
                        requires_human_review=True,
                        metadata={
                            "readiness": "NOT_EXECUTION_READY",
                            "reason": "NEEDS_HUMAN_REVIEW",
                        },
                    ),
                ),
                notes="Deferred pending official execution venue and trading API review.",
                metadata={
                    "execution_ready": False,
                    "registry_scope": "deferred venue identity only",
                },
            ),
        )
    )


def _venue_descriptor(
    *,
    venue_id: str,
    display_name: str,
    products: tuple[VenueProductDescriptor, ...],
) -> VenueDescriptor:
    return VenueDescriptor(
        venue_id=venue_id,
        display_name=display_name,
        support_status=VenueSupportStatus.SUPPORTED_FOR_RESEARCH,
        environments=(VenueOperatingEnvironment.MAINNET,),
        products=products,
        source_templates=_default_source_templates(venue_id),
        notes="Known venue descriptor for research identity; not execution readiness.",
        metadata={
            "execution_ready": False,
            "capability_snapshot_created": False,
            "source_record_created": False,
        },
    )


def _linear_perpetual(venue_id: str) -> VenueProductDescriptor:
    return _product(
        venue_id=venue_id,
        product_family=VenueProductFamily.LINEAR_PERPETUAL,
        payoff_kinds=(ContractPayoffKind.LINEAR,),
        collateral_modes=(CollateralMode.SINGLE_ASSET, CollateralMode.MULTI_ASSET),
    )


def _inverse_perpetual(venue_id: str) -> VenueProductDescriptor:
    return _product(
        venue_id=venue_id,
        product_family=VenueProductFamily.INVERSE_PERPETUAL,
        payoff_kinds=(ContractPayoffKind.INVERSE,),
        collateral_modes=(CollateralMode.SINGLE_ASSET,),
    )


def _coin_margined_perpetual(venue_id: str) -> VenueProductDescriptor:
    return _product(
        venue_id=venue_id,
        product_family=VenueProductFamily.COIN_MARGINED_PERPETUAL,
        payoff_kinds=(ContractPayoffKind.INVERSE,),
        collateral_modes=(CollateralMode.SINGLE_ASSET, CollateralMode.CROSS_COLLATERAL),
    )


def _product(
    *,
    venue_id: str,
    product_family: VenueProductFamily,
    payoff_kinds: tuple[ContractPayoffKind, ...],
    collateral_modes: tuple[CollateralMode, ...],
) -> VenueProductDescriptor:
    return VenueProductDescriptor(
        venue_id=venue_id,
        environment=VenueOperatingEnvironment.MAINNET,
        product_family=product_family,
        support_status=VenueSupportStatus.SUPPORTED_FOR_RESEARCH,
        supported_contract_payoff_kinds=payoff_kinds,
        supported_collateral_modes=collateral_modes,
        notes=(
            "Product family identity only; rules, fees, leverage, filters, "
            "and margins are not captured."
        ),
        metadata={
            "official_rules_captured": False,
            "accepted_for_execution": False,
        },
    )


def _default_source_templates(venue_id: str) -> tuple[VenueSourceTemplate, ...]:
    metadata = _source_template_metadata()
    return (
        VenueSourceTemplate(
            venue_id=venue_id,
            environment=VenueOperatingEnvironment.MAINNET,
            template_kind=VenueSourceTemplateKind.OFFICIAL_DOCS,
            source_trust=VenueCapabilitySourceTrust.MANUAL_REVIEW_REQUIRED,
            reference_label=f"{venue_id} official documentation reference",
            requires_human_review=True,
            metadata=metadata,
        ),
        VenueSourceTemplate(
            venue_id=venue_id,
            environment=VenueOperatingEnvironment.MAINNET,
            template_kind=VenueSourceTemplateKind.OFFICIAL_REST_API_REFERENCE,
            source_trust=VenueCapabilitySourceTrust.MANUAL_REVIEW_REQUIRED,
            reference_label=f"{venue_id} official REST API reference",
            requires_human_review=True,
            metadata=metadata,
        ),
        VenueSourceTemplate(
            venue_id=venue_id,
            environment=VenueOperatingEnvironment.MAINNET,
            template_kind=VenueSourceTemplateKind.MANUAL_OFFICIAL_IMPORT,
            source_trust=VenueCapabilitySourceTrust.MANUAL_REVIEW_REQUIRED,
            reference_label=f"{venue_id} manual official import placeholder",
            requires_human_review=True,
            metadata=metadata,
        ),
    )


def _source_template_metadata() -> Mapping[str, Any]:
    return {
        "metadata_only": True,
        "fetches_remote_content": False,
        "creates_source_record": False,
        "creates_capability_snapshot": False,
        "requires_future_capture_or_import": True,
    }
