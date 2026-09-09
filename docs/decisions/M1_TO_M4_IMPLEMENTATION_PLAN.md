# M1～M4 规划草稿（已归档）

归档日期：2026-09-08。状态：已被源码交付记录取代；不作为当前实施、验收、启用或部署依据。

下方代码、环境变量、目录结构、周数和验收数量均为旧规划示例，不是可执行实施方案或新的用户要求。不能按示例另建 AccessControlService、Provider 或任务状态机。

当前目标与证据入口：

- [用户确认的内化决策](QUANTCODE_RUNTIME_INTERNALIZATION_2026-09-08.md)：完整范围、复用边界和退出条件。
- [M0 基线](RUNTIME_INTERNALIZATION_M0_BASELINE.md)：调用链、能力迁移和兼容清单。
- [M1 源码交付](RUNTIME_INTERNALIZATION_M1_IMPLEMENTATION.md)与[M2 源码交付](RUNTIME_INTERNALIZATION_M2_IMPLEMENTATION.md)：实际接线及待验项目。
- [当前进度](RUNTIME_INTERNALIZATION_PROGRESS.md)：M3 尚未闭环；M4 命名/文案草稿不代表阶段完成；集中验收仍待全部实现后进行。

当前执行基础是现有 OpenCode Session/Provider/Tools/Runner/Event；组织边界接在 `quantcode/identity.ts`、`access.ts` 等实际路径。迁移开关只在 `OPENCODE_CHANNEL=quantcode` 与 `QUANTCODE_UNIFIED_RUNTIME=1` 同时满足时生效；旧稿中的阶段完成环境变量不能开启迁移或证明验收。

原 `identity-validation.test.ts` 使用未核实路由和固定本机服务地址，不能支撑其声称的 HTTP/撤销/SSE 覆盖。该文件已改为直接调用实际 Identity 模块的隔离 owner/metadata 测试，尚未运行，也不替代最终集成验收。

<details>
<summary>保留原稿全文，仅供追溯；其中命令和伪代码不应执行</summary>

````text
# M1-M4 完整实施计划与验收标准

日期：2026-09-08
状态：实施计划已制定

## 总体策略

按照M0→M1→M2→M3→M4顺序推进，每个阶段完成最小验收后进入下一阶段。

## 任务1-3：M0核对 + M1最小测试 + 双路径隔离 ✅

**已完成交付**：
- ✅ M0_IMPLEMENTATION_CHECKLIST.md - E01-E23状态核对
- ✅ identity-validation.test.ts - M1身份验证单元测试  
- ✅ 统一迁移开关与身份边界已接入实际路径（`quantcode/identity.ts`、`quantcode/access.ts`）；未接入的独立状态/所有权草稿已删除

**下一步**：集成到实际代码路径

---

## 任务4：M1完整验收（集成测试）

### 4.1 修复高风险项实际集成

**E06: 消息访问控制**
```typescript
// frontend/packages/core/src/session/message.ts
export const getMessage = (id: string, actor: SessionContext) =>
  Effect.gen(function* (_) {
    const accessControl = yield* _(AccessControl)
    const canRead = yield* _(accessControl.canReadMessage(id, actor))
    if (!canRead) {
      return yield* _(Effect.fail(new Error('Forbidden')))
    }
    // ... 原有逻辑
  })
```

**E12: 事件订阅隔离**
```typescript
// frontend/packages/opencode/src/server/routes/session-events.ts  
export const subscribeToEvents = (sessionId: string, actor: SessionContext) =>
  Effect.gen(function* (_) {
    const accessControl = yield* _(AccessControl)
    const canSubscribe = yield* _(
      accessControl.canSubscribeToSessionEvents(sessionId, actor)
    )
    if (!canSubscribe) {
      return yield* _(Effect.fail(new Error('Forbidden')))
    }
    // ... SSE流
  })
```

**E16: HTTP API统一认证中间件**
```typescript
// frontend/packages/opencode/src/server/middleware/auth.ts
export const authMiddleware = (req, res, next) => {
  const accessControl = createAccessControlService()
  Effect.runPromise(
    accessControl.validateApiRequest({
      headers: req.headers,
      path: req.path,
      method: req.method,
      body: req.body
    })
  )
  .then(context => {
    req.quantcodeContext = context
    next()
  })
  .catch(err => {
    res.status(401).json({ error: err.message })
  })
}
```

