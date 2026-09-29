#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

profile="${1:-full}"
quality_targets=(src tests)
pyright_targets=(src)
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
