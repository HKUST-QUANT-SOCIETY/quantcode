# OpenCode 落地检验 — QuantCode v5

> 本文已按 v5 更新。组身份来自 SSH roster Session Context；不要通过选择
> 不同 MCP server 或传入 `QUANTCODE_GROUP` 在生产环境切组。

> 目标：在 **OpenCode TUI** 里能发现 MCP tools，Agent 能调用并产出合法 artifact。  
> 协议层可先跑 `python3 scripts/test_mcp_groups.py`（不依赖 OpenCode UI）。

---

## 1. 前置

```bash
# 1) 打开 quantcode 仓库（OpenCode 会读根目录 opencode.jsonc）
cd ~/Projects/quantcode-workspace/quantcode

# 2) 安装 Python 依赖（若未装）
uv sync --extra dev

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

`opencode.jsonc` 只注册一个 `quantcode` MCP server。生产会话必须由桌面
SSH Agent/Keychain bridge 注入 `QUANTCODE_SSH_KEY_FINGERPRINT`，服务端再从
`.opencode/authorized_groups.yaml` roster 签发 actor、组、角色和工作目录。
未命中 roster 时服务端按 v5 规则 fail-closed。

本地离线协议烟测可以显式使用：

```bash
QUANTCODE_ENV=development QUANTCODE_GROUP=factor \
  python3 scripts/test_mcp_client.py
```

---

## 4. Compose 任务示例（在 OpenCode 输入）

### options 组

以下任务在已认证的 options Session Context 中执行；任务文本不负责切组。

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

- [ ] `python3 scripts/test_mcp_client.py` 全绿（协议层）
- [ ] OpenCode 启动无 MCP 报错
- [ ] Agent 能调用至少 1 个 `quantcode` MCP tool（日志有 tool_call）
- [ ] 返回 JSON 通过 schema（StrategyReport / ResearchResult / VolSurfaceResult）
- [ ] （可选）截图或录屏给 Lead

---

## 6. 常见问题

| 现象 | 处理 |
|------|------|
| OpenCode 找不到 tool | 确认 `QUANTCODE_ROOT` 指向 QuantCode；`python3 -m quantcode.mcp_server` 能手动跑 |
| `python` not found | `opencode.jsonc` 已改为 `python3` |
| 组身份不对 | 检查 SSH roster 指纹和当前 Session Context；不要用任务参数切组 |
| tool 报错 schema | 看 tool description，按 Pydantic 字段传参 |
