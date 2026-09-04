"""P0-7 身份绑定单测：SSH key → group（quantcode/identity.py + _get_mcp_group 三级）。"""
from __future__ import annotations

import pytest
import yaml

from quantcode import identity
from quantcode import mcp_server

# 固定测试公钥（ed25519，仅为测试生成），指纹对照真实 `ssh-keygen -lf` 输出
TEST_PUBKEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKppLIXBw3gtueCPjn+AS5bGODGphnlIBrE1jb"
    "/lxi3C quantcode-test"
)
TEST_FP = "SHA256:oVDaaoONrPL38IxAoGR14Do45YIKvDt5o7ASsv0jiaA"


@pytest.fixture(autouse=True)
def _isolated_identity(monkeypatch, tmp_path):
    """隔离环境：清指纹相关 env、把绑定文件指向 tmp、清进程内缓存。"""
    monkeypatch.setenv("QUANTCODE_ENV", "test")
    for var in (
        "QUANTCODE_SSH_KEY_FINGERPRINT",
        "QUANTCODE_SSH_FINGERPRINT",
        "QUANTCODE_GROUP",
        "QUANTCODE_ALLOW_UNAUTH",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(
        identity, "DEFAULT_BINDINGS_PATH", tmp_path / "opencode" / "authorized_groups.yaml"
    )
    monkeypatch.setattr(mcp_server, "_SESSION_GROUP", None)
    yield


def _write_bindings(tmp_path, entries):
    path = identity.DEFAULT_BINDINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"bindings": entries}), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# fingerprint_of_public_key
# ---------------------------------------------------------------------------


def test_fingerprint_matches_ssh_keygen():
    """指纹计算与 `ssh-keygen -lf` 输出一致（硬编码已知值）。"""
    assert identity.fingerprint_of_public_key(TEST_PUBKEY) == TEST_FP


def test_fingerprint_accepts_fingerprint_string():
    """入参已是 SHA256:... 指纹 → 幂等原样返回。"""
    assert identity.fingerprint_of_public_key(TEST_FP) == TEST_FP


def test_fingerprint_invalid_line_raises():
    with pytest.raises(ValueError):
        identity.fingerprint_of_public_key("not-a-key")


# ---------------------------------------------------------------------------
# load_bindings / resolve_group
# ---------------------------------------------------------------------------


def test_load_bindings_missing_file_returns_empty(tmp_path):
    assert identity.load_bindings(tmp_path / "nope.yaml") == {}


def test_load_bindings_reads_yaml(tmp_path):
    p = tmp_path / "b.yaml"
    p.write_text(
        "bindings:\n"
        f"  - fingerprint: \"{TEST_FP}\"\n"
        "    group: factor\n"
        '    note: "zhang@laptop"\n',
        encoding="utf-8",
    )
    assert identity.load_bindings(p) == {TEST_FP: "factor"}


def test_load_bindings_dedupes_same_fingerprint(tmp_path):
    """同指纹多条 → 去重，后写覆盖先写。"""
    p = _write_bindings(
        tmp_path,
        [
            {"fingerprint": TEST_FP, "group": "model"},
            {"fingerprint": TEST_FP, "group": "factor"},
            {"fingerprint": "SHA256:AAAA", "group": "risk"},
        ],
    )
    assert identity.load_bindings(p) == {TEST_FP: "factor", "SHA256:AAAA": "risk"}


def test_resolve_group_hit_and_miss():
    bindings = {TEST_FP: "factor"}
    assert identity.resolve_group(TEST_FP, bindings) == "factor"
    assert identity.resolve_group("SHA256:MISSING", bindings) is None


# ---------------------------------------------------------------------------
# CLI (add / remove / list)
# ---------------------------------------------------------------------------


def test_cli_add_creates_file_and_dedupes(tmp_path, capsys):
    key_file = tmp_path / "id_test.pub"
    key_file.write_text(TEST_PUBKEY + "\n", encoding="utf-8")

    identity.main(["add", "--group", "factor", "--public-key", str(key_file), "--note", "zhang@laptop"])
    bindings = identity.load_bindings()
    assert bindings == {TEST_FP: "factor"}

    # 同指纹再次 add → 去重不追加，改为更新
    identity.main(["add", "--group", "model", "--public-key", str(key_file)])
    raw = yaml.safe_load(identity.DEFAULT_BINDINGS_PATH.read_text(encoding="utf-8"))
    entries = raw["bindings"]
    assert len(entries) == 1
    assert entries[0]["group"] == "model"
    assert "note" not in entries[0]
    assert identity.load_bindings() == {TEST_FP: "model"}


def test_cli_remove_and_list(tmp_path, capsys):
    identity.main(["add", "--group", "factor", "--public-key", TEST_FP])
    identity.main(["list"])
    assert TEST_FP in capsys.readouterr().out

    identity.main(["remove", "--fingerprint", TEST_FP])
    assert identity.load_bindings() == {}
    with pytest.raises(SystemExit):
        identity.main(["remove", "--fingerprint", TEST_FP])  # 再删 → 报错退出


