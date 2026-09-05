"""Persisted notifications, authorized against current GitHub repository access."""
from pydantic import BaseModel, Field

from runner.langgraph_base import PROJECT_ROOT
from runner.pop_service import PopService
from tools.registry import ToolDef, registry


class ListPopsArgs(BaseModel):
    unread_only: bool = False
    limit: int = Field(default=100, ge=1, le=200)
    cursor: str | None = Field(default=None, max_length=1024)


class UpdatePopArgs(BaseModel):
    pop_id: str = Field(min_length=1, max_length=256)
    read: bool | None = None
    ack: bool | None = None


def _access(ctx: dict) -> tuple[str, set[str]]:
    from tools.admin._register import _resolve_github_token, _visible_repos

    actor = ctx.get("actor_id")
    if not actor or ctx.get("role") not in {"analyst", "approver", "admin"}:
        raise PermissionError("Pop requires authenticated Session Context")
    token = _resolve_github_token(ctx)
    if not token:
        raise PermissionError("GitHub identity token is not connected")
    repos, _ = _visible_repos(ctx, token)
    return actor, {str(repo.get("full_name") or "") for repo in repos if repo.get("full_name")}


def _list(args: ListPopsArgs, ctx: dict) -> dict:
    actor, repos = _access(ctx)
    service = PopService(PROJECT_ROOT / ".quantcode" / "pops.db")
    page = service.page_scoped(actor_id=actor, repositories=repos, **args.model_dump())
    return {**page, "pops": [pop.model_dump(mode="json") for pop in page["pops"]]}


def _update(args: UpdatePopArgs, ctx: dict) -> dict:
    actor, repos = _access(ctx)
    service = PopService(PROJECT_ROOT / ".quantcode" / "pops.db")
    pop = service.update_scoped(actor_id=actor, repositories=repos, **args.model_dump())
    page = service.page_scoped(actor_id=actor, repositories=repos, limit=1)
    return {"pop": pop.model_dump(mode="json"), "unread_count": page["unread_count"]}


for tool in (
    ToolDef(id="list_pops", description="List persisted repo/package notifications within current GitHub access. Read status is personal.", schema=ListPopsArgs, execute=_list),
    ToolDef(id="update_pop_status", description="Persist the current actor's notification read/ack status after rechecking repository access. Does not approve HumanGate.", schema=UpdatePopArgs, execute=_update),
):
    tool._meta = True
    registry._tools[tool.id] = tool


class GraphArgs(BaseModel):
    pass


def _graph(args: GraphArgs, ctx: dict) -> dict:
    from runner.github_sync import sync_graph
    return sync_graph(ctx)


tool = ToolDef(id="get_gitgraph", description="Read all currently authorized repositories and branches, HEADs, recent commit DAG, dependency-file changes and sync status. Maintains a local baseline and notification cache; does not write GitHub.", schema=GraphArgs, execute=_graph)
tool._meta = True
registry._tools[tool.id] = tool
