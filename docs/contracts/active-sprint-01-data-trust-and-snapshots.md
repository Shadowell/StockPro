# Sprint 01 Contract: Data Trust And Snapshots

## Status

Completed locally on 2026-07-16. The accepted research baseline is dataset snapshot 8 (20 symbols, 9,700 two-year daily bars and nine reference datasets); the managed daily acceptance run is job 40 / snapshot 7.

## Sprint Name

`data-trust-and-snapshots`

## Goal

Create a source-aware, point-in-time, quality-gated and immutable daily-data foundation used by factor calculation, backtesting and later post-close market research. At sprint completion, a reference dataset with normal, ST, suspended and delisted securities can be synchronized from TuShare with explicit AKShare fallback, validated, frozen with a knowledge cutoff and consumed without any external call during factor calculation or backtesting. The sprint also publishes separately versioned market-evidence snapshots; Sprint 05 owns their page presentation and composite interpretation.

## Dependencies

- Sprint 00 completed.
- Postgres is the only platform database.
- Existing TuShare token and current provider configuration remain external secrets.

## Verified Current State

Verified on 2026-07-15:

| Area | Existing behavior | Gap |
| --- | --- | --- |
| Provider | `backend/app/services/tushare_provider.py:303` falls back from TuShare to AKShare | Fallback reason is logged but not persisted with a dataset batch |
| Sync jobs | `backend/app/db/postgres_db.py:860` persists sync job and item progress; `scheduler_service.py` already uses APScheduler | Schedules/config are not fully PG-backed and jobs do not publish one normalized immutable daily snapshot |
| Historical data | Postgres stores K-line rows with `source` | No partition manifest, hash, quality result or snapshot membership |
| Page mapping | `backend/app/services/database_data_service.py:35` converts missing values to numeric zero | Missing source facts can appear as valid values |
| Backtest | Backtest services can load/fetch historical data directly | Experiment input is not bound to a frozen dataset snapshot |

## In Scope

- Dataset registry limited to security master/history, trading calendar, unadjusted daily bars, adjustment factors, corporate actions, daily valuation/turnover, suspension, daily price-limit data, historical industry/benchmark constituents and benchmark index bars.
- Source-fetch run records with requested provider, actual provider, fallback reason, timestamps, schema version and response hash.
- Normalized dataset partitions keyed by dataset, trade-date range and symbol range.
- Point-in-time availability rules: every normalized fact has `trade_date`, `available_at` and source collection time; every sealed snapshot has `knowledge_cutoff_at`.
- Versioned historical security/universe evidence for listing, name/code mapping, ST, suspension, delisting, industry classification and benchmark membership.
- Corporate-action facts and reconciliation checks for cash dividends, rights issues, splits/consolidations and adjustment factors.
- Provider entitlement metadata for permitted endpoints, cache/export scope, rate/permission state and contract version; no secret value is persisted.
- A TuShare 5,000-credit endpoint catalogue and capability probe. The catalogue groups admitted A-share research endpoints as Reference & Calendar, Price & Valuation, Corporate Actions & Financial Disclosure, Index & Industry, Capital Flow & Dragon-Tiger, Limit-up Ecology, Fund/ETF & Convertible Bond, Macro & Cross-market Context, and Research Events. It records the required-credit/independent-authorisation contract, actual permission state, supported fields and rate limit.
- Post-close market-evidence snapshots for breadth, limit-up/down/broken-board membership, a `limit_list_d.limit_times`-derived consecutive-board ladder, KPL short-line ranks, sector evidence and heat rankings. Intraday evidence, if later enabled, is a separate snapshot type and cannot overwrite post-close facts.
- Deterministic quality checks and blocking/non-blocking issue severity.
- Immutable dataset snapshots and snapshot item manifests.
- Snapshot APIs and a backtest-data maintenance page for coverage, sync runs, quality and snapshots.
- Remove hard-coded zero substitution from the selected research-data path.
- Prevent factor/backtest input paths from calling TuShare or AKShare.

## Out of Scope

