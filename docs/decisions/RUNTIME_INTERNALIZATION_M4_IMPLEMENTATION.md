# M4 入口和发布收敛源码交付

状态：实现待验，未启用迁移、未退役真实历史库、未重启已有服务。M0～M3交付核对完成后进入本阶段；完整编译、桌面UI、用例和安装验收仍待执行。

- 新任务目录沿已有MCP准入排除旧Runner/通用子Agent；直接Python AgentRunner、并行和Compose执行入口在双迁移开关下同样拒绝。受信legacy宿主只授权已登记的精确恢复实例，不能用新task、组或Skill绕过。Memory、Blackboard、组件服务和非迁移环境历史保留。
- QuantCode本产品的升级和安装沿已有Electron发布机制。Installation底层、global升级和WSL上游安装入口不再另装OpenCode；仍可连接受信的QuantCode执行宿主。内部协议、包名和环境变量兼容不批量改名。
- QuantCode模型始终是显式URL/API Key连接，构建和运行不再通过models.dev填默认供应商。既有Config/Auth路径保留，宿主显式导入旧自定义连接的说明与工具见 `MODEL_CONFIGURATION_COMPATIBILITY.md`；来源文件和目标已配置连接不覆盖。
- 桌面身份/GitHub桥改用Node原生进程接口，兼容已有Electron utilityProcess；本仓构建继续打包现有Node服务，不需要单独的OpenCode应用。组织Python服务在受信执行宿主按现有部署流程配置，用户不维护第二个模型key。
- 原LICENSE字节及来源摘要通过既有prebuild复制到安装包资源，第三方来源名称保留。产品日志、任务、设置与历史UI使用QuantCode语义；数据文件名仍按兼容约定读入。
- 历史兼容保留原生EventTable、Python checkpoint、来源声明、回执、用量和旧投影归档。任何正式切换须通过下一阶段验收，不把代码守卫存在当成执行已验证。

2026-09-09 增量：增加[个人原生宿主安装准备](NATIVE_RESEARCH_HOST.md)，使用现有 compiled CLI `serve`、完整构建资产及已登记研究 UID，不把 Python MCP 的 native 标志当成 HTTP 统一引擎。默认只读计划，显式 apply 仅新建版本、独立控制目录、私有访问凭据和 unit，不启动、不重启、不覆盖旧历史。该工具尚未执行，实际远端运行与单次模型配置闭环仍待验收。

下一步严格遵守用户顺序：先让当前源码可运行并核验桌面UI，修好UI后再收集并运行全部用例、类型/构建/打包及真实权限与组件场景。保留的1300个旧用例nodeid须逐项对照；缺项/跳过/外部阻断都不能算“全部通过”。
