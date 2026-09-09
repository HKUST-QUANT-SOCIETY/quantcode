---
name: model:pr-submit
description: 整理已授权 PR 的 ModelSpec 与证据，按当前共享服务合同交接
group: model
owner: 陈镇鸿
pattern: Native task + contract validation + exact shared write
---

# 模型 PR 与交接

在当前原生任务中处理已授权仓库的 PR。身份与 GitHub 可见范围来自宿主会话；参数不能切换组，密钥不进入任务文本、Blackboard 或 artifact。

## 输入

需要真实 PR/commit 引用、训练数据时点、模型类型、超参、特征/算子依赖与风险元数据。先查询能力目录和组 Memory，核对相关组件状态；缺失字段明确补齐，不使用默认日期、unknown_factor 或示例数字冒充真实元数据。

## 工作流程

1. 通过当前公布的 GitHub/文件读取能力取得 PR 描述与完整变更。`read_pr`、`extract_metadata` 只有在实际目录允许时使用，不绕过被禁用的本地路径分支。
2. 由当前任务模型整理候选 metadata，再调用已公布的 `generate_model_spec` 进行真实 `schemas.model.ModelSpec` 校验。模型生成内容本身不算验证通过。
3. 若用户需要共享交接，先冻结任务方案，并用 `read_blackboard({input_data:{blackboard_key:"shared.model_entries.<entry_id>"}})` 读取当前真实版本。
4. 提出 `write_blackboard({key:"shared.model_entries.<entry_id>",value:spec,expected_version:version})`。规范 key、完整 value 和预期版本一同进入当前精确 merge 审批；工具无权替用户确认。
5. 成功后引用返回的共享条目、版本、原生调用和批准回执。风险 CI/后续组件只使用实际已公布的交接接口；接口未接通时明确报告，不能调用旧队列写入绕过当前合同。

共享读写服务未配置或未发布时停在可审阅的契约与证据，不宣称交接成功。写入结果不明时先核对已有回执；不要用另一 call 或更大版本猜测重试。

## 验收

- PR/commit 与 ModelSpec 中的来源、时点和数据范围一致。
- 实际契约验证通过，并保留校验结果。
- 如果请求共享写入，只有真实服务成功结果才算完成；风险验收和生产部署仍由各自权威入口负责。
