# QuantCode 功能连续性核对

核对日期：2026-09-10。范围：用户指出的 SSH 命令行连接体验、知识沉淀卡片，以及相邻功能在当前版本中的去向。用户已确认网络问题不再处理。本轮只核对代码、Git 历史、当前窗口和服务器数据，没有改产品代码、迁移数据或重启服务。

用户所说的“Clea 登录”已澄清为类似 VS Code Remote SSH 的命令行连接体验，不是 Claude/Codex 的模型账号授权。

**结论：有实际的入口替换和功能收窄，也有保留下来的数据因展示方式、搜索能力和宿主切换而不可见。不能把当前状态概括为“都删了”，也不能因为代码仍在就说“功能都还在”。**

## 1. 这次实际确认的事实

| 核对项 | 结果 | 证据类别 |
|---|---|---|
| 当前组织身份 | quantadmin，admin，当前组 agent | 当前宿主接口 |
| 能力目录 | 14 张卡；5 PARTIAL、8 UNVERIFIED、1 UNAVAILABLE | 当前 list_capabilities 返回 |
| 旧共享知识库 | 15 份 Markdown，15 条索引记录 | Server C 文件与只读 SQLite |
| 新共享知识库 | 同样 15 份；每份相对路径、内容 SHA256 与旧库一致 | 两库逐文件比较 |
| 搜索 capability | 0 条 | 当前 search_memory 返回 |
| 搜索 因子 | 0 条 | 当前 search_memory 返回 |
| 搜索 factor | 7 条，含 factor/model 组 | 当前 search_memory 返回 |
| 搜索 data_access | 3 条 | 当前 search_memory 返回 |
| 管理员知识候选 | 0 条；管理员候选目录没有 index.json | 当前接口及文件元数据 |
| 管理员发布目录 | 存在，0 份 Markdown | Server C 文件元数据 |
| 管理员旧历史 | 配置指向的新 checkpoints.db 与 legacy-provenance.json 均不存在 | Server C 文件元数据 |
| 当前模型 | organization-qwen 已连接 | 当前 Provider 接口 |
| GitGraph | 当前实际桌面能显示仓库与分支、提交数据 | 当前窗口只读观察 |

15 份知识文档是 **14 张能力卡 + 1 份平台契约**。这证明这批既有卡片保存完好；不证明所有其他机器、历史私有目录或未发布候选都已迁移。

## 2. SSH 命令行连接体验为什么不见了

### 2.1 原登录面板被新向导替换

旧 `SshLoginView` 仍在源码中，包含身份选择、目标主机、连接过程日志、指纹、组和退出。它的连接日志使用 `qc-ssh-log`，形式接近命令行连接过程。

2026-09-10 的提交 `f695394` 引入两步向导，并在存在桌面组织桥时替换旧面板。后续 `93f6796` 仅允许“已有 SSH 会话，或没有组织桥”时显示旧面板。因此正常桌面未登录时只能见到新向导，旧面板及逐行连接日志没有并列入口。

当前新向导是“选私钥 → 探测 → 选组/管理员 → 打开工作区”，连接中只显示一行进度，不展示原来的连接日志、目标信息和详细阶段。后台真实 SSH 已实现，但用户可见的连接体验被简化了。

定位：[入口条件](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/frontend/packages/app/src/components/quantcode/panels.tsx:582>)、[旧连接日志](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/frontend/packages/app/src/components/quantcode/ssh-login.tsx:247>)、[新向导](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/frontend/packages/app/src/components/quantcode/ssh-login.tsx:372>)。

### 2.2 实际终端仍在，新标题栏漏了按钮

