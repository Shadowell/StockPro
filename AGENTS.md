# AGENTS.md

## Purpose

This repository uses Codex as a delivery partner. Codex should work incrementally, keep project state in files, and avoid treating the chat history as the only source of truth.

## Files To Read First

Before substantial work, read:

1. `README.md`
2. `docs/spec.md`
3. `docs/progress.md`
4. the current contract pointed to by `docs/contracts/active.md`

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

## Session Branch Rule

At the start of every new Codex session, recreate the working branch from the
latest `main`:

1. Fetch or pull the latest `main` from `origin`.
2. Create a fresh `codex/*` branch from `main` before making changes.
3. Do not continue work on an old session branch unless the user explicitly
   requests it.

## GitHub Delivery Rule

After each completed user-requested change set that modifies code, configuration,
scripts, tests, or deployment files:

1. Run the relevant verification. Documentation-only changes require at least `git diff --check`.
2. Review `git status` and the scoped diff before staging.
3. Stage only files and hunks changed for the current task. Never sweep in unrelated pre-existing worktree changes.
4. Create one clear, conventional commit for the completed change set on a temporary `codex/*` branch.
5. Push that branch to `origin`, merge it into `main` only after the checks pass, and push `main` to `origin`.
6. Treat the `main` push as the deployment trigger. Wait for the corresponding GitHub Actions deployment run and verify its result, the deployed SHA, service health, and the key smoke test before reporting completion.
7. Report the feature-branch commit, merge commit, `main` SHA, GitHub Actions run, and deployment verification in the final response.

Safety rules:

- Do not commit or push when required checks fail unless the user explicitly asks to preserve a failing checkpoint.
- Do not merge or deploy when the worktree contains unrelated or unreviewed changes; isolate the current change set first.
- Never commit secrets, `.env` files, credentials, private keys, local runtime configuration, browser artifacts, generated output, or database files.
- Never amend an existing commit, force-push, rewrite history, or bypass branch protection solely to make an automatic merge or deployment succeed.
- If authentication, branch protection, a non-fast-forward update, or another remote error blocks the push, stop and report it; do not bypass the protection.
- Do not deploy directly with ad-hoc SSH, `scp`, `rsync`, or remote shell commands when the GitHub Actions deployment path is available; use the workflow triggered by the `main` push.

## GitHub Actions Deployment Boundary

- Production deployment is performed only by the existing GitHub Actions workflow after a verified `main` push. The workflow owns remote synchronization, dependency installation, migrations, service restart, health checks, and deployment-SHA recording.
- After source-code changes, still start or restart the local frontend, backend, and required local dependencies before verification; local verification does not replace the GitHub Actions deployment verification.
- Keep the local development URLs at `http://localhost:4444` and `http://localhost:4445`.
- If the GitHub Actions run fails, is blocked, or cannot prove the deployed SHA and health checks, stop and report the failure; do not manually patch the server as a fallback.

## Current Deployment Restriction

- 当前阶段不在 `stockpro` 服务器或生产环境部署；只保证本地部署、前后端重启和本地验证。
- 原因是服务器环境中的 AKShare 数据链路当前无法调通或尚未验证，服务器端 Provider 结果不能作为本地功能完成的前置条件。
- 在用户明确解除本限制并确认 AKShare 已恢复前，不得推送会触发生产部署的 `main`、运行服务器端部署/重启或执行生产数据同步；服务器状态与本地验证必须分开报告。

## Done Criteria

A sprint is done only when:

- the agreed scope is implemented
- verification has been run or explicitly deferred
- known gaps are documented
- the repository is left in a coherent state for the next session

## Local Service Restart Rule

After every code, configuration, script, or test change, restart both the frontend and backend services before verification. This restart is mandatory after each completed modification, even when Vite hot reload or Uvicorn reload appears to have applied the change; hot reload does not replace the required clean restart.

Documentation-only changes do not require a service restart.

Restart the backend with the virtual environment's Python module entrypoint
and the local isolation database URL. Never inherit a server `DATABASE_URL`:

```bash
kill $(lsof -ti:4445) 2>/dev/null; sleep 1
export DATABASE_URL="$(./scripts/local_database.sh --print-url)"
source backend/venv/bin/activate
cd backend
nohup env DATABASE_URL="$DATABASE_URL" python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 4445 > /tmp/backend.log 2>&1 &
```

Restart the frontend after returning to the repository root; proxy only the
local backend:

```bash
kill $(lsof -ti:4444) 2>/dev/null; sleep 1
cd frontend
nohup env VITE_DEV_API_PROXY_TARGET=http://127.0.0.1:4445 npm run dev -- --host 127.0.0.1 --port 4444 > /tmp/frontend.log 2>&1 &
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
export DATABASE_URL="$(./scripts/setup_isolation_db.sh --print-url)"
./scripts/check.sh
```

`DATABASE_URL` must point at the isolated `stockpro_bitpro_rebase_dev` database;
`check.sh` refuses anything else. If project-specific commands exist, add them
to `scripts/check.sh`.

## When To Pause

Pause and ask for confirmation when:

- the change affects security, billing, or production data
- the task requires a cross-cutting rewrite
- the current contract conflicts with the new request
- success criteria are too vague to verify
