from futures_bot.domain.policies import PolicyKind, UniversePolicyKind


def test_policy_kind_has_no_universal_technical_prerequisite_method() -> None:
    assert not hasattr(PolicyKind.TECHNICAL_ONLY, "requires_technical_setup_for_trading")
    assert not hasattr(PolicyKind, "requires_technical_setup_for_trading")
    assert "classification only" in (PolicyKind.__doc__ or "")


def test_policy_kind_contains_ml_neural_and_hybrid_variants() -> None:
    assert PolicyKind.ML_MODEL_DRIVEN
    assert PolicyKind.NEURAL_MODEL_DRIVEN
    assert PolicyKind.HYBRID_MODEL_DRIVEN
    assert PolicyKind.HYBRID


def test_universe_policy_labels_are_present() -> None:
    assert UniversePolicyKind.LOW_CAP_RESEARCH
    assert UniversePolicyKind.SHITCOIN_RESEARCH_PAPER_ONLY
    assert UniversePolicyKind.HIGH_VOLATILITY_RESEARCH
    assert UniversePolicyKind.FREE_WITHIN_SAFETY
    assert "not global safety law" in (UniversePolicyKind.__doc__ or "")
