# Sprint Contract: A-Share Research Professionalization

> Status: Superseded on 2026-07-15 by the A-share Sprint 00-07 contract set; that roadmap completed locally on 2026-07-16 and has no active successor contract.

## Sprint Name

`ashare-research-professionalization`

## Goal

Turn StockPro from a visually aligned console into a more professional A-share research workstation: every page should expose a clear research or execution purpose, show whether its data path is usable, and respect A-share-specific constraints such as T+1, 100-share lots, limit-up/down, suspension, trading sessions, concept rotation, and event catalysts.

## In Scope

- Audit every protected frontend route for usability, page errors, empty states, and A-share professional anchors.
- Keep a cross-page E2E smoke that opens all primary pages and verifies core workflow anchors.
- Enrich strategy, backtest, paper trading, monitor, market, and data pages with visible A-share guardrails.
- Define a product roadmap from market research to factor research, strategy development, backtesting, paper trading, risk monitoring, and broker dry-run.
- Create a step-by-step implementation plan for the next development tranche.
- Update `docs/progress.md` with verification evidence.

## Out of Scope

- Production deployment.
- Real broker order submission.
- Replacing all backend data contracts in one pass.
- Multi-user permissions.
- Full visual redesign beyond small professional anchors needed for usability.

## Deliverables

- New or updated page-level E2E coverage.
- Page audit document under `docs/qa/`.
- Product roadmap document under `docs/`.
- Implementation plan under `docs/superpowers/plans/`.
- Small frontend improvements that make A-share constraints visible on core workflow pages.

## Done Means

- All primary protected pages can be opened in mocked E2E without React page errors.
- Strategy, backtest, paper trading, monitor, market, and data pages visibly communicate A-share-specific constraints.
- The audit identifies which pages are usable today, which are shallow, and which need product-depth work.
- The roadmap defines an end-to-end path from data foundation to broker dry-run.
- The implementation plan is task-by-task, test-first, and points to exact files and verification commands.

## Verification

```bash
npm run check
npm run lint
npm run test:e2e:mock -- --grep "primary pages expose"
npm run test:e2e:mock
./scripts/check.sh
```

Manual or QA checks:

- Open `http://127.0.0.1:4444/` after login and click every sidebar entry.
- Confirm every primary page has a clear A-share research, strategy, data, or risk purpose.
- Confirm no core page depends on hidden-only labels to communicate business meaning.

## Risks / Notes

- Some current pages still rely on shallow mock/default data. Future work should separate fixture readiness from production data readiness.
- Real-time money flow should not be presented as tick-level truth unless the provider actually supports it.
- Broker integration remains dry-run until a separate live-trading contract is approved.

## Handoff

- Next likely step: implement roadmap Phase 1, starting with page readiness contracts, data freshness badges, and A-share constraint checks shared across strategy/backtest/paper.
