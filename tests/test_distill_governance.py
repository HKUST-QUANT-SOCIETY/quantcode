from __future__ import annotations

import json
from pathlib import Path

import pytest

from runner.distill.governance import review_candidate
from runner.distill.governance import read_governed_skill
import runner.distill.governance as governance


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
        reviewer_group="factor", candidates_dir=tmp_path, publish_root=tmp_path / "published",
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
            reviewer_group="factor", candidates_dir=tmp_path, publish_root=tmp_path / "published",
        )


def test_candidate_review_enforces_group_and_role(tmp_path):
    _candidate(tmp_path)
    with pytest.raises(PermissionError):
        review_candidate(
            "factor-flow", "reject", reviewer_id="model-lead", reviewer_role="approver",
            reviewer_group="model", candidates_dir=tmp_path, publish_root=tmp_path / "published",
        )
    with pytest.raises(PermissionError):
        review_candidate(
            "factor-flow", "reject", reviewer_id="factor-user", reviewer_role="analyst",
            reviewer_group="factor", candidates_dir=tmp_path, publish_root=tmp_path / "published",
        )
    with pytest.raises(ValueError, match="superseded_by"):
        review_candidate(
            "factor-flow", "supersede", reviewer_id="factor-lead", reviewer_role="approver",
            reviewer_group="factor", candidates_dir=tmp_path, publish_root=tmp_path / "published",
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
            candidates_dir=tmp_path, publish_root=tmp_path / "published",
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
            reviewer_group="factor", candidates_dir=tmp_path, publish_root=tmp_path / "published",
        )


@pytest.mark.parametrize("stage", ["install", "decision_audit", "activation"])
def test_interrupted_publication_stays_inactive_and_can_resume(tmp_path, monkeypatch, stage):
    _candidate(tmp_path)
    options = dict(reviewer_id="lead", reviewer_role="approver", reviewer_group="factor",
                   candidates_dir=tmp_path, publish_root=tmp_path / "published")
    original_link = governance.os.link
    original_audit = governance._audit
    original_write = governance._atomic_write

    def link(*args, **kwargs):
        if stage == "install":
            raise OSError("simulated interruption during installation")
        return original_link(*args, **kwargs)

    def audit(path, event):
        if stage == "decision_audit" and event["action"] == "promote":
            raise OSError("simulated audit disk failure")
        return original_audit(path, event)

    def write(path, value):
        if stage == "activation" and any(item.get("status") == "promoted" for item in value.get("candidates", [])):
            raise OSError("simulated interruption before activation")
        return original_write(path, value)

    with monkeypatch.context() as fault:
        fault.setattr(governance.os, "link", link)
        fault.setattr(governance, "_audit", audit)
        fault.setattr(governance, "_atomic_write", write)
        with pytest.raises(OSError, match="simulated"):
            review_candidate("factor-flow", "promote", **options)
    saved = json.loads((tmp_path / "index.json").read_text())["candidates"][0]
    assert saved["status"] == "publishing"
    published = Path(saved["published_skill_path"])
    if published.exists():
        with pytest.raises(PermissionError, match="not active"):
            read_governed_skill(published)
    resumed = review_candidate("factor-flow", "promote", **options)
    assert resumed["status"] == "promoted"
    assert "status: accepted" in read_governed_skill(published)
    review_candidate("factor-flow", "revoke", **options)
    assert published.exists()  # Preserve the evidence; revoke via authority.
    with pytest.raises(PermissionError, match="not active"):
        read_governed_skill(published)


@pytest.mark.parametrize("change", ["source", "published", "expired", "naive_expiry"])
def test_changed_or_expired_skill_is_rejected_on_next_read(tmp_path, change):
    _candidate(tmp_path)
    item = review_candidate("factor-flow", "promote", reviewer_id="lead", reviewer_role="approver",
                            reviewer_group="factor", candidates_dir=tmp_path, publish_root=tmp_path / "published")
    published = Path(item["published_skill_path"])
    assert read_governed_skill(published)
    if change == "source":
        Path(item["skill_md_path"]).write_text("changed source")
    elif change == "published":
        published.write_text("changed published skill")
    else:
        index = json.loads((tmp_path / "index.json").read_text())
        index["candidates"][0]["expires_at"] = "2000-01-01T00:00:00+00:00" if change == "expired" else "2999-01-01T00:00:00"
        (tmp_path / "index.json").write_text(json.dumps(index))
    with pytest.raises(PermissionError):
        read_governed_skill(published)
