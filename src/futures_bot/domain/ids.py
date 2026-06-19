from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, field_validator


class DomainId(BaseModel):
    """Small immutable string value object for audited domain identities."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: str

    def __init__(self, value: str | None = None, **data: Any) -> None:
        if value is not None:
            if data:
                raise TypeError("pass either a positional value or keyword fields, not both")
            data = {"value": value}
        super().__init__(**data)

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("domain id must be a string")
        if not value:
            raise ValueError("domain id must be non-empty")
        if value != value.strip():
            raise ValueError("domain id must not contain leading or trailing whitespace")
        if not value.strip():
            raise ValueError("domain id must not be whitespace-only")
        if len(value) > 128:
            raise ValueError("domain id must be at most 128 characters")
        return value

    @classmethod
    def from_str(cls, value: str) -> Self:
        return cls(value)

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.value!r})"


class BotId(DomainId):
    pass


class BotBlueprintId(DomainId):
    pass


class ExperimentId(DomainId):
    pass


class CohortId(DomainId):
    pass


class BucketId(DomainId):
    pass


class PositionId(DomainId):
    pass


class InstrumentId(DomainId):
    pass


class DecisionIntentId(DomainId):
    pass


class ReplayDecisionContextId(DomainId):
    pass


class ReplayDecisionMarketContextReferenceId(DomainId):
    pass


class ExecutionIntentId(DomainId):
    pass


class OrderIntentId(DomainId):
    pass


class ExchangeOrderId(DomainId):
    pass


class FillId(DomainId):
    pass


class EvidenceId(DomainId):
    pass


class MarketEvidenceItemId(DomainId):
    pass


class MarketEvidenceSetId(DomainId):
    pass


class CandidateId(DomainId):
    pass


class EventId(DomainId):
    pass


class SnapshotId(DomainId):
    pass


class ModelArtifactId(DomainId):
    pass


class PolicyId(DomainId):
    pass


class PolicyVersion(DomainId):
    pass


class RunId(DomainId):
    pass


class ProducerId(DomainId):
    pass


class WalSegmentId(DomainId):
    pass


class SidecarId(DomainId):
    pass


class ConsumerId(DomainId):
    pass


class BrokerTopicId(DomainId):
    pass


class BrokerPartitionId(DomainId):
    pass


class BrokerMessageId(DomainId):
    pass


class BatchId(DomainId):
    pass


class MarketDataSourceId(DomainId):
    pass


class VenueInstrumentId(DomainId):
    pass


class MarketObservationId(DomainId):
    pass


class MarketConnectionId(DomainId):
    pass


class MarketHealthSnapshotId(DomainId):
    pass


class MarketFrameId(DomainId):
    pass


class ReplayMarketBindingId(DomainId):
    pass


class ReplayMarketObservationProjectionId(DomainId):
    pass


class ReplayMarketFrameProjectionId(DomainId):
    pass


class ReplayMarketFrameTimelineId(DomainId):
    pass


class ReplayMarketFrameLookupEntryId(DomainId):
    pass
