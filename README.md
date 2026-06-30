# QuantCode

> **港科大量化协会 Agent 平台** — 把投研流程编译成确定性 pipeline，让 AI 成为可靠生产力

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-alpha-orange.svg)]()

QuantCode 是 HKUST QUANT SOCIETY agent 组在 [MimoCode](https://github.com/XiaomiMiMo/MiMo-Code) 之上构建的量化投研 agent 平台。我们不 fork MimoCode 源码，只通过 skills / plugins / schemas 做加法。

## 核心理念

| 原则 | 含义 |
|---|---|
| **载体不自建** | MimoCode 提供 TUI / 桌面端 / 编辑器，我们不重复造轮子 |
| **流程层自建** | 业务 skills、JSON schema、验收 runner 是我们的 IP |
| **确定性契约** | skill 之间用 JSON schema 通信，不依赖自然语言 |
| **程序化验收** | 验收标准 = `assert` 语句，不是人工"看一眼" |

详见 [quantcode_design.md](./quantcode_design.md)。

## 目录结构

```
.mimocode/         # MimoCode 配置 + skills + plugins
schemas/           # JSON Schema 业务契约
pipelines/         # 各 skill 的 Python 实现
templates/         # Typst 模板、prompt 模板
runner/            # 验收 runner（公用）
.github/workflows/ # CI gate
docs/              # PRD、架构文档
vendor/            # 第三方依赖（不入版本控制）
```

## 快速开始

```bash
# 1. 安装 MimoCode（载体）
curl -fsSL https://mimo.xiaomi.com/install | bash

# 2. 克隆本仓库
gh repo clone HKUST-QUANT-SOCIETY/quantcode
cd quantcode

# 3. 配置 provider（不入库）
cp .mimocode/mimocode.jsonc .mimocode/mimocode.local.jsonc
# 编辑 mimocode.local.jsonc 加 API key

# 4. 启动
mimo
```

## 核心 Skills

| Skill | 描述 | Owner |
|---|---|---|
| `risk-gate` | PR 风控门禁 | 陈镇鸿 |
| `pit-rag` | Point-in-time RAG | 杨欣琳 / Lead |
| `research-pdf` | 中金风格 PDF 研报 | Lead / 刘炽 |
| `factor-eval` | 因子有效性评估 | 肖骥超 |

## 文档

- [PRD](docs/PRD.md) — 产品需求文档
- [设计文档](quantcode_design.md) — 架构方法论

## 团队

HKUST QUANT SOCIETY · Agent Group

## License

MIT
