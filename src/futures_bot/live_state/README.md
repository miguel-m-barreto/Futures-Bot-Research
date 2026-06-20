# Live State Contracts

This package contains pure domain services and deterministic in-memory doubles for
the future data plane.

The planned durable stream is Kafka/Redpanda-compatible and will become the
canonical source for ordered stream events. Redis is planned only as a live
materialized state projection for latest and rolling bot-facing reads; it is not
the source of historical truth. PostgreSQL is planned for historical events,
audit records, and DB writer checkpoints.

The DB writer contract is micro-batch oriented. Flush decisions are made by
bytes, count, and elapsed wait time, with an optional tighter wait bound for
critical events.

Bots consume freshness-aware snapshots. A snapshot carries stream position,
durability status, staleness, gap-free status, completeness, and speculative
state. Bot-facing policy checks must reject hidden stale, incomplete, or
insufficiently durable state.

Historical DB slices and live tail slices are stitched by stream partition,
offset, event ID, and payload hash. If the DB is persisted through offset `N`
and the live tail starts at `N + 1`, the stitched state may be complete. If the
live tail starts later, the gap is explicit and the result is non-tradable.
Overlaps are accepted only when event IDs and payload hashes match exactly.

Real Kafka/Redpanda, Redis, and PostgreSQL adapters are intentionally deferred.
There are no live APIs, DB schemas, migrations, exchange adapters, bots, order
intents, or execution simulators in this layer.
