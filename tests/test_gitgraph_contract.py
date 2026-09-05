from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
from types import SimpleNamespace

from runner.github_worker import read_status, sync_once
from schemas.gitgraph import GitGraph, GitGraphSyncResult
from tools.pop._register import GraphArgs, _graph


def test_gitgraph_contract_matches_sync_payload():
    graph = GitGraph(
        repo="HKUST-QUANT-SOCIETY/quantcode",
        visibility_source="github-team:fixture",
        default_branch="main",
        dependency_files=[
            {
                "path": "pyproject.toml",
                "sha": "a" * 40,
                "parser_revision": "fixture",
                "versions": {"pydantic": ">=2.6"},
                "version_status": "PARSED",
            }
        ],
        package_changes=[
            {"file": "pyproject.toml", "package": "pydantic", "old_value": "2", "new_value": "3"}
        ],
        errors=[],
        commit_window_per_branch=30,
        dependency_scope="recursive-v1",
        observed_at=datetime.now(timezone.utc),
        sync_status="CONNECTED",
    )
    result = GitGraphSyncResult(
        repos=[graph],
        visibility_source=graph.visibility_source,
        sync_status="CONNECTED",
    )
    assert result.repos[0].dependency_files[0]["path"] == "pyproject.toml"


def test_gitgraph_permission_denial_is_structured(monkeypatch):
    def denied(ctx):
        raise PermissionError("GitHub identity token is not connected")

    monkeypatch.setattr("runner.github_sync.sync_graph", denied)
    result = _graph(GraphArgs(), {"actor_id": "fixture", "role": "analyst"})
    assert result["sync_status"] == "PERMISSION_DENIED"
    assert result["repos"] == []
    assert result["errors"] == ["GitHub identity token is not connected"]


def test_worker_persists_permission_denied_separately_from_transport_error(tmp_path):
    database = tmp_path / "gateway.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE identity_sessions (token_hash TEXT)")
        connection.execute("INSERT INTO identity_sessions VALUES ('fixture-digest')")

    context = {
        "actor_id": "fixture",
        "role": "analyst",
        "group": "factor",
        "github_subject": "fixture-user",
    }
    gateway = SimpleNamespace(
        database=database,
        session_digest=lambda digest: SimpleNamespace(
            model_dump=lambda mode: dict(context)
        ),
    )

    def denied(ctx):
        raise PermissionError("fixture denial")

    sync_once(gateway, sync=denied)
    assert read_status(database, context)["last_attempt_status"] == "PERMISSION_DENIED"
