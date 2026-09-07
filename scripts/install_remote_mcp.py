"""Install one immutable, root-owned remote MCP source release for enrolled users."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from quantcode.remote_mcp import trusted_path  # noqa: E402


def write_json(path: Path, record: dict) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".remote-mcp-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump(record, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, default=Path("/etc/quantcode/research-identities.json"))
    parser.add_argument("--roster", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "linux" or os.geteuid() != 0:
        raise PermissionError("the Linux administrator must install the runtime")
    import pwd
    import yaml

    root = trusted_path(args.runtime_root)
    trusted_path((root / ".venv").resolve())
    if (root / "users").exists():
        raise FileExistsError("use a new source release directory; existing runtimes are immutable")
    accounts = json.loads(trusted_path(args.registry).read_text())["accounts"]
    roster = yaml.safe_load(args.roster.read_text())
    if roster.get("status") == "REVIEW_REQUIRED":
        raise ValueError("roster requires review")
    enrollments = []
    for actor, account in accounts.items():
        user = pwd.getpwnam(account["username"])
        matches = [entry for entry in roster["bindings"] if entry["actor_id"] == actor]
        if (user.pw_uid != account["uid"] or user.pw_dir != account["workspace_path"] or not matches
                or {entry["workspace_path"] for entry in matches} != {user.pw_dir}
                or len({entry["workspace_id"] for entry in matches}) != 1
                or os.getgrouplist(user.pw_name, user.pw_gid) != [user.pw_gid]):
            raise PermissionError("Linux account and approved roster no longer match")
        enrollments.append({"actor_id": actor, "uid": user.pw_uid, "username": user.pw_name,
                            "workspace_path": user.pw_dir, "workspace_id": matches[0]["workspace_id"]})
    for name in ("quantcode", "runner", "schemas", "tools", "flows", "configs", ".opencode", "dream"):
        trusted_path(root / name)
        for path in (root / name).rglob("*"):
            trusted_path(path)
    if (root / ".opencode/authorized_groups.yaml").exists() or (root / ".quantcode").exists():
        raise ValueError("the source release must not contain credentials or runtime state")
    users = root / "users"
    users.mkdir(mode=0o755)
    destination = Path("/opt/quantcode/enrollments")
    destination.mkdir(mode=0o755, exist_ok=True)
    trusted_path(destination)
    for record in enrollments:
        target = users / str(record["uid"])
        target.mkdir(mode=0o755)
        for name in ("quantcode", "runner", "schemas", "tools", "flows", "configs", ".opencode", "dream"):
            shutil.copytree(root / name, target / name, copy_function=os.link)
        (target / ".venv").symlink_to(root / ".venv")
        (target / ".quantcode").symlink_to(Path(record["workspace_path"]) / ".quantcode")
        write_json(destination / f"{record['uid']}.json", record)
    ops = trusted_path(Path("/opt/quantcode/ops"))
    shutil.copyfile(root / "ops/remote-mcp", ops / "remote-mcp.next")
    (ops / "remote-mcp.next").chmod(0o755)
    os.replace(ops / "remote-mcp.next", ops / "remote-mcp")
    write_json(ops / "remote-runtime.json", {"runtime_root": str(root), "gateway": "http://127.0.0.1:4097"})
    pointer = root.parent / "current.next"
    pointer.symlink_to(root)
    os.replace(pointer, root.parent / "current")
    print(json.dumps({"status": "INSTALLED", "runtime_root": str(root), "enrollments": len(enrollments)}))


if __name__ == "__main__":
    main()
