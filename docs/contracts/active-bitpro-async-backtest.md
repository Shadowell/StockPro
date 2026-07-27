# Sprint Contract: BitPro-parity Asynchronous Backtest Jobs

> Status: Completed on 2026-07-27.

## Goal

Replace blocking browser-owned backtest execution with PostgreSQL-owned jobs that
remain observable through status, progress and logs, and can be cancelled or
retried under the authenticated role and quota boundary.

## In Scope

- Add PostgreSQL backtest job and job-log records.
- Create quick/full jobs that return immediately with a stable job ID.
- Run jobs in a bounded local worker with phase and progress checkpoints.
- Persist owner role, session, guest invitation, request payload and result run ID.
- Allow administrators to inspect all jobs and guests to inspect only their jobs.
- Add cooperative cancellation and retry as a new attempt.
- Mark in-flight jobs interrupted after a backend process restart.
- Bind guest daily, concurrent and date-range quotas to job lifecycle.
- Add a frontend task console with polling, progress, logs, cancel, retry and
  result navigation.

## Out of Scope

- Distributed workers, Redis, Celery or remote deployment.
- Resuming from an exact processed market bar.
- Parameter-matrix jobs.
- Real-broker execution.

## Contract

1. `POST /api/backtest/jobs` returns `202` and a persisted job before execution.
2. Job status is one of `pending`, `running`, `cancelling`, `cancelled`,
   `success`, `failed` or `interrupted`.
3. Every transition is persisted with an append-only job log.
4. Cancellation is cooperative until the immutable result is sealed; a stop
   request arriving after that commit point cannot relabel successful evidence.
5. Retry creates a new job linked through `parent_job_id`; prior evidence is kept.
6. Guest quota is reserved with the job and released from concurrent usage only
   on a terminal transition.
7. A successful job links to the immutable `backtest_runs` result.

## Done Means

- Migration, service and API tests pass.
- Job creation returns before the engine result and polling reaches a terminal state.
- Failure, cancellation, retry and restart interruption are testable.
- Frontend shows task progress and truthful terminal states.
- Existing synchronous routes remain compatible during migration.
- Both services restart and the repository check passes.
