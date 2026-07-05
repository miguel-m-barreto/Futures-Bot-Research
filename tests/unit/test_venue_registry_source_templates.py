from __future__ import annotations

from datetime import UTC, datetime

from futures_bot.domain.venue_capability_sources import (
    VenueCapabilitySourceDescriptor,
    VenueCapabilitySourceTrust,
)
from futures_bot.domain.venue_registry import (
    VenueOperatingEnvironment,
    VenueProductFamily,
    VenueSourceTemplate,
    VenueSourceTemplateKind,
)
from futures_bot.venue_capabilities.registry import (
    build_default_official_venue_descriptor_registry,
)


def test_each_supported_venue_has_source_template_requiring_review() -> None:
    registry = build_default_official_venue_descriptor_registry()

    for venue_id in ("BINANCE", "KUCOIN", "COINEX", "MEXC", "PHEMEX"):
        templates = registry.list_source_templates(venue_id)

        assert templates
        assert any(template.requires_human_review for template in templates)
        assert {
            VenueSourceTemplateKind.OFFICIAL_DOCS,
            VenueSourceTemplateKind.OFFICIAL_REST_API_REFERENCE,
            VenueSourceTemplateKind.MANUAL_OFFICIAL_IMPORT,
        }.issubset({template.template_kind for template in templates})


def test_source_templates_are_metadata_only() -> None:
    registry = build_default_official_venue_descriptor_registry()

    for template in registry.list_source_templates("BINANCE"):
        assert template.metadata["metadata_only"] is True
        assert template.metadata["fetches_remote_content"] is False
        assert template.metadata["creates_source_record"] is False
        assert template.metadata["creates_capability_snapshot"] is False


def test_source_templates_do_not_imply_accepted_source_provenance() -> None:
    registry = build_default_official_venue_descriptor_registry()

    for template in registry.list_source_templates("BINANCE"):
        descriptor = template.to_source_descriptor(
            created_at=datetime(2026, 1, 1, tzinfo=UTC)
        )

        assert isinstance(descriptor, VenueCapabilitySourceDescriptor)
        assert descriptor.trust is VenueCapabilitySourceTrust.MANUAL_REVIEW_REQUIRED
        assert not hasattr(descriptor, "payload")
        assert not hasattr(descriptor, "accepted_for_execution")


def test_source_template_conversion_deep_thaws_nested_metadata() -> None:
    template = VenueSourceTemplate(
        venue_id="BINANCE",
        environment=VenueOperatingEnvironment.MAINNET,
        product_family=VenueProductFamily.LINEAR_PERPETUAL,
        template_kind=VenueSourceTemplateKind.MANUAL_OFFICIAL_IMPORT,
        source_trust=VenueCapabilitySourceTrust.MANUAL_REVIEW_REQUIRED,
        reference_label="Binance nested manual official import",
        requires_human_review=True,
        metadata={"nested": {"values": [1, 2], "flag": True}},
    )

    assert template.metadata["nested"]["values"] == (1, 2)
    try:
        template.metadata["nested"]["values"].append(3)
    except AttributeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("nested metadata list remained mutable")

    source_descriptor = template.to_source_descriptor(
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    dumped = source_descriptor.model_dump(mode="json")

    template_metadata = dumped["metadata"]["template_metadata"]
    assert template_metadata == {"nested": {"values": [1, 2], "flag": True}}
    assert isinstance(template_metadata, dict)
    assert isinstance(template_metadata["nested"], dict)
    assert isinstance(template_metadata["nested"]["values"], list)


def test_manual_import_source_template_can_be_represented() -> None:
    template = VenueSourceTemplate(
        venue_id="PHEMEX",
        environment=VenueOperatingEnvironment.MAINNET,
        product_family=VenueProductFamily.LINEAR_PERPETUAL,
        template_kind=VenueSourceTemplateKind.MANUAL_OFFICIAL_IMPORT,
        source_trust=VenueCapabilitySourceTrust.MANUAL_REVIEW_REQUIRED,
        reference_label="Phemex reviewed manual official import",
        requires_human_review=True,
        metadata={"metadata_only": True},
    )

    assert template.template_kind is VenueSourceTemplateKind.MANUAL_OFFICIAL_IMPORT
    assert template.requires_human_review is True


def test_source_template_listing_does_not_fetch_urls() -> None:
    registry = build_default_official_venue_descriptor_registry()

    templates = registry.list_source_templates(
        "MEXC",
        environment=VenueOperatingEnvironment.MAINNET,
    )

    assert templates
    assert all(template.metadata["fetches_remote_content"] is False for template in templates)
    assert all("://" not in template.reference_label for template in templates)
