from unittest.mock import patch
import pytest
from quantcode.github_host import execute, verified_token

CONTEXT = {"session_id": "session-one", "github_subject": "member", "actor_id": "member", "role": "analyst", "group": "factor"}

def test_github_rejects_session_mismatch_before_reading_credentials(monkeypatch):
    monkeypatch.setenv("QUANTCODE_IDENTITY_SESSION_FILE", "/unused")
    with patch("quantcode.github_host.read_session_file", return_value=CONTEXT), patch("quantcode.github_host.verified_token") as lookup:
        with pytest.raises(PermissionError, match="身份已变化"):
            execute("status", "another-session", {})
        lookup.assert_not_called()

def test_github_rejects_wrong_subject_including_admin():
    with patch("quantcode.github_host.subject_token", return_value="fixture"), patch("tools.admin._register._gh_get", return_value={"login": "other"}):
        with pytest.raises(PermissionError, match="不一致"):
            verified_token({**CONTEXT, "role": "admin"})

def test_github_rechecks_session_after_read(monkeypatch):
    monkeypatch.setenv("QUANTCODE_IDENTITY_SESSION_FILE", "/unused")
    with patch("quantcode.github_host.read_session_file", side_effect=[CONTEXT, {**CONTEXT, "session_id": "replaced"}]), patch("quantcode.github_host.verified_token", return_value="fixture"):
        with pytest.raises(PermissionError, match="身份已变化"):
            execute("status", "session-one", {})

def test_github_status_never_returns_token(monkeypatch):
    monkeypatch.setenv("QUANTCODE_IDENTITY_SESSION_FILE", "/unused")
    with patch("quantcode.github_host.read_session_file", return_value=CONTEXT), patch("quantcode.github_host.verified_token", return_value="secret-fixture"):
        assert execute("status", "session-one", {}) == {"status": "connected", "subject": "member"}

def test_cached_graph_is_filtered_by_fresh_access_and_background_batches_rotate(tmp_path):
    from runner.github_sync import sync_graph
    from tools.admin import _register
    ctx = {**CONTEXT, "github_token": "fixture"}
    repos = [{"name": "first", "full_name": "HKUST-QUANT-SOCIETY/first"}, {"name": "second", "full_name": "HKUST-QUANT-SOCIETY/second"}]
    with patch.object(_register, "_resolve_github_token", return_value="fixture"), patch.object(_register, "_visible_repos", return_value=(repos, "fixture")), patch.object(_register, "_gh_get", side_effect=RuntimeError("fixture offline")) as get:
        initial = sync_graph(ctx, db_path=tmp_path / "pops.db", refresh_limit=0)
        assert len(initial["repos"]) == 2 and initial["refresh_pending"] == 2
        get.assert_not_called()
        sync_graph(ctx, db_path=tmp_path / "pops.db", refresh_limit=1)
        assert "/first/branches" in get.call_args.args[0]
        sync_graph(ctx, db_path=tmp_path / "pops.db", refresh_limit=1)
        assert "/second/branches" in get.call_args.args[0]
    with patch.object(_register, "_resolve_github_token", return_value="fixture"), patch.object(_register, "_visible_repos", return_value=([], "fixture")):
        assert sync_graph(ctx, db_path=tmp_path / "pops.db", refresh_limit=0)["repos"] == []

def test_commit_details_recheck_repo_access_before_reading_patch():
    from quantcode.github_host import commit_detail
    ctx = {**CONTEXT, "github_token": "fixture"}
    payload = {"repo": "HKUST-QUANT-SOCIETY/example", "sha": "a" * 40}
    with patch("tools.admin._register._visible_repos", return_value=([], "fixture")), patch("tools.admin._register._gh_get") as get:
        with pytest.raises(PermissionError, match="无权"):
            commit_detail(ctx, payload)
        get.assert_not_called()
    with patch("tools.admin._register._visible_repos", return_value=([{"full_name": payload["repo"]}], "fixture")), patch("tools.admin._register._gh_get", return_value={
        "sha": payload["sha"], "commit": {"message": "subject\n\nfull description", "author": {"name": "Author", "date": "2026-09-08"}},
        "files": [{"filename": "example.py", "patch": "-old\n+new", "status": "modified", "additions": 1, "deletions": 1}], "token": "should-not-return",
    }):
        result = commit_detail(ctx, payload)
        assert result["author"] == "Author"
        assert result["message"].endswith("full description")
        assert result["files"][0]["patch"] == "-old\n+new"
        assert "token" not in result
    with pytest.raises(ValueError):
        commit_detail(ctx, {**payload, "sha": "../../evil"})
