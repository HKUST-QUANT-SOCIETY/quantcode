"""Activate a verified compiled terminal fix; preserve prior artifacts and manifests."""

from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sqlite3
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--actor", help="Optional staged rollout to one enrolled actor")
    parser.add_argument("--backup-tag", default="terminal-engine", help="Unique label for this activation's backups")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9-]{1,80}", args.backup_tag):
        raise ValueError("Invalid activation backup label")
    backup_suffix = ".before-" + args.backup_tag
    artifact = args.artifact.resolve()
    binary = artifact / "bin/opencode"
    manifest = artifact / "native-build.json"
    metadata = json.loads(manifest.read_text())
    if (
        binary.is_symlink()
        or hashlib.sha256(binary.read_bytes()).hexdigest() != args.sha256
        or metadata["binary_sha256"] != args.sha256
    ):
        raise ValueError("Compiled engine does not match its reviewed digest")
    if os.geteuid() != 0:
        raise PermissionError("Use sudo on Server C")
    plans = []
    for base in ["/opt/quantcode-test-v1/native-hosts", "/opt/quantcode-admin/native-hosts"]:
        for path in Path(base).glob("*/*/native-host.json"):
            raw = path.read_bytes()
            value = json.loads(raw)
            target = path.parent / "bin/opencode"
            if args.actor and value["member"]["actor_id"] != args.actor:
                continue
            if target.parent.resolve() != target.parent or target.is_symlink():
                raise ValueError("Noncanonical engine target")
            current = hashlib.sha256(target.read_bytes()).hexdigest()
            if current == args.sha256 and value["source"]["binary_sha256"] == args.sha256:
                continue
            if current != value["source"]["binary_sha256"]:
                raise ValueError("Installed engine has changed")
            if path.with_name(path.name + backup_suffix).exists():
                raise ValueError("A prior terminal activation needs inspection")
            plans.append((path, raw, value, target))
    print(
        json.dumps({"status": "PLAN", "hosts": len(plans), "binary_sha256": args.sha256}),
        flush=True,
    )
    if not args.apply:
        return
    for path, raw, value, target in plans:
        for database in Path(value["paths"]["state"]).glob("**/*.db"):
            if database.is_symlink() or database.parent.resolve() != database.parent:
                raise ValueError("Noncanonical database path")
            backup = database.with_name(database.name + backup_suffix)
            if backup.exists():
                raise ValueError("Database backup already exists; inspect before retry")
            source = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
            destination = sqlite3.connect(backup)
            try:
                source.backup(destination)
            finally:
                source.close()
                destination.close()
            info = database.stat()
            os.chown(backup, info.st_uid, info.st_gid)
            backup.chmod(0o600)
        path.with_name(path.name + backup_suffix).write_bytes(raw)
        fd, temp = tempfile.mkstemp(dir=target.parent)
        os.close(fd)
        os.unlink(temp)
        os.link(binary, temp)
        os.replace(temp, target)
        value["source"].update(
            binary=str(binary),
            binary_sha256=args.sha256,
            artifact_root=str(artifact),
            source_commit=metadata["base_commit"],
            source_worktree_manifest=str(manifest),
            source_worktree_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        )
        fd, temp = tempfile.mkstemp(dir=path.parent)
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o644)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    for _, _, value, _ in plans:
        unit = value["unit_name"]
        if subprocess.run(["systemctl", "is-active", "--quiet", unit]).returncode == 0:
            subprocess.run(["systemctl", "restart", unit], check=True)
    print(json.dumps({"status": "APPLIED", "hosts": len(plans), "artifact": str(artifact)}))


if __name__ == "__main__":
    main()
