"""runner/server_ssh 测试 — P0-7（A09-04/05，SSH 读主线服务器）。

全部用注入的假连接工厂（``_CONNECT_FN``）走本地缓存，不走网络，覆盖：
1. list_servers / 列目录 / 读文件（假 client）
2. 本地缓存命中：第二次读不再调连接工厂
3. 路径穿越守卫："../" 与绝对路径抛 ValueError
4. paramiko 缺失：RuntimeError 提示 pip install 'quantcode[ssh]'
5. match_main._enrich_with_mainline：有配置命中 → extra_context 含主线内容；
   无配置 / 无关键词命中 → 原样返回
"""
from __future__ import annotations

import json
import sys

import pytest

import runner.server_ssh as server_ssh
from runner.server_ssh import list_servers
from runner.server_ssh import read_mainline_file
from runner.server_ssh import read_mainline_listing

SERVER_CFG = [
    {
        "name": "srv-a",
        "host": "10.1.1.11",
        "port": 22,
        "user": "quant",
        "key_path": "/tmp/id_test",
        "mainline_dir": "/srv/factor/mainline",
    }
]

LISTING_ROOT = ["/srv/factor/mainline"]
FILE_PB = "/srv/factor/mainline/pb_factor.py"


# ---------------------------------------------------------------------------
# 假 SSH 环境（替代 paramiko，注入 _CONNECT_FN，零网络）
# ---------------------------------------------------------------------------


class FakeSFTPFile:
    def __init__(self, files: dict[str, str], path: str):
        self._files = files
        self._path = path

    def read(self) -> bytes:
        if self._path not in self._files:
            raise FileNotFoundError(f"fake sftp: no such file {self._path}")
        return self._files[self._path].encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSFTP:
    def __init__(self, listings: dict[str, list[str]], files: dict[str, str]):
        self._listings = listings
        self._files = files

    def listdir(self, path: str) -> list[str]:
        if path not in self._listings:
            raise FileNotFoundError(f"fake sftp: no such dir {path}")
        return list(self._listings[path])

    def open(self, path: str, mode: str = "rb") -> FakeSFTPFile:
        return FakeSFTPFile(self._files, path)

    def close(self) -> None:
        pass


class FakeClient:
    """假 SSHClient：与 server_ssh._open_sftp 的协议面一致（open_sftp/close）。"""

    def __init__(self, sftp: FakeSFTP):
        self._sftp = sftp
        self.closed = False

    def open_sftp(self) -> FakeSFTP:
        return self._sftp

    def close(self) -> None:
        self.closed = True


class FakeSSHEnv:
    """记录连接次数的假环境，验证缓存命中时不再触发连接。"""

    def __init__(self, listings: dict[str, list[str]], files: dict[str, str]):
        self.listings = listings
        self.files = files
        self.connect_calls = 0

    def make_client(self, server_cfg: dict) -> FakeClient:
        self.connect_calls += 1
        return FakeClient(FakeSFTP(self.listings, self.files))


@pytest.fixture
def fake_env(monkeypatch, tmp_path):
    """返回 install(listings, files) -> FakeSSHEnv；env 配置 + 缓存目录已隔离。"""
    monkeypatch.setenv("QUANTCODE_SSH_MAINLINE", json.dumps(SERVER_CFG))
    monkeypatch.setenv("QUANTCODE_MAINLINE_CACHE", str(tmp_path / "cache"))

    def _install(listings, files) -> FakeSSHEnv:
        env = FakeSSHEnv(listings, files)
        monkeypatch.setattr(server_ssh, "_CONNECT_FN", env.make_client)
        return env

    return _install


@pytest.fixture
def env_only_config(monkeypatch, tmp_path):
    """只设 env 配置 + 缓存目录（不注入连接工厂），用于守卫/paramiko 缺失用例。"""
    monkeypatch.setenv("QUANTCODE_SSH_MAINLINE", json.dumps(SERVER_CFG))
    monkeypatch.setenv("QUANTCODE_MAINLINE_CACHE", str(tmp_path / "cache"))


# ---------------------------------------------------------------------------
# 1. 基础 API（假 client）
# ---------------------------------------------------------------------------


def test_list_servers_from_env(monkeypatch):
    monkeypatch.setenv("QUANTCODE_SSH_MAINLINE", json.dumps(SERVER_CFG))
    assert list_servers() == ["srv-a"]


def test_list_servers_empty_without_config(monkeypatch, tmp_path):
    monkeypatch.delenv("QUANTCODE_SSH_MAINLINE", raising=False)
    monkeypatch.setattr(server_ssh, "_CONFIG_PATH", tmp_path / "nope.json")
    assert list_servers() == []


def test_read_mainline_listing(fake_env):
    env = fake_env(
        {
            LISTING_ROOT[0]: ["pb_factor.py", "roe_lib.py", "README.md"],
        },
        {},
    )
    assert read_mainline_listing("srv-a") == ["README.md", "pb_factor.py", "roe_lib.py"]
    assert env.connect_calls == 1


def test_read_mainline_listing_subdir(fake_env):
    env = fake_env({"/srv/factor/mainline/sub": ["x.py"]}, {})
    assert read_mainline_listing("srv-a", "sub") == ["x.py"]
    assert env.connect_calls == 1


def test_read_mainline_file(fake_env):
    fake_env({}, {FILE_PB: "def compute_pb(): ..."})
    assert read_mainline_file("srv-a", "pb_factor.py") == "def compute_pb(): ..."


# ---------------------------------------------------------------------------
# 2. 缓存命中：第二次读不再调连接工厂
# ---------------------------------------------------------------------------


