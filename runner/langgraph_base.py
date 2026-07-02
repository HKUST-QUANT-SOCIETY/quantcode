"""LangGraph infrastructure for Day 2 Compose flows.

All Compose flows build StateGraph instances through this module. Shared state
fields live in BaseFlowState; flow-specific modules can provide a narrower or
extended TypedDict when compiling their own workflow.
"""
from __future__ import annotations

import operator
import os
import sqlite3
import time
from pathlib import Path
from typing import Annotated, Any, Callable, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CHECKPOINT_DB = PROJECT_ROOT / ".quantcode" / "checkpoints.db"


class BaseFlowState(TypedDict, total=False):
    """Shared state fields for all Compose flows."""

    group: str
    flow_name: str
    thread_id: str
    input_data: dict[str, Any]
    output_data: dict[str, Any] | None
    artifacts: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
    _memory: Any


def create_workflow(
    nodes: dict[str, Callable[[dict[str, Any]], dict[str, Any]]],
    edges: list[tuple[str, str]],
    state_schema: type = BaseFlowState,
) -> StateGraph:
    """Create an uncompiled StateGraph from nodes and directed edges."""
    if not nodes:
        raise ValueError("create_workflow: nodes cannot be empty")
    if END in nodes:
        raise ValueError(f"create_workflow: {END!r} cannot be used as a node name")

    workflow = StateGraph(state_schema)
    for name, func in nodes.items():
        workflow.add_node(name, func)
    for source, target in edges:
        workflow.add_edge(source, target)
    return workflow


_CHECKPOINTER_CACHE: dict[str, tuple[SqliteSaver, sqlite3.Connection]] = {}


def get_checkpointer(db_path: str | os.PathLike | None = None) -> SqliteSaver:
    """Return a cached SqliteSaver backed by a long-lived sqlite connection."""
    path = Path(db_path) if db_path else DEFAULT_CHECKPOINT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    key = str(path.resolve())

    cached = _CHECKPOINTER_CACHE.get(key)
    if cached is not None:
        return cached[0]

    conn = sqlite3.connect(key, check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    _CHECKPOINTER_CACHE[key] = (saver, conn)
    return saver


def clear_checkpointer_cache() -> None:
    """Close cached sqlite connections."""
    for _, conn in _CHECKPOINTER_CACHE.values():
        try:
            conn.close()
        except Exception:
            pass
    _CHECKPOINTER_CACHE.clear()


def make_thread_id(
    group: str,
    flow_name: str,
    *,
    ts: int | None = None,
    suffix: str = "",
) -> str:
    """Generate `<group>-<flow>-<epoch_seconds>[-suffix]` thread IDs."""
    safe_flow = flow_name.replace(":", "_").replace("/", "_")
    epoch = int(ts if ts is not None else time.time())
    base = f"{group}-{safe_flow}-{epoch}"
    return f"{base}-{suffix}" if suffix else base


def default_compose_edges(steps: list[str]) -> list[tuple[str, str]]:
    """Create START -> step1 -> ... -> stepN -> END edges for a linear flow."""
    if len(steps) < 2:
        raise ValueError("default_compose_edges: at least 2 steps are required")
    edges: list[tuple[str, str]] = [(START, steps[0])]
    for source, target in zip(steps, steps[1:]):
        edges.append((source, target))
    edges.append((steps[-1], END))
    return edges


__all__ = [
    "BaseFlowState",
    "DEFAULT_CHECKPOINT_DB",
    "PROJECT_ROOT",
    "clear_checkpointer_cache",
    "create_workflow",
    "default_compose_edges",
    "get_checkpointer",
    "make_thread_id",
]

