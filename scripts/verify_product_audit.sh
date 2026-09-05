#!/usr/bin/env bash
# Local regression only. Does not enable real LLMs, SSH credentials or deployment.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
python_bin="${QUANTCODE_TEST_PYTHON:-python3}"
PYTHONPATH="$repo_root${PYTHONPATH:+:$PYTHONPATH}" "$python_bin" -m pytest -q
if [[ -z "${QUANTCODE_UI_ROOT:-}" ]]; then
  echo 'Backend complete. Set QUANTCODE_UI_ROOT to the opencode-lens checkout to include UI checks.'
  exit 0
fi
cd "$QUANTCODE_UI_ROOT/packages/app"
bun test --only-failures --preload ./happydom.ts ./src/components/quantcode
bun run typecheck
# Uses branded launcher; reuses an existing server without restarting it.
QUANTCODE_ROOT="$repo_root" bunx playwright test --config playwright.quantcode.config.ts
