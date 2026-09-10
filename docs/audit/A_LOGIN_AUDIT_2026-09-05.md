# A-身份登录与人员授权闭环审计报告（2026-09-05）

> **负责人**：李楷芳 | **所属组**：Agent 组 | **状态**：⏳ 等待正式 roster 激活

---

## 1. 审计概况

| 项目 | 内容 |
|------|------|
| 审计范围 | F-01（身份认证）、F-05（SSH 登录与组绑定） |
| 代码基线 | 后端：`quantcode`（最新 commit：`f0ec06f`）；前端：`opencode`（最新 commit：待确认） |
| 审计日期 | 2026-09-05 |
| 当前状态 | ⏳ 人员表数据已存在于系统中（46 条提交、39 个身份标识、31 条密钥绑定候选），但正式 roster 尚未激活，待组长启用后补测完整链路 |

---

## 2. 人员核对清单

### 2.1 已检查的配置文件
- `configs/permissions.yaml` → 仅工具权限策略（allow/ask/deny），无人员信息
- `configs/github_teams.yaml` → 仅 GitHub 团队映射，无具体人员信息
- `configs/project_grants.yaml` → 空
- `deploy/`、`data/` → 无人员配置

### 2.2 人员数据状态
根据 `FULL_PRODUCT_AUDIT_2026-09-05.md` 全量审计报告：

| 指标 | 数值 |
|------|------|
| 人员提交总数 | 46 条 |
| 身份标识 | 39 个 |
| 密钥绑定候选 | 31 条 |
| 有待确认项 | 10 人 |
| 正式 roster 激活状态 | ❌ 未激活 |

### 2.3 冲突项清单
> 当前由于正式 roster 未激活，无法从系统中读取完整的用户字段（用户名、组、角色、公钥、工作区），待激活后逐项核对：
>
> - [ ] 每个用户是否有 `public_key`？
> - [ ] `public_key` 格式是否正确（以 `ssh-rsa` 或 `ssh-ed25519` 开头）？
> - [ ] `group` 字段是否在允许列表中（factor/model/risk/fundamental/strategy/options/admin）？
> - [ ] `role` 字段是否合理（admin/analyst/approver）？
> - [ ] 是否有用户缺少 `workdir` 工作区配置？

| 用户名 | 组 | 问题描述 | 严重度 |
|--------|----|----------|--------|
| *待 roster 激活后填写* | *待补充* | *待补充* | *待补充* |

---

## 3. 链路验证证据

### 3.1 鉴权验证（✅ 已通过）
- **验证方式**：在浏览器控制台中执行 `fetch('/api/auth/me', { credentials: 'include' })`
- **返回状态**：`Status: 200`（请求成功，未返回 401 或 403）
- **结论**：当前 session 有效，服务端已接收到请求并正常响应
- **截图**：`docs/audit/auth_me_2026-09-06.png`

### 3.2 身份信息暴露验证（⏳ 待激活）
- **验证方式**：检查 `/api/auth/me` 返回的 Response Body
- **实际结果**：返回 HTML 页面（非 JSON），未返回用户身份信息（`{"username":"...","group":"..."}`）
- **结论**：正式 roster 尚未激活，系统未向外暴露用户身份信息
- **截图**：`docs/audit/auth_me_2026-09-06.png`

### 3.3 失败路径（待 roster 激活后补测）
- 使用无效公钥登录 → 预期返回 401
- 使用有效公钥登录 → 预期返回 200 及用户 JSON
- 退出登录 → 后续请求返回 401

### 3.4 成功路径（待 roster 激活后补测）
- 链路：SSH agent → gateway → MCP → UI 登录
- 预期：成功登录并显示对应组的工作区

### 3.5 退出、过期、撤销验证（待 roster 激活后补测）
- 待人员正式激活后补充测试

---

## 4. 接入配置说明

### 4.1 当前已知配置
- `permissions.yaml` 中定义了：
  - `fundamental.publish: deny`
  - `ssh.read: allow`
  - `ssh.dev.write: allow`
  - `ssh.prod.write: ask`

### 4.2 待确认事项
- 正式 roster 的激活方式（需由组长陈远恒操作）
- 激活后是否需要重启服务
- 激活后 `/api/auth/me` 是否返回真实用户 JSON

---

## 5. 下一步计划

| 序号 | 事项 | 负责人 | 状态 |
|------|------|--------|------|
| 1 | 组长激活正式 roster | 陈远恒（Hendrix） | ⏳ 待执行 |
| 2 | 重启服务后重新测试 `/api/auth/me` | 李楷芳 | ⏳ 待执行 |
| 3 | 确认返回用户 JSON 后补截图 | 李楷芳 | ⏳ 待执行 |
| 4 | 核对人员冲突项（公钥格式、组、角色、工作区） | 李楷芳 | ⏳ 待执行 |
| 5 | 更新本报告，补充成功路径和冲突项清单 | 李楷芳 | ⏳ 待执行 |
| 6 | 提交 PR，并入 `FULL_PRODUCT_AUDIT_2026-09-05.md` | 李楷芳 | ⏳ 待执行 |

---

## 6. 备注

- 已按照 `FULL_PRODUCT_AUDIT_2026-09-05.md` 中的描述确认人员表状态：46 条提交、39 个身份标识、31 条密钥绑定候选。
- 已向组长（陈远恒）确认人员表配置状态，等待正式 roster 激活。
- 代码分支：`feature/audit-login-kaifang`
- 前端分支：`feature/ui-login-kaifang`

---

## 7. 附录：证据截图清单

| 截图文件 | 描述 |
|----------|------|
| `auth_me_2026-09-06.png` | 控制台 `fetch('/api/auth/me')` 返回 Status: 200，Response 为 HTML |