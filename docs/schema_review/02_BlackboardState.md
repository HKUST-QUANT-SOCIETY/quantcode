# BlackboardState Schema 评审文档

> **Owner**: 用户（Lead）  
> **模式**: Pattern 2 (Stateful Blackboard)  
> **评审时长**: 5 分钟  
> **状态**: 已评审

---

## 一句话定义

> **BlackboardState 是 Pattern 2 共享状态层的契约**，定义"agent 用来交换信息的存储层长什么样、谁能读谁能写、数据存哪里"。

---

## 为什么需要它

**问题**：

- 长任务（10+ 小时）会遇到上下文 compact，依赖 LLM 长程记忆不可靠
- Worker agent 之间不能直接对话传数据（Pattern 1 禁止），必须通过共享层
- 跨组协作：模型组写 PR 元数据，风控组读取 → 需要明确的读写权限

**解决**：

- 状态外化到磁盘（MEMORY.md / checkpoint.md / progress.md）
- 4+1 层隔离（GLOBAL / PROJECT / GROUP / SESSION / TASK）
- WritePolicy 明确谁能写（OWNER / APPEND / GROUP_APPEND）

---

## 核心字段

### BlackboardEntry（一条记录）

| 字段                 | 类型                         | 必填               | 用途                                          |
| -------------------- | ---------------------------- | ------------------ | --------------------------------------------- |
| `key`                | `str`                        | ✅                 | 命名空间 key（如 `factor.pb_roe.ic_metrics`） |
| `scope`              | `BlackboardScope`            | ✅                 | 隔离级别（5 选 1）                            |
| `group`              | `GroupName \| None`          | scope=GROUP 时必填 | 哪个组的数据                                  |
| `value`              | `dict \| list \| str \| ...` | ✅                 | JSON-serializable 任意值                      |
| `write_policy`       | `WritePolicy`                | ✅                 | 谁能写（OWNER / APPEND / GROUP_APPEND）       |
| `written_by_task_id` | `str`                        | ✅                 | 哪个 task 写的（溯源）                        |
| `written_by_group`   | `GroupName`                  | ✅                 | 哪个组写的（权限判断）                        |
| `version`            | `int`                        | ✅                 | 版本号（乐观锁）                              |
| `created_at`         | `datetime`                   | ✅                 | 创建时间                                      |
| `updated_at`         | `datetime`                   | ✅                 | 更新时间                                      |

### BlackboardState（整个黑板）

| 字段         | 类型                         | 必填 | 用途                                                  |
| ------------ | ---------------------------- | ---- | ----------------------------------------------------- |
| `session_id` | `str`                        | ✅   | 当前会话 ID                                           |
| `entries`    | `dict[str, BlackboardEntry]` | ✅   | 所有记录（key = `make_entry_key(scope, group, key)`） |
| `updated_at` | `datetime`                   | ✅   | 黑板最后更新时间                                      |

---

## 5 层隔离（核心决策）

| Scope       | 磁盘路径                                                   | 谁能读     | 典型用途        | 示例 key               |
| ----------- | ---------------------------------------------------------- | ---------- | --------------- | ---------------------- |
| **GLOBAL**  | `.quantcode/memory/global/MEMORY.md`                       | 所有人     | 跨项目用户偏好  | `user.preferred_model` |
| **PROJECT** | `./MEMORY.md`                                              | 所有组     | 项目级共享知识  | `shared.last_pr`       |
| **GROUP**   | `.quantcode/memory/groups/<group>/MEMORY.md`               | **仅本组** | 组内私有知识    | `factor.ic_registry`   |
| **SESSION** | `.quantcode/memory/sessions/<sid>/checkpoint.md`           | 本会话     | 会话 checkpoint | `session.current_task` |
| **TASK**    | `.quantcode/memory/sessions/<sid>/tasks/<tid>/progress.md` | 本任务     | 任务进度        | `task.progress_pct`    |

### 🔴 关键决策：GROUP 隔离墙是硬的

**用户核心要求**：

> "跨组读权限应该不能给。只有部分 public 的数据可以读 memory，或者说干脆就全部隔离，因为我们本身代码设计上就是隔离的。"

**实现**：

