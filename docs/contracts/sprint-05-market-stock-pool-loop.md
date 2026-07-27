# Sprint 05 Contract: Market And Stock-Pool Loop

## Status

Completed on 2026-07-16. Sprint 06 and Sprint 07 subsequently completed locally.

## Sprint Name

`market-stock-pool-loop`

## Goal

Create the complete research-to-experiment handoff: consolidate market evidence into the Market L1 page, turn screeners/factors/sectors/events into reproducible stock pools, freeze pool snapshots and send them into a backtest without copying symbols or rebuilding parameters.

## Dependencies

- Sprint 01 datasets and source metadata.
- Sprint 02 published factor snapshots and factor-ranking APIs.
- Sprint 03 screener/strategy separation.
- Sprint 04 experiment API accepting `pool_snapshot_id` and optional `factor_snapshot_id`.

## Verified Current State

Verified on 2026-07-15:

- Market research is split across `/research/overview`, `/sentiment`, `/news`, `/calendar`, `/ai`, `/factors` and `/market`.
- `frontend/src/components/Navigation.tsx` exposes these as separate L1 entries.
- Existing strategy scripts mix candidate generation with strategy naming.
- No immutable stock-pool manifest connects a research decision to a later experiment.
- `ths_hot_realtime` is currently populated from `ak.stock_hot_rank_em()`; this is EastMoney popularity data and must not remain labelled as a THS ranking.

## In Scope

- Market L1 page with Structure, Sector Rotation, Sentiment/Limit, Events, Calendar and Stock workspaces.
- A dense BitPro-style `Sentiment/Limit` workspace: source/freshness header, KPI strip, breadth trend, transparent market-temperature composition, consecutive-board ladder and promotion/elimination flow, limit-up/down/broken-board lists, sector/theme evidence and date/scope comparisons.
- Stock Pools L1 page with My Pools, Screener, Factor Pools, Sector Pools, Event Pools and Snapshots.
- Stock-pool definitions, rules, members, evidence and immutable snapshots.
- Migration of one factor, one sector and one event path into pool generators.
- Route redirects from legacy research pages.
- Evidence-aware AI summaries inside Market/Stock context.
- One-click pool snapshot -> Backtest experiment handoff.

## Out of Scope

- AI autonomous trading.
- Factor calculation, storage and research diagnostics; Sprint 02 owns them.
- Paid news redistribution or full-text archive.
- Social/community collaboration.
- Paper scheduling; that starts in Sprint 06.

## Data Model

Add:

| Table | Required fields |
| --- | --- |
| `stock_pools` | `id`, `name`, `pool_type`, `description`, `status`, `created_at`, `updated_at` |
| `stock_pool_rules` | `id`, `pool_id`, `rule_type`, `rule_version`, `config`, `content_hash` |
| `stock_pool_members` | `pool_id`, `symbol`, `score`, `reason`, `evidence`, `valid_from`, `valid_until`, `source_object_type`, `source_object_id` |
| `stock_pool_snapshots` | `id`, `pool_id`, `dataset_snapshot_id`, `universe_snapshot_id`, `factor_snapshot_id`, `trade_date`, `knowledge_cutoff_at`, `manifest_hash`, `member_count`, `status`, `sealed_at` |
| `stock_pool_snapshot_members` | `snapshot_id`, `ordinal`, `symbol`, `score`, `reason`, `evidence_hash` |

Required universe filters are versioned rules evaluated against the historical universe snapshot: market/board, ST exclusion, suspension exclusion, delisting/listing status, minimum listing days, price range, liquidity and optional industry constraints. Current security metadata may not replace historical eligibility.

## Page And Route Contract

| Legacy route | Target |
| --- | --- |
| `/research/overview` | `/market?tab=structure` |
| `/sentiment` | `/market?tab=sentiment` |
| `/news` | `/market?tab=events` |
| `/calendar` | `/market?tab=calendar` |
| `/ai` | `/market?tab=stock&panel=ai` |
| `/factors` | `/factors` (retained as the Factor Research L1 page) |

Legacy URLs remain redirects for one release cycle. New page state must be linkable by query/tab and selected object ID.

## Pool Generator Contract

Each generator receives:

- Dataset snapshot ID.
- Universe snapshot ID and knowledge cutoff.
- Trade date.
- Universe filter version.
- Generator rule version and parameters.

Each candidate emits:

- Symbol and normalized score.
- Human-readable reason.
- Evidence object references and dates.
- Valid-from and valid-until.
- Generator version and input manifest hash.

Generators do not emit buy/sell orders and cannot start Paper instances.

## Market Evidence And Sentiment Contract

The page consumes only sealed Sprint 01 market-evidence snapshots or explicitly marked realtime snapshots. It never requests TuShare/AKShare in the browser or fabricates absent facts.

The header selects a trade date and market scope (`all_a`, `main_board`, `chinext`, `star`, `beijing`, `exclude_st`) and displays snapshot ID, actual source mix, permission state, captured time and stale state. Comparisons are day-over-day, 5/20 trading days and one-year percentile; an intraday snapshot is never compared with a post-close snapshot without its session label.

The KPI strip contains rise/fall/flat, limit-up, limit-down, broken-board, sealing rate, highest board, red-market ratio, rise/fall ratio, new highs and new lows. A metric exposes its definition, numerator/denominator, actual source and missing-state.

`market_temperature` is an optional versioned display metric. Its five public components are breadth, limit-up ecology, momentum continuity, loss/risk and liquidity/participation. The API returns raw component values, normalisation method, weights, formula version and missing components. If any required component is unavailable, the score is `null` with `publication_state=unavailable`; it is neither backfilled nor rendered as a 0-100 recommendation.

