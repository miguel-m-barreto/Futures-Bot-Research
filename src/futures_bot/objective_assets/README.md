# Objective Asset Policy

Objective asset policy defines what "profit" means for a bot or account.

It answers a deterministic readiness question:

Can this PnL, settlement, or collateral outcome be measured against the stated objective asset safely?

It does not decide whether a strategy is profitable, fetch prices, submit orders, mutate ledgers, or create an automatic conversion.

## Doctrine

PnL asset mismatch is not automatically profit. A leg that produces USDT PnL and a leg that produces ETH PnL cannot be added together as profit for a BTC-accumulation objective unless explicit valuation or conversion readiness exists.

USDT, USD, BTC, ETH, BNB, and venue-specific assets are distinct assets. The domain does not assume stablecoin parity, does not treat USDT as USD, and does not infer ETH/BTC conversion from symbols.

Objective readiness is a gate. It is not strategy alpha, execution readiness, order admission, accounting, or portfolio valuation.

## Measurement Modes

Objective policies model whether the bot is accumulating native units, maximizing value in a reference asset, preserving collateral, matching settlement, or requiring explicit conversion evidence.

Reference-value measurement still requires explicit evidence when the outcome asset differs from the reference asset. Collateral-adjusted reference measurement additionally requires a ready collateral valuation decision.

Objective asset mismatches require scoped conversion readiness from the asset being measured into the objective, reference, or settlement asset required by the policy. Unrelated conversion readiness and collateral valuation readiness are not interchangeable evidence.

Objective readiness does not prove margin mode, leverage, risk bracket, or
liquidation model semantics. Those are handled by margin/liquidation readiness.

## Cross-Venue Comparability

A cross-venue opportunity is not profit unless the economic objective is defined.

Example:

- Binance leg produces USDT PnL
- KuCoin leg produces ETH PnL
- bot objective is BTC accumulation

The system cannot count both outcomes as BTC profit without objective asset valuation or conversion readiness for each leg.

This module intentionally does not implement arbitrage, pricing, adapters, execution, ledgers, or reporting.
