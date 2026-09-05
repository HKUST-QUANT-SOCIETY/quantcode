---
name: infra
description: 基础设施组的研发环境、组件接入、测试与可观测性任务
group: infra
---

# 基础设施组

服务端认证组必须为 `infra`。本组是工作职责，不是 Admin 角色。

1. 先查询 Capability Catalog 和本组长期 Memory，复用组织现有组件。
2. 对任务分级；L2/L3 在 SolutionDoc 冻结后才开始实现。
3. 通过宿主开发工具在已授权研发工作区完成研发环境、组件接入、测试与可观测性，执行相应测试。
4. 输出变更、测试证据、artifact 来源与未完成项。知识先形成候选，确认后再晋升。
5. GitGraph 只消费已验证 GitHub subject 在映射 team 下可见的仓库；组名本身不授予仓库权限。
6. 普通 HumanGate 仅 merge/permission；生产部署属于独立 Admin 管理面。本组不获得生产 shell 或部署权限。
