# Sprint Contract: StockPro Platform Professionalization

> Status: Active from 2026-08-09. This contract supersedes the completed or
> historical `active-*` contracts for current delivery priority; those files
> remain as implementation history.

## Goal

Turn the current local StockPro build into a trustworthy, professional A-share
quant research and strategy-development platform. Every visible metric and
state must be backed by one coherent evidence chain, every core workflow must
be operable or explain why it is unavailable, and every completed fix must have
repeatable automated and browser acceptance evidence.

## Delivery Strategy

Work in small, independently verifiable slices, in this order:

1. Correct data and runtime truthfulness defects that can mislead an operator.
2. Isolate test/acceptance objects from business workspaces.
3. Complete broken, clipped or inaccessible page interactions on desktop and
   mobile.
4. Close data, factor, pool, strategy, backtest, Paper, monitor and review
   workflow gaps.
5. Raise automated test, performance, observability and maintainability gates.

The prioritized work queue and acceptance evidence live in
[`../todo.md`](../todo.md).

## In Scope

- All 12 protected primary workspaces and their query-addressable secondary
  tabs, Backtest detail, Paper detail and Data Processing compatibility pages.
- Data-source, trade-date, knowledge-cutoff, freshness, missing-value and
  calculation-version presentation.
- A-share price-limit, suspension, T+1, board-lot, adjusted-research-price and
  unadjusted-execution-price semantics.
- Data publication, factor evaluation, pool sealing, strategy versioning,
  backtest evidence, Paper health, monitoring and daily review workflows.
- Desktop and 390px mobile usability, accessibility, error/empty/loading states,
  API contract tests, mocked E2E and safe read-only real-backend regression.
- Bundle, lint, framework-deprecation and long-running data reliability work
  after correctness gates are green.

## Out of Scope

- Real-money broker order submission or automatic live trading.
- Production deployment, SSH or server mutation without a separate explicit
  user instruction.
- Paid/external Provider synchronization merely to make a page look populated.
- Hiding missing or stale evidence behind generated example values.

## Safety Boundaries

- Browser audit is read-only unless a test explicitly runs against isolated
  fixtures or a disposable test database.
- Missing is not zero; stale is not live; API response time is not evidence
  freshness.
- Research prices and executable prices must never be silently mixed.
- Existing user worktree changes, secrets, local databases and generated QA
  artifacts are never staged.

## Done Means

- Every item marked `done` in `docs/todo.md` has linked code/tests and current
  verification evidence.
- All protected primary and secondary pages pass desktop and mobile browser QA
  without console errors, clipped controls or dead read-only interactions.
- All key metrics expose value/null semantics, source, relevant date/cutoff and
  freshness; contradictory evidence cannot be presented as one healthy state.
- The end-to-end path data -> factor -> pool -> strategy -> backtest -> Paper ->
  watch/monitor -> review has at least one reproducible, sealed local example.
- `./scripts/check.sh` and the curated mocked/real-backend E2E gates pass after a
  clean local restart of both services.

## Verification

```bash
./scripts/check.sh
npm --prefix frontend run test:e2e:mock
```

Real-backend tests must be selected for read-only safety before execution. Any
write-flow acceptance uses isolated fixtures or a disposable database.
