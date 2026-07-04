# OpenCode / MimoCode Compose 模式 & Tool 扩展调研报告

> **用途**：团队在 OpenCode 上落地自定义 compose 流和 tool 时的参考手册。
> **调研对象**：`vendor/mimo-code/packages/opencode/`（MimoCode = OpenCode fork）
> **调研时间**：2026-07-03
> **状态**：基于源码阅读的调研结论，**尚未实机验证**（本地启动 + MCP 连通性需要各自测试）

---

## 0. 一句话结论

OpenCode 的 compose 模式本质是 **ReAct 循环 + 不同 system prompt**，不是特殊编排引擎。自定义 tool 有三种接入方式：**TS 文件**（`.opencode/tools/*.ts`）、**Plugin**、**MCP Server（可用 Python）**。要接入 Python 写的 tool，走 **MCP** 这条路。

---

## 1. Compose 模式

### 1.1 定义位置
`src/agent/agent.ts`（约 L198-212）：

```typescript
compose: {
  name: "compose",
  description: "Compose mode. Orchestrates workflows with built-in compose skills.",
  permission: Permission.merge(defaults, Permission.fromConfig({ question: "allow" }), user),
  mode: "primary",
  native: true,
}
```

### 1.2 compose vs build/plan 的区别
**代码层面几乎对称，区别只在 system prompt 和权限**：

| Agent | Prompt | 特殊权限 | 用途 |
|---|---|---|---|
| build | 通用 | 允许 question | 执行工具调用 |
| plan | PROMPT_PLAN | 编辑限制（仅 `.mimocode/plans/`） | 规划阶段 |
| compose | 通用 + compose skills 注入 | 允许 question | 编排工作流 |

**关键真相**：compose **不是**特殊编排逻辑，而是同一个 ReAct 循环 + compose skills 内容注入 system prompt。

### 1.3 核心推理循环
`src/session/prompt.ts`（约 L1814）的 `runLoop`：

```typescript
// 伪代码
while (true) {
  const messages = yield* sessions.messages({ sessionID, agentID })  // 1. 加载历史
  const response = yield* llm.stream({ agent, model, system, messages, tools })  // 2. LLM 推理
  const assistant = yield* sessions.updateMessage(parsedResponse)  // 3. 执行 tool + 记录
  if (classify(response) === "stop") {  // 4. 停止判断
    const needReentry = yield* taskGate(lastUser) || yield* goalGate(lastUser)
    if (!needReentry) break
  }
  // 5. 各种恢复（output-length / invalid-output / text-loop）
}
```

**这就是 ReAct**：LLM 推理 → tool 执行 → 观察 → 再推理。终止条件：taskGate / goalGate / 主动 stop。最大重试 `MAX_GOAL_REACT = 12`。

---

## 2. 15 个内置 Compose Skills

### 2.1 位置
`src/skill/compose/.bundle/`

### 2.2 清单
```
ask/         brainstorm/  debug/       execute/     feedback/
merge/       new-skill/   parallel/    plan/        report/
review/      subagent/    tdd/         verify/      worktree/
```

### 2.3 本质
它们是 **markdown 文件（SKILL.md）**，是写给 LLM 看的"工作流指导说明书"（如 plan skill 是 500+ 行的计划编写指南）。**不含执行逻辑，引擎无关**——喂给任何 ReAct 循环都能用。

### 2.4 加载机制
`src/skill/compose/extract.ts`：编译时打包，运行时解包到 `~/.mimocode/compose/{version}/skills/`，扫描 `**/*.SKILL.md`。

---

## 3. SKILL.md 格式与加载

### 3.1 格式
```markdown
---
name: compose:ask          # 必需：唯一标识，通常 namespace:skillname
description: "..."         # 必需：一句话描述
hidden: true               # 可选：不在列表展示
---

# Skill Title
## Content...
```

### 3.2 加载流程
`src/skill/index.ts`：discovery（发现）→ load（加载）→ parse（用 gray-matter 解析 frontmatter）

### 3.3 目录约定（扫描顺序，后覆盖先）
| 优先级 | 位置 |
|---|---|
| 1 | Builtin |
| 2 | Compose bundle |
| 3 | `~/.opencode/skills/**/SKILL.md`（全局） |
| 4 | `.opencode/skills/**/SKILL.md`（项目级）★ 我们放这里 |
| 5 | `config.skills.paths` |
| 6 | `config.skills.urls` |

