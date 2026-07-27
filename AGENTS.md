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

## GitHub Delivery Rule

After each completed user-requested change set that modifies repository files:

1. Run the relevant verification. Documentation-only changes require at least `git diff --check`.
2. Review `git status` and the scoped diff before staging.
3. Stage only files and hunks changed for the current task. Never sweep in unrelated pre-existing worktree changes.
4. Create one clear, conventional commit for the completed change set.
5. Push the checked-out branch to `origin`. If it has no upstream, use `git push -u origin <current-branch>`.
6. Report the commit hash and pushed branch in the final response.

Safety rules:

- Do not commit or push when required checks fail unless the user explicitly asks to preserve a failing checkpoint.
- Never commit secrets, `.env` files, credentials, private keys, local runtime configuration, browser artifacts, generated output, or database files.
- Never amend an existing commit, force-push, rewrite history, or switch branches solely to make an automatic push succeed.
- If authentication, branch protection, a non-fast-forward update, or another remote error blocks the push, stop and report it; do not bypass the protection.
- Pushing source code to GitHub is delivery, not deployment.

## Local-only Deployment Boundary

- Do not automatically deploy, SSH, `scp`, `rsync`, run production deployment scripts, restart remote services, or mutate server data.
- After source-code changes, start or restart only the local frontend, backend, and required local dependencies.
- Keep the local development URLs at `http://localhost:4444` and `http://localhost:4445`.
- Server deployment requires a new explicit instruction from the user in the current conversation.

## Done Criteria

A sprint is done only when:

- the agreed scope is implemented
- verification has been run or explicitly deferred
- known gaps are documented
- the repository is left in a coherent state for the next session

## Local Service Restart Rule

After every source-code change, restart both the frontend and backend services before verification. Do this even when Vite hot reload or Uvicorn reload appears to have applied the change; hot reload does not replace the required clean restart.

Documentation-only changes do not require a service restart.

Restart the backend with the virtual environment's Python module entrypoint:

```bash
kill $(lsof -ti:4445) 2>/dev/null; sleep 1
source backend/venv/bin/activate
cd backend
nohup python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 4445 > /tmp/backend.log 2>&1 &
```

Restart the frontend after returning to the repository root:

```bash
kill $(lsof -ti:4444) 2>/dev/null; sleep 1
cd frontend
nohup npm run dev -- --host 127.0.0.1 --port 4444 > /tmp/frontend.log 2>&1 &
```

After each restart, verify both ports are listening and call the backend health endpoint. Do not report a code change complete while either service is unavailable.

Both services:
- Frontend: http://localhost:4444
- Backend: http://localhost:4445
- Admin login: `admin` / `stockpro123`

## 前端设计

所有交易、监控、数据后台类页面必须先读取并遵循
`~/.codex/skills/financial-operator-ui/SKILL.md`。

优先使用 `@bitpro/ui` 组件和主题令牌，禁止复制 BitPro 业务页面代码。

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
