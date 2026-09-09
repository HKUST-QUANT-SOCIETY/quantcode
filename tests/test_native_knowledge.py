"""Isolated native Distill ingestion regressions; no gateway or model calls."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from quantcode.knowledge_host import DistillInput
from runner.dream_consumer import distill_new_runs
from runner.distill.governance import review_candidate


def _source(revision: int = 7) -> dict:
    return {"source_id": "host-one", "session_id": "ses_one", "root_session_id": "ses_one",
            "source_revision": revision, "owner": {"actor_id": "researcher-one", "group": "factor"},
            "tools": [{"call_id": "call-one", "tool": "read"}, {"call_id": "call-two", "tool": "write"}],
            "input_digest": "a" * 64}


def _runs(tools: list[str] | None = None) -> list[dict]:
    return [{"run_id": "native-test", "_records": [
        {"thread_id": "native-test", "group": "factor", "action": {"tool_name": tool, "tool_args": {}},
         "observation": {"success": True, "summary": ""}}
        for tool in (["read", "write"] if tools is None else tools)
    ]}]


def test_native_reingestion_preserves_reviewed_draft_and_publication(tmp_path):
    root = tmp_path / "candidates"
    first = distill_new_runs(_runs(), candidates_dir=root, native_source=_source())
    assert len(first) == 1 and first[0]["status"] == "draft"
    draft = Path(first[0]["skill_md_path"])
    content = draft.read_text(encoding="utf-8").replace("- [ ]", "- [x]") + "\nHuman reviewed detail.\n"
    draft.write_text(content, encoding="utf-8")
    approved = review_candidate(first[0]["name"], "promote", reviewer_id="reviewer-one",
                                reviewer_role="approver", reviewer_group="factor",
                                candidates_dir=root, publish_root=tmp_path / "published")
    published = Path(approved["published_skill_path"])
    published_before = published.read_bytes()

    again = distill_new_runs(_runs(), candidates_dir=root, native_source=_source(8))

    assert again[0]["status"] == "promoted"
    assert draft.read_text(encoding="utf-8") == content
    assert published.read_bytes() == published_before
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    assert len(index["candidates"]) == 1
    assert next(iter(index["native_sources"].values()))["source_revision"] == 7


def test_native_provenance_rejects_conflicting_revision_owner_and_history(tmp_path):
    distill_new_runs(_runs(), candidates_dir=tmp_path, native_source=_source())
    conflict = {**_source(), "input_digest": "b" * 64}
    with pytest.raises(ValueError, match="revision conflicts"):
        distill_new_runs(_runs(), candidates_dir=tmp_path, native_source=conflict)
    with pytest.raises(PermissionError, match="owner changed"):
        distill_new_runs(_runs(), candidates_dir=tmp_path, native_source={**_source(8), "owner": {"actor_id": "another"}})
    with pytest.raises(ValueError, match="moved backwards"):
        distill_new_runs(_runs(), candidates_dir=tmp_path, native_source=_source(6))
    with pytest.raises(ValueError, match="rewrote its tool history"):
        distill_new_runs(_runs(["write", "read"]), candidates_dir=tmp_path,
                         native_source={**conflict, "source_revision": 8, "tools": list(reversed(_source()["tools"]))})


def test_native_empty_tool_sequence_is_recorded_once_without_fabricating_a_candidate(tmp_path):
    source = {**_source(), "tools": []}
    assert distill_new_runs(_runs([]), candidates_dir=tmp_path, native_source=source) == []
    before = (tmp_path / "index.json").read_bytes()
    assert distill_new_runs(_runs([]), candidates_dir=tmp_path, native_source=source) == []
    assert (tmp_path / "index.json").read_bytes() == before


def test_distinct_sequences_with_same_endpoints_do_not_overwrite(tmp_path):
    first = distill_new_runs(_runs(["read", "write", "read"]), candidates_dir=tmp_path)
    original = Path(first[0]["skill_md_path"]).read_bytes()
    second = distill_new_runs(_runs(["read", "edit", "read"]), candidates_dir=tmp_path)

    assert first[0]["name"] != second[0]["name"]
    assert first[0]["skill_md_path"] != second[0]["skill_md_path"]
    assert Path(first[0]["skill_md_path"]).read_bytes() == original


def test_revoked_ingestion_does_not_register_candidates(tmp_path):
    def denied():
        raise PermissionError("identity revoked")

    with pytest.raises(PermissionError, match="identity revoked"):
        distill_new_runs(_runs(), candidates_dir=tmp_path, native_source=_source(), before_commit=denied)
    assert not (tmp_path / "index.json").exists()
    assert not list(tmp_path.glob("candidate-*.md"))


def test_review_rejects_stale_preview_for_non_publication_actions(tmp_path):
    item = distill_new_runs(_runs(), candidates_dir=tmp_path)[0]
    draft = Path(item["skill_md_path"])
    preview = hashlib.sha256(draft.read_bytes()).hexdigest()
    draft.write_text(draft.read_text(encoding="utf-8") + "\nAnother reviewer's edit.\n", encoding="utf-8")

    with pytest.raises(ValueError, match="changed since preview"):
        review_candidate(item["name"], "reject", reviewer_id="reviewer-one", reviewer_role="approver",
                         reviewer_group="factor", candidates_dir=tmp_path, expected_digest=preview)
    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert index["candidates"][0]["status"] == "draft"


@pytest.mark.parametrize("extra", [{"group": "model"}, {"task": "new task"}, {"api_key": "fixture"},
                                  {"candidates_dir": "/another-store"}, {"tools": [{"call_id": "one", "tool": "read", "args": {}}]}])
def test_host_contract_rejects_identity_paths_model_keys_and_tool_bodies(extra):
    payload = {key: value for key, value in _source().items() if key not in {"owner", "input_digest"}}
    with pytest.raises(ValidationError):
        DistillInput.model_validate({**payload, **extra})
