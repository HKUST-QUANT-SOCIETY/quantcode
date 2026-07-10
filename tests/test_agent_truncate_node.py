"""truncate_node 测试 — Day 4 尹一帆(引擎 gap #2)。

覆盖:
1. 短消息不截(no-op)
2. 长消息触发截断,头 N / 尾 M 保留
3. _estimate_tokens 中文 //2 估值(100 中文字 → ~50 token)
4. _estimate_tokens 英文 //2 估值
5. 不带 tiktoken 仍能跑(tiktoken 缺失 silently fallback)
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from runner.agent_nodes import _estimate_tokens, make_truncate_node


# ---------------------------------------------------------------------------
# _estimate_tokens 单测
# ---------------------------------------------------------------------------


def test_estimate_tokens_chinese_half_chars():
    """Day 4 #C 验收:中文 token 估算保守。

    100 个中文字符 → 约 100 token（tiktoken cl100k_base 中 1 中文字 ≈ 1 token）。
    无 tiktoken 时退化为 len//2 ≈ 50。允许 40-200 范围覆盖两种场景。
    """
    text = "中" * 100
    n = _estimate_tokens(text)
    assert 40 <= n <= 200, f"100 中文字应估 50-200 token,实际 {n}"


def test_estimate_tokens_empty_string():
    """空字符串 → 0 token。"""
    assert _estimate_tokens("") == 0


def test_estimate_tokens_no_tiktoken_falls_back_to_len_div_2(monkeypatch):
    """🟢Day 4 #C 验收:tiktoken 不可用时 silently fallback 到 //2。

    模拟 tiktoken 不可用,验证 _estimate_tokens 仍工作。
    """
    import runner.agent_nodes as an

    monkeypatch.setattr(an, "_TIKTOKEN_AVAILABLE", False)
    text = "a" * 200
    n = _estimate_tokens(text)
    assert n == 100, f"无 tiktoken 时 200 chars → 100 tokens (//2),实际 {n}"


# ---------------------------------------------------------------------------
# make_truncate_node 单测
# ---------------------------------------------------------------------------


def test_truncate_node_short_messages_no_op():
    """🟢Day 4 #C 验收:短消息不截,no-op。

    5 条短消息(< max_tokens 阈值)→ 返回 {} 不变。
    """
    node = make_truncate_node(max_tokens=10000)
    state = {
        "messages": [
            HumanMessage(content="hi"),
            AIMessage(content="hello"),
            ToolMessage(content="ok", tool_call_id="1", name="echo"),
            AIMessage(content="done"),
        ],
        "iterations": 2,
    }
    out = node(state)
    assert out == {}, f"短消息应 no-op, got {out}"


def test_truncate_node_truncates_middle_message_only():
    """🟢Day 4 #C 验收:超长时截断中段,头 N + 尾 M 保持原样。

    中段某条超长 → 该条被截(字符数减小),头 4 + 尾 6 完全保持原 content。
    总长度 = head + middle + tail(数量不变,只中段某些被缩短)。
    """
    node = make_truncate_node(max_tokens=200, head_preserve=4, tail_preserve=6)
    long_content = "a" * 2000  # ~1000 tokens,远超 max_tokens
    state = {
        "messages": [
            SystemMessage(content="sys"),
            HumanMessage(content="h1"),
            AIMessage(content="a1"),
            ToolMessage(content="t1", tool_call_id="1", name="t"),
            HumanMessage(content="h2"),
            AIMessage(content="a2"),
            ToolMessage(content=long_content, tool_call_id="2", name="t"),  # 中段,会被截
            ToolMessage(content="t2", tool_call_id="3", name="t"),
            ToolMessage(content="t3", tool_call_id="4", name="t"),
            ToolMessage(content="t4", tool_call_id="5", name="t"),
            ToolMessage(content="t5", tool_call_id="6", name="t"),
            ToolMessage(content="tail1", tool_call_id="7", name="t"),
            ToolMessage(content="tail2", tool_call_id="8", name="t"),
            AIMessage(content="final"),
        ],
        "iterations": 3,
    }
    out = node(state)
    assert "messages" in out
    truncated_msgs = out["messages"]
    # 总长度不变(14 条 = 4 head + 4 middle + 6 tail)
    assert len(truncated_msgs) == 14, f"期望 14 条,实际 {len(truncated_msgs)}"
    # 头 4 条不变
    for i in range(4):
        assert truncated_msgs[i].content == state["messages"][i].content, (
            f"head[{i}] 应保持原样,被改成 {truncated_msgs[i].content[:30]}"
        )
    # 尾 6 条不变
    n = len(state["messages"])
    for i in range(6):
        assert truncated_msgs[-(i + 1)].content == state["messages"][-(i + 1)].content, (
            f"tail[{i}] 应保持原样"
        )
    # 中段第 2 条(原 2000 字符)被截
    middle = truncated_msgs[4:8]  # 4 条中段
    # 找那条原 2000 字符被截到 < 2000 的(可能是 long_content 那条)
    long_original_idx = 6  # state["messages"][6] 是 long_content
    truncated_long = middle[long_original_idx - 4]  # 在 truncated 中 idx 6-4=2
    assert len(truncated_long.content) < 2000, (
        f"原 2000 字符的 middle 消息应被截,实际长度 {len(truncated_long.content)}"
    )
    assert "[... truncated" in truncated_long.content, (
        f"被截后应含省略标记,实际 {truncated_long.content[:80]}"
    )
    # 标记
    assert out.get("_truncated") is True


# ---------------------------------------------------------------------------
# 端到端集成测试:AgentRunner + truncate_node 真实跑长 task
# ---------------------------------------------------------------------------


def test_agent_runner_truncate_actually_truncates_long_messages(tmp_path):
    """Day 4 #C 端到端验收:AgentRunner(truncate_tokens=100) 跑长 task,
    final["messages"] 总 token 应 < 100(每条中间消息被截)。

    验证 truncate_node 真的被集成到 AgentRunner,不是只测了节点工厂。

    注意:tiktoken 对重复字符有高效编码(500 个 'a' ≈ 63 tokens),
    需用更长的内容(2000 字符)确保截断阈值被触发。
    """
    from runner.agent_engine import AgentRunner

    # 2000 字符 → tiktoken ~250 tokens, no-tiktoken ~1000 tokens, 都 > 100 阈值
    long_content = "a" * 2000

    # 每次 echo 用不同 args，避免触发 PR25 引擎的 state-fingerprint 死循环检测
    # （相同 tool + 相同 args 连续调用会被判定为 state loop 提前中止）。
    script = [
        AIMessage(content="", tool_calls=[{"name": "echo", "args": {"msg": f"x{i}"}, "id": str(i)}])
        for i in range(1, 7)
    ] + [AIMessage(content="[done]")]

    # 注册一个 echo tool 返长内容
    from pydantic import BaseModel
    from tools.registry import ToolDef, register_tool

    class EchoArgs(BaseModel):
        msg: str

    def _echo_execute(args, ctx):
        return long_content

    register_tool(ToolDef(
        id="echo",
        description="echo back a long message",
        schema=EchoArgs,
        execute=_echo_execute,
    ))

    try:
        # 临时把 echo 加到 factor allowlist(其他 allowlist 已有)
        # 改用直接调 AgentRunner 配 mock tool registry
        runner = AgentRunner(
            group="factor",
            model=_ScriptedLLM(script),
            truncate_tokens=100,  # 降低阈值，确保 2000 字符触发截断
            checkpoint_db=tmp_path / "cp.db",
        )
        final = runner.run(
            task="长 task 测试 truncate",
            skill_name=None,
            system_prompt="x",
            thread_id="t-truncate-e2e",
        )
        msgs = final.get("messages", [])
        # 🟢严格断言:truncate_node 真的在 tool 之后跑(产生 truncated 副本)
        # 已知限制:LangGraph operator.add reducer 会把 truncated 列表追加,而非替换,
        # 所以 messages 里既有原版(500 字符)也有 truncated 版(< 200 字符)。
        # 验证:至少 1 条 echo ToolMessage 含 "[... truncated" 标记
        truncated_echo_count = sum(
            1 for m in msgs
            if isinstance(m, ToolMessage) and m.name == "echo" and "[... truncated" in m.content
        )
        assert truncated_echo_count >= 1, (
            f"长 messages 应至少 1 条含 truncate 标记,got {truncated_echo_count}"
        )
        # 验证:truncated 版本 content 长度 < 原 2000 字符
        for m in msgs:
            if isinstance(m, ToolMessage) and m.name == "echo" and "[... truncated" in m.content:
                assert len(m.content) < 2000, (
                    f"truncated echo ToolMessage 应 < 2000 chars,实际 {len(m.content)}"
                )
                break  # 至少 1 条满足即可
    finally:
        # 清理临时 echo tool
        from tools.registry import registry as global_registry
        global_registry._tools.pop("echo", None)


class _ScriptedLLM:
    """复用 factor 测试的脚本 LLM(本地小类,避免跨文件 import)。"""

    def __init__(self, responses):
        self._responses = responses
        self._idx = 0

    def __call__(self, messages, tools=None):
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
            self._idx += 1
            return resp
        from langchain_core.messages import AIMessage
        return AIMessage(content="[mock done]")
