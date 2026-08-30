"""model:submit Compose 流 — 模型组 PR 提交 → ModelSpec → risk handoff。

节点序列（node 本体零业务逻辑，只串 tools/model 已注册的真实 tool）：
    parse_pr_input      = read_pr + extract_metadata（透传整理：PR → ModelSpec 形 metadata）
    → generate_model_spec = generate_model_spec（schemas.model.ModelSpec 校验归一）
    → handoff_to_risk    = write_blackboard + trigger_risk_flow（组合进一个 handoff 节点）
    → produce_output     = 汇总 output_data 并落 ModelSpec JSON artifact

input_data 约定（全透传，不做二次加工）：
    - pr_path / pr_number(+repo) / body 三选一 → read_pr
    - 或直接给 metadata（已结构化的 ModelSpec dict，跳过 read_pr/extract_metadata）
    - blackboard_key 可选（缺省 ``model.<model_name>_spec``；归一层自动补
      ``shared.model_entries.`` 前缀，幂等）
    - blackboard_db_path 可选（覆盖 blackboard 数据库路径，测试用）

import flows.model_submit 即注册 ("model", "model:submit") 到 FLOW_REGISTRY
（注册语句在 runner/compose_executor.py 底部统一 import）。
"""
from __future__ import annotations

import json
import operator
import re
from os import PathLike
from pathlib import Path
from typing import Annotated, Any, TypedDict

from tools.registry import registry

# 触发 model 组 tool 注册（幂等；register_tool 重复注册为覆盖）
import tools.model._register  # noqa: F401


class ModelSubmitFlowState(TypedDict, total=False):
    """model:submit 流的 JSON-serializable state（风格对齐 FactorFlowState）。"""

    group: str
    flow_name: str
    thread_id: str
    input_data: dict[str, Any]
    output_data: dict[str, Any] | None
    artifacts: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
    pr: dict[str, Any]
    metadata: dict[str, Any]
    model_spec: dict[str, Any]
    handoff: dict[str, Any]
    _memory: Any  # compose_executor 注入的 MemoryService handle（本流暂不读写，占位对齐）


def _ctx(state: ModelSubmitFlowState) -> dict[str, Any]:
    """构造 tool ctx（thread_id / group / 可选 blackboard_db_path）。"""
    input_data = state.get("input_data") or {}
    ctx: dict[str, Any] = {
        "thread_id": state.get("thread_id") or "model-submit-flow",
        "group": state.get("group") or "model",
    }
    if input_data.get("blackboard_db_path"):
        ctx["blackboard_db_path"] = str(input_data["blackboard_db_path"])
    return ctx


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


def parse_pr_input(state: ModelSubmitFlowState) -> dict[str, Any]:
    """read_pr + extract_metadata 透传整理：PR（本地 fixture / GitHub / 正文）→ metadata。"""
    input_data = state.get("input_data") or {}

    if input_data.get("metadata"):
        # 已结构化 metadata 直接透传（不 read_pr）
        return {"metadata": dict(input_data["metadata"])}

    if input_data.get("pr_path") is not None:
        pr = registry.call("read_pr", {"pr_path": input_data["pr_path"]}, _ctx(state))
    elif input_data.get("pr_number") is not None:
        args: dict[str, Any] = {"pr_number": input_data["pr_number"]}
        if input_data.get("repo"):
            args["repo"] = input_data["repo"]
        pr = registry.call("read_pr", args, _ctx(state))
    elif input_data.get("body") is not None:
        pr = {"source": "inline", "body": str(input_data["body"])}
    else:
        raise ValueError(
            "model:submit input_data requires metadata, pr_path, pr_number, or body"
        )

    metadata = registry.call("extract_metadata", {"pr": pr}, _ctx(state))
    return {"pr": pr, "metadata": metadata}


def generate_model_spec_node(state: ModelSubmitFlowState) -> dict[str, Any]:
    """generate_model_spec：metadata 校验并归一为 ModelSpec dict。"""
    spec = registry.call("generate_model_spec", {"metadata": state["metadata"]}, _ctx(state))
    return {"model_spec": spec}


def handoff_to_risk(state: ModelSubmitFlowState) -> dict[str, Any]:
    """组合节点：write_blackboard（PROJECT scope handoff）+ trigger_risk_flow（风控入队）。"""
    spec = state["model_spec"]
    input_data = state.get("input_data") or {}
    key = input_data.get("blackboard_key") or f"model.{_slug(str(spec['model_name']))}_spec"

    write_result = registry.call("write_blackboard", {"key": key, "value": spec}, _ctx(state))
    trigger_result = registry.call("trigger_risk_flow", {"blackboard_key": key}, _ctx(state))

    return {
        "handoff": {
            "blackboard_key": key,
            "project_entry": write_result.get("project_entry"),
            "risk_queue_key": trigger_result.get("risk_queue_key"),
            "risk_review": trigger_result.get("review"),
        }
    }


def produce_output(state: ModelSubmitFlowState) -> dict[str, Any]:
    """汇总 output_data（ModelSpec + handoff 结果）并写 spec JSON artifact。"""
    spec = state["model_spec"]
    handoff = state["handoff"]
    output = {
        "model_name": spec["model_name"],
        "model_spec": spec,
        "blackboard_key": handoff["blackboard_key"],
        "risk_review": handoff["risk_review"],
    }

    artifact_path = Path("artifacts") / "model" / f"{_slug(str(spec['model_name']))}-model-spec.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(spec, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"output_data": output, "artifacts": [artifact_path.as_posix()]}


def build_workflow(checkpoint_db: str | PathLike[str] | None = None):
    """Build the LangGraph app（结构对齐 flows.factor_autoeval.build_workflow）。"""
    try:
        from runner.langgraph_base import (
            create_workflow,
            default_compose_edges,
            get_checkpointer,
        )
    except ImportError as exc:
        raise RuntimeError(
            "LangGraph base is not available yet. Node functions can be tested "
            "directly; call build_workflow() after runner/langgraph_base.py lands."
        ) from exc

    nodes = {
        "parse_pr_input": parse_pr_input,
        "generate_model_spec": generate_model_spec_node,
        "handoff_to_risk": handoff_to_risk,
        "produce_output": produce_output,
    }
    edges = default_compose_edges(list(nodes.keys()))
    workflow = create_workflow(nodes, edges, state_schema=ModelSubmitFlowState)
    return workflow.compile(checkpointer=get_checkpointer(checkpoint_db))


# ---------------------------------------------------------------------------
# 注册（import 即注册）
# ---------------------------------------------------------------------------

_FLOW_GROUP = "model"
_FLOW_NAME = "model:submit"


def register(overwrite: bool = False) -> None:
    """compile 并注册到 FLOW_REGISTRY。"""
    from runner.compose_executor import register_flow

    register_flow(_FLOW_GROUP, _FLOW_NAME, build_workflow(), overwrite=overwrite)


def _auto_register() -> None:
    try:
        register(overwrite=False)
    except KeyError:
        # 已注册（模块 reload / 重复注册）——幂等跳过
        pass


_auto_register()