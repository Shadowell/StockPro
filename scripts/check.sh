#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT_DIR/backend/venv/bin/python"
SETUP_CMD="./scripts/setup_isolation_db.sh"
ISOLATION_DB="stockpro_bitpro_rebase_dev"

isolation_setup_hint() {
  cat <<EOF >&2
[check] Isolation database '${ISOLATION_DB}' is required for this golden path.
[check] Create it with one command:
[check]   ${SETUP_CMD}
[check] Then:
[check]   export DATABASE_URL="\$(${SETUP_CMD} --print-url)"
[check]   ${SETUP_CMD} --migrate
[check] Docs: docs/deployment.md#isolation-database
EOF
}

load_database_url_from_env_file() {
  local env_file="$1"
  [ -f "$env_file" ] || return 0
  local line value
  line="$(grep -E '^[[:space:]]*DATABASE_URL=' "$env_file" | tail -n 1 || true)"
  [ -n "$line" ] || return 0
  value="${line#*=}"
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  if [ -n "$value" ]; then
    DATABASE_URL="$value"
    export DATABASE_URL
    echo "[check] loaded DATABASE_URL from ${env_file}"
  fi
}

VENV_OK=1
if [ ! -x "$PYTHON" ]; then
  echo "[check] backend virtual environment is missing: $PYTHON" >&2
  echo "[check] Create it with: python3 -m venv backend/venv && backend/venv/bin/python -m pip install -r backend/requirements.txt" >&2
  VENV_OK=0
fi

if [ -z "${DATABASE_URL:-}" ] && [ "${STOCKPRO_CHECK_SKIP_ENV_FILE:-0}" != "1" ]; then
  load_database_url_from_env_file "$ROOT_DIR/backend/.env"
fi

if [ -z "${DATABASE_URL:-}" ]; then
  echo "[check] DATABASE_URL is unset." >&2
  isolation_setup_hint
  exit 1
fi

case "$DATABASE_URL" in
  *"/stockpro_bitpro_rebase_dev") ;;
  *)
    echo "[check] refusing non-isolated DATABASE_URL (must end with /${ISOLATION_DB})" >&2
    isolation_setup_hint
    exit 1
    ;;
esac

if [ "$VENV_OK" -ne 1 ]; then
  exit 1
fi

echo "[check] repository root: $ROOT_DIR"
echo "[check] isolation DATABASE_URL is set"
mkdir -p "$ROOT_DIR/.codex-artifacts/rebuild"

echo "[check] rebuild safety"
"$PYTHON" "$ROOT_DIR/rebuild/assert_safety.py" --root "$ROOT_DIR" --format json \
  > "$ROOT_DIR/.codex-artifacts/rebuild/safety.json"

echo "[check] pinned BitPro frontend parity"
"$PYTHON" "$ROOT_DIR/rebuild/audit_frontend_parity.py" \
  --source "/Users/jie.feng/Dev/Github/Private/BitPro/frontend/src" \
  --target "$ROOT_DIR/frontend/src" \
  --manifest "$ROOT_DIR/rebuild/contracts/frontend-parity.json" \
  --output "$ROOT_DIR/.codex-artifacts/rebuild/frontend-parity.json"

echo "[check] python compile"
"$PYTHON" -m compileall -q "$ROOT_DIR/backend/app" "$ROOT_DIR/backend/tests" "$ROOT_DIR/rebuild"

echo "[check] current backend and rebuild tests"
(
  cd "$ROOT_DIR"
  "$PYTHON" -m pytest backend/tests rebuild/tests -q --junitxml="$ROOT_DIR/.codex-artifacts/rebuild/backend-tests.xml"
)

echo "[check] frontend frozen install"
npm --prefix "$ROOT_DIR/frontend" ci --ignore-scripts --no-audit --no-fund

echo "[check] frontend type check"
npm --prefix "$ROOT_DIR/frontend" run check

echo "[check] frontend lint"
npm --prefix "$ROOT_DIR/frontend" run lint

echo "[check] frontend production build"
npm --prefix "$ROOT_DIR/frontend" run build

echo "[check] frontend bundle budget"
npm --prefix "$ROOT_DIR/frontend" run check:bundle-budget

echo "[check] frontend production dependency audit"
npm --prefix "$ROOT_DIR/frontend" audit --audit-level=moderate --omit=dev

echo "[check] mock operator shell, research, and mainline E2E"
npm --prefix "$ROOT_DIR/frontend" run test:e2e:mock

echo "[check] diff whitespace"
git -C "$ROOT_DIR" diff --check

echo "[check] evidence-backed pre-deploy completion audit"
"$PYTHON" "$ROOT_DIR/rebuild/audit_completion.py" --mode pre-deploy --output "$ROOT_DIR/.codex-artifacts/rebuild/completion-audit.json"

echo "[check] done"
