# Quant Code Multi-Agent Review 与 Server B 运维说明

> 更新日期：2026-08-17
> Workflow：`.github/workflows/review.yml`
> Repository config：`.review-ci/`

## 当前结论

Quant Code 的目标流程是：仓库内部分支提交 PR 后，由 GitHub 调用中央 Multi-Agent Review。旧的 `Risk Gate` workflow 只执行单一业务风控流程，并且每次安装完整 Quant Code，不能承担通用代码审查职责。

新 workflow 已按以下方式设计：

1. `Quant Physical Gates` 运行不依赖 Quant Code 的 deterministic checks。
2. `Quant Multi-Agent Review` 读取 physical artifact，运行 Quant Code 专属 reviewer matrix。
3. arbiter 输出 `pass / warn / block`，workflow 更新同一条 PR 评论。
4. 两个 job 都使用 Server B 的受限 runner，不使用 GitHub-hosted runner 额度。
5. 两个 job 都调用固定 SHA 的预构建 review engine，不创建临时 Quant Code venv，也不安装 Quant Code。

## 部署状态

| 项目 | 状态 | 证据或待办 |
|---|---|---|
| Server B organization runner | 完成 | runner ID `386`，状态 `online` |
| Runner Group | 完成 | `quant-review-runners`，只授权中央仓库与 `quantcode` |
| 中央引擎固定版本 | 完成 | `374e0176fecb21b1729bf38fcaf205580793afc6` |
| Server B 预构建环境 | 完成 | `/opt/quant-review-ci/releases/374e0176fecb21b1729bf38fcaf205580793afc6`，含 root-owned bootstrap config |
| wheel SHA-256 | 完成 | `8632262aef058ce81adf6eecb1ca1a5e75040ab263e69a9bf9f829b869d9e003` |
| Quant Code repository variables | 完成 | `REVIEW_CI_REF`、`REVIEW_CI_PROFILE=quantcode`、DeepSeek endpoint/model |
| `deepseek-review` Environment | 已创建 | Quant Code repository environment 已存在 |
| `DEEPSEEK_API_KEY` | 未完成 | 中央仓库的 Environment secret 无法由 GitHub 读取或复制，需要管理员向 Quant Code 环境写入同一密钥 |
| Workflow 与 `.review-ci` 合入 main | 未完成 | 当前随接入 PR 评审 |
| Quant Code 专属矩阵实跑 | 未完成 | 接入 PR 合入后，用下一条内部测试 PR 验证 base SHA 配置 |

只要 `DEEPSEEK_API_KEY` 尚未写入 Quant Code 的 `deepseek-review` Environment，physical gates 可以运行，agent review 会因 `--require-llm` 失败。不能把这种状态标记为“部署成功”。

## Reviewer matrix

`.review-ci/reviewer_matrix.yaml` 定义六个 reviewer：

| Reviewer | 主要目录 | 阻断重点 |
|---|---|---|
| Contract Boundary | `schemas/`、Blackboard/HumanGate 契约、`.review-ci/` | 不兼容 schema、scope 越界、HumanGate 绕过 |
| Agent Runtime | `runner/`、`quantcode/`、`dream/`、routing/memory tests | 未注册命令执行、重复副作用、checkpoint 或 dedupe 失效 |
| Factor Pipeline | `tools/factor/`、AutoEval flow、factor tests | 未来数据、公式语义、指标方向、mock 冒充真实结果 |
| Model and Risk | `tools/model/`、`tools/risk/`、Risk Gate flow | 时序泄漏、宽松默认值、阈值或 HumanGate 绕过 |
| Research Workflow | Fundamental、Strategy、Options | PIT、成交时序、成本约束、部署人审 |
| CI and Supply Chain | `.github/`、scripts、依赖文件、docs | secret、未固定依赖、信任边界、生产写入 |

改动文件可以属于多个 category，因此同一个 diff 可以由多个 reviewer 交叉检查。没有相关文件的 reviewer 返回 benign skip，不阻断 PR。

## Gate policy

`.review-ci/gate_policy.yaml` 当前策略如下：

| Gate | 状态 | 是否阻断 | 原因 |
|---|---|---|---|
| `secret_gate` | 启用 | blocker 时阻断 | 所有 PR 必须检查凭据泄漏 |
| `prod_path_gate` | 启用 | blocker 时阻断 | 防止研究代码直接写受保护 Server A/B 或 COS 路径 |
| `schema_gate` | 启用 | 解析失败时阻断 | JSON/YAML 必须可解析 |
| `shell_syntax_gate` | 启用 | shell 语法错误时阻断 | 不需要安装业务依赖 |
| `reproducibility_gate` | 启用 | important 及以上阻断 | 模型随机性与 wall-clock 时间必须显式化 |
| `pytest_gate` | 禁用 | 不参与 | Review job 不安装 Quant Code；完整测试属于独立 CI |
| `artifact_contract_gate` | 禁用 | 不参与 | 当前仓库尚未形成统一、可验证的 artifact manifest |

