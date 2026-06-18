# Market Data Boundary

Market data represents market facts with explicit provenance.

Raw venue events flow through future venue adapters into typed
`NormalizedMarketObservation` objects. Source-health monitoring records whether a
source or stream is live, stale, disconnected, unsupported, or otherwise degraded.
The pure frame builder then produces a `CrossVenueMarketFrame` for one logical
instrument and decision time. Replay DecisionStack context may consume
deterministic replay frames through a lookup boundary; future evidence/features
remain separate.

```text
raw venue events
-> venue adapter
-> NormalizedMarketObservation
-> source-health monitoring
-> CrossVenueMarketFrame
-> future EvidenceSet/features
-> replay DecisionStack context lookup
```

The source is where data was received from. The venue is where the market or
quoted product exists. A venue symbol is the venue-native name, while the logical
instrument is only the normalized pair. The logical pair is not the full tradable
contract identity.

`MarketObservationId` identifies one normalized ingestion observation, including
local receive provenance such as receive time, connection identity, reconnect
generation, and monotonic timestamp. It is not a provider-independent canonical
source-event deduplication key across reingestion or replay.

Spot, perpetual, delivery future, leveraged-product, reference, and index facts
remain separate even when they share a logical pair. Observed quotes are not
guaranteed fill prices. Stale or missing sources are represented as stale or
missing; they are not silently replaced by another source.

The frame builder does not generate alpha, consensus prices, preferred venues,
leader venues, lagger venues, fallback prices, or merged books. Lead-lag remains
a future measured hypothesis, and no venue is assumed to lead permanently.

## Replay Projection

Replay market projection keeps `ReplayInputRecord.payload` in the validated
`ReplayInputBatch`. `ReplayTimelineEvent` remains a metadata reference to the
batch, dataset, record, event kind, instrument, event time, sequence, order
index, and content hash.

`ReplayMarketDataBinding` explicitly maps the legacy replay instrument identity
to the market-data source and venue-instrument authority. The projection does not
infer market kind, settlement, collateral, or venue aliases from raw symbols.

`EVENT_TIME_AS_SOURCE_AND_RECEIVED` is deterministic legacy replay behavior:
source event time and received time both come from the replay record event time,
engine time is absent, monotonic time is zero, and reconnect generation is zero.
This does not claim real receive latency and is unsuitable for real latency or
lead-lag measurement.

Replay market frames are generated in replay timeline order. Same-timestamp
later events do not enter earlier frames. `LocalReplayMarketFrameLookup` indexes
the validated `ReplayMarketFrameTimeline` by `(event_id, event_order_index)` and
returns the exact paired observation/frame projections for a replay event
boundary. The generic replay runtime and dispatcher remain market-agnostic.

`ReplayDecisionStackHandler` performs the lookup inside the decision handler
boundary and passes a `ReplayDecisionStackContext` to the DecisionStack. Decision
outputs store compact context references: market timeline ID, adapter
fingerprint, projection IDs, frame ID, triggering observation ID, and binding
authority fingerprint. They do not duplicate the complete market frame or all
observation payloads in the journal.

The projection does not fabricate source-health state. RiskBehaviorModel,
HardRiskGate, execution, live APIs, feature pipelines, EvidenceSet generation,
and replay source-health events remain future boundaries.
