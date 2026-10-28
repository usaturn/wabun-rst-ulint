#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

profile="${1:-full}"
quality_targets=(src tests)
pyright_targets=(src)

# Pyright must use the patched PATH runtime, not a bundled wheel or nodeenv.
export PYRIGHT_PYTHON_NODEJS_WHEEL=0
export PYRIGHT_PYTHON_GLOBAL_NODE=1
if ! command -v node > /dev/null; then
  printf 'Node.js 24.22.1 or later in the 24.x series is required on PATH.\n' >&2
  exit 1
fi
node --input-type=commonjs <<'JS'
const [major, minor, patch] = process.versions.node.split('.').map(Number);
console.log(`Pyright Node.js: ${process.version} (${process.execPath})`);
if (major !== 24 || minor < 22 || (minor === 22 && patch < 1)) {
  console.error('Node.js 24.22.1 or later in the 24.x series is required (eMudhra CA fix).');
  process.exit(1);
}
JS

uv lock --check
uv sync --locked --all-groups

case "$profile" in
  full)
    uv run --no-sync python -c 'import docutils; assert docutils.__version__ == "0.22.4"'
    uv run --no-sync pytest -v
    uv run --no-sync ruff format --check "${quality_targets[@]}"
    uv run --no-sync ruff check "${quality_targets[@]}"
    uv run --no-sync pyright "${pyright_targets[@]}"
    uv build --out-dir dist --clear
    uvx twine check --strict dist/*
    ;;
  *)
    printf 'unknown verification profile: %s\n' "$profile" >&2
    exit 64
    ;;
esac
