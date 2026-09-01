"""P-08 Admin 角色与跨组语义查询单测（AG-D）。

覆盖：
- ``runner/admin_scope.is_admin`` 三判定源（env / 绑定 role 名单 / 缺省拒绝）+ fail-closed；
- ``runner.metrics.aggregate_runs`` / ``error_digest`` 纯函数（表驱动）；
- 五个 ``admin_*`` 工具：非 Admin 领域拒绝（{"ok": False, "error": "admin only"}，
  不抛）+ Admin 正常（env 与名单两条放行路径）；repo/package 工具无 token 诚实空态；
- ``ssh_status`` 元工具注册可见（AG-F 后端实现，AG-D 注册）；
- _meta 通道：六组 MCP tools/list 可见、不进任何组 allowlist。
"""
from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from quantcode import mcp_server
from quantcode import identity
from runner import admin_scope
from runner import metrics
import tools.admin._register as admin_register
from tools.registry import registry as global_registry

ADMIN_IDS = (
    "admin_list_runs",
    "admin_errors",
    "admin_blackboard_read",
    "admin_repo_status",
    "admin_package_updates",
)
ALL_ADMIN_TOOL_IDS = ADMIN_IDS + ("ssh_status",)

FP_ADMIN = "SHA256:adminfp00000000000000000000000000000000000000000000000000000001"
FP_PLAIN = "SHA256:plainfp0000000000000000000000000000000000000000000000000000002"
TASK_ID = "T0.11111111"  # TASK_ID_PATTERN：T0 = 未分配任务的诚实占位


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """隔离：清判定 env、绑定文件与 metrics.jsonl 指向 tmp、重注册 admin 工具。"""
    for var in ("QUANTCODE_ADMIN", "GITHUB_TOKEN", "QUANTCODE_GROUP"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(
        identity, "DEFAULT_BINDINGS_PATH",
        tmp_path / "opencode" / "authorized_groups.yaml",
    )
    monkeypatch.setattr(metrics, "METRICS_PATH", tmp_path / "metrics.jsonl")
    importlib.reload(admin_register)  # 幂等覆盖注册（其他测试可能清过 registry）
    yield
    for tid in ALL_ADMIN_TOOL_IDS:  # 卫生：不留全局态给别的测试文件
        global_registry._tools.pop(tid, None)


def _write_bindings(entries: list[dict]) -> None:
    path = identity.DEFAULT_BINDINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"bindings": entries}), encoding="utf-8")


# ---------------------------------------------------------------------------
# is_admin：三判定源 + fail-closed
# ---------------------------------------------------------------------------


def test_is_admin_env_source(monkeypatch):
    """env QUANTCODE_ADMIN=1 显式提权：identity 缺失也放行。"""
    monkeypatch.setenv("QUANTCODE_ADMIN", "1")
    assert admin_scope.is_admin(None, None) is True
    assert admin_scope.is_admin("", "model") is True


@pytest.mark.parametrize("value", ["0", "true", "yes", " 1x", ""])
def test_is_admin_env_must_be_exact_1(monkeypatch, value):
    """env 值非精确 "1"（含 "true"/"yes"）→ 不放行（宽松误放行防线）。"""
    monkeypatch.setenv("QUANTCODE_ADMIN", value)
    assert admin_scope.is_admin(None, None) is False


def test_is_admin_roster_source(monkeypatch):
    """名单源：绑定文件 role: admin 条目的指纹放行；无 role 条目拒绝。"""
    _write_bindings([
        {"fingerprint": FP_ADMIN, "group": "model", "role": "admin"},
        {"fingerprint": FP_PLAIN, "group": "risk"},  # 无 role → 普通组员
    ])
    assert admin_scope.is_admin(FP_ADMIN, "model") is True
    assert admin_scope.is_admin(FP_PLAIN, "risk") is False
    assert admin_scope.is_admin(FP_ADMIN.lower(), "model") is False  # 指纹精确匹配


def test_is_admin_default_deny():
    """缺省拒绝：无 env、identity 缺失/未知 → 非 Admin（fail-closed）。"""
    assert admin_scope.is_admin(None, None) is False
    assert admin_scope.is_admin("", None) is False
    assert admin_scope.is_admin("SHA256:unknown", "model") is False


