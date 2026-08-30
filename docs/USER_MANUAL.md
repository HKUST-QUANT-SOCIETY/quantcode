# QuantCode 用户手册

> **目标用户**：HKUST QUANT SOCIETY 6个业务组的研究员  
> **版本**：v1.1  
> **最后更新**：2026-08-30

---

## 📚 目录

1. [快速开始](#快速开始)
2. [供应商绑定](#供应商绑定桌面端)
3. [Factor组（因子开发）](#factor组因子开发)
4. [Model组（模型建模）](#model组模型建模)
5. [Risk组（风险评估）](#risk组风险评估)
6. [Fundamental组（基本面研究）](#fundamental组基本面研究)
7. [Strategy组（策略构建）](#strategy组策略构建)
8. [Options组（期权定价）](#options组期权定价)
9. [常见问题](#常见问题)

---

## 快速开始

### 前置条件

- QuantCode桌面端已安装并运行
- 你的组账号已配置（联系Agent组获取）

### 启动QuantCode

**方式1：一键启动脚本**（推荐）
```bash
cd /path/to/QUANTcode
./scripts/start-quantcode.sh
```

**方式2：手动启动**（需先完成 LLM 环境变量配置，见 README Quick Start）
```bash
# 1. 启动桌面端
cd opencode && bun run dev:desktop

# 2. 在桌面端中选择你的组
# 3. 开始对话
```

### 基本使用流程

1. **打开QuantCode桌面端** → 看到聊天界面
2. **描述你的任务** → 例如："我想开发一个动量因子"
3. **Agent自动执行** → 调用工具、生成报告
4. **审查结果** → 查看生成的artifact（JSON/PDF/图表）
5. **人工审批**（如需要）→ 风险超阈值时gate面板出现 Approve/Reject 按钮

---

## 供应商绑定（桌面端）

桌面端 **Settings → Providers** 只支持第三方供应商（DeepSeek / StepFun / Kimi / GLM / OpenRouter 等）。官方供应商直连与 OAuth 登录入口已移除。

**绑定步骤**：

1. 打开设置 → Providers → **添加自定义供应商**
2. 填写统一表单：**显示名称** / **Base URL** / **API Key**（三项都必需；Base URL 形如 `https://api.deepseek.com/v1`）
3. 点击 **获取模型列表** 按钮 — 系统实时请求该供应商的 `/models` 接口，拉取可用模型供选择
4. 选中默认模型，保存

绑定完成后，Agent 的 LLM 调用即走该供应商。也可用环境变量方式（`QUANTCODE_API_KEY` / `QUANTCODE_MODEL_PROVIDER` / `QUANTCODE_MODEL_NAME` / `QUANTCODE_MODEL_BASE_URL`），见 README Quick Start。

---

## Factor组（因子开发）

### 你的工作场景

你需要：
1. 提出因子想法
2. 让系统自动匹配主线因子库
3. 生成因子spec
4. 提交AutoEval评估
5. 查看IC/IR/换手率等指标

### 典型对话示例

```
你: 我想开发一个基于营收增速的动量因子，看最近4个季度的营收同比增长率

QuantCode: 
✓ 正在匹配主线因子库...
✓ 找到3个相似因子：revenue_growth_mom, fundamental_momentum, earnings_acceleration
✓ 生成FactorSpec...
✓ 提交AutoEval评估...

评估结果：
- IC均值: 0.045
- IR: 0.8
- 月度换手率: 0.25
- t统计量: 2.5 (显著)

验收判定 (阈值见 runner/acceptance.py)：pass
建议: IC均值与IR达到验收线，可以进入下一步。
```

> **注意**：以上为示例数字。实际指标来自 AutoEval 评估（API 不可用时降级为 mock 数据并明确标注 `_is_mock`），是否通过以 `runner/acceptance.py` 的验收阈值判定为准（|ic_mean| ≥ 0.03、ir ≥ 0.5、turnover ≤ 0.8、t_stat ≥ 2.0）。

### 关键工具

| 工具 | 用途 | 何时调用 |
|---|---|---|
| `match_main` | 匹配主线因子库 | 提出因子想法时自动 |
| `gen_schema` | 生成FactorSpec | 匹配后自动 |
| `autoeval` | 提交AutoEval评估 | FactorSpec生成后自动 |

### 输出Artifact

- `artifacts/factor/{factor_name}-report.json` — AutoEval评估报告（含 IC/IR/turnover 与验收判定）

### 常见问题

**Q: AutoEval评估需要多久？**  
A: 取决于因子复杂度与 API 状态。若 AutoEval 服务不可用，工具会降级返回 mock 数据并标注 `_is_mock`，请据此判断结果可信度。

**Q: IC均值低于0.03还有价值吗？**  
A: 验收判定（`runner/acceptance.py`）会返回 fail。可以综合 IR / t统计量人工判断是否继续优化，但当前不会进入合并流程（`merge_to_main` 尚未实现，合并/拒绝由人工决策）。

**Q: 如何修改因子定义？**  
A: 直接告诉Agent："修改因子公式，改用EPS增速替代营收增速"

---

## Model组（模型建模）

### 你的工作场景

你需要：
1. 提交PR到模型仓库
2. 自动触发风控评估
3. 等待风控组审批（如超阈值）
4. 合并PR

### 典型对话示例

```
你: 我提交了PR#42，请帮我跑风控评估

QuantCode:
✓ 读取PR#42...
✓ 提取模型元数据...
✓ 生成ModelSpec并写入Blackboard...
✓ 触发risk组flow...

[自动切换到risk组Agent]
✓ 计算风险指标...
✓ 生成RiskProfile...
⚠️ HumanGate触发：max_drawdown (0.22) 超过阈值 (0.15)

等待风控组审批...
```

### 关键工具

| 工具 | 用途 |
|---|---|
| `read_pr` | 读取GitHub PR信息 |
| `extract_metadata` | 从diff提取模型元数据 |
| `generate_model_spec` | 生成ModelSpec |
| `write_blackboard` | 写入共享状态（触发risk组） |

### 跨组协作

Model → Risk 自动handoff：
1. 你提交PR
2. Model Agent生成ModelSpec
3. 写入Blackboard（PROJECT scope）
4. Risk Agent自动读取并评估
5. 风控报告自动写回PR评论

### 常见问题

**Q: PR评论多久出现？**  
A: 通常5分钟内。检查GitHub Actions状态。

**Q: 风控拒绝了我的PR怎么办？**  
A: 查看RiskProfile中的`breached_limits`，调整模型参数后重新提交。

---

## Risk组（风险评估）

### 你的工作场景

你需要：
1. 审查模型组提交的PR
2. 查看自动生成的RiskProfile
3. 人工审批超阈值的模型

### 典型对话示例

```
你: 查看待审批的风控gate

QuantCode:
找到1个待审批项目：

PR#42 - ML因子优化 (model组提交)
- max_drawdown: 0.22 (阈值: 0.15) ❌
- tail_risk_var_99: 0.085 (阈值: 0.05) ❌
- position_limit: 0.92 (阈值: 0.8) ❌

你的决定？[approve/reject]

你: approve, 但要求降低position_limit到0.85

QuantCode:
✓ 审批通过
✓ 已在PR#42添加评论：风控批准，需调整position_limit≤0.85
```

### 关键工具

| 工具 | 用途 |
|---|---|
| `read_blackboard` | 读取Model组写入的ModelSpec |
| `calc_risk` | 计算风险指标 |
| `generate_risk_profile` | 生成RiskProfile |
| `check_gate` | 检查是否超阈值 |
| `write_pr_comment` | 写GitHub PR评论 |

### HumanGate机制

**何时触发**：任一风险指标超过阈值  
**如何审批（桌面gate面板）**：
1. Agent暂停，gate面板显示RiskProfile（含 risk_metrics、reasons、thread_id）
2. 点击面板上的 **Approve** 或 **Reject** 按钮 → 自动以 resume 方式恢复该会话
3. Agent继续执行或终止

（命令行等价操作：`python scripts/replay.py resume --decision approve`）

**阈值配置**：默认阈值内置于 `schemas/risk_profile.py` 的 `RiskThresholds`（max_drawdown/VaR/position_limit 等，如 max_drawdown 0.15）；factor/risk 验收阈值与默认值统一见 `runner/acceptance.py`。

---

## Fundamental组（基本面研究）

### 你的工作场景

你需要：
1. 研究某个公司/行业
2. 查找历史研报（point-in-time safe）
3. 提取财务数据
4. 生成DCF估值
5. 输出专业PDF研报

### 典型对话示例

```
你: 帮我研究腾讯控股(0700.HK)，生成DCF估值和投资建议

QuantCode:
✓ PIT RAG检索历史研报 (截止2026-Q2)...
✓ 提取财务数据 (营收/利润/现金流)...
✓ DCF估值计算...
  - WACC: 8.5%
  - 永续增长率: 3%
  - 估值: HK$ 485/股
  - 当前价: HK$ 420/股
  - 上涨空间: 15.5%
✓ 生成PDF研报...

研报已保存: artifacts/research/0700_HK_research_20260716.md（Typst 环境可用时渲染 PDF，否则降级 markdown）
```

### 关键工具

| 工具 | 用途 |
|---|---|
| `pit_rag_search` | Point-in-time安全的研报检索 |
| `extract_financial` | 提取财务数据 |
| `dcf_valuation` | DCF估值计算 |
| `render_report` | 生成PDF研报 |

### Point-in-Time安全

**什么是PIT**：确保回测时不使用"未来信息"  
**如何实现**：Chroma向量库+时间戳过滤  
**示例**：2023-01-01回测时，只检索2022-12-31前的研报

---

## Strategy组（策略构建）

### 你的工作场景

你需要：
1. 选择信号（因子/模型）
2. 组合优化（权重分配）
3. 回测验证
4. 上线部署

### 典型对话示例

```
你: 用momentum和value两个因子构建策略，月度调仓

QuantCode:
✓ 筛选可用信号...
✓ 组合优化 (最大化夏普比率)...
  - momentum权重: 60%
  - value权重: 40%
✓ 回测 (2020-2026)...
  - 年化收益: 18.5%
  - 夏普比率: 2.1
  - 最大回撤: 12.3%
✓ 生成StrategyReport...

是否部署到生产环境？[yes/no]
```

### 关键工具

| 工具 | 用途 |
|---|---|
| `select_signals` | 筛选因子/模型 |
| `combine_signals` | 组合优化 |
| `run_strategy_backtest` | 回测 |
| `deploy_strategy` | 部署（需HumanGate） |

### 风险控制

**部署前检查**：
- 夏普比率 > 1.5
- 最大回撤 < 20%
- IC稳定性（无显著衰减）

**HumanGate**：`deploy_strategy`总是需要人工批准

---

## Options组（期权定价）

### 你的工作场景

你需要：
1. 构建波动率曲面
2. 计算Greeks
3. 期权组合回测

### 典型对话示例

```
你: 构建标普500期权的波动率曲面，计算ATM期权的Greeks

QuantCode:
✓ 获取期权链数据...
✓ 构建波动率曲面 (SABR模型)...
✓ 计算Greeks (ATM, 30天到期)...
  - Delta: 0.52
  - Gamma: 0.08
  - Vega: 18.5
  - Theta: -0.35
✓ 生成可视化图表...

曲面已保存: artifacts/options/{symbol}_vol_surface.png（示例路径）
```

### 关键工具

| 工具 | 用途 |
|---|---|
| `build_vol_surface` | 构建波动率曲面 |
| `calc_greeks` | 计算Greeks |
| `run_options_backtest` | 期权策略回测 |

---

## 常见问题

### 通用问题

**Q: 如何查看历史对话？**  
A: QuantCode自动保存所有对话，在侧边栏选择"历史会话"

**Q: Agent卡住不动了怎么办？**  
A: 1) 等待30秒；2) 如仍卡住，点击"停止"按钮；3) 联系Agent组

**Q: 如何修改工具配置？**  
A: 只有Agent组可以修改。如有需求，提Issue到GitHub仓库。

**Q: 生成的artifact在哪里？**  
A: `artifacts/{你的组}/` 目录下（如 factor 报告在 `artifacts/factor/{name}-report.json`、fundamental 研报在 `artifacts/research/`）

**Q: 如何查看最近运行情况？**  
A: 会话内打开桌面端 Monitor 面板，或让 Agent 调用只读 `list_runs` 工具（数据源 `.quantcode/metrics.jsonl`）。

### 错误排查

**错误：Tool 'xxx' not found**  
原因：你的组没有权限使用该工具  
解决：检查你是否登录到正确的组账号

**错误：API key未配置**  
原因：`QUANTCODE_API_KEY` 环境变量未设置，或桌面供应商绑定未填 API Key  
解决：设置环境变量（见 README Quick Start）或重新完成供应商绑定

**错误：卡在等待人工审批**  
原因：风控gate触发 waiting for human  
解决：在桌面gate面板点击 Approve/Reject，或用 `python scripts/replay.py resume --decision approve|reject` 恢复

---

## 获取帮助

- **技术支持**：Agent组 (Slack: #quantcode-support)
- **功能建议**：GitHub Issues
- **紧急问题**：Hendrix Chen (chenyuanheng0127@gmail.com)

---

**提示**：本手册假设你已经有量化投研背景。IC/IR/DCF 等术语解释为示例性简述，实际指标口径以 `schemas/` 下的 Pydantic 模型字段与 `runner/acceptance.py` 验收逻辑为准。
