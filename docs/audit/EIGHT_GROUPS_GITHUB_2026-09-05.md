# 八组与 GitHub Team 核验 · 2026-09-05

用户决定新增 Infra、Agent 两个工作组，风控归 risk、RL 工程落地归 factor、因子挖掘归 factor、模型归 model。新增组不是 Admin 角色；一个 Session 仍绑定一个组。

## 实际组织核对

通过现有 GitHub CLI 授权，只读查询 HKUST-QUANT-SOCIETY 的 teams、members、repositories 和成员登记的公钥。读取 23 个 team，去重 39 个成员；已有 infra/agent，因此没有重复创建远端 team，也没有修改任何远端成员或仓库授权。

| QuantCode group | 实际 GitHub team slug | 观测成员数 | team repo 并集数 |
|---|---|---:|---:|
| infra | infra | 7 | 4 |
| agent | agent | 9 | 6 |
| factor | mining | 5 | 2 |
| model | factor-model | 7 | 6 |
| risk | risk | 6 | 3 |
| fundamental | fundamentals | 15 | 2 |
| strategy | strategy、cta | 6 | 5 |
| options | options-research | 4 | 0 |

这些是管理员只读观测值，不是给所有成员的授权承诺，之后可变。options-research 此时 repo 列表为空；不伪造或自动补仓库权限。evaluation、research、docs-write 等 team 未被不加区别地并入工作组。配置单源为 `configs/github_teams.yaml`。

GitHub 的 team member 列表包含子 team 成员，因此 infra 的个人子 team 成员可按实际父组继承关系核对；这一行为依照 [GitHub Team Members API](https://docs.github.com/en/rest/teams/members?apiVersion=2022-11-28)。仓库列表依照 [GitHub Teams API](https://docs.github.com/en/rest/teams/teams)。

## GitGraph 与依赖更新的权限路径

普通用户：服务端固定 group + roster github_subject → 用户 token 的 /user 必须为同一 subject → 当前组映射的 team membership → team repos，且 pull 权限成立。没有 subject、token 不匹配、非成员或 API 不可用时，拒绝或返回明确错误，不降级到组织全部仓库。

`admin_repo_status` 与 `admin_package_updates` 共用同一可见性函数；响应带 group 和 visibility_source，供 GitGraph/Pop 识别权限来源。Admin 保留组织视角。此处实现的是仓库及依赖元数据可见范围，不等于完整分支图、后台推送或 GitHub token broker 已部署。

## 人员表再处理

46 条原始提交按邮箱归并 39 个人员标识。更新分组规则后：31 条公钥绑定候选，10 人仍有待确认项（多组、未知分组、姓名/公钥冲突或仅指纹）。31 是密钥绑定数，不是人数。

使用公钥指纹与 GitHub 已登记公钥精确比对，11 条原始提交匹配到唯一 GitHub subject；其中 10 条无冲突候选绑定补充了 github_subject。未按姓名或邮箱猜用户名。公钥匹配是身份关联证据，实际登录仍须验证私钥持有证明；不会因为在人员表中找到公钥就跳过签名认证。

本地交付：

- `.quantcode/roster-eight-groups-20260905/candidate.yaml`：REVIEW_REQUIRED 候选，不可直接用于登录；
- `.quantcode/roster-eight-groups-20260905/github-review.md`：姓名、Excel 行、建议组、精确账号匹配、实际 team 与待确认项；
- `.quantcode/github-team-crosscheck-20260905/`：带观测时间的只读快照与原始行匹配记录。

以上人员与权限明细不提交到 GitHub。角色、真实研发目录、剩余多组/密钥冲突仍需明确；本次没有激活正式 roster、创建服务器账号或授予 Admin。

## 实现与验收

八组身份已进入 SessionContext、GroupName、能力卡 owner、Memory/蒸馏治理、Subagent、Admin 全组扫描、MCP 和 UI 组校验。新增 Infra/Agent 的发布 Skill 与宿主开发工具配置；六条既有领域兼容 Compose 流保持领域定位。

- 后端全量：**1,098 passed / 4 skipped**，18.63 秒；真实 LLM 仍未启用。
- 前端 QuantCode 组件：**126 passed**；App typecheck 通过。
- Playwright：**9 passed**，12.6 秒；新增 Infra/Agent 可提交、GitGraph 入口、无自动 Admin 提权断言（浏览器 MCP 响应为 fixture）。
- 八组真实 stdio MCP smoke，包括新组工具发现和拒绝部署工具。
- 新增 subject/token 不匹配、非成员、缺失身份、API 故障、继承成员、两个 GitGraph 数据通道同界限的测试。
- GitHub 实读只证明观测时 team/成员/仓库/公钥状态，不证明尚未配置的生产身份或 token broker 已接通。
