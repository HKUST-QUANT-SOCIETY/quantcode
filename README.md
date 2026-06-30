# QuantCode

> **港科大量化协会 Agent 平台** — 6 个组登录同一个 agent，每个组进入自己工作流的 Compose 流；流跑完自动接入生产主线。

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-alpha-orange.svg)]()

QuantCode 是 HKUST QUANT SOCIETY agent 组在 [OpenCode](https://github.com/anomalyco/opencode) fork 之上构建的量化投研 agent 平台。我们**不 fork MimoCode**：从 MimoCode cherry-pick Memory / Checkpoint / Subagent / Goal / Dream / Distill 等模块代码进我们的 OpenCode fork，业务能力通过 plugin / tool / skill 加在 fork 之上。

## 核心叙事

> 用 agent 把 5 人 agent 组的产能放大成 30 人投研团队——做大机构嫌人力成本不划算、单一精品店没有广度去做的事：全标的、低相关、高频迭代的策略工厂。

## 核心理念

| 原则 | 含义 |
|---|---|
| **千组千流** | 统一 UI + 按组分发不同的 SKILL.md / MEMORY / 默认 tool 集 |
| **Compose Mode 是产品中枢** | 第三种 primary agent，6 套 vertical Compose 流落到三大生产模式 |
| **三大生产模式** | Pattern 1 (Orchestrator-Worker) + Pattern 2 (Stateful Blackboard) + Pattern 5 (Human-in-the-Loop Gate) + 副作用 tool dedupe 保险栓 |
| **确定性契约** | skill 之间用 Pydantic / JSON Schema 通信，不依赖自然语言 |
| **程序化验收** | 验收 = `assert` + Goal/Judge，不是"看一眼觉得行" |
| **Dream + Distill** | 后台自我进化：自动沉淀 MEMORY、识别重复操作封装新 SKILL.md |

详见 [`docs/QuantCode_Design.md`](docs/QuantCode_Design.md)。

## 目录结构

```
.opencode/groups/<group>/        # 按组分发：fundamental / factor / model / risk / strategy / options
   ├── MEMORY.md                  # 组内私有长期知识
   ├── skills/                    # 该组的 SKILL.md 文件（Compose 流构件）
   ├── tools/                     # 该组私有 tool
   └── agent.yaml                 # 该组 primary agent 配置（计划）
opencode.jsonc                    # OpenCode 全局配置 + 权限
schemas/                          # Pydantic / JSON Schema 业务契约
pipelines/                        # 各 skill 的 Python 实现
templates/                        # Typst 模板、prompt 模板
runner/                           # 验收 runner（公用，吃 JSON 吐 pass/fail）
tools/utils/                      # 跨组共享工具（含 @dedupe_within 保险栓）
.github/workflows/                # CI gate
docs/                             # PRD、Design、Day 1 任务清单
vendor/                           # 第三方依赖（cherry-pick 参考，.gitignore，不入主仓）
```

## 快速开始

```bash
# 1. clone 本仓库
gh repo clone HKUST-QUANT-SOCIETY/quantcode
cd quantcode

# 2. clone OpenCode fork（载体）
gh repo clone HKUST-QUANT-SOCIETY/opencode ../opencode
cd ../opencode && bun install && bun run dev
# TUI 起来后能跟内置 build agent 对话即代表载体跑通

# 3. 配置 provider（不入库）
cp opencode.jsonc opencode.local.jsonc
# 编辑 opencode.local.jsonc，加 LLM API key

# 4. 安装 Python 业务包
cd ../quantcode
pip install -e .
```

## 6 套 Compose 流（业务层）

| Compose 流 | Owner | 核心 SKILL.md |
|---|---|---|
| **fundamental** | 用户（Lead） | `fundamental:brainstorm/fetch/extract/dcf/draft/render/review/publish` |
| **factor** | 肖骥超 | `factor:brainstorm/match-main/gen-schema/execute/autoeval/risk-check/merge-main` |
| **model** | 陈镇鸿 | `model:brainstorm/lit-review/plan/execute/pr-submit/cross-handoff` |
| **risk** | 杨欣琳 | `risk:detect/analyze/schema-gen/ci-gate/feedback` |
| **strategy** | 待定 | `strategy:brainstorm/select/combine/backtest/deploy` |
| **options** | 刘炽 | `options:brainstorm/vol-surface/greeks/execute` |

## 文档

- [Design](docs/QuantCode_Design.md) — 项目定位、架构、Pattern 1/2/5、6 套 Compose 流、团队分工
- [PRD](docs/PRD.md) — 产品需求文档
- [Day 1 任务清单](docs/Day1_TaskList.md) — 启动日全员任务

## 团队

HKUST QUANT SOCIETY · Agent Group · 6 人

## License

MIT
