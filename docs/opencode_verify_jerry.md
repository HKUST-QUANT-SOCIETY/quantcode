# OpenCode 落地检验 — 刘炽（strategy / fundamental / options）

> 目标：在 **OpenCode TUI** 里能发现 MCP tools，Agent 能调用并产出合法 artifact。  
> 协议层可先跑 `python3 scripts/test_mcp_groups.py`（不依赖 OpenCode UI）。

---

## 1. 前置

```bash
# 1) 打开 quantcode 仓库（OpenCode 会读根目录 opencode.jsonc）
cd ~/Projects/quantcode-workspace/quantcode

# 2) 安装 Python 依赖（若未装）
pip install -e .

# 3) MCP 多组烟测（必须先绿）
python3 scripts/test_mcp_groups.py
```

预期：strategy / fundamental / options 三组各 `tools/list` 数量正确，`tools/call` 成功。

---

## 2. 启动 OpenCode

```bash
# 在 quantcode 目录启动（或 OpenCode 里 Open Folder 选 quantcode）
cd ~/Projects/quantcode-workspace/opencode
bun run dev
```

在 OpenCode 里：

1. `/connect` — 配置 LLM API Key（Anthropic / OpenAI）
2. 确认项目根目录是 **quantcode**（能看到 `opencode.jsonc`）

---

## 3. MCP 配置说明

`opencode.jsonc` 已注册 4 个 MCP server（按组隔离）：

| MCP 名 | `QUANTCODE_GROUP` | 用途 |
|--------|-------------------|------|
| `quantcode-model` | model | 读 PR / ModelSpec（陈镇鸿主） |
| `quantcode-strategy` | strategy | 你 Day4 strategy 四件套 |
| `quantcode-fundamental` | fundamental | 你 Day4 fundamental 四件套 |
| `quantcode-options` | options | 你 Day3/4 options 三件套 |

OpenCode 启动后日志里应能看到 MCP server 连接成功。

---

## 4. Compose 任务示例（在 OpenCode 输入）

### options 组

```
/compose 为 GC 黄金期权构建波动率曲面：读取 data/sample_options/gc_options_merged_sample.csv，调用 build_vol_surface，再 calc_greeks
```

加载 skill 提示：可引用 `options-compose`（`.opencode/groups/options/skills/options-compose/SKILL.md`）

### strategy 组

```
/compose 从两个因子候选 pb_roe 和 mom20 筛选信号、组合权重、回测，产出 StrategyReport
```

### fundamental 组

```
/compose 对 2097.HK 做时点 2025-01-01 的基本面研究：pit_rag_search → extract_financial → dcf_valuation → render_report
```

---

## 5. 验收 checklist

- [ ] `python3 scripts/test_mcp_groups.py` 全绿
- [ ] OpenCode 启动无 MCP 报错
- [ ] Agent 能调用至少 1 个 quantcode-* MCP tool（日志有 tool_call）
- [ ] 返回 JSON 通过 schema（StrategyReport / ResearchResult / VolSurfaceResult）
- [ ] （可选）截图或录屏给 Lead

---

## 6. 常见问题

| 现象 | 处理 |
|------|------|
| OpenCode 找不到 tool | 确认 cwd 是 quantcode；`python3 -m quantcode.mcp_server` 能手动跑 |
| `python` not found | `opencode.jsonc` 已改为 `python3` |
| 调错组的 tool | 确认用的是 `quantcode-strategy` 等对应 MCP |
| tool 报错 schema | 看 tool description，按 Pydantic 字段传参 |
