from __future__ import annotations

from datetime import UTC, datetime

import pytest

from futures_bot.domain.asset_semantics import CollateralMode, ContractPayoffKind
from futures_bot.domain.venue_capability_sources import (
    VenueCapabilitySourceFetchMode,
    VenueCapabilitySourceTrust,
)
from futures_bot.domain.venue_registry import (
    VenueDescriptor,
    VenueOperatingEnvironment,
    VenueProductDescriptor,
    VenueProductFamily,
    VenueRegistrySnapshot,
    VenueSourceTemplate,
    VenueSourceTemplateKind,
    VenueSupportStatus,
)


def _product() -> VenueProductDescriptor:
    return VenueProductDescriptor(
        venue_id="binance",
        environment=VenueOperatingEnvironment.MAINNET,
        product_family=VenueProductFamily.LINEAR_PERPETUAL,
        support_status=VenueSupportStatus.SUPPORTED_FOR_RESEARCH,
        supported_contract_payoff_kinds=(ContractPayoffKind.LINEAR,),
        supported_collateral_modes=(CollateralMode.SINGLE_ASSET,),
        metadata={"metadata_only": True},
    )


def _source_template() -> VenueSourceTemplate:
    return VenueSourceTemplate(
        venue_id="BINANCE",
        environment=VenueOperatingEnvironment.MAINNET,
        product_family=VenueProductFamily.LINEAR_PERPETUAL,
        template_kind=VenueSourceTemplateKind.MANUAL_OFFICIAL_IMPORT,
        source_trust=VenueCapabilitySourceTrust.MANUAL_REVIEW_REQUIRED,
        reference_label="Binance manual official import",
        requires_human_review=True,
        metadata={"metadata_only": True},
    )


def _descriptor(
    *,
    metadata: dict[str, object] | None = None,
) -> VenueDescriptor:
    return VenueDescriptor(
        venue_id="BINANCE",
        display_name="Binance",
        support_status=VenueSupportStatus.SUPPORTED_FOR_RESEARCH,
        environments=(VenueOperatingEnvironment.MAINNET,),
        products=(_product(),),
        source_templates=(_source_template(),),
        metadata=metadata or {"metadata_only": True},
    )


def test_venue_product_descriptor_deterministic_id() -> None:
    first = _product()
    second = _product()

    assert first.product_descriptor_id == second.product_descriptor_id
    assert first.venue_id == "BINANCE"


def test_venue_product_descriptor_id_ignores_mode_order() -> None:
    first = VenueProductDescriptor(
        venue_id="BINANCE",
        environment=VenueOperatingEnvironment.MAINNET,
        product_family=VenueProductFamily.LINEAR_PERPETUAL,
        support_status=VenueSupportStatus.SUPPORTED_FOR_RESEARCH,
        supported_contract_payoff_kinds=(
            ContractPayoffKind.LINEAR,
            ContractPayoffKind.QUANTO,
        ),
        supported_collateral_modes=(
            CollateralMode.MULTI_ASSET,
            CollateralMode.SINGLE_ASSET,
        ),
        metadata={},
    )
    second = VenueProductDescriptor(
        venue_id="BINANCE",
        environment=VenueOperatingEnvironment.MAINNET,
        product_family=VenueProductFamily.LINEAR_PERPETUAL,
        support_status=VenueSupportStatus.SUPPORTED_FOR_RESEARCH,
        supported_contract_payoff_kinds=(
            ContractPayoffKind.QUANTO,
            ContractPayoffKind.LINEAR,
        ),
        supported_collateral_modes=(
            CollateralMode.SINGLE_ASSET,
            CollateralMode.MULTI_ASSET,
        ),
        metadata={},
    )

    assert first.product_descriptor_id == second.product_descriptor_id
    assert first.supported_contract_payoff_kinds == (
        ContractPayoffKind.LINEAR,
        ContractPayoffKind.QUANTO,
    )
    assert first.supported_collateral_modes == (
        CollateralMode.MULTI_ASSET,
        CollateralMode.SINGLE_ASSET,
    )


def test_venue_product_descriptor_rejects_duplicate_modes() -> None:
    with pytest.raises(ValueError, match="supported_contract_payoff_kinds"):
        VenueProductDescriptor(
            venue_id="BINANCE",
            environment=VenueOperatingEnvironment.MAINNET,
            product_family=VenueProductFamily.LINEAR_PERPETUAL,
            support_status=VenueSupportStatus.SUPPORTED_FOR_RESEARCH,
            supported_contract_payoff_kinds=(
                ContractPayoffKind.LINEAR,
                ContractPayoffKind.LINEAR,
            ),
            supported_collateral_modes=(CollateralMode.SINGLE_ASSET,),
            metadata={},
        )

    with pytest.raises(ValueError, match="supported_collateral_modes"):
        VenueProductDescriptor(
            venue_id="BINANCE",
            environment=VenueOperatingEnvironment.MAINNET,
            product_family=VenueProductFamily.LINEAR_PERPETUAL,
            support_status=VenueSupportStatus.SUPPORTED_FOR_RESEARCH,
            supported_contract_payoff_kinds=(ContractPayoffKind.LINEAR,),
            supported_collateral_modes=(
                CollateralMode.SINGLE_ASSET,
                CollateralMode.SINGLE_ASSET,
            ),
            metadata={},
        )