def test_is_admin_fail_closed_on_broken_roster(monkeypatch, tmp_path):
    """名单文件 YAML 损坏 → 视为无名单 → 拒绝（fail-closed，不抛）。"""
    path = identity.DEFAULT_BINDINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("bindings: [unclosed", encoding="utf-8")
    assert admin_scope.admin_fingerprints() == frozenset()
    assert admin_scope.is_admin(FP_ADMIN, None) is False


def test_is_admin_fail_closed_on_roster_exception(monkeypatch):
    """名单读取函数本身抛异常 → is_admin 仍返回 False（fail-closed 兜底）。"""

    def _boom(path=None):
        raise RuntimeError("disk error")

    monkeypatch.setattr(admin_scope, "admin_fingerprints", _boom)
    assert admin_scope.is_admin(FP_ADMIN, None) is False


# ---------------------------------------------------------------------------
# metrics 纯函数：aggregate_runs / error_digest（表驱动）
# ---------------------------------------------------------------------------

_RUNS = [
    {"group": "model", "thread_id": "t1", "flow": "f", "status": "completed", "error": None, "ts": 1.0},
    {"group": "model", "thread_id": "t1", "flow": "f", "status": "error", "error": "boom", "ts": 2.0},
    {"group": "model", "thread_id": "t2", "flow": "f", "status": "error", "error": "boom", "ts": 3.0},
    {"group": "risk", "thread_id": "t3", "flow": "g", "status": "stopped", "error": None, "ts": 4.0},
]


def test_aggregate_runs_groups_threads_statuses_errors():
    agg = metrics.aggregate_runs(_RUNS)
    assert agg["total"] == 4
    model = agg["by_group"]["model"]
    assert model["runs"] == 3
    assert model["statuses"] == {"completed": 1, "error": 2}
    assert model["errors"] == ["boom"]  # 跨线程去重
    assert model["by_thread"]["t1"]["runs"] == 2
    assert model["by_thread"]["t2"]["runs"] == 1
    risk = agg["by_group"]["risk"]
    assert risk["statuses"] == {"stopped": 1}
    assert risk["errors"] == []


def test_aggregate_runs_filters():
    assert metrics.aggregate_runs(_RUNS, status_filter="error")["total"] == 2
    by_group = metrics.aggregate_runs(_RUNS, status_filter="error")["by_group"]
    assert set(by_group) == {"model"}
    assert metrics.aggregate_runs(_RUNS, group_filter="risk")["total"] == 1
    assert metrics.aggregate_runs(_RUNS, group_filter="risk", status_filter="completed")["total"] == 0


def test_aggregate_runs_empty():
    assert metrics.aggregate_runs([]) == {"total": 0, "by_group": {}}


def test_error_digest_table():
    digest = metrics.error_digest(_RUNS)
    assert digest["total_errors"] == 2
    assert digest["by_group"]["model"]["count"] == 2
    msgs = [e["error"] for e in digest["by_group"]["model"]["errors"]]
    assert msgs == ["boom", "boom"]  # 按记录保留（不跨记录去重），定位每条现场
    assert digest["by_group"]["model"]["errors"][0]["thread_id"] == "t1"


def test_error_digest_empty_and_status_only_error():
    assert metrics.error_digest([]) == {"total_errors": 0, "by_group": {}}
    digest = metrics.error_digest([{"group": "risk", "thread_id": "t", "flow": "f", "status": "error", "error": None}])
    assert digest["total_errors"] == 1
    assert digest["by_group"]["risk"]["errors"][0]["error"] == "(status=error, no message)"


# ---------------------------------------------------------------------------
# 工具门禁：非 Admin 一律领域拒绝（不抛）；Admin 两条放行路径
# ---------------------------------------------------------------------------

_MIN_ARGS = {
    "admin_list_runs": {},
    "admin_errors": {},
    "admin_blackboard_read": {"key": "foo"},
    "admin_repo_status": {},
    "admin_package_updates": {},
}


