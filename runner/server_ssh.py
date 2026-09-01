"""server_ssh — SSH 读取各组主线服务器代码（P0-7，A09-04/05）。

规划来源：
- docs/Architecture_Spec.md:591 — ``server_ssh.py：SSH 读不同组服务器主线``
- docs/QuantCode_Design.md:370-374 — match_main 通过 SSH 读 Server A/B 主线代码并缓存到本地

设计（PonyTail 最小可用）：

- 配置：config.json 新段 ``ssh_mainline: [{name, host, port, user, key_path,
  mainline_dir, host_key?}]``（复用 runner/llm_config.py 的 ``_CONFIG_PATH`` 常量
  定位 config.json），或环境变量 ``QUANTCODE_SSH_MAINLINE``（同样结构的 JSON
  字符串，CI/测试场景，优先级高于 config.json）。
- 缓存：``~/.cache/quantcode/mainline/<sha1(host)>/`` 下缓存列目录结果与文件内容；
  读时写缓存、命中直接回本地。**无 TTL** — 主线代码变更后需手动清缓存
  （升级路径：按 remote mtime / 哈希失效或加 TTL）。
- 安全：
  * 路径穿越守卫 — relpath 必须相对、不含 ``..``、resolve 后仍在 mainline_dir 内；
  * host/user/key_path 只来自本地配置文件（非用户会话输入）；
  * connect 设 timeout=15 / banner_timeout=15，仅用显式 key（禁 agent/交互式探测）；
  * known_hosts：配置了 ``host_key`` 时用 RejectPolicy 严格校验；缺省 AutoAdd +
    UserWarning（升级路径：支持 known_hosts 文件 / TOFU 持久化）。
- 依赖：paramiko 为可选依赖（pyproject ``[project.optional-dependencies].ssh``），
  懒加载；未安装时首次真实连接抛 RuntimeError 并提示
  ``pip install 'quantcode[ssh]'``。``list_servers`` 不需要 paramiko。
- 可测性：连接工厂 ``_CONNECT_FN`` 模块级可替换（或 monkeypatch），测试注入假
  client 不走网络。
"""
from __future__ import annotations

import hashlib
import json
import os
import posixpath
import warnings
from pathlib import Path, PurePosixPath
from typing import Any, Callable

# 复用 llm_config 定位 config.json（其加载器只返回 llm 段，故这里只借路径常量）
from runner.llm_config import _CONFIG_PATH

_CONNECT_TIMEOUT = 15
_BANNER_TIMEOUT = 15

# 测试/CI 可注入的连接工厂：signature (server_cfg: dict) -> SSHClient-like
# （需实现 open_sftp() -> SFTP-like、close()）。None = 真实 paramiko 连接。
_CONNECT_FN: Callable[[dict[str, Any]], Any] | None = None


# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------


def _load_configs() -> list[dict[str, Any]]:
    """读取 ssh_mainline 配置：env ``QUANTCODE_SSH_MAINLINE`` 优先，其次 config.json。

    每项必需 name / host / user / key_path / mainline_dir，port 缺省 22，
    host_key 可选（OpenSSH 公钥行，如 ``ssh-ed25519 AAAA...``），
    env 可选（环境角色标注，``"prod"`` → F-03 生产写闸，见 classify_ssh_action）。
    配置缺失返回空列表；结构非法抛 ValueError。
    """
    raw: Any = None
    env = os.environ.get("QUANTCODE_SSH_MAINLINE", "").strip()
    if env:
        try:
            raw = json.loads(env)
        except json.JSONDecodeError as exc:
            raise ValueError(f"QUANTCODE_SSH_MAINLINE 不是合法 JSON: {exc}") from exc
    elif _CONFIG_PATH.exists():
        try:
            data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []  # config.json 损坏 → 视为未配置，诚实降级
        raw = data.get("ssh_mainline")

    if raw is None:
        return []
    if isinstance(raw, dict):  # 容错：允许 {"ssh_mainline": [...]} 包装
        raw = raw.get("ssh_mainline")
    if not isinstance(raw, list):
        raise ValueError("ssh_mainline 配置必须是数组")

    servers: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError(f"ssh_mainline 每项必须是对象: {item!r}")
        missing = [
            k for k in ("name", "host", "user", "key_path", "mainline_dir") if not item.get(k)
        ]
        if missing:
            raise ValueError(f"ssh_mainline 条目缺少字段 {missing}: {item.get('name', item)!r}")
        host_key = item.get("host_key")
        servers.append(
            {
                "name": str(item["name"]),
                "host": str(item["host"]),
                "port": int(item.get("port", 22)),
                "user": str(item["user"]),
                "key_path": str(item["key_path"]),
                "mainline_dir": str(item["mainline_dir"]),
                "host_key": str(host_key).strip() if host_key else None,
                "env": str(item.get("env") or "").strip().lower() or None,
            }
        )
    return servers


