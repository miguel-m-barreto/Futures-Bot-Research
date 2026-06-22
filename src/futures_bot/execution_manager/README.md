# Execution Manager Contracts

This package contains the deterministic local execution-manager coordinator.

DecisionStack code only proposes order, cancel, and replace intents. The
ExecutionManager owns lifecycle authority: it evaluates runtime order-flow
permission, appends auditable lifecycle events, and creates or updates local
execution records.

Admission accepted is not venue submission. Accepted order intents stop at
`ACCEPTED_BY_EXECUTION`; cancel and replace intents stop at local
`CANCEL_REQUESTED` or `REPLACE_REQUESTED`. This layer never creates venue
acknowledgements, fills, ledger mutations, or exchange IO.

Permission rejections are auditable and do not create active venue-submission
records. Unknown or untrusted target order state creates a reconciliation
marker instead of querying a venue.

Real exchange adapters, submit/cancel/replace operations, execution simulation,
fill ingestion, ledger/accounting integration, and persistent stores are
intentionally deferred.
