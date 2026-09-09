---
name: fundamental-compose
description: 基本面研究任务：授权PIT资料、权威财务/估值组件与研报产物
group: fundamental
owner: 刘炽
pattern: Native task orchestration
schema_in: schemas.fundamental.ResearchSpec
schema_out: schemas.fundamental.ResearchResult
---

# 基本面研究任务

使用 roster 赋予的组身份、当前原生任务和宿主模型配置。先查询已公布的能力目录与组 Memory，再由 `organization_reuse` 记录覆盖判断；有缺口时取得用户决定。

研究顺序：确认公司/行业与 as_of_date → 读取授权资料 → 调用财务/估值组件 → 整理报告 → 用户验收。工具名称和文件中的 flow 仅描述业务流程，实际能否调用由服务端发布目录和权限决定。

能力目录可能发布 `pit_rag_search`、`extract_financial`、`dcf_valuation` 和 `render_report` 等适配器；名称本身不代表已接通。

- PIT 资料必须满足 published_at <= as_of_date，引用保留来源与时间。
- 财务数据和估值计算来自真实权威组件；fixture、stub 或 hash 造数不能作为研究结论。
- 需要写入报告文件时用 `organization_solution` 明确文件范围与验收，待当前方案冻结后执行原生写入/渲染。
- 报告内容由当前任务模型根据资料整理，不另配 Python 模型密钥。
- 报告质量验收属于任务内审阅；普通 HumanGate 仅用于真实共享写入 merge 或受限读取 permission，不创建第三种“研报审批”权限。
- 只有实际已发布的共享/发布接口及精确批准才能对外提交报告；产出本地PDF本身不表示已经发布。

完成时返回实际 artifact、引用、契约验证和组件状态。任何未接通或失败步骤如实说明，不能以固定六步或示例结果冒充完整研究流程。
