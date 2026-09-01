"""staging 占位适配器（P-09 /deploy，AG-H）。

ponytail: 真适配器（AlphaFlow 部署库格式）**blocked 待外部规格（世杰）**——
目标格式 / 入库协议未定，不预造转换层。本占位只锁住接口行为
（source 校验 → artifact 副本 + sha256 记录哈希），真适配器落地时实现
``tools/deploy/adapter.py`` 的 ``DeployAdapter`` 协议、在
``tools/deploy/_register.py`` 换一行 ``_ADAPTER`` 即完成替换，其余不动。

行为（占位语义，接口已锁）：
- source 为存在的本地**文件** → 读取字节，artifact = 字节副本；
- source 为存在的目录 → 拒绝（诚实失败，不猜意图）；
- 其余非空 source → 按**非空描述**处理，描述文本即工件内容；
- 空/纯空白 source → 拒绝；
- deploy_record_hash = 工件字节 sha256（64 hex），同源重部署幂等同名。
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from tools.deploy.adapter import DeployResult, PROJECT_ROOT

# 默认工件目录（仓库根 artifacts/deploy/）；ctx["artifacts_dir"] 可覆盖（测试/多环境注入）。
DEFAULT_ARTIFACTS_DIR = PROJECT_ROOT / "artifacts" / "deploy"


def _display_path(p: Path) -> str:
    """工件路径：仓库根内给相对路径（evidence/verify_chain 按 artifacts_root 解析），
    仓库根外（测试 tmp）给绝对路径。"""
    try:
        return str(p.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(p)


class StagingDeployAdapter:
    """DeployAdapter 的 staging 占位实现（无网络、无外部依赖）。"""

    def adapt(self, source: str, ctx: dict[str, Any] | None = None) -> DeployResult:
        ctx = ctx or {}
        text = (source or "").strip()
        if not text:
            return DeployResult(
                ok=False,
                error="deploy aborted: source 为空（需已调试代码的本地路径或非空描述）",
            )

        src = Path(text)
        try:
            if src.exists() and not src.is_file():
                return DeployResult(
                    ok=False, error="deploy failed: source 路径存在但不是文件"
                )
            if src.is_file():
                data = src.read_bytes()
                stem, suffix, is_copy = src.stem, src.suffix or ".bin", True
            else:
                data = text.encode("utf-8")
                stem, suffix, is_copy = "description", ".txt", False
        except (OSError, ValueError):
            return DeployResult(ok=False, error="deploy failed: source 不可读")

        digest = hashlib.sha256(data).hexdigest()
        artifacts_dir = Path(ctx.get("artifacts_dir") or DEFAULT_ARTIFACTS_DIR)
        artifact_path = artifacts_dir / f"{stem}_{digest[:12]}{suffix}"
        try:
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            if is_copy:
                shutil.copyfile(src, artifact_path)
            else:
                artifact_path.write_bytes(data)
        except OSError:
            return DeployResult(ok=False, error="deploy failed: artifact 写入失败")

        return DeployResult(
            ok=True,
            artifact_path=_display_path(artifact_path),
            deploy_record_hash=digest,
        )


__all__ = ["StagingDeployAdapter", "DEFAULT_ARTIFACTS_DIR"]
