# Yang Xinlin Day 1 Schema Review

> Reviewer: 杨欣琳  
> Track: T2 风控 / 跨组接收  
> Review scope: ComposeTask, BlackboardState, ResearchSpec + PITQuery/PITResult  
> Main concern: whether the foundational contracts can support HumanGate, RiskProfile, risk-gate, and deduped PR comments.

---

## Overall Position

I agree with freezing `ComposeTask` and `BlackboardState` as the Day 1 v1 contracts.
They are enough for the T2 risk flow to start drafting `HumanGate`, `RiskProfile`,
and `risk-gate` without blocking on a larger orchestration redesign.

My main review comments are not blockers. They are interface questions that should be
clarified before the risk-gate flow starts writing PR comments and creating manual
approval gates.

---

## 1. ComposeTask Review

### What Works

- `task_id`, `parent_task_id`, `root_task_id`, and `depth` can represent the risk
  task tree clearly.
- `group=GroupName.RISK` gives the risk flow a first-class owner.
- `status=blocked` can represent a task waiting on human review.
- `outcome=REJECTED` gives HumanGate denial a clean terminal result.
- `ComposeTaskEvent.HANDOFF` fits the model-to-risk transition.

### T2 Risk Concern

For HumanGate, we need a clear convention for manual review states.

Current fields are enough, but we should document the mapping:

| HumanGate state | ComposeTask status | ComposeTask outcome |
|---|---|---|
| pending human review | `blocked` | `None` |
| approved | `done` | `success` |
| rejected | `abandoned` | `rejected` |
| timed out | `abandoned` | `cancelled` or `failure` |
| escalated | `blocked` | `None` |

### Question

Should `timeout` map to `TaskOutcome.CANCELLED` or `TaskOutcome.FAILURE`?

My recommendation: use `CANCELLED` when timeout means "no decision made", and reserve
`FAILURE` for technical or validation failures.

---

## 2. BlackboardState Review

### What Works

- Hard `GROUP` isolation is the right default for risk work.
- Cross-group handoff through `PROJECT` scope is safer than allowing direct reads
  from another group's private memory.
- The model-to-risk example in the review doc matches the actual T2 workflow.

### T2 Risk Concern

Risk-gate needs to write side effects back to GitHub. The first side effect is a PR
comment. To avoid duplicate comments, the dedupe key needs a stable place.

I suggest recording dedupe metadata in `PROJECT` scope, because PR comments are
cross-group artifacts and should not live only in the risk group's private memory.

Suggested key:

```text
shared.side_effects.github_pr_comment.risk_gate
```

Suggested value:

```json
{
  "pr_url": "https://github.com/HKUST-QUANT-SOCIETY/quantcode/pull/123",
  "head_sha": "abc123",
  "dedupe_key": "risk-gate:https://.../pull/123:abc123",
  "last_comment_id": "123456789",
  "written_by": "risk-gate"
}
```

### Question

Should dedupe records live only in SQLite inside `tools/utils/dedupe.py`, or should
the dedupe key also be mirrored into `BlackboardState` for auditability?

My recommendation: use SQLite as the execution guard, and mirror a summary into
`BlackboardState` for traceability.

---

## 3. ResearchSpec + PITQuery/PITResult Review

This is not my primary Day 1 track, but I reviewed it for cross-flow consistency.

### What Works

- The `as_of_date` contract is clear.
- The `PITResult` validator catches lookahead bias directly.
- The schema can support fundamental research and later provide artifacts to risk
  or strategy flows if needed.

### Non-blocking Comment

`PITResult` may later need a stable artifact path if other groups consume the
retrieval result. For Day 1, keeping it as typed output is enough.

---

## 4. Implications for HumanGate

Based on the current contracts, I can draft `HumanGate` with these fields:

- `gate_id`
- `task_id`
- `trigger`
- `risk_thresholds`
- `required_approvers`
- `timeout_minutes`
- `notify_channels`
- `decision`
- `decision_by`
- `decision_reason`
- `dedupe_key`
- `pr_url`

The schema should reference `ComposeTask.task_id` and use `TaskOutcome.REJECTED`
for denied gates.

---

## 5. Implications for RiskProfile

`RiskProfile` can be the typed output of a risk task:

```python
ComposeTask[ModelSpec, RiskProfile]
```

Minimum Day 1 fields:

- `max_drawdown`
- `position_limit`
- `correlation_with_existing`
- `tail_risk_var_99`
- `pr_url`
- `strategy_id`
- `as_of_date`

The acceptance runner can then assert:

```python
assert risk.max_drawdown <= 0.20
assert risk.position_limit <= 0.30
assert abs(risk.correlation_with_existing) <= 0.60
assert risk.tail_risk_var_99 is not None
```

---

## Review Decision

I am OK with the current `ComposeTask` and `BlackboardState` v1 contracts for Day 1.

My two requested clarifications:

1. Confirm the HumanGate-to-ComposeTask status/outcome mapping.
2. Confirm whether PR comment dedupe metadata should be mirrored into
   `BlackboardState` in addition to SQLite.

These are not blockers for starting the T2 risk schema draft.
