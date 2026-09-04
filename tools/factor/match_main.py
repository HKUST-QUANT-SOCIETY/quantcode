"""match_main tool — Day 5 Lead 真LLM实现 + P0-7 SSH 主线增强。

用LLM分析因子idea，推断需要的字段和兼容性。
保持与stub相同的schema，只替换_execute函数体。

P0-7（A09-04/05，QuantCode_Design.md 4.2.4）：调用 LLM 前先
``_enrich_with_mainline`` 尝试经 SSH（runner/server_ssh.py）按 idea 关键词匹配
主线服务器的文件列表；命中文件再 read_mainline_file 摘取前 2000 字符拼入
``extra_context["mainline_snippets"]`` 并注入 prompt。无 ssh_mainline 配置 /
paramiko 缺失 / 任何 SSH 或缓存异常 → 静默返回原 extra_context，不阻断 LLM
主路径（诚实降级：SSH 是增强不是依赖）。
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tools.registry import ToolDef

# 摘录与命中数量上限，防止大量命中撑爆 prompt
_MAINLINE_SNIPPET_CHARS = 2000
_MAINLINE_HITS_PER_SERVER = 3
_MAINLINE_MAX_SNIPPETS = 6

# 从 idea 提取 ASCII 关键词（PB-ROE → pb / roe），与主线文件名做子串匹配
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,}")


class MatchMainArgs(BaseModel):
    """match_main tool 的入参 schema。"""

    model_config = ConfigDict(extra="forbid")

    idea: str = Field(min_length=1, max_length=2048, description="因子想法描述,如 'PB-ROE 因子,季度再平衡'")
    extra_context: dict[str, Any] | None = Field(
        default=None,
        description=(
            "调用方可塞入已有因子列表 / 历史等；若配置了 ssh_mainline 且 paramiko 可用，"
            "会自动按 idea 关键词拼入 mainline_snippets（SSH 读主线，失败静默跳过）"
        ),
    )


def _extract_tokens(idea: str) -> list[str]:
    """提取 idea 中的 ASCII 关键词（小写去重），用于与主线文件名做子串匹配。"""
    return sorted({t.lower() for t in _TOKEN_RE.findall(idea)})


def _enrich_with_mainline(
    extra_context: dict[str, Any] | None, idea: str
) -> dict[str, Any]:
    """尝试按 idea 关键词匹配 SSH 主线服务器文件，命中则摘录文件前 2000 字符。

    命中的片段写入返回 dict 的 ``mainline_snippets: [{server, file, excerpt}]``，
    同时保留原 extra_context 的所有键（不改传入对象）。
    任何失败（无 ssh_mainline 配置 / paramiko 缺失 / SSH、缓存异常）都静默返回
    原 extra_context — SSH 读主线是增强，绝不阻断 LLM 主路径。
    """
    base: dict[str, Any] = dict(extra_context) if extra_context else {}
    try:
        from runner import server_ssh

        servers = server_ssh.list_servers()
        if not servers:
            return base
        tokens = _extract_tokens(idea)
        if not tokens:
            return base

        snippets: list[dict[str, str]] = []
        for name in servers:
            try:
                listing = server_ssh.read_mainline_listing(name)
            except Exception:
                continue  # 单台服务器不可用不阻断其余
            hits = [f for f in listing if any(tok in f.lower() for tok in tokens)]
            for fname in hits[:_MAINLINE_HITS_PER_SERVER]:
                try:
                    excerpt = server_ssh.read_mainline_file(
                        name, fname
                    )[:_MAINLINE_SNIPPET_CHARS]
                except Exception:
                    continue
                snippets.append({"server": name, "file": fname, "excerpt": excerpt})
                if len(snippets) >= _MAINLINE_MAX_SNIPPETS:
                    break
            if len(snippets) >= _MAINLINE_MAX_SNIPPETS:
                break
        if snippets:
            base["mainline_snippets"] = snippets
    except Exception:
        pass
    return base


def _format_mainline_block(extra: dict[str, Any]) -> str:
    """把 mainline_snippets 渲染成 prompt 附录段；无片段时返回空串。"""
    snippets = extra.get("mainline_snippets")
    if not snippets:
        return ""
    parts = "\n\n".join(
        f"[{s['server']}] {s['file']}:\n{s['excerpt']}" for s in snippets
    )
    return f"\n\n主线代码参考（SSH 读自主线服务器）:\n{parts}"


def _match_main_execute(args: MatchMainArgs, ctx: dict) -> dict[str, Any]:
    """真LLM实现：分析因子idea，推断需要的字段和兼容性。"""
    from runner.llm_provider import create_deepseek_llm

    # P0-7：先尝试经 SSH 补充主线代码片段（失败静默，extra_context 原样保留）
    extra = _enrich_with_mainline(args.extra_context, args.idea)
    mainline_block = _format_mainline_block(extra)

    # 构造prompt分析因子idea
    prompt = f"""分析以下因子想法，推断需要的数据字段和兼容性：