The ladder is 1/2/3/4/5+ boards plus highest-board detail. Promotion and elimination statistics use explicit adjacent-day cohort definitions. With 5,000 credits it is calculated from `limit_list_d.limit_times` and labelled `tushare_limit_list_derived`; an entitled `limit_step` result is separately labelled `tushare_limit_step`.

Sector/Theme panels lock a single classification system per view, show 1/5/20-day return, constituent breadth, limit-up/ladder participation, leading/lagging member, persistence and permitted money flow. `stock_hot_rank_em` is exposed as `eastmoney_popularity`; only an actual THS provider may appear as `ths_popularity`.

## API Contract

| Method | Path | Outcome |
| --- | --- | --- |
| `POST` | `/api/pools` | Create pool definition |
| `POST` | `/api/pools/{id}/generate` | Generate candidate members from explicit inputs |
| `GET` | `/api/pools/{id}/members` | List current candidates and evidence |
| `POST` | `/api/pools/{id}/snapshots` | Validate and seal a pool snapshot |
| `GET` | `/api/pool-snapshots/{id}` | Return immutable ordered manifest |
| `POST` | `/api/pool-snapshots/{id}/backtests` | Create experiment draft using the pool snapshot |
| `GET` | `/api/market/research-context` | Return source-aware evidence for Market workspaces |
| `GET` | `/api/market/evidence-snapshots` | List date/scope/session snapshots and source/permission state |
| `GET` | `/api/market/sentiment` | Return transparent raw metrics, formula version and optional market-temperature score |
| `GET` | `/api/market/limit-ecosystem` | Return limit pools, 1/2/3/4/5+ ladder and cohort promotion/elimination evidence |
| `GET` | `/api/market/sector-evidence` | Return locked-classification sector/theme evidence and actual source labels |

## Deliverables

- Additive pool migration, repositories and services.
- Market and Stock Pools L1 pages with required L2 workspaces.
- Three reference pool generators: factor, sector and event.
- Legacy route redirects and regression tests.
- Experiment handoff using `pool_snapshot_id`.
- Evidence/source/freshness UI components.
- Progress update.

## Acceptance Criteria

1. Market has exactly six defined L2 workspaces and legacy research routes redirect to them.
2. Pool members always include reason, evidence, validity and generator version.
3. A sealed pool snapshot is immutable and has a stable manifest hash.
4. Re-running the same generator inputs produces the same ordered member manifest.
5. Factor pools reference a sealed Sprint 02 factor snapshot and preserve factor/version/ranking evidence.
6. Event/news cards retain source, published time and original link; missing full text does not block headline-level research.
7. AI summaries cite stored evidence objects and distinguish fact from inference.
8. A user can create a sector pool, seal it and open a backtest draft without copying symbols.
9. All listed legacy routes remain functional redirects.
10. `./scripts/check.sh` passes.
11. Re-running a historical pool against the same snapshot cannot include a later-renamed, delisted or newly-ST symbol because the universe manifest is pinned.
12. The Market Sentiment/Limit workspace presents the defined KPI strip, ladder and sector evidence for a chosen date/scope with source, freshness and empty/restricted states.
13. The market-temperature score is reproducible from returned raw component inputs and weights; a missing component returns `null`/unavailable, not 0.
14. An EastMoney ranking cannot be rendered with a THS label, and a derived AKShare ladder cannot be rendered as a TuShare `limit_step` result.

## Testing Plan

| Layer | Coverage | Minimum additions |
| --- | --- | --- |
| Unit | historical universe filters, generator determinism, validity, hashes | 15 tests |
| Repository | pool lifecycle, member uniqueness, snapshot immutability | 7 tests |
| Integration | factor/sector/event data -> pool -> experiment draft | 4 tests |
| Frontend | L2 routing, source badges, evidence links, empty states | 6 component tests |
| E2E | research -> pool -> snapshot -> backtest draft | 2 flows |

## Verification

```bash
./scripts/check.sh
cd frontend && npm run test:e2e:mock
```

## Rollback Plan

- Preserve legacy page components until redirects and consolidated L2 workspaces pass E2E.
- New pool tables are additive and can remain read-only if generation is disabled.
- Existing static universe backtests remain readable; no completed run is rewritten.

## Risks / Notes

- AKShare news and board interfaces are upstream-web dependencies. Their failures must show stale/unavailable states, not empty valid research.
- News content rights are separate from API access. Store normalized metadata and source links by default.
- Pool ranking should never imply execution eligibility; strategy and broker rules remain separate gates.

## Handoff

- Next contract: `sprint-06-paper-watch-monitor.md`.
- Sprint 06 consumes approved strategy versions and pool snapshots without changing their manifests.

## Completion Evidence

- Added PG migrations `202607160016`-`018` for definitions, versioned rules, deterministic generations, immutable members/snapshots, experiment references and retry-safe failed generations.
- Real factor, sector and event generators produced 10, 8 and 20 ordered members. Repeating the factor input reused generation `f900bedd-a2bf-4604-936f-341f3e25f5cc` and member hash `f044b4ccdd60e1011befa89bf3413dfa8e2b1a645e44fb91ec1e201a6d153f20`.
- Sealed pool snapshots `1`-`3`; repeated sealing reused the same manifest. PG rejected direct mutation of a sealed snapshot, completed member evidence and a rule version.
- Experiment `29f03da1-f5b3-40ba-a725-c7111249e521` references pool snapshot `1`; the backtest service reads its ordered members and rejects a replacement symbol list.
- `/market` and `/pools` each expose exactly six linkable L2 workspaces. All agreed legacy research routes redirect into `/market`; `/factors` remains independent.
- Focused backend coverage passes 53 tests. Mock browser coverage passes 13/13 and the real PG/browser Market-to-Pool case passes 1/1. The full local check passes with lint warnings only.