def test_file_cache_hit_skips_connect(fake_env):
    env = fake_env({}, {FILE_PB: "content-v1"})
    assert read_mainline_file("srv-a", "pb_factor.py") == "content-v1"
    assert env.connect_calls == 1
    # 即使远端数据"变了"，缓存命中也直接回（无 TTL，ponytail 升级路径）
    env.files[FILE_PB] = "content-v2"
    assert read_mainline_file("srv-a", "pb_factor.py") == "content-v1"
    assert env.connect_calls == 1


def test_listing_cache_hit_skips_connect(fake_env):
    env = fake_env({LISTING_ROOT[0]: ["a.py"]}, {})
    assert read_mainline_listing("srv-a") == ["a.py"]
    assert read_mainline_listing("srv-a") == ["a.py"]
    assert env.connect_calls == 1


# ---------------------------------------------------------------------------
# 3. 路径穿越守卫
# ---------------------------------------------------------------------------


def test_path_traversal_rejected_for_file(env_only_config):
    with pytest.raises(ValueError, match=r"\.\."):
        read_mainline_file("srv-a", "../etc/passwd")


def test_path_traversal_rejected_for_listing(env_only_config):
    with pytest.raises(ValueError, match=r"\.\."):
        read_mainline_listing("srv-a", "../../secrets")


def test_absolute_relpath_rejected(env_only_config):
    with pytest.raises(ValueError, match="相对路径"):
        read_mainline_file("srv-a", "/etc/passwd")


def test_escape_via_normpath_rejected(env_only_config):
    # 不含字面 ".." 之外的越界形态（如符号链接外的 join 逃逸）也由 resolve 守卫兜底
    with pytest.raises(ValueError):
        read_mainline_file("srv-a", "a/../../etc/passwd")


def test_unknown_server_raises_keyerror(monkeypatch, tmp_path):
    monkeypatch.delenv("QUANTCODE_SSH_MAINLINE", raising=False)
    monkeypatch.setattr(server_ssh, "_CONFIG_PATH", tmp_path / "nope.json")
    with pytest.raises(KeyError):
        read_mainline_file("no-such-server", "x.py")


# ---------------------------------------------------------------------------
# 4. paramiko 缺失：懒加载 RuntimeError 带安装提示
# ---------------------------------------------------------------------------


def test_paramiko_missing_runtime_error(monkeypatch, env_only_config):
    # sys.modules 里塞 None 让 `import paramiko` 抛 ImportError（模拟未安装）
    monkeypatch.setitem(sys.modules, "paramiko", None)
    with pytest.raises(RuntimeError) as ei:
        read_mainline_file("srv-a", "pb_factor.py")
    assert "quantcode[ssh]" in str(ei.value)


def test_paramiko_missing_listing_runtime_error(monkeypatch, env_only_config):
    monkeypatch.setitem(sys.modules, "paramiko", None)
    with pytest.raises(RuntimeError, match="quantcode\\[ssh\\]"):
        read_mainline_listing("srv-a")


# ---------------------------------------------------------------------------
# 5. match_main._enrich_with_mainline
# ---------------------------------------------------------------------------


def test_enrich_hit_adds_mainline_snippets(fake_env):
    fake_env(
        {LISTING_ROOT[0]: ["pb_factor.py", "roe_lib.py", "README.md"]},
        {FILE_PB: "def compute_pb(): ...\n" * 300},  # 远超 2000 字符
    )
    from tools.factor.match_main import _enrich_with_mainline

    extra = _enrich_with_mainline({"existing": 1}, "PB-ROE 季度再平衡")
    assert extra["existing"] == 1  # 原 extra_context 键保留
    snippets = extra["mainline_snippets"]
    assert any(s["file"] == "pb_factor.py" for s in snippets)
    assert all(s["server"] == "srv-a" for s in snippets)
    assert all(len(s["excerpt"]) <= 2000 for s in snippets)
    # README.md 与 roe_lib.py 不含 pb/roe 关键词……roe_lib.py 命中 roe，README 不命中
    assert not any(s["file"] == "README.md" for s in snippets)


def test_enrich_no_config_returns_original_untouched(monkeypatch, tmp_path):
    monkeypatch.delenv("QUANTCODE_SSH_MAINLINE", raising=False)
    monkeypatch.setattr(server_ssh, "_CONFIG_PATH", tmp_path / "nope.json")
    from tools.factor.match_main import _enrich_with_mainline

    original = {"keep": "x"}
    out = _enrich_with_mainline(original, "PB-ROE 因子")
    assert out == {"keep": "x"}
    assert original == {"keep": "x"}  # 不改传入对象


def test_enrich_none_context_no_config(monkeypatch, tmp_path):
    monkeypatch.delenv("QUANTCODE_SSH_MAINLINE", raising=False)
    monkeypatch.setattr(server_ssh, "_CONFIG_PATH", tmp_path / "nope.json")
    from tools.factor.match_main import _enrich_with_mainline

    assert _enrich_with_mainline(None, "PB-ROE") == {}


def test_enrich_no_token_hit_returns_without_snippets(fake_env):
    fake_env({LISTING_ROOT[0]: ["pb_factor.py"]}, {})
    from tools.factor.match_main import _enrich_with_mainline

    extra = _enrich_with_mainline(None, "纯中文描述的动量因子，无ASCII关键词")
    assert "mainline_snippets" not in extra


def test_enrich_swallows_ssh_failure(monkeypatch, env_only_config):
    """配置了服务器但连接必炸（paramiko 缺失即触发）→ 静默返回原 extra_context。"""
    monkeypatch.setitem(sys.modules, "paramiko", None)  # 无 _CONNECT_FN 且无 paramiko
    from tools.factor.match_main import _enrich_with_mainline

    original = {"hist": [1, 2]}
    out = _enrich_with_mainline(original, "PB-ROE")
    assert out == {"hist": [1, 2]}
