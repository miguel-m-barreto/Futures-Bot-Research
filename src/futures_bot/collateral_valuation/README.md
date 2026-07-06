# Collateral Valuation

Collateral valuation answers one deterministic domain question:

Can this collateral asset be valued safely enough for risk sizing?

It does not fetch live prices, submit orders, mutate ledgers, calculate balances, or decide whether a strategy should trade.

## Doctrine

Collateral assets are modeled as generic `AssetSymbol` values. USDT, USDC, BTC, ETH, BNB, venue tokens, and future venue-specific assets can all be represented, but none is implicitly treated as USD.

A valuation snapshot states only:

`1 collateral_asset = price reference_asset`

No implicit conversion is created from that fact. A BTC/USDT valuation is not an ETH/USD valuation, and a USDT/USD valuation is not permission to value every stablecoin at par.

Haircut rules are explicit. A `haircut_rate` of `0.20` means only 80 percent of the marked value is counted by downstream risk sizing. Non-stable collateral is not executable by default merely because a mark exists.

## Readiness

`evaluate_collateral_valuation_readiness` checks explicit artifacts supplied by the caller:

- valuation snapshot
- source trust and health
- valuation freshness
- reference asset match
- eligibility rule
- haircut rule

The evaluator uses the caller-supplied `checked_at` timestamp. It does not call a clock, perform I/O, or fetch market data.

## Cross-Venue Exposure

Collateral valuation is required before cross-venue dislocation or arbitrage logic can compare exposures funded by different collateral assets.

Example:

- Binance leg collateralized with USDT
- KuCoin leg collateralized with ETH

The system cannot compare residual risk across those legs until ETH valuation, ETH haircut rules, and eligibility semantics are known in the intended reference asset.
