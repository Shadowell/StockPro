#!/usr/bin/env bash

set -euo pipefail

TARGET_ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
PINNED_SOURCE_SHA="2e4b90c3f83672cb9c3fc2e31b772f6c52efacb1"
BITPRO_SOURCE_REPO="${BITPRO_SOURCE_REPO:-/Users/jie.feng/Dev/Github/Private/BitPro}"
BITPRO_SOURCE_SHA="${BITPRO_SOURCE_SHA:-$PINNED_SOURCE_SHA}"

MODE=""
MANIFEST_PATH=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      MODE="dry-run"
      shift
      ;;
    --apply)
      MODE="apply"
      shift
      ;;
    --manifest)
      if [ "$#" -lt 2 ]; then
        echo "--manifest requires a path" >&2
        exit 2
      fi
      MANIFEST_PATH="$2"
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [ "$MODE" != "dry-run" ] && [ "$MODE" != "apply" ]; then
  echo "exactly one of --dry-run or --apply is required" >&2
  exit 2
fi
if [ -z "$MANIFEST_PATH" ]; then
  echo "--manifest is required" >&2
  exit 2
fi
if [ "$(pwd -P)" != "$TARGET_ROOT" ]; then
  echo "refusing to import outside $TARGET_ROOT" >&2
  exit 1
fi
TARGET_BRANCH="$(git branch --show-current)"
if [[ "$TARGET_BRANCH" != codex/* ]]; then
  echo "refusing to import outside a codex/* branch" >&2
  exit 1
fi
if [ "$BITPRO_SOURCE_SHA" != "$PINNED_SOURCE_SHA" ]; then
  echo "BitPro source SHA must remain pinned to $PINNED_SOURCE_SHA" >&2
  exit 1
fi

backend/venv/bin/python rebuild/verify_source.py \
  "$BITPRO_SOURCE_REPO" \
  "$BITPRO_SOURCE_SHA" \
  >/dev/null

IMPORT_TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$IMPORT_TEMP_DIR"' EXIT
git -C "$BITPRO_SOURCE_REPO" archive "$BITPRO_SOURCE_SHA" | tar -x -C "$IMPORT_TEMP_DIR"

GENERATED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
WRITES_PERFORMED="false"

if [ "$MODE" = "apply" ]; then
  COMMON_EXCLUDES=(
    --exclude=.env
    --exclude='.env.*'
    --exclude=__pycache__/
    --exclude='*.pyc'
    --exclude='*.db'
    --exclude='*.sqlite'
    --exclude='*.log'
  )
  rsync -a --delete "${COMMON_EXCLUDES[@]}" --exclude=venv/ \
    "$IMPORT_TEMP_DIR/backend/" "$TARGET_ROOT/backend/"
  rsync -a --delete "${COMMON_EXCLUDES[@]}" --exclude=node_modules/ --exclude=dist/ \
    "$IMPORT_TEMP_DIR/frontend/" "$TARGET_ROOT/frontend/"
  rsync -a --delete "${COMMON_EXCLUDES[@]}" \
    "$IMPORT_TEMP_DIR/packages/" "$TARGET_ROOT/packages/"
  rsync -a --delete "${COMMON_EXCLUDES[@]}" \
    "$IMPORT_TEMP_DIR/scripts/" "$TARGET_ROOT/scripts/"
  rsync -a --delete "${COMMON_EXCLUDES[@]}" \
    "$IMPORT_TEMP_DIR/tests/" "$TARGET_ROOT/tests/"

  mkdir -p "$TARGET_ROOT/docs/reference/bitpro-baseline"
  rsync -a --delete "$IMPORT_TEMP_DIR/docs/pages/" \
    "$TARGET_ROOT/docs/reference/bitpro-baseline/pages/"
  rsync -a --delete "$IMPORT_TEMP_DIR/docs/screenshots/" \
    "$TARGET_ROOT/docs/reference/bitpro-baseline/screenshots/"
  rsync -a --delete "$IMPORT_TEMP_DIR/docs/product_manual/" \
    "$TARGET_ROOT/docs/reference/bitpro-baseline/product-manual/"
  WRITES_PERFORMED="true"
fi

mkdir -p "$(dirname "$MANIFEST_PATH")"
python3 - \
  "$MANIFEST_PATH" \
  "$MODE" \
  "$BITPRO_SOURCE_REPO" \
  "$BITPRO_SOURCE_SHA" \
  "$TARGET_ROOT" \
  "$TARGET_BRANCH" \
  "$GENERATED_AT" \
  "$WRITES_PERFORMED" <<'PY'
import json
import sys
from pathlib import Path

(
    manifest_path,
    mode,
    source_repo,
    source_sha,
    target_root,
    target_branch,
    generated_at,
    writes_performed,
) = sys.argv[1:]
manifest = {
    "schema_version": "stockpro-bitpro-import.v1",
    "mode": mode,
    "source_repo": str(Path(source_repo).resolve()),
    "source_sha": source_sha,
    "source_archive": "git-object-database",
    "target_root": target_root,
    "target_branch": target_branch,
    "generated_at": generated_at,
    "writes_performed": writes_performed == "true",
    "copied_roots": ["backend", "frontend", "packages", "scripts", "tests"],
    "preserved_roots": [
        ".github",
        "deploy",
        "docs/contracts",
        "docs/spec.md",
        "docs/progress.md",
        "AGENTS.md",
        "LICENSE",
    ],
    "excluded_roots": ["data", "content"],
    "excluded_patterns": [
        ".env",
        ".env.*",
        "venv/",
        "node_modules/",
        "dist/",
        "__pycache__/",
        "*.pyc",
        "*.db",
        "*.sqlite",
        "*.log",
    ],
    "reference_paths": ["docs/pages", "docs/screenshots", "docs/product_manual"],
    "reference_destinations": [
        "docs/reference/bitpro-baseline/pages",
        "docs/reference/bitpro-baseline/screenshots",
        "docs/reference/bitpro-baseline/product-manual",
    ],
}
Path(manifest_path).write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
PY

if [ "$MODE" = "apply" ]; then
  cp "$MANIFEST_PATH" "$TARGET_ROOT/docs/reference/bitpro-baseline/source.json"
fi

echo "$MODE verified for $BITPRO_SOURCE_SHA; manifest: $MANIFEST_PATH"
