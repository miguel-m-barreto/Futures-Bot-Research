# Decision Boundary

The decision layer creates `DecisionIntent` and `NoTradeDecision`.

It does not create orders directly. It does not mutate Ledger. It does not
bypass RiskGate.

## Replay Decision Context

The generic replay runtime and dispatcher stay market-agnostic. They continue to
invoke replay handlers with only `ReplayDispatchContext` and
`ReplayTimelineEvent`.

`ReplayDecisionStackHandler` is the market-aware decision boundary. It uses a
`ReplayMarketFrameLookupPort` to resolve the exact deterministic market frame
known at the replay event boundary, builds a `ReplayDecisionStackContext`, and
calls:

```python
DecisionStackPort.decide(context)
```

The DecisionStack receives one cohesive context object containing the dispatch
context, timeline event, lookup result, observation projection, frame projection,
and `CrossVenueMarketFrame`. It no longer receives a separate event argument.

Replay decision outputs use schema v2. Their deterministic decision IDs commit
to the composite decision handler fingerprint and the exact market context ID,
so changing the market timeline, adapter authority, observation, or frame
changes the decision identity.

Journal payloads do not duplicate full market frames. They store a compact
`ReplayDecisionMarketContextReference` with IDs and fingerprints needed for
audit lookup: market timeline ID, adapter fingerprint, observation projection
ID, frame projection ID, frame ID, triggering observation ID, and binding
authority fingerprint.

RiskBehaviorModel, HardRiskGate, order execution, Ledger mutation, EvidenceSet
generation, feature pipelines, and live API adapters remain future boundaries.
