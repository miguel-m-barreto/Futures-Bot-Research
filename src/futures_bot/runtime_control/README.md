# Runtime Control Contracts

This package defines pure runtime safety and control-plane contracts.

A DecisionStack is not the sole owner of open exposure. When a stack is paused,
stopped, restarted, halted, or stale, open exposure must remain owned by an
explicit protection path such as guardian management, reduce-only handling,
exchange-side protection, closing, or manual intervention.

Open position gaps activate guardian/protection semantics. New entries are
blocked immediately when runtime state, data health, reconciliation state, or a
kill switch makes the system unsafe. Exit, reduce-only, cancel, reconciliation,
and emergency-close paths are modeled separately so protective actions can remain
available while alpha entries are blocked.

Startup, resume, restart, and resync flows must pass through resync and warm-up
before a stack may return to RUNNING. A disabled stack must not auto-start.

Kill switches are scoped by global, venue, instrument, account, decision stack,
submission, and execution domains. Scope matching is pure and deterministic.

Real runtime orchestration, guardian services, order adapters, exchange
reconciliation, live APIs, persistent manifests/checkpoints, and data-plane
adapters are intentionally deferred.
