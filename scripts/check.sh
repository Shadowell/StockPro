#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT_DIR/backend/venv/bin/python"

if [ ! -x "$PYTHON" ]; then
  echo "[check] backend virtual environment is missing: $PYTHON" >&2
  exit 1
fi
if [ -z "${DATABASE_URL:-}" ]; then
  echo "[check] DATABASE_URL must point to stockpro_bitpro_rebase_dev" >&2
  exit 1
fi
case "$DATABASE_URL" in
  *"/stockpro_bitpro_rebase_dev") ;;
  *)
    echo "[check] refusing non-isolated DATABASE_URL" >&2
    exit 1
    ;;
esac

echo "[check] repository root: $ROOT_DIR"

echo "[check] rebuild safety"
"$PYTHON" "$ROOT_DIR/rebuild/assert_safety.py" --root "$ROOT_DIR" --format json \
  > "$ROOT_DIR/.codex-artifacts/rebuild/safety.json"

echo "[check] python compile"
"$PYTHON" -m compileall -q "$ROOT_DIR/backend/app" "$ROOT_DIR/backend/tests" "$ROOT_DIR/rebuild"

echo "[check] current backend and rebuild tests"
(
  cd "$ROOT_DIR"
  "$PYTHON" -m pytest backend/tests rebuild/tests -q
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
npm --prefix "$ROOT_DIR/frontend" run test:e2e:mock -- --grep "shell|home|market switches|stock pool|factor lab|strategy center|backtest console|paper dashboard|only execution mainline|signal center audits|monitor separates lifecycle|daily review|one Paper lineage"

echo "[check] diff whitespace"
git -C "$ROOT_DIR" diff --check

echo "[check] done"
