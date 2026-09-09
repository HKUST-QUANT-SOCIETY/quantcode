# M2 新任务入口源码交付

状态：入口迁移源码已接线，统一开关默认关闭；未运行测试、类型检查、构建或真实任务验收。

前置材料：[M1 源码交付](RUNTIME_INTERNALIZATION_M1_IMPLEMENTATION.md)。按用户要求先依次实现，后集中验证。本表不能替代 M1 行为通过，也不授权提前切换运行服务器。

## 新任务实际链路

2026-09-09 UI 回修：提交前通过无需项目上下文的 `quantcode.workspaces.list` 发现所选宿主上的真实授权根，并重新核对缓存项目。首次单根可默认进入，多根复用 V2 目录选择；选择前绑定 `login_session_id`，宿主切换、取消或重新登录后拒绝迟到选择。loopback 不作为“本机文件系统”的判断依据。草稿页使用 QuantCode 文案，统一模式停用未接组织工作区契约的旧 worktree 创建入口；编辑器/终端继续使用现有目录 SDK。

隔离 UI 已观察首次任务原文进入正确成员目录的草稿，以及修复后目录选择器列出授权子目录；没有配置模型或运行真实研究任务，最终选择/取消和完整模型执行仍待验。

1. 桌面从服务端 capabilities 确认 `quantcodeUnifiedRuntime`。未知状态或读取失败时保留任务并提示错误，不猜测开启，也不降回旧 `run_agent` 模板。
2. 首页将原始任务文本交给既有 `tabs.newDraft(..., {submit:true})` 和 composer；已有原生任务使用该会话真实目录和当前 `useLocal` 的 agent/model/variant，通过 SDK `session.promptAsync` 提交同一 session。
3. 后端仍走同一 `SessionPrompt → SessionTools → LLM/Provider`。`task-context.ts` 加载当前组安装 Skill，并调用已发布且获准自动读取的目录/Memory 工具。实际调用产生同一原生会话的 ToolPart 与 inspection 回执，没有新的模型或任务循环。
4. 上下文按原始需求、登录与目录版本复用。失败/过期结果不会生成成功检查凭据；检索内容作为引用数据加入模型输入，不能变成组织授权规则。记录超限、取消和身份变更保持错误状态。
5. 原生消息、SSE、错误、取消和用量属于同一 session；全屏工作区提交成功后返回已有任务。完整组织 Activity/Admin/历史投影仍留到 M3。

原生 `search_memory` 强制复用 gateway 的共享 Memory 查询，缺宿主会话或共享库时明确报错，不回落成员个人数据库；读取前后验证凭据、roster 和原任务登录。旧本机分支仅保留给 legacy 执行器。

## 单一模型配置

- QuantCode 只加载宿主配置中显式声明的 OpenAI-compatible URL 和模型；API Key 只读隔离的宿主 `auth.json`。
- 不从内置供应商、models.dev、环境密钥、上游账号或项目配置继承另一套模型连接。供应商 ID 与内置同名不会带入其环境、模型表或认证加载器。
- 配置与密钥变化使 SDK 缓存失效；在途响应复验当前连接，旧流不能继续使用已撤回的配置。标题/压缩等辅助调用仍从同一已配置供应商选择模型并归属任务预算。
- `/provider` 与 `/config` 公开响应不返回 key、MCP headers/env、服务器密码或宿主私有指令。保留内部原配置只为受信任服务使用。
- QuantCode 使用既有兼容 SDK 请求路径，使模型凭据校验覆盖所有实际请求；未另建 Provider 或第二个 Python 模型客户端。

## 旧入口与 Skill 边界

- 16 份组 Skill、3 份通用 Skill 去掉强制转交 Runner、第二份模型配置、mock 交接与直接写 Memory 的指导。组由 roster 决定，方案/能力缺口由原生服务和桌面决定。
- native Python tools/list 与 tools/call 同时排除 12 个旧循环、旧方案及独立模型入口；普通组织函数和宿主只读查询不初始化 Python 模型。`match_main`、`gen_schema` 尚未接入统一受控 Provider，保持不可用，不伪造可调用状态。
- 旧 checkpoint 查询仍保留，native 前端不将旧恢复模板发送为新任务。M3 将接显式 legacy/version/owner 恢复适配；M4 才实际退役旧循环与清理兼容命名。

## 仍需最终证明

真实宿主配置/目录发布、组共享 Memory 初始化、一个实际可用模型、一个已接通组件、一次 URL/API Key 设置后的全流程任务，以及撤销密钥/取消/多成员/界面导航均未验证。现有组件的 UNAVAILABLE/STAGING 状态继续保留。

验收链必须实际完成“查询能力 → 读授权文件 → 调用已接入组件 → 记录结果”，并证明没有隐藏 Python 推理循环、第二份密钥或未计量的辅助请求。本次未宣称达到该运行验收条件。
