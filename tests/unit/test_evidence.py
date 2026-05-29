from decimal import Decimal

import pytest
from pydantic import ValidationError

from futures_bot.domain.evidence import (
    EvidenceDirection,
    EvidenceSet,
    EvidenceSourceKind,
    TechnicalEvidence,
)
from futures_bot.domain.ids import EvidenceId


def _evidence(evidence_id: str, instrument: str = "BTC/USDT") -> TechnicalEvidence:
    return TechnicalEvidence(
        evidence_id=EvidenceId(evidence_id),
        instrument=instrument,
        source_kind=EvidenceSourceKind.ML_MODEL,
        source_id="model-1",
        direction=EvidenceDirection.LONG,
        confidence="0.8",
        tags=("momentum",),
    )


def test_technical_evidence_validates_confidence_tags_and_source() -> None:
    evidence = _evidence("evidence-1")

    assert evidence.confidence == Decimal("0.8")
    assert evidence.tags == ("momentum",)

    with pytest.raises(ValidationError, match="source_id"):
        TechnicalEvidence(
            evidence_id=EvidenceId("evidence-2"),
            instrument="BTC/USDT",
            source_kind=EvidenceSourceKind.LLM,
            source_id=" bad ",
            direction=EvidenceDirection.UNKNOWN,
        )
    with pytest.raises(ValidationError, match="float input"):
        TechnicalEvidence(
            evidence_id=EvidenceId("evidence-2"),
            instrument="BTC/USDT",
            source_kind=EvidenceSourceKind.LLM,
            source_id="llm-1",
            direction=EvidenceDirection.UNKNOWN,
            confidence=0.5,
        )
    with pytest.raises(ValidationError, match="tags"):
        TechnicalEvidence(
            evidence_id=EvidenceId("evidence-2"),
            instrument="BTC/USDT",
            source_kind=EvidenceSourceKind.LLM,
            source_id="llm-1",
            direction=EvidenceDirection.UNKNOWN,
            tags=("x", "x"),
        )


def test_evidence_set_rejects_mismatched_instruments_and_duplicate_ids() -> None:
    evidence = _evidence("evidence-1")

    with pytest.raises(ValidationError, match="must match"):
        EvidenceSet(instrument="ETH/USDT", evidence=(evidence,))

    with pytest.raises(ValidationError, match="duplicate"):
        EvidenceSet(instrument="BTC/USDT", evidence=(evidence, evidence))


def test_technical_evidence_invalid_instrument_type_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        TechnicalEvidence(
            evidence_id=EvidenceId("evidence-bad"),
            instrument=123,  # type: ignore[arg-type]
            source_kind=EvidenceSourceKind.ML_MODEL,
            source_id="model-1",
            direction=EvidenceDirection.LONG,
        )


@pytest.mark.parametrize("bad", ["abc", "", "not-a-number"])
def test_technical_evidence_confidence_invalid_string_raises_validation_error(bad: str) -> None:
    with pytest.raises(ValidationError):
        TechnicalEvidence(
            evidence_id=EvidenceId("evidence-bad"),
            instrument="BTC/USDT",
            source_kind=EvidenceSourceKind.ML_MODEL,
            source_id="model-1",
            direction=EvidenceDirection.LONG,
            confidence=bad,
        )


def test_evidence_set_lookup_methods() -> None:
    ml = _evidence("evidence-1")
    neutral = TechnicalEvidence(
        evidence_id=EvidenceId("evidence-2"),
        instrument="BTC/USDT",
        source_kind=EvidenceSourceKind.TECHNICAL_INDICATOR,
        source_id="rsi-14",
        direction=EvidenceDirection.NEUTRAL,
    )
    evidence_set = EvidenceSet(instrument="BTC/USDT", evidence=(ml, neutral))

    assert evidence_set.has_source_kind(EvidenceSourceKind.ML_MODEL)
    assert evidence_set.directions() == frozenset(
        {EvidenceDirection.LONG, EvidenceDirection.NEUTRAL},
    )