- Minute-level whole-market history.
- Financial statement normalization beyond the disclosure/availability contract needed to block future use.
- Realtime quotes, news and announcements, plus the Market L1 presentation/UI, its composite market-temperature formula, stock-pool generation and route migration. Sprint 05 owns those behaviors.
- A general-purpose data warehouse or SQL workbench redesign.
- Stock-pool snapshots.
- Factor definitions, calculations and diagnostics; Sprint 02 owns them.
- Unified strategy runtime.
- Backtest execution redesign.
- Frontend navigation consolidation beyond Data page additions required to inspect this sprint.

## Data Model

Add one migration under `backend/postgres/migrations/` with these tables:

| Table | Required key/fields |
| --- | --- |
| `dataset_definitions` | `id`, unique `code`, `name`, `primary_source`, `fallback_source`, `schema_version`, `quality_policy`, `enabled` |
| `source_fetch_runs` | `id`, `dataset_id`, `requested_source`, `actual_source`, `fallback_reason`, `request_params`, `started_at`, `finished_at`, `status`, `row_count`, `response_hash`, `error_message` |
| `dataset_partitions` | `id`, `dataset_id`, `fetch_run_id`, `partition_key`, `start_date`, `end_date`, `symbol_count`, `row_count`, `content_hash`, `status`, `created_at` |
| `data_quality_issues` | `id`, `partition_id`, `check_code`, `severity`, `record_key`, `message`, `details`, `created_at` |
| `dataset_snapshots` | `id`, unique `name`, `status`, `manifest_hash`, `created_at`, `sealed_at` |
| `dataset_snapshot_items` | `snapshot_id`, `partition_id`, `dataset_code`, `content_hash`; unique pair `(snapshot_id, partition_id)` |
| `dataset_sync_schedules` | `id`, `code`, `cron`, `timezone`, `enabled`, `catchup_days`, `max_retries`, `updated_at` |
| `dataset_orchestration_runs` | `schedule_code`, `trade_date`, unique pair, `status`, requested symbols, attempt count, K-line job, sealed snapshot and market-evidence links, result/error/timestamps |
| `dataset_watermarks` | `dataset_id`, `last_published_trade_date`, `last_fetch_run_id`, `updated_at` |
| `security_status_history` | `symbol`, `effective_from`, `effective_to`, `listing_status`, `is_st`, `suspension_status`, `name`, `source_fetch_run_id` |
| `security_alias_history` | `symbol`, `alias`, `alias_type`, `effective_from`, `effective_to`, `source_fetch_run_id` |
| `corporate_actions` | `symbol`, `action_type`, `ex_date`, `announcement_available_at`, `cash_per_share`, `share_ratio`, `source_fetch_run_id` |
| `universe_definitions` | `id`, `code`, `rule_version`, `description`, `enabled` |
| `universe_snapshots` | `id`, `definition_id`, `trade_date`, `knowledge_cutoff_at`, `manifest_hash`, `status`, `sealed_at` |
| `universe_snapshot_members` | `snapshot_id`, `symbol`, `industry_code`, `benchmark_weight`, `eligibility_flags` |
| `source_entitlements` | `dataset_code`, `source`, `permission_state`, `cache_policy`, `export_policy`, `contract_version`, `checked_at` |
| `tushare_endpoint_catalog` | `endpoint_code`, `module_code`, `required_credits`, `requires_independent_authorisation`, `schedule_kind`, `storage_dataset`, `enabled`, `contract_url`, `updated_at` |
| `tushare_endpoint_probes` | `id`, `endpoint_code`, `checked_at`, `permission_state`, `supported_fields`, `rate_limit`, `error_code`, `error_message`, `response_hash` |
| `market_evidence_snapshots` | `id`, `trade_date`, `snapshot_type` (`post_close`/`intraday`), `market_scope`, `captured_at`, `available_at`, `source_map`, `status`, `content_hash` |
| `market_evidence_metrics` | `snapshot_id`, `metric_code`, `value`, `unit`, `definition_version`, `source_fetch_run_id`; unique `(snapshot_id, metric_code)` |
| `limit_pool_members` | `snapshot_id`, `pool_kind` (`up`/`down`/`broken`), `symbol`, `limit_times`, `first_limit_at`, `last_limit_at`, `open_times`, `seal_amount`, `turnover`, `industry`, `source_fetch_run_id` |
| `short_line_rank_rows` | `snapshot_id`, `ranking_kind`, `rank`, `symbol`, `theme`, `status`, `source_fetch_run_id` |
| `sector_evidence_rows` | `snapshot_id`, `classification_system`, `sector_code`, `sector_name`, `return_1d`, `breadth`, `limit_up_count`, `leader_symbol`, `net_flow`, `source_fetch_run_id` |
| `heat_ranking_rows` | `snapshot_id`, `ranking_provider`, `ranking_kind`, `rank`, `symbol`, `score`, `source_fetch_run_id`; unique `(snapshot_id, ranking_provider, ranking_kind, rank)` |