---

## 4. Tool 扩展（最关键）

### 4.1 四种方式
| 方式 | 位置 | 语言 | 用途 |
|---|---|---|---|
| A. 项目目录 | `.opencode/tools/*.ts` 或 `tools/*.ts` | TS/JS | 项目级 tool |
| B. Plugin | npm / local file:// | TS/JS + hooks | 打包复用 |
| **C. MCP Server** | via `config.mcp` | **任何语言（含 Python）** | 外部进程 |
| D. 源码扩展 | `src/ext/*.ts` | TS/JS | 改 OpenCode 源码 |

### 4.2 Tool 定义签名（TS）
`src/tool/tool.ts`（约 L38-52）：

```typescript
export interface Def<Parameters extends z.ZodType> {
  id: string
  description: string
  parameters: Parameters          // Zod schema
  execute(args, ctx): Effect      // 执行函数
  shell?: { ... }                 // 可选 shell 模式
}
```

### 4.3 项目目录 tool 加载
`src/tool/registry.ts`（约 L183-203）：扫描 `{tool,tools}/*.{js,ts}`，文件名→namespace。

```
tools/read_pr.ts 导出 default        → tool ID = "read_pr"
tools/github.ts 导出 const extract   → tool ID = "github_extract"
```

---

## 5. MCP —— Python 接入的关键路径

### 5.1 为什么用 MCP
- **语言无关**：Python / Go / Rust 都能写 MCP server
- **进程隔离**：MCP server 独立进程，不拖累 OpenCode
- **复杂逻辑**：Python 数据科学库、LangGraph 编排

### 5.2 配置
`src/config/mcp.ts` 定义了 Local 和 Remote 两种：

```json
// .opencode/mimocode.json
{
  "mcp": {
    "quantcode_tools": {
      "type": "local",
      "command": ["python", "-m", "quantcode.mcp_server"],
      "environment": { "OPENCODE_PROJECT": "./" },
      "enabled": true,
      "timeout": 5000
    },
    "remote_api": {
      "type": "remote",
      "url": "http://localhost:3000/mcp"
    }
  }
}
```

### 5.3 MCP 支持状态
- ✅ Local stdio MCP servers（命令行启动）
- ✅ Remote HTTP MCP servers
- ✅ OAuth 认证
- ✅ 与 Claude Code 的 MCP 配置互通
- ❌ SSE transport（不支持）

### 5.4 Python MCP Server 最小例子
```python
# quantcode/mcp_server.py
from mcp import Server

server = Server("quantcode-tools")

@server.tool()
def read_pr(pr_number: int) -> str:
    """Read GitHub PR diff"""
    return diff_text  # 你的 Python 逻辑

if __name__ == "__main__":
    server.run()  # stdio 监听
```

---

## 6. Plugin 机制

### 6.1 位置
`src/plugin/index.ts` + `packages/plugin`

### 6.2 Plugin 能做什么
1. **提供 tool**（`hooks.tool` 字段）
2. **注册 hooks**（`actor.preStop` / `actor.postStop`）
3. **工作空间适配器**

### 6.3 最小 Plugin
```typescript
export const MyToolPlugin = async (input) => {
  return {
    tool: {
      extract_metadata: {
        description: "Extract metadata from PR",
        args: { pr_url: { type: "string" } },
        execute: async (args, ctx) => ({ output: "result" }),
      }
    }
  }
}
```

---

## 7. Agent（Mode）定义

### 7.1 内置 Agent
`src/agent/agent.ts`：
- **Primary（用户可选）**：build / plan / compose / general
- **Subagent（系统内部）**：explore / dream / distill / checkpoint-writer

### 7.2 Agent 间差异的实现
1. **System Prompt**：每个 agent 可有自定义 `prompt`
2. **Tool 集**：`toolAllowlist` 显式限制
3. **Permission**：每个 agent 有自己的 ruleset
4. **Model**：可指定不同 model/temperature
5. **hardPermission**：不可被覆盖的硬约束（如 plan mode 的写入限制）

