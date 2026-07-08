# Asset Conversion Evidence

Asset conversion readiness proves scoped asset comparability for a specific
from-asset, to-asset, policy, and checked-at timestamp.

It does not fetch live prices, provide strategy alpha, submit orders, mutate
ledger/accounting state, or prove execution readiness.

USDT, USD, USDC, BTC, ETH, and every other asset symbol remain distinct unless
there is explicit source-backed conversion readiness for the exact path being
evaluated. A BTC->USDT decision does not prove USDT->BTC unless the policy
explicitly allows inverse-rate evidence and the inverse snapshot matches.
Triangulation is likewise policy-gated and every leg must connect in order.

Collateral valuation readiness is not generic conversion evidence. It may prove
collateral valuation for collateral policy paths, but it does not prove PnL,
settlement, objective, or reference conversion by itself.

Objective asset readiness can consume scoped conversion evidence. It cannot
invent conversion evidence or treat unrelated READY decisions as interchangeable.

Margin/liquidation readiness is a separate gate. Conversion evidence does not
prove margin mode, risk tier, leverage, maintenance margin, or liquidation model
semantics.

Execution cost readiness is also separate. Conversion evidence does not prove
maker fees, taker fees, funding rules, spread limits, or executable depth.
