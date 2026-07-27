# Sprint 03 Contract: Stable Python Strategy Runtime

## Status

Completed on 2026-07-16 after local PostgreSQL, isolated-runtime, parity, quota, API and browser acceptance.

## Sprint Name

`stable-python-strategy-runtime`

## Goal

Build a stable, platform-owned strategy runtime inspired by JoinQuant's function-based Python model. A user creates or modifies a strategy by editing ordinary Python lifecycle functions only; no strategy change may require editing the framework, adding a registry entry, changing a backend route or restarting the service.

The same strategy version and ordered market-data stream must produce the same ordered order-intent stream in backtest and Paper Replay before broker-specific risk and fill handling.

## Product Reference

- [JoinQuant getting-started guide](https://www.joinquant.com/help/api/guide)
- [JoinQuant API document](https://cdn.joinquant.com/help/img/JoinQuantAPI.pdf)

StockPro follows the interaction model, not JoinQuant's internal implementation. StockPro symbols, data snapshots, A-share rules and persistence remain StockPro contracts.

## Dependencies

- Sprint 01 sealed backtest dataset snapshots.
- Sprint 02 sealed factor snapshots and point-in-time factor query contract.
- Existing `strategy_versions` table from `202606030001_strategy_workbench_core.sql`.

## Verified Current State

Verified on 2026-07-16:

- `backend/app/services/strategy_execution_service.py` executes general Python scripts as subprocesses and interprets process output.
- `backend/app/services/strategy_lab_service.py:579` attempts to load a Backtrader subclass and otherwise falls back to an internal strategy.
- Strategy execution, backtest and Paper do not share one lifecycle or one order API.
- Creating some strategy forms currently depends on implementation knowledge such as Backtrader classes or backend script behavior.

## Architecture Boundary

```text
User Python strategy
  -> StockPro Strategy API v1
  -> fixed runtime/event loop
  -> market data + clock + portfolio context
  -> normalized OrderIntent
  -> backtest/Paper broker + A-share risk rules
```

Only the first box changes when a new strategy is written. Everything below it is platform framework code.

## In Scope

- Stable `StockPro Strategy API v1` exposed to user scripts.
- Function-based lifecycle loader and scheduler.
- Dynamic strategy code stored in `strategy_versions.script_content`.
- Immutable versions, code hashing, validation and API-version pinning.
- Platform-owned context, data, history, order, scheduling, logging and record APIs.
- One runtime shared by quick backtest, full backtest and Paper Replay.
- Restricted worker execution with a package allowlist, CPU/wall-time/memory/output quotas and persisted resource-violation evidence.
- One migrated reference strategy and one minimal example strategy.
- Determinism, future-data prevention and backtest/Paper parity tests.

## Out of Scope

- User-defined framework classes or custom broker engines.
- Editing `backend/app/services/*`, routing or a strategy registry when a strategy is created.
- Arbitrary package installation.
- Direct TuShare/AKShare/database access from strategy code.
- Full portfolio accounting and performance metrics; Sprint 04 owns them.
- Realtime Paper scheduling; Sprint 06 owns it.
- Real broker adapters.

## User Strategy Contract

Required lifecycle functions:

```python
def initialize(context):
    """Called once at the start of a backtest or Paper instance."""

def handle_data(context, data):
    """Called once per configured daily/minute event."""
```

Optional lifecycle functions:

```python
def before_trading_start(context): ...
def after_trading_end(context): ...
def on_strategy_end(context): ...
```

Optional scheduled callbacks are registered during `initialize`:

```python
run_daily(callback, time="open")
run_weekly(callback, weekday=1, time="open")
run_monthly(callback, trading_day=1, time="open")
```

Minimal example:

```python
def initialize(context):
    context.security = "600519.SH"
    set_benchmark("000300.SH")
    set_option("avoid_future_data", True)

def handle_data(context, data):
    closes = history(context.security, 20, "1d", "close")
    target = 1.0 if data[context.security].close > closes.mean() else 0.0
    order_target_percent(context.security, target)
    record(ma20=float(closes.mean()))
```

## StockPro Strategy API v1

| Domain | Supported API |
| --- | --- |
| Configuration | `set_benchmark`, `set_option`, `set_order_cost`, `set_slippage` |
| Scheduling | `run_daily`, `run_weekly`, `run_monthly` |
| History | `history`, `get_price`, `get_current_data`, `get_security_info` |
| Factors | `get_factor_values`, `get_factor_snapshot_info` |
| Orders | `order`, `order_value`, `order_target`, `order_target_value`, `order_target_percent`, `cancel_order` |
| State | `context.current_dt`, `context.previous_date`, `context.portfolio`, `context.parameters`, `context.universe` |
| Output | `log.debug/info/warning/error`, `record` |

All APIs are implemented by injected safe bindings. User scripts do not import StockPro internal packages.

## Framework Invariants

- `strategy_api_version='stockpro.v1'` is pinned on every strategy version and run.
- Framework code is not copied into strategy code.
- User globals/context state must be serializable for Paper Replay and restart recovery.
- Market-data functions enforce the current simulated timestamp and cannot return future bars.
- Order APIs return platform order objects and persist normalized intents; strategy code does not emit stdout JSON.
- Unsupported API calls fail validation with stable error codes.
- An invalid script never falls back to another strategy.
- Runtime randomness is seeded and recorded when explicitly enabled.
- Every data handle exposes `trade_date`, `available_at` and the run knowledge cutoff; a strategy cannot inspect a fact that was not available at the simulated event time.
- Each order intent carries the signal timestamp and is only a request. Sprint 04 owns the earliest fill timestamp and matching semantics.
- Runtime quotas are fixed/versioned per run: wall time, CPU time, memory, open files, output bytes, log bytes and emitted intents/records.

## Forbidden Capabilities

- Network, socket or subprocess creation.
- Direct filesystem or database writes.
- Importing `backend.app`, provider services, broker services or unrestricted OS modules.
- Reading unrestricted environment variables.
- Dynamic package installation or runtime code downloads.
- Wall-clock decisions outside `context.current_dt`.
- Exceeding a resource quota, swallowing a worker failure or using an undeclared third-party dependency.

## Persistence Changes

Extend `strategy_versions` with:

- `content_hash TEXT NOT NULL`
- `strategy_api_version TEXT NOT NULL DEFAULT 'stockpro.v1'`
- `validation_status TEXT NOT NULL`
- `validation_report JSONB NOT NULL DEFAULT '{}'`
- `validated_at TIMESTAMPTZ`
- `parent_version_id UUID NULL REFERENCES strategy_versions(id)`
- `dependency_manifest JSONB NOT NULL DEFAULT '{}'`
- `runtime_limits JSONB NOT NULL`

Add:

- `strategy_validation_runs`
- `strategy_replay_runs`
- `strategy_replay_intents`
- `strategy_custom_records`
- `strategy_runtime_failures`

Each intent and custom record stores event ordinal, simulated timestamp, data-availability cutoff and deterministic payload hash. Runtime failures store limit type, observed usage, worker exit state and sanitized diagnostic output.

## API Contract

| Method | Path | Outcome |
| --- | --- | --- |
| `POST` | `/api/strategy` | Create strategy and first Python draft version |
| `POST` | `/api/strategy/{strategy_id}/versions` | Create immutable child version from Python code |
| `POST` | `/api/strategy/versions/{version_id}/validate` | Validate lifecycle, imports and API calls |
| `GET` | `/api/strategy/versions/{version_id}` | Return code, API version and validation report |
| `POST` | `/api/strategy/versions/{version_id}/quick-run` | Short deterministic behavior check |
| `POST` | `/api/strategy/versions/{version_id}/replay` | Replay explicit snapshot/range through the shared runtime |
| `GET` | `/api/strategy/replays/{run_id}/intents` | Return ordered normalized order intents |

Legacy execute/backtest/Paper endpoints become wrappers only after they call this runtime. They cannot keep independent strategy-loading semantics.

## Deliverables

- Platform-owned strategy runtime and safe API bindings.
- Lifecycle/scheduler loader.
- Additive migration and repository methods.
- Validation service with future-data and forbidden-capability checks.
- Isolated worker limits, package manifest validation and resource-failure persistence.
- Dynamic DB strategy create/version/validate APIs.
- Minimal example and migrated reference strategy.
- Strategy editor integration required to save and quick-run plain Python code.
- Determinism and parity tests.
- Documentation for Strategy API v1 available from the editor.

## Acceptance Criteria

1. A new strategy is created by saving one Python script containing `initialize` and `handle_data`; no framework file changes occur.
2. Updating a strategy creates a new immutable `strategy_versions` row and requires no process restart.
3. No new strategy requires a registry edit, new backend route or Backtrader subclass.
4. All supported Strategy API calls work through injected bindings and are version-pinned.
5. Invalid imports, future-data requests, database/network access and missing lifecycle functions fail validation with stable issue codes.
6. The same code, API version, parameters, dataset/factor snapshots and event order produce identical intent and `record` hashes across two runs.
7. Backtest replay and Paper Replay produce identical ordered intents before broker processing.
8. An invalid script never runs `RegisteredMomentumStrategy` or any fallback strategy.
9. Existing saved strategies remain readable and have an explicit migration status.
10. `./scripts/check.sh` passes.
11. A deliberately non-terminating, memory-over-limit or output-flooding script is stopped within the configured limit, emits one auditable failed replay and never blocks another run.
12. An order emitted from a daily close event contains its signal/data-availability timestamps and does not imply same-bar execution.

## Testing Plan

| Layer | Coverage | Minimum additions |
| --- | --- | --- |
| Unit | lifecycle discovery, scheduler, API bindings, dependency/limit validation | 20 tests |
| Runtime | deterministic clock, availability cutoff, serialization, quota and worker errors | 16 tests |
| Repository/API | versions, API pinning, validation and quick runs | 7 tests |
| Parity | backtest versus Paper Replay intents and records | 4 fixtures |
| E2E | write Python -> validate -> quick-run -> inspect records | 1 mocked + 1 real-backend flow |

## Verification

```bash
./scripts/check.sh
python3 -m unittest discover -s backend/tests
cd frontend && npm run test:e2e:mock
```

## Completion Evidence

- Added immutable Strategy API v1 versions, validation runs, replay runs, timestamped intents, custom records and auditable runtime failures through additive PostgreSQL migrations.
- Added the isolated lifecycle worker and one shared deterministic replay path for `quick`, `backtest` and `paper_replay`; identical inputs produce identical ordered intent and record hashes.
- Validation rejects missing/invalid lifecycle functions, imports, filesystem/network/database access, unsupported APIs, dunder introspection, explicit-date data reads and wall-clock class methods with stable issue codes.
- Runtime limits cannot be expanded by a replay request. Wall time, CPU, memory, open files, output, log, intent and record limits are versioned, and quota failures are persisted without blocking the next run.
- Factor values remain hidden until their sealed snapshot knowledge cutoff and are then forward-filled point-in-time; the worker never calls a provider or database.
- The existing strategy UI now saves immutable plain-Python versions, validates them and quick-runs them against explicit sealed dataset/factor snapshots. A migrated Strategy API v1 reference strategy is installed idempotently for existing local databases.
- Local verification passed with 27 focused Strategy runtime tests, 78 total backend tests, frontend build/lint, 11 mocked browser flows and 7 real-backend/browser flows. Real PostgreSQL probes also confirmed immutable-version rejection, backtest/Paper hash parity and wall-time/memory failure persistence.

## Rollback Plan

- Keep legacy strategy records readable while the new runtime is feature-flagged.
- New version/validation/replay tables are additive and remain audit records.
- Disable the new runtime feature flag if needed; do not silently label legacy runs as Strategy API v1 runs.
- Never require users to move strategy code into backend source files during rollback.

## Risks / Notes

- Python is not perfectly sandboxable. The runtime must combine AST validation, restricted imports, injected builtins, resource limits and process isolation.
- API stability is a product contract. Incompatible changes require `stockpro.v2`, not silent changes to v1.
- JoinQuant compatibility is conceptual; exact API parity is not a requirement unless explicitly added later.

## Handoff

- Next contract: `sprint-04-joinquant-backtest-workbench.md`.
- Sprint 04 starts only after a plain Python strategy runs unchanged through quick backtest, full replay and Paper Replay.