def list_servers() -> list[str]:
    """列出已配置的主线服务器名（不需要 paramiko / 不联网）。"""
    return [s["name"] for s in _load_configs()]


# ---------------------------------------------------------------------------
# F-03 触发点② 写操作分级（governance SPEC §2.3 ②，AG-F）
# ---------------------------------------------------------------------------

# 读操作封闭集合；未知名 action 一律按**写**处理（fail-closed：陌生写操作不会
# 被误判为 read 绕过生产写闸）。
_SSH_READ_ACTIONS = frozenset({
    "read", "list", "ls", "listdir", "get", "status", "stat", "cat",
    "read_file", "read_mainline_file", "read_mainline_listing",
})

# target_env 直接给环境名时可识别的生产标签。
PROD_ENV_LABELS = frozenset({"prod", "production", "生产"})


def _prod_targets() -> set[str]:
    """收集 prod 判定标记（``classify_ssh_action`` 的 prod 来源，注释即规格）：

    ① **服务器配置 env 角色标注**（最简可测方案）：``ssh_mainline`` 条目可选
       ``"env": "prod"`` 字段标注 A/B 服务器的生产角色——命中后该条目的 name 与
       host 都算生产目标。配置来源与 ``_load_configs`` 同源（env 变量
       ``QUANTCODE_SSH_MAINLINE`` 优先，其次 config.json）。
    ② **内建环境标签**：target_env 直接写 ``prod`` / ``production`` / ``生产``。
    未命中任何来源 → 开发环境（按显式标注判定，不做猜测。升级路径：SSH 指纹
    →组映射绑定 env 角色，见 F-05 登录界面）。
    """
    targets: set[str] = set(PROD_ENV_LABELS)
    for s in _load_configs():
        if str(s.get("env") or "").lower() in PROD_ENV_LABELS:
            targets.update({s["name"].lower(), s["host"].lower()})
    return targets


def classify_ssh_action(action: str, target_env: str) -> str:
    """F-03 触发点②分级纯函数：``"read" | "dev_write" | "prod_write"``。

    - action ∈ ``_SSH_READ_ACTIONS`` → read（SSH 读永不 gate）；
    - 其余 action（写/部署/删除等，含未知名，fail-closed）→ 按 target_env 分级：
      命中 ``_prod_targets()``（配置 env=prod 标注或内建 prod 标签）→ prod_write，
      否则 dev_write（开发环境写不 gate）。

    纯判定：只读本地配置与入参，不联网、无副作用（prod 判定来源见
    ``_prod_targets`` 注释）。
    """
    if str(action).strip().lower() in _SSH_READ_ACTIONS:
        return "read"
    env = str(target_env).strip().lower()
    return "prod_write" if env in _prod_targets() else "dev_write"


