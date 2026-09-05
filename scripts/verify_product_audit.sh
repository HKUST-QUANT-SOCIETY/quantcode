#!/usr/bin/env bash
# Local regression only. Does not enable real LLMs, SSH credentials or deployment.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
python_bin="${QUANTCODE_TEST_PYTHON:-python3}"
PYTHONPATH="$repo_root${PYTHONPATH:+:$PYTHONPATH}" "$python_bin" -m pytest -q
cd "$repo_root/frontend/packages/app"
bun test --only-failures --preload ./happydom.ts ./src/components/quantcode
bun run typecheck
# Require the caller to identify the migrated Dev, rather than silently testing an old checkout.
: "${PLAYWRIGHT_BASE_URL:?Set PLAYWRIGHT_BASE_URL to the existing quantcode/frontend Dev URL}"
# Never start/restart it from a test.
PLAYWRIGHT_EXTERNAL_SERVER=1 PLAYWRIGHT_BASE_URL="${PLAYWRIGHT_BASE_URL}" \
  bun run test:e2e -- quantcode/workspace.spec.ts
