---
name: risk-gate
description: 按业务上下文创建 Risk Scout subagent，动态定位风险范围、检查流程与证据，返回 head-bound Artifact
group: risk
owner: 杨欣琳
pattern: Pattern 1 (Orchestrator-Worker) + Pattern 5 (Human-in-the-Loop Gate)
---

# Dynamic Risk Gate Skill

## 何时使用

当 PR、研究 Artifact 或业务 handoff 可能需要风险审查时调用本 skill。Risk Gate 不是
固定的 VaR / 回撤清单；主 agent 必须创建独立 **Risk Scout subagent**，让它先定位本次
真正要审查的内容，再设计检查流程和证据要求。

典型入口：

- GitHub Actions 在 PR 创建或更新时触发
- 模型组通过 `model:pr-submit` handoff 给 risk 组
- OpenCode MCP `quantcode` server（`QUANTCODE_GROUP=risk`）

## 动态 Orchestrator-Worker 流程

1. 主 agent 创建 Risk Scout child task，绑定 repository / PR / base SHA / head SHA、
   `subagent_id` 和 `parent_task_id`。
2. Scout 使用 CI 专用只读工具定位 changed files、相关契约、政策和已有 Artifact。
3. Scout 提交 `RiskGateTaskArtifact`，decision 为 `required | not_required | indeterminate`。
4. 确定性 validator 校验 coverage、证据引用、步骤 DAG、capability requests 和 Artifact digest。
5. `required` 且 `execution_ready=true` 时，orchestrator 按动态 `process[]` 创建受限 specialist
   subagents；每个 specialist 只能调用对应 capability。
6. specialist 返回 head/plan-bound evidence Artifact；无证据、超时、未知 capability 或失败步骤
   均 fail closed。
7. 无密钥 reducer 汇总证据和版本化政策，产生最终 `RiskGateArtifact`。
8. 只有最终 Artifact 为 `needs_human` 时才创建 HumanGate；审批必须绑定 head SHA、task digest、
   plan digest 和 evidence digest。

## Risk Scout 的受控工具

CI 规划阶段只允许 `list_changed_files`、`read_changed_files`、
`list_risk_capabilities`、`get_policy_ref` 和 `submit_risk_gate_task`。当前 provider egress
只包含 PR changed-file diff 与受信 capability/policy metadata；非 PR Artifact / handoff connector
尚未接入。

不得提供 `bash`、`write_file`、任意 Python entrypoint、GitHub 写接口、原始 COS / 数据库凭据
或 `request_human_review`。规划阶段不产生外部副作用。

## Fail-closed 规则

- `not_required` 也必须覆盖全部 changed files 并返回 Artifact，不能静默 skip；
- diff 未完整检查、存在重要 unknowns 或缺少 capability 时不能标记 execution-ready；
- 模型发明 changed file、policy、evidence 或 capability 时拒绝 Artifact；
- 未注册 capability 可以保留在计划中供人处理，但绝不自动执行；
- DeepSeek 输出不能直接设置 GitHub status、发评论或批准 HumanGate；
- stale head、dangling evidence、步骤环、缺少必需步骤、哈希不符或工具越权一律失败；
- specialist 或 reducer 异常不得降级为 pass / not_required。

## 输入

必需：

- `repository` / `pr_number`
- `base_sha` / `head_sha`
- PR diff 或其他业务事件的可信 context refs

可选：

- `project_id` / `blackboard_db_path` / `blackboard_key`
- `ModelSpec`、`FactorReport`、`RiskProfile`、BacktestManifest 等 Artifact 引用
- 版本化 policy refs 和 capability registry 引用

旧的 `scenario=normal|high_risk` 只保留为 legacy fixture，不得作为生产 Risk Gate。

## 输出

正式规划输出为 `schemas.risk_gate_task.RiskGateTaskArtifact`：

- `trigger`：decision、引用证据的原因和开放式 risk domains；
- `scope`：included / excluded / assumptions / unknowns / diff coverage；
- `process[]`：objective、method、capability、依赖、证据输出、验收标准、失败动作；
- `execution_requests[]`：结构化 capability 请求，不是 shell command；
- `evidence[]`、subagent provenance 和 canonical SHA-256。

`RiskProfile` 继续作为量化策略的一种 domain attachment，不再是所有 Risk Gate 的总契约。

## 运行路径

- **CI / Server B**：`scripts/ci/discover_risk_gate.py` 运行 bounded tool loop，随后由 capability
  compiler / executor / reducer / publisher 分权处理；
- **当前 CI v1 限制**：只自动执行一个 required step/request；多步骤 Artifact 会保留，但结果为
  `not_evaluable`。`needs_human` 会发布失败的 advisory status，尚未接入交互式 approve/resume；
- **OpenCode / MCP**：真实 ComposeTask child spawn 与 context-Artifact connector 尚未接入，当前仍走
  legacy `runner.risk_agent`；
- **Legacy**：`scripts/run_risk_gate_tool.py` 仅供旧 UI、fixture 和渐进迁移。

## 依赖

- `schemas.risk_gate_task.RiskGateTaskArtifact`
- trusted capability / policy registry
- task-level tool execution allowlist
- evidence validator + head-bound HumanGate binding schema（interactive CI wiring pending）
