
# Whole Project Audit - Sprint 52 / Review 124

Date: 2026-07-03
Workspace: `/home/miguel/Desktop/Futures-Bot-Research`

This was a read-only architecture and consistency audit. Source code and tests were not modified.
This report file is local human-review output only.

## A. Executive summary

Overall architecture health: strong for a pre-adapter, pre-ledger, safety-first research foundation. The project has clear boundary modules, deterministic IDs, explicit Pydantic validation, pure in-memory stores, no real exchange submission path, no live adapters, and broad tests.

Safety-first status: still safety-first. Runtime control, venue capability resolution, freshness validation, source provenance, manual import, order lifecycle, and execution admission all bias toward explicit rejection and auditability.

New doctrine status: partially reflected. The newest capability and asset-semantics layer models real futures/collateral complexity from the start: linear/inverse/quanto payoff, collateral mode, settlement/PnL/objective/valuation assets, readiness gates, and cross-venue exposure comparability. However, several older public domain contracts still encode stablecoin-only constraints, and the top-level public README/package metadata still describes a stablecoin-collateral scope.

Highest priority risks:

- Active legacy stablecoin-only contracts remain in `domain.assets`, `domain.bots`, `domain.buckets`, `domain.decisions`, `domain.execution`, and `domain.replay`.
- Execution admission can create an accepted local execution record without capability validation when the request does not require it. This is documented as local-only, but future venue submission must not consume these records as executable without a mandatory second gate.
- Generalized asset semantics are mostly readiness/gating contracts. They do not yet include valuation source records, haircut policies, conversion policies, liquidation formulas, fee/funding models, or multi-leg bundle state.
- Public docs and package metadata contradict the v18 private doctrine.

Ready for next implementation sprint: yes, if the next sprint is doctrine-alignment and domain hardening. Not ready for any sprint that adds venue adapters, simulators, live submission, strategy execution, or ledger mutation.

Validation run:

- `.venv/bin/python -m pytest`: 2914 passed, 13 Pydantic serializer warnings from tampering/negative tests, 917.99s.
- `.venv/bin/python -m ruff check .`: passed.
- `.venv/bin/python -m pyright`: 0 errors, 0 warnings, 0 informations. Pyright reported a newer version is available.

## B. Critical blockers

### 1. Active legacy stablecoin-only domain contracts conflict with v18 doctrine

Severity: High architecture blocker before expanding domain or execution surface.

Files involved:

- `src/futures_bot/domain/assets.py:10-12`, `src/futures_bot/domain/assets.py:60-84`
- `src/futures_bot/domain/bots.py:7`, `src/futures_bot/domain/bots.py:33-38`, `src/futures_bot/domain/bots.py:53`
- `src/futures_bot/domain/buckets.py:5`, `src/futures_bot/domain/buckets.py:16`
- `src/futures_bot/domain/decisions.py:11`, `src/futures_bot/domain/decisions.py:94-103`
- `src/futures_bot/domain/execution.py:10`, `src/futures_bot/domain/execution.py:102-128`
- `src/futures_bot/domain/replay.py:14`, `src/futures_bot/domain/replay.py:63-93`

Why it matters:

The v18 doctrine says the domain must not be modeled as stablecoin-only with later patches. These contracts are active public models and are tested. They reject ETH/BTC/BNB/SOL collateral or objective/capital forms before capability/risk gates can decide whether execution is allowed. That makes stablecoin-only an embedded domain assumption, not merely an execution gate.

Concrete reproduction/code path:

- `StableCollateralAsset("BTC")` fails by allowlist.
- `BotBlueprint(initial_capital=AssetAmount(asset="ETH", ...))` fails through `StableCollateralAsset(self.initial_capital.asset)`.
- `DecisionIntent(proposed_margin=AssetAmount(asset="ETH", ...))` fails through `StableCollateralAsset(str(value.asset))`.
- `ExecutionIntent` requires `quote_asset: StableCollateralAsset` and `max_margin.asset == quote_asset.symbol`.
- `ReplayInstrumentRef.settlement_asset` and `quote_asset` are `StableCollateralAsset`, so replay input contracts cannot represent BTC-settled inverse futures.

