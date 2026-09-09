---
name: risk-ci
description: 生成 RiskProfile 与风险 verdict，并把真实 pass/fail 写入 CI 报告
group: risk
owner: 杨欣琳
pattern: ReAct tool loop + deterministic CI compatibility flow
---

# Risk CI Skill

## 使用边界

本 Skill 用于消费结构化 ModelSpec、调用风险组件、生成 RiskProfile，并把风险结果写入 CI 报告。Model→Risk 是 GitHub Actions/CI 基建，不是 QuantCode 产品主流程。

风险越限是领域 `fail`/`warning`，不得创建 HumanGate。普通 HumanGate 只有 `merge` 与 `permission`。

## ReAct 顺序

1. `read_blackboard`：读取最小 ModelSpec/Artifact 引用；
2. `calc_risk`：调用风险计算 Adapter；
3. `generate_risk_profile`：生成并验证 RiskProfile；
4. `risk_verdict`：返回 `verdict`、`breached` 和 `reasons`；
5. `write_pr_comment`：无论 pass/fail 都写真实 CI 报告，保留来源、版本和降级状态。

不得调用 `request_human_review`，不得等待 approve/reject，不得把 mock/stub 结果表述为生产证据。

## 运行路径

- 产品主路径：当前 QuantCode 原生任务加载本 Skill，直接调用当前发布目录中的组织/组件工具；
- CI 兼容路径：`scripts/run_risk_ci_tool.py` → `runner.risk_ci`；
- MCP 工具：`read_blackboard`、`calc_risk`、`generate_risk_profile`、`risk_verdict`、`write_pr_comment`。

上列为适配接口名，不表示它们已接通或拥有发布权限。共享读写与受限资源访问仍遵守当前精确 merge/permission 审批；不得将“风险本身不触发审批”解释为允许绕过工具权限。

## 完成条件

- RiskProfile 通过 Schema；
- verdict、breached reasons、来源和环境显式；
- CI 报告已产生或错误明确；
- 全程没有风险类 HumanGate。
