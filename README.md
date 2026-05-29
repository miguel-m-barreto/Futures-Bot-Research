# Futures Bot Research

Python-first research-to-live futures bot platform foundation for the Futures Bot / trading_bot
project.

The previous Rust repository is archived as a reference prototype only. It is useful for
architecture lessons, but it is not the active implementation and will not be ported mechanically.

The current foundation sprint implements domain foundations only. Future sprints target many bots,
ML models, neural models, LLM-assisted DecisionStacks, training and retraining pipelines,
database/storage, API/dashboard surfaces, exchange integration, and controlled live execution.
Replay, paper, and shadow modes are validation stages, not the final purpose.

Live execution is a goal after evidence, auditability, RiskGate, Ledger, Execution,
reconciliation, and kill-switch work are implemented and validated.

## Current Stablecoin-Collateral Sprint Scope

The current implementation supports stablecoin-collateral futures only. This is the current sprint
scope, not a forever limitation.

Current allowed capital, collateral, and settlement assets:

- USDT
- USDC

Out of current sprint scope:

- ETH or BTC collateral
- BNB, SOL, or other non-stable collateral
- coin-margined futures
- inverse futures
- multi-asset collateral
- portfolio margin
- implicit USD accounting

USDT and USDC are distinct assets. The system must not assume that `100 USDT` equals `100 USDC`
without an explicit future conversion or valuation snapshot.

## Boundary Rules

- No float accounting.
- Scripts and notebooks are allowed for research, analysis, experiments, and tooling, but they are
  not production runtime modules.
- Bots, models, and LLMs may produce annotations, predictions, scores, DecisionIntent candidates,
  NoTrade decisions, sizing preferences, leverage preferences, and learned risk behavior.
- Bots, models, and LLMs must not submit exchange orders directly or mutate Ledger/accounting
  directly.
- Training pipelines produce versioned artifacts/model states; training is not part of the
  production hot path.
- `DecisionIntent` is not an order.
- Technical evidence is not a trade.
- DecisionStack proposes.
- RiskBehaviorModel proposes learned/adaptive risk behavior.
- HardRiskGate validates physical, execution, and accounting reality.
- Execution simulates or submits approved actions.
- Ledger accounts.
- Event Journal records facts.
- Evaluation measures outcomes.
- Allow strategic freedom. Reject impossible reality.
- The system informs; bots decide.
- Ledger is the future monetary authority and will be the only place that mutates money.
