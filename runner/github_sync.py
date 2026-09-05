"""Authorized GitHub graph snapshots with atomic baselines and durable Pop events."""
from __future__ import annotations

import hashlib
import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from quantcode.github_visibility import paginated
from runner.pop_service import PopService
from runner.dependency_versions import PARSER_REVISION, is_dependency_file, parse_versions
from runner.github_tree import repository_files
from schemas.pop import Pop, PopType


def sync_graph(ctx: dict, *, db_path: Path | None = None) -> dict:
    from runner.langgraph_base import PROJECT_ROOT
    from tools.admin._register import GH_ORG, _gh_get, _resolve_github_token, _safe_repo, _visible_repos

    if not ctx.get("actor_id") or ctx.get("role") not in {"analyst", "approver", "admin"}:
        raise PermissionError("GitGraph requires authenticated Session Context")
    token = _resolve_github_token(ctx)
    if not token:
        raise PermissionError("GitHub identity token is not connected")
    repos, visibility = _visible_repos(ctx, token)
    get = lambda path: _gh_get(path, token)
    store = PopService(db_path or PROJECT_ROOT / ".quantcode" / "pops.db")
    scope = hashlib.sha256(json.dumps([
        ctx.get("actor_id"), ctx.get("group"), ctx.get("role"), ctx.get("workspace_id"),
        ctx.get("workspace_path"), ctx.get("github_subject"),
        sorted(ctx.get("resource_scopes") or []), visibility,
    ]).encode()).hexdigest()
    with store._conn() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS graph_snapshots (scope TEXT, repo TEXT, payload TEXT NOT NULL, PRIMARY KEY(scope,repo))")
    output = []
    for repo in repos:
        name = _safe_repo(repo.get("name"))
        if not name:
            raise ValueError("invalid GitHub repository name")
        full_name = f"{GH_ORG}/{name}"
        now = datetime.now(timezone.utc)
        with store._conn() as conn:
            row = conn.execute("SELECT payload FROM graph_snapshots WHERE scope=? AND repo=?", (scope, full_name)).fetchone()
        previous = json.loads(row[0]) if row else None
        # Membership is freshly verified above, even when graph data is cached.
        if (previous and 0 <= (now - datetime.fromisoformat(previous["observed_at"])).total_seconds() < 60
                and previous.get("default_branch") == repo.get("default_branch")
                and previous.get("archived") == bool(repo.get("archived"))):
            output.append(previous)
            continue
        graph = dict(repo=full_name, default_branch=repo.get("default_branch"),
                     archived=bool(repo.get("archived")), visibility_source=visibility,
                     observed_at=now.isoformat(), branches=[], heads=[], commit_nodes=[],
                     parent_edges=[], dependency_files=[], dependency_changes=[], package_changes=[], errors=[],
                     sync_status="CONNECTED", commit_window_per_branch=30, dependency_scope="recursive-v1")
        base = f"/repos/{full_name}"
        try:
            branches = paginated(get, f"{base}/branches")
            nodes = {}
            for branch in branches:
                branch_name = branch.get("name")
                head = branch.get("commit", {}).get("sha")
                if not isinstance(branch_name, str) or not isinstance(head, str):
                    raise ValueError("invalid GitHub branch response")
                graph["branches"].append({"name": branch_name, "sha": head, "protected": bool(branch.get("protected"))})
                graph["heads"].append({"branch": branch_name, "sha": head})
                commits = get(f"{base}/commits?sha={quote(head, safe='')}&per_page=30")
                if not isinstance(commits, list):
                    raise ValueError("invalid GitHub commit response")
                for commit in commits:
                    info = commit.get("commit") or {}
                    sha = commit["sha"]
                    nodes[sha] = {"sha": sha, "message": str(info.get("message") or "").split("\n")[0],
                                  "tree_sha": (info.get("tree") or {}).get("sha"),
                                  "author": (info.get("author") or {}).get("name"),
                                  "date": (info.get("author") or {}).get("date"),
                                  "parents": [parent["sha"] for parent in commit.get("parents", [])]}
            graph["commit_nodes"] = list(nodes.values())
            graph["parent_edges"] = [{"child": node["sha"], "parent": parent,
                                      "outside_window": parent not in nodes}
                                     for node in nodes.values() for parent in node["parents"]]
            default_head = next((head["sha"] for head in graph["heads"] if head["branch"] == graph["default_branch"]), None)
            graph["latest_commit"] = nodes.get(default_head)
            if graph["heads"] and not default_head:
                raise ValueError("default branch is absent from the branch snapshot; retry synchronization")
            if default_head:
                tree_sha = (nodes.get(default_head) or {}).get("tree_sha")
                if not tree_sha:
                    tree_sha = get(f"{base}/git/commits/{quote(default_head, safe='')}").get("tree", {}).get("sha")
                if not isinstance(tree_sha, str) or not tree_sha:
                    raise ValueError("default branch tree is unavailable")
                contents = repository_files(get, base, tree_sha)
                blobs = {item["path"]: item["sha"] for item in contents}
                text_cache = {}

                def read_manifest(path):
                    if path not in blobs:
                        raise ValueError("included dependency file is absent from the fixed repository tree")
                    sha = blobs[path]
                    if sha not in text_cache:
                        blob = get(f"{base}/git/blobs/{quote(sha, safe='')}")
                        if blob.get("encoding") != "base64" or int(blob.get("size", 0)) > 5_000_000:
                            raise ValueError("dependency blob is unsupported or exceeds 5 MB")
                        text_cache[sha] = base64.b64decode("".join(blob["content"].split()), validate=True).decode("utf-8")
                    return text_cache[sha]

                graph["dependency_files"] = [{"path": item["path"], "sha": item["sha"]} for item in contents
                    if is_dependency_file(Path(item["path"]).name)]
                prior_files = {item["path"]: item for item in (previous or {}).get("dependency_files", [])}
                for dependency in graph["dependency_files"]:
                    prior = prior_files.get(dependency["path"])
                    dependency["parser_revision"] = PARSER_REVISION
                    if prior and prior["sha"] == dependency["sha"] and prior.get("parser_revision") == PARSER_REVISION and "versions" in prior and not Path(dependency["path"]).name.startswith("requirements"):
                        dependency.update(versions=prior["versions"], version_status=prior.get("version_status", "UNSUPPORTED"))
                        continue
                    content = read_manifest(dependency["path"])
                    versions = parse_versions(dependency["path"], content, read_file=read_manifest)
                    dependency.update(versions=versions, version_status="PARSED" if versions is not None else "UNSUPPORTED")
        except Exception as exc:
            graph["sync_status"] = "PARTIAL"
            graph["errors"].append(str(exc))
            # An incomplete refresh cannot become the next comparison baseline.
            output.append(graph)
            continue
        with store._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT payload FROM graph_snapshots WHERE scope=? AND repo=?", (scope, full_name)).fetchone()
            previous = json.loads(row[0]) if row else None
            if previous and datetime.fromisoformat(previous["observed_at"]) > now:
                # A newer desktop/worker refresh completed while this request
                # was in flight. Never reverse its baseline or emit false Pops.
                output.append(previous)
                continue
            if previous:
                for field, kind, key in (("heads", PopType.BRANCH, "branch"), ("dependency_files", PopType.PACKAGE, "path")):
                    if field == "dependency_files" and previous.get("dependency_scope") != graph["dependency_scope"]:
                        continue
                    old = {item[key]: item["sha"] for item in previous.get(field, [])}
                    new = {item[key]: item["sha"] for item in graph[field]}
                    for name in sorted(old.keys() | new.keys()):
                        if old.get(name) == new.get(name):
                            continue
                        event_id = hashlib.sha256(json.dumps([full_name, field, name, old.get(name), new.get(name)]).encode()).hexdigest()
                        pop = Pop(pop_id=event_id, type=kind, repo_or_package=name, repository=full_name,
                                  change_summary=f"{full_name}: {name}", old_value=old.get(name), new_value=new.get(name),
                                  observed_at=now, source="github", visibility_context=visibility, dedupe_key=event_id,
                                  link=f"https://github.com/{full_name}")
                        conn.execute("INSERT OR IGNORE INTO pops(dedupe_key,pop_id,payload,observed_at) VALUES(?,?,?,?)",
                                     (pop.dedupe_key, pop.pop_id, pop.model_dump_json(), now.isoformat()))
                        if field == "dependency_files":
                            graph["dependency_changes"].append({"file": name, "old_sha": old.get(name), "new_sha": new.get(name)})
                old_heads = {head["branch"]: head["sha"] for head in previous.get("heads", [])}
                old_files = {item["path"]: item for item in previous.get("dependency_files", [])}
                new_files = {item["path"]: item for item in graph["dependency_files"]}
                comparable_files = sorted(old_files.keys() | new_files.keys()) if previous.get("dependency_scope") == graph["dependency_scope"] else []
                for filename in comparable_files:
                    before = old_files.get(filename, {"versions": {}}).get("versions")
                    after = new_files.get(filename, {"versions": {}}).get("versions")
                    if filename in old_files and old_files[filename].get("parser_revision") != PARSER_REVISION:
                        continue
                    # Older snapshots without parsed versions establish a new
                    # baseline; do not invent additions for every dependency.
                    if before is None or after is None:
                        continue
                    for package in sorted(before.keys() | after.keys()):
                        if before.get(package) == after.get(package):
                            continue
                        change = {"file": filename, "package": package, "old_value": before.get(package), "new_value": after.get(package)}
                        graph["package_changes"].append(change)
                        event_id = hashlib.sha256(json.dumps([full_name, "package_version", change], sort_keys=True).encode()).hexdigest()
                        pop = Pop(pop_id=event_id, type=PopType.PACKAGE, repo_or_package=package, repository=full_name,
                                  change_summary=f"{full_name}: {filename} · {package}", old_value=before.get(package), new_value=after.get(package),
                                  observed_at=now, source="github", visibility_context=visibility, dedupe_key=event_id,
                                  link=f"https://github.com/{full_name}")
                        conn.execute("INSERT OR IGNORE INTO pops(dedupe_key,pop_id,payload,observed_at) VALUES(?,?,?,?)",
                                     (pop.dedupe_key, pop.pop_id, pop.model_dump_json(), now.isoformat()))
                for head in graph["heads"]:
                    head["changed"] = old_heads.get(head["branch"]) != head["sha"]
            conn.execute("INSERT INTO graph_snapshots(scope,repo,payload) VALUES(?,?,?) "
                         "ON CONFLICT(scope,repo) DO UPDATE SET payload=excluded.payload",
                         (scope, full_name, json.dumps(graph)))
        output.append(graph)
    result = {"repos": output, "visibility_source": visibility,
              "sync_status": "PARTIAL" if any(repo["sync_status"] == "PARTIAL" for repo in output) else "CONNECTED"}
    if ctx.get("role") == "admin":
        from runner.admin_scope import audited_read_result
        return audited_read_result("get_gitgraph", ctx, result)
    return result