def test_venue_product_descriptor_rejects_empty_venue_id() -> None:
    with pytest.raises(ValueError, match="venue_id"):
        VenueProductDescriptor(
            venue_id=" ",
            environment=VenueOperatingEnvironment.MAINNET,
            product_family=VenueProductFamily.LINEAR_PERPETUAL,
            support_status=VenueSupportStatus.SUPPORTED_FOR_RESEARCH,
            supported_contract_payoff_kinds=(ContractPayoffKind.LINEAR,),
            supported_collateral_modes=(CollateralMode.SINGLE_ASSET,),
            metadata={},
        )


def test_venue_product_descriptor_rejects_empty_modes_when_supported() -> None:
    with pytest.raises(ValueError, match="payoff kinds"):
        VenueProductDescriptor(
            venue_id="BINANCE",
            environment=VenueOperatingEnvironment.MAINNET,
            product_family=VenueProductFamily.LINEAR_PERPETUAL,
            support_status=VenueSupportStatus.SUPPORTED_FOR_RESEARCH,
            supported_contract_payoff_kinds=(),
            supported_collateral_modes=(CollateralMode.SINGLE_ASSET,),
            metadata={},
        )


def test_supported_product_descriptor_rejects_unknown_semantics() -> None:
    with pytest.raises(ValueError, match="known product_family"):
        VenueProductDescriptor(
            venue_id="BINANCE",
            environment=VenueOperatingEnvironment.MAINNET,
            product_family=VenueProductFamily.UNKNOWN,
            support_status=VenueSupportStatus.SUPPORTED_FOR_RESEARCH,
            supported_contract_payoff_kinds=(ContractPayoffKind.LINEAR,),
            supported_collateral_modes=(CollateralMode.SINGLE_ASSET,),
            metadata={},
        )

    with pytest.raises(ValueError, match="known payoff"):
        VenueProductDescriptor(
            venue_id="BINANCE",
            environment=VenueOperatingEnvironment.MAINNET,
            product_family=VenueProductFamily.LINEAR_PERPETUAL,
            support_status=VenueSupportStatus.SUPPORTED_FOR_RESEARCH,
            supported_contract_payoff_kinds=(ContractPayoffKind.UNKNOWN,),
            supported_collateral_modes=(CollateralMode.SINGLE_ASSET,),
            metadata={},
        )

    with pytest.raises(ValueError, match="known collateral"):
        VenueProductDescriptor(
            venue_id="BINANCE",
            environment=VenueOperatingEnvironment.MAINNET,
            product_family=VenueProductFamily.LINEAR_PERPETUAL,
            support_status=VenueSupportStatus.SUPPORTED_FOR_RESEARCH,
            supported_contract_payoff_kinds=(ContractPayoffKind.LINEAR,),
            supported_collateral_modes=(CollateralMode.UNKNOWN,),
            metadata={},
        )

    with pytest.raises(ValueError, match="known environment"):
        VenueProductDescriptor(
            venue_id="BINANCE",
            environment=VenueOperatingEnvironment.UNKNOWN,
            product_family=VenueProductFamily.LINEAR_PERPETUAL,
            support_status=VenueSupportStatus.SUPPORTED_FOR_RESEARCH,
            supported_contract_payoff_kinds=(ContractPayoffKind.LINEAR,),
            supported_collateral_modes=(CollateralMode.SINGLE_ASSET,),
            metadata={},
        )

    with pytest.raises(ValueError, match="collateral modes"):
        VenueProductDescriptor(
            venue_id="BINANCE",
            environment=VenueOperatingEnvironment.MAINNET,
            product_family=VenueProductFamily.LINEAR_PERPETUAL,
            support_status=VenueSupportStatus.SUPPORTED_FOR_RESEARCH,
            supported_contract_payoff_kinds=(ContractPayoffKind.LINEAR,),
            supported_collateral_modes=(),
            metadata={},
        )