- **GROUP scope 默认不可跨组读**：factor 组写的 `group:factor:ic_registry`，risk 组调 `get_entry(GROUP, FACTOR, "ic_registry")` 返回 `None`
- **显式 PUBLIC 数据**：如果要跨组共享，必须写到 **PROJECT scope**，并在 key 里标记 `shared.*` 前缀
- **示例**：

  ```python
  # ❌ 跨组读不到
  factor_private = bb.get_entry(BlackboardScope.GROUP, GroupName.FACTOR, "ic_registry")
  # factor_private = None（如果当前是 risk 组）

  # ✅ 显式 PUBLIC 数据
  bb.add_entry(BlackboardEntry(
      scope=BlackboardScope.PROJECT,
      key="shared.factor_registry",  # shared.* 前缀表示 public
      value={"count": 10},
      written_by_task_id="T1",
      written_by_group=GroupName.FACTOR,
  ))
  # 所有组都能读到
  ```

---

## WritePolicy（3 种）

| Policy           | 谁能写                  | 典型场景                      |
| ---------------- | ----------------------- | ----------------------------- |
| **OWNER**        | 只有写入的 task         | 任务进度（task 自己独占）     |
| **APPEND**       | 任何 task，仅追加       | 全局日志、trace               |
| **GROUP_APPEND** | 同组的任何 task，仅追加 | 因子注册表（factor 组内协作） |

**R2 Q1 澄清**：`GROUP_APPEND` 在 `PROJECT` scope 的语义

- **场景**：factor registry 放在 PROJECT scope（让 fundamental 组也能追加）
- **权限判断**：用 `written_by_group` 追踪，但策略是"任意组可追加"
- **示例**：

  ```python
  # fundamental 组写一个因子
  bb.add_entry(BlackboardEntry(
      scope=BlackboardScope.PROJECT,
      key="shared.factor_registry",
      write_policy=WritePolicy.GROUP_APPEND,
      value={"factors": ["pb_roe"]},
      written_by_group=GroupName.FUNDAMENTAL,
  ))

  # factor 组追加另一个因子
  entry = bb.get_entry(BlackboardScope.PROJECT, None, "shared.factor_registry")
  entry.value["factors"].append("momentum")
  entry.written_by_group = GroupName.FACTOR  # 追踪最后写入者
  bb.add_entry(entry)
  ```

---

## 示例：跨组协作（model → risk）

### 场景：模型组提 PR，风控组读取元数据

```python
# 1. 模型组 task T1 写 GROUP-scoped 元数据
model_task_entry = BlackboardEntry(
    scope=BlackboardScope.GROUP,
    group=GroupName.MODEL,
    key="pr.metadata",
    value={"pr_url": "https://github.com/.../pull/123", "model_type": "xgboost"},
    write_policy=WritePolicy.OWNER,
    written_by_task_id="T1",
    written_by_group=GroupName.MODEL,
)
bb.add_entry(model_task_entry)

# 2. 模型组同时写 PROJECT-scoped 通知（显式 PUBLIC）
notification_entry = BlackboardEntry(
    scope=BlackboardScope.PROJECT,
    key="shared.pending_risk_reviews",
    value={"pr_123": {"from_group": "model", "metadata_key": "pr.metadata"}},
    write_policy=WritePolicy.GROUP_APPEND,
    written_by_task_id="T1",
    written_by_group=GroupName.MODEL,
)
bb.add_entry(notification_entry)

# 3. 风控组 task T2 读取
# ❌ 直接读 GROUP:model:pr.metadata → None（硬隔离）
direct = bb.get_entry(BlackboardScope.GROUP, GroupName.MODEL, "pr.metadata")
assert direct is None

# ✅ 从 PROJECT-scoped 通知里找到 "去哪读"
notification = bb.get_entry(BlackboardScope.PROJECT, None, "shared.pending_risk_reviews")
pr_info = notification.value["pr_123"]
# 然后通过 PR URL 外部 API 或约定的 handoff 协议拿数据
```

---

## 关键方法

### `make_entry_key(scope, group, key) -> str`

**作用**：生成 `entries` dict 的复合 key（R2 Issue 3 修复）

**格式**：`<scope>:<group_or_'_'>:<key>`

**示例**：

