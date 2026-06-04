from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class WalOffset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    value: int

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value: int) -> int:
        if value < 0:
            raise ValueError("WalOffset value must be >= 0")
        return value

    def next(self) -> WalOffset:
        return WalOffset(value=self.value + 1)

    def is_before_or_equal(self, other: WalOffset) -> bool:
        return self.value <= other.value

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, WalOffset):
            return NotImplemented  # type: ignore[return-value]
        return self.value < other.value

    def __le__(self, other: object) -> bool:
        if not isinstance(other, WalOffset):
            return NotImplemented  # type: ignore[return-value]
        return self.value <= other.value

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, WalOffset):
            return NotImplemented  # type: ignore[return-value]
        return self.value > other.value

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, WalOffset):
            return NotImplemented  # type: ignore[return-value]
        return self.value >= other.value


class WalOffsetRange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    first: WalOffset
    last: WalOffset

    @model_validator(mode="after")
    def _validate_range(self) -> WalOffsetRange:
        if self.first.value > self.last.value:
            raise ValueError("WalOffsetRange first must be <= last")
        return self

    @property
    def count(self) -> int:
        return self.last.value - self.first.value + 1

    def contains(self, offset: WalOffset) -> bool:
        return self.first.value <= offset.value <= self.last.value