def ssh_status() -> dict[str, Any]:
    """只读元工具后端：SSH 连接配置状态摘要（不联网、不连 SSH、零副作用）。

    返回每个已配置服务器的连接要素（host/user/port）、host_key 摘要（sha256
    前 12 位）、env 角色、私钥文件存在性，以及指纹→组映射
    （``quantcode.identity``）是否就绪——供 F-05 登录界面 / Admin 面板展示。

    **移交说明：注册到 mcp_server 的工作归 AG-D（W3 窗口）**——本函数只交付
    可被调用的后端实现。

    ponytail: 只读现有配置与绑定文件，不做连通性探测
    （升级路径：可选 TCP probe / paramiko 指纹实算）。
    """
    from quantcode.identity import load_bindings

    servers: list[dict[str, Any]] = []
    for s in _load_configs():
        host_key = s.get("host_key")
        servers.append(
            {
                "name": s["name"],
                "host": s["host"],
                "port": s["port"],
                "user": s["user"],
                "env_role": s.get("env"),
                "host_key_set": bool(host_key),
                "host_key_digest": (
                    hashlib.sha256(host_key.encode("utf-8")).hexdigest()[:12]
                    if host_key
                    else None
                ),
                "key_file_present": Path(os.path.expanduser(s["key_path"])).exists(),
            }
        )
    bindings = load_bindings()
    return {
        "configured": bool(servers),
        "servers": servers,
        "group_bindings_ready": bool(bindings),
        "group_bindings_count": len(bindings),
    }


def _get_server(name: str) -> dict[str, Any]:
    for s in _load_configs():
        if s["name"] == name:
            return s
    raise KeyError(f"未配置的 SSH 主线服务器: {name!r}（可用: {list_servers()}）")


# ---------------------------------------------------------------------------
# 本地缓存
# ---------------------------------------------------------------------------