_ADMIN_GATED = sorted(set(_MIN_ARGS) - {"admin_repo_status", "admin_package_updates"})


@pytest.mark.parametrize("tool_id", _ADMIN_GATED)
def test_admin_tools_deny_non_admin(tool_id):
    """非 Admin：三个跨组数据工具返回 {"ok": False, "error": "admin only"}，不抛异常。"""
    result = global_registry.call(tool_id, dict(_MIN_ARGS[tool_id]), ctx={})
    assert result == {"ok": False, "error": "admin only"}


@pytest.mark.parametrize("tool_id", ["admin_repo_status", "admin_package_updates"])
def test_org_metadata_tools_open_to_all(tool_id):
    """2026-09-01 定版：org 只读元数据（GitGraph/双类 pop 数据源）全员可读——
    非 Admin 无 token 时返回诚实空态而非 admin only（数据字段类敏感蒸馏仍由能力卡 Mask 承担）。"""
    result = global_registry.call(tool_id, dict(_MIN_ARGS[tool_id]), ctx={})
    assert result.get("ok") is False
    assert "admin only" not in str(result.get("error", ""))


def test_admin_tools_deny_plain_group_member(monkeypatch):
    """普通组员（无 env、无名单命中）即使带组身份也被拒。"""
    _write_bindings([{"fingerprint": FP_PLAIN, "group": "risk"}])
    result = global_registry.call("admin_list_runs", {}, ctx={"identity": FP_PLAIN, "group": "risk"})
    assert result == {"ok": False, "error": "admin only"}


def test_admin_list_runs_admin_via_env(monkeypatch):
    """Admin（env 路径）：跨组聚合 model + risk 两组的 run（含 thread 维度）。"""
    monkeypatch.setenv("QUANTCODE_ADMIN", "1")
    metrics.record_run(group="model", flow="f", thread_id="t1",
                       started_at=0.0, ended_at=1.0, status="completed")
    metrics.record_run(group="risk", flow="g", thread_id="t2",
                       started_at=0.0, ended_at=2.0, status="error", error="kaput")
    result = global_registry.call("admin_list_runs", {}, ctx={})
    assert result["total"] == 2
    assert set(result["by_group"]) == {"model", "risk"}  # 跨组可见（普通 list_runs 是全量也可见，但 admin 工具语义为跨组聚合）
    assert result["by_group"]["risk"]["errors"] == ["kaput"]
    assert result["by_group"]["model"]["by_thread"]["t1"]["runs"] == 1

    filtered = global_registry.call(
        "admin_list_runs", {"status_filter": "error", "group_filter": "risk"}, ctx={}
    )
    assert filtered["total"] == 1
    assert set(filtered["by_group"]) == {"risk"}


def test_admin_list_runs_admin_via_roster():
    """Admin（名单路径）：ctx 带 role:admin 指纹 → 放行。"""
    _write_bindings([{"fingerprint": FP_ADMIN, "group": "model", "role": "admin"}])
    metrics.record_run(group="factor", flow="f", thread_id="t9",
                       started_at=0.0, ended_at=1.0, status="stopped")
    result = global_registry.call(
        "admin_list_runs", {}, ctx={"identity": FP_ADMIN, "group": "model"}
    )
    assert result["total"] == 1
    assert "factor" in result["by_group"]


def test_admin_errors_admin_empty_state_then_digest(monkeypatch):
    """Admin：无错误 → 诚实空态；有错误 → 按组汇总。"""
    monkeypatch.setenv("QUANTCODE_ADMIN", "1")
    empty = global_registry.call("admin_errors", {}, ctx={})
    assert empty == {"total_errors": 0, "by_group": {}}  # 空态（不伪造）

    metrics.record_run(group="options", flow="f", thread_id="t1",
                       started_at=0.0, ended_at=1.0, status="error", error="bad strike")
    metrics.record_run(group="options", flow="f", thread_id="t2",
                       started_at=0.0, ended_at=1.0, status="completed")
    digest = global_registry.call("admin_errors", {}, ctx={})
    assert digest["total_errors"] == 1
    assert digest["by_group"]["options"]["errors"][0]["error"] == "bad strike"