Recommended fix sprint:

Sprint 52A: Legacy Asset/Capital Contract Generalization. Replace stable-only fields with explicit `AssetSymbol`, `AssetDescriptor`, `CapitalAssetPolicy`, `CollateralAccountMode`, and execution/readiness gates. Keep USDT/USDC as supported cases, not model roots.

### 2. Accepted execution records do not themselves prove capability/freshness/provenance validation

Severity: High blocker before any venue submission or simulator consumes `ACCEPTED_BY_EXECUTION` records.

Files involved:

- `src/futures_bot/domain/execution_manager.py:71-84`
- `src/futures_bot/execution_manager/coordinator.py:176-309`
- `src/futures_bot/execution_manager/coordinator.py:310-342`
- `src/futures_bot/domain/order_lifecycle.py:344-395`

Why it matters:

`ExecutionAdmissionRequest` makes venue capability validation optional. If disabled, `_admit_order_intent` still appends `ACCEPTED_BY_EXECUTION` and creates an active local record. The README correctly says this is local acceptance only, and no venue submission exists. But the accepted record does not carry a mandatory validation status, freshness decision ID, source provenance state, or "not venue-executable" marker. A future submission path could accidentally treat local acceptance as executable.

Concrete reproduction/code path:

1. Build an `ExecutionAdmissionRequest` with `require_venue_capability_validation=False`.
2. Runtime permission allows the order.
3. Coordinator appends `ACCEPTED_BY_EXECUTION` and stores an `ExecutionOrderRecord`.
4. The record has no field proving capability/freshness/provenance validation occurred.

Recommended fix sprint:

Sprint 52B: Execution Record Readiness State. Split local admission from execution readiness, or attach explicit `capability_validation_status`, `freshness_status`, `provenance_status`, and `venue_submission_eligible=False` unless a strict gate passes. Require any future simulator/submission path to revalidate from source-backed snapshots.

## C. Major inconsistencies

- Public docs vs private doctrine: `README.md:17-34` says current implementation supports stablecoin-collateral futures only and lists coin-margined/inverse/multi-asset/portfolio margin as out of scope. `README_docs.md:24-26`, `Glossary.md:332-352`, `Risk_Gate_Explanation.md:237-268`, and `trading_bot_consolidated_final_technical_plan.md:14-66` say the domain is not stablecoin-only.
- Package metadata drift: `pyproject.toml:8` still describes a stablecoin-collateral futures foundation.
- Duplicate/conflicting `StableCollateralAsset` concepts: `domain.assets.StableCollateralAsset` is a Pydantic model with allowlist; `domain.venue_capabilities.StableCollateralAsset` is a StrEnum used by the legacy validator. This increases naming ambiguity.
- Contract-kind naming is split. `domain.asset_semantics.ContractPayoffKind` has `LINEAR`, `INVERSE`, `QUANTO`; `domain.venue_capabilities.FuturesContractKind` has `LINEAR_PERPETUAL`, `LINEAR_DELIVERY`, `INVERSE_PERPETUAL`, `INVERSE_DELIVERY`, `SPOT`, `UNKNOWN`, but not explicit coin-margined, portfolio margin, or quanto contract families.
- The venue capability README says the architecture is not stablecoin-only, but `venue_capabilities.validator` still falls back to a legacy stable-only validator whenever `asset_semantics` is absent.
- Some audit-only rejection lifecycle events for active cancel/replace targets use `CREATED -> REJECTED_BY_PERMISSION` in `_append_rejection_for_target`, even though the target record is active and not mutated. This is not an active state mutation bug, but it is semantically confusing for audit readers.

## D. Hidden stablecoin-only or single-collateral assumptions

