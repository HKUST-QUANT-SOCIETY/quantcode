"""render_report tool — 生成研报 artifact（markdown 含 PIT/财务/DCF；Typst 可选）。"""
from __future__ import annotations

import shutil
import subprocess
import time
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from schemas.fundamental import ResearchResult, SectionType
from tools.registry import PROJECT_ROOT, ToolDef
from tools.utils.paths import safe_filename_component


class RenderReportArgs(BaseModel):
    target_identifier: str = Field(min_length=1)
    target_name: str | None = None
    as_of_date: date
    research_questions: list[str] = Field(default_factory=list)
    fair_value_per_share: float | None = None
    citations_count: int = Field(default=12, ge=0)
    sections: list[str] = Field(
        default_factory=lambda: [
            "overview",
            "business",
            "financials",
            "valuation",
            "risks",
        ]
    )
    use_typst: bool = Field(
        default=True,
        description="若本机有 typst，尝试编译 templates/typst/research-report.typ",
    )
    # Optional pipeline payloads — when present, markdown is filled (not empty stubs)
    financials: dict[str, Any] = Field(default_factory=dict)
    dcf: dict[str, Any] = Field(default_factory=dict)
    documents: list[dict[str, Any]] = Field(
        default_factory=list,
        description="pit_rag_search 返回的 documents（已过 PIT）",
    )
    pit_filtered_count: int = Field(default=0, ge=0)


def _write_markdown(path: Path, args: RenderReportArgs) -> None:
    name = args.target_name or args.target_identifier
    fin = args.financials or {}
    dcf = args.dcf or {}
    docs = args.documents or []
    fv = args.fair_value_per_share
    if fv is None:
        fv = dcf.get("fair_value_per_share")

    lines = [
        f"# Research Report — {name}",
        "",
        f"- Identifier: `{args.target_identifier}`",
        f"- As of: {args.as_of_date.isoformat()}",
        f"- Fair value / share: **{fv}**",
        f"- PIT docs used: {len(docs)} (filtered lookahead: {args.pit_filtered_count})",
        f"- Data note: financials/DCF from pipeline; narrative synthesized from PIT snippets",
        "",
        "## Research questions",
    ]
    for q in args.research_questions or ["N/A"]:
        lines.append(f"- {q}")

    # Overview
    lines.extend(["", "## 1. Overview"])
    lines.append(
        f"本报告对 **{name}**（`{args.target_identifier}`）在时点 "
        f"**{args.as_of_date.isoformat()}** 做基本面梳理与简化 DCF。"
        f"检索严格遵守 `published_at <= as_of_date`，已过滤 {args.pit_filtered_count} 篇未来文档。"
    )

    # Business / evidence from PIT
    lines.extend(["", "## 2. Business & evidence (PIT corpus)"])
    if docs:
        for d in docs:
            title = d.get("title") or d.get("id")
            src = d.get("source", "unknown")
            pub = d.get("published_at", "")
            snip = (d.get("snippet") or "").strip()
            lines.append(f"- **{title}**（{src}，{pub}）")
            if snip:
                lines.append(f"  - {snip}")
    else:
        lines.append("- （未传入 PIT documents；仅输出框架）")

    # Financials
    lines.extend(["", "## 3. Financials"])
    if fin:
        lines.extend(
            [
                f"| Metric | Value |",
                f"| --- | --- |",
                f"| Currency | {fin.get('currency', 'N/A')} |",
                f"| Revenue TTM | {fin.get('revenue_ttm', 'N/A')} |",
                f"| EBIT TTM | {fin.get('ebit_ttm', 'N/A')} |",
                f"| Net income TTM | {fin.get('net_income_ttm', 'N/A')} |",
                f"| FCF TTM | {fin.get('fcf_ttm', 'N/A')} |",
                f"| Shares (m) | {fin.get('shares_outstanding_m', 'N/A')} |",
            ]
        )
        src_ids = fin.get("source_doc_ids") or []
        if src_ids:
            lines.append(f"- Source doc ids: {', '.join(src_ids)}")
        if fin.get("notes"):
            lines.append(f"- Notes: {fin['notes']}")
    else:
        lines.append("- （未传入 financials）")

    # Valuation
    lines.extend(["", "## 4. Valuation (DCF)"])
    if dcf or fv is not None:
        lines.extend(
            [
                f"- Method: `{dcf.get('method', 'n/a')}`",
                f"- WACC: {dcf.get('wacc', 'n/a')}",
                f"- Growth: {dcf.get('growth_rate', 'n/a')}",
                f"- Terminal growth: {dcf.get('terminal_growth', 'n/a')}",
                f"- Projection years: {dcf.get('projection_years', 'n/a')}",
                f"- Enterprise / equity value: {dcf.get('equity_value', 'n/a')}",
                f"- **Fair value per share: {fv}**",
            ]
        )
    else:
        lines.append("- （未传入 dcf）")

    # Risks
    lines.extend(["", "## 5. Risks"])
    lines.extend(
        [
            "- 财务与 DCF 仍为 pipeline stub/简化模型，不能替代正式卖方模型。",
            "- 语料若来自 fixture，需在正式环境切换 Chroma 真库。",
            "- 未覆盖竞争格局、门店扩张质量、供应链与监管等完整风险矩阵。",
        ]
    )

    # Citations
    lines.extend(["", "## Citations"])
    if docs:
        for i, d in enumerate(docs, 1):
            lines.append(
                f"{i}. [{d.get('id')}] {d.get('title')} — {d.get('source')} "
                f"({d.get('published_at')})"
            )
    else:
        lines.append(f"(citation slots reserved: {args.citations_count})")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _typst_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("#", "\\#")
        .replace("@", "\\@")
        .replace("$", "\\$")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def _write_filled_typst(path: Path, args: RenderReportArgs) -> None:
    name = args.target_name or args.target_identifier
    fv = args.fair_value_per_share
    if fv is None:
        fv = (args.dcf or {}).get("fair_value_per_share", "N/A")
    fin = args.financials or {}
    docs = args.documents or []

    doc_lines = []
    for d in docs[:8]:
        title = _typst_escape(str(d.get("title") or d.get("id")))
        snip = _typst_escape(str(d.get("snippet") or "")[:180])
        src = _typst_escape(str(d.get("source") or ""))
        pub = _typst_escape(str(d.get("published_at") or "")[:10])
        doc_lines.append(f"- *{title}* ({src}, {pub}): {snip}")

    body = f"""
#set text(font: ("Times New Roman", "Songti SC", "PingFang SC"), size: 11pt)
#set page(margin: 2cm)

#align(center)[
  #text(size: 18pt, weight: "bold")[Research Report — {_typst_escape(str(name))}]
]

#v(8pt)
- Identifier: `{_typst_escape(args.target_identifier)}`
- As of: {args.as_of_date.isoformat()}
- Fair value / share: *{fv}*
- PIT docs: {len(docs)} (filtered lookahead: {args.pit_filtered_count})

== Research questions
"""
    for q in args.research_questions or ["N/A"]:
        body += f"- {_typst_escape(q)}\n"

    body += "\n== Financials\n"
    if fin:
        body += (
            f"- Revenue TTM: {fin.get('revenue_ttm')}\n"
            f"- EBIT TTM: {fin.get('ebit_ttm')}\n"
            f"- FCF TTM: {fin.get('fcf_ttm')}\n"
            f"- Shares (m): {fin.get('shares_outstanding_m')}\n"
        )
    else:
        body += "- (no financials)\n"

    body += "\n== Valuation (DCF)\n"
    dcf = args.dcf or {}
    body += (
        f"- Method: `{_typst_escape(str(dcf.get('method', 'n/a')))}`\n"
        f"- WACC: {dcf.get('wacc', 'n/a')}\n"
        f"- Fair value / share: *{fv}*\n"
    )

    body += "\n== PIT evidence\n"
    body += "\n".join(doc_lines) if doc_lines else "- (no documents)\n"

    body += (
        "\n== Risks\n"
        "- Financials/DCF may be stub-backed; verify before production use.\n"
        "- Corpus backend may be local Chroma seeded from fixture.\n"
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.strip() + "\n", encoding="utf-8")


