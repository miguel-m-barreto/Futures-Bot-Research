# Market Data Observation Semantics

Market-data readiness proves that required source-backed observations exist for
a venue, instrument, observation kind, and checked timestamp.

It is not live market data access, order-book reconstruction, slippage
calculation, strategy alpha, execution readiness, order admission, or
profitability estimation. Future Kafka, Redis, DB, LiveState, replay, and
dataset writer code must consume these explicit contracts instead of inventing
market-data assumptions.

There is no stale or gapped data acceptance for strict readiness, no implicit
stablecoin market-data assumption, and no mark/index/last price substitution
unless an explicit future policy models it. Best bid/ask, spread, depth, mark,
index, and last-trade observations remain distinct evidence paths.

Collateral valuation readiness, asset conversion readiness, objective readiness,
margin/liquidation readiness, execution cost readiness, and market-data
readiness are separate gates.

Event journal readiness is another separate gate. Market-data readiness does
not prove deterministic stream continuity, checkpoint scope, or replay-ready
journal evidence.
