"""P0-2 model→risk 跨组 handoff 端到端回归（A03/A08）。

链路：
    1. model 组 ctx 写 blackboard（裸 key，写侧经归一层补前缀）
    2. trigger_risk_flow 入队 shared.pending_risk_reviews
    3. 模拟 agent_mcp_tool 队列读取（_start_mode risk 分支调用的同一函数，
       覆盖此前 ``from tools.blackboard.blackboard_service import ...`` 的
       坏 import 被 except 吞掉、risk 组永远收不到 reviews 的缺陷）
    4. risk read_blackboard 读到 ModelSpec（session/key 与写侧两端一致）

P0-2 归一规则：跨组共享条目统一 PROJECT scope + 固定 ``PROJECT_SESSION_ID``，
不再用 thread_id 当 session_id。
"""
from __future__ import annotations

import json
from pathlib import Path

from runner.agent_mcp_tool import _read_pending_risk_reviews
from runner.blackboard import BlackboardService
from runner.blackboard_keys import (
    KEY_MODEL_ENTRY_PREFIX,
    KEY_PENDING_RISK_REVIEWS,
    PROJECT_SESSION_ID,
    make_read_key,
)
from schemas import BlackboardScope, GroupName
from tools.model.trigger_risk_flow import (
    TriggerRiskFlowArgs,
    trigger_risk_flow_execute,
)
from tools.model.write_blackboard import (
    WriteBlackboardArgs,
    write_blackboard_execute,
)
from tools.risk.risk_tools import read_blackboard

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SAMPLE_MODEL_SPEC = FIXTURES_DIR / "sample_model" / "model_spec.json"


def _sample_model_spec() -> dict:
    return json.loads(SAMPLE_MODEL_SPEC.read_text(encoding="utf-8"))


def test_model_to_risk_handoff_end_to_end(tmp_path):
    db_path = tmp_path / "blackboard.db"
    thread_id = "model-thread-e2e"
    model_ctx = {
        "thread_id": thread_id,
        "group": "model",
        "blackboard_db_path": str(db_path),
    }

    # 1) model 组 ctx 写 blackboard（裸 key；写侧归一补 shared.model_entries. 前缀）
    write_result = write_blackboard_execute(
        WriteBlackboardArgs(key="model_spec", value=_sample_model_spec()),
        ctx=model_ctx,
    )
    stored_key = write_result["project_entry"]["key"]
    assert stored_key == KEY_MODEL_ENTRY_PREFIX + "model_spec"

    # 2) trigger_risk_flow：传裸 key（归一层幂等解析到同一 entry），入队
    trigger_result = trigger_risk_flow_execute(
        TriggerRiskFlowArgs(blackboard_key="model_spec"),
        ctx=model_ctx,
    )
    assert trigger_result["risk_queue_key"] == KEY_PENDING_RISK_REVIEWS
    assert trigger_result["review"]["status"] == "pending"
    assert trigger_result["review"]["to_group"] == "risk"
    assert trigger_result["review"]["blackboard_key"] == "model_spec"

    # 3) 模拟 agent_mcp_tool 队列读取（_start_mode risk 分支的同款读取路径）
    review_count = _read_pending_risk_reviews(db_path=db_path)
    assert review_count == 1, (
        "risk 组启动时应能从 PROJECT scope 读到 model 组触发的 pending review"
    )

    # 4) risk read_blackboard 读 ModelSpec——写读两端 (session_id, entry_key) 一致
    result = read_blackboard({
        "blackboard_db_path": str(db_path),
        # 缺省 blackboard_key="model_spec"，读侧归一后命中写侧条目
    })
    assert result["model_spec"]["model_name"] == "pb_roe_ranker"

    # 传写侧返回的完整 key 也能读到（幂等归一）
    result_by_full_key = read_blackboard({
        "blackboard_db_path": str(db_path),
        "blackboard_key": stored_key,
    })
    assert result_by_full_key == result

    # P0-2 回归锚点：条目写在固定 PROJECT session 下，不再挂在 thread_id session
    stale_board = BlackboardService(
        db_path=db_path,
        session_id=thread_id,
        requester_group=GroupName.RISK,
    )
    assert stale_board.get_entry(
        BlackboardScope.PROJECT, None, make_read_key("model_spec")
    ) is None

    # risk 组在 PROJECT session 下也能直接读到 model 条目（PROJECT scope 跨组可读）
    risk_board = BlackboardService(
        db_path=db_path,
        session_id=PROJECT_SESSION_ID,
        requester_group=GroupName.RISK,
    )
    entry = risk_board.get_entry(BlackboardScope.PROJECT, None, stored_key)
    assert entry is not None
    assert entry.value["model_name"] == "pb_roe_ranker"
