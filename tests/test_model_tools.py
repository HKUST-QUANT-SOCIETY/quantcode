"""Tests for model-group PR tools and Blackboard handoff."""
from __future__ import annotations

from pathlib import Path

from runner.blackboard import BlackboardService
from schemas import BlackboardScope, GroupName, ModelType
from tools.model import (
    extract_metadata,
    generate_model_spec,
    read_pr,
    trigger_risk_flow,
    write_blackboard,
)

VALID_SESSION = "S0123456789abcdef"
SAMPLE_PR = Path("tests/fixtures/sample_model_pr/README.md")


def test_read_pr_and_extract_metadata_from_fixture():
    pr = read_pr(SAMPLE_PR)
    metadata = extract_metadata(pr)
    spec = generate_model_spec(metadata)

    assert pr["pr_url"] is None
    assert spec.model_name == "pb_roe_ranker"
    assert spec.model_type == ModelType.BOOSTING
    assert spec.pr_url is None


def test_write_blackboard_writes_private_and_public_entries(tmp_path):
    metadata = extract_metadata(read_pr(SAMPLE_PR))
    spec = generate_model_spec(metadata)
    db_path = tmp_path / "blackboard.db"

    result = write_blackboard(spec, db_path=db_path, session_id=VALID_SESSION)

    assert result["private_entry_key"] == "model.private_specs.pb_roe_ranker"
    assert result["project_entry_key"] == "shared.model_specs.pb_roe_ranker"

    risk_board = BlackboardService(
        db_path,
        session_id=VALID_SESSION,
        requester_group=GroupName.RISK,
    )
    public_entry = risk_board.get_entry(
        BlackboardScope.PROJECT,
        None,
        "shared.model_specs.pb_roe_ranker",
    )
    private_entry = risk_board.get_entry(
        BlackboardScope.GROUP,
        GroupName.MODEL,
        "model.private_specs.pb_roe_ranker",
    )

    assert public_entry is not None
    assert public_entry.value["model_name"] == "pb_roe_ranker"
    assert private_entry is None


def test_trigger_risk_flow_writes_project_queue(tmp_path):
    metadata = extract_metadata(read_pr(SAMPLE_PR))
    spec = generate_model_spec(metadata)
    db_path = tmp_path / "blackboard.db"
    write_blackboard(spec, db_path=db_path, session_id=VALID_SESSION)

    result = trigger_risk_flow(spec, db_path=db_path, session_id=VALID_SESSION)

    risk_board = BlackboardService(
        db_path,
        session_id=VALID_SESSION,
        requester_group=GroupName.RISK,
    )
    queue = risk_board.get_entry(
        BlackboardScope.PROJECT,
        None,
        "shared.pending_risk_reviews",
    )

    assert result["review_id"] == spec.commit_sha
    assert queue is not None
    assert result["review_id"] in queue.value["reviews"]
    assert queue.value["reviews"][result["review_id"]]["to_group"] == "risk"


def test_model_pr_flow_runs_end_to_end_as_separate_tools(tmp_path):
    db_path = tmp_path / "blackboard.db"

    pr = read_pr(SAMPLE_PR)
    metadata = extract_metadata(pr)
    spec = generate_model_spec(metadata)
    service = BlackboardService(
        db_path,
        session_id=VALID_SESSION,
        requester_group=GroupName.MODEL,
    )
    write_result = write_blackboard(
        spec,
        blackboard=service,
        session_id=VALID_SESSION,
        task_id="T1",
    )
    trigger_result = trigger_risk_flow(
        spec,
        blackboard=service,
        session_id=VALID_SESSION,
        task_id="T1",
    )

    assert spec.model_name == "pb_roe_ranker"
    assert write_result["project_entry_key"] == "shared.model_specs.pb_roe_ranker"
    assert trigger_result["risk_queue_key"] == "shared.pending_risk_reviews"

    model_board = BlackboardService(
        db_path,
        session_id=VALID_SESSION,
        requester_group=GroupName.MODEL,
    )
    risk_board = BlackboardService(
        db_path,
        session_id=VALID_SESSION,
        requester_group=GroupName.RISK,
    )

    assert model_board.get_entry(
        BlackboardScope.GROUP,
        GroupName.MODEL,
        "model.private_specs.pb_roe_ranker",
    ) is not None
    assert risk_board.get_entry(
        BlackboardScope.GROUP,
        GroupName.MODEL,
        "model.private_specs.pb_roe_ranker",
    ) is None
    assert risk_board.get_entry(
        BlackboardScope.PROJECT,
        None,
        "shared.pending_risk_reviews",
    ) is not None
