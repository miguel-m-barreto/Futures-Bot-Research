from __future__ import annotations

from enum import StrEnum


class PolicyKind(StrEnum):
    """Policy classification only, not a universal prerequisite engine.

    A policy kind must not imply that every non-research bot requires technical setup.
    Actual requirements belong to explicit bot, cohort, decision, and risk policies.
    """

    TECHNICAL_ONLY = "TECHNICAL_ONLY"
    TECHNICAL_NEWS_HYBRID = "TECHNICAL_NEWS_HYBRID"
    PATTERN_ASSISTED = "PATTERN_ASSISTED"
    LLM_META_RESTRICTED = "LLM_META_RESTRICTED"
    LLM_META_FREE = "LLM_META_FREE"
    SCANNER_ONLY = "SCANNER_ONLY"
    RESEARCH_OBSERVER = "RESEARCH_OBSERVER"
    ML_MODEL_DRIVEN = "ML_MODEL_DRIVEN"
    NEURAL_MODEL_DRIVEN = "NEURAL_MODEL_DRIVEN"
    HYBRID_MODEL_DRIVEN = "HYBRID_MODEL_DRIVEN"
    HYBRID = "HYBRID"


class UniversePolicyKind(StrEnum):
    """Bot/cohort universe label only, not global safety law.

    Low liquidity, high volatility, and low market cap are not global hard rejects by default.
    They are evidence, annotations, or bot-specific universe choices unless a separate safety
    or validity boundary rejects the instrument.
    """

    SAFETY_VALID_ONLY = "SAFETY_VALID_ONLY"
    BOT_RESTRICTED = "BOT_RESTRICTED"
    CURATED_BY_BOT_POLICY = "CURATED_BY_BOT_POLICY"
    MAJOR_ONLY = "MAJOR_ONLY"
    SINGLE_INSTRUMENT = "SINGLE_INSTRUMENT"
    TOP_LIQUIDITY_BY_BOT_POLICY = "TOP_LIQUIDITY_BY_BOT_POLICY"
    LOW_CAP_RESEARCH = "LOW_CAP_RESEARCH"
    SHITCOIN_RESEARCH_PAPER_ONLY = "SHITCOIN_RESEARCH_PAPER_ONLY"
    HIGH_VOLATILITY_RESEARCH = "HIGH_VOLATILITY_RESEARCH"
    FREE_WITHIN_SAFETY = "FREE_WITHIN_SAFETY"
    EXPERIMENTAL_PAPER_ONLY = "EXPERIMENTAL_PAPER_ONLY"
