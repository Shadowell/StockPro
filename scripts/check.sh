#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

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

run_if_present "frontend build" "$ROOT_DIR/frontend/package.json" npm run build
run_if_present "frontend lint" "$ROOT_DIR/frontend/package.json" npm run lint

if [ -f "$ROOT_DIR/pyproject.toml" ]; then
  echo "[check] python project detected via pyproject.toml"
elif [ -d "$ROOT_DIR/backend" ]; then
  echo "[check] compiling backend python sources"
  python3 -m compileall "$ROOT_DIR/backend"
fi

if [ -f "$ROOT_DIR/voice_gen.py" ]; then
  echo "[check] compiling standalone python entrypoints"
  python3 -m compileall "$ROOT_DIR/voice_gen.py"
fi

echo "[check] done"