因子想法：{args.idea}{mainline_block}

请分析：
1. 这个因子是否可以实现（compatible: true/false）
2. 需要哪些数据字段（suggested_fields: 如 ["pb", "roe", "market_cap"]）
3. 实现说明（notes）

常见金融字段参考：
- 估值类：pb, pe, ps, pcf, ev_ebitda
- 盈利类：roe, roa, gross_margin, net_margin
- 成长类：revenue_growth, earnings_growth, eps_growth
- 质量类：asset_turnover, inventory_turnover, debt_to_equity
- 动量类：return_1m, return_3m, return_6m, return_12m
- 波动类：volatility_20d, volatility_60d, beta
- 再平衡：quarterly_rebalance, monthly_rebalance, annual_rebalance

请以JSON格式返回：
{{
  "compatible": true/false,
  "suggested_fields": ["field1", "field2", ...],
  "notes": "简要说明"
}}"""

    try:
        llm = create_deepseek_llm()
        # 调用LLM
        from langchain_core.messages import HumanMessage
        messages = [HumanMessage(content=prompt)]
        if callable(llm):
            response = llm(messages)
        elif hasattr(llm, "invoke"):
            response = llm.invoke(messages)
        else:
            raise TypeError("configured LLM does not implement the supported call protocol")

        # 解析LLM响应
        import json
        content = response.content if hasattr(response, 'content') else str(response)

        # 尝试从markdown代码块中提取JSON
        if "```json" in content:
            json_str = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            json_str = content.split("```")[1].split("```")[0].strip()
        else:
            json_str = content.strip()

        result = json.loads(json_str)

        # 验证必需字段
        if not isinstance(result, dict):
            raise ValueError("LLM response must be a JSON object")
        if "compatible" not in result or not isinstance(result["compatible"], bool):
            raise ValueError("LLM response must contain boolean compatible")
        if "suggested_fields" not in result:
            result["suggested_fields"] = []
        if not isinstance(result["suggested_fields"], list):
            raise ValueError("LLM response suggested_fields must be a list")
        if "notes" not in result:
            result["notes"] = "LLM分析完成"

        return result

    except Exception as e:
        # Failed matching is not evidence of compatibility.
        return {
            "compatible": False,
            "suggested_fields": [],
            "result_status": "UNAVAILABLE",
            "error": f"LLM分析失败: {type(e).__name__}",
            "notes": "LLM分析不可用，未生成主线兼容结论",
        }


match_main_tool = ToolDef(
    id="match_main",
    description=(
        "Given a factor idea (text), return matching mainline fields and a "
        "compatibility verdict. Use this as the first step before generating a FactorSpec."
    ),
    schema=MatchMainArgs,
    execute=_match_main_execute,
)


__all__ = ["MatchMainArgs", "match_main_tool"]
