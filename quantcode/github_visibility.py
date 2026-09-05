"""Subject- and team-scoped GitGraph reads. Local group names never grant access."""
from __future__ import annotations

import re
from typing import Any, Callable

from runner.config_loader import load_yaml

GH_ORG = "HKUST-QUANT-SOCIETY"


def paginated(get: Callable[[str], Any], path: str) -> list[dict]:
    rows = []
    for page in range(1, 101):
        separator = "&" if "?" in path else "?"
        batch = get(f"{path}{separator}per_page=100&page={page}")
        if not isinstance(batch, list) or any(not isinstance(item, dict) for item in batch):
            raise ValueError("invalid GitHub list response")
        rows.extend(batch)
        if len(batch) < 100:
            return rows
    raise ValueError("GitHub pagination limit exceeded")


def team_repositories(ctx: dict, get: Callable[[str], Any]) -> tuple[list[dict], str]:
    """Validate the user's token and team membership before reading repo metadata."""
    subject = str(ctx.get("github_subject") or "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", subject):
        raise PermissionError("GitHub subject is not bound to this session")
    user = get("/user")
    if not isinstance(user, dict) or str(user.get("login") or "").lower() != subject.lower():
        raise PermissionError("GitHub token subject does not match authenticated session")
    config = load_yaml("github_teams", strict=True)
    if config.get("organization") != GH_ORG:
        raise ValueError("unexpected GitHub organization mapping")
    teams = config.get("groups", {}).get(ctx.get("group"), [])
    if not isinstance(teams, list) or not teams:
        raise PermissionError("No GitHub team mapping for this session group")
    repos = {}
    admitted = []
    for team in teams:
        if not isinstance(team, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", team):
            raise ValueError("invalid GitHub team slug")
        # GitHub's member list includes inherited members from child teams.
        members = paginated(get, f"/orgs/{GH_ORG}/teams/{team}/members")
        if not any(str(member.get("login") or "").lower() == subject.lower() for member in members):
            continue
        admitted.append(team)
        for repo in paginated(get, f"/orgs/{GH_ORG}/teams/{team}/repos"):
            if str(repo.get("owner", {}).get("login") or "").lower() != GH_ORG.lower():
                raise ValueError("unexpected repository owner")
            if repo.get("permissions", {}).get("pull") is not True:
                continue
            repos[repo["full_name"]] = {**repo, "group": ctx["group"]}
    if not admitted:
        raise PermissionError("Authenticated GitHub subject is not a member of this group's teams")
    return list(repos.values()), f"github-team:{GH_ORG}/{'+'.join(admitted)};subject:{subject}"