`dataset_partitions` include `available_at` and `knowledge_cutoff_at`; `dataset_snapshots` include `knowledge_cutoff_at`. Snapshot rows are append-only after `status='sealed'`. A sealed snapshot cannot add, remove or replace partitions.

## Normalization Contract

- Symbol: TuShare format such as `600519.SH`, `000001.SZ`, `430047.BJ`.
- Daily date: SQL `DATE` using exchange trade date.
- Availability: `available_at` is the earliest Shanghai timestamp the platform can use a fact; it may be later than `trade_date` and is required for financial, corporate-action and revised data.
- Knowledge cutoff: a run only sees records where `available_at <= knowledge_cutoff_at`; revision arrival never rewrites what an earlier sealed snapshot knew.
- Timestamp: `TIMESTAMPTZ`, normalized to Asia/Shanghai at application boundaries.
- Volume: normalized to shares; raw unit recorded in fetch metadata.
- Amount: normalized to CNY yuan.
- Missing value: SQL `NULL`; never numeric zero unless the upstream fact is actually zero.
- Each normalized row must be traceable to `source_fetch_run_id`.
- Historical security, industry and benchmark membership are effective-dated; a current `stock_basic` row cannot be substituted for its historical state.

## API Contract

Add or extend endpoints under the existing unversioned `/api` convention:

| Method | Path | Outcome |
| --- | --- | --- |
| `GET` | `/api/data/datasets` | List definitions, coverage, latest partition and quality state |
| `POST` | `/api/data/sync-jobs` | Create an idempotent dataset sync job |
| `GET` | `/api/data/sync-jobs/{job_id}` | Return item progress and source/fallback metadata |
| `GET` | `/api/data/schedules/daily` | Return persisted schedule, watermarks and next run |
| `PUT` | `/api/data/schedules/daily` | Update local daily schedule and retry/catch-up policy |
| `POST` | `/api/data/schedules/daily/run` | Trigger the same idempotent orchestration manually |
| `GET` | `/api/data/quality/issues` | Filter issues by dataset, partition and severity |
| `GET` | `/api/data/universe-snapshots/{snapshot_id}` | Return immutable historical eligibility/industry/benchmark manifest |
| `GET` | `/api/data/source-entitlements` | Return configured source permission/cache/export status without secrets |
| `POST` | `/api/data/snapshots` | Create a draft snapshot from explicit partitions |
| `POST` | `/api/data/snapshots/{snapshot_id}/seal` | Validate and seal the manifest |
| `GET` | `/api/data/snapshots/{snapshot_id}` | Return immutable manifest and hashes |

Repeated sync submission with the same dataset, date range, symbol set and schema version must return the existing queued/running job instead of creating a duplicate.

## Daily Incremental Sync Contract

Reuse the existing `AsyncIOScheduler`; do not introduce a second scheduler. The default local schedule is `17:30 Asia/Shanghai` on weekdays, but the job first checks the persisted TuShare trading calendar and exits as `not_trading_day` when the date is closed. Schedule configuration, watermark and run state live in PostgreSQL, not process memory or a local JSON file.

For each open trading date, one orchestrated run executes in dependency order:

1. Acquire a PostgreSQL advisory lock for `daily_market_sync + trade_date`; a second backend process exits without duplicating work.
2. Refresh security/calendar/universe history only when due, then fetch `daily`, `adj_factor`, corporate-action changes, `daily_basic`, `suspend_d`, `stk_limit` and benchmark `index_daily` for that trade date.
3. Write provider responses to unsealed source/partition records. TuShare is primary; an allowed AKShare fallback applies to the whole dataset/date item and records `fallback_reason`.
4. Normalize symbols, units and dates, then run duplicate, OHLC, calendar, coverage, adjustment-factor and price-limit checks.
5. Atomically mark all required partitions published only when blocking checks pass. Partial successful items remain inspectable but cannot become a usable snapshot.
6. Create and seal a new dataset/universe snapshot containing the new date plus prior published partitions; record one `knowledge_cutoff_at` and update each dataset watermark in the same publication transaction.
7. Emit a persisted `dataset_snapshot.sealed` event. Sprint 02 consumes that event to queue factor calculations; factor calculation never starts from an unsealed or partial day.
8. After the daily reference datasets seal, run entitled post-close market-evidence collection. Each category is one actual provider per snapshot: TuShare is preferred; an AKShare fallback is explicit and category-wide. A restricted or schema-incompatible endpoint creates a visible `restricted`/`failed` evidence state, never a zero metric or silently substituted provider.

The sync is incremental by `trade_date`, not a daily full-history pull. The initial 17:30 attempt is a collection attempt, not an assertion that every source has finalized. A required dataset still unavailable after its configured grace window leaves the day unpublished and blocks factor/backtest use. Every run also reconciles the most recent five trading days to catch provider corrections. Corrections create new partitions and a new snapshot; they do not mutate a sealed historical snapshot.

Retry policy is 3 attempts with configurable backoff (default 5/15/45 minutes). Startup recovery scans queued/running/failed trading dates since the watermark and resumes safely. The idempotency key is `dataset_code + trade_date + schema_version + requested_source`; retries cannot create duplicate published partitions.

## Quality Gates

Blocking checks:

- Duplicate `(symbol, trade_date)` rows.
- `high < max(open, close, low)` or `low > min(open, close, high)`.
- Negative price, volume or amount.
- Missing daily bar inside an open trading day unless a suspension record explains it.
- Missing adjustment factor for a date required by an adjusted-price experiment.
- Missing or inconsistent corporate action that prevents adjusted signal prices, unadjusted executable prices, position quantity and cash from reconciling.
- Missing historical security/universe eligibility for an included symbol, or a fact whose `available_at` exceeds snapshot `knowledge_cutoff_at`.
- Restricted/unknown source entitlement for a dataset requested for a publishable snapshot.
- Unknown exchange suffix or invalid symbol format.
- Partition hash mismatch after persistence.

Non-blocking checks:

- Source-to-source field differences beyond configured tolerances.
- Optional valuation or amount field missing.
- AKShare fallback used successfully.
- A later provider revision that is recorded as a separate correction snapshot.
- An optional market-evidence category is restricted, stale or unavailable; no composite market-temperature metric is calculated in this sprint.

## Deliverables

- Postgres migration and repository methods.
- Dataset registry and normalization service.
- Quality-check service with deterministic issue codes.
- Snapshot service and API endpoints.
- PG-backed daily schedule, trade-calendar gate, per-date run ledger, advisory-lock orchestration and a Data-page inspection panel.
- Point-in-time security/universe/corporate-action normalization and availability checks.
- Source entitlement registry and visible restricted-state handling.
- TuShare 5,000-credit endpoint catalogue/probes plus module-specific schedule definitions.
- Immutable post-close market-evidence snapshots and raw limit-pool/KPL/sector/heat rows with actual-provider labels.
- Data page sections needed to inspect datasets, runs, issues and manifests.
- Unit, integration and API tests.
- Updated `scripts/check.sh` if new test commands are required.
- Updated `docs/progress.md` after each meaningful slice.

## Acceptance Criteria

