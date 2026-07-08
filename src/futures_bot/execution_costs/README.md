# Execution Cost Semantics

Execution cost readiness proves that required source-backed fee, funding, and
executable-depth semantics exist for a venue, instrument, asset path, and
checked timestamp.

It is not live slippage calculation, live order-book depth calculation, funding
accrual/accounting, strategy alpha, execution readiness, order admission, or
profitability estimation. Future simulators and HardRiskGate code must consume
these explicit rules instead of inventing fee, funding, spread, or depth
assumptions.

There is no zero-fee default, no ignored-funding default, no implicit
stablecoin fee/funding assumption, and no generic depth or spread assumption.
Collateral valuation readiness, asset conversion readiness, objective readiness,
margin/liquidation readiness, market-data readiness, and execution cost
readiness are separate gates. Execution cost rules do not prove fresh bid/ask,
mark, index, last-trade, or order-book observations.

Event journal readiness is separate too. Execution cost rules do not prove
contiguous journal sequence, checkpoint scope, or payload-hash evidence.
