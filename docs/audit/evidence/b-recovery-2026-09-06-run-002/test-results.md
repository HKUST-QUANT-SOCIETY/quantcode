# Task B test results (2026-09-06)

- Base: `f0ec06fa80c9ffad28753827ce9533b080ea5f30`
- Branch: `feat/task-recovery-and-approval-reliability`
- P-10 focused: `35 passed, 1 warning in 1.39s`
- Task B combined regression: `134 passed, 1 warning in 10.22s`
- Full backend: `1160 passed, 4 skipped, 2 warnings in 25.46s`
- `git diff --check`: clean

Commands:

```bash
uv run --extra dev pytest -q \
  tests/test_solution_workflow.py \
  tests/test_solution_invalidation_process.py

uv run --extra dev pytest -q \
  tests/test_solution_workflow.py \
  tests/test_solution_invalidation_process.py \
  tests/test_checkpoint_recovery_process.py \
  tests/test_tool_receipts_process.py \
  tests/test_approval_reliability.py \
  tests/test_gate_expiry.py \
  tests/test_human_gate.py \
  tests/test_tool_receipts.py \
  tests/test_agent_mcp_tool.py \
  tests/test_agent_engine_basic.py

uv run --extra dev pytest -q
```

The two warnings are the existing Pydantic `ToolDef.schema` shadow warning and
the Chroma telemetry Python 3.14 deprecation warning. Four real-LLM tests remain
skipped by their existing environment guards.
