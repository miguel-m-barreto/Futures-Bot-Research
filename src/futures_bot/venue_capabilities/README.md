# Venue Capability Contracts

Sprint 44 models factual execution constraints for future venue adapters. A venue
capability snapshot describes account- and venue-level execution support, while an
instrument rule snapshot describes symbol-level filters such as order types, time in
force, tick size, step size, quantity bounds, and notional bounds.

The validator is hard execution-validity only. It is not alpha logic, strategy
filtering, profitability filtering, or risk scoring. ExecutionManager may admit a
local intent, but a later venue-submission path must validate the order against a
venue/instrument capability snapshot before it can become executable.

Futures Bot v1 is stablecoin-collateral linear futures only. Supported collateral and
settlement assets are USDT and USDC; inverse, coin-margined, multi-asset collateral,
and portfolio-margin assumptions are intentionally outside this contract.

Dead-man switch, rate-limit, self-trade-prevention, and price-protection capabilities
are modeled as deterministic contracts, but no live runtime enforcement is added here.

Official exchange ingestion and real adapters are deferred. This package performs no
network calls, filesystem persistence, database writes, order submission, cancel,
replace, or simulation.