1. A reference universe with at least 20 symbols and two years of daily bars synchronizes into normalized Postgres datasets, including fixtures for ST, suspension, delisting and a corporate action.
2. Every partition exposes actual source, collection time, schema version, row count and content hash.
3. A TuShare failure either records an allowed AKShare fallback or fails the job; no silent mixed-source partition is produced.
4. Injected duplicate, illegal OHLC and unexplained missing-trading-day fixtures block snapshot sealing.
5. A sealed snapshot returns the same manifest hash after service restart.
6. Attempts to mutate a sealed snapshot return HTTP 409.
7. Reference factor/backtest loaders read by `dataset_snapshot_id` and perform zero provider calls; research display pages outside Data/Factors/Backtest do not depend on these tables in this sprint.
8. Missing numeric facts remain `null` through API serialization.
9. Existing cached market pages continue to load.
10. `./scripts/check.sh` passes.
11. Two concurrent daily triggers publish one snapshot because the PG advisory lock and idempotency constraints reject duplicate work.
12. A failed required dataset prevents snapshot sealing and factor triggering; retry recovery later publishes one complete snapshot.
13. A provider correction inside the five-day reconciliation window creates a new partition/snapshot without changing the old manifest hash.
14. A factor/backtest request at historical cutoff T cannot read a financial/corporate-action/security-status fact with `available_at > T`, even if the current database holds it.
15. Snapshot sealing fails when a corporate-action reconciliation, historical-universe eligibility or entitlement check fails.
16. The endpoint probe records `limit_step`, `limit_cpt_list` and `dc_hot` as 8,000-credit restricted and `ths_hot`/THS money-flow as 6,000-credit restricted when the configured account is at 5,000 credits; none is represented as empty data.
17. `limit_list_d` publishes U/D/Z categories and a 1/2/3/4/5+ ladder derived from `limit_times`; source metadata labels the ladder `tushare_limit_list_derived`.
18. The same post-close market-evidence snapshot never labels `stock_hot_rank_em` as a THS ranking, and no intraday row can overwrite its post-close row.

## Testing Plan

| Layer | Coverage | Minimum additions |
| --- | --- | --- |
| Unit | symbol/unit/availability normalization, hashes, corporate-action/universe checks, sealed-state guards | 18 tests |
| Repository | migrations, unique constraints, manifests, history, advisory locks, watermarks and idempotent jobs | 13 tests |
| API | create job, inspect failure, create/seal/read snapshot, mutation conflict | 6 tests |
| Integration | TuShare success, explicit AKShare fallback, both providers fail, retry/catch-up, correction snapshots and sealed-event handoff | 8 tests |
| E2E | Data page shows source, freshness, blocking issue and sealed snapshot | 1 mocked + 1 real-backend flow |

## Verification

```bash
./scripts/check.sh
python3 -m unittest discover -s backend/tests
cd frontend && npm run test:e2e:mock
```

Manual acceptance:

- Synchronize the reference universe.
- Verify that a historical cutoff excludes a deliberately late disclosure/revision and includes the same fact only in the later snapshot.
- Open Data -> Quality and inspect a deliberately failed partition.
- Fix/re-run the partition, create a snapshot and seal it.
- Restart the backend and confirm manifest ID, rows and hash are unchanged.

## Rollback Plan

- Keep current K-line tables readable during the sprint; new snapshot tables are additive.
- Roll back application code first so old reads continue.
- Drop new tables only in a dedicated rollback migration after confirming no experiment references them.
- Never rewrite or delete an already sealed manifest during rollback; mark it unavailable instead.

## Risks / Notes

- TuShare permissions vary by account. Restricted endpoints must be represented as `restricted`, not `empty-success`.
- AKShare upstream response shapes can change. Normalization contract tests must fail loudly.
- Hashing must use canonical ordering and serialization or snapshots will not be reproducible.
- Existing provider fallback logs are not sufficient audit evidence.

## Handoff

- Next contract: `sprint-02-factor-store-and-daily-research.md`.
- Sprint 02 may start only after sealed snapshot reads work through an API/repository boundary.
