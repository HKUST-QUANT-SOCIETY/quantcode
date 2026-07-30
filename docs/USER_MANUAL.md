# QuantCode 用户手册

> **目标用户**：HKUST QUANT SOCIETY 6个业务组的研究员  
> **版本**：v1.0  
> **最后更新**：2026-07-16

---

## 📚 目录

1. [快速开始](#快速开始)
2. [Factor组（因子开发）](#factor组因子开发)
3. [Model组（模型建模）](#model组模型建模)
4. [Risk组（风险评估）](#risk组风险评估)
5. [Fundamental组（基本面研究）](#fundamental组基本面研究)
6. [Strategy组（策略构建）](#strategy组策略构建)
7. [Options组（期权定价）](#options组期权定价)
8. [常见问题](#常见问题)

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

**方式2：手动启动**
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
5. **人工审批**（如需要）→ 风险超阈值时会暂停等待你的批准

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
- IC均值: 0.042
- IR: 1.85
- 月度换手率: 15.3%
- t统计量: 4.23 (显著)

建议: IC稳定，IR较高，可以进入回测阶段。
```

### 关键工具

| 工具 | 用途 | 何时调用 |
|---|---|---|
| `match_main` | 匹配主线因子库 | 提出因子想法时自动 |
| `gen_schema` | 生成FactorSpec | 匹配后自动 |
| `autoeval` | 提交AutoEval评估 | FactorSpec生成后自动 |

### 输出Artifact

- `artifacts/factor/{factor_name}_spec.json` — FactorSpec定义
- `artifacts/factor/{factor_name}_eval.json` — AutoEval评估结果

### 常见问题

**Q: AutoEval评估需要多久？**  
A: 通常2-5分钟。如果超过10分钟请联系Agent组。

**Q: IC<0.03是否值得继续？**  
A: 需要综合IR和t统计量判断。IR>1.5且t>3.0仍有价值。

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
**如何审批**：
1. Agent暂停并显示RiskProfile
2. 你输入`approve`或`reject`
3. Agent继续执行或终止

**阈值配置**：`pipelines/risk_gate/config.yaml`

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

研报已保存: artifacts/fundamental/0700_HK_research_20260716.pdf
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

曲面已保存: artifacts/options/SPX_vol_surface_20260716.png
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
A: `artifacts/{你的组}/` 目录下，按日期和任务ID组织

**Q: 如何分享结果给团队？**  
A: Artifact路径可以直接发到Slack，或使用`/export`命令导出为压缩包

### 错误排查

**错误：Tool 'xxx' not found**  
原因：你的组没有权限使用该工具  
解决：检查你是否登录到正确的组账号

**错误：API key未配置**  
原因：config.json缺失或格式错误  
解决：联系Agent组重新配置

**错误：HumanGate超时**  
原因：24小时内未审批  
解决：重新运行任务并及时审批

---

## 获取帮助

- **技术支持**：Agent组 (Slack: #quantcode-support)
- **功能建议**：GitHub Issues
- **紧急问题**：Hendrix Chen (chenyuanheng0127@gmail.com)

---

**提示**：本手册假设你已经有量化投研背景。如果对某个术语不理解（如IC/IR/DCF），请参考`docs/GLOSSARY.md`。
