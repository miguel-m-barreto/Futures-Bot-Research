from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.ids import BrokerTopicId
from futures_bot.domain.journal import JournalRecord, WalOffset


class BrokerPublishStatus(StrEnum):
    PUBLISHED = "PUBLISHED"
    REJECTED_BROKER_UNAVAILABLE = "REJECTED_BROKER_UNAVAILABLE"
    REJECTED_SERIALIZATION_FAILED = "REJECTED_SERIALIZATION_FAILED"
    REJECTED_TOPIC_UNAVAILABLE = "REJECTED_TOPIC_UNAVAILABLE"
    REJECTED_INVALID_RECORD = "REJECTED_INVALID_RECORD"


class KafkaPartitionOffset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    topic: BrokerTopicId
    partition: int
    offset: int

    @field_validator("partition")
    @classmethod
    def _validate_partition(cls, value: int) -> int:
        if value < 0:
            raise ValueError("partition must be >= 0")
        return value

    @field_validator("offset")
    @classmethod
    def _validate_offset(cls, value: int) -> int:
        if value < 0:
            raise ValueError("offset must be >= 0")
        return value


class KafkaPublishRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    journal_record: JournalRecord
    topic: BrokerTopicId
    key: str
    headers: tuple[tuple[str, str], ...] = ()

    @field_validator("key")
    @classmethod
    def _validate_key(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("key must be a non-empty trimmed string")
        return value

    @field_validator("headers")
    @classmethod
    def _validate_headers(
        cls, value: tuple[tuple[str, str], ...]
    ) -> tuple[tuple[str, str], ...]:
        names: list[str] = []
        for name, _ in value:
            if not name or name != name.strip():
                raise ValueError("header name must be a non-empty trimmed string")
            names.append(name)
        if len(set(names)) != len(names):
            raise ValueError("duplicate header names are not allowed")
        return value


class KafkaConsumedRecord(BaseModel):
    """Broker-assigned record suitable for downstream consumers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    journal_record: JournalRecord
    topic: BrokerTopicId
    key: str | None = None
    kafka_offset: KafkaPartitionOffset

    @field_validator("key")
    @classmethod
    def _validate_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or value != value.strip():
            raise ValueError("key must be a non-empty trimmed string")
        return value

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.kafka_offset.topic != self.topic:
            raise ValueError("kafka_offset.topic must equal topic")
        return self


class KafkaPublishAck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: BrokerPublishStatus
    published: bool
    journal_offset: WalOffset
    kafka_offset: KafkaPartitionOffset | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.status is BrokerPublishStatus.PUBLISHED:
            if not self.published:
                raise ValueError("PUBLISHED status requires published=True")
            if self.kafka_offset is None:
                raise ValueError("PUBLISHED status requires kafka_offset")
            if self.reason is not None:
                raise ValueError("PUBLISHED status must not have reason")
        else:
            if self.published:
                raise ValueError("rejected status requires published=False")
            if self.kafka_offset is not None:
                raise ValueError("rejected status must not have kafka_offset")
            if not self.reason or self.reason != self.reason.strip():
                raise ValueError("rejected status requires a non-empty trimmed reason")
        return self
