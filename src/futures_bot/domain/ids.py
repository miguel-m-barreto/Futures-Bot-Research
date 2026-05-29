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
            raise TypeError("domain id must be a string")
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


class DecisionIntentId(DomainId):
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
