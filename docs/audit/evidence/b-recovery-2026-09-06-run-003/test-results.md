# B2 final test results

- Focused B2 acceptance: `88 passed, 1 warning in 10.97s`
- Full backend: `1167 passed, 4 skipped, 2 warnings in 29.90s`
- Ruff on all B-line changed/new Python files: `All checks passed!`
- `git diff --check`: clean

Focused command:

```bash
uv run --extra dev pytest -q \
  tests/test_tool_receipts_process.py \
  tests/test_mcp_recovery_reliability.py \
  tests/test_receipt_reconciliation_gateway.py \
  tests/test_tool_receipts.py \
  tests/test_checkpoint_recovery_process.py \
  tests/test_approval_reliability.py \
  tests/test_gate_expiry.py \
  tests/test_solution_workflow.py \
  tests/test_solution_invalidation_process.py \
  tests/test_agent_mcp_tool.py \
  --junitxml=docs/audit/evidence/b-recovery-2026-09-06-run-003/b2-acceptance.xml
```

Full command:

```bash
uv run --extra dev pytest -q
```

The warnings are the existing `ToolDef.schema` Pydantic warning and the Chroma
telemetry Python 3.14 deprecation warning. The four existing real-LLM tests
remain skipped by environment guards.