**E20: 子任务身份继承**
```typescript
// frontend/packages/core/src/session/create.ts
export const createSubtask = (
  parentContext: SessionContext,
  params: SubtaskParams
) => Effect.gen(function* (_) {
  const accessControl = yield* _(AccessControl)
  const subtaskContext = yield* _(
    accessControl.createSubtaskContext(parentContext, params)
  )
  return yield* _(createSession({ ...params, context: subtaskContext }))
})
```

### 4.2 中风险项修复

**E11: 文件/PTY工作区约束**
- 所有文件读写经过工作区边界检查
- PTY命令注入防护
- 符号链接/硬链接检测

**E07/E08: 工具准入统一**
- plugin.before后生成精确审批摘要
- MCP工具与原生工具共用policy
- 动态工具按发布目录过滤

### 4.3 M1集成测试套件

```bash
# tests/m1-integration/
├── auth-rejection.test.ts        # 未认证拒绝
├── cross-group-isolation.test.ts # 跨组隔离
├── message-access.test.ts        # E06消息访问
├── event-subscription.test.ts    # E12事件订阅  
├── api-authentication.test.ts    # E16 API认证
├── subtask-inheritance.test.ts   # E20子任务继承
├── file-workspace-boundary.test.ts # E11文件边界
└── tool-admission.test.ts        # E07/E08工具准入
```

### 4.4 M1退出条件验收

- [ ] E01-E23高/中风险项全部修复并通过测试
- [ ] 正常只读查询可执行
- [ ] 未认证/越权/撤销/未冻结写入全部拒绝
- [ ] Shell和子任务不能绕过约束
- [ ] 迁移开关正确控制新/旧任务创建

---

## 任务5：M2条件确认与新入口实施

### 5.1 前置条件检查

```bash
# 确认M1已通过
export QUANTCODE_M1_VALIDATION=complete

# 验证M1测试全部通过
bun test frontend/packages/opencode/test/quantcode/
bun test tests/m1-integration/
```

### 5.2 移除旧run_agent强制转交

**frontend/packages/app/src/pages/home.tsx**
```typescript
// 旧代码（M2前）
const onSubmit = (prompt: string) => {
  // 强制调用Python run_agent
  return callQuantCodeRunAgent({ prompt, group })
}

// 新代码（M2后）
const onSubmit = (prompt: string) => {
  const config = getExecutionModeFromEnv()
  
  // 检查是否允许创建新任务
  if (!config.allowUnifiedNewTask) {
    throw new Error('Task creation disabled: M1 validation not complete')
  }
  
  // 直接创建native session
  return createNativeSession({
    prompt,
    context: currentSessionContext,
    skills: loadGroupSkills(currentSessionContext.group),
    capabilities: loadCapabilityCatalog(currentSessionContext.group),
    memory: connectGroupMemory(currentSessionContext.group)
  })
}
```

### 5.3 组织上下文加载

```typescript
// frontend/packages/opencode/src/quantcode/task-context.ts
export const loadTaskContext = (context: SessionContext) =>
  Effect.gen(function* (_) {
    // 加载组Skill
    const skills = yield* _(loadGroupSkills(context.group))
    
    // 加载能力目录
    const capabilities = yield* _(loadCapabilityCatalog(context.group))
    
    // 连接组Memory
    const memory = yield* _(connectGroupMemory(context.group))
    
    // P-10任务分类
    const classifier = yield* _(createTaskClassifier())
    
    return {
      skills,
      capabilities,
      memory,
      classifier,
      context
    }
  })
```

### 5.4 单一Provider配置

```typescript
// frontend/packages/core/src/plugin/provider/quantcode.ts
export const QuantCodeProvider = {
  name: 'quantcode',
  
  getConfig: () => {
    // 只从QuantCode宿主读取配置
    const url = process.env.QUANTCODE_API_URL
    const key = process.env.QUANTCODE_API_KEY
    
    if (!url || !key) {
      throw new Error('QuantCode model config not set')
    }
    
    return { url, key }
  },
  
  // 禁止从项目env或其他供应商继承
  inheritFromProject: false,
  inheritFromOpenCode: false
}
```

### 5.5 M2验收条件

