# QuantCode GitHub Actions → Server B 迁移说明

> 更新日期：2026-08-17
> 适用 workflow：`.github/workflows/risk-gate.yml`

## 结论

QuantCode 最近的 GitHub Actions 红灯不是测试失败。GitHub 在分配
`ubuntu-latest` runner 前就因组织付款或 spending limit 问题拒绝启动 job。

仓库 workflow 已改为使用以下 Server B 标签：

```text
self-hosted
linux
x64
server-b-multiagent-review
```

Server B runner 已在 2026-08-17 从中央仓库专用的 repository-level runner
重注册为 organization-level runner，并放入只授权中央仓库与 QuantCode 的
`quant-review-runners` group。workflow 改动合入后，QuantCode job 不再依赖
GitHub-hosted runner 额度。

## 当前已核实状态

- Server B：`qs-compute-research-hk-01`
- runner：`server-b-multiagent-review-01`
- runner 目录：`/srv/quant/runners/multiagent-review`
- service 用户：`gha-multiagent-review`
- 当前注册范围：`HKUST-QUANT-SOCIETY` organization
- Runner Group：`quant-review-runners`（Selected repositories）
- 授权仓库：`multiagent_review_ci_standalone`、`quantcode`
- GitHub runner ID：`386`
- 当前 service：
  `actions.runner.HKUST-QUANT-SOCIETY.server-b-multiagent-review-01.service`
- runner 版本：`2.336.0`
- 当前状态：`online`

## 已执行的管理员一次性操作

以下操作已于 2026-08-17 完成，保留在此作为重建/灾备记录。它们需要 Server B
`sudo` 权限和 GitHub organization admin 权限。注册和移除 token 都是短期凭据，
不得写入仓库、shell profile、systemd unit 或长期文件。

1. GitHub organization runner group `quant-review-runners` 已创建，访问范围使用
   `Selected repositories`，首批仅加入：

   - `multiagent_review_ci_standalone`
   - `quantcode`

2. 重建时，为旧 repository runner 生成 remove token，为 organization 生成 registration token：

   ```bash
   gh api --method POST \
     repos/HKUST-QUANT-SOCIETY/multiagent_review_ci_standalone/actions/runners/remove-token

   gh api --method POST \
     orgs/HKUST-QUANT-SOCIETY/actions/runners/registration-token
   ```

   只复制响应中的 `token` 值到当前维护会话；完成后立即从终端历史和临时剪贴板清除。

3. 在 Server B 停止并卸载旧 service，然后以原低权限用户移除旧注册：

   ```bash
   cd /srv/quant/runners/multiagent-review
   sudo ./svc.sh stop
   sudo ./svc.sh uninstall
   sudo -u gha-multiagent-review ./config.sh remove --token '<repository remove token>'
   ```

4. 在同一目录注册 organization runner。不要改变 service 用户，也不要授予 runner
   Docker、生产数据库或无关密钥权限：

   ```bash
   cd /srv/quant/runners/multiagent-review
   sudo -u gha-multiagent-review ./config.sh \
     --url https://github.com/HKUST-QUANT-SOCIETY \
     --token '<organization registration token>' \
     --name server-b-multiagent-review-01 \
     --runnergroup quant-review-runners \
     --labels server-b-multiagent-review \
     --work _work \
     --unattended \
     --replace

   sudo ./svc.sh install gha-multiagent-review
   sudo ./svc.sh start
   sudo ./svc.sh status
   ```

5. 确认 runner 位于 `quant-review-runners`、状态为 `Online`，并确认
   `quantcode` 在 Selected repositories 中。

## 验收顺序

1. 在中央仓库重跑已知成功的 Server B smoke workflow，确认迁移未破坏中央引擎。
2. 在 QuantCode 手动运行 `Risk Gate` 的 `workflow_dispatch`，确认
   `QuantCode Risk Gate` 被 Server B 接单并成功。
3. 在 QuantCode 创建一个仅修改文档的 Draft PR，验证：

   - job 不再出现付款错误；
   - checkout、Python 3.12 和隔离 venv 正常；
   - Risk Gate 生成 artifact/结果；
   - 重复执行不会产生重复 PR 评论；
   - job 完成后临时 venv 被清理。

4. 观察稳定后，再决定是否将 `QuantCode Risk Gate` 设为 required check。

## 安全边界

- workflow 使用 `pull_request`，不会使用 `pull_request_target`。
- fork PR 不会在内部 self-hosted runner 上执行。
- checkout 不持久化 GitHub credentials。
- 每次运行使用 `$RUNNER_TEMP` 下的独立 venv，并对清理路径做前缀校验。
- 本迁移只修复现有 QuantCode Risk Gate。中央 Multi-Agent Review 的
  `.review-ci/` 规则需要按 QuantCode 真实目录单独设计，不能直接套用旧的
  `quant-factor-*` preset。
