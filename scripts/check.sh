#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="$ROOT_DIR/backend/venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python3"
fi

echo "[check] repository root: $ROOT_DIR"

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
