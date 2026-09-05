"""v5 product audit: real SQLite and adapter failure/coverage regressions."""
import sqlite3
import json

import pytest

from runner.memory.service import MemoryService
from tools.admin import _register as admin


def test_long_term_filter_precedes_limit(tmp_path):
    service = MemoryService(tmp_path / "memory.db", root=tmp_path, requester_group="factor")
    for index in range(60):
        service.write(scope="sessions", scope_id="session", type="checkpoint",
                      key=f"runtime-{index}", body="evaluator")
    service.write(scope="groups", scope_id="factor", type="reference",
                  key="knowledge", body="evaluator canonical source and validated research guidance")
    hits = service.search(query="evaluator", limit=1, long_term_only=True, strict_errors=True)
    assert len(hits) == 1
    assert hits[0].scope == "groups"
    assert hits[0].type == "reference"


def test_broken_search_index_is_not_empty_success(tmp_path):
    service = MemoryService(tmp_path / "memory.db", root=tmp_path)
    with sqlite3.connect(service.db_path) as connection:
        connection.execute("DROP TABLE memory_fts_idx")
    with pytest.raises(sqlite3.OperationalError):
        service.search(query="evaluator", strict_errors=True)


def test_repository_listing_includes_second_page(monkeypatch):
    calls = []

    def fetch(path, token):
        calls.append(path)
        return [{"name": f"repo-{i}"} for i in range(100)] if path.endswith("&page=1") else [{"name": "last"}]

    monkeypatch.setattr(admin, "_gh_get", fetch)
    result = admin._list_org_repos("fixture-token")
    assert len(result) == 101
    assert result[-1]["name"] == "last"
    assert len(calls) == 2


def test_dependency_failure_is_partial_not_connected(monkeypatch):
    monkeypatch.setattr(admin, "_resolve_github_token", lambda ctx: "fixture-token")
    monkeypatch.setattr(admin, "_list_org_repos", lambda token: [{"name": "restricted"}])

    def unavailable(path, token):
        raise OSError("offline")

    monkeypatch.setattr(admin, "_gh_get", unavailable)
    result = admin._admin_package_updates_execute(admin.AdminPackageUpdatesArgs(), {})
    assert result["sync_status"] == "PARTIAL"
    assert result["errors"] == ["restricted: dependency files unavailable"]
    assert result["updates"] == []


def test_admin_rows_retain_actor_and_are_audited(monkeypatch, tmp_path):
    from runner import metrics

    row = {"actor_id": "researcher", "group": "factor", "thread_id": "run-1",
           "status": "error", "error": "fixture failure", "ts": 1}
    monkeypatch.setattr(metrics, "read_recent", lambda limit: [row])
    ctx = {"role": "admin", "actor_id": "auditor", "session_id": "admin-session",
           "evidence_dir": tmp_path}
    result = admin._admin_list_runs_execute(admin.AdminListRunsArgs(), ctx)
    assert result["runs"] == [row]
    errors = admin._admin_errors_execute(admin.AdminErrorsArgs(), ctx)
    assert errors["errors"][0]["actor_id"] == "researcher"
    entries = [json.loads(path.read_text()) for path in tmp_path.glob("admin-read-*.jsonl")]
    assert len(entries) == 2
    assert all(entry["payload"]["actor_id"] == "auditor" for entry in entries)
    assert all("fixture failure" not in json.dumps(entry) for entry in entries)


def test_admin_read_does_not_disclose_when_audit_fails(monkeypatch):
    from runner import evidence, metrics

    monkeypatch.setattr(metrics, "read_recent", lambda limit: [])

    def failed(*args, **kwargs):
        assert kwargs["required"] is True
        raise OSError("audit store unavailable")

    monkeypatch.setattr(evidence, "append_event", failed)
    with pytest.raises(OSError, match="audit store unavailable"):
        admin._admin_list_runs_execute(admin.AdminListRunsArgs(), {"role": "admin"})


def test_permission_evidence_preserves_checkpoint_gate_and_resumer(monkeypatch, tmp_path):
    from runner import permission_engine
    from runner.evidence import build_report
    import langgraph.types

    monkeypatch.setattr(permission_engine, "check", lambda *args: {"decision": "ask", "reason": "shared access"})
    monkeypatch.setattr(langgraph.types, "interrupt", lambda payload: {
        "decision": "proceed", "decided_by": "approver-b", "gate_id": "original-gate",
    })
    result = permission_engine.enforce("restricted", "factor", {
        "actor_id": "creator-a", "thread_id": "permission-audit", "evidence_dir": tmp_path,
    })
    assert result["decision"] == "allow"
    report = build_report("permission-audit", tmp_path)
    assert report.decision.decided_by == "approver-b"
    assert report.decision.gate_id == "original-gate"


def test_product_memory_does_not_infer_project_access_from_group(tmp_path, monkeypatch):
    from quantcode import mcp_server

    monkeypatch.setattr(mcp_server, "PROJECT_ROOT", tmp_path)
    service = MemoryService(tmp_path / ".quantcode" / "memory.db", root=tmp_path,
                            requester_group="factor")
    service.write(scope="projects", scope_id="other-project", type="reference",
                  key="restricted", body="evaluator project private reference")
    service.write(scope="groups", scope_id="factor", type="reference",
                  key="shared", body="evaluator group reference")
    args = mcp_server.SearchMemoryArgs(query="evaluator")
    ordinary = mcp_server._search_memory_execute(args, {"group": "factor", "role": "analyst"})
    assert {hit["scope"] for hit in ordinary["hits"]} == {"groups"}
    admin_result = mcp_server._search_memory_execute(args, {
        "group": "factor", "role": "admin", "actor_id": "admin-fixture",
        "evidence_dir": tmp_path / "evidence",
    })
    assert {hit["scope"] for hit in admin_result["hits"]} == {"groups", "projects"}
