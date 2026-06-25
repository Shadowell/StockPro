# AGENTS.md

## Purpose

This repository uses Codex as a delivery partner. Codex should work incrementally, keep project state in files, and avoid treating the chat history as the only source of truth.

## Files To Read First

Before substantial work, read:

1. `README.md`
2. `docs/spec.md`
3. `docs/progress.md`
4. the active contract under `docs/contracts/`

## Operating Rules

1. Work only within the current sprint contract unless explicitly told to expand scope.
2. Prefer small, reviewable changes over broad rewrites.
3. Update `docs/progress.md` after each meaningful implementation step.
4. Do not call work done without running the relevant checks, or clearly documenting what was not checked.
5. If requirements, architecture, or API contracts change, update `docs/spec.md` and the active contract in the same change.

## Standard Loop

Use this delivery loop for non-trivial tasks:

1. Read the current project state.
2. Select or create a sprint contract.
3. Implement only that slice.
4. Run verification.
5. Record QA findings if needed.
6. Update progress and next step.

## Done Criteria

A sprint is done only when:

- the agreed scope is implemented
- verification has been run or explicitly deferred
- known gaps are documented
- the repository is left in a coherent state for the next session

## Frontend Dev Server

After any frontend file modification, the Vite dev server auto-reloads. If the backend is modified, restart it manually:

```bash
kill $(lsof -ti:4445) 2>/dev/null; sleep 1
source backend/venv/bin/activate
nohup uvicorn app.main:app --reload --port 4445 > /tmp/backend.log 2>&1 &
```

Both services:
- Frontend: http://localhost:4444
- Backend: http://localhost:4445
- Admin login: `admin` / `stockpro123`

## Verification

Preferred entrypoint:

```bash
./scripts/check.sh
```

If project-specific commands exist, add them to `scripts/check.sh`.

## When To Pause

Pause and ask for confirmation when:

- the change affects security, billing, or production data
- the task requires a cross-cutting rewrite
- the current contract conflicts with the new request
- success criteria are too vague to verify
