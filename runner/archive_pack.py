"""Archive pack helpers — freeze demo/acceptance artifacts for handoff.

Layout::

    archives/<archive_id>/
      manifest.json
      README.md
      artifacts/   # copied files (preserve relative names under artifacts/)
      meta/
        input.json
        acceptance.json   # optional
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from schemas.archive import ArchiveManifest, ArchivePackResult, ArchiveSource
from tools.registry import PROJECT_ROOT

ARCHIVES_DIRNAME = "archives"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _slug(text: str, *, max_len: int = 48) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", text.strip()).strip("-._")
    return (s or "pack")[:max_len]


def make_archive_id(group: str, *, label: str | None = None, when: datetime | None = None) -> str:
    ts = (when or _utc_now()).strftime("%Y%m%dT%H%M%SZ")
    parts = [ts, _slug(group)]
    if label:
        parts.append(_slug(label))
    return "-".join(parts)


def _rel_to_root(path: Path | str) -> str:
    p = Path(path)
    if not p.is_absolute():
        return str(p).replace("\\", "/")
    try:
        return str(p.resolve().relative_to(PROJECT_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def _collect_paths_from_demo_result(track: str, result: dict[str, Any]) -> list[str]:
    """Gather repo-relative artifact paths from a jerry demo result dict."""
    keys = [
        "artifact_path",
        "markdown_path",
        "pdf_path",
        "surface_artifact",
        "greeks_artifact",
    ]
    out: list[str] = []
    seen: set[str] = set()
    for key in keys:
        raw = result.get(key)
        if not raw or not isinstance(raw, str):
            continue
        rel = _rel_to_root(raw)
        if rel not in seen:
            seen.add(rel)
            out.append(rel)

    # fundamental: also pack companion .typ next to pdf when present
    pdf = result.get("pdf_path")
    if isinstance(pdf, str) and pdf:
        typ = str(Path(pdf).with_suffix(".typ"))
        typ_rel = _rel_to_root(typ)
        if typ_rel not in seen and (PROJECT_ROOT / typ_rel).exists():
            seen.add(typ_rel)
            out.append(typ_rel)

    # options: surface path may also live inside options_risk.json; already covered
    _ = track
    return out


def _schemas_from_demo_result(result: dict[str, Any]) -> list[str]:
    raw = result.get("schema")
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    # "A + B + C" style
    parts = [p.strip() for p in str(raw).replace("+", " ").split() if p.strip()]
    return parts or [str(raw)]


def pack_files(
    *,
    group: str,
    source_paths: list[str],
    source: ArchiveSource = ArchiveSource.DEMO,
    task: str | None = None,
    thread_id: str | None = None,
    schemas: list[str] | None = None,
    acceptance: dict[str, Any] | None = None,
    input_meta: dict[str, Any] | None = None,
    notes: str | None = None,
    label: str | None = None,
    archive_id: str | None = None,
    archives_root: Path | None = None,
) -> ArchivePackResult:
    """Copy ``source_paths`` (repo-relative) into a new archive pack."""
    when = _utc_now()
    aid = archive_id or make_archive_id(group, label=label, when=when)
    root = archives_root or (PROJECT_ROOT / ARCHIVES_DIRNAME)
    pack_dir = root / aid
    art_dir = pack_dir / "artifacts"
    meta_dir = pack_dir / "meta"
    art_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    missing: list[str] = []

    for rel in source_paths:
        rel_n = _rel_to_root(rel)
        src = PROJECT_ROOT / rel_n
        if not src.exists() or not src.is_file():
            missing.append(rel_n)
            continue
        # Keep path under archives/.../artifacts/... mirroring repo when under artifacts/
        if rel_n.startswith("artifacts/"):
            dest_rel = rel_n[len("artifacts/") :]
        else:
            dest_rel = Path(rel_n).name
        dest = art_dir / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(f"artifacts/{dest_rel}".replace("\\", "/"))

    manifest = ArchiveManifest(
        archive_id=aid,
        group=group,
        created_at=when,
        thread_id=thread_id,
        task=task,
        artifact_paths=copied,
        schemas=schemas or [],
        acceptance=acceptance,
        source=source,
        notes=notes,
        missing_sources=missing,
    )

    manifest_path = pack_dir / "manifest.json"
    manifest_path.write_text(
        manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

    meta_payload = input_meta if input_meta is not None else {"group": group, "task": task}
    (meta_dir / "input.json").write_text(
        json.dumps(meta_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if acceptance is not None:
        (meta_dir / "acceptance.json").write_text(
            json.dumps(acceptance, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    readme = [
        f"# Archive `{aid}`",
        "",
        f"- Group: `{group}`",
        f"- Source: `{manifest.source.value}`",
        f"- Created (UTC): `{when.isoformat()}`",
        f"- Schemas: {', '.join(manifest.schemas) or '(none)'}",
        f"- Files packed: {len(copied)}",
        "",
        "## Artifacts",
    ]
    for p in copied:
        readme.append(f"- `{p}`")
    if missing:
        readme.extend(["", "## Missing sources", ""])
        for m in missing:
            readme.append(f"- `{m}`")
    if notes:
        readme.extend(["", "## Notes", "", notes])
    (pack_dir / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")

    return ArchivePackResult(
        archive_id=aid,
        archive_dir=_rel_to_root(pack_dir),
        manifest_path=_rel_to_root(manifest_path),
        manifest=manifest,
        file_count=len(copied),
    )


def pack_demo_result(
    track: str,
    result: dict[str, Any],
    *,
    source: ArchiveSource = ArchiveSource.DEMO,
    acceptance: dict[str, Any] | None = None,
    notes: str | None = None,
    archives_root: Path | None = None,
) -> ArchivePackResult:
    """Pack one Jerry demo track result into ``archives/``."""
    paths = _collect_paths_from_demo_result(track, result)
    label = None
    if track == "fundamental":
        # e.g. from artifact path .../2097_HK-2025-01-01/...
        ap = result.get("artifact_path") or ""
        parts = Path(str(ap)).parts
        label = parts[-2] if len(parts) >= 2 else None
    elif track == "strategy":
        label = "strategy_report"
    elif track == "options":
        label = result.get("track") and "options_risk"

    return pack_files(
        group=track,
        source_paths=paths,
        source=source,
        task=f"jerry demo: {track}",
        schemas=_schemas_from_demo_result(result),
        acceptance=acceptance,
        input_meta={"track": track, "demo_result": _demo_result_summary(result)},
        notes=notes or "Packed from runner.jerry_demos",
        label=label,
        archives_root=archives_root,
    )


def _demo_result_summary(result: dict[str, Any]) -> dict[str, Any]:
    """Drop bulky nested blobs; keep paths and key scalars."""
    keep = {
        k: v
        for k, v in result.items()
        if k
        in (
            "track",
            "schema",
            "artifact_path",
            "verdict",
            "deploy_status",
            "pit_filtered_count",
            "pit_doc_count",
            "pit_backend",
            "human_gate",
            "markdown_path",
            "pdf_path",
            "typst_used",
            "markdown_filled",
            "pdf_filled",
            "surface_artifact",
            "greeks_artifact",
            "portfolio_delta",
            "backtest_sharpe",
            "archive_id",
            "archive_dir",
        )
    }
    return keep


def pack_jerry_demo_results(
    results: dict[str, Any],
    *,
    source: ArchiveSource = ArchiveSource.DEMO,
    acceptance: dict[str, Any] | None = None,
    archives_root: Path | None = None,
) -> dict[str, ArchivePackResult]:
    """Pack strategy/fundamental/options demo results.

    ``results`` may be either a single-track dict (has ``track``) or
    ``{"strategy": {...}, "fundamental": {...}, "options": {...}}``.
    """
    if "track" in results and results.get("track") in (
        "strategy",
        "fundamental",
        "options",
    ):
        track = str(results["track"])
        return {
            track: pack_demo_result(
                track,
                results,
                source=source,
                acceptance=acceptance,
                archives_root=archives_root,
            )
        }

    out: dict[str, ArchivePackResult] = {}
    for track in ("strategy", "fundamental", "options"):
        if track not in results or not isinstance(results[track], dict):
            continue
        out[track] = pack_demo_result(
            track,
            results[track],
            source=source,
            acceptance=acceptance,
            archives_root=archives_root,
        )
    return out


def list_archives(*, group: str | None = None, archives_root: Path | None = None) -> list[dict[str, Any]]:
    root = archives_root or (PROJECT_ROOT / ARCHIVES_DIRNAME)
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for d in sorted(root.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        mf = d / "manifest.json"
        if not mf.exists():
            continue
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
            man = ArchiveManifest.model_validate(data)
        except Exception:
            continue
        if group and man.group != group:
            continue
        rows.append(
            {
                "archive_id": man.archive_id,
                "group": man.group,
                "created_at": man.created_at.isoformat(),
                "source": man.source.value,
                "file_count": len(man.artifact_paths),
                "archive_dir": _rel_to_root(d),
            }
        )
    return rows


__all__ = [
    "ARCHIVES_DIRNAME",
    "make_archive_id",
    "pack_files",
    "pack_demo_result",
    "pack_jerry_demo_results",
    "list_archives",
]
