"""Register the /deploy black-box tool (P-09, AG-H) to the global registry.

契约红线：tool id 与 args **严格**为 ``deploy_alphaflow`` / ``{"source": string}``——
lens 的 /deploy 会话命令已按此契约注册（AG-G），改即破坏集成。

执行流程（specs/FUNCTIONAL_SPEC.md P-09）：
① Admin 管理面门禁：普通研究 Agent 不可见、不可调用；Admin Session 才能提交。
② 适配：staging 占位适配器（真 AlphaFlow 适配器 blocked 待世杰，接口已锁）。
③ 留痕：复用 ``runner/evidence.append_event``（best-effort 哈希链）追加一环
   ARTIFACT（payload 带 path/sha256/bytes，与 verify_chain 的工件重绑格式一致）。
   ponytail: append_event 本身带 ``artifacts_dir`` 形参——工具层经 ctx 注入
   （``evidence_dir`` / ``artifacts_dir``，测试与多环境用），属最小适配非新接口。
④ 返回 DeployResult 字段面（刻意最小，黑盒断言见 tests/test_deploy_blackbox.py）。

接线注意：本模块需被 import 才会注册（与 tools/risk、tools/solution 同模式）。
``quantcode/mcp_server.py`` 属 AG-C/AG-D 独占窗口，本卡不触碰；**移交项**：
AG-D 在 mcp_server 注册块补一行
``import tools.deploy._register  # noqa: F401,E402  触发 /deploy 黑盒工具注册（P-09，AG-H 移交项）``
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from runner.evidence import EVIDENCE_DIR, append_event
from tools.deploy.adapter import DeployResult, PROJECT_ROOT
from tools.deploy.staging_adapter import StagingDeployAdapter
from tools.registry import ToolDef, register_tool, registry

# ponytail: 真适配器落地时只改这一行（实现 DeployAdapter 协议即可替换）
_ADAPTER: StagingDeployAdapter = StagingDeployAdapter()


class DeployAlphaflowArgs(BaseModel):
    """lens /deploy 契约参数：严格 ``{"source": string}``，extra="forbid"。"""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(
        min_length=1,
        description="已调试代码的本地路径，或非空描述；/deploy 适配的唯一输入",
    )


def _deploy_execute(args: DeployAlphaflowArgs, ctx: dict) -> dict[str, Any]:
    ctx = ctx or {}

    # ① Admin 管理面门禁。生产部署不是普通 HumanGate。
    from runner.admin_scope import is_admin
    ident = ctx.get("identity") or ctx.get("ssh_fingerprint")
    if ctx.get("role") != "admin" and not is_admin(
        ident if isinstance(ident, str) else None, ctx.get("group")
    ):
        return DeployResult(ok=False, error="admin_only: deploy is available only from Admin management plane").model_dump()

    # 适配（staging 占位；领域性失败返回 ok=False，不抛异常——
    #    tool_node 对非 read_ 工具异常只留类名，会吞掉可纠偏原因）
    result = _ADAPTER.adapt(args.source, ctx)

    # ③ 留痕：成功部署追加 ARTIFACT 环（append_event best-effort，绝不砸主流程）
    if result.ok:
        artifact = Path(result.artifact_path or "")
        if not artifact.is_absolute():
            artifact = PROJECT_ROOT / artifact
        append_event(
            str(ctx.get("thread_id") or "deploy"),
            "artifact",
            {
                "path": result.artifact_path,
                "sha256": result.deploy_record_hash,
                "bytes": artifact.stat().st_size,
                "tool": "deploy_alphaflow",
            },
            artifacts_dir=ctx.get("evidence_dir") or EVIDENCE_DIR,
        )

    # ④ DeployResult 字段面即输出（ok/artifact_path/deploy_record_hash/error）
    return result.model_dump()


deploy_alphaflow_tool = ToolDef(
    id="deploy_alphaflow",
    description=(
        "P-09 /deploy 黑盒部署：提交已调试代码（本地路径或非空描述）到部署库"
        "适配入库。仅 Admin 管理面可调用；普通 Agent 不可见、不可调用。"
    ),
    schema=DeployAlphaflowArgs,
    execute=_deploy_execute,
    # Admin 管理面门禁；部署不经普通 Agent HumanGate。
    permission=None,
)


def register_all() -> None:
    """幂等注册（重复 id 跳过）——mcp_server import 与测试显式调用共用。"""
    if deploy_alphaflow_tool.id not in set(registry.list_ids()):
        register_tool(deploy_alphaflow_tool)


register_all()

__all__ = ["deploy_alphaflow_tool", "DeployAlphaflowArgs", "register_all"]
