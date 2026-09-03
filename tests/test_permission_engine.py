"""G4-A1 permission_engine 测试 — deny 拦截 / ask interrupt / approve 放行 /
未配置默认 allow / yaml 缺失整体 allow（向后兼容）。"""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from runner import permission_engine
from runner.permission_engine import check, enforce, load_permissions, reset_cache
from tools.registry import ToolDef, registry


class _Args(BaseModel):
    x: int = 0


def _tool(name: str, **kw) -> ToolDef:
    return ToolDef(
        id=name,
        description=f"mock {name}",
        schema=_Args,
        execute=lambda a, c: {"ok": name},
        **kw,
    )


@pytest.fixture(autouse=True)
def perm_file(monkeypatch, tmp_path):
    """每个用例一个独立 permissions.yaml（env 覆盖 + 清缓存）。默认空配置 → 全 allow。"""
    path = tmp_path / "permissions.yaml"
    path.write_text("", encoding="utf-8")
    monkeypatch.setenv("QUANTCODE_PERMISSIONS_FILE", str(path))
    reset_cache()
    yield path
    reset_cache()


def _set(path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    reset_cache()


# ---------------------------------------------------------------------------
# 1. deny 拦截：check / enforce 直接抛 PermissionError
# ---------------------------------------------------------------------------

def test_deny_raises(perm_file):
    _set(
        perm_file,
        "permissions:\n  fundamental.publish: deny\n  deploy: deny\n",
    )
    # group.tool_id 精确匹配
    with pytest.raises(PermissionError):
        check("publish", "fundamental", {})
    # 裸 tool_id 匹配（组不匹配也拦）
    with pytest.raises(PermissionError):
        check("deploy", "strategy", {})
    # enforce 同样拦截且不返回
    with pytest.raises(PermissionError):
        enforce("publish", "fundamental", {})


# ---------------------------------------------------------------------------
# 2. ask 未批准 → interrupt payload kind=permission（enforce 冒泡 GraphInterrupt）
# ---------------------------------------------------------------------------

def test_ask_without_approve_interrupts(perm_file):
    _set(perm_file, "permissions:\n  strategy.deploy_strategy: ask\n")
    verdict = check("deploy_strategy", "strategy", {"thread_id": "t1"})
    assert verdict["decision"] == "ask"
    assert "requires human approval" in verdict["reason"]

    payload = permission_engine.permission_interrupt_payload(
        "deploy_strategy", "strategy", verdict["reason"], {"thread_id": "t1"}
    )
    assert payload["kind"] == "permission"
    assert payload["tool_id"] == "deploy_strategy"
    assert payload["reasons"]

    # 真实链路：ask 必须走 interrupt 暂停而非直接执行/报错。
    # 裸调 enforce() 不在 LangGraph runnable 上下文里，interrupt() 会抛
    # RuntimeError("Called get_config outside of a runnable context")——
    # 两个异常都发生在 check 判定 ask 之后、tool 执行之前，语义等价。
    with pytest.raises(Exception) as ei:
        enforce("deploy_strategy", "strategy", {"thread_id": "t2"})
    msg = f"{type(ei.value).__name__}: {ei.value}"
    assert "Interrupt" in msg or "interrupt" in msg.lower() or "runnable" in msg.lower()


# ---------------------------------------------------------------------------
# 3. ask + ctx.human_approved=True → 放行（HumanGate approve 流程注入）
# ---------------------------------------------------------------------------

def test_ask_with_approved_allows(perm_file):
    _set(perm_file, "permissions:\n  strategy.deploy_strategy: ask\n")
    verdict = check(
        "deploy_strategy", "strategy", {"human_approved": True, "thread_id": "t1"}
    )
    assert verdict["decision"] == "allow"
    assert "approved" in verdict["reason"]


# ---------------------------------------------------------------------------
# 4. 未配置 tool 默认 allow
# ---------------------------------------------------------------------------

def test_unconfigured_tool_defaults_allow(perm_file):
    assert load_permissions() == {}
    assert check("random_calc", "model", {})["decision"] == "allow"
    # enforce 直接放行（不 interrupt、不抛错）
    assert enforce("random_calc", "model", {})["decision"] == "allow"


# ---------------------------------------------------------------------------
# 5. yaml 缺失 → 整体 allow（向后兼容）
# ---------------------------------------------------------------------------

def test_missing_yaml_allows(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "QUANTCODE_PERMISSIONS_FILE", str(tmp_path / "no_such_file.yaml")
    )
    reset_cache()
    assert load_permissions() == {}
    assert check("anything", "any_group", {})["decision"] == "allow"
    assert enforce("anything", "any_group", {})["decision"] == "allow"


def test_malformed_yaml_fails_closed(monkeypatch, tmp_path):
    """损坏的权限配置不能退化为全量 allow。"""
    path = tmp_path / "broken-permissions.yaml"
    path.write_text("permissions: [broken", encoding="utf-8")
    monkeypatch.setenv("QUANTCODE_PERMISSIONS_FILE", str(path))
    reset_cache()
    with pytest.raises(ValueError, match="invalid"):
        check("publish", "fundamental", {})


# ---------------------------------------------------------------------------
# ToolDef.permission 元数据：registry 注册校验合法值
# ---------------------------------------------------------------------------

def test_tooldef_permission_validation():
    t = _tool("perm_bad", permission="maybe")
    with pytest.raises(ValueError):
        registry.register(t)
    assert registry._tools.get("perm_bad") is None

    ok = _tool("perm_ok", permission="ask")
    registry.register(ok)
    assert registry.get("perm_ok").permission == "ask"

    # 默认 None = 未声明
    plain = _tool("perm_none")
    registry.register(plain)
    assert registry.get("perm_none").permission is None

# ---------------------------------------------------------------------------
# ReAct 集成：yaml 配 ask 后，真 AgentRunner 通过 tool_node 钩子暂停，
# resume(approve) 后复跑同一 tool（不造第二套人审系统，复用 HumanGate）。
# ---------------------------------------------------------------------------

def test_react_agent_permission_ask_interrupt_and_resume(perm_file):
    import importlib

    import langchain_core.messages as lc
    import tools.strategy._register  # noqa: F401
    from runner.agent_engine import AgentRunner
    from runner.langgraph_base import clear_checkpointer_cache

    importlib.reload(tools.strategy._register)
    _set(perm_file, "permissions:\n  strategy.deploy_strategy: ask\n")

    calls: list[str] = []

    def _spy_exec(args, ctx):
        calls.append(args.strategy_name)
        return {"status": "deployed_stub", "strategy_name": args.strategy_name}

    t = registry.get("deploy_strategy")
    registry._tools.pop("deploy_strategy", None)  # 换 spy 版（re-register 语义）
    registry.register(ToolDef(
        id="deploy_strategy",
        description=t.description,
        schema=t.schema,
        execute=_spy_exec,
        permission="ask",
    ))

    from langchain_core.messages import AIMessage

    class _LLM:
        def __init__(self):
            self.n = 0

        def __call__(self, messages, tools=None):
            self.n += 1
            if self.n == 1:
                return AIMessage(content="", tool_calls=[{
                    "name": "deploy_strategy",
                    "args": {"strategy_name": "perm-e2e"},
                    "id": "c-perm-1",
                }])
            return AIMessage(content="deploy done")

    tmp = perm_file.parent
    t = registry.get("deploy_strategy")
    registry._tools.pop("deploy_strategy", None)  # 换 spy 版（re-register 语义）
    registry.register(ToolDef(
        id="deploy_strategy",
        description=t.description,
        schema=t.schema,
        execute=_spy_exec,
        permission="ask",
    ))
    clear_checkpointer_cache()
    try:
        runner = AgentRunner(group="strategy", model=_LLM(), checkpoint_db=tmp / "ck.db")
        paused = runner.stream(
            task="部署策略 perm-e2e",
            skill_name=None,
            system_prompt="x",
            flow_name="perm_e2e",
            thread_id="perm-e2e-1",
        )
        gate = (paused.get("gate") or {})
        assert "permission" in str(gate.get("message", "")) or \
            any("permission" in str(r) for r in (gate.get("reasons") or [])), \
            f"expected permission gate, got {gate}"

        resumed = runner.resume(
            thread_id="perm-e2e-1",
            decision="approve",
            skill_name=None,
            system_prompt="x",
            flow_name="perm_e2e",
        )
        assert not any(
            getattr(m, "tool_calls", None)
            for m in (resumed.get("messages") or [])
            if type(m).__name__ == "AIMessage" and m is resumed["messages"][-1]
        ), "resume 后不应再有 pending tool_call"
        assert calls == ["perm-e2e"], f"approve 后工具应执行且仅一次: {calls}"
    finally:
        clear_checkpointer_cache()
        registry._tools.pop("deploy_strategy", None)
        registry.register(t)  # 还原真实 deploy tool