```python
BlackboardState.make_entry_key(BlackboardScope.PROJECT, None, "last_pr")
# → "project:_:last_pr"

BlackboardState.make_entry_key(BlackboardScope.GROUP, GroupName.FACTOR, "ic")
# → "group:factor:ic"
```

### `add_entry(entry)` / `get_entry(scope, group, key)` / `remove_entry(scope, group, key)`

**作用**：统一使用 `make_entry_key()` 的 CRUD 接口

---

## 开放问题（评审会讨论）

### Q1: SESSION 级 checkpoint 保留多久？

- **背景**：`.quantcode/memory/sessions/<sid>/checkpoint.md`
- **问题**：会话结束后多久删除？还是永久保留？
- **建议**：
  - **A**: 保留 7 天（滚动清理）
  - **B**: 保留到项目关闭
  - **C**: 用户手动 `/clean-sessions` 清理

### Q2: TASK 级 progress 谁清理？

- **背景**：`.quantcode/memory/sessions/<sid>/tasks/<tid>/progress.md`
- **问题**：task 完成后，progress.md 立即删还是留着？
- **建议**：
  - **A**: task 完成后立即删（减少磁盘占用）
  - **B**: 保留到 session 结束（方便 debug）
  - **C**: 归档到 `artifacts/tasks/<tid>/` 而不是删除

### Q3: GROUP scope 下要不要再细分"子组"？

- **背景**：6 个组（fundamental / factor / model / risk / strategy / options）
- **问题**：如果 factor 组有 5 个人，要不要每个人有自己的 "user-scoped" 隔离？
- **建议**：
  - **A**: 不做，6 组已经够细（MVP）
  - **B**: 加 `USER` scope，key 格式 `user:<ssh_key_fp>:<key>`
  - **C**: GROUP scope 下加 `owner` 字段（user-level 过滤）

### Q4: `version` 字段的乐观锁语义？

- **背景**：`BlackboardEntry.version` 从 1 开始
- **问题**：runner 怎么用它防止并发写冲突？
- **建议**：
  - **A**: 写入时检查 `current_version == expected_version`，不匹配拒绝
  - **B**: 不用乐观锁，改成 last-writer-wins（简单但可能丢数据）
  - **C**: MVP 不做并发写（单 session 串行执行），version 只做审计

---

## 依赖关系

**BlackboardState 被以下 schema 依赖**：

- `ComposeTask` — task 通过 blackboard 读写状态
- 所有业务 schema（间接）— 业务数据最终落到 blackboard

**BlackboardState 依赖**：

- `GroupName` (enum) — 6 组边界
- `TaskIDStr` (type alias) — 溯源到 task

---

## 测试覆盖

✅ 29 个测试中有 8 个覆盖 BlackboardState：

- GROUP scope 需要 group 字段（否则 ValidationError）
- GROUP_APPEND 只能用于 GROUP/PROJECT scope
- `make_entry_key()` 格式正确
- `add_entry()` / `get_entry()` / `remove_entry()` CRUD
- **硬隔离测试**：factor 组写 GROUP entry，risk 组 `get_entry()` 返回 `None`

---

## 决策记录（评审会后填写）

| 决策点                        | 决策                | 理由                                                        | 反对意见                                   |
| ----------------------------- | ------------------- | ----------------------------------------------------------- | ------------------------------------------ |
| Q1: SESSION checkpoint 保留期 | 保留 7 天滚动清理   | 兼顾 compact/replay debug 和磁盘占用                        | 项目关闭前长期复盘需求可另行归档           |
| Q2: TASK progress 清理策略    | 保留到 session 结束 | 便于 debug 单次长任务，不立即丢失进度                       | 长期留存交给 artifacts，而不是 progress.md |
| Q3: 是否细分子组/用户         | MVP 不细分          | 6 个组已经是当前隔离边界，避免过早增加 USER scope           | 多人协作冲突后续通过 owner/audit 扩展      |
| Q4: version 乐观锁语义        | MVP 只做审计字段    | 当前单 session 串行执行，先不引入 expected-version 写入协议 | 并行写入上线时再改为乐观锁检查             |

---

**评审通过签字**（全员）：

- [ ] 用户（Lead）
- [ ] 陈镇鸿
- [ ] 杨欣琳
- [ ] 刘炽
- [√] 肖骥超
