# Market Evidence

`MarketEvidenceSet` is factual market evidence derived from one validated
`CrossVenueMarketFrame`.

The complete source frame is embedded in the evidence set as the derivation
authority. Every item is a direct field extraction from an observation payload or
a source-health snapshot in that frame. The builder does not read future data,
look up other frames, inspect clocks, call models, or fetch external data.

Source health is emitted only when the source frame contains source-health
snapshots. Missing source health remains missing.

This package does not calculate midpoint, spread, basis, residuals, lead-lag,
order-book imbalance, microprice, funding, liquidation, executable edge, or
confidence. Those require explicit deterministic derivation policies.

`TechnicalEvidence` and the existing `EvidenceSet` remain separate analytical
contracts. Factual market evidence is not a target, decision, risk verdict,
order, recommended side, or execution instruction.

## Replay Projection Timeline

`ReplayMarketEvidenceTimeline` is the deterministic replay artifact for factual
market evidence. It projects one `MarketEvidenceSet` from each
`ReplayMarketFrameProjection` in a validated `ReplayMarketFrameTimeline`.

The `ReplayMarketFrameLookupAuthority` is the membership authority. Every
evidence projection embeds the lookup descriptor, the exact lookup entry, the
exact market frame projection, and the derived evidence set.

The evidence timeline embeds projections, not decision outputs. Decision output
envelopes use compact references to this evidence rather than duplicating full
evidence sets.

## Replay Evidence Lookup

`ReplayMarketEvidenceLookupAuthority` is the deterministic membership authority
for looking up evidence by replay event. It contains compact lookup entries
derived from a `ReplayMarketEvidenceTimeline`, with one entry per evidence
projection.

`ReplayMarketEvidenceLookupDescriptor` is the compact boundary descriptor. It
binds the evidence timeline, replay timeline, replay plan, market-frame lookup
authority fingerprint, evidence builder fingerprint, and supported event kinds
without embedding every entry.

`LocalReplayMarketEvidenceLookup` accepts a `ReplayDispatchContext` and matching
`ReplayTimelineEvent`, then returns a `ReplayMarketEvidenceLookupResult` proving
the compact entry and complete projection agree.

`ReplayDecisionStackContext` now includes that deterministic lookup result. The
decision output envelope keeps only compact market and evidence context
references, and decision IDs commit to both. The first real bot and DB
persistence remain deferred.
