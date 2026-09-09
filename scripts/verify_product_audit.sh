#!/usr/bin/env bash
# Local regression only. Does not enable real LLMs, SSH credentials or deployment.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
if [[ -n "${QUANTCODE_TEST_PYTHON:-}" ]]; then
  python_bin="$QUANTCODE_TEST_PYTHON"
else
  python_bin=""
  for candidate in "$repo_root/.venv/bin/python" python3 python3.12 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import pytest" >/dev/null 2>&1; then
      python_bin="$candidate"
      break
    fi
  done
  if [[ -z "$python_bin" ]]; then
    echo "No Python interpreter with pytest is available; set QUANTCODE_TEST_PYTHON." >&2
    exit 2
  fi
fi
PYTHONPATH="$repo_root${PYTHONPATH:+:$PYTHONPATH}" "$python_bin" -m pytest -q
PYTHONPATH="$repo_root${PYTHONPATH:+:$PYTHONPATH}" "$python_bin" -m ruff check .
cd "$repo_root/frontend/packages/app"
bun test --only-failures --preload ./happydom.ts ./src/components/quantcode
bun run typecheck
cd "$repo_root/frontend/packages/opencode"
bun run typecheck
cd "$repo_root/frontend/packages/desktop"
bun run typecheck
cd "$repo_root"
bun run build:web
cd "$repo_root/frontend/packages/app"
# Require the caller to identify the migrated Dev, rather than silently testing an old checkout.
: "${PLAYWRIGHT_BASE_URL:?Set PLAYWRIGHT_BASE_URL to the existing quantcode/frontend Dev URL}"
# Never start/restart it from a test.
PLAYWRIGHT_EXTERNAL_SERVER=1 PLAYWRIGHT_BASE_URL="${PLAYWRIGHT_BASE_URL}" \
  bun run test:e2e -- --config=playwright.quantcode.config.ts quantcode/workspace.spec.ts
