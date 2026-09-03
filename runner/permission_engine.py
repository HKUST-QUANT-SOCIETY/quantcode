"""permission_engine — G4-A1 权限三态（allow / ask / deny）。

单一配置真相源：``configs/permissions.yaml``（key 是 ``<group>.<tool_id>``
或裸 ``<tool_id>``）。缺失配置 → allow（向后兼容，行为与今天一致）。

- deny  → ``check`` 抛 ``PermissionError``（tool_node 转 tool_result error）
- ask   → 未批准时 ``needs_human`` 信号；``tool_node`` 交由 LangGraph
  ``interrupt()`` 暂停，复用 ``human_gate.build_interrupt_payload``，
  HumanGate approve resume 后放行（**不造第二套人审系统**）。

ToolDef.permission 只是声明性元数据（registry 校验合法值），执行层只认
yaml——避免 mock/同名真工具在六组 e2e 里行为漂移。
"""
from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any

import yaml

VALID_PERMISSIONS = ("allow", "ask", "deny")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PERMISSIONS_FILE = PROJECT_ROOT / "configs" / "permissions.yaml"


@functools.lru_cache(maxsize=1)
def _load_cached(path: str) -> dict[str, str]:
    """读取 path 的 permissions 映射；文件缺失允许本地默认策略，配置损坏则拒绝启动该读取。"""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"permissions config is unreadable or invalid: {p}") from exc
    permissions = data.get("permissions") if isinstance(data, dict) else None
    if permissions is None and isinstance(data, dict):
        return {}
    if not isinstance(permissions, dict):
        raise ValueError(f"permissions config must contain a mapping: {p}")
    invalid = [str(k) for k, v in permissions.items() if str(v).strip().lower() not in VALID_PERMISSIONS]
    if invalid:
        raise ValueError(f"permissions config has invalid values for: {', '.join(invalid)}")
    return {str(k): str(v).strip().lower() for k, v in permissions.items()}


def load_permissions() -> dict[str, str]:
    """加载当前生效的 tool -> permission 映射（带缓存）。"""
    path = os.environ.get("QUANTCODE_PERMISSIONS_FILE") or str(DEFAULT_PERMISSIONS_FILE)
    return _load_cached(str(path))


def reset_cache() -> None:
    """env 覆盖 / 配置热更后清缓存（测试用）。"""
    _load_cached.cache_clear()


def _lookup(tool_id: str, group: str) -> str | None:
    perms = load_permissions()
    if group:
        v = perms.get(f"{group}.{tool_id}")
        if v:
            return v
    return perms.get(tool_id)


def check(tool_id: str, group: str = "", ctx: dict | None = None) -> dict[str, str]:
    """返回 ``{"decision": allow|deny|ask, "reason"}``。

    - deny → 直接抛 ``PermissionError``
    - ask 且 ``ctx["human_approved"]`` 为真（HumanGate approve 流程注入）→ allow
    - ask 未批准 → 返回 ``{"decision": "ask", ...}`` needs_human 信号
    """
    ctx = ctx or {}
    entry = _lookup(tool_id, group) or "allow"
    if entry not in VALID_PERMISSIONS:
        entry = "allow"
    key = f"{group}.{tool_id}" if group else tool_id
    if entry == "deny":
        raise PermissionError(f"tool '{key}' denied by permissions config")
    if entry == "ask" and not ctx.get("human_approved"):
        return {
            "decision": "ask",
            "reason": f"tool '{key}' requires human approval (permissions ask)",
        }
    return {
        "decision": "allow",
        "reason": "" if entry == "allow" else f"human approved for '{key}'",
    }


def permission_interrupt_payload(
    tool_id: str,
    group: str,
    reason: str,
    ctx: dict | None = None,
) -> dict[str, Any]:
    """构造 permission interrupt payload（复用 human_gate 结构，kind=permission）。"""
    from runner.human_gate import build_interrupt_payload, make_gate_id

    c = ctx or {}
    payload = build_interrupt_payload(
        gate_id=make_gate_id(str(c.get("thread_id") or "")),
        risk_profile=c.get("risk_metrics") or {},
        reasons=[reason],
        message=f"⏸️ PermissionGate: 需要人工批准执行 {tool_id}",
    )
    payload["kind"] = "permission"
    payload["tool_id"] = tool_id
    payload["group"] = group
    return payload


def enforce(tool_id: str, group: str = "", ctx: dict | None = None) -> dict[str, str]:
    """tool_node 执行前的单行钩子：check + ask 未批准时 interrupt 等人审。

    - allow / ask 且已批准 → 直接返回（继续执行）
    - deny → 抛 ``PermissionError``（tool_node 转 tool_result error）
    - ask 未批准 → LangGraph ``interrupt(kind="permission")`` 暂停；
      resume approve 后放行，reject 视为拒绝（抛 PermissionError）。
    """
    verdict = check(tool_id, group, ctx)
    if verdict["decision"] != "ask":
        return verdict

    from langgraph.types import interrupt

    from runner.human_gate import normalize_external_decision, parse_resume_decision

    payload = permission_interrupt_payload(tool_id, group, verdict["reason"], ctx)
    resume_value = interrupt(payload)  # ★ 复用 HumanGate 暂停/恢复
    raw = parse_resume_decision(resume_value)
    if normalize_external_decision(raw or "") == "approve":
        return {"decision": "allow", "reason": f"human approved '{tool_id}' via HumanGate"}
    raise PermissionError(f"tool '{tool_id}' rejected by human (permission ask)")


