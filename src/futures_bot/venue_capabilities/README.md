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

Resolution is backward-compatible by default. Existing snapshots without
provenance can still resolve to ready when
`require_official_source_provenance=False`.

Official provenance can be required explicitly on the resolution request. In
that mode, ready resolution requires both the venue snapshot and instrument rule
snapshot to carry `source_record_id` and `source_payload_hash` values that point
to stored source records. Those records must exist, belong to the same venue, be
accepted for execution, have official trust, be healthy, and match the snapshot
payload hash. Missing or invalid provenance returns a not-ready decision with a
source provenance reason; the resolver never guesses replacement rules.

A ready resolution is only a safe handoff bundle for the downstream capability
gate: resolved snapshots, a freshness check/decision, and a
`VenueOrderValidationContext`. It is not venue submission, and the gateway does
not itself decide whether the order passes venue order rules.

Futures Bot v1 is stablecoin-collateral linear futures only. Supported collateral and
settlement assets are USDT and USDC; inverse, coin-margined, multi-asset collateral,
and portfolio-margin assumptions are intentionally outside this contract.

Dead-man switch, rate-limit, self-trade-prevention, and price-protection capabilities
are modeled as deterministic contracts, but no live runtime enforcement is added here.

Official capability sources are provenance only. A source descriptor records where a
venue capability payload claims to come from, how it may eventually be fetched, its
trust classification, and reference metadata. Reference URIs are never fetched by
these contracts.

Source payloads are canonical JSON-compatible values with deterministic SHA-256
hashes. Source records capture a descriptor, payload, health status, acceptance
reason, and recorded time. They are factual audit records; they are not alpha,
strategy logic, profitability filtering, or risk scoring. Unknown, untrusted, or
test-only sources cannot be silently accepted for execution provenance.

Manual official imports are deterministic contracts for reviewed snapshots. A manual
import requires an accepted official source record and rejects venue or instrument
snapshots whose venue, source record ID, or source payload hash do not match that
record.

The manual official import gateway writes reviewed, source-backed capability data
into the deterministic stores used by resolution. It requires an accepted,
official, healthy source record and venue/instrument snapshots whose venue,
`source_record_id`, and `source_payload_hash` match that source record. The
gateway preflights all source, snapshot, instrument rule, and manual import store
conflicts before writing anything, so invalid or conflicting imports do not
partially populate execution-eligible capability stores. Repeating the same import
is accepted idempotently.

Imported snapshots are immediately usable by strict provenance resolution. When
`require_official_source_provenance=True`, resolution can return ready from these
stores only when the imported source record and snapshot provenance remain
official, healthy, accepted, venue-matched, and payload-hash consistent.

Venue capability snapshots and instrument rule snapshots can carry optional
`source_record_id` and `source_payload_hash` fields. The fields are backward
compatible and optional for existing snapshots, but when one is present the other
must be present too.

Passing freshness and capability validation is still local acceptance only. It is
not real venue submission.

Official exchange ingestion and real adapters remain deferred. Endpoint mapping,
venue-specific payload schemas, source TTLs, manual review workflow, import
approval UI/API, persistent provenance stores, database schemas, runtime ingestion
loops, and adapter-specific source health models require human review before
implementation. This package
performs no network calls, API polling, filesystem persistence, database writes,
order submission, cancel, replace, or simulation.
