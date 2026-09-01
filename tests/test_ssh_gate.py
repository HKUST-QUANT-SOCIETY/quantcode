"""tests/test_ssh_gate.py — F-03 触发点② SSH 写操作分级门禁（governance SPEC §2.3 ②）。

覆盖（对应 governance SPEC G2-A8(d)）：
1. classify_ssh_action 纯函数分级判定表（read / dev_write / prod_write；
   prod 判定来源 = ssh_mainline 条目 "env": "prod" 标注 + 内建 prod 标签）；
2. prod 写 → ask（needs approval）→ interrupt payload kind=="deploy"
   （kind 为调用点注入的 payload 约定，非 schema 字段，照 merge/permission 模式）；
3. SSH 读 / 开发环境写零 interrupt 放行（收窄语义：非生产面不 gate）；
4. ssh_status 只读状态结构（host/user/指纹摘要/组映射就绪，零联网）。

AG-I 引用：governance SPEC §2.3 ② 与 §6 G2-A8(d) 回填 test_ssh_prod_write_gate。
"""
from __future__ import annotations

import json

import pytest

from runner.permission_engine import (
    check_ssh,
    enforce_ssh,
    reset_cache,
    ssh_gate_interrupt_payload,
)
from runner.server_ssh import classify_ssh_action, ssh_status


@pytest.fixture(autouse=True)
def perm_file(monkeypatch, tmp_path):
    """每个用例独立 permissions.yaml（env 覆盖 + 清缓存）。默认空配置。"""
    path = tmp_path / "permissions.yaml"
    path.write_text("", encoding="utf-8")
    monkeypatch.setenv("QUANTCODE_PERMISSIONS_FILE", str(path))
    reset_cache()
    yield path
    reset_cache()


