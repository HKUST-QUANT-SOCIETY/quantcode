"""Tests for runner.rlhf_collector.RLHFCollector.

Day 3 — Agent 引擎的 RLHF 接入点。覆盖写入、序列化、上下文管理器、父目录创建等。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from runner.rlhf_collector import RLHFCollector, _make_serializable


# ---------------------------------------------------------------------------
# Stubs / helpers
# ---------------------------------------------------------------------------

class _StubMessage:
    """伪装成 LangChain BaseMessage 的最小 duck type：class 名以 ``Message`` 结尾 + content 属性。"""

    def __init__(self, content: str) -> None:
        self.content = content

    def __repr__(self) -> str:
        return f"_StubMessage({self.content!r})"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_record_writes_one_line(tmp_path: Path) -> None:
    path = tmp_path / "rlhf.jsonl"
    collector = RLHFCollector(path)
    try:
        collector.record({"k": "v"}, {"tool": "x"}, 0.5)
    finally:
        collector.close()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["state"] == {"k": "v"}
    assert parsed["action"] == {"tool": "x"}
    assert parsed["reward"] == 0.5
    assert "timestamp" in parsed
    assert isinstance(parsed["timestamp"], float)



def test_record_flushes_after_each_write(tmp_path: Path) -> None:
    """``record`` 后应立即落盘：未 ``close`` 也能从文件读到刚刚写入的数据。"""
    path = tmp_path / "rlhf.jsonl"
    collector = RLHFCollector(path)
    try:
        collector.record({"k": 1}, {"tool": "x"}, 0.1)
        # 不调用 close，直接读文件 —— 必须看得到已 flush
        content = path.read_text(encoding="utf-8")
        assert content.strip()  # 非空
        parsed = json.loads(content.splitlines()[0])
        assert parsed["state"] == {"k": 1}
    finally:
        collector.close()
def test_record_handles_langchain_messages(tmp_path: Path) -> None:
    """state 含 BaseMessage duck-type 对象时，应序列化为 content 字符串。"""
    path = tmp_path / "rlhf.jsonl"
    msg = _StubMessage("hello world")
    collector = RLHFCollector(path)
    try:
        collector.record(
            {"messages": [msg], "other": "x"},
            {"tool": "y"},
            0.7,
        )
    finally:
        collector.close()

    parsed = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    # BaseMessage 已被降级为字符串 content
    assert parsed["state"]["messages"] == ["hello world"]
    assert parsed["state"]["other"] == "x"


def test_record_handles_datetime(tmp_path: Path) -> None:
    """state 含 datetime 对象时，应序列化为 isoformat 字符串。"""
    path = tmp_path / "rlhf.jsonl"
    dt = datetime(2026, 7, 4, 12, 0, 0)
    collector = RLHFCollector(path)
    try:
        collector.record({"ts": dt}, {"tool": "y"}, 0.2)
    finally:
        collector.close()

    parsed = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert parsed["state"]["ts"] == dt.isoformat()


def test_context_manager(tmp_path: Path) -> None:
    """上下文管理器语法可用，退出 with 块后文件应已关闭。"""
    path = tmp_path / "rlhf.jsonl"
    with RLHFCollector(path) as c:
        c.record({"k": "v"}, {"tool": "x"}, 0.5)
        # Day 3 评审修复：MAX_RECORDS_PER_FLUSH 常量与阈值计数器已删除，
        # 每条 record() 直接 flush，无需再验证阈值。
        assert not c._fp.closed  # 退出前不关闭

    # 退出 with 后应已关闭
    assert c._fp.closed

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["state"] == {"k": "v"}


def test_creates_parent_dir(tmp_path: Path) -> None:
    """传入不存在的父目录路径，应自动创建。"""
    nested = tmp_path / "deep" / "nest" / "rlhf.jsonl"
    assert not nested.parent.exists()  # 防御性确认：测试前确实不存在

    with RLHFCollector(nested) as c:
        c.record({"k": 1}, {"tool": "x"}, 0.0)

    assert nested.exists()
    assert nested.parent.is_dir()


# ---------------------------------------------------------------------------
# 直接覆盖 _make_serializable 的边界用例
# ---------------------------------------------------------------------------

def test_make_serializable_basic_types() -> None:
    """基本类型应原样返回。"""
    assert _make_serializable(None) is None
    assert _make_serializable(True) is True
    assert _make_serializable(42) == 42
    assert _make_serializable(3.14) == 3.14
    assert _make_serializable("hello") == "hello"


def test_make_serializable_nested_dict() -> None:
    """嵌套 dict / list / 混合 BaseMessage 都应被递归处理。"""
    msg = _StubMessage("hi")
    out = _make_serializable(
        {"a": 1, "b": [1, 2, {"c": msg}], "d": {"e": [msg]}}
    )
    assert out == {"a": 1, "b": [1, 2, {"c": "hi"}], "d": {"e": ["hi"]}}
