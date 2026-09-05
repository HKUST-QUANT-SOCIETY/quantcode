"""Repo metadata is bounded by roster group AND actual GitHub team membership."""
import pytest

from quantcode.github_visibility import GH_ORG, team_repositories
from quantcode.github_roster_check import match_records


def repo(name):
    return {"name": name, "full_name": f"{GH_ORG}/{name}", "owner": {"login": GH_ORG}, "permissions": {"pull": True}}


def getter(path):
    if path == "/user":
        return {"login": "fixture-member"}
    if "/teams/infra/members?" in path:
        return [{"login": "fixture-member", "inherited": True}]
    if "/teams/infra/repos?" in path:
        return [repo("infra-repo")]
    raise AssertionError(f"must not query unrelated org repos: {path}")


def test_member_sees_only_session_team_repositories():
    rows, source = team_repositories({"group": "infra", "github_subject": "fixture-member"}, getter)
    assert [row["name"] for row in rows] == ["infra-repo"]
    assert rows[0]["group"] == "infra"
    assert "github-team:" in source and "/infra;" in source


def test_token_cannot_impersonate_roster_subject():
    with pytest.raises(PermissionError, match="does not match"):
        team_repositories({"group": "infra", "github_subject": "another-user"}, getter)


def test_local_group_without_github_membership_is_not_a_grant():
    def missing(path):
        if "/members?" in path:
            return []
        return getter(path)
    with pytest.raises(PermissionError, match="not a member"):
        team_repositories({"group": "infra", "github_subject": "fixture-member"}, missing)


def test_missing_subject_does_not_fall_back_to_organization():
    with pytest.raises(PermissionError, match="not bound"):
        team_repositories({"group": "infra"}, getter)


def test_failed_team_lookup_does_not_fall_back_to_organization():
    def failed(path):
        if path == "/user":
            return {"login": "fixture-member"}
        raise OSError("API unavailable")
    with pytest.raises(OSError):
        team_repositories({"group": "infra", "github_subject": "fixture-member"}, failed)


def test_email_never_used_as_github_subject_match():
    result = match_records([{"row": 2, "email": "fixture-member@example.test", "public_key": "SHA256:missing"}],
                           {"teams": [], "fingerprints": {"fixture-member": []}})
    assert result[0]["status"] == "PUBLIC_KEY_REQUIRED_OR_INVALID"
    assert "github_subjects" not in result[0]


@pytest.mark.parametrize("tool", ["repo", "package"])
def test_both_gitgraph_channels_share_team_boundary(monkeypatch, tool):
    from tools.admin import _register as admin
    from datetime import datetime, timezone

    monkeypatch.delenv("QUANTCODE_ADMIN", raising=False)
    monkeypatch.setattr(admin, "_resolve_github_token", lambda ctx: "user-token")
    calls = []
    def api(path, token):
        calls.append(path)
        if path.endswith("/contents"):
            return [{"name": "pyproject.toml", "type": "file"}]
        if "/commits?" in path:
            return [{"sha": "a" * 40, "commit": {"message": "update", "author": {"date": datetime.now(timezone.utc).isoformat()}}}]
        if "/commits/" in path:
            return {"sha": "a" * 40, "commit": {"message": "update"}}
        return getter(path)
    monkeypatch.setattr(admin, "_gh_get", api)
    ctx = {"group": "infra", "github_subject": "fixture-member", "role": "analyst"}
    result = (admin._admin_repo_status_execute(admin.AdminRepoStatusArgs(), ctx) if tool == "repo"
              else admin._admin_package_updates_execute(admin.AdminPackageUpdatesArgs(), ctx))
    assert result["ok"] is True
    assert "github-team:" in result["visibility_source"]
    assert not any(f"/orgs/{GH_ORG}/repos?" in path for path in calls)
    rows = result["repos"] if tool == "repo" else result["updates"]
    assert len(rows) == 1
    assert rows[0]["name" if tool == "repo" else "repo"] == "infra-repo"