# ---------------------------------------------------------------------------
# _get_mcp_group 三级行为
# ---------------------------------------------------------------------------


def test_get_mcp_group_tier_b_env_fallback_no_bindings(monkeypatch):
    """无指纹 + 无绑定文件 → 沿用 QUANTCODE_GROUP（现状不变）。"""
    monkeypatch.setenv("QUANTCODE_GROUP", "model")
    assert mcp_server._get_mcp_group() == "model"
    monkeypatch.delenv("QUANTCODE_GROUP")
    assert mcp_server._get_mcp_group() is None


def test_get_mcp_group_tier_a_hit(monkeypatch):
    """指纹 env + 绑定命中 → 返回绑定组。"""
    _write_bindings(identity.DEFAULT_BINDINGS_PATH.parent, [{"fingerprint": TEST_FP, "group": "factor"}])
    monkeypatch.setenv("QUANTCODE_SSH_KEY_FINGERPRINT", TEST_FP)
    monkeypatch.setenv("QUANTCODE_GROUP", "risk")  # 绑定优先于 env
    assert mcp_server._get_mcp_group() == "factor"


def test_get_mcp_group_tier_a_alias_env(monkeypatch):
    """别名 env QUANTCODE_SSH_FINGERPRINT 同样生效。"""
    _write_bindings(identity.DEFAULT_BINDINGS_PATH.parent, [{"fingerprint": TEST_FP, "group": "model"}])
    monkeypatch.setenv("QUANTCODE_SSH_FINGERPRINT", TEST_FP)
    assert mcp_server._get_mcp_group() == "model"


def test_get_mcp_group_tier_a_session_immutable_cache(monkeypatch):
    """命中后进程内缓存：删除 env 和绑定文件，仍返回原组（会话内不可变）。"""
    _write_bindings(identity.DEFAULT_BINDINGS_PATH.parent, [{"fingerprint": TEST_FP, "group": "factor"}])
    monkeypatch.setenv("QUANTCODE_SSH_KEY_FINGERPRINT", TEST_FP)
    assert mcp_server._get_mcp_group() == "factor"
    monkeypatch.delenv("QUANTCODE_SSH_KEY_FINGERPRINT")
    identity.DEFAULT_BINDINGS_PATH.unlink()
    assert mcp_server._get_mcp_group() == "factor"


def test_get_mcp_group_tier_a_miss_fail_closed(monkeypatch):
    """指纹未命中绑定 → fail-closed，报错含如何 add。"""
    _write_bindings(identity.DEFAULT_BINDINGS_PATH.parent, [{"fingerprint": "SHA256:OTHER", "group": "risk"}])
    monkeypatch.setenv("QUANTCODE_SSH_KEY_FINGERPRINT", TEST_FP)
    with pytest.raises(RuntimeError, match="identity add"):
        mcp_server._get_mcp_group()


def test_get_mcp_group_tier_a_miss_no_file_fail_closed(monkeypatch):
    """有指纹 env 但文件不存在 → 同样 fail-closed（不能静默落到 env）。"""
    monkeypatch.setenv("QUANTCODE_SSH_KEY_FINGERPRINT", TEST_FP)
    with pytest.raises(RuntimeError, match="identity add"):
        mcp_server._get_mcp_group()


def test_get_mcp_group_tier_c_bindings_without_fingerprint_fail_closed(monkeypatch):
    """有绑定配置但无指纹 → fail-closed，报错给出三条出路。"""
    _write_bindings(identity.DEFAULT_BINDINGS_PATH.parent, [{"fingerprint": TEST_FP, "group": "factor"}])
    with pytest.raises(RuntimeError, match="QUANTCODE_ALLOW_UNAUTH"):
        mcp_server._get_mcp_group()


def test_get_mcp_group_tier_c_allow_unauth_env_fallback(monkeypatch, caplog):
    """显式 QUANTCODE_ALLOW_UNAUTH=1 → env 兜底 + warning。"""
    _write_bindings(identity.DEFAULT_BINDINGS_PATH.parent, [{"fingerprint": TEST_FP, "group": "factor"}])
    monkeypatch.setenv("QUANTCODE_ALLOW_UNAUTH", "1")
    monkeypatch.setenv("QUANTCODE_GROUP", "risk")
    with caplog.at_level("WARNING", logger="quantcode.mcp"):
        assert mcp_server._get_mcp_group() == "risk"
    assert any("降级" in r.message for r in caplog.records)


def test_get_mcp_group_tier_b_warning_logged(monkeypatch, caplog):
    """降级路径打 warning（未配置 SSH 绑定，组身份来自环境变量）。"""
    monkeypatch.setenv("QUANTCODE_GROUP", "model")
    with caplog.at_level("WARNING", logger="quantcode.mcp"):
        assert mcp_server._get_mcp_group() == "model"
    assert any("环境变量" in r.message for r in caplog.records)
