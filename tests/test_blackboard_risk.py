"""Tests for BlackboardService integration with risk read_blackboard."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from runner.blackboard import BlackboardService
from runner.blackboard_keys import make_read_key
from schemas import BlackboardScope, GroupName, WritePolicy
from tools.risk.risk_tools import read_blackboard


def _sample_model_spec() -> dict:
    path = Path(__file__).resolve().parent / "fixtures/sample_model/model_spec.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_read_blackboard_from_blackboard_service_project_scope(tmp_path):
    db_path = tmp_path / "blackboard.db"
    # P0-2：session 归一为 PROJECT_SESSION_ID，读侧（read_blackboard）固定用它
    from runner.blackboard_keys import PROJECT_SESSION_ID

    service = BlackboardService(db_path=db_path, session_id=PROJECT_SESSION_ID)
    model_spec = _sample_model_spec()
    service.write_value(
        scope=BlackboardScope.PROJECT,
        # 写侧 key 与读侧归一结果一致（裸名 → shared.model_entries. 前缀）
        key=make_read_key("model_spec"),
        value=model_spec,
        written_by_task_id="T0001",
        written_by_group=GroupName.MODEL,
    )

    result = read_blackboard({
        "project_id": "test-project-001",
        "blackboard_db_path": str(db_path),
        "blackboard_key": "model_spec",
    })

    assert result["model_spec"]["model_name"] == "pb_roe_ranker"


def test_read_blackboard_fallback_still_works():
    model_spec = _sample_model_spec()
    result = read_blackboard({"model_spec": model_spec})
    assert result["model_spec"]["model_name"] == "pb_roe_ranker"
