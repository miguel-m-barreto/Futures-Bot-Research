# Decision Boundary

The decision layer creates `DecisionIntent` and `NoTradeDecision`.

It does not create orders directly. It does not mutate Ledger. It does not
bypass RiskGate.

## Replay Decision Context

The generic replay runtime and dispatcher stay market-agnostic. They continue to
invoke replay handlers with only `ReplayDispatchContext` and
`ReplayTimelineEvent`.

`ReplayDecisionStackHandler` is the market- and evidence-aware decision
boundary. It uses a `ReplayMarketFrameLookupPort` to resolve the exact
deterministic market frame and a `ReplayMarketEvidenceLookupPort` to resolve
the factual evidence set known at the same replay event boundary, builds a
`ReplayDecisionStackContext`, and calls:

```python
DecisionStackPort.decide(context)
```

The DecisionStack receives one cohesive context object containing the dispatch
context, timeline event, market lookup result, evidence lookup result,
observation projection, frame projection, `CrossVenueMarketFrame`, and factual
`MarketEvidenceSet`. It no longer receives a separate event argument.

Replay decision outputs use schema v3. Their deterministic decision IDs commit
to the composite decision handler fingerprint, the compact market context
reference, and the compact evidence context reference. Changing the market
timeline, adapter authority, observation, frame, evidence lookup authority,
evidence projection, or evidence set changes the decision identity.

Journal payloads do not duplicate full market frames or full
`MarketEvidenceSet` objects. They store compact
`ReplayDecisionMarketContextReference` and
`ReplayDecisionEvidenceContextReference` records with the IDs and fingerprints
needed for audit lookup.

Evidence in the decision context is factual only, not a recommendation. The
first baseline DecisionStack bot, DB persistence, RiskBehaviorModel,
HardRiskGate, order execution, Ledger mutation, feature pipelines, and live API
adapters remain future boundaries.
