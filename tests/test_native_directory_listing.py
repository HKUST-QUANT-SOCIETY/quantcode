"""Descriptor-relative listing regression; no gateway or real credentials."""
import os
from pathlib import Path

import pytest

from quantcode import file_mutation

pytestmark = pytest.mark.skipif(
    os.name != "posix" or os.scandir not in os.supports_fd,
    reason="directory fd enumeration requires the POSIX host boundary",
)


def request(root: Path, relative: str = "", denied: list[str] | None = None) -> dict:
    root = root.resolve()
    info = root.stat()
    directory = (root / relative).stat()
    return {"version": 1, "action": "list", "root": str(root), "relative": relative,
            "root_device": str(info.st_dev), "root_inode": str(info.st_ino), "denied": denied or [],
            "expected_directory": file_mutation._directory_snapshot(directory)}


def test_lists_workspace_root_and_nested_directory_by_fd(tmp_path):
    nested = tmp_path / "research"
    nested.mkdir()
    (nested / "分析.txt").write_text("fixture", encoding="utf-8")
    (tmp_path / "README.md").write_text("fixture")
    root = file_mutation._apply(request(tmp_path))
    assert {(entry["name"], entry["type"]) for entry in root["entries"]} == {
        ("research", "directory"), ("README.md", "file"),
    }
    child = file_mutation._apply(request(tmp_path, "research"))
    assert [(entry["name"], entry["type"]) for entry in child["entries"]] == [("分析.txt", "file")]
    assert child["directory"] == file_mutation._directory_snapshot(nested.stat())


def test_excludes_private_subtrees_symlinks_hardlinks_and_special_files(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    control = root / ".quantcode"
    control.mkdir()
    (control / "identity.json").write_text("fixture-only")
    (root / "visible.txt").write_text("fixture")
    (root / "directory").mkdir()
    (root / "alias").symlink_to(root / "directory", target_is_directory=True)
    source = tmp_path / "other-member.txt"
    source.write_text("must not appear")
    os.link(source, root / "hardlink.txt")
    os.mkfifo(root / "pipe")
    result = file_mutation._apply(request(root, denied=[".quantcode"]))
    assert {entry["name"] for entry in result["entries"]} == {"visible.txt", "directory"}


def test_rejects_a_symlink_in_directory_traversal(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "alias").symlink_to(tmp_path / "real", target_is_directory=True)
    with pytest.raises(OSError):
        file_mutation._apply(request(tmp_path, "alias"))


def test_rejects_replaced_directory_even_when_path_is_unchanged(tmp_path):
    (tmp_path / "research").mkdir()
    original = request(tmp_path, "research")
    (tmp_path / "research").rename(tmp_path / "retired")
    (tmp_path / "research").mkdir()
    with pytest.raises(file_mutation.MutationDenied, match="stale"):
        file_mutation._apply(original)


def test_rejects_a_changed_directory_snapshot(tmp_path):
    original = request(tmp_path)
    (tmp_path / "new-entry.txt").write_text("changed")
    with pytest.raises(file_mutation.MutationDenied, match="stale"):
        file_mutation._apply(original)


def test_rejects_oversized_directory_instead_of_returning_a_partial_success(tmp_path, monkeypatch):
    for name in ["first", "second", "third"]:
        (tmp_path / name).touch()
    monkeypatch.setattr(file_mutation, "MAX_DIRECTORY_ENTRIES", 2)
    with pytest.raises(file_mutation.MutationDenied, match="directory_too_large"):
        file_mutation._apply(request(tmp_path))


def test_directory_listing_cannot_accept_mutation_fields_or_private_targets(tmp_path):
    (tmp_path / "control").mkdir()
    with pytest.raises(file_mutation.MutationDenied, match="invalid_request"):
        file_mutation._apply({**request(tmp_path), "content": "eA=="})
    with pytest.raises(file_mutation.MutationDenied, match="private_path"):
        file_mutation._apply(request(tmp_path, "control", ["control"]))
