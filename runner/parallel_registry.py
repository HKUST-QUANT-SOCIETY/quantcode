"""进程内并行 subagent registry — P-04（FUNCTIONAL_SPEC §P-04 / ROADMAP R3 Q2）。

架构一句话：**线程模型** — 每个 subagent 是进程内一条 ``threading.Thread``，
registry（dict + threading.Lock）只存元数据，线程里跑 ``AgentRunner.stream()``，
结果轮询式写回条目（升级路径 asyncio.AsyncAgentRunner）。

三件事（Q2 范围）：
1. ``create_subagent``  — spawn：new AgentRunner(group, budget_tokens, checkpoint_db)
2. ``kill``             — 协作式取消：per-step cancel check（model wrapper 在每次
   LLM 调用前查 ``cancel_event``，等价于"tool 路由前 check"且 agent_engine 0 行改动）
3. ``list_children``    — 任务树（parent_thread_id 链，MAX_TREE_DEPTH 上限）

ponytail:
- 线程内循环 + 结果写回 registry 条目，不引 asyncio/进程池；升级路径 = asyncio.TaskGroup
- cancel check 放 model wrapper（每次 ReAct 步必有 LLM 调用）→ agent_engine 零改动；
  局限：卡在单个慢 tool 调用内时 kill 只能标记（status 停 running，stop_requested=True）
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable

from runner.agent_engine import AgentRunner
from runner.langgraph_base import CHECKPOINTS_DB, make_thread_id

# P-04 契约：任务树最大深度
MAX_TREE_DEPTH = 4

# 终态集合（kill 幂等判断用）
TERMINAL_STATUSES = frozenset(
    {"completed", "stopped", "stopped_budget", "stopped_loop", "waiting_for_human", "aborted", "error"}
)


def guards_max_iterations() -> int:
    # ponytail: 延迟 import，避免 parallel_registry 拖上整个 routing 链
    from runner.routing.guards import MAX_ITERATIONS

    return MAX_ITERATIONS


class SubagentCancelled(RuntimeError):
    """kill() 触发的协作式取消信号（在子线程 model wrapper 处抛出）。"""


class SubagentRegistry:
    """进程内 subagent registry：{subagent_id: entry}，threading.Lock 保护。

    entry 字段：subagent_id / runner / thread_id / status / budget_used /
    parent_thread_id / created_at（spec 契约）+ task / group / skill_name /
    budget_tokens / output_data / trace / error / kill_reason / finished_at /
    cancel_event / thread（内部字段，get_status 不外泄）。
    """

    def __init__(self) -> None:
        self._entries: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # spawn
    # ------------------------------------------------------------------
    def create_subagent(
        self,
        task: str,
        group: str,
        *,
        skill_name: str | None = None,
        budget_tokens: int | None = None,
        parent_thread_id: str = "",
        model: Any = None,
        checkpoint_db: str | None = None,
        max_iterations: int | None = None,
    ) -> dict[str, Any]:
        """spawn 一个子 agent：子线程跑 ``AgentRunner.stream()``，返回 entry 快照。

        Args:
            model: LLM 可调用（签名 ``(messages, tools=...) -> AIMessage``），
                供 AgentRunner 用；缺省由调用方（MCP/_register 层）注入 ctx["_model"]。
            checkpoint_db: None → 默认 ``CHECKPOINTS_DB``（与主 run 共用，测试传 tmp）。

        Raises:
            ValueError: model 缺失。
        """
        if model is None:
            raise ValueError("create_subagent: model is required (parent model from ctx['_model'])")

        subagent_id = f"sub-{uuid.uuid4().hex[:8]}"
        thread_id = make_thread_id(group, "subagent")

        # 子任务链深度校验（P-04 任务树；parent 自己也是 subagent 时才有链）
        if self._chain_depth(parent_thread_id) + 1 > MAX_TREE_DEPTH:
            raise ValueError(
                f"subagent tree depth would exceed MAX_TREE_DEPTH={MAX_TREE_DEPTH} "
                f"(parent chain={self._chain_depth(parent_thread_id)})"
            )

        cancel_event = threading.Event()

        # per-step 取消：包一层 model，每次 ReAct 步的 LLM 调用前查 flag。
        def cancelable_model(messages: Any, tools: Any = None) -> Any:
            if cancel_event.is_set():
                raise SubagentCancelled(f"cancelled before LLM step (subagent_id={subagent_id})")
            return model(messages, tools=tools)

        runner = AgentRunner(
            group=group,
            model=cancelable_model,
            budget_tokens=budget_tokens,
            checkpoint_db=checkpoint_db if checkpoint_db else CHECKPOINTS_DB,
            max_iterations=(
                max_iterations if max_iterations is not None
                else guards_max_iterations()
            ),
        )

        with self._lock:
            entry: dict[str, Any] = {
                "subagent_id": subagent_id,
                "runner": runner,
                "thread_id": thread_id,
                "parent_thread_id": parent_thread_id,
                "task": task,
                "group": group,
                "skill_name": skill_name,
                "budget_tokens": budget_tokens,
                "status": "running",
                "budget_used": 0,
                "output_data": None,
                "trace": None,
                "error": None,
                "kill_reason": None,
                "created_at": time.time(),
                "finished_at": None,
                "cancel_event": cancel_event,
                "thread": None,
            }
            self._entries[subagent_id] = entry

        th = threading.Thread(
            target=self._run, args=(entry, task, skill_name), daemon=True,
            name=f"subagent-{subagent_id}",
        )
        with self._lock:
            entry["thread"] = th
        th.start()
        return self.get_status(subagent_id)

    # ------------------------------------------------------------------
    # 子线程体：跑 stream()，结果写回 entry（轮询式，parent 轮询 get_status）
    # ------------------------------------------------------------------
    def _run(self, entry: dict[str, Any], task: str, skill_name: str | None) -> None:
        runner: AgentRunner = entry["runner"]
        try:
            final = runner.stream(
                task=task,
                skill_name=skill_name,
                flow_name="subagent",
                thread_id=entry["thread_id"],
            )
            explicit_status = final.get("status")
            status = (
                str(explicit_status)
                if explicit_status in {"waiting_for_human", "stopped_budget", "stopped_loop"}
                else "completed" if final.get("task_status") == "done"
                else "stopped"
            )
            self._finish(
                entry,
                status=status,
                budget_used=int(final.get("budget_used") or 0),
                output_data=final.get("output_data"),
                trace=final.get("execution_trace"),
            )
        except SubagentCancelled as exc:
            self._finish(entry, "aborted", error=str(exc), trace=[{
                "type": "subagent_aborted",
                "subagent_id": entry["subagent_id"],
                "thread_id": entry["thread_id"],
                "reason": entry.get("kill_reason") or "",
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            }])
        except Exception as exc:
            self._finish(
                entry, "error",
                error=f"{type(exc).__name__}: {exc}",
            )

    def _finish(self, entry: dict[str, Any], status: str, **fields: Any) -> None:
        with self._lock:
            entry["status"] = status
            entry["finished_at"] = time.time()
            for k, v in fields.items():
                entry[k] = v

    # ------------------------------------------------------------------
    # 状态查询 / kill / 任务树
    # ------------------------------------------------------------------
    def get_status(self, subagent_id: str) -> dict[str, Any]:
        """返回 entry 的外部可见快照（不含 runner/cancel_event/thread 内部字段）。"""
        with self._lock:
            if subagent_id not in self._entries:
                raise KeyError(f"subagent '{subagent_id}' not found")
            entry = self._entries[subagent_id]
            snapshot = {
                k: (v.copy() if isinstance(v, list) else v)
                for k, v in entry.items()
                if k not in ("runner", "cancel_event", "thread")
            }
        return snapshot

    def kill(self, subagent_id: str, reason: str = "") -> dict[str, Any]:
        """协作式 kill：设 stop flag（cancel_event），子线程下一步 LLM 前中断。

        - running 且 cancel 命中 → aborted（trace 记 subagent_aborted）
        - 已终态 → 幂等：状态不被覆盖（waiting_for_human 等暂停态保持原样）
        - cancel 未及命中（线程自然结束/卡在慢 tool 内）→ 保持原结果状态，
          由 stop_requested=True 表达"杀过"。

        join 上限 1s；超时说明卡在单个 tool 调用里，下次 step 处理。
        """
        with self._lock:
            if subagent_id not in self._entries:
                raise KeyError(f"subagent '{subagent_id}' not found")
            entry = self._entries[subagent_id]
            if entry["status"] not in TERMINAL_STATUSES and not entry["cancel_event"].is_set():
                entry["kill_reason"] = reason
            entry["cancel_event"].set()
            th = entry["thread"]

        # join 在锁外（线程 _finish 需要拿同一把锁）
        t0 = time.time()
        if th is not None:
            th.join(timeout=1.0)
        snapshot = self.get_status(subagent_id)
        snapshot["stop_requested"] = True
        snapshot["stop_elapsed_s"] = round(time.time() - t0, 4)
        if snapshot["status"] == "running":
            snapshot["note"] = "cancel flag set; thread still inside a step (tool/LLM call)"
        return snapshot

    def list_children(self, parent_thread_id: str) -> list[dict[str, Any]]:
        """父 thread_id 下所有 subagent 快照（按 created_at 排序）。"""
        with self._lock:
            ids = sorted(
                (e["subagent_id"] for e in self._entries.values()
                 if e["parent_thread_id"] == parent_thread_id),
            )
        return [self.get_status(sid) for sid in ids]

    def _chain_depth(self, parent_thread_id: str) -> int:
        """parent_thread_id 沿 parent 链上溯的深度（顶层=0；非 subagent 线程=0）。"""
        depth = 0
        tid = parent_thread_id
        seen: set[str] = set()
        with self._lock:
            by_thread = {e["thread_id"]: e for e in self._entries.values()}
        while tid and tid not in seen and tid in by_thread:
            seen.add(tid)
            depth += 1
            tid = by_thread[tid]["parent_thread_id"]
        return depth


# 全局单例（与 tools.registry.registry 同款模式）
parallel_registry = SubagentRegistry()

__all__ = [
    "SubagentRegistry",
    "SubagentCancelled",
    "parallel_registry",
    "MAX_TREE_DEPTH",
    "TERMINAL_STATUSES",
]