终端组件 `TerminalPanel`、后台 PTY、工作区与身份校验仍存在。任务页也注册了 `terminal.toggle`（Ctrl + `）和 `terminal.new`。

但是旧标题栏有终端按钮，新布局 `SessionHeaderV2Actions` 只有状态、审查和 QuantCode 面板，没有终端按钮。当前窗口实际展示的就是后一种布局。用户看不见入口，不等于终端底层已经删除；同时也不能仅凭快捷键代码存在，就宣称远程终端实机完整可用。

定位：[旧按钮](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/frontend/packages/app/src/components/session/session-header.tsx:455>)、[新标题栏](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/frontend/packages/app/src/components/session/session-header.tsx:537>)、[终端命令](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/frontend/packages/app/src/pages/session/use-session-commands.tsx:507>)、[终端挂载](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/frontend/packages/app/src/pages/session.tsx:1885>)。

### 2.3 “服务器状态”页面不等于远程终端

当前服务器页面只执行固定的系统、运行时长和磁盘状态查询，没有交互式命令输入。它不能替代 VS Code Remote SSH 的远程工作区/终端体验。

历史审计也曾明确记录“SSH 身份登录不等于远程 IDE 已完成”。因此本轮可以确认旧连接面板被隐藏、终端按钮遗漏；没有充分证据把一套完整且曾经实机验收的 VS Code 式 Remote SSH 产品描述为后来被整体删掉。

建议保留两步登录，同时提供清楚的“连接详情”和工作区终端入口，复用同一身份与连接；不再拆出第二套工作/运维账号。

## 3. 知识沉淀卡片为什么看起来没了

### 3.1 三种资产被分到了不同入口

| 资产 | 当前来源 | 当前入口 | 问题 |
|---|---|---|---|
| 组件能力卡 | configs/capabilities.yaml | 能力目录 → 组织组件 | 14 张保留，但接口说明字段缺失 |
| 共享长期知识 | Gateway 的 Markdown 与 FTS 索引 | Memory → 长期知识 | 只有搜索，没有默认卡片浏览/总量/正文阅读 |
| 工具序列沉淀候选与发布 Skill | 当前宿主的 knowledge/candidates、knowledge/published | Memory → 知识候选审核 | 新管理员宿主为空；审核列表没有组织范围聚合 |

这三个入口不是同一张表。修好 `list_capabilities` 的 14 张卡，不能算完成长期知识浏览和候选沉淀验收。

### 3.2 原能力卡接口说明被实际移出返回值

提交 `22faa90`（2026-09-05）从 `_list_capabilities_execute` 的返回卡片中删除了 `api_surface`。配置仍保留该字段，前端“接口与契约”也仍会尝试显示它，但现在服务端没有返回。来源没有丢，页面确实少了原有内容。

定位：[返回卡片](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/runner/distill/cards.py:198>)、[前端接口说明](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/frontend/packages/app/src/components/quantcode/capability-catalog.tsx:161>)。恢复时应使用已有可见性处理后的卡片字段，继续遵守组权限，不绕过原 Mask。

### 3.3 共享库已经迁移，但展示与检索不够用

旧库：`/home/ubuntu/quantcode-gateway-data/shared-memory`。

当前库：`/var/lib/quantcode-test-v1/gateway/shared-memory`。

两库的 15 份 Markdown 相对路径和内容摘要一致，索引都为 15 条，新库索引路径也已指向新根。不存在“这批能力卡忘了复制”的证据。

实际问题有两个：

- Memory 初次进入默认显示空查询提示，不列已有知识；没有“全部卡片”“按组浏览”“最近更新”等发现入口。
- 检索使用 Unicode61 全词匹配。`capability` 不等于正文中的 `CapabilityCard`；中文短词也不自动分词或前缀匹配。实际“因子”返回 0，`factor` 返回 7、`data_access` 返回 3。零命中不能证明库是空的。

定位：[首屏空态](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/frontend/packages/app/src/components/quantcode/memory-query.tsx:258>)、[查询构造](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/runner/memory/query.py:32>)、[索引分词器](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/runner/memory/fts.py:87>)。

### 3.4 管理员候选审核仍然只看当前宿主

安装器给每个人设置独立的 `QUANTCODE_DISTILL_CANDIDATES_DIR` 和 `QUANTCODE_DISTILL_PUBLISH_ROOT`。管理员宿主也得到一套新的空目录。

`list_candidates` 的 admin 分支只是不限制“这个目录内的组”，没有去读取其他成员宿主或历史候选库。虽然原生任务索引已有知识候选摘要的投影代码，当前候选审核页仍直接访问本宿主 list 接口。管理员角色因此不能自动获得全组织候选列表。

当前管理员及核对的成员参考宿主候选目录都是空的。本地旧 `.quantcode/distill_candidates` 仍有历史样本，但其中包含 unknown/测试工具来源，不能直接当成已批准的组织知识导入。

定位：[宿主目录配置](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/scripts/install_native_host.py:286>)、[审核范围](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/runner/distill/governance.py:362>)、[当前审核页](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/frontend/packages/app/src/components/quantcode/panels.tsx:1764>)。

## 4. 相邻功能去向清单

| 功能 | 当前去向/变化 | 判定 |
|---|---|---|
| 两步组织登录 | 原生私钥选择、SSH、正式组织会话 | 主流程保留，旧连接体验未保留 |
| CLI/远程连接详情 | 旧面板被向导替换，新面板没有逐行日志 | 入口与体验回退 |
| 工作区终端 | PTY 和组件在，V2 标题栏无按钮 | UI 入口遗漏；实机终端待专项验收 |
| 能力卡 | 14 张仍在，api_surface 不返回 | 部分内容回退 |
| 长期知识 | 15 份保留，只能输入词检索 | 浏览能力缺失，检索体验有缺口 |
| 知识候选审核 | admin 有页签，但只读当前新宿主 | 组织范围接入缺口 |
| 旧任务/检查点 | 执行记录拆为原生历史和归档任务；管理员新 legacy 路径为空 | 新旧历史连续性未接齐，不等于旧文件已删除 |
| 组 Skill 选择器 | unifiedRuntime 下隐藏，改为按组织身份自动读取 | 产品行为改变；需展示实际加载清单，不能用空选择器或一句提示代替 |
| 管理概览 | 原 AdminConsoleView 改成原生组织任务概览 | 旧语义查询/分组运行/错误沉淀视图不再通过原组件呈现；需逐项对齐数据映射 |
| 方案与审批 | 转到原生任务内的方案、预算、精确审批页 | 有对应实现；需进入具体任务，不能把首页空态判为删除 |
| GitGraph | 独立 GitGraph 页面，当前实际可见仓库、分支及提交 | 保留；先前缺管理员绑定已另行处理 |
| 模型连接 | 只显示 URL/API Key 自定义供应商；统一运行时拒绝 OAuth 凭据并跳过插件 hooks | 明确功能收窄，属于另一个问题，不是用户所说的 CLI 登录 |
| 部署 | 组织管理 → 部署，仍有 DeploymentPanel | 入口仍在；存在入口不代表生产部署链已验收 |

模型范围证据：[供应商过滤](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/frontend/packages/app/src/hooks/use-providers.ts:28>)、[凭据限制](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/frontend/packages/opencode/src/auth/index.ts:93>)、[插件跳过](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/frontend/packages/opencode/src/plugin/index.ts:137>)。本轮未取得旧模型 OAuth 界面在本项目完整可用的历史运行证据，不将它写成“已完成后又删除”。

## 5. 为什么会发生这些问题

1. **替换入口时没有建立功能保留清单。** 新登录向导替换了旧面板；新标题栏没有承接终端按钮。底层尚在，但产品入口已经少了。
2. **统一执行器迁移改变了数据来源。** `unifiedRuntime` 同时改变 Skill、历史、审批、管理概览等分支，旧组件与新组织投影没有逐项对应验收。
3. **新管理员宿主被当成了完整管理员工作台。** 签发 admin、打开工作区、模型能执行已经成立；候选库和 legacy 历史的组织汇总没有随之完成。角色权限不能补出未连接的数据源。
4. **验证粒度过小。** 接口成功、卡片数量或大量单元测试通过，均不能证明用户能找到旧功能、读到原卡片字段、浏览旧知识和审核跨成员候选。之前我用这些结果宣布“完整工作台恢复”，范围说大了。
5. **源码、部署与历史报告有多个基线。** 当前前端为 `93f6796` 加未提交修复；管理员宿主清单登记构建来源为 `009dde4`，Python runtime 为 `test-v1-20260909-02`。9 月 8 日的待验报告与 9 月 9 日 Test V1 验收记录描述不同阶段，必须依据具体入口和当前部署复核，不能混用通过结论。

## 6. 建议的恢复顺序与验收

| 顺序 | 工作 | 验收方式 |
|---|---|---|
| 1 | 保留两步登录，恢复连接详情、逐阶段日志和可发现的终端入口 | 从实际桌面完成选钥、连接、打开授权工程、打开终端；确认命令运行位置与当前账号 |
| 2 | 恢复能力卡 api_surface，并提供知识库默认浏览、分类、总量及正文/来源查看 | 14 张能力卡字段对照配置；15 份长期文档可浏览；中文短词与组件名检索有明确、合理的结果 |
| 3 | 整理候选及已发布 Skill 的组织索引和历史接入 | admin 看到授权范围内跨成员候选；能看来源、状态和正文；普通成员范围不扩大 |
| 4 | 对照旧历史、组 Skill 和管理卡片逐项补接 | 明确每个旧入口的新位置、数据源和缺口；迁移前后记录数及来源一致 |
| 5 | 建立功能连续性验收表 | 每项同时记录“设计要求、旧入口、当前入口、当前数据源、实机证据”；不能只用通过用例总数销项 |

本轮交付的是核对与恢复清单。网络问题已排除在本轮范围之外；上述缺口没有在审计过程中被悄悄修改或重新设计。


后续修复与当前验证状态见 [功能连续性修复记录](FEATURE_CONTINUITY_REPAIR_2026-09-10.md)。
