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


class CancelOrderIntentId(DomainId):
    pass


class ReplaceOrderIntentId(DomainId):
    pass


class OrderLifecycleEventId(DomainId):
    pass


class ExecutionOrderRecordId(DomainId):
    pass


class FillReportId(DomainId):
    pass


class ClientOrderId(DomainId):
    pass


class OrderIdempotencyKey(DomainId):
    pass


class VenueOrderId(DomainId):
    pass


class ExecutionReconciliationId(DomainId):
    pass


class ExecutionAdmissionRequestId(DomainId):
    pass


class ExecutionAdmissionDecisionId(DomainId):
    pass


class ExecutionReadinessProofId(DomainId):
    pass


class ExecutionReadinessDecisionId(DomainId):
    pass


class ExecutionReadinessStoreId(DomainId):
    pass


class ExecutionCoordinatorRunId(DomainId):
    pass


class ExecutionCoordinatorEventId(DomainId):
    pass


class ExecutionSubmissionRequestId(DomainId):
    pass


class VenueCapabilitySnapshotId(DomainId):
    pass


class VenueInstrumentRuleSnapshotId(DomainId):
    pass


class VenueRateLimitProfileId(DomainId):
    pass


class VenueOrderValidationId(DomainId):
    pass


class DeadManSwitchCapabilityId(DomainId):
    pass


class VenueCapabilityFreshnessPolicyId(DomainId):
    pass


class VenueCapabilityFreshnessCheckId(DomainId):
    pass


class VenueCapabilityFreshnessDecisionId(DomainId):
    pass


class VenueCapabilityReadinessSnapshotId(DomainId):
    pass


class VenueCapabilitySourceId(DomainId):
    pass


class VenueCapabilitySourceRecordId(DomainId):
    pass


class VenueCapabilitySourcePayloadHashId(DomainId):
    pass


class VenueCapabilitySourceImportId(DomainId):
    pass


class VenueCapabilityManualImportRequestId(DomainId):
    pass


class VenueCapabilityManualImportDecisionId(DomainId):
    pass


class VenueCapabilityManualImportGatewayId(DomainId):
    pass


class AssetSymbolId(DomainId):
    pass


class AssetSemanticsId(DomainId):
    pass


class ContractAssetSemanticsId(DomainId):
    pass


class EconomicExposureId(DomainId):
    pass


class ObjectiveAssetPolicyId(DomainId):
    pass


class CollateralValuationPolicyId(DomainId):
    pass


class VenueCapabilitySourceHealthRecordId(DomainId):
    pass


class VenueCapabilityResolutionRequestId(DomainId):
    pass


class VenueCapabilityResolutionDecisionId(DomainId):
    pass


class VenueCapabilityResolutionGatewayId(DomainId):
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


class ReplayMarketEvidenceProjectionId(DomainId):
    pass


class ReplayMarketEvidenceTimelineId(DomainId):
    pass


class ReplayMarketEvidenceLookupEntryId(DomainId):
    pass


class StreamId(DomainId):
    pass


class StreamPartitionId(DomainId):
    pass


class StreamEventId(DomainId):
    pass


class LiveStateSnapshotId(DomainId):
    pass


class HistoricalStateSliceId(DomainId):
    pass


class LiveTailSliceId(DomainId):
    pass


class StitchedStateSliceId(DomainId):
    pass


class DbWriterCheckpointId(DomainId):
    pass


class RuntimeControlCommandId(DomainId):
    pass


class RuntimeControlEventId(DomainId):
    pass


class RuntimeStateTransitionId(DomainId):
    pass


class ProgramRuntimeId(DomainId):
    pass


class DecisionStackRuntimeId(DomainId):
    pass


class RuntimeCheckpointId(DomainId):
    pass


class RuntimeManifestId(DomainId):
    pass


class ExposureStateId(DomainId):
    pass


class ExposureRecoveryPlanId(DomainId):
    pass


class KillSwitchId(DomainId):
    pass


class WarmupPolicyId(DomainId):
    pass


class ResyncPlanId(DomainId):
    pass


class RuntimeDataHealthSnapshotId(DomainId):
    pass


class ExecutionCapabilityCheckId(DomainId):
    pass


class ExecutionCapabilityDecisionId(DomainId):
    pass


class ExecutionCapabilityGateId(DomainId):
    pass
