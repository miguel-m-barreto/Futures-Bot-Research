# Market Data Boundary

Market data represents market facts with explicit provenance.

Raw venue events flow through future venue adapters into typed
`NormalizedMarketObservation` objects. Source-health monitoring records whether a
source or stream is live, stale, disconnected, unsupported, or otherwise degraded.
The pure frame builder then produces a `CrossVenueMarketFrame` for one logical
instrument and decision time. Future evidence/features and future decision
context, including future DecisionStack context, may consume those frames.

```text
raw venue events
-> venue adapter
-> NormalizedMarketObservation
-> source-health monitoring
-> CrossVenueMarketFrame
-> future EvidenceSet/features
-> future DecisionStack context
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
