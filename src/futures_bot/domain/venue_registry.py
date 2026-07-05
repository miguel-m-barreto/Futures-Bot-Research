from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from math import isfinite
from types import MappingProxyType
from typing import Any, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from futures_bot.domain.asset_semantics import CollateralMode, ContractPayoffKind
from futures_bot.domain.ids import (
    VenueDescriptorId,
    VenueProductDescriptorId,
    VenueRegistrySnapshotId,
    VenueSourceTemplateId,
)
from futures_bot.domain.time import ensure_aware_utc
from futures_bot.domain.venue_capability_sources import (
    VenueCapabilitySourceDescriptor,
    VenueCapabilitySourceFetchMode,
    VenueCapabilitySourceKind,
    VenueCapabilitySourceTrust,
)


class VenueOperatingEnvironment(StrEnum):
    MAINNET = "MAINNET"
    TESTNET = "TESTNET"
    SANDBOX = "SANDBOX"
    UNKNOWN = "UNKNOWN"


class VenueSupportStatus(StrEnum):
    SUPPORTED_FOR_RESEARCH = "SUPPORTED_FOR_RESEARCH"
    MODELLED_NOT_EXECUTION_READY = "MODELLED_NOT_EXECUTION_READY"
    DEFERRED = "DEFERRED"
    UNSUPPORTED = "UNSUPPORTED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"


class VenueProductFamily(StrEnum):
    SPOT = "SPOT"
    MARGIN_SPOT = "MARGIN_SPOT"
    LINEAR_PERPETUAL = "LINEAR_PERPETUAL"
    LINEAR_EXPIRING_FUTURE = "LINEAR_EXPIRING_FUTURE"
    INVERSE_PERPETUAL = "INVERSE_PERPETUAL"
    INVERSE_EXPIRING_FUTURE = "INVERSE_EXPIRING_FUTURE"
    COIN_MARGINED_PERPETUAL = "COIN_MARGINED_PERPETUAL"
    COIN_MARGINED_EXPIRING_FUTURE = "COIN_MARGINED_EXPIRING_FUTURE"
    PORTFOLIO_MARGIN = "PORTFOLIO_MARGIN"
    MULTI_COLLATERAL = "MULTI_COLLATERAL"
    UNKNOWN = "UNKNOWN"


class VenueSourceTemplateKind(StrEnum):
    OFFICIAL_DOCS = "OFFICIAL_DOCS"
    OFFICIAL_REST_API_REFERENCE = "OFFICIAL_REST_API_REFERENCE"
    OFFICIAL_WEBSOCKET_API_REFERENCE = "OFFICIAL_WEBSOCKET_API_REFERENCE"
    OFFICIAL_EXPORT = "OFFICIAL_EXPORT"
    MANUAL_OFFICIAL_IMPORT = "MANUAL_OFFICIAL_IMPORT"
    HUMAN_REVIEW_NOTE = "HUMAN_REVIEW_NOTE"


class VenueDescriptorReadinessReason(StrEnum):
    READY_FOR_RESEARCH = "READY_FOR_RESEARCH"
    NOT_EXECUTION_READY = "NOT_EXECUTION_READY"
    MISSING_OFFICIAL_SOURCE_TEMPLATE = "MISSING_OFFICIAL_SOURCE_TEMPLATE"
    UNSUPPORTED_ENVIRONMENT = "UNSUPPORTED_ENVIRONMENT"
    UNSUPPORTED_PRODUCT_FAMILY = "UNSUPPORTED_PRODUCT_FAMILY"
    DEFERRED = "DEFERRED"


class VenueDescriptorNotFoundError(LookupError):
    """Raised when a deterministic venue registry does not contain a venue."""


class VenueProductDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    product_descriptor_id: VenueProductDescriptorId | None = None
    venue_id: str
    environment: VenueOperatingEnvironment
    product_family: VenueProductFamily
    support_status: VenueSupportStatus
    supported_contract_payoff_kinds: tuple[ContractPayoffKind, ...]
    supported_collateral_modes: tuple[CollateralMode, ...]
    notes: str | None = None
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("venue_id", mode="before")
    @classmethod
    def _normalize_venue_id(cls, value: object) -> object:
        return _canonical_venue_id(value)

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "notes")

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return _freeze_json_mapping(value, path="metadata")

    @field_serializer("metadata")
    def _serialize_metadata(self, value: Mapping[str, Any]) -> Any:
        return _thaw_json_value(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        _reject_duplicates(
            self.supported_contract_payoff_kinds,
            "supported_contract_payoff_kinds",
        )
        _reject_duplicates(
            self.supported_collateral_modes,
            "supported_collateral_modes",
        )
        object.__setattr__(
            self,
            "supported_contract_payoff_kinds",
            tuple(
                sorted(
                    self.supported_contract_payoff_kinds,
                    key=lambda item: item.value,
                )
            ),
        )
        object.__setattr__(
            self,
            "supported_collateral_modes",
            tuple(
                sorted(
                    self.supported_collateral_modes,
                    key=lambda item: item.value,
                )
            ),
        )
        if self.support_status not in _EMPTY_MODES_ALLOWED_STATUSES:
            if not self.supported_contract_payoff_kinds:
                raise ValueError("supported product descriptors require payoff kinds")
            if not self.supported_collateral_modes:
                raise ValueError("supported product descriptors require collateral modes")
        if self.support_status is VenueSupportStatus.SUPPORTED_FOR_RESEARCH:
            if self.product_family is VenueProductFamily.UNKNOWN:
                raise ValueError("SUPPORTED_FOR_RESEARCH requires known product_family")
            if ContractPayoffKind.UNKNOWN in self.supported_contract_payoff_kinds:
                raise ValueError("SUPPORTED_FOR_RESEARCH requires known payoff kinds")
            if CollateralMode.UNKNOWN in self.supported_collateral_modes:
                raise ValueError("SUPPORTED_FOR_RESEARCH requires known collateral modes")
        if self.environment is VenueOperatingEnvironment.UNKNOWN and (
            self.support_status is VenueSupportStatus.SUPPORTED_FOR_RESEARCH
        ):
            raise ValueError("SUPPORTED_FOR_RESEARCH requires a known environment")
        expected = deterministic_venue_product_descriptor_id(self)
        if (
            self.product_descriptor_id is not None
            and self.product_descriptor_id != expected
        ):
            raise ValueError("product_descriptor_id is not deterministic")
        object.__setattr__(self, "product_descriptor_id", expected)
        return self


class VenueSourceTemplate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_template_id: VenueSourceTemplateId | None = None
    venue_id: str
    environment: VenueOperatingEnvironment
    product_family: VenueProductFamily | None = None
    template_kind: VenueSourceTemplateKind
    source_trust: VenueCapabilitySourceTrust
    reference_label: str
    requires_human_review: bool
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("venue_id", mode="before")
    @classmethod
    def _normalize_venue_id(cls, value: object) -> object:
        return _canonical_venue_id(value)

    @field_validator("reference_label")
    @classmethod
    def _validate_reference_label(cls, value: str) -> str:
        return _trimmed(value, "reference_label")

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return _freeze_json_mapping(value, path="metadata")

    @field_serializer("metadata")
    def _serialize_metadata(self, value: Mapping[str, Any]) -> Any:
        return _thaw_json_value(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if (
            self.template_kind is VenueSourceTemplateKind.HUMAN_REVIEW_NOTE
            and not self.requires_human_review
        ):
            raise ValueError("HUMAN_REVIEW_NOTE requires human review")
        if (
            self.source_trust is VenueCapabilitySourceTrust.OFFICIAL
            and self.requires_human_review
        ):
            raise ValueError("human-reviewed templates cannot claim OFFICIAL trust")
        expected = deterministic_venue_source_template_id(self)
        if self.source_template_id is not None and self.source_template_id != expected:
            raise ValueError("source_template_id is not deterministic")
        object.__setattr__(self, "source_template_id", expected)
        return self

    def to_source_descriptor(
        self,
        *,
        created_at: datetime,
        reference_uri: str | None = None,
        official_owner: str | None = None,
        version: str | None = None,
    ) -> VenueCapabilitySourceDescriptor:
        """Convert metadata into a source descriptor without creating a payload record."""
        return VenueCapabilitySourceDescriptor(
            venue_id=self.venue_id,
            source_kind=_source_kind_for_template(self.template_kind),
            trust=self.source_trust,
            fetch_mode=_fetch_mode_for_template(self.template_kind),
            reference_uri=reference_uri,
            reference_name=self.reference_label,
            official_owner=official_owner,
            version=version,
            created_at=ensure_aware_utc(created_at),
            metadata={
                "source_template_id": str(self.source_template_id),
                "environment": self.environment.value,
                "product_family": (
                    None if self.product_family is None else self.product_family.value
                ),
                "requires_human_review": self.requires_human_review,
                "template_metadata": _thaw_json_value(self.metadata),
            },
        )


class VenueDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    descriptor_id: VenueDescriptorId | None = None
    venue_id: str
    display_name: str
    support_status: VenueSupportStatus
    environments: tuple[VenueOperatingEnvironment, ...]
    products: tuple[VenueProductDescriptor, ...] = ()
    source_templates: tuple[VenueSourceTemplate, ...] = ()
    notes: str | None = None
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("venue_id", mode="before")
    @classmethod
    def _normalize_venue_id(cls, value: object) -> object:
        return _canonical_venue_id(value)

    @field_validator("display_name")
    @classmethod
    def _validate_display_name(cls, value: str) -> str:
        return _trimmed(value, "display_name")

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "notes")

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return _freeze_json_mapping(value, path="metadata")

    @field_serializer("metadata")
    def _serialize_metadata(self, value: Mapping[str, Any]) -> Any:
        return _thaw_json_value(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        _canonicalize_descriptor_environments(self)
        _validate_descriptor_support_status(self)
        _validate_descriptor_products(self)
        _validate_descriptor_source_templates(self)
        product_keys = tuple(str(product.product_descriptor_id) for product in self.products)
        if len(set(product_keys)) != len(product_keys):
            raise ValueError("duplicate product descriptors are not allowed")
        template_keys = tuple(
            str(template.source_template_id) for template in self.source_templates
        )
        if len(set(template_keys)) != len(template_keys):
            raise ValueError("duplicate source templates are not allowed")
        sorted_products = tuple(
            sorted(
                self.products,
                key=lambda item: (
                    item.environment.value,
                    item.product_family.value,
                    str(item.product_descriptor_id),
                ),
            )
        )
        sorted_templates = tuple(
            sorted(
                self.source_templates,
                key=lambda item: (
                    item.environment.value,
                    "" if item.product_family is None else item.product_family.value,
                    item.template_kind.value,
                    item.reference_label,
                    str(item.source_template_id),
                ),
            )
        )
        object.__setattr__(self, "products", sorted_products)
        object.__setattr__(self, "source_templates", sorted_templates)
        expected = deterministic_venue_descriptor_id(self)
        if self.descriptor_id is not None and self.descriptor_id != expected:
            raise ValueError("descriptor_id is not deterministic")
        object.__setattr__(self, "descriptor_id", expected)
        return self


class VenueRegistrySnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: VenueRegistrySnapshotId | None = None
    descriptors: tuple[VenueDescriptor, ...]
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return _freeze_json_mapping(value, path="metadata")

    @field_serializer("metadata")
    def _serialize_metadata(self, value: Mapping[str, Any]) -> Any:
        return _thaw_json_value(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        venue_ids = tuple(descriptor.venue_id for descriptor in self.descriptors)
        if len(set(venue_ids)) != len(venue_ids):
            raise ValueError("duplicate venue descriptors are not allowed")
        object.__setattr__(
            self,
            "descriptors",
            tuple(
                sorted(
                    self.descriptors,
                    key=lambda item: (item.venue_id, item.display_name),
                )
            ),
        )
        expected = deterministic_venue_registry_snapshot_id(self)
        if self.snapshot_id is not None and self.snapshot_id != expected:
            raise ValueError("snapshot_id is not deterministic")
        object.__setattr__(self, "snapshot_id", expected)
        return self


def canonical_venue_id(value: str) -> str:
    return _canonical_venue_id(value)


def deterministic_venue_product_descriptor_id(
    descriptor: VenueProductDescriptor,
) -> VenueProductDescriptorId:
    digest = _digest(_model_identity(descriptor, exclude={"product_descriptor_id"}))
    return VenueProductDescriptorId(value=f"venue-product-descriptor:{digest}")


def deterministic_venue_source_template_id(
    template: VenueSourceTemplate,
) -> VenueSourceTemplateId:
    digest = _digest(_model_identity(template, exclude={"source_template_id"}))
    return VenueSourceTemplateId(value=f"venue-source-template:{digest}")


def deterministic_venue_descriptor_id(
    descriptor: VenueDescriptor,
) -> VenueDescriptorId:
    digest = _digest(_model_identity(descriptor, exclude={"descriptor_id"}))
    return VenueDescriptorId(value=f"venue-descriptor:{digest}")


def deterministic_venue_registry_snapshot_id(
    snapshot: VenueRegistrySnapshot,
) -> VenueRegistrySnapshotId:
    digest = _digest(_model_identity(snapshot, exclude={"snapshot_id"}))
    return VenueRegistrySnapshotId(value=f"venue-registry-snapshot:{digest}")


_EMPTY_MODES_ALLOWED_STATUSES = {
    VenueSupportStatus.DEFERRED,
    VenueSupportStatus.UNSUPPORTED,
    VenueSupportStatus.NEEDS_HUMAN_REVIEW,
}


def _canonicalize_descriptor_environments(descriptor: VenueDescriptor) -> None:
    if not descriptor.environments:
        raise ValueError("environments must be non-empty")
    _reject_duplicates(descriptor.environments, "environments")
    object.__setattr__(
        descriptor,
        "environments",
        tuple(sorted(descriptor.environments, key=lambda item: item.value)),
    )


def _validate_descriptor_support_status(descriptor: VenueDescriptor) -> None:
    if descriptor.support_status is VenueSupportStatus.SUPPORTED_FOR_RESEARCH:
        if VenueOperatingEnvironment.UNKNOWN in descriptor.environments:
            raise ValueError("SUPPORTED_FOR_RESEARCH requires known environments")
        if not descriptor.products:
            raise ValueError("SUPPORTED_FOR_RESEARCH requires product descriptors")
        if not descriptor.source_templates:
            raise ValueError("SUPPORTED_FOR_RESEARCH requires source templates")
        return
    if any(
        product.support_status is VenueSupportStatus.SUPPORTED_FOR_RESEARCH
        for product in descriptor.products
    ):
        raise ValueError("not-ready venue descriptors cannot contain supported products")


def _validate_descriptor_products(descriptor: VenueDescriptor) -> None:
    for product in descriptor.products:
        if product.venue_id != descriptor.venue_id:
            raise ValueError("product venue_id must match descriptor venue_id")
        if product.environment not in descriptor.environments:
            raise ValueError("product environment must be listed on descriptor")


def _validate_descriptor_source_templates(descriptor: VenueDescriptor) -> None:
    for template in descriptor.source_templates:
        if template.venue_id != descriptor.venue_id:
            raise ValueError("source template venue_id must match descriptor venue_id")
        if template.environment not in descriptor.environments:
            raise ValueError("source template environment must be listed on descriptor")
        if template.product_family is not None and not any(
            product.environment is template.environment
            and product.product_family is template.product_family
            for product in descriptor.products
        ):
            raise ValueError("source template product_family must match a product")


def _canonical_venue_id(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("venue_id must be a string")
    normalized = value.strip().upper()
    if not normalized:
        raise ValueError("venue_id must be non-empty")
    return normalized


def _reject_duplicates(values: Sequence[Any], field_name: str) -> None:
    seen: set[Any] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"{field_name} must not contain duplicates")
        seen.add(value)


def _source_kind_for_template(
    template_kind: VenueSourceTemplateKind,
) -> VenueCapabilitySourceKind:
    if template_kind is VenueSourceTemplateKind.OFFICIAL_DOCS:
        return VenueCapabilitySourceKind.OFFICIAL_EXCHANGE_DOCS
    if template_kind in {
        VenueSourceTemplateKind.OFFICIAL_REST_API_REFERENCE,
        VenueSourceTemplateKind.OFFICIAL_WEBSOCKET_API_REFERENCE,
    }:
        return VenueCapabilitySourceKind.OFFICIAL_EXCHANGE_API
    if template_kind is VenueSourceTemplateKind.OFFICIAL_EXPORT:
        return VenueCapabilitySourceKind.OFFICIAL_EXCHANGE_EXPORT
    if template_kind is VenueSourceTemplateKind.MANUAL_OFFICIAL_IMPORT:
        return VenueCapabilitySourceKind.MANUAL_OFFICIAL_SNAPSHOT
    return VenueCapabilitySourceKind.UNKNOWN


def _fetch_mode_for_template(
    template_kind: VenueSourceTemplateKind,
) -> VenueCapabilitySourceFetchMode:
    if template_kind is VenueSourceTemplateKind.MANUAL_OFFICIAL_IMPORT:
        return VenueCapabilitySourceFetchMode.MANUAL
    if template_kind is VenueSourceTemplateKind.HUMAN_REVIEW_NOTE:
        return VenueCapabilitySourceFetchMode.STATIC_REFERENCE
    return VenueCapabilitySourceFetchMode.API_DEFERRED


def _model_identity(model: BaseModel, *, exclude: set[str]) -> dict[str, Any]:
    dumped = model.model_dump(mode="json")
    for key in exclude:
        dumped.pop(key, None)
    return _canonical_value(dumped)


def _digest(payload: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _canonical_value(value: Any) -> Any:
    result: Any
    if isinstance(value, datetime):
        result = ensure_aware_utc(value).isoformat()
    elif isinstance(value, StrEnum):
        result = value.value
    elif isinstance(value, BaseModel):
        result = _canonical_value(value.model_dump(mode="json"))
    elif isinstance(value, Mapping):
        result = {key: _canonical_value(item) for key, item in value.items()}
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        result = [_canonical_value(item) for item in value]
    else:
        result = value
    return result


def _canonical_json_bytes(payload: Any) -> bytes:
    payload = _canonical_value(payload)
    _validate_json_compatible(payload, path="payload")
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _validate_json_compatible(value: Any, *, path: str) -> None:
    if value is None or isinstance(value, str | bool | int):
        return
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f"{path} float must be finite")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} object keys must be strings")
            _validate_json_compatible(item, path=f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, item in enumerate(value):
            _validate_json_compatible(item, path=f"{path}[{index}]")
        return
    raise ValueError(f"{path} must be JSON-compatible")


def _freeze_json_mapping(value: Mapping[str, Any], *, path: str) -> Mapping[str, Any]:
    frozen = _freeze_json_value(value, path=path)
    if not isinstance(frozen, Mapping):
        raise ValueError(f"{path} must be a JSON-compatible object")
    return frozen


def _freeze_json_value(value: Any, *, path: str) -> Any:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f"{path} float must be finite")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} object keys must be strings")
            frozen[key] = _freeze_json_value(item, path=f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return tuple(
            _freeze_json_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    raise ValueError(f"{path} must be JSON-compatible")


def _thaw_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_thaw_json_value(item) for item in value]
    return value


def _trimmed(value: str, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty and trimmed")
    return value