def test_admin_blackboard_read_admin(monkeypatch, tmp_path):
    """Admin：PROJECT（make_read_key 归一）+ GROUP（组私有）两类条目都跨组可读；
    无命中 → 诚实空态。只读：本工具无任何写路径。"""
    monkeypatch.setenv("QUANTCODE_ADMIN", "1")
    from runner.blackboard import BlackboardService
    from runner.blackboard_keys import PROJECT_SESSION_ID, make_read_key

    db = tmp_path / "bb.db"
    svc = BlackboardService(db_path=db, session_id=PROJECT_SESSION_ID)
    # PROJECT 条目：与 write_blackboard 同款——写侧先 make_read_key 归一
    svc.write_value(scope="project", key=make_read_key("foo"), value={"a": 1},
                    written_by_task_id=TASK_ID, written_by_group="model")
    # GROUP 条目：factor 组私有
    svc.write_value(scope="group", group="factor", key="ic_registry", value={"ic": 0.05},
                    written_by_task_id=TASK_ID, written_by_group="factor")

    ctx = {"blackboard_db_path": str(db)}
    result = global_registry.call("admin_blackboard_read", {"key": "foo"}, ctx=ctx)
    assert result["ok"] is True and result["found"] is True
    assert result["key"] == make_read_key("foo")
    scopes = {e["scope"] for e in result["entries"]}
    assert scopes == {"project"}  # 裸名 foo 命中 PROJECT 归一条目

    # GROUP 私有条目：admin 跨组可读其他组的 scope（factor 组的 ic_registry）
    group_read = global_registry.call("admin_blackboard_read", {"key": "ic_registry"}, ctx=ctx)
    assert group_read["found"] is True
    assert [e["scope"] for e in group_read["entries"]] == ["group"]
    assert group_read["entries"][0]["group"] == "factor"
    assert group_read["entries"][0]["value"] == {"ic": 0.05}

    missing = global_registry.call("admin_blackboard_read", {"key": "nope"}, ctx=ctx)
    # 裸名同样经 make_read_key 归一（回显归一后的 key），无命中 → 诚实空态
    assert missing == {"ok": True, "key": make_read_key("nope"), "found": False, "entries": []}


# ---------------------------------------------------------------------------
# GitHub 只读工具：无 token 诚实空态 + mock 正常路径（不触网）
# ---------------------------------------------------------------------------


def test_admin_repo_status_no_token_honest_empty(monkeypatch):
    """无 token → 诚实空态 + error 字段（不伪造数据）。gate 在前：需先过 Admin。"""
    monkeypatch.setenv("QUANTCODE_ADMIN", "1")
    result = global_registry.call("admin_repo_status", {}, ctx={})
    assert result["ok"] is False
    assert "GITHUB_TOKEN" in result["error"]
    assert result["repos"] == []
    assert result["org"] == admin_register.GH_ORG


def test_admin_package_updates_no_token_honest_empty(monkeypatch):
    monkeypatch.setenv("QUANTCODE_ADMIN", "1")
    result = global_registry.call("admin_package_updates", {}, ctx={})
    assert result["ok"] is False
    assert "GITHUB_TOKEN" in result["error"]
    assert result["updates"] == []


def _fake_gh_get_repo_status(path: str, token: str):
    if path.startswith("/orgs/"):
        return [
            {"name": "quantcode", "pushed_at": "2026-08-30T00:00:00Z", "default_branch": "main"},
            {"name": "bad/name", "pushed_at": "2026-08-30T00:00:00Z", "default_branch": "main"},
        ]
    if "/commits/main" in path:
        return {
            "sha": "0123456789abcdef",
            "commit": {
                "message": "feat: latest\n\nbody",
                "author": {"name": "hw", "date": "2026-08-30T10:00:00Z"},
            },
        }
    raise AssertionError(f"unexpected path: {path}")


