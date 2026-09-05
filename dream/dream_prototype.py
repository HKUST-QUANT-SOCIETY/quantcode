"""Dream 原型 — Day 4 尹一帆。

对齐 Day4 §1.4:扫 execution trace → LLM 提取 → 写 memory ≥1 条 → 检索可命中。

数据源优先级:
- 主源 = ``checkpoints.db``(SqliteSaver,Day4 §1.4 原文要求)
- fallback = ``rlhf_data.jsonl``(若 checkpoints.db 无 trace)

用法::

    from dream.dream_prototype import run_dream
    hits = run_dream(trace_source="auto", llm_mode="mock")
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field


class _DreamSummary(BaseModel):
    """Dream 一次扫描的产出结构。"""

    repetitions: list[str] = Field(default_factory=list, description="重复操作模式")
    lessons: list[str] = Field(default_factory=list, description="教训/改进点")
    hotspots: list[str] = Field(default_factory=list, description="高频 tool / 字段")


def _load_last_checkpoint_trace(db_path: Path) -> dict | None:
    """从 SqliteSaver 的 checkpoints 表读最近一条 trace。

    SqliteSaver 表 schema(LangGraph 0.2+ 实测):
    - thread_id TEXT
    - checkpoint_ns TEXT (DESC 时最新)
    - checkpoint_id TEXT
    - parent_checkpoint_id TEXT
    - type TEXT
    - checkpoint BLOB (msgpack 序列化)
    - metadata BLOB

    返回 dict 包含:
    - thread_id
    - checkpoint_id
    - checkpoint_present(bool)
    - raw(checkpoint blob 字节,供 debug)

    注:SqliteSaver 的 checkpoint 是 msgpack 序列化,完整反序列化需要 langgraph 内部 API;
    本原型**只取 thread_id 和 checkpoint_id**,不深解 checkpoint 内部结构。
    """
    if not db_path.exists():
        return None
    try:
        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute(
                "SELECT thread_id, checkpoint_id, checkpoint FROM checkpoints "
                "ORDER BY checkpoint_ns DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        thread_id, checkpoint_id, checkpoint_blob = row
        return {
            "thread_id": thread_id,
            "checkpoint_id": checkpoint_id,
            "checkpoint_present": bool(checkpoint_blob),
            "raw": checkpoint_blob,
        }
    except sqlite3.DatabaseError as e:
        # 表结构可能跟 langgraph 版本不匹配(降级到 fallback)
        import warnings

        warnings.warn(f"dream: checkpoints.db read failed: {e}", stacklevel=2)
        return None


def _extract_text_from_blob(blob: bytes) -> list[str]:
    """从 checkpoint blob(可能 msgpack 序列化)粗略提取文本片段。

    简化实现:用 msgpack 反序列化(若装了),否则按 utf-8 容错 decode 抓 ASCII。
    本原型不追求完整 messages 还原——只取文本概要供 LLM 摘要。
    """
    if not blob:
        return []
    try:
        import msgpack  # type: ignore

        obj = msgpack.unpackb(blob, raw=False, strict_map_key=False)
        # 递归找 string 字段
        out: list[str] = []
        _walk_strings(obj, out, max_depth=8)
        return out[:50]  # 限 50 段
    except Exception:
        # fallback:粗略 decode
        try:
            text = blob.decode("utf-8", errors="ignore")
            # 按非 ascii 控制字符切段
            import re

            chunks = re.findall(r"[\x20-\x7e]{20,}", text)
            return chunks[:50]
        except Exception:
            return []


def _walk_strings(obj: Any, out: list[str], *, max_depth: int) -> None:
    """递归 walk msgpack 反序列化对象,收集所有 string 字段。"""
    if max_depth <= 0:
        return
    if isinstance(obj, str) and len(obj) > 5:
        out.append(obj[:500])
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk_strings(v, out, max_depth=max_depth - 1)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk_strings(v, out, max_depth=max_depth - 1)


def _load_last_rlhf_record(rlhf_path: Path) -> dict | None:
    """从 .quantcode/rlhf_data.jsonl 读最后一行非空 JSON。"""
    if not rlhf_path.exists():
        return None
    try:
        last: dict | None = None
        with rlhf_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    last = json.loads(line)
                except json.JSONDecodeError:
                    continue
        return last
    except OSError:
        return None


def _load_rlhf_aggregate(rlhf_path: Path) -> dict | None:
    """Day 5 补强：聚合 rlhf_data.jsonl 的**所有**记录，而非只取最后一条。

    产出一个 record，除了保留最后一条的字段（向后兼容），额外附上跨条聚合：
    - ``_aggregate.total_records`` / ``_thread_count`` / ``_groups``
    - ``_aggregate.tool_frequency``：tool_name → 次数（降序）
    - ``_aggregate.top_tools``：最高频的几个 tool

    这样 LLM 摘要能看到"整体重复模式"，而不是被单条 trace 局限。
    """
    if not rlhf_path.exists():
        return None
    try:
        records: list[dict] = []
        with rlhf_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return None

    if not records:
        return None

    from collections import Counter

    tool_freq: Counter = Counter()
    threads: set[str] = set()
    groups: set[str] = set()
    for rec in records:
        action = rec.get("action", {})
        name = action.get("tool_name", "") if isinstance(action, dict) else ""
        if name:
            tool_freq[name] += 1
        if tid := rec.get("thread_id"):
            threads.add(tid)
        if grp := rec.get("group"):
            groups.add(grp)

    # 以最后一条为基底（保留 thread_id 等字段），叠加聚合视图
    base = dict(records[-1])
    base["_aggregate"] = {
        "total_records": len(records),
        "thread_count": len(threads),
        "groups": sorted(groups),
        "tool_frequency": dict(tool_freq.most_common()),
        "top_tools": [t for t, _ in tool_freq.most_common(5)],
    }
    return base


def _summarize_with_llm(
    record: dict | None,
    *,
    llm_mode: str,
    model: Callable | None,
) -> _DreamSummary:
    """调 LLM 提取 3 段(repetitions/lessons/hotspots)。

    mock mode:返固定 summary(供测试)
    real mode:调 model(prompt),期望 model 返 _DreamSummary dict(JSON 格式)
    """
    if llm_mode == "mock":
        return _DreamSummary(
            repetitions=[
                "Agent 连续调 read_blackboard ≥3 次(typical fetch pattern)",
                "calc_risk 后立即 risk_verdict(typical gate flow)",
            ],
            lessons=[
                "high_risk scenario 必须先经 risk_verdict 再调 write_pr_comment",
                "rlhf collector 记录每次 tool 调用的 state_fingerprint,便于事后审计",
            ],
            hotspots=[
                "calc_risk:high_risk",
                "risk_verdict:breached",
                "write_pr_comment:pr_url",
            ],
        )
    # real mode
    if model is None:
        raise ValueError("dream: llm_mode='real' 必须传 model")
    prompt = (
        "Given the following execution trace, extract 3 sections:\n"
        "- repetitions: repeated tool call patterns\n"
        "- lessons: insights / improvements for future runs\n"
        "- hotspots: high-frequency tool names or fields\n\n"
        f"Trace: {json.dumps(record, ensure_ascii=False, default=str)[:2000]}\n\n"
        "Return JSON with keys: repetitions (list[str]), lessons (list[str]), "
        "hotspots (list[str])"
    )
    result = model(prompt)
    if isinstance(result, _DreamSummary):
        return result
    if isinstance(result, dict):
        return _DreamSummary(**result)
    if isinstance(result, str):
        try:
            return _DreamSummary(**json.loads(result))
        except Exception:
            pass
    raise ValueError(f"dream: unexpected model return type: {type(result)}")


def run_dream(
    trace_source: str = "auto",
    *,
    db_path: str | Path = ".quantcode/checkpoints.db",
    rlhf_path: str | Path = ".quantcode/rlhf_data.jsonl",
    memory_root: str | Path = ".quantcode",
    llm_mode: str = "auto",
    model: Callable | None = None,
) -> list[dict]:
    """Dream 主入口:扫 trace → LLM 提取 → 写 memory → 返 search 结果。

    Args:
        trace_source: ``"auto"`` 优先 checkpoints 再 rlhf;``"checkpoints"`` 强制主源;``"rlhf"`` 强制 fallback
        db_path: SqliteSaver checkpoint db 路径
        rlhf_path: rlhf_data.jsonl 路径
        memory_root: MemoryService 写入根目录(默认 ``.quantcode/``)
        llm_mode: ``"auto"`` 有 config.json 就用 real DeepSeek,没有就 fallback mock;
                  ``"mock"`` 用固定 summary;``"real"`` 调 model
        model: ``llm_mode="real"`` 必传,签名 ``(prompt: str) -> dict | str | _DreamSummary``;
               ``llm_mode="auto"`` 时可选,不传则自动从 config.json 创建 DeepSeek LLM

    Returns:
        MemoryService.search 返回的 hits 列表(每个是 dict 含 path/scope/type/snippet/score)

    Raises:
        ValueError: ``llm_mode="real"`` 但 model=None
    """
    db_path = Path(db_path)
    rlhf_path = Path(rlhf_path)
    memory_root = Path(memory_root)

    # 1. 选 trace source
    record: dict | None = None
    source_used: str = ""
    if trace_source in ("auto", "checkpoints"):
        record = _load_last_checkpoint_trace(db_path)
        if record is not None:
            source_used = "checkpoints"
    if record is None and trace_source in ("auto", "rlhf"):
        # Day 5 补强：优先聚合所有 rlhf 记录（跨 trace 模式），失败退回单条。
        record = _load_rlhf_aggregate(rlhf_path) or _load_last_rlhf_record(rlhf_path)
        if record is not None:
            source_used = "rlhf"
    if record is None:
        return []

    # 2. 从 checkpoint blob 提取文本(若 source_used=checkpoints)
    if source_used == "checkpoints" and "raw" in record:
        texts = _extract_text_from_blob(record["raw"])
        record["_extracted_texts"] = texts

    # 3. LLM 提取 —— auto 模式:有 config.json 就用 DeepSeek,没有就 mock
    if llm_mode == "auto":
        if model is not None:
            # 显式传了 model,直接用
            summary = _summarize_with_llm(record, llm_mode="real", model=model)
        else:
            # 尝试从 config.json 创建 DeepSeek LLM
            try:
                from runner.llm_provider import create_deepseek_llm

                deepseek = create_deepseek_llm()
                # 包装成 Dream 需要的 (prompt: str) -> dict 签名
                def _dream_model(prompt: str) -> dict:
                    import json as _json
                    from langchain_core.messages import HumanMessage

                    result = deepseek([HumanMessage(content=prompt)])
                    content = result.content if hasattr(result, "content") else str(result)
                    try:
                        return _json.loads(content)
                    except (_json.JSONDecodeError, TypeError):
                        import re
                        match = re.search(r"\{[\s\S]*\}", content)
                        if match:
                            try:
                                return _json.loads(match.group(0))
                            except _json.JSONDecodeError:
                                pass
                        return {
                            "repetitions": [f"LLM output (raw): {content[:200]}"],
                            "lessons": ["Dream auto mode — parse failed, using raw output"],
                            "hotspots": [],
                        }

                summary = _summarize_with_llm(record, llm_mode="real", model=_dream_model)
            except ValueError:
                # config.json 不存在或无 API key → fallback mock
                import warnings
                warnings.warn(
                    "dream: config.json 未配置,使用 mock 模式。"
                    "复制 config.example.json 为 config.json 并填入 API key 启用真 LLM。",
                    stacklevel=2,
                )
                summary = _summarize_with_llm(record, llm_mode="mock", model=None)
    else:
        summary = _summarize_with_llm(record, llm_mode=llm_mode, model=model)

    # 4. 写 memory
    from runner.memory.service import MemoryService  # 延迟 import 避免循环

    mem_db = memory_root / "memory.db"
    mem = MemoryService(db_path=str(mem_db), root=str(memory_root))

    thread_id = record.get("thread_id", "unknown")
    body = (
        f"# Dream Summary for {thread_id}\n\n"
        f"**Source**: {source_used}\n\n"
        f"## Repetitions\n\n"
        + "\n".join(f"- {r}" for r in summary.repetitions)
        + "\n\n## Lessons\n\n"
        + "\n".join(f"- {l}" for l in summary.lessons)
        + "\n\n## Hotspots\n\n"
        + "\n".join(f"- {h}" for h in summary.hotspots)
        + "\n"
    )

    mem.write(
        scope="global",
        scope_id=None,
        type="memory",
        key=f"dream/{thread_id}.md",
        body=body,
        requester_group="dream",
    )

    # 5. 检索,验证 ≥1 hit
    hits = mem.search(
        query=thread_id,
        scope="global",
        type="memory",
        limit=5,
    )
    return [
        {
            "path": h.path,
            "scope": h.scope,
            "type": h.type,
            "snippet": h.snippet,
            "score": h.score,
        }
        for h in hits
    ]


__all__ = ["run_dream", "_DreamSummary"]
