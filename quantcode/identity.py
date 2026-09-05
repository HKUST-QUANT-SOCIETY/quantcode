"""SSH key → group 身份绑定（P0-7）。

设计要求（``docs/QuantCode_Design.md`` §2.1）：SSH key 与组**长期绑定**，
会话内不可变；MCP server 启动时凭宿主注入的公钥指纹解析出组身份，
未命中一律 fail-closed。

映射文件：``.opencode/authorized_groups.yaml``（真实文件含敏感绑定关系，
进 .gitignore 不入库；仓库提交 ``.opencode/authorized_groups.example.yaml``
样例）。格式::

    bindings:
      - fingerprint: "SHA256:xxxxx"   # ssh-keygen -lf 输出格式
        group: factor
        note: "zhang@laptop"

CLI::

    python -m quantcode.identity add    --group <g> --public-key <path> [--note txt]
    python -m quantcode.identity remove --fingerprint <fp>
    python -m quantcode.identity list
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import sys
from pathlib import Path

import yaml

# 默认绑定文件：相对仓库根（本模块位于 <root>/quantcode/ 下），与 CWD 无关。
# 测试通过 monkeypatch 本模块属性指向 tmp 路径。
DEFAULT_BINDINGS_PATH = (
    Path(__file__).resolve().parent.parent / ".opencode" / "authorized_groups.yaml"
)


def fingerprint_of_public_key(pubkey_line: str) -> str:
    """计算 OpenSSH 公钥的 SHA256 指纹，格式与 ``ssh-keygen -lf`` 输出一致。

    解析公钥行的 base64 部分并解码，对 blob 做 SHA256，再以
    ``"SHA256:" + base64(无填充)`` 返回。已是 ``"SHA256:..."`` 的指纹字符串
    原样返回（幂等）。
    """
    line = pubkey_line.strip()
    if line.startswith("SHA256:"):
        return line
    parts = line.split()
    if len(parts) < 2:
        raise ValueError(f"不是合法的 OpenSSH 公钥行: {pubkey_line!r}")
    blob = base64.b64decode(parts[1], validate=True)
    digest = hashlib.sha256(blob).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def _load_entries(path: Path | str | None = None) -> list[dict]:
    """读取绑定文件，返回原始 entry 列表（保留 note）。文件缺失返回 []。"""
    p = Path(path) if path is not None else Path(DEFAULT_BINDINGS_PATH)
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if data.get("status") == "REVIEW_REQUIRED":
        raise ValueError("roster candidate requires review before activation")
    entries = []
    fingerprints = {}
    for item in data.get("bindings") or []:
        if not isinstance(item, dict):
            continue
        fp = str(item.get("fingerprint", "")).strip()
        group = str(item.get("group", "")).strip()
        if fp and group:
            entry: dict = {"fingerprint": fp, "group": group}
            for key in (
                "actor_id",
                "role",
                "workspace_id",
                "workspace_path",
                "github_subject",
                "note",
            ):
                value = str(item.get(key, "") or "").strip()
                if value:
                    entry[key] = value
            scopes = item.get("resource_scopes")
            if isinstance(scopes, list):
                entry["resource_scopes"] = [str(scope) for scope in scopes]
            previous = fingerprints.get(fp)
            if previous is not None and previous != entry:
                raise ValueError("conflicting roster entries for one SSH fingerprint")
            if previous is None:
                entries.append(entry)
                fingerprints[fp] = entry
    return entries


def _write_entries(entries: list[dict], path: Path | str | None = None) -> None:
    p = Path(path) if path is not None else Path(DEFAULT_BINDINGS_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        yaml.safe_dump({"bindings": entries}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def load_bindings(path: Path | str | None = None) -> dict[str, str]:
    """读取 ``fingerprint -> group`` 映射。文件不存在或为空返回 ``{}``。

    同指纹相同记录去重；身份/权限冲突拒绝加载，不按行顺序授予权限。
    """
    return {e["fingerprint"]: e["group"] for e in _load_entries(path)}


def resolve_group(fingerprint: str, bindings: dict[str, str]) -> str | None:
    """按指纹查组。未命中返回 ``None``（调用方 fail-closed）。"""
    return bindings.get(fingerprint.strip())


def resolve_identity(fingerprint: str, path: Path | str | None = None) -> dict | None:
    """Return the full roster entry for a fingerprint, or ``None``."""
    target = fingerprint.strip()
    for entry in _load_entries(path):
        if entry["fingerprint"] == target:
            return dict(entry)
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _read_public_key_arg(value: str) -> str:
    """--public-key 参数：既接受公钥文件路径，也接受直接粘贴的公钥行/指纹。"""
    p = Path(value).expanduser()
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line
        raise SystemExit(f"error: {p} 中没有公钥行")
    return value


def cmd_add(args: argparse.Namespace) -> None:
    key_line = _read_public_key_arg(args.public_key)
    fp = fingerprint_of_public_key(key_line)
    entries = _load_entries()
    for e in entries:
        if e["fingerprint"] == fp:
            e["group"] = args.group
            if args.note:
                e["note"] = args.note
            else:
                e.pop("note", None)
            _write_entries(entries)
            print(f"updated: {fp} -> {args.group}")
            return
    entry: dict = {"fingerprint": fp, "group": args.group}
    if args.note:
        entry["note"] = args.note
    entries.append(entry)
    _write_entries(entries)
    print(f"added: {fp} -> {args.group}")


def cmd_remove(args: argparse.Namespace) -> None:
    # 指纹入参经 fingerprint_of_public_key 归一化（对 "SHA256:..." 幂等）
    fp = fingerprint_of_public_key(args.fingerprint)
    entries = _load_entries()
    kept = [e for e in entries if e["fingerprint"] != fp]
    if len(kept) == len(entries):
        raise SystemExit(f"error: 未找到指纹 {fp}（用 list 查看现有绑定）")
    _write_entries(kept)
    print(f"removed: {fp}")


def cmd_list(_args: argparse.Namespace) -> None:
    entries = _load_entries()
    if not entries:
        print("(no bindings)")
        return
    for e in entries:
        note = f"  # {e['note']}" if e.get("note") else ""
        print(f"{e['fingerprint']} -> {e['group']}{note}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m quantcode.identity",
        description="SSH key → group 绑定管理（P0-7）",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="添加/更新绑定（同指纹去重）")
    p_add.add_argument("--group", required=True)
    p_add.add_argument("--public-key", required=True, help="公钥文件路径或公钥行/指纹")
    p_add.add_argument("--note", default="", help="备注，如 zhang@laptop")
    p_add.set_defaults(func=cmd_add)

    p_rm = sub.add_parser("remove", help="删除绑定")
    p_rm.add_argument("--fingerprint", required=True)
    p_rm.set_defaults(func=cmd_remove)

    p_ls = sub.add_parser("list", help="列出绑定")
    p_ls.set_defaults(func=cmd_list)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
