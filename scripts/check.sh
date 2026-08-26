#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="$ROOT_DIR/backend/venv/bin/python"
SETUP_CMD="./scripts/setup_isolation_db.sh"
ISOLATION_DB="stockpro_bitpro_rebase_dev"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python3"
fi

echo "[check] repository root: $ROOT_DIR"

isolation_setup_hint() {
  echo "[check] Isolation database '${ISOLATION_DB}' is required for this golden path." >&2
  echo "[check] Create it with one command:" >&2
  echo "[check]   ${SETUP_CMD}" >&2
  echo "[check] Then:" >&2
  echo "[check]   export DATABASE_URL=\"\$(${SETUP_CMD} --print-url)\"" >&2
  echo "[check]   ${SETUP_CMD} --migrate" >&2
  echo "[check] Docs: docs/deployment.md#isolation-database" >&2
}

load_database_url_from_env_file() {
  if [ "${STOCKPRO_CHECK_SKIP_ENV_FILE:-0}" = "1" ]; then
    return 0
  fi
  local env_file="$ROOT_DIR/backend/.env"
  if [ -n "${DATABASE_URL:-}" ] || [ ! -f "$env_file" ]; then
    return 0
  fi
  local loaded
  loaded="$(grep -E '^DATABASE_URL=' "$env_file" | tail -n 1 | sed -E 's/^DATABASE_URL=//; s/^"//; s/"$//; s/^'\''//; s/'\''$//')" || true
  if [ -n "$loaded" ]; then
    export DATABASE_URL="$loaded"
  fi
}

load_database_url_from_env_file
if [ -z "${DATABASE_URL:-}" ]; then
  isolation_setup_hint
  exit 1
fi
if [[ "${DATABASE_URL}" != */"${ISOLATION_DB}" ]]; then
  echo "[check] refusing non-isolated DATABASE_URL (must end with /${ISOLATION_DB})" >&2
  isolation_setup_hint
  exit 1
fi

run_if_present() {
  local description="$1"
  local path="$2"
  shift 2

  if [ -e "$path" ]; then
    echo "[check] $description"
    (
      cd "$(dirname "$path")"
      "$@"
    )
  fi
}

run_if_present "frontend frozen install" "$ROOT_DIR/frontend/package-lock.json" npm ci --ignore-scripts --no-audit --no-fund
run_if_present "frontend type check" "$ROOT_DIR/frontend/package.json" npm run check
run_if_present "frontend build" "$ROOT_DIR/frontend/package.json" npm run build
run_if_present "frontend bundle budget" "$ROOT_DIR/frontend/package.json" npm run check:bundle-budget
run_if_present "frontend lint" "$ROOT_DIR/frontend/package.json" npm run lint
run_if_present "frontend production dependency audit" "$ROOT_DIR/frontend/package.json" npm audit --audit-level=moderate --omit=dev

if [ -f "$ROOT_DIR/pyproject.toml" ]; then
  echo "[check] python project detected via pyproject.toml"
elif [ -d "$ROOT_DIR/backend" ]; then
  echo "[check] compiling backend python sources"
  "$PYTHON_BIN" -m compileall -q "$ROOT_DIR/backend/app"
fi

echo "[check] active A-share test suite"
(cd "$ROOT_DIR" && "$PYTHON_BIN" -m pytest -q)

echo "[check] active runtime safety"
(cd "$ROOT_DIR" && "$PYTHON_BIN" rebuild/assert_safety.py)

run_if_present "mock operator E2E" "$ROOT_DIR/frontend/playwright.config.ts" npm run test:e2e:mock

echo "[check] diff whitespace"
git -C "$ROOT_DIR" diff --check

if [ -f "$ROOT_DIR/voice_gen.py" ]; then
  echo "[check] compiling standalone python entrypoints"
  python3 -m compileall "$ROOT_DIR/voice_gen.py"
fi

echo "[check] done"
