# Margin / Liquidation Semantics

Margin/liquidation readiness proves that required source-backed rules exist for
a venue, instrument, margin mode, and asset path at a checked timestamp.

It is not live liquidation-price calculation, portfolio margin math, strategy
alpha, execution readiness, order admission, or risk sizing. Future execution
and simulation code must consume these explicit rules instead of inventing
margin, leverage, risk bracket, or liquidation assumptions.

There is no implicit stablecoin margin assumption and no generic leverage
default. Isolated, cross, portfolio, and multi-asset modes are explicit policy
inputs. Collateral valuation readiness, asset conversion readiness, objective
readiness, execution cost readiness, market-data readiness, and
margin/liquidation readiness are separate gates.