def test_venue_product_descriptor_allows_empty_modes_when_deferred() -> None:
    descriptor = VenueProductDescriptor(
        venue_id="YOUHODLER",
        environment=VenueOperatingEnvironment.UNKNOWN,
        product_family=VenueProductFamily.UNKNOWN,
        support_status=VenueSupportStatus.DEFERRED,
        supported_contract_payoff_kinds=(),
        supported_collateral_modes=(),
        metadata={},
    )

    assert descriptor.support_status is VenueSupportStatus.DEFERRED


def test_venue_source_template_deterministic_id_and_conversion() -> None:
    first = _source_template()
    second = _source_template()

    assert first.source_template_id == second.source_template_id

    source_descriptor = first.to_source_descriptor(
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        official_owner="Binance",
    )

    assert not hasattr(source_descriptor, "accepted_for_execution")
    assert source_descriptor.fetch_mode is VenueCapabilitySourceFetchMode.MANUAL
    assert source_descriptor.trust is VenueCapabilitySourceTrust.MANUAL_REVIEW_REQUIRED
    assert source_descriptor.metadata["source_template_id"] == str(first.source_template_id)


def test_venue_source_template_rejects_empty_reference_label() -> None:
    with pytest.raises(ValueError, match="reference_label"):
        VenueSourceTemplate(
            venue_id="BINANCE",
            environment=VenueOperatingEnvironment.MAINNET,
            template_kind=VenueSourceTemplateKind.OFFICIAL_DOCS,
            source_trust=VenueCapabilitySourceTrust.MANUAL_REVIEW_REQUIRED,
            reference_label="",
            requires_human_review=True,
            metadata={},
        )


def test_venue_descriptor_deterministic_id() -> None:
    first = _descriptor()
    second = _descriptor()

    assert first.descriptor_id == second.descriptor_id


def test_venue_descriptor_id_ignores_environment_order() -> None:
    first = VenueDescriptor(
        venue_id="BINANCE",
        display_name="Binance",
        support_status=VenueSupportStatus.MODELLED_NOT_EXECUTION_READY,
        environments=(
            VenueOperatingEnvironment.TESTNET,
            VenueOperatingEnvironment.MAINNET,
        ),
        products=(),
        source_templates=(),
        metadata={},
    )
    second = VenueDescriptor(
        venue_id="BINANCE",
        display_name="Binance",
        support_status=VenueSupportStatus.MODELLED_NOT_EXECUTION_READY,
        environments=(
            VenueOperatingEnvironment.MAINNET,
            VenueOperatingEnvironment.TESTNET,
        ),
        products=(),
        source_templates=(),
        metadata={},
    )

    assert first.descriptor_id == second.descriptor_id
    assert first.environments == (
        VenueOperatingEnvironment.MAINNET,
        VenueOperatingEnvironment.TESTNET,
    )


def test_venue_descriptor_rejects_duplicate_environments() -> None:
    with pytest.raises(ValueError, match="environments"):
        VenueDescriptor(
            venue_id="BINANCE",
            display_name="Binance",
            support_status=VenueSupportStatus.MODELLED_NOT_EXECUTION_READY,
            environments=(
                VenueOperatingEnvironment.MAINNET,
                VenueOperatingEnvironment.MAINNET,
            ),
            products=(),
            source_templates=(),
            metadata={},
        )


def test_supported_venue_descriptor_requires_known_ready_research_inputs() -> None:
    with pytest.raises(ValueError, match="known environments"):
        VenueDescriptor(
            venue_id="BINANCE",
            display_name="Binance",
            support_status=VenueSupportStatus.SUPPORTED_FOR_RESEARCH,
            environments=(VenueOperatingEnvironment.UNKNOWN,),
            products=(_product(),),
            source_templates=(),
            metadata={},
        )

    with pytest.raises(ValueError, match="product descriptors"):
        VenueDescriptor(
            venue_id="BINANCE",
            display_name="Binance",
            support_status=VenueSupportStatus.SUPPORTED_FOR_RESEARCH,
            environments=(VenueOperatingEnvironment.MAINNET,),
            products=(),
            source_templates=(_source_template(),),
            metadata={},
        )

    with pytest.raises(ValueError, match="source templates"):
        VenueDescriptor(
            venue_id="BINANCE",
            display_name="Binance",
            support_status=VenueSupportStatus.SUPPORTED_FOR_RESEARCH,
            environments=(VenueOperatingEnvironment.MAINNET,),
            products=(_product(),),
            source_templates=(),
            metadata={},
        )


def test_not_ready_venue_descriptor_rejects_supported_products() -> None:
    with pytest.raises(ValueError, match="cannot contain supported products"):
        VenueDescriptor(
            venue_id="BINANCE",
            display_name="Binance",
            support_status=VenueSupportStatus.DEFERRED,
            environments=(VenueOperatingEnvironment.MAINNET,),
            products=(_product(),),
            source_templates=(),
            metadata={},
        )


