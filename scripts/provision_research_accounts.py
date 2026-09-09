"""Provision dedicated, unprivileged Linux research accounts from an approved roster.

Run without --apply to inspect the plan. This never starts a research runtime or
grants business groups, sudo, production credentials or a shared session file.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from quantcode.roster import normalize_public_key  # noqa: E402
from schemas.groups import GROUP_IDS  # noqa: E402


def build_plan(roster: dict, workspace_root: Path) -> list[dict]:
    if roster.get("status") == "REVIEW_REQUIRED":
        raise ValueError("roster requires review")
    if not workspace_root.is_absolute() or workspace_root.resolve() != workspace_root:
        raise ValueError("workspace root must be absolute and contain no symlinks")
    actors: dict[str, dict] = {}
    owners: dict[str, str] = {}
    for entry in roster.get("bindings", []):
        actor = entry.get("actor_id", "")
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,28}", actor):
            raise ValueError("invalid actor id for a research account")
        workspace = str(workspace_root / actor)
        if entry.get("workspace_path") != workspace:
            raise ValueError("workspace must be the actor's direct child of the approved root")
        groups = entry.get("groups") or [entry.get("group")]
        if entry.get("group") not in groups or any(group not in GROUP_IDS for group in groups):
            raise ValueError("invalid authorized group")
        key, fingerprint = normalize_public_key(entry.get("public_key", ""))
        if fingerprint != entry.get("fingerprint"):
            raise ValueError("public key does not match the approved fingerprint")
        if fingerprint in owners and owners[fingerprint] != actor:
            raise ValueError("public key shared by different actors")
        owners[fingerprint] = actor
        account = actors.setdefault(actor, {"actor_id": actor, "username": f"qc-{actor}",
            "workspace_path": workspace, "public_keys": {}, "groups": sorted(set(groups))})
        if account["groups"] != sorted(set(groups)):
            raise ValueError("conflicting group grants for one actor")
        account["public_keys"][fingerprint] = key
    if not actors:
        raise ValueError("approved roster has no complete identities")
    return list(actors.values())


def apply_plan(plan: list[dict], registry_path: Path, workspace_root: Path) -> list[dict]:
    if sys.platform != "linux" or os.geteuid() != 0:
        raise PermissionError("account provisioning requires the Linux administrator")
    import pwd
    if not registry_path.is_absolute() or registry_path.is_symlink() or (registry_path.exists() and
            (registry_path.stat().st_uid != 0 or registry_path.stat().st_mode & 0o077)):
        raise PermissionError("account registry must be root-owned and owner-only")
    registry = json.loads(registry_path.read_text()) if registry_path.exists() else {"accounts": {}}
    for parent in [workspace_root.parent, registry_path.parent]:
        if not parent.is_dir() or parent.resolve() != parent or parent.stat().st_uid != 0 or parent.stat().st_mode & 0o022:
            raise PermissionError("provisioning parents must be root-owned and not group/world writable")
    workspace_root.mkdir(mode=0o755, exist_ok=True)
    if workspace_root.stat().st_uid != 0 or workspace_root.stat().st_mode & 0o022:
        raise PermissionError("workspace parent must remain administrator-owned")

    # Preflight every identity before changing accounts. Existing personal
    # accounts and directories are never adopted by a coincidentally equal name.
    for account in plan:
        saved = registry["accounts"].get(account["actor_id"])
        try:
            existing = pwd.getpwnam(account["username"])
        except KeyError:
            existing = None
        if saved:
            if not existing or existing.pw_uid != saved["uid"] or existing.pw_dir != account["workspace_path"]:
                raise ValueError("registered account no longer matches its Linux identity")
            if set(saved["fingerprints"]) != set(account["public_keys"]):
                raise ValueError("key rotation requires an explicit enrollment update")
            for path, mode in [(Path(account["workspace_path"]), 0o700),
                               (Path(account["workspace_path"]) / ".ssh", 0o700),
                               (Path(account["workspace_path"]) / ".ssh/authorized_keys", 0o600)]:
                if path.is_symlink() or path.stat().st_uid != existing.pw_uid or path.stat().st_mode & 0o777 != mode:
                    raise PermissionError("registered workspace ownership or permissions changed")
            keys = (Path(account["workspace_path"]) / ".ssh/authorized_keys").read_text().splitlines()
            fingerprints = {normalize_public_key(key)[1] for key in keys if key.strip() and not key.startswith("#")}
            if fingerprints != set(saved["fingerprints"]):
                raise ValueError("registered SSH keys changed; review enrollment before proceeding")
        elif existing or Path(account["workspace_path"]).exists() or Path(account["workspace_path"]).is_symlink():
            raise ValueError("unregistered account or workspace already exists")

    result = []
    for account in plan:
        if account["actor_id"] in registry["accounts"]:
            result.append({"actor_id": account["actor_id"], "status": "EXISTING"})
            continue
        subprocess.run(["useradd", "--create-home", "--user-group", "--no-log-init",
                        "--home-dir", account["workspace_path"], "--shell", "/bin/bash",
                        "--comment", f"QuantCode research {account['actor_id']}", account["username"]],
                       check=True, capture_output=True)
        user = pwd.getpwnam(account["username"])
        workspace = Path(account["workspace_path"])
        workspace.chmod(0o700)
        ssh = workspace / ".ssh"
        ssh.mkdir(mode=0o700)
        os.chown(ssh, user.pw_uid, user.pw_gid)
        with (ssh / "authorized_keys").open("x") as output:
            os.chmod(output.fileno(), 0o600)
            os.fchown(output.fileno(), user.pw_uid, user.pw_gid)
            output.write("\n".join(account["public_keys"].values()) + "\n")
        registry["accounts"][account["actor_id"]] = {"username": user.pw_name, "uid": user.pw_uid,
            "gid": user.pw_gid, "workspace_path": str(workspace), "fingerprints": list(account["public_keys"]),
            "runtime_status": "NOT_CONFIGURED"}
        descriptor, temporary = tempfile.mkstemp(prefix=".research-identities-", dir=registry_path.parent)
        try:
            with os.fdopen(descriptor, "w") as output:
                json.dump(registry, output, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, registry_path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        result.append({"actor_id": account["actor_id"], "status": "CREATED"})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, default=Path("/srv/quant/users"))
    parser.add_argument("--registry", type=Path, default=Path("/etc/quantcode/research-identities.json"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    plan = build_plan(yaml.safe_load(args.roster.read_text()), args.workspace_root)
    result = apply_plan(plan, args.registry, args.workspace_root) if args.apply else [
        {key: value for key, value in account.items() if key != "public_keys"} for account in plan
    ]
    print(json.dumps({"status": "PROVISIONED" if args.apply else "PLAN", "accounts": result, "count": len(result)}))


if __name__ == "__main__":
    main()