def test_admin_repo_status_admin_with_mock(monkeypatch):
    """Admin + mock GitHub：repo 列表 + 默认分支最近提交摘要；非法 repo 名跳过。"""
    monkeypatch.setenv("QUANTCODE_ADMIN", "1")
    monkeypatch.setattr(admin_register, "_gh_get", _fake_gh_get_repo_status)
    result = global_registry.call(
        "admin_repo_status", {}, ctx={"github_token": "test-token"}  # ctx token 通道
    )
    assert result["ok"] is True
    assert result["count"] == 1  # "bad/name" 被 _safe_repo 拒绝
    repo = result["repos"][0]
    assert repo["name"] == "quantcode"
    assert repo["latest_commit"]["sha"] == "0123456789ab"  # 12 位摘要
    assert repo["latest_commit"]["message"] == "feat: latest"
    assert repo["latest_commit"]["author"] == "hw"


_NOW = datetime.now(timezone.utc)
_RECENT_ISO = (_NOW - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
_OLD_ISO = (_NOW - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fake_gh_get_updates(path: str, token: str):
    if path.startswith("/orgs/"):
        return [{"name": "quantcode"}, {"name": "oldrepo"}]
    if path.endswith("/contents"):
        if "quantcode" in path:
            return [
                {"name": "pyproject.toml", "type": "file"},
                {"name": "requirements-dev.txt", "type": "file"},
                {"name": "README.md", "type": "file"},  # 非依赖文件，忽略
            ]
        return [{"name": "requirements.txt", "type": "file"}]
    if "commits?path=pyproject.toml" in path:
        return [{"sha": "a" * 40, "commit": {"message": "bump pyproject", "author": {"date": _RECENT_ISO}}}]
    if "commits?path=requirements" in path:
        return [{"sha": "b" * 40, "commit": {"message": "bump reqs", "author": {"date": _OLD_ISO}}}]
    raise AssertionError(f"unexpected path: {path}")


@pytest.mark.parametrize(
    "since_days,expected",
    [(7, ["quantcode"]), (90, ["oldrepo", "quantcode"])],
)
def test_admin_package_updates_admin_with_mock(monkeypatch, since_days, expected):
    """Admin + mock GitHub：窗口内依赖文件有 commit 的 repo 进 updates 清单。"""
    monkeypatch.setenv("QUANTCODE_ADMIN", "1")
    monkeypatch.setattr(admin_register, "_gh_get", _fake_gh_get_updates)
    result = global_registry.call(
        "admin_package_updates", {"since_days": since_days},
        ctx={"github_token": "test-token"},  # ctx token 通道（与 read_pr 同源）
    )
    assert result["ok"] is True
    assert result["repos_checked"] == 2
    assert sorted(u["repo"] for u in result["updates"]) == expected


# ---------------------------------------------------------------------------
# ssh_status 元工具注册（AG-F 后端实现 + AG-D 注册）与 _meta 通道
# ---------------------------------------------------------------------------


def test_ssh_status_registered_and_callable(monkeypatch):
    """ssh_status 已注册、_meta=True；execute 返回 AG-F 契约的结构键。"""
    from runner import server_ssh

    tool = global_registry.get("ssh_status")  # 未注册会 KeyError
    assert getattr(tool, "_meta", False) is True
    monkeypatch.setattr(server_ssh, "_load_configs", lambda: [])  # 不依赖本机 config.json
    result = global_registry.call("ssh_status", {}, ctx={})
    assert set(result) >= {"configured", "servers", "group_bindings_ready", "group_bindings_count"}
    assert result["configured"] is False
    assert result["group_bindings_count"] == 0  # 绑定文件已指向 tmp（不存在）


def test_admin_tools_meta_visible_via_mcp_tools_list(monkeypatch):
    """_meta 通道：设置组过滤后六工具仍出现在 MCP tools/list（发现面全员一致）。"""
    monkeypatch.setenv("QUANTCODE_GROUP", "model")
    names = {t["name"] for t in mcp_server.list_tools()["tools"]}
    assert set(ALL_ADMIN_TOOL_IDS) <= names


def test_admin_tools_not_in_group_allowlist():
    """不进任何组 allowlist：内部 ReAct agent（include_meta=False）看不到 admin 工具。"""
    internal = {t.id for t in global_registry.get_tools_for_group("model")}
    assert not (internal & set(ALL_ADMIN_TOOL_IDS))