- `domain.assets.StableCollateralAsset`: wrong and should be generalized for domain-level capital/collateral models. Still valid only as one supported asset-family helper.
- `domain.bots.BotBlueprint.initial_capital` stable validation and `BotInstance.capital_asset`: wrong and should be generalized.
- `domain.buckets.BucketState.capital_asset: StableCollateralAsset`: wrong and should be generalized.
- `domain.decisions.DecisionIntent.proposed_margin` stable validation: wrong and should be generalized.
- `domain.execution.ExecutionIntent.quote_asset: StableCollateralAsset` and `max_margin` equality: wrong and should be generalized or deprecated behind newer `order_lifecycle` intent contracts.
- `domain.replay.ReplayInstrumentRef.settlement_asset` and `quote_asset`: wrong for inverse/coin-margined replay. Should support general asset refs and contract/payoff semantics.
- `venue_capabilities.validator._legacy_contract_and_asset_reason`: already handled by capability/risk gate only if `asset_semantics` is present. Without `asset_semantics`, it remains a stable-only legacy fallback.
- Tests and fixtures heavily use USDT/USDC. Valid as supported cases, but insufficient as doctrine proof. The newer tests for asset semantics and cross-venue exposure are the right direction.
- README and pyproject wording: documentation-only cleanup, but important because it can guide future implementation in the wrong direction.

## E. Risk/safety audit

Properties that hold:

- Runtime permission is checked before active record creation for new order intents. Permission rejections do not create active records.
- Freshness validation happens before venue order validation when `require_fresh_capability_snapshot=True`.
- Venue capability rejection creates rejection events/decisions and no active record.
- Replace validation targets the replacement order and does not mutate the target until replacement passes runtime permission, freshness, and capability validation.
- Manual official import validates source/provenance and preflights store conflicts before writing.
- Resolution missing/stale/source-invalid paths return not-ready and do not fabricate a `VenueOrderValidationContext`.
- No real exchange adapters, HTTP/API polling, websocket clients, venue submission, execution simulator, strategy/bot runtime, ledger mutation, DB persistence, Kafka/Redis/Postgres adapters, async runtime, or threading were found in production code.

Findings:

- High: accepted local execution records need explicit readiness/provenance fields before any future submission/simulator path.
- Medium: runtime kill-switch checks happen before emergency/program-state checks, so the reported permission reason can mask a simultaneous emergency halt. Blocking behavior is safe; diagnostic priority may need policy.
- Medium: source/capability snapshot stores are deterministic, but not transactional beyond in-memory preflight. Future persistent stores must preserve the all-or-nothing manual import contract.
- Low: audit rejection events for cancel/replace permission rejections may be semantically misleading because they are modeled as `CREATED -> REJECTED_BY_PERMISSION` rather than target-state-specific rejection facts.

## F. Data model audit

Strengths:

- Pydantic models are mostly frozen with `extra="forbid"`.
- Decimal coercion rejects floats in money/quantity paths.
- IDs are deterministic and validated across many models.
- Details/payload fields generally enforce JSON compatibility.
- Asset semantics now separate base, quote, margin, collateral, settlement, PnL, objective, valuation reference, payoff kind, collateral mode, settlement mode, and contract size.
- Cross-venue comparability rejects mismatched base/quote/payoff/settlement/PnL/contract-size/valuation-reference.

Gaps:

- Stablecoin-only legacy models remain active.
- `ContractAssetSemantics` has booleans for haircut/conversion requirements but no concrete haircut policy or conversion policy IDs. Current readiness must reject when those booleans are true. That is safe, but it means these are not yet executable-ready semantics.
- `ValuationRequirement.REQUIRED_FOR_MARGIN` and `REQUIRED_FOR_PNL` exist but are not emitted by `_valuation_requirements`.
- `VenueCapabilitySnapshot` and `VenueInstrumentRuleSnapshot` use plain strings for supported assets and margin/settlement assets. They do not enforce the stricter `AssetSymbol` format.
- Venue capability snapshots do not yet model margin modes, portfolio margin formulas, collateral haircuts, conversion rules, liquidation semantics, fee/funding assets, funding schedules, depth/slippage, or rate-limit runtime counters.
- `OrderIntent` lacks explicit margin/collateral/settlement/PnL/objective/valuation fields. It relies on instrument/capability context.
- No `BundleIntent`, `MultiLegExposure`, residual delta, max unhedged duration, hedge/abort policy, or bundle lifecycle model exists yet.