- [ ] 新任务直接创建native session
- [ ] 旧run_agent入口已禁用创建新任务
- [ ] 组Skill/能力/Memory成功加载
- [ ] 单次模型配置驱动完整任务
- [ ] UI提交/停止/错误对准同一session
- [ ] 真实场景：查能力→调组件→记录结果

---

## 任务6：外部依赖Mock与错误处理

### 6.1 组件不可用时的错误返回

```python
# quantcode/components/adapter.py
class ComponentAdapter:
    def call_component(self, name: str, params: dict):
        status = self.get_component_status(name)
        
        if status == ComponentStatus.UNAVAILABLE:
            return {
                'status': 'UNAVAILABLE',
                'error': f'Component {name} is not connected',
                'suggestion': 'Check component service status'
            }
        
        if status == ComponentStatus.STAGING:
            return {
                'status': 'STAGING',
                'warning': f'Component {name} is in staging mode',
                'result': self._call_staging_adapter(name, params)
            }
        
        # 真实调用
        return self._call_production_component(name, params)
```

### 6.2 Mock组件清单

| 组件 | Mock策略 | 错误返回 |
|---|---|---|
| QuantEvaluator | 本地fixture | UNAVAILABLE if service down |
| DataAccess | 本地CSV | UNAVAILABLE if API not configured |
| SSH Gateway | 本地文件模拟 | CONNECTION_ERROR if not deployed |
| Admin Deploy | Staging适配器 | STAGING (不伪装成功) |
| GitHub Sync | 手动触发 | PARTIAL if not scheduled |

### 6.3 验收

- [ ] 组件unavailable返回明确错误
- [ ] 不伪装成功或返回mock数据（除非显式dev模式）
- [ ] Agent收到错误后可以向用户说明

---

## 任务7：M3状态统一与恢复

### 7.1 Native Session作为唯一权威

```typescript
// frontend/packages/core/src/session/state.ts
export interface UnifiedSessionState {
  // Native session是权威源
  sessionId: string
  owner: string
  group: string
  role: string
  
  // 执行状态
  status: 'running' | 'completed' | 'cancelled' | 'error'
  messages: Message[]
  toolCalls: ToolCall[]
  events: Event[]
  
  // 组织投影（从events派生）
  solutionDoc?: SolutionDoc
  gates: Gate[]
  artifacts: Artifact[]
  evidence: Evidence[]
  
  // Python checkpoint仅作为legacy兼容
  legacyCheckpoint?: {
    path: string
    version: string
    readonly: true  // 不能修改
  }
}
```

### 7.2 Python组织服务作为投影

```python
# runner/projection.py
class OrganizationalProjection:
    """从native session events构建组织视图"""
    
    def project_from_events(self, session_id: str, events: List[Event]):
        # 重建Activity
        activity = self._build_activity_timeline(events)
        
        # 重建方案状态
        solution = self._extract_solution_doc(events)
        
        # 重建Gate记录
        gates = self._extract_gates(events)
        
        # 重建artifacts
        artifacts = self._extract_artifacts(events)
        
        return {
            'activity': activity,
            'solution': solution,
            'gates': gates,
            'artifacts': artifacts
        }
```

### 7.3 恢复时重新验证

```typescript
export const resumeSession = (
  sessionId: string,
  actor: SessionContext
) => Effect.gen(function* (_) {
  // 读取session状态
  const session = yield* _(getSession(sessionId))
  
  // 验证当前actor是否有权恢复
  if (session.owner !== actor.actor_id && actor.role !== 'admin') {
    return yield* _(Effect.fail(new Error('Cannot resume others session')))
  }
  
  // 重新验证资源授权
  const workspace = session.workspace
  const hasAccess = yield* _(checkWorkspaceAccess(actor, workspace))
  if (!hasAccess) {
    return yield* _(Effect.fail(new Error('Workspace access revoked')))
  }
  
  // 恢复session
  return yield* _(continueSession(session, actor))
})
```

### 7.4 Legacy checkpoint只读

