from __future__ import annotations

import json
from pathlib import Path

import pytest

from runner.distill.governance import review_candidate


def _candidate(root: Path, *, content: str = "---\nstatus: draft\n---\n\n# reviewed\n") -> None:
    draft = root / "candidate-factor-flow.md"
    draft.write_text(content, encoding="utf-8")
    (root / "index.json").write_text(
        json.dumps({"candidates": [{"name": "factor-flow", "group": "factor", "status": "draft", "skill_md_path": str(draft)}]}),
        encoding="utf-8",
    )


def test_candidate_promotion_requires_review_and_writes_audit(tmp_path):
    _candidate(tmp_path)
    result = review_candidate(
        "factor-flow", "promote", reviewer_id="factor-lead", reviewer_role="approver",
        reviewer_group="factor", candidates_dir=tmp_path,
    )
    assert result["status"] == "promoted"
    published = Path(result["published_skill_path"])
    assert published.is_file()
    assert "status: accepted" in published.read_text(encoding="utf-8")
    audit = (tmp_path / "review_audit.jsonl").read_text(encoding="utf-8")
    assert '"action": "promote"' in audit


def test_candidate_promotion_rejects_unfinished_draft(tmp_path):
    _candidate(tmp_path, content="---\nstatus: draft\n---\n- [ ] fill acceptance\n")
    with pytest.raises(ValueError, match="unfinished"):
        review_candidate(
            "factor-flow", "promote", reviewer_id="factor-lead", reviewer_role="approver",
            reviewer_group="factor", candidates_dir=tmp_path,
        )


def test_candidate_review_enforces_group_and_role(tmp_path):
    _candidate(tmp_path)
    with pytest.raises(PermissionError):
        review_candidate(
            "factor-flow", "reject", reviewer_id="model-lead", reviewer_role="approver",
            reviewer_group="model", candidates_dir=tmp_path,
        )
    with pytest.raises(PermissionError):
        review_candidate(
            "factor-flow", "reject", reviewer_id="factor-user", reviewer_role="analyst",
            reviewer_group="factor", candidates_dir=tmp_path,
        )
    with pytest.raises(ValueError, match="superseded_by"):
        review_candidate(
            "factor-flow", "supersede", reviewer_id="factor-lead", reviewer_role="approver",
            reviewer_group="factor", candidates_dir=tmp_path,
        )


def test_candidate_supersede_cannot_target_another_group(tmp_path):
    _candidate(tmp_path)
    draft = tmp_path / "candidate-model-flow.md"
    draft.write_text("---\nstatus: draft\n---\n", encoding="utf-8")
    (tmp_path / "index.json").write_text(
        json.dumps(
            {
                "candidates": [
                    {"name": "factor-flow", "group": "factor", "status": "draft", "skill_md_path": str(tmp_path / "candidate-factor-flow.md")},
                    {"name": "model-flow", "group": "model", "status": "promoted", "skill_md_path": str(draft)},
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(PermissionError, match="another group"):
        review_candidate(
            "factor-flow",
            "supersede",
            reviewer_id="factor-lead",
            reviewer_role="approver",
            reviewer_group="factor",
            superseded_by="model-flow",
            candidates_dir=tmp_path,
        )


def test_candidate_promotion_rejects_out_of_tree_draft(tmp_path):
    outside = tmp_path.parent / "outside-candidate.md"
    outside.write_text("---\nstatus: draft\n---\n", encoding="utf-8")
    (tmp_path / "index.json").write_text(
        json.dumps({"candidates": [{"name": "factor-flow", "group": "factor", "status": "draft", "skill_md_path": str(outside)}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="inside candidates_dir"):
        review_candidate(
            "factor-flow", "promote", reviewer_id="factor-lead", reviewer_role="approver",
            reviewer_group="factor", candidates_dir=tmp_path,
        )