## G. Store/idempotency audit

Strengths:

- Source, venue snapshot, instrument rule, manual import, lifecycle event, admission decision, and many replay stores accept exact idempotent repeats and reject same-ID/different-payload collisions.
- Latest venue/rule selection is deterministic by `(captured_at, snapshot_id)`.
- Append-order stores preserve deterministic listing order or sort by stable timestamps/IDs.
- Manual import gateway preflights source, venue snapshot, instrument rule, and manual import conflicts before writing.

Findings:

- Medium: `InMemoryRuntimeManifestStore.save` allows replacing the manifest mapped to the same stack with a different manifest ID without an explicit conflict or latest-selection policy.
- Medium: `InMemoryDecisionStackCheckpointStore.save` overwrites the latest checkpoint by stack ID without forward-only or epoch/revision checks.
- Low: `InMemoryExecutionOrderRecordStore.upsert` intentionally mutates lifecycle state for existing records, but this means it is not a pure same-ID/same-payload idempotency store. That is acceptable for order state, but future persistent implementations need compare-and-swap/versioning.
- Low: in-memory stores are deterministic test doubles, not durability or transaction boundaries.

## H. Test quality audit

Strengths:

- Very broad suite: 2914 tests.
- Coverage includes happy paths, rejection paths, idempotency, deterministic IDs, JSON-compatible details, boundary scans, source provenance, manual import, capability freshness, execution admission ordering, replace/cancel mutation safety, cross-venue exposure comparability, market frame authority collisions, and no external infra imports.
- Boundary tests explicitly prevent tests from reading Markdown docs and scan for forbidden infrastructure/runtime dependencies.
- Newer tests verify non-stable collateral can pass venue validation when explicit asset semantics are ready.

Gaps:

- Stablecoin-heavy fixtures remain dominant and can preserve old assumptions by inertia.
- Legacy models are not tested against ETH/BTC collateral in a way that would reveal doctrine mismatch as a failing test.
- Tests do not yet assert that accepted execution records carry explicit capability/freshness/provenance readiness status.
- No tests for haircut policy IDs, conversion policy IDs, valuation source freshness, liquidation formulas, fee/funding/depth cost semantics, multi-leg lifecycle, residual exposure, or bundle protection.
- Some tests assert exact implementation details and private helper behavior; useful for regression, but brittle as generalized domain contracts are refactored.

## I. Naming and API consistency

- `source` vs `provenance`: market data uses both correctly, but capability sources use `source_record_id`/`source_payload_hash` while resolution uses `provenance_*` fields. This is acceptable but should be documented as "source record proves provenance".
- `capability` vs `readiness`: venue capability validation means hard venue/instrument rule validation; asset semantics readiness and resolution readiness are separate. The names are clear enough but need stronger API handoff docs.
- `snapshot` vs `rule snapshot`: mostly clear.
- `record` vs `decision`: admission decisions and order records are distinct. However, `ACCEPTED_BY_EXECUTION` can sound more executable than it is.
- `pnl_asset` vs `settlement_asset`: explicitly separated in new semantics; legacy replay and execution contracts still compress these.
- `margin_asset` vs `collateral_asset`: explicitly separated in new semantics; legacy validator checks only margin/settlement strings unless asset semantics are present.
- `FuturesContractKind` should be renamed or extended to avoid hiding coin-margined/quanto/portfolio cases behind payoff/collateral modes.

## J. Documentation audit

Good docs:

- Private v18 docs clearly state no stablecoin-only domain assumption.
- Venue capability README accurately explains freshness, provenance, manual import, no network calls, and no venue submission.
- Runtime and exposure docs clearly express fail-closed/fail-protected doctrine.

Gaps:

