"""LangGraph 基础设施 — Day 2 尹一帆。

任何 Compose 流（fundamental / factor / model / risk / strategy / options）
都通过本模块搭建 StateGraph，shared 状态 schema 见 BaseFlowState。

设计要点（Day 2 决策）：
- StateGraph 替代手写状态机（Pattern 1 Orchestrator-Worker）
- SqliteSaver 替代手写 checkpoint.md（Pattern 2 Stateful Blackboard 的持久化层）
- interrupt_before/after 替代手写人审断点（Pattern 5 HumanGate；Day 2 留 stub）
- thread_id 命名 `<group>-<flow>-<ts>` 便于 checkpoint 恢复与日志检索

所有节点函数统一签名：
    def node_fn(state: BaseFlowState) -> dict:
        ...  # 读 state，return 一个被 merge 进 state 的 dict

返回值约定：
- artifacts / errors 用 operator.add 累加（见 annotations）
- 其他字段直接覆盖
- 抛异常时，LangGraph 自动不入 checkpoint；上层 runner 决定如何重试

Owner: 尹一帆
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path
from typing import Annotated, Any, Callable, TypedDict

import operator
from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.sqlite import SqliteSaver


# ---------------------------------------------------------------------------
# 路径与常量
# ---------------------------------------------------------------------------

# .quantcode/ 位于仓库根（与 runner/ 同级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 统一 checkpoint DB：compose / agent / MCP 所有入口共用这一个文件。
# （原 MCP 侧 opencode-checkpoints.db 已停用；旧 db 不迁移。）
CHECKPOINTS_DB = PROJECT_ROOT / ".quantcode" / "checkpoints.db"
DEFAULT_CHECKPOINT_DB = CHECKPOINTS_DB  # 向后兼容别名


# ---------------------------------------------------------------------------
# BaseFlowState：所有 Compose 流共享的状态 schema
# ---------------------------------------------------------------------------

class BaseFlowState(TypedDict, total=False):
    """所有 Compose 流的基础 state。

    注意 TypedDict 字段采用 total=False，因为各 flow 会扩展 state（如 FactorFlowState），
    而 BaseFlowState 仅列共通字段。这里用 total=True 也可，但 total=False 更宽松，便于子类叠加。
    """
    # 路由与身份
    group: str                                       # fundamental/factor/model/risk/strategy/options
    flow_name: str                                   # 例 "factor:evaluation"
    thread_id: str                                   # 由 make_thread_id 生成的唯一 id

    # 输入输出（接 Pydantic schema 的 dict 序列化形式）
    input_data: dict[str, Any]
    output_data: dict[str, Any] | None

    # 累加型字段：node 可返回追加项，LangGraph 自动合并
    artifacts: Annotated[list[str], operator.add]     # 产出文件路径列表
    errors:    Annotated[list[str], operator.add]     # 错误信息列表

    # 内部注入：compose_executor 会写入，node 可读
    _memory: Any                                     # MemoryService 实例（M4 注入）


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------

def create_workflow(
    nodes: dict[str, Callable[[dict[str, Any]], dict[str, Any]]],
    edges: list[tuple[str, str]],
    state_schema: type = BaseFlowState,
) -> StateGraph:
    """根据节点/边配置构造 StateGraph。

    Args:
        nodes: 节点名 → 节点函数。函数签名 ``(state) -> dict``，返回值被 merge。
        edges: 有向边列表。源节点、目标节点，例 ``[("a", "b"), ("b", END)]``。
               支持 ``START`` 作为起点别名。
        state_schema: 状态 TypedDict 类，默认 BaseFlowState。

    Returns:
        未 compile 的 StateGraph 实例；调用方需 ``.compile(checkpointer=...)``。

    Examples:
        >>> workflow = create_workflow(
        ...     nodes={"step1": my_step1, "step2": my_step2},
        ...     edges=[("step1", "step2"), ("step2", END)],
        ... )
        >>> app = workflow.compile(checkpointer=get_checkpointer())
    """
    if not nodes:
        raise ValueError("create_workflow: nodes 不能为空")
    # END 不允许作为 node 名（仅作为 edge 目标）
    if END in nodes:
        raise ValueError(f"create_workflow: {END!r} 不能作为节点名，仅作为边的目标")

    workflow = StateGraph(state_schema)
    for name, func in nodes.items():
        workflow.add_node(name, func)
    for source, target in edges:
        # START 别名直接透传给 StateGraph.add_edge，它本来就接受 "__start__" / START 常量
        workflow.add_edge(source, target)
    return workflow


# ---------------------------------------------------------------------------
# Checkpointer 封装
# ---------------------------------------------------------------------------

# 模块级缓存：path(str) -> (SqliteSaver, sqlite3.Connection)
# 缓存 SqliteSaver + Connection，避免 from_conn_string 的上下文管理器语义
# 导致 connection 关闭后无法继续使用 saver。
_CHECKPOINTER_CACHE: dict[str, tuple[SqliteSaver, sqlite3.Connection]] = {}


def get_checkpointer(db_path: str | os.PathLike | None = None) -> SqliteSaver:
    """返回 SqliteSaver 实例（首次调用会创建并缓存）。

    Args:
        db_path: checkpoint 数据库路径，默认 ``.quantcode/checkpoints.db``。
                 父目录不存在会自动创建。

    Returns:
        SqliteSaver：长期存活的 saver。调用 ``clear_checkpointer_cache()``
        以关闭所有打开的连接（测试间切换 db_path 时常用）。
    """
    path = Path(db_path) if db_path else DEFAULT_CHECKPOINT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    key = str(path.resolve())

    cached = _CHECKPOINTER_CACHE.get(key)
    if cached is not None:
        return cached[0]

    # langgraph 1.x：from_conn_string 是 @contextmanager，仅在 with 块内有效。
    # 为支持长存活的 saver，我们手动接管 sqlite3.Connection 的生命周期。
    conn = sqlite3.connect(
        key,
        check_same_thread=False,  # 多线程由 SqliteSaver 内部锁保护
    )
    saver = SqliteSaver(conn)
    # setup() 会在第一次写 checkpoint 时自动调用；这里显式触发以便及时发现 schema 问题
    saver.setup()
    _CHECKPOINTER_CACHE[key] = (saver, conn)
    return saver


def clear_checkpointer_cache() -> None:
    """关闭所有缓存的 SqliteSaver 连接（测试 / 优雅退出时调用）。"""
    for _, conn in _CHECKPOINTER_CACHE.values():
        try:
            conn.close()
        except Exception:
            pass
    _CHECKPOINTER_CACHE.clear()


# ---------------------------------------------------------------------------
# thread_id 命名
# ---------------------------------------------------------------------------

def make_thread_id(
    group: str,
    flow_name: str,
    *,
    ts: int | None = None,
    suffix: str = "",
    task_id: str | None = None,
) -> str:
    """生成统一格式的 thread_id。

    规则：
    - 传 ``task_id``：``<group>-<flow>-<task_id>-<uuid8>``
    - 未传：``<group>-<flow>-<uuid8>``（uuid 截 8 位；同秒同参不碰撞）
    - 显式传 ``ts``（测试/演示注入固定值）：保留旧格式 ``<group>-<flow>-<ts>[-suffix]``

    Args:
        group: 6 组之一（fundamental/factor/model/risk/strategy/options）。
        flow_name: 流名（例 ``factor:evaluation``）。自动把冒号替换成下划线以兼容文件名。
        ts: 时间戳（秒）。显式传入时作为唯一段（旧行为，确定性 id）；默认用 uuid8。
        suffix: 可选后缀（例 ``"retry-1"`` ``"step3-debug"``）。
        task_id: 可选任务 id（例 OpenCode 任务号）；有则插在 flow 之后、唯一段之前。

    Returns:
        thread_id 字符串。

    Examples:
        >>> make_thread_id("factor", "factor:evaluation", ts=1719876543)
        'factor-factor_evaluation-1719876543'
        >>> make_thread_id("factor", "factor:evaluation", task_id="T42", ts=1719876543)
        'factor-factor_evaluation-T42-1719876543'
        >>> make_thread_id("factor", "factor:evaluation")  # doctest: +SKIP
        'factor-factor_evaluation-1a2b3c4d'   # uuid8 每次调用不同
    """
    safe_flow = flow_name.replace(":", "_").replace("/", "_")
    unique = str(int(ts)) if ts is not None else uuid.uuid4().hex[:8]
    parts = [group, safe_flow]
    if task_id:
        parts.append(str(task_id))
    base = "-".join(parts) + f"-{unique}"
    return f"{base}-{suffix}" if suffix else base


# ---------------------------------------------------------------------------
# 便利函数：常见 4 步 Compose 流（validate → call → report → accept）
# ---------------------------------------------------------------------------

def default_compose_edges(steps: list[str]) -> list[tuple[str, str]]:
    """为 ``[s1, s2, ..., sN]`` 这种线性流生成 edges。

    输出包含 4 类边：
    - ``START → s1``
    - ``s1 → s2 → ... → sN``
    - ``sN → END``

    Day 2 大量 Compose 流（factor:evaluation / model:pr-submit / risk:detect 等）
    都是线性流水线，本函数减少重复样板。

    Args:
        steps: 节点名顺序列表，至少 2 项。

    Returns:
        edges 列表，可直接传给 :func:`create_workflow`。

    Raises:
        ValueError: 节点少于 2 项。
    """
    if len(steps) < 2:
        raise ValueError("default_compose_edges: 至少需要 2 个节点")
    edges: list[tuple[str, str]] = [(START, steps[0])]
    for src, dst in zip(steps, steps[1:]):
        edges.append((src, dst))
    edges.append((steps[-1], END))
    return edges


__all__ = [
    "BaseFlowState",
    "CHECKPOINTS_DB",
    "DEFAULT_CHECKPOINT_DB",
    "PROJECT_ROOT",
    "create_workflow",
    "default_compose_edges",
    "get_checkpointer",
    "make_thread_id",
]  # noqa: F401  (END / START are re-imported for user convenience)