def test_product_scoped_source_templates_must_match_product_descriptor() -> None:
    mismatched_template = VenueSourceTemplate(
        venue_id="BINANCE",
        environment=VenueOperatingEnvironment.MAINNET,
        product_family=VenueProductFamily.INVERSE_PERPETUAL,
        template_kind=VenueSourceTemplateKind.OFFICIAL_DOCS,
        source_trust=VenueCapabilitySourceTrust.MANUAL_REVIEW_REQUIRED,
        reference_label="Binance inverse docs",
        requires_human_review=True,
        metadata={},
    )

    with pytest.raises(ValueError, match="product_family"):
        VenueDescriptor(
            venue_id="BINANCE",
            display_name="Binance",
            support_status=VenueSupportStatus.SUPPORTED_FOR_RESEARCH,
            environments=(VenueOperatingEnvironment.MAINNET,),
            products=(_product(),),
            source_templates=(mismatched_template,),
            metadata={},
        )


def test_venue_descriptor_rejects_duplicate_product_descriptors() -> None:
    product = _product()
    with pytest.raises(ValueError, match="duplicate product descriptors"):
        VenueDescriptor(
            venue_id="BINANCE",
            display_name="Binance",
            support_status=VenueSupportStatus.SUPPORTED_FOR_RESEARCH,
            environments=(VenueOperatingEnvironment.MAINNET,),
            products=(product, product),
            source_templates=(_source_template(),),
            metadata={},
        )


def test_venue_descriptor_rejects_duplicate_source_templates() -> None:
    template = _source_template()
    with pytest.raises(ValueError, match="duplicate source templates"):
        VenueDescriptor(
            venue_id="BINANCE",
            display_name="Binance",
            support_status=VenueSupportStatus.SUPPORTED_FOR_RESEARCH,
            environments=(VenueOperatingEnvironment.MAINNET,),
            products=(_product(),),
            source_templates=(template, template),
            metadata={},
        )


def test_venue_descriptor_metadata_json_compatible() -> None:
    with pytest.raises(ValueError, match="JSON-compatible"):
        VenueDescriptor(
            venue_id="BINANCE",
            display_name="Binance",
            support_status=VenueSupportStatus.SUPPORTED_FOR_RESEARCH,
            environments=(VenueOperatingEnvironment.MAINNET,),
            products=(_product(),),
            source_templates=(_source_template(),),
            metadata={"bad": object()},
        )


def test_metadata_cannot_be_mutated_after_construction() -> None:
    metadata = {"nested": {"value": 1}, "items": [{"name": "alpha"}]}
    product = VenueProductDescriptor(
        venue_id="BINANCE",
        environment=VenueOperatingEnvironment.MAINNET,
        product_family=VenueProductFamily.LINEAR_PERPETUAL,
        support_status=VenueSupportStatus.SUPPORTED_FOR_RESEARCH,
        supported_contract_payoff_kinds=(ContractPayoffKind.LINEAR,),
        supported_collateral_modes=(CollateralMode.SINGLE_ASSET,),
        metadata=metadata,
    )
    template = VenueSourceTemplate(
        venue_id="BINANCE",
        environment=VenueOperatingEnvironment.MAINNET,
        product_family=VenueProductFamily.LINEAR_PERPETUAL,
        template_kind=VenueSourceTemplateKind.MANUAL_OFFICIAL_IMPORT,
        source_trust=VenueCapabilitySourceTrust.MANUAL_REVIEW_REQUIRED,
        reference_label="Binance manual official import",
        requires_human_review=True,
        metadata=metadata,
    )
    descriptor = _descriptor(metadata=metadata)
    snapshot = VenueRegistrySnapshot(descriptors=(descriptor,), metadata=metadata)

    for model in (product, template, descriptor, snapshot):
        with pytest.raises(TypeError):
            model.metadata["new"] = "blocked"
        with pytest.raises(TypeError):
            model.metadata["nested"]["value"] = 2
        with pytest.raises(AttributeError):
            model.metadata["items"].append({"name": "beta"})
        with pytest.raises(TypeError):
            model.metadata["items"][0]["name"] = "beta"

    metadata["nested"]["value"] = 99
    assert product.metadata["nested"]["value"] == 1


def test_metadata_model_dump_json_returns_normal_json_structures() -> None:
    descriptor = _descriptor(
        metadata={"nested": {"value": 1}, "items": [{"name": "alpha"}]},
    )

    dumped = descriptor.model_dump(mode="json")

    assert dumped["metadata"] == {
        "nested": {"value": 1},
        "items": [{"name": "alpha"}],
    }
    assert isinstance(dumped["metadata"], dict)
    assert isinstance(dumped["metadata"]["nested"], dict)
    assert isinstance(dumped["metadata"]["items"], list)
