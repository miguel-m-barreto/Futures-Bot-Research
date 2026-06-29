# Venue Capability Contracts

Sprint 44 models factual execution constraints for future venue adapters. A venue
capability snapshot describes account- and venue-level execution support, while an
instrument rule snapshot describes symbol-level filters such as order types, time in
force, tick size, step size, quantity bounds, and notional bounds.

The freshness validator and order validator are hard execution-validity only.
They are not alpha logic, strategy filtering, profitability filtering, or risk
scoring. ExecutionManager may admit a local intent, but a later venue-submission
path must validate the order against fresh venue/instrument capability data
before it can become executable.

Capability snapshots must be fresh before execution capability validation when
`require_fresh_capability_snapshot=True`. Missing, stale, future-dated, degraded,
unavailable, unknown, or mismatched venue capability data rejects hard before the
venue order validator runs. The system never falls back to unknown or default
exchange rules when capability data is missing or stale.

The resolution gateway chooses the latest known venue snapshot and instrument
rule snapshot from deterministic stores using `captured_at` and snapshot ID as a
tiebreak. Missing data is not guessed and no default exchange rules are
fabricated. Freshness is evaluated before readiness; stale, future-dated,
degraded, unavailable, or mismatched snapshots return not-ready decisions without
creating a validation context.

A ready resolution is only a safe handoff bundle for the downstream capability
gate: resolved snapshots, a freshness check/decision, and a
`VenueOrderValidationContext`. It is not venue submission, and the gateway does
not itself decide whether the order passes venue order rules.

Futures Bot v1 is stablecoin-collateral linear futures only. Supported collateral and
settlement assets are USDT and USDC; inverse, coin-margined, multi-asset collateral,
and portfolio-margin assumptions are intentionally outside this contract.

Dead-man switch, rate-limit, self-trade-prevention, and price-protection capabilities
are modeled as deterministic contracts, but no live runtime enforcement is added here.

Passing freshness and capability validation is still local acceptance only. It is
not real venue submission.

Official exchange ingestion and real adapters remain deferred. This package
performs no network calls, filesystem persistence, database writes, order
submission, cancel, replace, or simulation.