启用 `pytest_gate` 的前提是另建固定 Quant Code 测试镜像或 wheelhouse，并由独立测试 workflow 使用。不要在 reviewer job 中恢复 `pip install -e .`。

## 可信配置与首个 PR

Workflow 从 PR 的 base SHA 检出 `.review-ci/`，不使用 head SHA 中刚修改的规则。这可以阻止 PR 为自己关闭 gate 或放宽 reviewer。

因此首个接入 PR 有一个预期的 bootstrap 行为：main 尚无 `.review-ci/`，该次运行使用 Server B 固定引擎目录下 root-owned 的 `profiles/quantcode`。这三份文件与本 PR 的候选配置一致，但 runner 用户不能修改。接入 PR 合入 main 后，下一条 PR 改为使用 base SHA 中的 Quant Code matrix 和 policy。验收不能只看 bootstrap PR 变绿。

## Server B 固定环境

当前预构建环境：

```text
/opt/quant-review-ci/releases/
└── 374e0176fecb21b1729bf38fcaf205580793afc6/
    ├── ENGINE_REF
    ├── WHEEL_SHA256
    ├── requirements.freeze
    ├── profiles/quantcode/
    │   ├── reviewer_matrix.yaml
    │   ├── gate_policy.yaml
    │   └── repo_profiles.yaml
    └── venv/bin/quant-review-ci
```

目录和文件由 `root:root` 持有，runner 服务用户 `gha-multiagent-review` 只有读取和执行权限。Workflow 同时检查：

- `REVIEW_CI_REF` 必须是 40 位 commit SHA；
- 对应目录必须存在；
- `venv/bin/quant-review-ci` 必须可执行；
- `ENGINE_REF` 必须与 repository variable 完全一致。

升级中央引擎时，先为新 SHA 构建 wheel，在新目录完成安装和 smoke test，再修改 `REVIEW_CI_REF`。不要原地覆盖旧目录。回滚只需把变量改回仍保留的旧 SHA。

## GitHub 配置

Repository variables：

```text
REVIEW_CI_REF=374e0176fecb21b1729bf38fcaf205580793afc6
REVIEW_CI_PROFILE=quantcode
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

Repository Environment `deepseek-review`：

```text
Secret: DEEPSEEK_API_KEY
```

密钥只配置在 Environment。不要写入 repository variable、workflow、Server B 文件、shell profile 或 artifact。

## Runner 状态

- Server B：`qs-compute-research-hk-01`
- 管理登录：`ubuntu@qs-compute`，可非交互 sudo
- runner：`server-b-multiagent-review-01`
- runner 目录：`/srv/quant/runners/multiagent-review`
- service 用户：`gha-multiagent-review`
- service：`actions.runner.HKUST-QUANT-SOCIETY.server-b-multiagent-review-01.service`
- labels：`self-hosted`、`linux`、`x64`、`server-b-multiagent-review`
- Runner Group：`quant-review-runners`
- 授权仓库：`multiagent_review_ci_standalone`、`quantcode`

## 验收顺序

1. 向 Quant Code 的 `deepseek-review` Environment 写入 `DEEPSEEK_API_KEY`。
2. 确认接入 PR 的 bootstrap physical 和 agent jobs 都完成。
3. 合入接入 PR，让 `.review-ci/` 成为 main 的可信 base 配置。
4. 新建一条仅修改文档的内部测试 PR，确认六个 reviewer 正常选择或 benign skip，且只有一条 bot 汇总评论。
5. 新建一条故意包含无效 YAML 的测试 PR，确认 `schema_gate` 阻断；测试后关闭该 PR，不合并。
6. 稳定运行后，把 `Quant Physical Gates` 和 `Quant Multi-Agent Review` 配成 branch protection required checks。

## 安全边界

- 使用 `pull_request`，不使用 `pull_request_target`。
- fork PR 不进入内部 self-hosted runner。
- checkout 不持久化 GitHub credentials。
- PR source、base 配置和 review engine 分开存放。
- physical job 不接触 DeepSeek secret。
- review job 不安装、不导入、不执行 Quant Code 业务包。
- 生产发布、Server A/B 写入和 HumanGate 决定仍是独立的人审流程。
