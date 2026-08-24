# QuantCode 测试人员操作手册

> **目的**：指导测试人员从源码启动和测试 QuantCode 桌面端
> **受众**：QA测试人员、产品经理、演示准备者
> **最后更新**：2026-07-15（Lead）

> 本手册描述开发与 QA 的源码测试环境。当前 GitHub Actions 已构建 macOS、Windows 和 Linux x64 的 unsigned 安装 artifact；它们仅用于 QA 验证，尚不是已签名、可向组员分发的正式 Release。

---

## 📋 目录

1. [环境准备](#1-环境准备)
2. [启动桌面端](#2-启动桌面端)
3. [基础功能测试](#3-基础功能测试)
4. [6组Agent测试](#4-6组agent测试)
5. [HumanGate测试](#5-humangate测试)
6. [常见问题排查](#6-常见问题排查)
7. [测试检查清单](#7-测试检查清单)

---

## 1. 环境准备

### 1.1 检查系统要求

**操作系统**：
- macOS 10.15+
- Windows 10+
- Linux (Ubuntu 20.04+，用于源码开发与 CI 安装包测试；当前可生成 unsigned x64 artifact，正式 Release 待签名验收)

**软件依赖**：
- Node.js 18+ / Bun 1.0+
- Python 3.12+
- Git

### 1.2 验证环境

打开终端，运行以下命令：

```bash
# 检查Python版本
python --version
# 应该显示: Python 3.12.x

# 检查Bun版本
bun --version
# 应该显示: 1.x.x

# 检查Git
git --version
# 应该显示: git version 2.x.x
```

### 1.3 获取代码

```bash
# 进入工作目录
cd ~/Desktop/私募

# 确认两个仓库都存在
ls -d QUANTcode opencode
# 应该看到两个目录

# 更新代码到最新
cd QUANTcode
git pull origin main

cd ../opencode
git checkout feat/quantcode-day5-ui
git pull origin feat/quantcode-day5-ui
```

### 1.4 安装依赖

#### Python依赖（QUANTcode）

```bash
cd ~/Desktop/私募/QUANTcode

# 安装quantcode包
pip install -e .

# 验证安装
python -c "import quantcode; print('✅ QuantCode安装成功')"
```

#### Node依赖（OpenCode）

```bash
cd ~/Desktop/私募/opencode

# 安装依赖
bun install

# 这会自动安装Electron和其他依赖
# 安装完成后应该看到: "installed electron@43.x.x with binaries"
```

### 1.5 配置API密钥

#### 配置DeepSeek API

```bash
cd ~/Desktop/私募/QUANTcode

# 复制配置模板
cp config.example.json config.json

# 编辑配置文件
nano config.json
# 或使用你喜欢的编辑器: code config.json / vim config.json
```

修改`config.json`中的API key：

```json
{
  "llm": {
    "provider": "deepseek",
    "api_key": "sk-你的真实API密钥",  // ← 修改这里
    "model": "deepseek-chat",
    "base_url": "https://api.deepseek.com/v1",
    "temperature": 0.0,
    "max_tokens": 4096
  }
}
```

**获取API密钥**：
- 访问 https://platform.deepseek.com/
- 登录后在"API Keys"页面创建

#### 配置OpenCode

```bash
cd ~/Desktop/私募/opencode

# 编辑配置
nano opencode.local.jsonc
```

确认`PYTHONPATH`正确指向QUANTcode目录：

```jsonc
{
  "mcp": {
    "quantcode": {
      "environment": {
        "QUANTCODE_GROUP": "factor",
        "PYTHONPATH": "/Users/你的用户名/Desktop/私募/QUANTcode"  // ← 确认路径正确
      }
    }
  }
}
```

---

## 2. 启动桌面端

### 2.1 方式1：一键启动脚本（推荐）

创建启动脚本，方便后续使用：

```bash
cd ~/Desktop/私募/opencode

# 创建启动脚本
cat > start-quantcode.sh << 'EOF'
#!/bin/bash
echo "🚀 启动QuantCode桌面端..."

# 检查依赖
if ! command -v bun &> /dev/null; then
    echo "❌ Bun未安装，请先安装: curl -fsSL https://bun.sh/install | bash"
    exit 1
fi

# 检查Electron
if [ ! -d "node_modules/electron" ]; then
    echo "📦 安装Electron..."
    bun add -d electron
fi

# 启动桌面端
echo "✅ 启动中，请稍候..."
bun run dev:desktop
EOF

# 添加执行权限
chmod +x start-quantcode.sh

# 启动
./start-quantcode.sh
```

### 2.2 方式2：手动启动

```bash
cd ~/Desktop/私募/opencode

# 启动桌面端
bun run dev:desktop
```

### 2.3 验证启动成功

启动后，你应该看到：

```
$ bun run script/dev-quantcode.ts desktop
$ bun --cwd packages/desktop dev
...
$ electron-vite dev
vite v7.1.4 building for development...
✓ built in 1234ms
```

**最后会自动打开 Electron 窗口**，页签、启动态和错误页都应显示 QuantCode；如果仍显示 OpenCode，说明启动的不是 `dev:desktop` QuantCode channel，或浏览器标签页仍保留旧文档，需强制刷新。

如果窗口没有自动打开，检查终端是否有错误信息。

---

## 3. 基础功能测试

### 3.1 界面检查

打开桌面端后，应该看到：

1. **主窗口**：
   - 左侧：文件树
   - 中间：对话区域
   - 右侧：侧边栏（可能默认折叠）

2. **右侧面板**（点击右上角图标展开）：
   - 应该能看到多个Tab
   - 找到**"QuantCode"** Tab

### 3.2 QuantCode Tab验证

点击"QuantCode" Tab，应该看到：

```
┌─────────────────────────────┐
│ QuantCode Control Panel     │
├─────────────────────────────┤
│ 📊 Session Info             │
│   Thread ID: [当前线程]     │
│   Group: [当前组]           │
├─────────────────────────────┤
│ 🎯 Agent Status             │
│   Status: idle              │
├─────────────────────────────┤
│ ⚙️ Tools                    │
│   [工具列表]                │
└─────────────────────────────┘
```

**检查项**：
- [ ] QuantCode Tab可见
- [ ] Session Info正确显示
- [ ] Tools列表非空

### 3.3 MCP连接测试

在主对话区输入：

```
/tools
```

应该返回可用工具列表，类似：

```
Available tools:
- match_main: Given a factor idea, return matching fields
- gen_schema: Generate a FactorSpec dict
- autoeval: Submit a FactorSpec to AutoEval
```

**检查项**：
- [ ] `/tools`命令返回工具列表
- [ ] 至少有3个工具（当前组的工具）

---

## 4. 6组Agent测试

### 4.1 Factor组测试（推荐第一个测试）

#### 测试场景：生成PB-ROE因子

**步骤1**：确认当前组为factor

```bash
# 在终端检查opencode.local.jsonc
grep "QUANTCODE_GROUP" ~/Desktop/私募/opencode/opencode.local.jsonc
# 应该显示: "QUANTCODE_GROUP": "factor"
```

如果不是factor，修改配置并重启桌面端。

**步骤2**：在对话区输入：

```
/compose 生成PB-ROE季度再平衡因子
```

**期望行为**：

1. **第1步**：调用`match_main`
   ```
   🤖 Calling tool: match_main
   Arguments: {"idea": "PB-ROE季度再平衡因子"}
   
   ✅ Result:
   {
     "compatible": true,
     "suggested_fields": ["pb", "roe"],
     "notes": "..."
   }
   ```

2. **第2步**：调用`gen_schema`
   ```
   🤖 Calling tool: gen_schema
   Arguments: {
     "idea": "PB-ROE季度再平衡因子",
     "match_result": {...}
   }
   
   ✅ Result:
   {
     "name": "pb_roe_quarterly",
     "formula": "pb * roe",
     ...
   }
   ```

3. **第3步**：调用`autoeval`
   ```
   🤖 Calling tool: autoeval
   Arguments: {"spec": {...}}
   
   ✅ Result:
   {
     "ic_mean": 0.045,
     "ir": 0.8,
     ...
   }
   ```

4. **最终回复**：
   ```
   ✅ 因子PB-ROE季度再平衡已生成。
   
   评估结果：
   - IC均值：0.045
   - 信息比率：0.8
   - T统计量：2.5
   
   该因子通过验收标准。
   ```

**检查项**：
- [ ] Agent自主推理≥3步
- [ ] 每步工具调用成功
- [ ] 最终返回评估结果
- [ ] QuantCode Tab显示更新

**预计耗时**：30-60秒

---

### 4.2 Risk组测试

#### 测试场景：高风险模型审批（HumanGate）

**步骤1**：修改配置切换到risk组

```bash
cd ~/Desktop/私募/opencode

# 修改opencode.local.jsonc
sed -i '' 's/"QUANTCODE_GROUP": "factor"/"QUANTCODE_GROUP": "risk"/' opencode.local.jsonc

# 重启桌面端
# Ctrl+C停止，然后重新运行: ./start-quantcode.sh
```

**步骤2**：在对话区输入：

```
/compose 评估高杠杆模型：max_leverage=5.0
```

**期望行为**：

1. **Agent开始推理**
2. **调用calc_risk工具**
3. **调用check_gate工具**
4. **触发HumanGate暂停**：
   ```
   ⚠️ Human approval required
   
   Risk metrics exceed threshold:
   - Max leverage: 5.0 (threshold: 3.0)
   
   Thread ID: risk-gate-001
   
   Please approve or reject this model.
   ```

5. **QuantCode Tab更新**：
   - Status变为`pending_human`
   - 显示Approve/Reject按钮

**步骤3**：点击"Approve"按钮

**期望行为**：
- Agent恢复执行
- 调用`write_pr_comment`
- 返回最终结果

**检查项**：
- [ ] Agent正确暂停
- [ ] QuantCode Tab显示暂停状态
- [ ] Approve按钮可用
- [ ] 点击后成功恢复
- [ ] 最终写入PR评论

**预计耗时**：45-90秒（包括人工交互）

---

### 4.3 Model组测试

#### 测试场景：读取PR并触发风控

**步骤1**：切换到model组（参考4.2的方式）

**步骤2**：配置GitHub token（如果还没有）

```bash
# 设置GitHub token
export GITHUB_TOKEN="ghp_你的token"

# 或写入配置
echo 'export GITHUB_TOKEN="ghp_你的token"' >> ~/.bashrc
source ~/.bashrc
```

**获取GitHub token**：
- 访问 https://github.com/settings/tokens
- 创建Personal Access Token
- 勾选`repo`权限

**步骤3**：在对话区输入：

```
/compose 读取PR #29并评估风险
```

**期望行为**：

1. 调用`read_pr`读取PR
2. 调用`extract_metadata`提取模型信息
3. 调用`trigger_risk_flow`触发risk组
4. 返回结果：
   ```
   ✅ PR #29已读取
   
   模型信息：
   - 名称：momentum_arb
   - 最大杠杆：3.5
   
   已触发risk组评估，thread_id: risk-gate-002
   ```

**检查项**：
- [ ] 成功读取PR
- [ ] 提取模型元数据
- [ ] 触发risk组（Blackboard写入）
- [ ] 跨组链路工作

---

### 4.4 Strategy/Fundamental/Options组

这三组使用相同的测试流程：

```bash
# 切换到对应组
# 修改opencode.local.jsonc中的QUANTCODE_GROUP

# 重启桌面端

# 测试命令
/compose [测试场景]
```

**测试场景建议**：

| 组 | 测试命令 | 期望结果 |
|---|---------|---------|
| strategy | `/compose 从因子池选择pb_roe和mom20组合回测` | 调用select_signals → combine_signals → backtest |
| fundamental | `/compose 对贵州茅台进行DCF估值` | 调用pit_rag_search → dcf_valuation |
| options | `/compose 构建SPX波动率曲面` | 调用build_vol_surface → calc_greeks |

---

## 5. HumanGate测试

HumanGate是关键功能，需要重点测试。

### 5.1 触发条件

HumanGate在以下情况触发：

1. **高杠杆**：`max_leverage > 3.0`
2. **高回撤**：`max_drawdown > 0.2`
3. **高VaR**：`var_95 > 0.1`

### 5.2 完整测试流程

**步骤1**：确保在risk组

**步骤2**：输入高风险场景

```
/compose 评估极端风险模型：max_leverage=10.0, max_drawdown=0.3
```

**步骤3**：观察暂停行为

应该看到：
```
⚠️ Human approval required

Risk Assessment:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
❌ Max Leverage: 10.0 (threshold: 3.0)
❌ Max Drawdown: 0.30 (threshold: 0.20)

Thread ID: risk-gate-003

⏸️  Agent paused, waiting for decision...
```

**步骤4**：检查QuantCode Tab

应该显示：

```
┌─────────────────────────────┐
│ 🚨 Human Gate Active        │
├─────────────────────────────┤
│ Thread: risk-gate-003       │
│ Status: pending_human       │
│                             │
│ Risk Violations:            │
│ • Max Leverage: 10.0 > 3.0  │
│ • Max Drawdown: 30% > 20%   │
├─────────────────────────────┤
│ [Approve]  [Reject]         │
└─────────────────────────────┘
```

**步骤5**：测试Approve

点击"Approve"按钮，应该看到：
- 按钮变为loading状态
- Agent恢复执行
- 调用后续工具（如write_pr_comment）
- 最终完成

**步骤6**：测试Reject（可选）

重新触发同样的场景，这次点击"Reject"：
- Agent应该终止执行
- 返回rejected状态
- 不调用后续工具

**检查项**：
- [ ] 高风险正确触发暂停
- [ ] QuantCode Tab正确显示状态
- [ ] Approve按钮工作
- [ ] Reject按钮工作
- [ ] thread_id正确传递

---

## 6. 常见问题排查

### 6.1 桌面端无法启动

**症状**：运行`bun run dev:desktop`后报错

**排查步骤**：

1. **检查Electron是否安装**
   ```bash
   cd ~/Desktop/私募/opencode
   ls node_modules/electron
   ```
   
   如果不存在：
   ```bash
   bun add -d electron
   ```

2. **检查端口占用**
   ```bash
   lsof -i :5173
   ```
   
   如果占用，杀掉进程：
   ```bash
   kill -9 [PID]
   ```

3. **清理缓存重试**
   ```bash
   rm -rf node_modules
   bun install
   bun run dev:desktop
   ```

---

### 6.2 MCP连接失败

**症状**：`/tools`命令返回空或报错

**排查步骤**：

1. **检查PYTHONPATH**
   ```bash
   cd ~/Desktop/私募/opencode
   grep PYTHONPATH opencode.local.jsonc
   ```
   
   确认路径正确指向QUANTcode目录。

2. **测试MCP Server手动启动**
   ```bash
   cd ~/Desktop/私募/QUANTcode
   QUANTCODE_GROUP=factor python -m quantcode.mcp_server
   ```
   
   应该启动stdin/stdout模式，等待输入。
   按Ctrl+C退出。

3. **检查工具注册**
   ```bash
   QUANTCODE_GROUP=factor python -c "
   import tools.factor._register
   from tools.registry import get_registry
   print('Registered tools:', get_registry().list())
   "
   ```
   
   应该显示至少3个factor工具。

---

### 6.3 Agent不推理

**症状**：输入`/compose`后无反应或直接报错

**排查步骤**：

1. **检查API配置**
   ```bash
   cd ~/Desktop/私募/QUANTcode
   cat config.json | grep api_key
   ```
   
   确认不是`sk-your-deepseek-api-key-here`。

2. **测试API可用性**
   ```bash
   python -c "
   from runner.llm_provider import create_deepseek_llm
   llm = create_deepseek_llm()
   from langchain_core.messages import HumanMessage
   result = llm.invoke([HumanMessage(content='Hello')])
   print('✅ API正常:', result.content[:50])
   "
   ```

3. **查看详细日志**
   
   在终端会显示Agent推理过程，检查是否有异常。

---

### 6.4 HumanGate不触发

**症状**：高风险场景没有暂停

**排查步骤**：

1. **确认在risk组**
   ```bash
   grep QUANTCODE_GROUP ~/Desktop/私募/opencode/opencode.local.jsonc
   ```

2. **检查routing逻辑**
   ```bash
   python -c "
   from runner.routing.router import route_next_step
   state = {'risk_metrics': {'max_leverage': 10.0}, 'risk_profile': {}}
   result = route_next_step(state)
   print('Routing result:', result)
   "
   ```
   
   应该返回`requires_human=True`。

3. **查看测试用例**
   ```bash
   python -m pytest tests/test_routing.py::TestRouteHumanGate -v
   ```

---

### 6.5 工具调用失败

**症状**：Agent推理正常，但工具调用报错

**排查步骤**：

1. **手动测试工具**
   ```bash
   QUANTCODE_FACTOR_USE_REAL_LLM=1 python -c "
   from tools.factor._register import match_main_tool
   from tools.factor.match_main import MatchMainArgs
   
   result = match_main_tool.execute(
       MatchMainArgs(idea='测试因子'),
       {}
   )
   print('Result:', result)
   "
   ```

2. **检查环境变量**
   ```bash
   echo $QUANTCODE_FACTOR_USE_REAL_LLM
   echo $DEEPSEEK_API_KEY
   ```

3. **查看stub/真实实现切换**
   ```bash
   python -c "
   import os
   os.environ['QUANTCODE_FACTOR_USE_REAL_LLM'] = '1'
   import tools.factor._register
   print('Using real LLM implementation')
   "
   ```

---

## 7. 测试检查清单

使用此清单确保所有功能测试完整：

### 7.1 环境准备

- [ ] Python 3.12+ 已安装
- [ ] Bun已安装
- [ ] 代码已更新到最新
- [ ] Python依赖已安装（`pip install -e .`）
- [ ] Node依赖已安装（`bun install`）
- [ ] Electron已安装（在node_modules中）
- [ ] config.json已配置真实API key
- [ ] opencode.local.jsonc路径配置正确

### 7.2 桌面端启动

- [ ] 桌面端成功启动
- [ ] Electron窗口打开
- [ ] 主界面正常显示
- [ ] 右侧面板可展开
- [ ] QuantCode Tab可见
- [ ] `/tools`命令返回工具列表

### 7.3 Factor组功能

- [ ] 切换到factor组成功
- [ ] match_main工具可调用
- [ ] gen_schema工具可调用
- [ ] autoeval工具可调用
- [ ] Agent自主推理≥3步
- [ ] 完整流程生成FactorReport
- [ ] QuantCode Tab显示更新

### 7.4 Risk组功能

- [ ] 切换到risk组成功
- [ ] calc_risk工具可调用
- [ ] check_gate工具可调用
- [ ] 高风险触发HumanGate暂停
- [ ] QuantCode Tab显示暂停状态
- [ ] Approve按钮可用且工作
- [ ] Reject按钮可用且工作
- [ ] write_pr_comment成功写入

### 7.5 Model组功能

- [ ] 切换到model组成功
- [ ] GitHub token已配置
- [ ] read_pr工具可调用
- [ ] extract_metadata工具可调用
- [ ] trigger_risk_flow成功触发
- [ ] 跨组流程工作

### 7.6 Strategy/Fundamental/Options组

- [ ] Strategy组基本流程通过
- [ ] Fundamental组基本流程通过
- [ ] Options组基本流程通过

### 7.7 HumanGate完整测试

- [ ] 高杠杆触发暂停
- [ ] 高回撤触发暂停
- [ ] 高VaR触发暂停
- [ ] Approve恢复执行
- [ ] Reject终止执行
- [ ] thread_id正确传递
- [ ] 状态正确回流到UI

### 7.8 边界情况

- [ ] 死循环检测（10次迭代后中止）
- [ ] API失败降级处理
- [ ] 工具调用超时处理
- [ ] 无效输入错误提示
- [ ] Checkpoint恢复（重启后恢复任务）

---

## 8. 性能基准

正常情况下的预期耗时：

| 操作 | 预期耗时 | 备注 |
|------|---------|------|
| 桌面端启动 | 5-10秒 | 首次启动更长 |
| MCP连接 | 1-2秒 | 自动重连 |
| 单次工具调用 | 2-5秒 | 取决于工具复杂度 |
| Agent完整流程（3步） | 30-60秒 | 包含LLM推理 |
| HumanGate暂停到恢复 | 即时 | 取决于人工速度 |
| AutoEval评估 | 60-120秒 | 真实API较慢 |

**异常阈值**：
- 单次工具调用 > 30秒：可能API超时
- Agent流程 > 5分钟：可能死循环
- MCP连接 > 10秒：可能配置错误

---

## 9. 录屏和Bug报告

### 9.1 录屏准备

测试时建议录屏，方便后续回顾：

**macOS**：
```bash
# 使用QuickTime录屏
# 应用程序 → QuickTime Player → 文件 → 新建屏幕录制
```

**Windows**：
```bash
# 使用Game Bar
# Win + G 启动
```

### 9.2 Bug报告格式

发现问题时，请按此格式报告：

```markdown
## Bug标题

简短描述问题

### 环境
- 操作系统：macOS 13.0
- QuantCode版本：commit hash或分支
- 测试场景：Factor组 / Risk组 / etc

### 复现步骤
1. 启动桌面端
2. 切换到factor组
3. 输入 `/compose 生成PB-ROE因子`
4. 观察到...

### 实际结果
描述看到的错误行为

### 期望结果
描述应该看到的正确行为

### 截图/录屏
附上截图或录屏链接

### 日志
```
粘贴相关终端日志
```

### 其他信息
- 是否稳定复现：是/否
- 首次出现时间：2026-07-15 14:30
```

---

## 10. 联系方式

测试过程中遇到问题，请联系：

- **技术支持**：Lead (Hendrix Chen)
- **GitHub Issues**：https://github.com/HKUST-QUANT-SOCIETY/quantcode/issues
- **Slack频道**：#quantcode-testing

---

## 附录A：快速命令参考

```bash
# 启动桌面端
cd ~/Desktop/私募/opencode && ./start-quantcode.sh

# 切换组（修改配置后需重启）
sed -i '' 's/"QUANTCODE_GROUP": ".*"/"QUANTCODE_GROUP": "risk"/' opencode.local.jsonc

# 手动测试工具
QUANTCODE_GROUP=factor python -m quantcode.mcp_server

# 运行单元测试
cd ~/Desktop/私募/QUANTcode && python -m pytest tests/ -v

# 查看日志
tail -f ~/.quantcode/logs/agent.log

# 清理checkpoint
rm ~/.quantcode/checkpoints.db
```

---

## 附录B：测试数据

### Factor组测试用例

| 测试场景 | 输入 | 期望输出 |
|---------|------|---------|
| 简单因子 | `生成PB因子` | name=pb, formula=pb |
| 组合因子 | `生成PB-ROE因子` | name=pb_roe, formula=pb*roe |
| 动量因子 | `生成20日动量因子` | name=mom20, formula=return_20d |

### Risk组测试用例

| 测试场景 | 输入 | 期望HumanGate |
|---------|------|--------------|
| 低风险 | `max_leverage=2.0` | 不触发 |
| 高杠杆 | `max_leverage=5.0` | 触发 |
| 高回撤 | `max_drawdown=0.3` | 触发 |

---

**祝测试顺利！** 🎉
