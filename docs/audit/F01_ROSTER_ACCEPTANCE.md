# F-01 人员表导入与身份验收

日期：2026-09-05。功能依据：FUNCTIONAL_SPEC F-01/F-05、D-001/D-010。

## 已完成

- `python -m quantcode.roster` 从指定列读取问卷 xlsx，不导入 IP、来源位置、答卷耗时等与授权无关的数据。
- 常见业务组名称映射到八组；CTA 映射 strategy。基建、AI Agent、多组填写等不自动映射，也不自动授予 approver/admin。
- 公钥通过 OpenSSH 验证。缺少类型前缀时只根据 blob 内部算法恢复；只有 SHA256 指纹的记录不冒充完整公钥。
- 重复邮箱归并为稳定 actor 标识，保留来源行；同邮箱姓名/组冲突、不同身份共用公钥均隔离。多台设备的不同公钥可属于同一 actor。
- 邮箱不自动变成 GitHub subject；不生成 repo 权限。角色默认最低 analyst，仅有对应组 Memory scope。
- 生成独立的 REVIEW_REQUIRED 候选；运行时拒绝将候选当正式授权文件。输出目录 0700，文件 0600；人员表及导入结果在本地保存，未提交 Git。
- 修复正式 roster 中重复指纹的读取不一致：以前 load_bindings 取末条、resolve_identity 取首条；现在冲突统一拒绝，相同条目去重。
- 修复生产会话在 roster 第二次读取失败时吞异常、继续冻结不完整 context；现在明确拒绝。

## 可复现导入

安装可选依赖 `pip install -e '.[roster]'` 后：

```sh
python -m quantcode.roster /path/to/roster.xlsx \
  --output .quantcode/roster-review-new \
  --workspace-root /srv/quant/users
```

工作目录根是拟定的服务器研发目录，导入不会创建服务器账号/目录，不会修改 SSH authorized_keys，不会自动激活授权。每次导入要求新的输出目录，避免覆盖先前确认记录。

本次 46 条提交按邮箱归并 39 个标识；历史候选文件保留原始 `REVIEW_REQUIRED` 结果。当前已激活 37 条组员绑定和 1 条本机 Lead/Admin 运维身份；张佳音为 `model + factor(Mining)`，杨欣琳为 `model + agent`，其余已确认的冲突归组已收敛。当前仍有 3 个身份案例待处理：张博睿、李卓缺完整公钥；叶易涵两条邮箱记录共用同一把 RSA 公钥。问题可重叠。

## 验证

`tests/test_roster.py` 使用临时生成的 SSH 密钥，无人员私钥、无外网调用：

- 实际 ssh-keygen 校验、裸公钥恢复和畸形/私钥文本拒绝；
- 重复记录归并、不同人员共用密钥、多组冲突与最低权限；
- REVIEW_REQUIRED 候选拒绝加载；
- 真实 OpenSSH 签名 → challenge 验证 → roster → SessionContext，重复使用 challenge 被拒；
- 真实生产模式 MCP 子进程加载测试 roster，session_context 返回 actor/group，run_agent 跨组参数被拒；
- 生产会话 roster 读取失败不放行。

这些是本地真实性测试，不是生产 SSH gateway/桌面 Keychain 登录完成证明。生产模式子进程的 fingerprint 来自受信任测试宿主；对实际宿主是否正确验证公钥所有权，需要 gateway 接入验收。

## 尚需明确的组织配置

1. 3 个剩余身份案例的完整公钥/邮箱归并确认。
2. 哪些 actor 是 approver/admin。人员表没有角色字段，不能推断。
3. 正式服务器 workspace 根及 SSH gateway 入口的运维核对。
4. 实际研发服务器 workspace 根及 SSH gateway 入口。候选路径不是已部署路径。
5. GitHub subject 与授权 token 的服务端绑定，不以邮箱代替用户名。

对应人员与原 Excel 行号只在 `.quantcode/roster-import-20260905/review.md` 中保存。当前已将 37 条组别唯一、公钥完整且无冲突的绑定激活到受保护的 `.opencode/authorized_groups.yaml`，另加入 1 条本机 Lead/Admin 运维身份；张佳音现登记为 `model` 主组并授权 `factor`（QuantCode 对应 Mining），Session 每次仍只选择一个固定组；张博睿、李卓的指纹-only 记录和叶易涵的共用公钥记录仍未放行。F-01 标记为“部分激活，生产人员授权待确认”，不能把整张人员表标记完成。

最终后端回归：2026-09-05，Python 3.12，**1,142 passed / 4 skipped**，4 项真实 LLM 未启用；ToolDef 外部 `schema` 契约通过 alias 保留，字段遮蔽告警已消除。
