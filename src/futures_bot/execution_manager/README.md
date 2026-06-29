# Execution Manager Contracts

This package contains the deterministic local execution-manager coordinator.

DecisionStack code only proposes order, cancel, and replace intents. The
ExecutionManager owns lifecycle authority: it evaluates runtime order-flow
permission, appends auditable lifecycle events, and creates or updates local
execution records.

## Three-step admission

Admission now passes through deterministic sequential checks:

1. **Runtime OrderFlowPermission gate** — decides whether the system is allowed
   to attempt a flow at all. This is the same gate as before: it evaluates the
   current `OrderFlowPermission` against the intent kind and reduces-only flag.

2. **Capability freshness hard-safety check** — when
   `require_fresh_capability_snapshot=True`, validates that the venue capability
   snapshot and instrument rule snapshot are present, fresh, not future-dated,
   source-healthy, and match the order/context. Freshness runs before venue
   order validation.

3. **Venue Capability hard-validity gate** — decides whether the specific order
   is executable given a snapshot of the venue's current capabilities and
   instrument rules. This gate is only run when
   `require_venue_capability_validation=True` is set on the admission request
   and a matching `VenueOrderValidationContext` is provided.

If the runtime gate blocks an intent, the capability gate is never invoked and
no active executable record is created.

If freshness is required and fails, venue order validation is never invoked. No
unknown or default venue rules are used.

If the capability gate rejects an intent, an auditable `REJECTED_BY_VALIDATION`
lifecycle event is appended with the venue validation reason and details, and no
active executable record is created.

## Capability pass is local acceptance only

Passing capability validation means the order is locally accepted
(`ACCEPTED_BY_EXECUTION`). It does **not** mean the order has been submitted to
the venue. The `SUBMITTED_TO_VENUE` state and beyond remain intentionally
deferred.

## Cancel does not require capability validation

`CancelOrderIntent` admission does not require venue capability validation in
this sprint. The `venue_validation_context` field is ignored for cancel requests
even when `require_venue_capability_validation=True`.

## Replace validates the replacement order

For `ReplaceOrderIntent`, capability validation (when enabled) applies to the
`replacement_order`, not to the target being replaced. The target is mutated to
`REPLACE_REQUESTED` only after the replacement passes runtime permission,
freshness when required, and venue capability validation. If the replacement is
rejected by freshness or venue capability, the target record is not mutated and
no replacement record is created.

## Auditable rejection

Every capability rejection appends a `REJECTED_BY_VALIDATION` lifecycle event
that includes the `request_id`, `order_intent_id`, `client_order_id`, venue
validation reason, and venue validation details. This record survives for audit
even though no active order record is created.

Freshness rejections preserve freshness reason/details and leave venue
validation reason/details empty because venue validation did not run.

## Intentionally deferred

- Real exchange adapters (Binance, KuCoin, CoinEx, MEXC, Phemex)
- Real order submission / cancel / replace / amend to venue
- Execution simulation and matching engine
- Real ledger or accounting mutation
- Official capability ingestion and venue-specific TTL selection
- Rate-limit runtime enforcement
- Dead-man switch runtime enforcement
- HardRiskGate integration
- Persistent stores (PostgreSQL, Redis, Kafka/Redpanda)
- Manual intervention UI/API
- First baseline bot