- `README.md` is outdated and still states stablecoin-collateral-only sprint scope.
- `pyproject.toml` description is outdated.
- Public docs should describe stablecoin-margined linear futures as one supported case, not the current domain assumption.
- Public docs should explain the split between generalized domain modeling and execution gating.
- Public docs should mention inverse/coin-margined/multi-collateral/portfolio margin as domain concepts that are gated pending official rules.
- Public docs should include source provenance/manual import/resolution gateway summaries or link to module docs.
- Public docs should warn that cross-venue price dislocation is not executable arbitrage until comparability, cost, depth, latency, funding, liquidation, capital, and leg-risk semantics exist.

## K. Cross-venue arbitrage/dislocation audit

Scenario: Binance ETHUSDT future = 1200, KuCoin ETHUSDT future = 1333.

Current structure that helps:

- `EconomicExposureDescriptor` can compare base asset, quote asset, payoff kind, settlement asset, PnL asset, valuation reference asset, and contract size.
- Tests cover the exact price-dislocation example as comparable only after exposure fields match.
- `CrossVenueMarketFrame` can hold multi-venue observations for the same logical instrument without selecting a preferred venue or alpha.
- Market observations distinguish trades, top-of-book, mark price, and index price.
- Source health exists as explicit frame input and is not fabricated.

Missing before any arbitrage strategy sprint:

- Venue Descriptor Registry with product family, contract kinds, collateral/margin modes, source templates, and manual import eligibility.
- Collateral valuation and haircut policies.
- Objective asset policy and conversion/benchmark semantics.
- Fee/funding/depth/slippage/latency cost model.
- Mark/index/last price dislocation semantics.
- Bundle/multi-leg intent and lifecycle.
- Multi-leg exposure guardian with residual delta and max unhedged duration.
- Venue-specific liquidation semantics.
- Capital availability per venue/account/asset.
- Transfer delay and "capital must be pre-positioned" policy.
- Cross-venue reconciliation for orders, fills, positions, account state, and collateral.

Conclusion: current code can identify whether two venue instruments are comparable enough to discuss a spread. It cannot yet decide that the spread is executable arbitrage.

## L. Recommended next sprints

### Sprint 52A - Legacy Stablecoin Contract Generalization

Goal: remove stablecoin-only assumptions from active public domain contracts.
Files likely touched: `domain/assets.py`, `domain/bots.py`, `domain/buckets.py`, `domain/decisions.py`, `domain/execution.py`, `domain/replay.py`, affected tests.
Why next: prevents old contracts from shaping future implementation.
Main invariants: USDT/USDC remain valid; ETH/BTC collateral can be represented; execution remains gated.
Expected tests: ETH/BTC collateral representation, USDT/USDC unchanged, no implicit conversion, legacy deprecation path.
Risk level: High.

### Sprint 52B - Execution Readiness State

Goal: separate local admission from venue-executable readiness.
Files likely touched: `domain/execution_manager.py`, `domain/order_lifecycle.py`, `execution_manager/coordinator.py`, tests.
Why next: prevents future venue submission from consuming locally accepted but ungated records.
Main invariants: accepted local record is not executable unless capability/freshness/provenance readiness is explicit.
Expected tests: accepted-without-capability is not venue-submission eligible; strict provenance acceptance records decision refs.
Risk level: High.

### Sprint 53 - Venue Descriptor Registry

Goal: model canonical venue descriptors for Binance, KuCoin, CoinEx, MEXC, Phemex without adapters.
Files likely touched: new `domain/venue_descriptors.py`, `venue_capabilities/`, tests.
Why next: capability snapshots need venue/product/account context.
Main invariants: no network calls; descriptors are facts/templates, not execution permission.
Expected tests: product family coverage, source descriptor links, no stablecoin-only descriptor schema.
Risk level: Medium.

### Sprint 54 - Collateral Valuation and Haircut Policy

Goal: add explicit valuation snapshots, haircut policy IDs, collateral eligibility, stale valuation rejection.
Files likely touched: `domain/asset_semantics.py`, `venue_capabilities/validator.py`, tests.
Why next: multi-collateral cannot be executable-ready without valuation/haircut semantics.
Main invariants: no implicit ETH/BTC/USD/USDT conversion; stale valuation blocks execution.
Expected tests: objective/collateral valuation required, haircut missing rejects, fresh valuation can mark readiness.
Risk level: High.