def _try_typst(pdf_path: Path, args: RenderReportArgs) -> bool:
    typst = shutil.which("typst")
    if not typst:
        return False
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    # Never report a stale or template-only PDF as the filled research report.
    pdf_path.unlink(missing_ok=True)
    typ_path = pdf_path.with_suffix(".typ")
    try:
        _write_filled_typst(typ_path, args)
        subprocess.run(
            [typst, "compile", str(typ_path), str(pdf_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return pdf_path.exists()
    except (subprocess.SubprocessError, OSError):
        return False


def render_report_execute(args: RenderReportArgs, ctx: dict) -> dict:
    t0 = time.perf_counter()
    safe_id = safe_filename_component(args.target_identifier)
    out_dir = PROJECT_ROOT / "artifacts" / "research"
    md_path = out_dir / f"{safe_id}-{args.as_of_date.isoformat()}.md"
    pdf_path = out_dir / f"{safe_id}-{args.as_of_date.isoformat()}.pdf"

    _write_markdown(md_path, args)
    pdf_ok = False
    if args.use_typst:
        pdf_ok = _try_typst(pdf_path, args)

    def _rel(p: Path) -> str:
        try:
            return p.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            return p.as_posix()

    sections: list[SectionType] = []
    for s in args.sections:
        try:
            sections.append(SectionType(s))
        except ValueError:
            continue

    word_count = len(md_path.read_text(encoding="utf-8").split())
    result = ResearchResult(
        pdf_path=_rel(pdf_path) if pdf_ok else None,
        markdown_path=_rel(md_path),
        sections_generated=sections,
        citations_count=max(args.citations_count, len(args.documents)),
        render_time_ms=int((time.perf_counter() - t0) * 1000),
        word_count=word_count,
    )
    payload = result.model_dump(mode="json")
    payload["typst_used"] = pdf_ok
    payload["markdown_filled"] = bool(args.documents or args.financials or args.dcf)
    payload["pdf_filled"] = pdf_ok
    return payload


render_report_tool = ToolDef(
    id="render_report",
    description=(
        "Render a research report artifact. Writes filled markdown under artifacts/research/ "
        "and compiles a filled Typst PDF when typst is installed. "
        "Pass documents/financials/dcf from upstream tools. "
        "Returns ResearchResult JSON."
    ),
    schema=RenderReportArgs,
    execute=render_report_execute,
)

__all__ = ["render_report_tool", "RenderReportArgs", "render_report_execute"]