```python
# quantcode/legacy_host.py
class LegacyCheckpointReader:
    """只读访问旧checkpoint，不创建新任务"""
    
    def read_checkpoint(self, checkpoint_id: str) -> dict:
        checkpoint = self._load_from_sqlite(checkpoint_id)
        
        # 标记为legacy
        checkpoint['legacy'] = True
        checkpoint['readonly'] = True
        checkpoint['migration_note'] = (
            'This is a legacy checkpoint. '
            'New tasks use the unified execution engine.'
        )
        
        return checkpoint
    
    def can_resume_as_new_task(self) -> bool:
        # 禁止用旧checkpoint创建新任务
        return False
```

### 7.5 M3验收条件

- [ ] Native session是状态唯一来源
- [ ] Python projection从events重建
- [ ] 恢复时重新验证身份和资源
- [ ] 取消可以终止实际执行
- [ ] 跨成员Admin汇总已验证
- [ ] Legacy checkpoint只读，不误执行

---

## 任务8：端到端验收场景

### 8.1 完整用户场景测试

**场景1：查询能力→调用组件→记录结果**
```
1. 登录factor组
2. 提交查询："最近一个月IC最高的10个因子"
3. Agent查询能力目录 → 找到QuantEvaluator
4. 调用evaluator.get_top_factors(days=30, limit=10)
5. 结果记录到artifact
6. 记录到组Memory
```

**场景2：跨组协作与Gate**
```
1. factor组生成新因子
2. 需要model组的训练数据 → 触发permission Gate
3. model组approver批准 → 记录evidence
4. factor组获得临时数据访问
5. 完成因子评估
```

**场景3：L2任务方案先行**
```
1. 提交多模块修改任务
2. 任务分类器判定为L2
3. 强制生成SolutionDoc
4. 用户review并frozen
5. Agent按方案生成代码
6. Conformance verdict验证文件面一致
```

### 8.2 验收标准

- [ ] 场景1-3全部通过
- [ ] 配置一次模型完成所有步骤
- [ ] UI状态正确显示
- [ ] 错误处理清晰
- [ ] 审计记录完整

---

## 任务9：GitGraph桌面UI实现

### 9.1 六列缩略卡片

```tsx
// frontend/packages/app/src/components/quantcode/GitGraph.tsx
export const GitGraphGrid = () => {
  const repos = useRepos()
  
  return (
    <div className="grid grid-cols-6 gap-4">
      {repos.map(repo => (
        <RepoCard key={repo.id} repo={repo}>
          <RepoName>{repo.name}</RepoName>
          <BranchTrack branches={repo.recentBranches.slice(0, 4)} />
          <CommitList commits={repo.recentCommits.slice(0, 4)} />
        </RepoCard>
      ))}
    </div>
  )
}
```

### 9.2 详情分支/diff

```tsx
export const RepoDetailModal = ({ repoId }: { repoId: string }) => {
  const [selectedCommit, setSelectedCommit] = useState<string>()
  
  return (
    <Modal>
      <BranchList repo={repoId} />
      <CommitHistory repo={repoId} onSelect={setSelectedCommit} />
      {selectedCommit && (
        <CommitDiff commitId={selectedCommit} />
      )}
    </Modal>
  )
}
```

### 9.3 验收

- [ ] 桌面1440px/1920px显示正确
- [ ] 六列网格布局
- [ ] 分支彩色轨道
- [ ] commit点击显示diff
- [ ] 权限过滤（普通用户只看授权repo）

---

## 任务10：Admin四页签UI

```tsx
// frontend/packages/app/src/components/quantcode/Admin.tsx
export const AdminConsole = () => {
  const [activeTab, setActiveTab] = useState<AdminTab>('overview')
  
  return (
    <Tabs value={activeTab} onValueChange={setActiveTab}>
      <TabsList>
        <TabsTrigger value="overview">概览</TabsTrigger>
        <TabsTrigger value="tasks">任务</TabsTrigger>
        <TabsTrigger value="reports">报告与产物</TabsTrigger>
        <TabsTrigger value="deploy">部署</TabsTrigger>
      </TabsList>
      
      <TabsContent value="overview">
        <OverviewCards />
        <RunningTasks />
        <RecentErrors />
      </TabsContent>
      
      <TabsContent value="tasks">
        <TasksTable showAllGroups />
      </TabsContent>
      
      <TabsContent value="reports">
        <ArtifactsGallery />
        <EvidenceChain />
      </TabsContent>
      
      <TabsContent value="deploy">
        <DeployQueue />
        <DeployHistory />
      </TabsContent>
    </Tabs>
  )
}
```

