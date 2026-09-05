"""P-09 /deploy 黑盒适配契约（specs/FUNCTIONAL_SPEC.md P-09，AG-H）。

黑盒约束：部署过程与输出**不得向非授权用户暴露部署库底层结构**
（AlphaFlow 内部模块/格式细节）。契约面刻意最窄：

- 入参：``source``（已调试代码的本地路径或非空描述）+ ctx（线程/路径注入）；
- 出参：``DeployResult``——四个字段，extra="forbid" 在类型层面锁死字段面，
  真适配器（AlphaFlow 格式）**无法**通过塞私有字段把底层结构泄进输出；
  错误信息由适配器自行拼装，同样受黑盒清单约束（tests/test_deploy_blackbox.py
  的 ``blackbox_forbidden_terms`` grep 断言）。

部署 = 写生产环境 → 门禁不在本层（在 _register.py 的 execute 里走
SSH 分级 ``enforce_ssh``，复用 AG-F 规则），适配器只管纯适配。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

# 仓库根（tools/deploy/adapter.py → tools/deploy → tools → 根）。
# artifact_path 相对路径按此解析；供 _register.py 复用，避免第二份根常量。
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class DeployResult(BaseModel):
    """部署结果（黑盒字段面，刻意最小——不含任何部署库内部结构信息）。

    - ok                  适配+入库是否成功
    - artifact_path       工件落盘路径（成功时；相对仓库根或绝对路径）
    - deploy_record_hash  部署记录哈希（成功时；sha256 hex 形态）
    - error               失败原因（黑盒安全话术，不回显底层细节）

    extra="forbid"：黑盒约束的类型层兜底——任何想把内部结构塞进输出的
    适配器实现直接 ValidationError。
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool
    artifact_path: str | None = None
    deploy_record_hash: str | None = None
    error: str | None = None


@runtime_checkable
class DeployAdapter(Protocol):
    """部署适配器协议：已调试代码 → 部署库格式 → 入库。

    真适配器（AlphaFlow 格式，规格未定——外部依赖世杰）实现本协议即可
    热替换 staging 占位（tools/deploy/staging_adapter.py），注册层不动。
    """

    def adapt(self, source: str, ctx: dict[str, Any] | None = None) -> DeployResult: ...


__all__ = ["DeployResult", "DeployAdapter", "PROJECT_ROOT"]
