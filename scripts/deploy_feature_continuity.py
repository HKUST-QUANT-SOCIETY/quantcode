"""Roll out the reviewed knowledge fixes while retaining previous runtime trees."""

from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

RELEASE = "feature-continuity-20260910"
BASE = Path("/opt/quantcode-test-v1/runtime/test-v1-20260909-02")
FILES = [
    "quantcode/gateway.py",
    "quantcode/shared_knowledge.py",
    "quantcode/knowledge_host.py",
    "runner/memory/service.py",
    "runner/distill/cards.py",
]


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def atomic(path, data, mode=0o644, uid=0, gid=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.resolve() != path.parent or path.is_symlink():
        raise ValueError("Deployment path is not canonical")
    if uid:
        program = """import os,sys,tempfile
from pathlib import Path
p=Path(sys.argv[1]); assert p.parent.resolve()==p.parent and not p.is_symlink()
fd,tmp=tempfile.mkstemp(dir=p.parent)
try:
 with os.fdopen(fd,'wb') as f: os.fchmod(f.fileno(),int(sys.argv[2])); f.write(sys.stdin.buffer.read()); f.flush(); os.fsync(f.fileno())
 os.replace(tmp,p)
finally: Path(tmp).unlink(missing_ok=True)
"""
        import pwd

        subprocess.run(
            [
                "runuser",
                "-u",
                pwd.getpwuid(uid).pw_name,
                "--",
                "/usr/bin/python3",
                "-I",
                "-c",
                program,
                str(path),
                str(mode),
            ],
            input=data,
            check=True,
        )
        return
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            os.fchown(stream.fileno(), uid, gid)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    manifest = (args.bundle / "manifest.json").read_bytes()
    if hashlib.sha256(manifest).hexdigest() != args.manifest_sha256:
        raise ValueError("Bundle manifest changed")
    hashes = json.loads(manifest)
    patches = {name: (args.bundle / name).read_bytes() for name in FILES}
    if set(hashes) != set(FILES) or any(
        hashlib.sha256(raw).hexdigest() != hashes[name] for name, raw in patches.items()
    ):
        raise ValueError("Bundle files differ from the reviewed source")
    if os.geteuid() != 0:
        raise PermissionError("Run with sudo on Server C")
    hosts = []
    for base in ["/opt/quantcode-test-v1/native-hosts", "/opt/quantcode-admin/native-hosts"]:
        for item in Path(base).glob("*/*/native-host.json"):
            value = json.loads(item.read_text())
            state, release = Path(value["paths"]["state"]), item.parent
            config_path, catalog_path = (
                state / "config/quantcode/opencode.json",
                state / "config/quantcode/tool-catalog.json",
            )
            config, catalog = (
                json.loads(config_path.read_text()),
                json.loads(catalog_path.read_text()),
            )
            old = config["mcp"]
            backend = release / ("backend-" + RELEASE)

            def remap(item):
                if isinstance(item, dict):
                    return {key: remap(value) for key, value in item.items()}
                if isinstance(item, list):
                    return [remap(value) for value in item]
                prefix = str(release / "backend")
                if isinstance(item, str) and (item == prefix or item.startswith(prefix + "/")):
                    return str(backend) + item[len(prefix) :]
                return item

            new = remap(old)
            for entry in [*catalog.get("tools", []), *catalog.get("content", [])]:
                server = entry["server"]
                if server not in old:
                    continue
                previous = digest(old[server])
                if entry["status"] == "published" and entry["server_config_hash"] != previous:
                    raise ValueError(
                        "Published tool catalog differs from its approved configuration: "
                        + value["member"]["actor_id"]
                    )
                if entry["server_config_hash"] == previous:
                    entry["server_config_hash"] = digest(new[server])
            config["mcp"] = new
            candidates = state / "knowledge/candidates/index.json"
            if candidates.exists() and json.loads(candidates.read_text()).get("candidates"):
                raise ValueError(
                    "Existing candidates need a reviewed source migration before switching "
                    + value["member"]["actor_id"]
                )
            env = (
                (release / "host.env")
                .read_text()
                .replace(str(release / "backend") + "/", str(backend) + "/")
                .replace(
                    'QUANTCODE_BACKEND_ROOT="' + str(release / "backend") + '"',
                    'QUANTCODE_BACKEND_ROOT="' + str(backend) + '"',
                )
            )
            unit = value["unit_name"]
            active = subprocess.run(["systemctl", "is-active", "--quiet", unit]).returncode == 0
            hosts.append(
                (
                    value,
                    backend,
                    state,
                    release,
                    config_path,
                    config,
                    catalog_path,
                    catalog,
                    env,
                    active,
                )
            )
    print(
        json.dumps(
            {
                "status": "PLAN",
                "hosts": len(hosts),
                "active_hosts": sum(h[-1] for h in hosts),
                "runtime": RELEASE,
                "patches": FILES,
            }
        ),
        flush=True,
    )
    if not args.apply:
        return
    destination = BASE.parent / RELEASE
    if destination.exists():
        raise ValueError("Release already exists; inspect before retry")
    shutil.copytree(BASE, destination, symlinks=True, copy_function=os.link)
    for name, raw in patches.items():
        atomic(destination / name, raw)
    # Preserve a manifest of the exact source delta independently of the old
    # compiled engine provenance. Engine binaries are not replaced here.
    atomic(destination / "feature-continuity-manifest.json", manifest)
    for (
        value,
        backend,
        state,
        release,
        config_path,
        config,
        catalog_path,
        catalog,
        env,
        active,
    ) in hosts:
        shutil.copytree(release / "backend", backend, symlinks=True, copy_function=os.link)
        for name, raw in patches.items():
            atomic(backend / name, raw)
        for path, data in [(config_path, config), (catalog_path, catalog)]:
            old = path.read_bytes()
            backup = path.with_name(path.name + ".before-" + RELEASE)
            if backup.exists():
                raise ValueError("Backup already exists")
            info = path.stat()
            atomic(backup, old, 0o600, info.st_uid, info.st_gid)
            atomic(
                path,
                (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode(),
                0o600,
                info.st_uid,
                info.st_gid,
            )
        env_file = release / (RELEASE + ".env")
        atomic(env_file, env.encode())
        dropin = (
            Path("/etc/systemd/system") / (value["unit_name"] + ".d") / "95-feature-continuity.conf"
        )
        atomic(
            dropin,
            (
                "[Service]\nEnvironmentFile="
                + str(env_file)
                + "\nRestrictAddressFamilies=\nRestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK\n"
            ).encode(),
        )
    original = Path("/etc/systemd/system/quantcode-test-v1-gateway.service").read_text()
    command = next(
        line.split("=", 1)[1] for line in original.splitlines() if line.startswith("ExecStart=")
    )
    command = command.replace(str(BASE), str(destination))
    gateway_dropin = Path(
        "/etc/systemd/system/quantcode-test-v1-gateway.service.d/95-feature-continuity.conf"
    )
    atomic(
        gateway_dropin,
        (
            "[Service]\nWorkingDirectory="
            + str(destination)
            + "\nExecStart=\nExecStart="
            + command
            + "\n"
        ).encode(),
    )
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "restart", "quantcode-test-v1-gateway.service"], check=True)
    for value, *_, active in hosts:
        if active:
            subprocess.run(["systemctl", "restart", value["unit_name"]], check=True)
    print(json.dumps({"status": "APPLIED", "hosts": len(hosts), "source": str(destination)}))


if __name__ == "__main__":
    main()
