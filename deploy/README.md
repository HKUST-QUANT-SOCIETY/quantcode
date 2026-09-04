# QuantCode 三机部署拓扑（G3-B1 首期文档落地）

> v1（2026-09-01）。依据 `docs/audit/ROADMAP_LONGTERM.md` Q2 G3-B1：A=dev/CI，B=主线+模拟盘 cron，C=对外+凭据宿主。本文是规划文档，不含任何真实凭据。

## 共同约定

- **凭据规则**：MCP 主链路只读 `QUANTCODE_*` 环境变量（`quantcode/mcp_server.py`、`runner/agent_mcp_tool.py`），不读仓库内配置文件明文密钥。凭据经 systemd `EnvironmentFile` 注入（模板见 `deploy/quantcode.service.example`，文件内只写路径不写值）。
- 现有 `QUANTCODE_*` 面：`QUANTCODE_GROUP` / `QUANTCODE_GROUPS` / `QUANTCODE_API_KEY` / `QUANTCODE_MODEL_PROVIDER` / `QUANTCODE_MODEL_NAME` / `QUANTCODE_MODEL_BASE_URL` / `QUANTCODE_ALLOW_UNAUTH` / `QUANTCODE_SSH_KEY_FINGERPRINT`（别名 `QUANTCODE_SSH_FINGERPRINT`）/ `QUANTCODE_TOKEN_BUDGET` / `QUANTCODE_CONFIG_DIR` / `QUANTCODE_PERMISSIONS_FILE` / `QUANTCODE_EVIDENCE_DIR` / `QUANTCODE_MAINLINE_CACHE` / `QUANTCODE_CONTEXT_TOKENS` / `QUANTCODE_TASKS` / `QUANTCODE_POST_RISK_COMMENT`。
- 本地运行态目录（相对仓库根）：`.quantcode/metrics.jsonl`（F-09 metrics）、`.quantcode/evidence/*.jsonl`（审计）、`.quantcode/memory/`（FTS5）、`.quantcode/distill_candidates/`（dream 蒸馏草案）。
- **备份**：各机每夜备份 `/srv/quant/backups/`，含 `.quantcode/` 运行态 + configs/；恢复口径=整目录回滚 + 重启 unit。
- MCP 入口为 stdio（`python -m quantcode.mcp_server`），无端口；带 HTTP 面（qs-data 只读服务 / 对外 API）时单独开端口并过安全域名清单。

## Server A：qs-data-ingest（开发 / CI + qs-data 只读数据服务规划）

- **角色**：CI 跑 pytest（当前基线 1025 passed，4 skipped）；qs-cold staging 勘察副本宿主（`/srv/quant/data/migration-staging/...`，见 `specs/data/SPEC.md` §2.1）；Q2 D2a 起加挂 qs-data 只读服务（group 粒度 key，LLM/L1 沙箱只经 market tool 访问）。
- **服务**：CI runner；qs-data 只读 HTTP 服务（D2a，未落地，占位）；不跑对外服务、不放凭据。
- **端口**：CI 无对外常驻端口；D2a 落地时仅内网段开放只读端口（规划，端口号定案时回填）。
- **凭据注入面**：CI secret 侧注入 runner 环境；机器上不落明文文件。
- **备份**：`/srv/quant/backups/`（staging 副本可由 COS 桶重建，备份以 selected_pool/index.json 治理件优先）。
- **红线**：本机是 `server A qs-data-ingest` 的 qs-cold 只读代理，不做写入/回算。

## Server B：qs-compute（主线代码 + 模拟盘 cron）

- **角色**：主线仓库唯一可写副本 + Multi-Agent 研究执行 + dream 消费端 + 模拟盘持续监控（Q2 G1-L2 cron 阈值扫描，占位）。
- **服务**：
  - `quantcode-mcp.service`：`python -m quantcode.mcp_server`（stdio，lens UI 会话拉起或常驻）。
  - `quantcode-dream.service`+timer：`python -m dream.cli` / `python scripts/dream_consume.py --interval 300`（tail `.quantcode/evidence/*.jsonl` → distill → judge RLHF）。
  - 模拟盘 cron（G1-L2，占位）：定时跑组 run + `runner/metrics.py` 阈值扫描，模板复用 `deploy/quantcode.service.example` 换 ExecStart；Timer 定案时不改 unit 文字、用 `*.timer` 挂。
- **端口**：全部 stdio/本地文件，无监听端口。
- **凭据注入面**：`EnvironmentFile=/etc/quantcode/quantcode.env`（root:0600）——模型供应商三件套（`QUANTCODE_API_KEY` / `QUANTCODE_MODEL_PROVIDER` / `QUANTCODE_MODEL_NAME` / `QUANTCODE_MODEL_BASE_URL`）+ 组/身份（`QUANTCODE_GROUP`、`QUANTCODE_SSH_KEY_FINGERPRINT`）。COS 凭据解锁前不落机（ROADMAP 风险表：本地 staging 先行）。
- **备份**：`/srv/quant/backups/`，优先 `.quantcode/memory/`、`evidence/`、`metrics.jsonl`、`distill_candidates/`。

## Server C：qs-gpu（对外服务 + 凭据宿主）

- **角色**：对外服务边界（A5 本地模型路由的小模型推理规划）+ G4-C1 Secret 管理宿主（注入 + 90 天轮换，Q3 规划）。
- **服务**：模型推理服务（A5，占位）；Secret 服务（G4-C1，占位）。
- **凭据注入面**：COS / API 凭据唯一宿主；其他两机经 `QUANTCODE_*` 环境变量按需注入，禁止另存副本。轮换=改 C 侧 secret → 重启 B 侧 unit 读新 env。
- **备份**：`/srv/quant/backups/`（仅 secret 密文与轮换审计记录，密钥材料按 G4-C1 规则另行管理）。
- **容器化**：对外推理面用 docker compose（占位，未编写 compose 文件；Q3 随 R7 qs-data 服务化一并定案）。

## 落地清单（首次部署顺序）

1. B 机：`python -m venv .venv && pip install -e .`，复制 `deploy/quantcode.service.example` → `/etc/systemd/system/quantcode-mcp.service`，先建 `/etc/quantcode/quantcode.env`（0600，只写 `QUANTCODE_*` 键值）再 `systemctl daemon-reload`。
2. A 机：CI 接 pytest 门禁；qs-cold staging 只读挂载。
3. C 机：等 G4-C1 定案后启用，先只作凭据宿主不跑业务。
4. 三机各建 `/srv/quant/backups/` + cron 每夜打包（`tar -czf /srv/quant/backups/quantcode-$(date +%F).tgz .quantcode configs`）。
