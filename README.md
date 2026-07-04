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

## Domain Asset Scope

The current domain contracts model futures assets generically. Stablecoin-margined linear futures
using USDT or USDC remain supported, but they are one supported family rather than the domain
boundary.

Capital, margin, settlement, quote, collateral, and PnL assets are represented as explicit asset
symbols. BTC, ETH, BNB, USD, USDT, USDC, and other valid asset symbols may appear in domain
contracts when the surrounding venue or execution policy supports them.

No implicit conversion is implemented. The system must not assume that `100 USDT` equals
`100 USDC`, `100 USD`, or any other asset amount without an explicit future conversion or
valuation snapshot.

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
