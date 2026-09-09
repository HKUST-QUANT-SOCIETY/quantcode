"""Read-only deployment layout for real enrolled Test V1 members on Server C.

Validates the existing Linux enrollment and SSH keys. This does not create
accounts, change permissions, install services or print connection credentials.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.install_native_host import authorized_public_keys, enrolled_member  # noqa: E402
from schemas.groups import GROUP_IDS  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--ssh-host", required=True)
    parser.add_argument("--release", default="test-v1-20260909")
    parser.add_argument("--gateway-port", type=int, default=5098)
    parser.add_argument("--base-port", type=int, default=8101)
    args = parser.parse_args()
    if sys.platform != "linux" or os.geteuid() != 0:
        raise PermissionError("Read-only enrollment inspection requires the Server C administrator")
    import pwd
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", args.release):
        raise ValueError("Invalid test release")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", args.ssh_host):
        raise ValueError("An explicit SSH hostname or IPv4 address is required")
    roster_bytes = args.roster.read_bytes()
    registry_bytes = args.registry.read_bytes()
    roster, registry = yaml.safe_load(roster_bytes), json.loads(registry_bytes)
    actors = defaultdict(list)
    for entry in roster.get("bindings", []):
        actors[entry["actor_id"]].append(entry)
    if not actors or set(actors) != set(registry.get("accounts", {})):
        raise ValueError("Roster and enrollment must contain the same real actors")
    count = len(actors)
    ports = [args.gateway_port, *range(args.base_port, args.base_port + count)]
    if min(ports) < 1024 or max(ports) > 65535 or len(set(ports)) != len(ports):
        raise ValueError("Test ports must be distinct non-privileged ports")
    listeners = {int(line.split()[3].rsplit(":", 1)[1])
                 for line in subprocess.check_output(["ss", "-ltn"], text=True).splitlines()[1:]}
    if conflict := sorted(listeners.intersection(ports)):
        raise ValueError(f"Proposed test ports already have listeners: {conflict}")
    records = []
    for index, (actor, entries) in enumerate(sorted(actors.items())):
        if actor.startswith("sim-"):
            raise ValueError("Synthetic QA identities are not Test V1 members")
        saved = registry["accounts"][actor]
        user = pwd.getpwnam(saved["username"])
        enrolled = [enrolled_member(roster, registry, actor, entry["fingerprint"], user,
                    os.getgrouplist(user.pw_name, user.pw_gid)) for entry in entries]
        workspace = Path(user.pw_dir)
        if (not workspace.is_relative_to("/srv/quant/users") or workspace.is_symlink()
                or workspace.stat().st_uid != user.pw_uid or workspace.stat().st_mode & 0o077):
            raise PermissionError("Existing research workspace ownership or privacy changed")
        keys = authorized_public_keys(workspace, user.pw_uid)
        if keys != {entry["fingerprint"]: entry["public_key"] for entry in enrolled}:
            raise PermissionError("Existing authorized_keys no longer match the approved roster")
        if len({(entry["group"], entry["role"], entry["workspace_id"]) for entry in enrolled}) != 1:
            raise ValueError("An actor's registered keys have inconsistent membership")
        install = Path("/opt/quantcode-test-v1/native-hosts") / actor / args.release
        state = Path("/var/lib/quantcode-test-v1/native") / actor / args.release
        private = workspace / ".quantcode/test-v1"
        records.append({"actor_id": actor, "username": user.pw_name, "group": enrolled[0]["group"],
            "role": enrolled[0]["role"], "workspace": str(workspace), "public_key_count": len(enrolled),
            "native_port": args.base_port + index, "native_url": f"http://127.0.0.1:{args.base_port + index}",
            "install": str(install), "state": str(state),
            "unit": f"quantcode-native-{actor}-{args.release}.service",
            "public_key_files": [str(install / f"identity-{key_index}.pub") for key_index in range(len(enrolled))],
            "private_connection_file": str(private / "connection.json"), "private_directory_mode": "0700", "private_file_mode": "0600",
            "ssh_destination": f"{user.pw_name}@{args.ssh_host}",
            "ssh_forward_target": f"127.0.0.1:{args.base_port + index}",
            "credential_status": "generated separately per member at installation"})
    groups = dict(Counter(record["group"] for record in records))
    if set(groups) != set(GROUP_IDS):
        raise ValueError("Real member enrollment does not cover all eight product groups")
    print(json.dumps({"status": "PLAN_ONLY", "release": args.release, "members": records,
        "member_count": count, "public_key_count": sum(record["public_key_count"] for record in records), "groups": groups,
        "roster_sha256": hashlib.sha256(roster_bytes).hexdigest(), "registry_sha256": hashlib.sha256(registry_bytes).hexdigest(),
        "gateway": {"unit": "quantcode-test-v1-gateway.service", "url": f"http://127.0.0.1:{args.gateway_port}",
                    "database": "/var/lib/quantcode-test-v1/gateway/gateway.db", "existing_formal_port": 4097},
        "source_and_binary": "reviewed immutable Test V1 artifacts; share verified root-owned binary inode",
        "sandbox_profile": "quantcode-test-v1-native", "service_policy": {"Restart": "on-failure", "RestartSec": 3,
            "MemoryMax": "1G", "CPUQuota": "100%", "TasksMax": 256},
        "model_credentials": "pending organization choice; no model key written",
        "disk_available_bytes": shutil.disk_usage("/").free,
        "mutations_performed": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