def _cache_root() -> Path:
    env = os.environ.get("QUANTCODE_MAINLINE_CACHE", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / ".cache" / "quantcode" / "mainline"


def _server_cache_dir(server_cfg: dict[str, Any]) -> Path:
    """缓存目录按 host 的 sha1 隔离（避免把主机名明文泄进路径）。"""
    digest = hashlib.sha1(server_cfg["host"].encode("utf-8")).hexdigest()
    return _cache_root() / digest


def _listing_cache_path(server_cfg: dict[str, Any], subdir: str) -> Path:
    digest = hashlib.sha1(subdir.encode("utf-8")).hexdigest()
    return _server_cache_dir(server_cfg) / "listings" / f"{digest}.json"


def _file_cache_path(server_cfg: dict[str, Any], relpath: str) -> Path:
    # relpath 已过路径穿越守卫（无 ".." 且相对），可直接镜像目录结构便于人工检查
    return _server_cache_dir(server_cfg) / "files" / relpath


def _write_cache(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# 安全守卫
# ---------------------------------------------------------------------------


def _safe_remote_path(mainline_dir: str, relpath: str) -> str:
    """路径穿越守卫：relpath 必须相对、不含 ".."、resolve 后仍在 mainline_dir 内。

    返回拼接后的远端绝对 POSIX 路径；非法时抛 ValueError。
    """
    if relpath.startswith("/"):
        raise ValueError(f"relpath 必须是相对路径，拒绝绝对路径: {relpath!r}")
    if ".." in PurePosixPath(relpath).parts:
        raise ValueError(f"relpath 禁止包含 '..': {relpath!r}")
    base = posixpath.normpath(mainline_dir)
    full = posixpath.normpath(posixpath.join(base, relpath)) if relpath else base
    if full != base and not full.startswith(base + "/"):
        raise ValueError(f"relpath 越出 mainline_dir: {relpath!r}")
    return full


# ---------------------------------------------------------------------------
# 连接（paramiko 懒加载 / 可注入）
# ---------------------------------------------------------------------------


def _import_paramiko():
    """懒加载 paramiko；未安装时抛带安装提示的 RuntimeError（核心依赖不含它）。"""
    try:
        import paramiko
    except ImportError as exc:
        raise RuntimeError(
            "paramiko 未安装，无法 SSH 读取主线服务器。"
            "请安装可选依赖: pip install 'quantcode[ssh]'"
        ) from exc
    return paramiko


def _connect(server_cfg: dict[str, Any]):
    """真实 paramiko 连接（仅用显式 key，host/user/key 均来自本地配置文件）。"""
    paramiko = _import_paramiko()
    client = paramiko.SSHClient()
    host_key = server_cfg.get("host_key")
    if host_key:
        entry = paramiko.hostkeys.HostKeyEntry.from_line(
            f"{server_cfg['host']} {host_key}"
        )
        if entry is None or entry.key is None:
            raise ValueError(f"host_key 解析失败（服务器 {server_cfg['name']}）")
        client.get_host_keys().add(server_cfg["host"], entry.key.get_name(), entry.key)
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        # PonyTail 升级路径：支持 known_hosts 文件 / TOFU 持久化；
        # 当前缺省 AutoAdd 信任首次指纹，并显式警告。
        warnings.warn(
            f"SSH 服务器 {server_cfg['name']}({server_cfg['host']}) 未配置 host_key，"
            "使用 AutoAddPolicy 信任首次连接的主机指纹"
            "（建议在 ssh_mainline 配置中提供 host_key）",
            stacklevel=2,
        )
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=server_cfg["host"],
        port=server_cfg["port"],
        username=server_cfg["user"],
        key_filename=os.path.expanduser(server_cfg["key_path"]),
        timeout=_CONNECT_TIMEOUT,
        banner_timeout=_BANNER_TIMEOUT,
        allow_agent=False,
        look_for_keys=False,
    )
    return client


def _open_sftp(server_cfg: dict[str, Any]):
    """经可注入工厂（或真实 paramiko）拿 client 并开 SFTP；调用方负责关闭两者。"""
    factory = _CONNECT_FN if _CONNECT_FN is not None else _connect
    client = factory(server_cfg)
    try:
        sftp = client.open_sftp()
    except Exception:
        client.close()
        raise
    return client, sftp


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def read_mainline_listing(server: str, subdir: str = "") -> list[str]:
    """列出主线目录（或其子目录）下的文件名，结果缓存到本地。

    命中缓存直接回；未命中经 SFTP listdir 拉取后写缓存。
    """
    server_cfg = _get_server(server)
    remote = _safe_remote_path(server_cfg["mainline_dir"], subdir)
    cache_path = _listing_cache_path(server_cfg, subdir)
    if cache_path.exists():
        try:
            files = json.loads(cache_path.read_text(encoding="utf-8"))["files"]
            if isinstance(files, list):
                return list(files)
        except (json.JSONDecodeError, KeyError, TypeError, OSError):
            pass  # 缓存损坏 → 回源重拉

    client, sftp = _open_sftp(server_cfg)
    try:
        names = sorted(sftp.listdir(remote))
    finally:
        sftp.close()
        client.close()

    _write_cache(
        cache_path,
        json.dumps({"subdir": subdir, "files": names}, ensure_ascii=False),
    )
    return names


def read_mainline_file(server: str, relpath: str) -> str:
    """读取主线文件内容（文本），结果缓存到本地；命中缓存不联网。"""
    if not PurePosixPath(relpath).parts:
        raise ValueError(f"relpath 不能为空: {relpath!r}")
    server_cfg = _get_server(server)
    remote = _safe_remote_path(server_cfg["mainline_dir"], relpath)
    cache_path = _file_cache_path(server_cfg, relpath)
    if cache_path.exists():
        try:
            return cache_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            pass  # 缓存损坏 → 回源重拉

    client, sftp = _open_sftp(server_cfg)
    try:
        with sftp.open(remote, "rb") as fh:
            data = fh.read()
    finally:
        sftp.close()
        client.close()

    text = data.decode("utf-8", errors="replace")
    _write_cache(cache_path, text)
    return text


__all__ = [
    "list_servers",
    "read_mainline_listing",
    "read_mainline_file",
    "classify_ssh_action",
    "ssh_status",
    "PROD_ENV_LABELS",
]