### Sprint 55 - Objective Asset Policy

Goal: define how bot objective asset differs from PnL/settlement asset.
Files likely touched: asset semantics, decisions/intents, research/evaluation contracts.
Why next: prevents alpha/evaluation from silently assuming account currency.
Main invariants: objective asset explicit; conversion/benchmark/hold policy explicit.
Expected tests: USDT PnL with ETH objective requires policy; matching PnL/objective remains simple.
Risk level: Medium.

### Sprint 56 - Cross-Venue Market Dislocation Semantics

Goal: model spread observations without calling them executable arbitrage.
Files likely touched: `domain/market_data.py`, `evidence/`, new dislocation contracts, tests.
Why next: builds on comparability without adding strategy.
Main invariants: mark/index/last/top-of-book distinguished; stale source blocks evidence readiness.
Expected tests: Binance 1200 / KuCoin 1333 produces dislocation observation only after comparable exposure and fresh sources.
Risk level: Medium.

### Sprint 57 - Fees/Funding/Depth Cost Model

Goal: add deterministic cost context for fees, funding, book depth, slippage, and latency assumptions.
Files likely touched: domain cost models, market evidence, venue capabilities, tests.
Why next: spread is meaningless without execution cost.
Main invariants: no profitability claim without cost model; missing cost data blocks executable edge.
Expected tests: fee/funding/depth missing rejects arbitrage readiness; deterministic cost fingerprints.
Risk level: High.

### Sprint 58 - Liquidation Semantics

Goal: model margin mode, maintenance margin, liquidation buffer, liquidation fee/penalty, and venue-specific formula provenance.
Files likely touched: venue capabilities, asset semantics, risk domain, tests.
Why next: futures execution cannot be safe without liquidation modeling.
Main invariants: unknown liquidation formula blocks execution; source-backed formulas required.
Expected tests: isolated/cross/portfolio cases; unknown formula rejection; source provenance.
Risk level: High.

### Sprint 59 - HardRiskGate Integration

Goal: connect runtime permission, capability readiness, valuation, liquidation, and policy into a hard validity gate.
Files likely touched: `domain/risk.py`, execution manager, runtime control, tests.
Why next: consolidates hard safety before simulator or adapters.
Main invariants: RiskGate is not alpha; missing facts reject; protective exits remain modeled separately.
Expected tests: entry blocked on stale valuation/capability/runtime gap; reduce-only allowed under protection policy.
Risk level: High.

### Sprint 60 - Ledger/Accounting Model

Goal: introduce asset-denominated ledger contracts without persistence or mutation side effects.
Files likely touched: `domain/ledger.py` or `ledger/`, asset models, tests.
Why next: fees/funding/PnL/settlement need an accounting authority before simulation/live.
Main invariants: no generic USD; no invented baseline; all events asset-denominated and source-backed.
Expected tests: fills, fees, funding, realized PnL, settlement, reconciliation events by asset.
Risk level: High.

### Sprint 61 - Multi-Leg Intent and Bundle Lifecycle

Goal: model bundle intents, leg states, partial fills, residual exposure, hedge/abort policy.
Files likely touched: order lifecycle, execution manager, runtime control, tests.
Why next: needed before cross-venue arbitrage can be simulated.
Main invariants: one filled leg is real exposure; no cross-exchange atomicity assumption.
Expected tests: partial fill activates bundle protection; max unhedged duration breach; target reconciliation.
Risk level: High.

### Sprint 62 - Multi-Leg Exposure Guardian

Goal: protect bundle/multi-venue exposure during failed or stale legs.
Files likely touched: runtime control, exposure safety, order lifecycle, tests.
Why next: closes the largest arbitrage safety gap.
Main invariants: no orphan bundle legs; stale venue on one leg blocks new entries and allows hedge/reduce/cancel paths.
Expected tests: venue outage per leg, residual delta threshold, manual intervention path.
Risk level: High.

## Final status

No source code, tests, or public docs were changed during this audit. Only this report file was created.

NEEDS_HUMAN_REVIEW
