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
order, recommended side, or execution instruction. DecisionStack integration is
deferred.

## Replay Projection Timeline

`ReplayMarketEvidenceTimeline` is the deterministic replay artifact for factual
market evidence. It projects one `MarketEvidenceSet` from each
`ReplayMarketFrameProjection` in a validated `ReplayMarketFrameTimeline`.

The `ReplayMarketFrameLookupAuthority` is the membership authority. Every
evidence projection embeds the lookup descriptor, the exact lookup entry, the
exact market frame projection, and the derived evidence set.

The evidence timeline embeds projections, not decision outputs. DecisionStack
integration is deferred; a future evidence lookup can reference this timeline by
replay event and pass compact evidence-set references into decision context.
