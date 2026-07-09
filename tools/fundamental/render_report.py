"""render_report tool — 生成研报 artifact（优先 Typst，失败则 markdown stub）。"""
from __future__ import annotations

import shutil
import subprocess
import time
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

from schemas.fundamental import ResearchResult, SectionType
from tools.registry import PROJECT_ROOT, ToolDef


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


def _write_markdown(path: Path, args: RenderReportArgs) -> None:
    name = args.target_name or args.target_identifier
    lines = [
        f"# Research Report — {name}",
        "",
        f"- Identifier: `{args.target_identifier}`",
        f"- As of: {args.as_of_date.isoformat()}",
        f"- Fair value (stub): {args.fair_value_per_share}",
        "",
        "## Research questions",
    ]
    for q in args.research_questions or ["N/A"]:
        lines.append(f"- {q}")
    lines.extend(["", "## Sections"])
    for s in args.sections:
        lines.append(f"### {s}")
        lines.append(f"Stub content for `{s}` as of {args.as_of_date.isoformat()}.")
        lines.append("")
    lines.append(f"Citations (stub count): {args.citations_count}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _try_typst(pdf_path: Path) -> bool:
    typst = shutil.which("typst")
    template = PROJECT_ROOT / "templates" / "typst" / "research-report.typ"
    if not typst or not template.exists():
        return False
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [typst, "compile", str(template), str(pdf_path)],
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
    safe_id = args.target_identifier.replace("/", "_").replace(".", "")
    out_dir = PROJECT_ROOT / "artifacts" / "research"
    md_path = out_dir / f"{safe_id}-{args.as_of_date.isoformat()}.md"
    pdf_path = out_dir / f"{safe_id}-{args.as_of_date.isoformat()}.pdf"

    _write_markdown(md_path, args)
    pdf_ok = False
    if args.use_typst:
        pdf_ok = _try_typst(pdf_path)

    # Relativize paths when under PROJECT_ROOT
    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(PROJECT_ROOT))
        except ValueError:
            return str(p)

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
        citations_count=args.citations_count,
        render_time_ms=int((time.perf_counter() - t0) * 1000),
        word_count=word_count,
    )
    payload = result.model_dump(mode="json")
    payload["typst_used"] = pdf_ok
    return payload


render_report_tool = ToolDef(
    id="render_report",
    description=(
        "Render a research report artifact. Writes markdown under artifacts/research/; "
        "if typst is installed, also compiles templates/typst/research-report.typ to PDF. "
        "Input: target_identifier, as_of_date, optional valuation / sections / citations_count. "
        "Returns ResearchResult JSON."
    ),
    schema=RenderReportArgs,
    execute=render_report_execute,
)

__all__ = ["render_report_tool", "RenderReportArgs", "render_report_execute"]
