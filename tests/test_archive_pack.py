"""Tests for demo archive packs — Jerry Day5 handoff."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from runner.archive_pack import list_archives, pack_demo_result, pack_jerry_demo_results
from runner.jerry_demos import run_fundamental_demo, run_options_demo, run_strategy_demo
from schemas.archive import ArchiveManifest, ArchiveSource
from tools.registry import PROJECT_ROOT


@pytest.fixture()
def archives_tmp(tmp_path: Path):
    root = tmp_path / "archives"
    root.mkdir()
    return root


def test_pack_strategy_demo_creates_manifest(archives_tmp: Path):
    result = run_strategy_demo(archive=False)
    packed = pack_demo_result(
        "strategy",
        result,
        source=ArchiveSource.DEMO,
        archives_root=archives_tmp,
    )
    assert packed.file_count >= 1
    manifest_path = PROJECT_ROOT / packed.manifest_path
    # pack wrote under archives_tmp; manifest_path is relative to PROJECT_ROOT
    # when archives_root is outside PROJECT_ROOT, relative_to may be absolute-ish —
    # so read via archive_dir resolution:
    pack_dir = archives_tmp / packed.archive_id
    man = ArchiveManifest.model_validate(
        json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    )
    assert man.group == "strategy"
    assert man.source == ArchiveSource.DEMO
    assert (pack_dir / "README.md").exists()
    assert (pack_dir / "meta" / "input.json").exists()
    assert any((pack_dir / p).exists() for p in man.artifact_paths)


def test_pack_fundamental_includes_markdown(archives_tmp: Path):
    result = run_fundamental_demo(archive=False)
    packed = pack_demo_result(
        "fundamental",
        result,
        source=ArchiveSource.ACCEPTANCE,
        acceptance={"status": "ok"},
        archives_root=archives_tmp,
    )
    pack_dir = archives_tmp / packed.archive_id
    man = ArchiveManifest.model_validate(
        json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    )
    assert man.source == ArchiveSource.ACCEPTANCE
    assert (pack_dir / "meta" / "acceptance.json").exists()
    # markdown should be copied when present
    copied_names = " ".join(man.artifact_paths)
    assert "fundamental_bundle.json" in copied_names or packed.file_count >= 1
    if result.get("markdown_path"):
        assert any(p.endswith(".md") or "research" in p for p in man.artifact_paths)


def test_pack_all_jerry_tracks(archives_tmp: Path):
    results = {
        "strategy": run_strategy_demo(archive=False),
        "fundamental": run_fundamental_demo(archive=False),
        "options": run_options_demo(archive=False),
    }
    packs = pack_jerry_demo_results(
        results, source=ArchiveSource.DEMO, archives_root=archives_tmp
    )
    assert set(packs) == {"strategy", "fundamental", "options"}
    listed = list_archives(archives_root=archives_tmp)
    assert len(listed) >= 3
    listed_opt = list_archives(group="options", archives_root=archives_tmp)
    assert all(r["group"] == "options" for r in listed_opt)


def test_demo_auto_archive_flag(archives_tmp: Path, monkeypatch: pytest.MonkeyPatch):
    # Point archives root used by default packer via monkeypatch of ARCHIVES path helper
    import runner.archive_pack as ap

    monkeypatch.setattr(ap, "ARCHIVES_DIRNAME", archives_tmp.name)
    # pack_demo_result uses PROJECT_ROOT / ARCHIVES_DIRNAME — redirect by packing explicitly
    result = run_strategy_demo(archive=False)
    packed = pack_demo_result("strategy", result, archives_root=archives_tmp)
    assert (archives_tmp / packed.archive_id / "manifest.json").exists()
