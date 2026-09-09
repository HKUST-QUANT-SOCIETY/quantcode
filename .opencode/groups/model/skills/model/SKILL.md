---
name: model
description: 模型组任务工作流：文献、ModelSpec、已接入训练组件与风控交接
group: model
owner: 陈镇鸿
pattern: Native task orchestration + exact HumanGate
schema_out: schemas.model.ModelSpec
---

# 模型组任务

组身份由 roster 登录会话固定。本 Skill 描述模型组职责，不授予组、角色、目录或工具权限。

在当前 QuantCode 原生任务中完成理解、计划、工具调用和结果汇报。桌面配置的一份 URL/API Key 由宿主 Provider 提供；不把整段任务交给另一个 Python Agent，也不要求第二份模型密钥。需要并行时使用当前引擎公布的原生子任务工具，继承父任务身份、目录、预算和方案。

## 执行顺序

1. 查询实际公布的 `list_capabilities` 和 `search_memory`，核对模型、特征、标签和训练组件的真实接入状态。
2. 使用 `organization_reuse` 查看或提出覆盖判断；能力不足时，由用户在任务界面决定下一步。不能以 Skill 文本或模型布尔值替代这个决定。
3. 使用 `organization_solution` 提出目标、验收要求和具体文件范围；需要方案的写入等待当前版本冻结。方案改变后重新确认。
4. 文献任务加载 `model-lit-review`；PR/契约整理加载 `model-pr-submit`。模型提出内容不等于契约已经验证；通过实际公布的验证工具取得结果。
5. 训练、OOS、特征预处理和风险计算调用组织权威组件；QuantCode 只适配契约、组织任务和记录结果。缺组件时保留 UNAVAILABLE/PARTIAL/STAGING。
6. 共享写入和受限读取只通过当前公布的工具及其精确 merge/permission 审批。预算耗尽或任务取消时停止执行。

## 产出与验收

`schemas.model.ModelSpec` 的核心字段包括 model_name、model_type、code_path、training_data_start、training_data_end、as_of_date、hyperparameters、feature_dependencies、operator_dependencies 和 risk_metadata。缺少真实值时明确列出，不能以 UNKNOWN 或 mock 数据完成交接。

- 当前任务的工具事件、用量、子任务、取消和回执来自同一原生任务流。
- 契约校验结果、组件来源/版本/环境与 artifact 均可追溯。
- 共享 Blackboard 只有完整成功回执才算写入；未知结果先核对，不能自动重放。
- 风控判定由风险组件负责；本组不宣称最终风险放行或生产部署成功。