def _set(path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    reset_cache()


# ssh_mainline 测试配置：srv-a 标注生产角色（env: prod），srv-dev 为开发环境
SSH_CFG = [
    {
        "name": "srv-a",
        "host": "10.1.1.11",
        "user": "quant",
        "key_path": "/tmp/id_test_a",
        "mainline_dir": "/srv/factor/mainline",
        "env": "prod",
    },
    {
        "name": "srv-dev",
        "host": "10.1.1.12",
        "user": "quant",
        "key_path": "/tmp/id_test_dev",
        "mainline_dir": "/srv/factor/dev",
    },
]


@pytest.fixture
def ssh_cfg(monkeypatch):
    monkeypatch.setenv("QUANTCODE_SSH_MAINLINE", json.dumps(SSH_CFG))


SHIPPED_YAML = (
    "permissions:\n"
    "  ssh.read: allow\n"
    "  ssh.dev.write: allow\n"
    "  ssh.prod.write: ask\n"
)


# ---------------------------------------------------------------------------
# 1. classify_ssh_action 纯函数：表驱动分级判定
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("ssh_cfg")
@pytest.mark.parametrize(
    "action, target_env, expected",
    [
        # —— 读：封闭集合内一律 read（即便目标是生产环境也不 gate）——
        ("read_mainline_file", "srv-a", "read"),
        ("read_mainline_listing", "srv-a", "read"),
        ("list", "srv-a", "read"),
        ("read", "prod", "read"),
        # —— 写 × 配置 env 角色标注（srv-a 标注 env: prod）——
        ("write_file", "srv-a", "prod_write"),
        ("deploy", "srv-a", "prod_write"),
        ("delete_file", "10.1.1.11", "prod_write"),  # host 命中 prod 标注
        # —— 写 × 内建环境标签 ——
        ("write_file", "prod", "prod_write"),
        ("write_file", "production", "prod_write"),
        ("write_file", "生产", "prod_write"),
        # —— 写 × 开发环境（未标注 = 开发）——
        ("write_file", "srv-dev", "dev_write"),
        ("write_file", "staging", "dev_write"),
        ("upload", "10.1.1.12", "dev_write"),
        # —— fail-closed：未知名 action 按写处理，不会被误判 read 绕闸 ——
        ("totally_unknown_action", "srv-dev", "dev_write"),
        ("totally_unknown_action", "srv-a", "prod_write"),
    ],
)
def test_classify_pure_function(action, target_env, expected):
    assert classify_ssh_action(action, target_env) == expected


def test_classify_no_config_defaults_dev_write(monkeypatch, tmp_path):
    """无任何 prod 标注（无配置、非 prod 标签）→ 写按 dev_write（不猜测生产）。"""
    monkeypatch.delenv("QUANTCODE_SSH_MAINLINE", raising=False)
    monkeypatch.setattr("runner.server_ssh._CONFIG_PATH", tmp_path / "nope.json")
    assert classify_ssh_action("write_file", "some-host") == "dev_write"
    assert classify_ssh_action("write_file", "prod") == "prod_write"  # 标签仍生效


# ---------------------------------------------------------------------------
# 2. prod 写 → ask → payload kind=deploy（G2-A8(d) 核心）
# ---------------------------------------------------------------------------


def test_prod_write_requires_deploy_gate(perm_file, ssh_cfg):
    _set(perm_file, SHIPPED_YAML)
    verdict = check_ssh("write_file", "srv-a", {"thread_id": "t1"})
    assert verdict["decision"] == "ask"
    assert "requires human approval" in verdict["reason"]

    payload = ssh_gate_interrupt_payload(
        "write_file", "srv-a", verdict["reason"], {"thread_id": "t1"}
    )
    assert payload["kind"] == "deploy"  # 调用点注入约定（merge/permission 同款）
    assert payload["action"] == "write_file"
    assert payload["target_env"] == "srv-a"
    assert payload["reasons"] == [verdict["reason"]]
    assert payload["gate_id"].startswith("hg_")

    # 真实链路：ask 必须走 interrupt 暂停（裸调 enforce_ssh 不在 runnable 上下文，
    # interrupt() 抛 RuntimeError——与 test_permission_engine 同款语义等价断言）
    with pytest.raises(Exception) as ei:
        enforce_ssh("write_file", "srv-a", {"thread_id": "t2"})
    msg = f"{type(ei.value).__name__}: {ei.value}"
    assert "Interrupt" in msg or "interrupt" in msg.lower() or "runnable" in msg.lower()


def test_prod_write_defaults_ask_when_unconfigured(perm_file, ssh_cfg):
    """ponytail fail-safe：yaml 缺 ssh.prod.write 键时生产写仍缺省 ask（闸不失效）。"""
    _set(perm_file, "")  # 空配置 → 引擎缺省 allow，但生产写例外
    assert check_ssh("write_file", "srv-a", {})["decision"] == "ask"


def test_prod_write_deny_raises(perm_file, ssh_cfg):
    _set(perm_file, "permissions:\n  ssh.prod.write: deny\n")
    with pytest.raises(PermissionError):
        check_ssh("write_file", "srv-a", {})


# ---------------------------------------------------------------------------
# 3. SSH 读 / 开发环境写零 interrupt 放行（收窄语义）
# ---------------------------------------------------------------------------


def test_read_and_dev_write_pass(perm_file, ssh_cfg):
    _set(perm_file, SHIPPED_YAML)
    # check 层直接 allow
    assert check_ssh("read_mainline_file", "srv-a", {})["decision"] == "allow"
    assert check_ssh("list", "srv-a", {})["decision"] == "allow"
    assert check_ssh("write_file", "srv-dev", {})["decision"] == "allow"
    # enforce 层零 interrupt：直接返回 allow（不抛 GraphInterrupt/RuntimeError）
    assert enforce_ssh("read_mainline_file", "srv-a", {})["decision"] == "allow"
    assert enforce_ssh("write_file", "srv-dev", {})["decision"] == "allow"


def test_ask_with_approved_allows(perm_file, ssh_cfg):
    """ask + ctx.human_approved=True → 放行（HumanGate approve 流程注入）。"""
    _set(perm_file, SHIPPED_YAML)
    verdict = check_ssh("write_file", "srv-a", {"human_approved": True})
    assert verdict["decision"] == "allow"
    assert "approved" in verdict["reason"]


# ---------------------------------------------------------------------------
# 4. G2-A8(d)：governance SPEC 命名断言（AG-I 回填 §2.3 ② / §6 时引用）
# ---------------------------------------------------------------------------


def test_ssh_prod_write_gate(perm_file, ssh_cfg):
    """G2-A8(d)：SSH 写生产环境触发点落地——prod 写 gate（kind=deploy）且
    读/开发写不 gate（与 test_human_gate_narrowing 的收窄语义组合成完整断言）。"""
    _set(perm_file, SHIPPED_YAML)
    # (d)-1 生产写 → needs approval + kind=deploy
    verdict = check_ssh("deploy", "prod", {})
    assert verdict["decision"] == "ask"
    assert ssh_gate_interrupt_payload("deploy", "prod", verdict["reason"], {})["kind"] == "deploy"
    # (d)-2 生产写之外零 gate（读 + 开发写）
    assert check_ssh("read", "prod", {})["decision"] == "allow"
    assert check_ssh("write", "dev", {})["decision"] == "allow"
    # (d)-3 fail-closed：人审 resume 非 approve（含垃圾输入归一化为 reject）→ 拒绝
    from runner.human_gate import normalize_external_decision

    assert normalize_external_decision("garbage") == "reject"


# ---------------------------------------------------------------------------
# 5. ssh_status 只读状态（零联网、零副作用）
# ---------------------------------------------------------------------------


def test_ssh_status_readonly(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTCODE_SSH_MAINLINE", json.dumps(SSH_CFG))
    bindings = tmp_path / "authorized_groups.yaml"
    bindings.write_text(
        "bindings:\n  - fingerprint: SHA256:abc123\n    group: factor\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("quantcode.identity.DEFAULT_BINDINGS_PATH", bindings)

    status = ssh_status()
    assert status["configured"] is True
    assert status["group_bindings_ready"] is True
    assert status["group_bindings_count"] == 1

    by_name = {s["name"]: s for s in status["servers"]}
    prod, dev = by_name["srv-a"], by_name["srv-dev"]
    # 连接要素（host/user/port 只读透出）
    assert prod["host"] == "10.1.1.11" and prod["user"] == "quant" and prod["port"] == 22
    # env 角色 / host_key 摘要
    assert prod["env_role"] == "prod" and dev["env_role"] is None
    assert prod["host_key_set"] is False and prod["host_key_digest"] is None
    # 指纹摘要：host_key 配置时为 12 位 hex（sha256 前 12 位）
    cfg_with_key = [dict(SSH_CFG[0], host_key="ssh-ed25519 AAAAc3R1Yg==")]
    monkeypatch.setenv("QUANTCODE_SSH_MAINLINE", json.dumps(cfg_with_key))
    status2 = ssh_status()
    digest = status2["servers"][0]["host_key_digest"]
    assert isinstance(digest, str) and len(digest) == 12
    int(digest, 16)  # hex 可解析
    # key 文件存在性只读探测（测试环境 key 文件不存在 → False，不抛错）
    assert status2["servers"][0]["key_file_present"] is False


def test_ssh_status_empty_config(monkeypatch, tmp_path):
    """未配置 → configured=False、组映射未就绪；不抛错（诚实降级）。"""
    monkeypatch.delenv("QUANTCODE_SSH_MAINLINE", raising=False)
    monkeypatch.setattr("runner.server_ssh._CONFIG_PATH", tmp_path / "nope.json")
    monkeypatch.setattr(
        "quantcode.identity.DEFAULT_BINDINGS_PATH", tmp_path / "no_bindings.yaml"
    )
    status = ssh_status()
    assert status == {
        "configured": False,
        "servers": [],
        "group_bindings_ready": False,
        "group_bindings_count": 0,
    }