### 7.3 自定义 Agent（我们加 model/risk 等组）
可通过配置文件定义，指定 prompt + toolAllowlist + permission。

---

## 8. Permission / 人审机制

### 8.1 位置
`src/permission/index.ts`

### 8.2 三种 action
```typescript
type Action = "allow" | "deny" | "ask"
```

### 8.3 评估流程
1. 先查规则：显式 `deny` 必胜
2. 再查批准状态（用户之前同意过的）
3. 都不是 allow → 发 `Permission.Asked` 事件，**阻塞等用户回复**（once/always/reject）

**关键**：`ask` action 就是人审触发点。非交互式 caller（系统 agent）没人回复 → 直接拒绝。

### 8.4 默认权限例子
```typescript
{
  "*": "allow",
  doom_loop: "ask",              // 死循环时询问
  external_directory: { "*": "ask" },
  read: { "*": "allow", "*.env": "ask" }  // .env 需询问
}
```

---

## 9. Session / State / Memory

### 9.1 Session
`src/session/session.ts`：SQLite 持久化，消息链按序存储，有 `contextWatermark`（compaction 边界）。

### 9.2 Checkpoint
`src/session/checkpoint.ts`：11 段 markdown 模板存到 `~/.mimocode/sessions/{id}/checkpoint.md`（active intent / next action / task tree / learnings / errors / ...）。

### 9.3 Memory
`src/memory/service.ts`：SQLite FTS5 + BM25，四层文件（projects / sessions / tasks / global）。**这跟我们 Day 2 做的一致**。

---

## 10. 落地手册：如果要加 "model 组的 read_pr tool + model compose 流"

### 最小路径
1. **写 tool**：
   - Python：写 `quantcode/mcp_server.py` 暴露 read_pr，配 `.opencode/mimocode.json` 的 mcp
   - 或 TS：写 `.opencode/tools/read_pr.ts`
2. **写 SKILL.md**：`.opencode/skills/model/SKILL.md`（frontmatter + 工作流指导）
3. **配 Agent**（可选）：定义 model 组的 primary agent（prompt + toolAllowlist）
4. **启动验证**：启动 OpenCode → compose 模式 → 输入任务 → 看 Agent 调不调 read_pr

### 是否要改 OpenCode 源码？
**不用**。加配置 + tool + skill + plugin 就行，不碰源码。

### Python 逻辑怎么接？
通过 **MCP server**——这是 Python 写的 tool/编排逻辑接入 OpenCode compose 模式的官方路径。

---

## 11. 未验证的风险点（需要实机测试）

⚠️ 以下是调研没覆盖、需要实际测试的：

1. **本地能否启动 OpenCode**：`vendor/mimo-code/packages/opencode/` 是大工程，`npm run dev` 能否起来、要不要配环境未验证
2. **MCP 连通性**：OpenCode + Python MCP server 能否真的连上、协议版本兼容性未验证
3. **compose 触发交互**：具体输入什么命令触发 compose 调我们的 tool，未实测
4. **LangGraph Agent 如何接入**：我们的编排层是 Python/LangGraph，它作为一个整体怎么接进 OpenCode（是包成一个大 MCP tool？还是 OpenCode 只做前端触发？）需要设计验证

**建议**：先用最简单的 hello_world MCP tool 验证连通性，跑通了再上业务 tool。

---

## 12. 关键文件索引（快速定位）

| 功能 | 文件路径 |
|---|---|
| compose 模式定义 | `src/agent/agent.ts` |
| ReAct 主循环 | `src/session/prompt.ts` |
| 15 个 compose skill | `src/skill/compose/.bundle/` |
| SKILL.md 加载 | `src/skill/index.ts` |
| Tool 定义接口 | `src/tool/tool.ts` |
| Tool 注册 | `src/tool/registry.ts` |
| MCP 配置 | `src/config/mcp.ts` |
| Plugin 机制 | `src/plugin/index.ts` |
| Permission | `src/permission/index.ts` |
| Session | `src/session/session.ts` |
| Checkpoint | `src/session/checkpoint.ts` |
| Memory | `src/memory/service.ts` |

---

**报告维护**：实机验证后，把"未验证风险点"（§11）的结论补回来，更新为确定结论。
