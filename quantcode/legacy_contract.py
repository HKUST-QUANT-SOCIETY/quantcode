"""Explicit original Runner construction and LangGraph recovery evidence.

This describes a reviewed old executor. It never derives missing original
options from today's defaults or interprets a serializer version as a graph.
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class LoopOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    window: StrictInt = Field(gt=0, le=100000)
    threshold: StrictInt = Field(gt=0, le=100000)

    @model_validator(mode="after")
    def validate_window(self):
        if self.threshold > self.window:
            raise ValueError("original loop threshold exceeds its window")
        return self


class Constructor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registry: Literal["default"]
    max_iterations: StrictInt = Field(gt=0, le=100000)
    truncate_tokens: StrictInt | None = Field(ge=1)
    retry_max_retries: StrictInt = Field(ge=0, le=100)
    retry_base_delay: float = Field(ge=0, le=60, allow_inf_nan=False)
    budget_tokens: StrictInt | None = Field(ge=0)
    blackboard_db_path: str | None
    allowed_tool_ids: list[str] | None
    loop_detector: LoopOptions


class Edge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(min_length=1, max_length=128)
    target: str = Field(min_length=1, max_length=128)
    conditional: bool
    label: str | None


class PendingTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)


class RuntimeDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    constructor: Constructor
    system_prompt_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    nodes: list[str] = Field(min_length=1, max_length=1000)
    edges: list[Edge] = Field(max_length=10000)
    next_nodes: list[str] = Field(max_length=1000)
    pending_tasks: list[PendingTask] = Field(max_length=1000)

    @model_validator(mode="after")
    def validate_graph(self):
        if len(set(self.nodes)) != len(self.nodes) or any(not node or len(node) > 128 for node in self.nodes):
            raise ValueError("registered graph nodes are invalid")
        if any(edge.source not in self.nodes or edge.target not in self.nodes for edge in self.edges):
            raise ValueError("registered graph edges reference absent nodes")
        if any(node not in self.nodes for node in self.next_nodes) or any(task.name not in self.nodes for task in self.pending_tasks):
            raise ValueError("registered pending execution references absent graph nodes")
        if len({task.id for task in self.pending_tasks}) != len(self.pending_tasks):
            raise ValueError("registered graph has duplicate pending task IDs")
        return self


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def graph_state(app, snapshot) -> dict:
    graph = app.get_graph()
    edges = [{"source": edge.source, "target": edge.target, "conditional": edge.conditional,
              "label": None if edge.data is None else str(edge.data)} for edge in graph.edges]
    return {"nodes": sorted(graph.nodes), "edges": sorted(edges, key=digest),
            "next_nodes": list(snapshot.next),
            "pending_tasks": [{"id": task.id, "name": task.name} for task in snapshot.tasks]}


def verify_runtime(runtime: RuntimeDefinition, app, snapshot) -> None:
    actual = graph_state(app, snapshot)
    expected = runtime.model_dump(include={"nodes", "edges", "next_nodes", "pending_tasks"})
    expected["nodes"] = sorted(expected["nodes"])
    expected["edges"] = sorted(expected["edges"], key=digest)
    if actual != expected:
        raise PermissionError("archived graph topology or pending nodes differ from the reviewed original executor")
    prompt = snapshot.values.get("system_prompt") or ""
    if not isinstance(prompt, str) or hashlib.sha256(prompt.encode()).hexdigest() != runtime.system_prompt_digest:
        raise PermissionError("original executor system prompt differs from its registered construction")
    if snapshot.values.get("_blackboard_db_path") != runtime.constructor.blackboard_db_path:
        raise PermissionError("original executor Blackboard constructor differs from its checkpoint")
