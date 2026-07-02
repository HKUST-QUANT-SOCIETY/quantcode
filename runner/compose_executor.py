"""Compose Mode 统一执行入口 — Day 2 尹一帆。

Skill / Node 作者通过 :func:`execute_compose_flow` 调用任何 Compose 流，
不必直接接触 LangGraph 的 invoke/checkpointer 细节。

设计要点（Day 2 决策）：
- ``FLOW_REGISTRY``：硬编码 ``(group, flow_name) -> 已 compile 的 StateGraph``。
  Day 4 再换成扫描 SKILL.md frontmatter 的自动注册。
- ``interrupt_before/after``：Day 2 留 stub，由杨欣琳的 HumanGate 模块后续接入；
  注册 flow 时若传 ``interrupt_after=[node_name]``，``compile`` 时挂上。
- 每次调用生成新 thread_id（除非 caller 显式传入），并把 ``_memory`` 注入 state。
- 返回统一 dict ``{artifacts, output_data, thread_id, state}``。

用法：

    from runner.compose_executor import register_flow, execute_compose_flow

    app = create_workflow(...).compile(checkpointer=get_checkpointer())
    register_flow('factor', 'factor:autoeval', app)

    result = execute_compose_flow(
        group='factor',
        flow_name='factor:autoeval',
        input_data={'name': 'pb_roe', ...},
    )
    print(result['artifacts'])

Owner: 尹一帆
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable


from .langgraph_base import (
    get_checkpointer,
    make_thread_id,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# 已 compile 的 StateGraph（app）作为值；键是 (group, flow_name)。
# 为预防 key 冲突，group 与 flow_name 一律做 strip 与 lower 处理（flow_name 保留大小写敏感）。
CompiledApp = Any  # langgraph.prebuilt Pregel 实例；type-ignore 避免拉入私有类型

FLOW_REGISTRY: dict[tuple[str, str], CompiledApp] = {}


def register_flow(
    group: str,
    flow_name: str,
    app: CompiledApp,
    *,
    overwrite: bool = False,
) -> None:
    """注册一个已 compile 的 StateGraph 到 FLOW_REGISTRY。

    Args:
        group: 6 组之一。strip 后存为小写。
        flow_name: 流名（保留大小写，仅 strip）。
        app: ``StateGraph.compile()`` 返回值（PREGEL/Pregel 实例）。
        overwrite: 若已存在是否覆盖。Day 2 测试期间开 True，生产 False。

    Raises:
        ValueError: group/flow_name/app 类型错误。
        KeyError: 已存在同 key 但 overwrite=False。
    """
    if not isinstance(group, str) or not group.strip():
        raise ValueError("register_flow: group 必须非空字符串")
    if not isinstance(flow_name, str) or not flow_name.strip():
        raise ValueError("register_flow: flow_name 必须非空字符串")
    if app is None:
        raise ValueError("register_flow: app 不能为 None")

    g = group.strip().lower()
    f = flow_name.strip()
    key = (g, f)
    if key in FLOW_REGISTRY and not overwrite:
        raise KeyError(
            f"register_flow: ({g!r}, {f!r}) 已注册；"
            f"传 overwrite=True 强制覆盖，或先调用 unregister_flow()"
        )
    FLOW_REGISTRY[key] = app
    logger.info("Registered flow (%s, %s)", g, f)


def unregister_flow(group: str, flow_name: str) -> bool:
    """注销一个 flow。返回 True 表示确实移除了一个 entry。"""
    key = (group.strip().lower(), flow_name.strip())
    existed = FLOW_REGISTRY.pop(key, None)
    return existed is not None


def list_registered_flows() -> list[tuple[str, str]]:
    """列出所有已注册 flow。"""
    return list(FLOW_REGISTRY.keys())


# ---------------------------------------------------------------------------
# Pre-invoke 钩子
# ---------------------------------------------------------------------------

# 在 invoke 前注入到 state 的辅助字段。
# Day 2：仅注入 _memory（M5 后才有用，先占位）。
# Day 3+：可在这里追加 session_id、user context 等。
PRE_INVOKE_HOOKS: list[Callable[[str, str, dict[str, Any]], dict[str, Any]]] = []


def register_pre_invoke_hook(
    fn: Callable[[str, str, dict[str, Any]], dict[str, Any]],
) -> None:
    """注册一个在 ``invoke`` 前修改 state 初始值的钩子。

    钩子签名：``(group, flow_name, init_state) -> {追加字段}``。
    返回值会用 dict.update 合并到 init_state。
    """
    PRE_INVOKE_HOOKS.append(fn)


def clear_pre_invoke_hooks() -> None:
    """清空所有钩子（测试用）。"""
    PRE_INVOKE_HOOKS.clear()


# ---------------------------------------------------------------------------
# Memory 注入序列化层（Day 2 下午新增）
# ---------------------------------------------------------------------------
#
# 问题：langgraph 1.x checkpointer 在每个 tick 末尾用 msgpack 序列化整个 state。
# MemoryService 实例（含 sqlite3.Connection）不可序列化 → TypeError。
#
# 方案：
# - 真实 svc 存到 module-level ``_MEMORY_BY_TID``（按 thread_id 索引）
# - state["_memory"] 放一个**纯 dict** ``{"_tid": tid, "_role": "memory"}``，
#   msgpack 可以序列化（dict[str, str]），node 端用 ``from runner.compose_executor
#   import get_memory; get_memory(state["_memory"]["_tid"])`` 拿真实 svc。
# - invoke 完毕（finally），final_state 里的 ``_memory`` 替换为真实 svc——
#   caller 拿到的 state 与任务表 §2.2 期望一致。
#
# 任务表 §2.2 期望的 ``state["_memory"].search(...)`` 语法**形式上**不能直接
# 满足（langgraph 1.x 序列化约束），但**语义上**满足：node 能拿到同一个
# MemoryService 实例，读写 Memory 都不受阻碍。调用方拿到的 final_state
# ``state["_memory"]`` 是真实 svc，可以直接 ``.search(...)``。
#
# 不在 init_state 注入 svc 是因为：在并发 invoke 场景下，state 走 channel
# 复制可能跨线程/跨 invoke 复用，svc 必须按 thread_id 隔离。

_MEMORY_BY_TID: dict[str, Any] = {}
_MEMORY_LOCK = threading.Lock()


def get_memory(tid: str) -> Any:
    """按 thread_id 拿注入的 MemoryService（node 函数推荐用法）。"""
    return _MEMORY_BY_TID.get(tid)


def clear_memory_registry() -> None:
    """清空所有已注入的 MemoryService（测试间调用）。"""
    with _MEMORY_LOCK:
        _MEMORY_BY_TID.clear()


# ---------------------------------------------------------------------------
# 核心 API
# ---------------------------------------------------------------------------

def execute_compose_flow(
    group: str,
    flow_name: str,
    input_data: dict[str, Any],
    *,
    thread_id: str | None = None,
    inject_memory: Callable[[str], Any] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """执行一条 Compose 流，返回标准化结果。

    Args:
        group: 6 组之一。
        flow_name: 流名。
        input_data: 传给首节点的 dict（Pydantic schema 的 model_dump() 输出）。
        thread_id: 可显式指定，否则按 ``make_thread_id(group, flow_name)`` 生成。
        inject_memory: 一个 ``(group) -> MemoryService`` 的工厂；
                       传 None 时不注入 ``_memory``。Day 3+ 由 Memory 模块提供。
        config: 透传给 ``app.invoke`` 的额外 config。

    Returns:
        包含以下键的 dict：
        - ``thread_id``：实际使用的 thread_id。
        - ``artifacts``：所有 node 累加的 artifact 路径列表。
        - ``output_data``：最终 ``state['output_data']``，可能为 None。
        - ``errors``：累加的错误信息列表（一般为空）。
        - ``state``：invoke 返回的完整 final state（M3 调试用）。

    Raises:
        KeyError: flow 未注册。
        ValueError: 入参类型错。
    """
    if not isinstance(group, str) or not isinstance(flow_name, str):
        raise ValueError("execute_compose_flow: group/flow_name 必须是字符串")
    if not isinstance(input_data, dict):
        raise ValueError("execute_compose_flow: input_data 必须是 dict")

    g = group.strip().lower()
    f = flow_name.strip()
    key = (g, f)
    app = FLOW_REGISTRY.get(key)
    if app is None:
        raise KeyError(
            f"execute_compose_flow: flow ({g!r}, {f!r}) 未注册。"
            f"已注册：{sorted(FLOW_REGISTRY.keys())}"
        )

    tid = thread_id or make_thread_id(g, f)

    # 构造 initial state
    init_state: dict[str, Any] = {
        "group": g,
        "flow_name": f,
        "thread_id": tid,
        "input_data": input_data,
        "output_data": None,
        "artifacts": [],
        "errors": [],
    }

    # Memory 注入
    # 注意：state["_memory"] 放纯 dict 包装（msgpack 可序列化），
    # 真实 svc 走 _MEMORY_BY_TID[tid]；详见模块顶部 docstring。
    memory_svc: Any = None
    if inject_memory is not None:
        memory_svc = inject_memory(g)
        if memory_svc is not None:
            with _MEMORY_LOCK:
                _MEMORY_BY_TID[tid] = memory_svc
            init_state["_memory"] = {"_tid": tid, "_role": "memory"}

    # 跑用户钩子
    for hook in PRE_INVOKE_HOOKS:
        try:
            extra = hook(g, f, dict(init_state))
            if isinstance(extra, dict):
                init_state.update(extra)
        except Exception as exc:  # 钩子出错仅记日志，不阻塞主流程
            logger.warning("pre_invoke hook 失败：%s", exc)

    # 装配 LangGraph config
    cfg: dict[str, Any] = {"configurable": {"thread_id": tid}}
    if config:
        cfg.update(config)

    logger.info("execute_compose_flow start group=%s flow=%s thread_id=%s", g, f, tid)
    final_state: dict[str, Any] = {}
    try:
        final_state = app.invoke(init_state, config=cfg)
    finally:
        # 把 _memory 替换为真实 svc（caller 拿到的 state 与任务表 §2.2 期望一致）
        if memory_svc is not None:
            final_state["_memory"] = memory_svc
    logger.info("execute_compose_flow end   group=%s flow=%s thread_id=%s", g, f, tid)

    return {
        "thread_id": tid,
        "artifacts": list(final_state.get("artifacts") or []),
        "output_data": final_state.get("output_data"),
        "errors": list(final_state.get("errors") or []),
        "state": final_state,
    }


# ---------------------------------------------------------------------------
# 异步 variant（暴露给异步 caller；Day 2 简单实现，Day 4 替换为真正的 ainvoke）
# ---------------------------------------------------------------------------

async def aexecute_compose_flow(
    group: str,
    flow_name: str,
    input_data: dict[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """异步 wrapper；当前直接调用同步版本。Day 4 改用 app.ainvoke。"""
    return execute_compose_flow(group, flow_name, input_data, **kwargs)


# ---------------------------------------------------------------------------
# 自检入口
# ---------------------------------------------------------------------------

def _self_check() -> None:
    """手动 ``python -m runner.compose_executor`` 时跑一个最小自检流程。"""
    from .langgraph_base import create_workflow, default_compose_edges

    def _passthrough_a(state: dict[str, Any]) -> dict[str, Any]:
        return {"artifacts": ["self_check_step_a.txt"]}

    def _passthrough_b(state: dict[str, Any]) -> dict[str, Any]:
        return {
            "output_data": {"echo": state["input_data"], "step": "done"},
            "artifacts": ["self_check_step_b.txt"],
        }

    wf = create_workflow(
        nodes={"step_a": _passthrough_a, "step_b": _passthrough_b},
        edges=default_compose_edges(["step_a", "step_b"]),
    )
    app = wf.compile(checkpointer=get_checkpointer())
    register_flow("__self_test__", "__self_test__", app, overwrite=True)
    try:
        result = execute_compose_flow(
            "__self_test__", "__self_test__", {"hi": "world"}
        )
        print(
            "[compose_executor self-check] OK:",
            "thread_id=", result["thread_id"],
            "artifacts=", result["artifacts"],
            "output=", result["output_data"],
        )
    finally:
        unregister_flow("__self_test__", "__self_test__")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _self_check()
