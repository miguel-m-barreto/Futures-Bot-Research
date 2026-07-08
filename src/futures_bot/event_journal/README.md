# Event Journal Readiness

Event journal readiness proves that deterministic, source-backed stream evidence
exists for a stream at an explicit `checked_at`.

It is a domain gate, not an infrastructure implementation. It is not Kafka, a
filesystem WAL, Redis LiveState, DBWriter, replay execution, strategy alpha,
market-data ingestion, or order submission.

Strict readiness requires scoped stream identity, deterministic record identity,
sequence and previous-sequence evidence, payload type and payload hash identity,
source trust and health, continuity status, and a stream-scoped checkpoint when
the policy requires one. Gapped, stale, unknown, or wrong-stream evidence is not
tradable state under strict policy.

Market-data readiness and event-journal readiness are separate gates: a ready
market-data decision does not prove journal continuity, and a ready journal
record does not prove bid/ask/depth sufficiency.

Future Kafka, WAL, Redis LiveState, DBWriter, and replay components should
consume these contracts rather than inventing their own event identity,
checkpoint, and continuity semantics.
