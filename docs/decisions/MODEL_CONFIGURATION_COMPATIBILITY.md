# 模型连接兼容

QuantCode 的新配置和凭据分别由现有 Config 与 Auth 存储。默认不扫描 OpenCode 账号、环境密钥或旧项目配置。普通用户直接在 QuantCode 的模型供应商设置里填写 URL、API Key 和模型信息。

2026-09-09 目标绑定补齐：新保存的 API Key 在现有 Auth metadata 中记录 `quantcode_base_url`，执行 Provider 仅在其与配置中的实际 API 路径一致时开放连接。这样先写密钥、后写配置失败时，新密钥不会被旧 URL 消费；配置修改为另一 URL 前，必须已有该目标的匹配密钥。旧无 metadata 凭据可继续使用现有配置，但不能经设置接口换地址而沿用它。修改地址时桌面要求重填对应 API Key，不把旧密钥静默转交给新地址。

绑定按 AI SDK 的真实拼接规则比较：无尾斜杠和一个尾斜杠表示相同 endpoint 命名空间；多个尾斜杠保留为不同路径。带 URL 用户名/密码、query、fragment 或环境变量替换的地址不进入此配置。模型列表请求及密钥写请求禁止 HTTP 重定向。桌面保存固定使用打开弹窗时的宿主，宿主切换/卸载后取消旧请求；修改表单后不采用旧模型列表响应。

需要保留旧自定义连接时，宿主维护员可显式选择一个兼容连接。`frontend/packages/opencode/script/import-quantcode-model.ts` 只接受来源配置/凭据绝对私有路径与确切 provider ID，支持原 `@ai-sdk/openai-compatible` 连接及 `type:api` 密钥；不导入 OAuth、默认供应商、额外权限、插件或组配置，不修改来源文件，不覆盖目标已有连接。

维护命令（本次未执行）：

```sh
OPENCODE_CHANNEL=quantcode bun script/import-quantcode-model.ts preview /private/old-config.jsonc /private/old-auth.json custom-provider
OPENCODE_CHANNEL=quantcode bun script/import-quantcode-model.ts import /private/old-config.jsonc /private/old-auth.json custom-provider EXACT_PREVIEW_DIGEST
```

预览仅列所选连接 URL、模型名和密钥存在状态，输出不含密钥。导入要求当前组织登录，比较来源与目标的预览摘要，沿现有宿主发布锁、私有归档和原子写入机制保存。配置与凭据是原有两个存储，先写密钥，再发布连接；若后一步失败，密钥不会被自动删除或用于另一连接，维护员可在 QuantCode 设置中补齐，避免回滚覆盖并发更新。

若源凭据已有 URL 绑定，导入必须核对其与来源配置一致；不允许将部分失败的“新密钥、旧配置”重新标记成匹配。真正无绑定的历史密钥才依据维护员明确选择的来源 URL 追加绑定。

本轮只完成源码及回归用例编写，尚未运行模型或测试。整链回归将使用真实 Auth/Config/Provider 与独立身份服务，覆盖历史原地址、换地址拒绝、部分保存期间不可用和正确完成后可用。

已运行的宿主须通过现有设置刷新配置或正常关闭后重新开启；维护命令不会重启任何服务。迁移开关和全部验收状态不由这份连接导入决定。
