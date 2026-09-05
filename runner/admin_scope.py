"""Admin 角色判定（P-08）——Admin 是**角色**而非第七组（不进 GroupName 枚举）。

规格来源：``specs/FUNCTIONAL_SPEC.md`` P-08（"实现为角色而非第七研究组——不进
GroupName 枚举，走 identity/permission role 判定"）与
``docs/audit/PLAN_SPEC_V02_DISPATCH.md`` AG-D 卡片（交付①：Admin 判定，
identity role / ``QUANTCODE_ADMIN=1``，fail-closed）。

判定源（短路顺序，见 :func:`is_admin`）：
1. env ``QUANTCODE_ADMIN=1`` —— host 对管理进程的显式提权（进程级，最简）；
2. identity（SSH 指纹）在 admin 名单 —— 名单暂挂 identity 绑定 YAML
   （``.opencode/authorized_groups.yaml``）条目的 ``role: admin`` 字段
   （绑定格式见 ``quantcode/identity.py`` 模块头）。

fail-closed：名单读取/解析异常、identity 缺失、env 非 ``1`` → 一律非 Admin。

ponytail: 名单权威源待 G4（permission_engine）接管后迁移——届时只改本模块
``admin_fingerprints`` 一个函数，工具侧 ``is_admin`` 签名不变。
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

# 显式提权 env：值必须精确为 "1"（"true"/"yes" 不算，避免宽松误放行）。
ADMIN_ENV_VAR = "QUANTCODE_ADMIN"

# 绑定条目里的 admin 角色标记（role 字段值，大小写不敏感）。
ADMIN_ROLE = "admin"


def admin_fingerprints(path: Path | str | None = None) -> frozenset[str]:
    """读 admin 名单：绑定文件里带 ``role: admin`` 的指纹集合。

    文件缺失 / 无命中 → 空集；读取或解析异常 → 空集（fail-closed）。
    """
    try:
        from quantcode.identity import DEFAULT_BINDINGS_PATH

        p = Path(path) if path is not None else Path(DEFAULT_BINDINGS_PATH)
        if not p.exists():
            return frozenset()
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        out: set[str] = set()
        for item in data.get("bindings") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("role", "") or "").strip().lower() != ADMIN_ROLE:
                continue
            fp = str(item.get("fingerprint", "") or "").strip()
            if fp:
                out.add(fp)
        return frozenset(out)
    except Exception:  # ponytail: fail-closed —— 名单读不了就当没有 admin
        return frozenset()


def is_admin(identity: str | None, group: str | None = None) -> bool:
    """判定调用者是否 Admin 角色。

    - ``identity``：调用者身份标识（当前 = SSH 公钥指纹，与
      ``quantcode.identity`` 绑定同源）；``None``/空 → 非 Admin。
    - ``group``：当前不参与判定（Admin 是角色不是组）；保留入参作为 G4
      permission_engine 接管后的组级策略扩展位（签名前向兼容）。

    判定源（短路）：
    1. env ``QUANTCODE_ADMIN=1``（host 显式提权）；
    2. ``identity`` 在 :func:`admin_fingerprints` 名单内。

    任何异常 → ``False``（fail-closed）。
    """
    try:
        if os.environ.get(ADMIN_ENV_VAR, "").strip() == "1":
            return True
        ident = (identity or "").strip()
        return bool(ident) and ident in admin_fingerprints()
    except Exception:
        return False


__all__ = ["ADMIN_ENV_VAR", "ADMIN_ROLE", "admin_fingerprints", "is_admin"]
