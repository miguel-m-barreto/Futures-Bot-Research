# Order Lifecycle Contracts

This package contains pure contracts and deterministic in-memory doubles for
order intent and execution lifecycle state.

A DecisionStack may propose an `OrderIntent`, but Execution owns lifecycle
authority. Intent creation, submission, venue acknowledgement, fills, cancels,
replace requests, unknown venue state, reconciliation, and closure are modeled
as explicit lifecycle states and append-only events.

Entry orders are separated from exit, protective, reduce-only, cancel, and
emergency-close flows. Runtime `OrderFlowPermission` gates each flow
independently so blocked entries do not automatically block protection or
exposure-reducing actions. Exit, reduce-only, protective, and emergency-close
intents are validated so they cannot silently become exposure-increasing entry
orders.

Client order IDs and idempotency keys are deterministic from canonical intent
fields. In-memory stores accept exact idempotent repeats and reject ID
collisions with different payloads.

Unknown venue state is represented explicitly and must move through
reconciliation before closure. Reconciliation markers identify the affected
scope and related order records or client order IDs, but this sprint does not
mutate a ledger or contact a venue.

No real exchange execution is implemented here. Real order adapters, venue
flags, execution simulation, persistent stores, ledger integration, and bot
integration are intentionally deferred.
