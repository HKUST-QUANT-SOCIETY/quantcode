"""tests/test_deploy_blackbox.py — P-09 /deploy 黑盒部署（AG-H）。

覆盖（对应 specs/FUNCTIONAL_SPEC.md P-09 验收草案 + AG-H 卡片交付④）：
1. 门禁：未经批准 → 中止且无 artifact 产出（复用 AG-F ssh.prod.write: ask 闸，
   图外未批准 → RuntimeError 被收敛为 {"ok": False} 黑盒话术）；
2. 批准（ctx.human_approved=True 注入，HumanGate approve 流程同款）→
   artifact 落盘 + deploy_record_hash 为 sha256 形态 + evidence ARTIFACT 环可重放校验；
3. 黑盒断言：DeployResult 全部序列化字段 + 错误消息 grep 不到 AlphaFlow 内部
   关键词（``blackbox_forbidden_terms`` 约定清单），字段面刻意最小；
4. registry 通道：工具可见、args 严格 {"source": string}（缺 source / 多余字段
   报错可见）、permission=None（门禁走 SSH 分级，不新增触发点类型）。

隔离纪律（与 test_ssh_gate 同款）：permissions.yaml env 覆盖 + reset_cache，
不依赖仓库配置漂移；artifacts/evidence 落 tmp_path，零仓库污染。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from runner.permission_engine import reset_cache
from runner.server_ssh import classify_ssh_action
from schemas.evidence_chain import AuditEventKind
from tools.deploy.adapter import DeployResult
from tools.deploy.staging_adapter import StagingDeployAdapter
from tools.registry import registry

# ---------------------------------------------------------------------------
# 黑盒约定清单（P-09）：AlphaFlow 底层结构关键词，禁止出现在
# DeployResult 任何序列化字段与错误消息中。
# 模块边界来源：docs/audit/ASSET_INVENTORY.md §5（alpha_core/alpha_data/
# alpha_mining/alpha_bus/alpha_materializer/alpha_eval/alpha_sink/alpha_monitor）
# + 内部结构词汇（operator/dsl/pipeline_internal）+ 库名本身
# （字段面刻意最小，连部署库点名都不进 DeployResult）。
# ---------------------------------------------------------------------------
blackbox_forbidden_terms = (
    "alpha_core",
    "alpha_data",
    "alpha_mining",
    "alpha_bus",
    "alpha_materializer",
    "alpha_eval",
    "alpha_sink",
    "alpha_monitor",
    "operator",
    "dsl",
    "pipeline_internal",
    "alphaflow",
    "alpha_flow",
)


# ---------------------------------------------------------------------------
# fixtures：权限隔离 + 工具注册 + 上下文工厂
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def perm_file(monkeypatch, tmp_path):
    """独立 permissions.yaml（env 覆盖 + 清缓存）——ssh.prod.write: ask 与线上同款。"""
    path = tmp_path / "permissions.yaml"
    path.write_text("permissions:\n  ssh.prod.write: ask\n", encoding="utf-8")
    monkeypatch.setenv("QUANTCODE_PERMISSIONS_FILE", str(path))
    reset_cache()
    yield path
    reset_cache()


@pytest.fixture(autouse=True)
def _registered():
    """deploy 工具注册（幂等；test_registry 的清空 fixture 不影响本模块）。"""
    from tools.deploy import _register

    _register.register_all()
    yield


@pytest.fixture
def deploy_ctx(tmp_path):
    """ctx 工厂：role 来自服务端会话，approved 参数仅保留测试兼容名。"""
    def _make(approved: bool = False, thread_id: str = "t-deploy") -> dict:
        return {
            "thread_id": thread_id,
            "human_approved": approved,
            "role": "admin" if approved else "analyst",
            "artifacts_dir": str(tmp_path / "artifacts"),
            "evidence_dir": str(tmp_path / "evidence"),
        }

    return _make


@pytest.fixture
def source_file(tmp_path) -> Path:
    """一份"已调试因子代码"（文件名/内容不含黑盒清单词）。"""
    p = tmp_path / "my_factor.py"
    p.write_text("def alpha_signal(df):\n    return df.close.pct_change()\n", encoding="utf-8")
    return p


def _no_artifacts(ctx: dict) -> bool:
    """artifact 目录不存在或为空 = 无 artifact 产出。"""
    d = Path(ctx["artifacts_dir"])
    return (not d.exists()) or not any(d.iterdir())


# ---------------------------------------------------------------------------
# 0. 前置：source 视为 prod 写（classify 语义钉死）
# ---------------------------------------------------------------------------


def test_deploy_action_classifies_as_prod_write():
    """/deploy 语义 = 写生产：action 非读集合 + 内建 prod 标签 → prod_write，
    与 ssh 服务器配置解耦（不需要 QUANTCODE_SSH_MAINLINE）。"""
    assert classify_ssh_action("deploy_alphaflow", "prod") == "prod_write"


# ---------------------------------------------------------------------------
# 1. 未经批准 → 中止且无 artifact 产出
# ---------------------------------------------------------------------------


def test_deploy_requires_admin_management_plane(deploy_ctx, source_file):
    ctx = deploy_ctx(approved=False)
    result = registry.call("deploy_alphaflow", {"source": str(source_file)}, ctx=ctx)

    # v5：部署不属于普通 HumanGate，而是 Admin 管理面能力
    assert result["ok"] is False
    assert "admin_only" in result["error"]
    # 无 artifact 产出
    assert _no_artifacts(ctx)
    # 中止路径不留 ARTIFACT 环（evidence 无该 run 的链文件）
    assert not (Path(ctx["evidence_dir"]) / f"{ctx['thread_id']}.jsonl").exists()

def test_deploy_reject_decision_aborts(deploy_ctx, source_file, monkeypatch):
    """普通研究会话即使声明 human_approved 也不能部署。"""
    ctx = deploy_ctx(approved=False)
    ctx["human_approved"] = True
    result = registry.call("deploy_alphaflow", {"source": str(source_file)}, ctx=ctx)
    assert result["ok"] is False
    assert "admin_only" in result["error"]
    assert _no_artifacts(ctx)


# ---------------------------------------------------------------------------
# 2. 批准 → artifact 落盘 + sha256 记录哈希 + evidence 留痕
# ---------------------------------------------------------------------------


def test_admin_deploy_produces_record(deploy_ctx, source_file):
    ctx = deploy_ctx(approved=True)
    result = registry.call("deploy_alphaflow", {"source": str(source_file)}, ctx=ctx)

    assert result["ok"] is True
    assert result["error"] is None
    # artifact 副本落盘，字节与 source 一致
    artifact = Path(result["artifact_path"])
    assert artifact.is_file()
    assert artifact.read_bytes() == source_file.read_bytes()
    # deploy_record_hash：sha256 形态（64 hex）且等于工件字节 sha256
    record_hash = result["deploy_record_hash"]
    assert isinstance(record_hash, str) and len(record_hash) == 64
    int(record_hash, 16)  # hex 可解析
    assert record_hash == hashlib.sha256(source_file.read_bytes()).hexdigest()

    # evidence 留痕：ARTIFACT 环存在且整链重放校验通过（工件 sha256 重绑磁盘）。
    # artifact 在 tmp_path/artifacts 下（仓库根外 → 绝对路径入链），
    # artifacts_root 取 tmp_path（= source_file.parent）供 verify_chain 重绑。
    from runner.evidence import verify_chain

    events = verify_chain(
        ctx["thread_id"],
        artifacts_dir=Path(ctx["evidence_dir"]),
        artifacts_root=source_file.parent,
    )
    artifact_events = [e for e in events if e.kind == AuditEventKind.ARTIFACT]
    assert len(artifact_events) == 1
    assert artifact_events[0].payload["sha256"] == record_hash
    assert artifact_events[0].payload["tool"] == "deploy_alphaflow"


def test_admin_deploy_description_source(deploy_ctx):
    """非路径非空描述 → 描述文本即工件（占位语义，接口已锁）。"""
    ctx = deploy_ctx(approved=True, thread_id="t-desc")
    result = registry.call(
        "deploy_alphaflow", {"source": "动量因子 v3，5日反转，已回测通过"}, ctx=ctx
    )
    assert result["ok"] is True
    assert Path(result["artifact_path"]).is_file()
    assert result["deploy_record_hash"] == hashlib.sha256(
        Path(result["artifact_path"]).read_bytes()
    ).hexdigest()


def test_deploy_invalid_source_fails_honestly(deploy_ctx, tmp_path):
    """目录 source / 空 source → 诚实失败（ok=False），黑盒话术。"""
    ctx = deploy_ctx(approved=True, thread_id="t-bad")
    (tmp_path / "a_dir").mkdir()
    bad = registry.call("deploy_alphaflow", {"source": str(tmp_path / "a_dir")}, ctx=ctx)
    assert bad["ok"] is False and bad["error"]
    assert bad["artifact_path"] is None and bad["deploy_record_hash"] is None

    empty = registry.call("deploy_alphaflow", {"source": "   "}, ctx=ctx)
    assert empty["ok"] is False and empty["error"]


# ---------------------------------------------------------------------------
# 3. 黑盒断言：序列化字段面 + 错误消息 grep 不到内部关键词
# ---------------------------------------------------------------------------


def test_deployresult_field_surface_is_minimal():
    """字段面刻意最小：只有四个黑盒安全字段，extra="forbid" 锁死。"""
    assert set(DeployResult.model_fields) == {
        "ok",
        "artifact_path",
        "deploy_record_hash",
        "error",
    }
    with pytest.raises(ValidationError):
        DeployResult(ok=True, pipeline_internal="leak")  # type: ignore[call-arg]


def test_output_blackbox(deploy_ctx, source_file):
    """全场景 DeployResult 序列化 + 错误消息 grep 不到 blackbox_forbidden_terms。"""
    adapter = StagingDeployAdapter()
    payloads: list[dict] = []

    # 场景 A：批准成功（文件 source）
    payloads.append(
        registry.call(
            "deploy_alphaflow", {"source": str(source_file)}, ctx=deploy_ctx(True, "t-a")
        )
    )
    # 场景 B：批准成功（描述 source）
    payloads.append(
        registry.call(
            "deploy_alphaflow",
            {"source": "反转因子 v2"},
            ctx=deploy_ctx(True, "t-b"),
        )
    )
    # 场景 C：未经批准中止
    payloads.append(
        registry.call(
            "deploy_alphaflow",
            {"source": str(source_file)},
            ctx=deploy_ctx(False, "t-c"),
        )
    )
    # 场景 D：适配失败（目录 source）
    ctx_d = deploy_ctx(True, "t-d")
    payloads.append(
        registry.call(
            "deploy_alphaflow", {"source": str(source_file.parent)}, ctx=ctx_d
        )
    )
    # 场景 E：适配器直调成功/失败原始 DeployResult（不经注册层）
    payloads.append(adapter.adapt(str(source_file)).model_dump())
    payloads.append(adapter.adapt("").model_dump())

    blob = json.dumps(payloads, ensure_ascii=False).lower()
    for term in blackbox_forbidden_terms:
        assert term not in blob, f"黑盒泄漏：DeployResult 输出含内部关键词 {term!r}"


# ---------------------------------------------------------------------------
# 4. registry 通道：可见性 + 严格 args 契约 + permission=None
# ---------------------------------------------------------------------------


def test_registry_channel(deploy_ctx, source_file):
    from tools.deploy._register import deploy_alphaflow_tool

    # 工具经 registry 可见，id 与契约严格一致
    tool = registry.get("deploy_alphaflow")
    assert tool is deploy_alphaflow_tool
    assert tool.id == "deploy_alphaflow"
    # args 严格 {"source": string}
    assert set(tool.schema.model_fields) == {"source"}
    # 门禁走 SSH 分级，不新增 per-tool HumanGate 触发点
    assert tool.permission is None

    # 缺 source → 校验错误可见（指回 source 字段）
    with pytest.raises(ValueError, match="source"):
        registry.call("deploy_alphaflow", {}, ctx=deploy_ctx(True))

    # 多余字段 → 拒绝（契约红线：lens 按 {"source": string} 调用）
    with pytest.raises(ValueError, match="extra"):
        registry.call(
            "deploy_alphaflow",
            {"source": str(source_file), "target": "prod"},
            ctx=deploy_ctx(True),
        )

    # 契约通路：{"source": string} 经 registry.call 端到端可执行
    ok = registry.call(
        "deploy_alphaflow", {"source": str(source_file)}, ctx=deploy_ctx(True, "t-registry")
    )
    assert ok["ok"] is True