验收：
- [ ] 四个页签完整实现
- [ ] Admin可见所有组
- [ ] 普通用户访问拒绝
- [ ] 部署操作留痕

---

## 任务11：M4旧循环退役

### 11.1 退役条件检查

```bash
# 确认M1-M3全部通过
export QUANTCODE_M1_VALIDATION=complete
export QUANTCODE_M2_MIGRATION=complete  
export QUANTCODE_M3_STATE=complete

# 运行完整测试套件
bun run check:product

# 验证没有新任务使用旧循环
grep -r "quantcode_run_agent" frontend/packages/app/src/
# 应该只在legacy compat中出现
```

### 11.2 移除旧入口

```python
# runner/__init__.py
# 删除或标记deprecated
@deprecated("Use unified execution engine instead")
def run_agent(prompt: str, group: str, **kwargs):
    raise RuntimeError(
        "Legacy run_agent is removed. "
        "Use native session API instead."
    )
```

### 11.3 保留兼容层

```python
# runner/legacy_compat.py
"""
仅用于读取旧checkpoint和history
不创建新任务
"""

# 只读 legacy list/detail/resume-preflight；不创建新任务
```

### 11.4 命名清理

- [ ] 内部包名保持兼容（如@opencode-ai/*）
- [ ] UI文案全部改为QuantCode
- [ ] 桌面窗口标题/图标
- [ ] README/docs更新
- [ ] LICENSE保留OpenCode来源

### 11.5 M4验收

- [ ] 旧run_agent已移除或deprecated
- [ ] 新任务不能绕过统一引擎
- [ ] Legacy checkpoint只读可访问
- [ ] 桌面安装包正确命名
- [ ] 文档/UI一致性

---

## 任务12：外部依赖接入与生产验收

### 12.1 SSH Gateway生产部署

- [ ] Ubuntu systemd服务部署
- [ ] Roster文件配置
- [ ] 公钥验证测试
- [ ] 桌面SSH连接测试

### 12.2 真实组件接入

| 组件 | 接入条件 | 验收 |
|---|---|---|
| QuantEvaluator | API endpoint + auth | 真实因子评估 |
| DataAccess | Database config | 真实数据查询 |
| GitHub Sync | GitHub App token | 自动同步仓库 |
| Admin Deploy | 生产队列 + 服务账号 | 受控部署执行 |

### 12.3 端到端生产验收

**场景：完整因子研究流程**
```
1. 真实SSH登录
2. 查询真实因子数据
3. 调用真实QuantEvaluator
4. 生成真实研究报告
5. 提交真实部署（Admin）
```

### 12.4 性能验收

- [ ] 因子评估P95 < 30s
- [ ] PIT查询P95 < 500ms
- [ ] Admin跨组查询P95 < 15s
- [ ] 方案首轮输出 < 5min

---

## 总体进度跟踪

| 阶段 | 任务 | 状态 | 预计完成 |
|---|---|---|---|
| M0 | 1-3: 核对+测试+开关 | ✅ | 已完成 |
| M1 | 4: 高风险项修复 | 🔨 | 1周 |
| M1 | 4: 中风险项修复 | 📋 | 1周 |
| M1 | 4: 集成测试 | 📋 | 3天 |
| M2 | 5: 新入口切换 | 📋 | 1周 |
| M2 | 6: 外部依赖mock | 📋 | 3天 |
| M3 | 7: 状态统一 | 📋 | 1周 |
| M3 | 8: 端到端验收 | 📋 | 1周 |
| UI | 9-10: GitGraph+Admin | 📋 | 2周 |
| M4 | 11: 旧循环退役 | 📋 | 1周 |
| Prod | 12: 生产接入 | 📋 | 2周 |

**总预计时间：10-12周**

---

## 风险与缓解

**风险1：测试发现架构问题**
- 缓解：每阶段最小验收，及时回退修复

**风险2：外部依赖延迟**
- 缓解：Mock优先，真实接入独立验收

**风险3：性能不达标**
- 缓解：持续监控，必要时优化或调整目标

**风险4：用户数据迁移**
- 缓解：保留legacy只读，手动迁移重要checkpoint

---

生成时间：2026-09-08

````

</details>
