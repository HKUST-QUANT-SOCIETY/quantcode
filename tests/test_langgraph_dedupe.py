from __future__ import annotations

from typing import Any, TypedDict

import pytest

from runner.langgraph_base import (
    clear_checkpointer_cache,
    create_workflow,
    default_compose_edges,
    get_checkpointer,
)
from tools.utils.dedupe import dedupe_within


class MiniFactorState(TypedDict, total=False):
    group: str
    flow_name: str
    input_data: dict[str, Any]
    input_spec: dict[str, Any]
    eval_result: dict[str, Any]
    output_data: dict[str, Any]


def _compile_demo_app(tmp_path, call_autoeval_api):
    def validate_factor_spec(state: MiniFactorState) -> dict[str, Any]:
        return {"input_spec": {"name": state["input_data"]["name"]}}

    def generate_report(state: MiniFactorState) -> dict[str, Any]:
        return {"output_data": state["eval_result"]}

    workflow = create_workflow(
        nodes={
            "validate": validate_factor_spec,
            "call_autoeval": call_autoeval_api,
            "generate_report": generate_report,
        },
        edges=default_compose_edges(["validate", "call_autoeval", "generate_report"]),
        state_schema=MiniFactorState,
    )
    return workflow.compile(checkpointer=get_checkpointer(tmp_path / "checkpoints.db"))


@pytest.fixture(autouse=True)
def close_cached_checkpointers():
    yield
    clear_checkpointer_cache()


def test_dedupe_within_langgraph_node_returns_cached_result_for_same_factor(tmp_path):
    calls: list[str] = []

    @dedupe_within(
        seconds=300,
        key=lambda state: state["input_spec"]["name"],
        db_path=tmp_path / "dedupe.sqlite",
    )
    def call_autoeval_api(state: MiniFactorState) -> dict[str, Any]:
        factor_name = state["input_spec"]["name"]
        calls.append(factor_name)
        return {"eval_result": {"factor_name": factor_name, "call_number": len(calls)}}

    app = _compile_demo_app(tmp_path, call_autoeval_api)
    input_state = {
        "group": "factor",
        "flow_name": "factor:autoeval",
        "input_data": {"name": "pb_roe"},
    }

    first = app.invoke(
        input_state,
        config={"configurable": {"thread_id": "factor-autoeval-dedupe-1"}},
    )
    second = app.invoke(
        input_state,
        config={"configurable": {"thread_id": "factor-autoeval-dedupe-2"}},
    )

    assert first["output_data"] == {"factor_name": "pb_roe", "call_number": 1}
    assert second["output_data"] == {"factor_name": "pb_roe", "call_number": 1}
    assert calls == ["pb_roe"]


def test_dedupe_within_langgraph_node_keeps_different_factors_separate(tmp_path):
    calls: list[str] = []

    @dedupe_within(
        seconds=300,
        key=lambda state: state["input_spec"]["name"],
        db_path=tmp_path / "dedupe.sqlite",
    )
    def call_autoeval_api(state: MiniFactorState) -> dict[str, Any]:
        factor_name = state["input_spec"]["name"]
        calls.append(factor_name)
        return {"eval_result": {"factor_name": factor_name, "call_number": len(calls)}}

    app = _compile_demo_app(tmp_path, call_autoeval_api)

    pb_roe = app.invoke(
        {"group": "factor", "flow_name": "factor:autoeval", "input_data": {"name": "pb_roe"}},
        config={"configurable": {"thread_id": "factor-autoeval-pb-roe"}},
    )
    eps_growth = app.invoke(
        {
            "group": "factor",
            "flow_name": "factor:autoeval",
            "input_data": {"name": "eps_growth"},
        },
        config={"configurable": {"thread_id": "factor-autoeval-eps-growth"}},
    )

    assert pb_roe["output_data"] == {"factor_name": "pb_roe", "call_number": 1}
    assert eps_growth["output_data"] == {"factor_name": "eps_growth", "call_number": 2}
    assert calls == ["pb_roe", "eps_growth"]


def test_failed_langgraph_node_is_not_deduped_and_resumes_from_failed_step(tmp_path):
    validate_calls: list[str] = []
    call_attempts: list[str] = []

    def validate_factor_spec(state: MiniFactorState) -> dict[str, Any]:
        factor_name = state["input_data"]["name"]
        validate_calls.append(factor_name)
        return {"input_spec": {"name": factor_name}}

    @dedupe_within(
        seconds=300,
        key=lambda state: state["input_spec"]["name"],
        db_path=tmp_path / "dedupe.sqlite",
    )
    def call_autoeval_api(state: MiniFactorState) -> dict[str, Any]:
        factor_name = state["input_spec"]["name"]
        call_attempts.append(factor_name)
        if len(call_attempts) == 1:
            raise RuntimeError("temporary autoeval outage")
        return {"eval_result": {"factor_name": factor_name, "attempt": len(call_attempts)}}

    def generate_report(state: MiniFactorState) -> dict[str, Any]:
        return {"output_data": state["eval_result"]}

    workflow = create_workflow(
        nodes={
            "validate": validate_factor_spec,
            "call_autoeval": call_autoeval_api,
            "generate_report": generate_report,
        },
        edges=default_compose_edges(["validate", "call_autoeval", "generate_report"]),
        state_schema=MiniFactorState,
    )
    app = workflow.compile(checkpointer=get_checkpointer(tmp_path / "checkpoints.db"))
    config = {"configurable": {"thread_id": "factor-autoeval-resume"}}

    with pytest.raises(RuntimeError, match="temporary autoeval outage"):
        app.invoke(
            {
                "group": "factor",
                "flow_name": "factor:autoeval",
                "input_data": {"name": "pb_roe"},
            },
            config=config,
        )

    result = app.invoke(None, config=config)

    assert result["output_data"] == {"factor_name": "pb_roe", "attempt": 2}
    assert validate_calls == ["pb_roe"]
    assert call_attempts == ["pb_roe", "pb_roe"]
