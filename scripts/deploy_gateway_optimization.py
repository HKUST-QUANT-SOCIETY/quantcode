"""Activate reviewed gateway performance changes in a new runtime tree."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    manifest = (args.bundle / "manifest.json").read_bytes()
    if os.geteuid() != 0 or hashlib.sha256(manifest).hexdigest() != args.manifest_sha256:
        raise ValueError("Use sudo with the reviewed manifest digest")
    hashes = json.loads(manifest)
    if set(hashes) != {"quantcode/gateway.py", "quantcode/identity.py"}:
        raise ValueError("Unexpected gateway bundle scope")
    patches = {name: (args.bundle / name).read_bytes() for name in hashes}
    if any(hashlib.sha256(raw).hexdigest() != hashes[name] for name, raw in patches.items()):
        raise ValueError("Gateway source differs from its reviewed digest")
    base = Path("/opt/quantcode-test-v1/runtime/feature-continuity-20260910")
    runtime = base.parent / "optimization-20260913"
    unit = "quantcode-test-v1-gateway.service"
    busy = []
    for prefix in ["/opt/quantcode-test-v1/native-hosts", "/opt/quantcode-admin/native-hosts"]:
        for path in Path(prefix).glob("*/*/native-host.json"):
            host = json.loads(path.read_text())
            cgroup = Path("/sys/fs/cgroup/system.slice") / host["unit_name"] / "cgroup.procs"
            pids = cgroup.read_text().split() if cgroup.exists() else []
            for database in Path(host["paths"]["state"]).glob("data/*/*.db"):
                with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
                    rows = db.execute("""SELECT e.data FROM event e JOIN
                        (SELECT aggregate_id,MAX(seq) seq FROM event WHERE type='quantcode.execution.changed.1' GROUP BY aggregate_id) last
                        ON e.aggregate_id=last.aggregate_id AND e.seq=last.seq WHERE e.type='quantcode.execution.changed.1'""").fetchall()
                if any((record := json.loads(row[0])).get("status") != "idle" and str(record.get("pid")) in pids for row in rows):
                    busy.append(host["unit_name"])
    print(json.dumps({"status": "PLAN", "runtime": str(runtime), "busy_hosts": busy}), flush=True)
    if not args.apply:
        return
    if busy:
        raise ValueError("Wait for active member tasks before restarting the identity gateway")
    if runtime.exists():
        raise ValueError("Activation directory already exists; inspect before retry")
    shutil.copytree(base, runtime, copy_function=os.link, symlinks=True, ignore=shutil.ignore_patterns("__pycache__"))
    for name, raw in patches.items():
        target = runtime / name
        temporary = target.with_suffix(".py.new")
        temporary.write_bytes(raw)
        temporary.chmod(0o644)
        os.replace(temporary, target)
    (runtime / "optimization-build.json").write_bytes(manifest)
    database = Path("/var/lib/quantcode-test-v1/gateway/gateway.db")
    backup = database.with_name("gateway.db.before-optimization-20260913")
    if backup.exists():
        raise ValueError("Gateway backup already exists")
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as original, sqlite3.connect(backup) as saved:
        original.backup(saved)
    backup.chmod(0o600)
    dropin = Path("/etc/systemd/system") / (unit + ".d/99-optimization.conf")
    if dropin.exists():
        raise ValueError("Gateway activation already exists")
    dropin.parent.mkdir(parents=True, exist_ok=True)
    dropin.write_text(f"[Service]\nWorkingDirectory={runtime}\nExecStart=\nExecStart={runtime}/.venv/bin/python -B -m quantcode.gateway --roster /var/lib/quantcode-test-v1/gateway/roster.yaml --database {database} --port 5098 --github-sync-interval 0 --dream-interval 0\n")
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "restart", unit], check=True)
    print(json.dumps({"status": "APPLIED", "runtime": str(runtime), "backup": str(backup)}))


if __name__ == "__main__":
    main()
