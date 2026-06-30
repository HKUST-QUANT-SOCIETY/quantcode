---
name: model:pr-submit
description: 模型组提 PR 时自动填风控元数据 + 触发 risk Compose 流
group: model
owner: 陈镇鸿
pattern: Pattern 1 (Orchestrator-Worker) + Pattern 5 (Human-in-the-Loop Gate)
---

# Model PR Submit Skill

## 何时使用

模型组同学完成一个新的 ML 因子 / 策略 / 模型，准备提 PR 时调用本 skill。

## 输入

- 本地模型代码路径
- 训练数据范围、超参、依赖算子
- 简短的策略描述

## 工作流程

1. **生成 `ModelSpec`**：模型类型、训练数据范围、超参、依赖算子、风控元数据
2. **校验**：用 Pydantic 校验 `ModelSpec`；不通过则报错给用户改
3. **创建 PR**：通过 `github_pr_create`（带 `@dedupe_within`）
4. **触发跨组**：调用 `model:cross-handoff`，通知 risk Compose 流
5. **登记到 Blackboard**：写入 `MEMORY.md`，让风控组的 `risk:detect` 能发现

## 输出 schema

`ModelSpec`（由陈镇鸿 Day 1 起草），同时在 PR 描述里附 JSON 块。

## 验收标准

- PR 成功创建（GitHub PR URL 返回）
- `ModelSpec` 通过 Pydantic 校验
- 风控组的 risk-gate workflow 被触发（GH Actions run 出现）

## 副作用 tool 约定

- `github_pr_create` 必须经 `@dedupe_within(seconds=300)` 装饰
- `cross_team_notify` 必须经 `@dedupe_within(seconds=300)` 装饰