__all__ = [
    "VALID_PERMISSIONS",
    "load_permissions",
    "reset_cache",
    "check",
    "enforce",
    "permission_interrupt_payload",
    "check_ssh",
    "enforce_ssh",
    "ssh_gate_interrupt_payload",
    "DEFAULT_PERMISSIONS_FILE",
]


# ---------------------------------------------------------------------------
# F-03 触发点②：SSH 写操作分级门禁（governance SPEC §2.3 ②，AG-F）
# 复用既有 check/enforce 三态 + interrupt 路径，不造第二套闸。
# ---------------------------------------------------------------------------

# 分级 → permissions.yaml 键（configs/permissions.yaml：ssh.read: allow /
# ssh.dev.write: allow / ssh.prod.write: ask）。
_SSH_CLASS_KEYS = {
    "read": "ssh.read",
    "dev_write": "ssh.dev.write",
    "prod_write": "ssh.prod.write",
}


def check_ssh(action: str, target_env: str, ctx: dict | None = None) -> dict[str, str]:
    """SSH 动作分级门禁判定（``server_ssh.classify_ssh_action`` 驱动）。

    - read / dev_write → allow（SSH 读、开发环境写不 gate，零 interrupt）；
    - prod_write → ``ssh.prod.write`` 配置；**yaml 缺失该键时仍缺省 ask**
      （ponytail: 唯一 fail-safe 缺省——生产写闸不随配置缺失失效；
      read/dev_write 未配置仍按引擎"缺省 allow"向后兼容）。
    """
    from runner.server_ssh import classify_ssh_action

    cls = classify_ssh_action(action, target_env)
    key = _SSH_CLASS_KEYS[cls]
    ctx = ctx or {}
    entry = _lookup(key, "")
    if entry is None:
        entry = "ask" if cls == "prod_write" else "allow"
    if entry == "deny":
        raise PermissionError(f"ssh action '{key}' denied by permissions config")
    if entry == "ask" and not ctx.get("human_approved"):
        return {
            "decision": "ask",
            "reason": (
                f"SSH {cls} ({action} @ {target_env}) requires human approval "
                "(F-03 deploy gate)"
            ),
        }
    return {
        "decision": "allow",
        "reason": "" if entry == "allow" else f"human approved for '{key}'",
    }


def ssh_gate_interrupt_payload(
    action: str,
    target_env: str,
    reason: str,
    ctx: dict | None = None,
) -> dict[str, Any]:
    """构造 deploy gate interrupt payload（复用 human_gate 结构，kind=deploy）。

    ponytail: ``kind`` 不是 schema 字段，是调用点注入的 payload 约定——照抄
    merge_to_main 注 ``payload["kind"]="merge"`` 与 permission 注
    ``"permission"`` 的模式，无需改 schemas/human_gate.py。
    """
    from runner.human_gate import build_interrupt_payload, make_gate_id

    c = ctx or {}
    payload = build_interrupt_payload(
        gate_id=make_gate_id(str(c.get("thread_id") or "")),
        risk_profile=c.get("risk_metrics") or {},
        reasons=[reason],
        message=f"⏸️ HumanGate(kind=deploy): SSH 写生产环境待审批 — {action} @ {target_env}",
    )
    payload["kind"] = "deploy"
    payload["action"] = action
    payload["target_env"] = target_env
    return payload


def enforce_ssh(action: str, target_env: str, ctx: dict | None = None) -> dict[str, str]:
    """SSH 工具执行前的单行钩子：check_ssh + prod_write ask 未批准时 interrupt。

    - read / dev_write（或 ask 且已批准）→ 直接返回（继续执行，零 interrupt）；
    - prod_write 未批准 → LangGraph ``interrupt(kind="deploy")`` 暂停，
      resume approve 后放行，reject 抛 PermissionError（fail-closed）。
    """
    verdict = check_ssh(action, target_env, ctx)
    if verdict["decision"] != "ask":
        return verdict

    from langgraph.types import interrupt

    from runner.human_gate import normalize_external_decision, parse_resume_decision

    payload = ssh_gate_interrupt_payload(action, target_env, verdict["reason"], ctx)
    resume_value = interrupt(payload)  # ★ 复用 HumanGate 暂停/恢复
    raw = parse_resume_decision(resume_value)
    if normalize_external_decision(raw or "") == "approve":
        return {
            "decision": "allow",
            "reason": f"human approved ssh {action} @ {target_env} via HumanGate",
        }
    raise PermissionError(
        f"ssh {action} @ {target_env} rejected by human (deploy gate)"
    )
