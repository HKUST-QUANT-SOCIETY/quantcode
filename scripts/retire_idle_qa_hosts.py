"""Stop old, idle QA hosts after SQLite backups; never delete their data."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess


PATTERN = re.compile(r"quantcode-native-(sim-[a-z]+-\d{6})-(e2e-(\d{8})-\d+)\.service")
ROOT = Path("/opt/quantcode-qa/native-hosts")
STATE = Path("/var/lib/quantcode-qa/native")
CGROUP = Path("/sys/fs/cgroup/system.slice")


def inspect(unit, before):
    match = PATTERN.fullmatch(unit)
    if not match or match[3] >= before:
        raise ValueError("Not an old QA unit")
    manifest = ROOT / match[1] / match[2] / "native-host.json"
    raw = manifest.read_bytes()
    value = json.loads(raw)
    state = Path(value["paths"]["state"])
    if value["unit_name"] != unit or state != STATE / match[1] / match[2] or state.resolve() != state:
        raise ValueError("QA manifest or state path changed")
    cgroup = CGROUP / unit
    pids = (cgroup / "cgroup.procs").read_text().split() if cgroup.exists() else []
    for pid in pids:
        try:
            command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
        except FileNotFoundError:
            continue
        if b"/bin/opencode serve " not in command and b"quantcode.mcp_server" not in command:
            raise ValueError("QA host has another live child process; inspect it before retirement")
    databases = sorted(path for path in state.rglob("*.db") if path.is_file())
    for database in databases:
        if database.is_symlink() or database.resolve() != database:
            raise ValueError("Noncanonical QA database")
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "event" not in tables:
                continue
            rows = db.execute("""SELECT e.data FROM event e JOIN
                (SELECT aggregate_id,MAX(seq) seq FROM event WHERE type='quantcode.execution.changed.1' GROUP BY aggregate_id) last
                ON e.aggregate_id=last.aggregate_id AND e.seq=last.seq
                WHERE e.type='quantcode.execution.changed.1'""").fetchall()
            for row in rows:
                execution = json.loads(row[0])
                if execution.get("status") != "idle" and str(execution.get("pid")) in pids:
                    raise ValueError("QA host still owns an active task")
    memory = int((cgroup / "memory.current").read_text()) if cgroup.exists() else 0
    return {"unit": unit, "manifest_sha256": hashlib.sha256(raw).hexdigest(), "state": str(state),
            "databases": [str(path) for path in databases], "memory_bytes": memory}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", default="20260913")
    parser.add_argument("--backup-root", type=Path, default=Path("/var/lib/quantcode-qa/maintenance/retire-20260913"))
    parser.add_argument("--expected-plan")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0 or not re.fullmatch(r"\d{8}", args.before):
        raise ValueError("Use sudo with a reviewed cutoff date")
    units = subprocess.check_output(["systemctl", "list-units", "--all", "--type=service", "--no-legend", "--plain", "quantcode-native-sim-*"], text=True)
    candidates, skipped = [], []
    for line in units.splitlines():
        unit = line.split()[0]
        try:
            candidates.append(inspect(unit, args.before))
        except (OSError, ValueError, sqlite3.Error) as error:
            skipped.append({"unit": unit, "reason": str(error)})
    signature = [{"unit": row["unit"], "manifest_sha256": row["manifest_sha256"]} for row in candidates]
    digest = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
    print(json.dumps({"status": "PLAN", "digest": digest, "units": len(candidates), "memory_mib": round(sum(row["memory_bytes"] for row in candidates) / 1048576, 1), "candidates": signature, "skipped": skipped}), flush=True)
    if not args.apply:
        return
    if args.expected_plan != digest:
        raise ValueError("Retirement plan changed")
    if args.backup_root.resolve() != args.backup_root or not args.backup_root.is_relative_to(STATE.parent / "maintenance"):
        raise ValueError("Backup directory must remain in QA maintenance storage")
    args.backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for row in candidates:
        current = inspect(row["unit"], args.before)
        if current["manifest_sha256"] != row["manifest_sha256"]:
            raise ValueError("QA host changed before retirement")
        backup = args.backup_root / row["unit"]
        backup.mkdir(mode=0o700, exist_ok=False)
        enabled = subprocess.run(["systemctl", "is-enabled", row["unit"]], capture_output=True, text=True).stdout.strip()
        (backup / "host.json").write_text(json.dumps({**row, "enabled_before": enabled}, indent=2))
        (backup / "host.json").chmod(0o600)
        for filename in row["databases"]:
            source = Path(filename)
            destination = backup / source.relative_to(row["state"])
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original, sqlite3.connect(destination) as saved:
                original.backup(saved)
            destination.chmod(0o600)
        subprocess.run(["systemctl", "disable", "--now", row["unit"]], check=True, capture_output=True)
        if subprocess.run(["systemctl", "is-active", "--quiet", row["unit"]]).returncode == 0:
            raise RuntimeError("QA unit remains active")
        print(json.dumps({"status": "STOPPED", "unit": row["unit"], "backup": str(backup)}), flush=True)


if __name__ == "__main__":
    main()
