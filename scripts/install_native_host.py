"""Plan or install a new personal native HTTP host; never start or switch it.

Uses the existing compiled QuantCode CLI, enrolled Linux research accounts and
Python organization services. Default mode reads sources and metadata only.
--apply requires the exact printed plan digest, creates new versioned paths and
writes an independent systemd unit, without running systemctl or any runtime.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import stat
import sys
from urllib.parse import urlparse

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from quantcode.identity import fingerprint_of_public_key  # noqa: E402
from quantcode.remote_mcp import trusted_path  # noqa: E402
from schemas.evidence_chain import canonical_json, sha256_hex  # noqa: E402
from schemas.groups import GROUP_IDS  # noqa: E402

SOURCE_DIRS = ("quantcode", "runner", "schemas", "tools", "flows", "configs", ".opencode", "dream")
SOURCE_FILES = ("pyproject.toml", "uv.lock", "LICENSE")


def absolute(path: Path) -> Path:
    if not path.is_absolute() or path.resolve() != path or any(char in str(path) for char in '\r\n\x00"\\%$'):
        raise ValueError("host paths must be canonical absolute paths without shell/systemd substitutions")
    return path


def new_target(path: Path) -> Path:
    absolute(path)
    if path.exists() or path.is_symlink():
        raise FileExistsError("installation destination already exists; do not overwrite a prior host")
    parent = path.parent
    while not parent.exists():
        parent = parent.parent
    trusted_path(parent)
    return path


def file_digest(path: Path) -> str:
    trusted_path(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("native host source must be a regular file")
        digest = hashlib.sha256()
        while chunk := handle.read(1_048_576):
            digest.update(chunk)
        after, linked = os.fstat(handle.fileno()), path.lstat()
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                or (linked.st_dev, linked.st_ino, linked.st_mtime_ns, linked.st_ctime_ns) !=
                (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError("native host source changed during inspection")
        return digest.hexdigest()


def enrolled_member(roster: dict, registry: dict, actor: str, fingerprint: str, user, group_ids: list[int]) -> dict:
    """Match an existing provision_research_accounts enrollment, never adopt it."""
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,28}", actor) or roster.get("status") == "REVIEW_REQUIRED":
        raise ValueError("an explicitly selected approved actor is required")
    saved = registry.get("accounts", {}).get(actor)
    if (not isinstance(saved, dict) or user.pw_uid == 0 or saved.get("uid") != user.pw_uid
            or saved.get("gid") != user.pw_gid or saved.get("username") != user.pw_name
            or user.pw_name != f"qc-{actor}" or saved.get("workspace_path") != user.pw_dir
            or set(group_ids) != {user.pw_gid} or fingerprint not in saved.get("fingerprints", [])):
        raise PermissionError("the existing Linux account does not match its approved enrollment")
    entries = [entry for entry in roster.get("bindings", []) if entry.get("actor_id") == actor]
    matching = [entry for entry in entries if entry.get("fingerprint") == fingerprint]
    if len(matching) != 1 or not entries:
        raise ValueError("select one exact registered public key for the personal native host")
    if (set(saved.get("fingerprints", [])) != {entry.get("fingerprint") for entry in entries}
            or {entry.get("workspace_path") for entry in entries} != {user.pw_dir}
            or len({entry.get("workspace_id") for entry in entries}) != 1):
        raise PermissionError("roster keys or workspace changed since Linux account enrollment")
    entry = matching[0]
    group = entry.get("group")
    groups = entry.get("groups") or [group]
    if (group not in GROUP_IDS or group not in groups or any(item not in GROUP_IDS for item in groups)
            or entry.get("role") not in {"analyst", "approver", "admin"}
            or not isinstance(entry.get("workspace_id"), str) or not entry["workspace_id"]):
        raise ValueError("selected roster record lacks a valid group, role or workspace")
    key = str(entry.get("public_key", "")).strip()
    parts = key.split()
    if len(parts) < 2 or "PRIVATE KEY" in key or "\n" in key or "\r" in key:
        raise ValueError("the enrollment must contain an OpenSSH public key")
    # Roster provisioning already verifies the key with normalize_public_key
    # and OpenSSH. Repeat only the existing pure fingerprint check here;
    # normalize_public_key would create temp files/execute ssh-keygen in plan.
    if not parts[0].startswith(("ssh-", "ecdsa-", "sk-")) or fingerprint_of_public_key(key) != fingerprint:
        raise ValueError("public key does not match the approved fingerprint")
    return {"actor_id": actor, "username": user.pw_name, "uid": user.pw_uid, "gid": user.pw_gid,
            "workspace_path": user.pw_dir, "workspace_id": entry["workspace_id"], "group": group,
            "role": entry["role"], "fingerprint": fingerprint, "public_key": " ".join(parts[:2])}


def authorized_public_keys(workspace: Path, uid: int) -> dict[str, str]:
    """Read a member-writable key file without following substituted parents."""
    root = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    ssh = None
    try:
        ssh = os.open(".ssh", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        directory = os.fstat(ssh)
        if directory.st_uid != uid or directory.st_mode & 0o077:
            raise PermissionError("enrolled SSH directory ownership or privacy changed")
        descriptor = os.open("authorized_keys", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=ssh)
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != uid or before.st_mode & 0o077
                    or before.st_nlink != 1 or before.st_size > 262144):
                raise PermissionError("enrolled SSH authorized_keys ownership or privacy changed")
            raw = handle.read(262145)
            after = os.fstat(handle.fileno())
            linked = os.stat("authorized_keys", dir_fd=ssh, follow_symlinks=False)
            ssh_link = os.stat(".ssh", dir_fd=root, follow_symlinks=False)
            if (len(raw) > 262144 or (directory.st_dev, directory.st_ino) != (ssh_link.st_dev, ssh_link.st_ino)
                    or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                       (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    or (linked.st_dev, linked.st_ino, linked.st_mtime_ns, linked.st_ctime_ns) !=
                       (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns)):
                raise PermissionError("enrolled authorized_keys changed during inspection")
        try:
            keys = [line for line in raw.decode().splitlines() if line.strip() and not line.startswith("#")]
            if any(len(line.split()) < 2 for line in keys):
                raise ValueError("public key line required")
            return {fingerprint_of_public_key(line): " ".join(line.split()[:2]) for line in keys}
        except (ValueError, UnicodeError):
            raise ValueError("enrolled authorized_keys contains an invalid public key") from None
    finally:
        if ssh is not None:
            os.close(ssh)
        os.close(root)


def source_inventory(root: Path) -> dict[str, str]:
    trusted_path(absolute(root))
    if (root / ".quantcode").exists() or (root / ".quantcode").is_symlink() or (root / ".opencode/authorized_groups.yaml").exists():
        raise ValueError("runtime source release must not contain member credentials, runtime state or a roster")
    result = {}
    for name in SOURCE_DIRS:
        directory = trusted_path(root / name)
        if not directory.is_dir():
            raise ValueError("organization source release is incomplete")
        for item in sorted(directory.rglob("*")):
            if "__pycache__" in item.parts or item.suffix == ".pyc":
                continue
            trusted_path(item)
            if item.is_file():
                result[item.relative_to(root).as_posix()] = file_digest(item)
            elif not item.is_dir():
                raise ValueError("organization source contains a non-regular path")
    for name in SOURCE_FILES:
        result[name] = file_digest(root / name)
    # Reuse the already installed immutable Python environment. Never pip/uv
    # install or execute imports during planning or apply.
    venv = trusted_path(root / ".venv")
    for directory, names, files in os.walk(venv):
        for name in [*names, *files]:
            trusted_path((Path(directory) / name).resolve())
    result[".venv/pyvenv.cfg"] = file_digest(venv / "pyvenv.cfg")
    interpreter = trusted_path((venv / "bin/python").resolve())
    if not interpreter.is_file() or not interpreter.stat().st_mode & 0o111:
        raise ValueError("the reviewed Python environment has no executable interpreter")
    result[".venv/interpreter-sha256"] = file_digest(interpreter)
    return result


def artifact_inventory(root: Path, binary: Path) -> dict[str, dict]:
    """Keep the entire reviewed bin payload used by the existing release tar."""
    trusted_path(absolute(root))
    if binary.parent != root or not re.fullmatch(r"[A-Za-z0-9._-]+", binary.name):
        raise ValueError("compiled CLI must be a direct file of its explicit artifact bin directory")
    if (root / ".git").exists() or (root / ".quantcode").exists():
        raise ValueError("artifact root must contain build outputs, not a checkout or runtime state")
    result = {}
    for item in sorted(root.rglob("*")):
        trusted_path(item)
        if item.is_file():
            result[item.relative_to(root).as_posix()] = {"sha256": file_digest(item),
                                                       "executable": bool(item.stat().st_mode & 0o111)}
        elif not item.is_dir():
            raise ValueError("compiled artifact contains an unsupported path")
    if binary.name not in result:
        raise ValueError("compiled CLI is absent from the artifact manifest")
    return result


def build_plan(args: argparse.Namespace) -> dict:
    if sys.platform != "linux":
        raise PermissionError("native research host installation targets the existing Linux research accounts")
    import pwd
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", args.release):
        raise ValueError("release must be a short explicit version identifier")
    if not re.fullmatch(r"[a-f0-9]{64}", args.binary_sha256) or not re.fullmatch(r"[a-f0-9]{40,64}", args.source_commit):
        raise ValueError("reviewed binary SHA-256 and source commit are required")
    if not 1024 <= args.port <= 65535:
        raise ValueError("an explicit unprivileged loopback port is required")
    gateway = urlparse(args.gateway)
    if (not gateway.hostname or any(char in args.gateway for char in '\r\n\x00"\\%$')
            or not re.fullmatch(r"[A-Za-z0-9.:-]+", gateway.hostname)
            or gateway.username or gateway.password or gateway.query or gateway.fragment or gateway.path not in {"", "/"}
            or (gateway.scheme != "https" and not (gateway.scheme == "http" and gateway.hostname in {"127.0.0.1", "localhost", "::1"}))):
        raise ValueError("gateway requires HTTPS or a loopback HTTP origin")
    roster_file, registry_file = trusted_path(absolute(args.roster)), trusted_path(absolute(args.registry))
    if roster_file.stat().st_mode & 0o077 or registry_file.stat().st_mode & 0o077:
        raise PermissionError("approved roster and research registry must remain root-private")
    roster = yaml.safe_load(roster_file.read_text(encoding="utf-8"))
    registry = json.loads(registry_file.read_text(encoding="utf-8"))
    user = pwd.getpwnam(f"qc-{args.actor}")
    member = enrolled_member(roster, registry, args.actor, args.fingerprint, user, os.getgrouplist(user.pw_name, user.pw_gid))
    workspace = absolute(Path(member["workspace_path"]))
    info = workspace.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != member["uid"] or info.st_mode & 0o077:
        raise PermissionError("enrolled research workspace ownership or privacy changed")
    trusted_path(workspace.parent)
    keys = authorized_public_keys(workspace, member["uid"])
    if set(keys) != set(registry["accounts"][args.actor]["fingerprints"]) or keys[args.fingerprint] != member["public_key"]:
        raise PermissionError("SSH authorized_keys differs from the registered identities")
    binary = trusted_path(absolute(args.binary))
    artifacts = artifact_inventory(args.artifact_root, binary)
    if file_digest(binary) != args.binary_sha256 or not binary.stat().st_mode & 0o111:
        raise ValueError("compiled CLI differs from the reviewed executable")
    with binary.open("rb") as handle:
        header = handle.read(20)
    architecture = {"x86_64": 62, "aarch64": 183}.get(platform.machine())
    if (len(header) < 20 or header[:6] != b"\x7fELF\x02\x01" or architecture is None
            or int.from_bytes(header[18:20], "little") != architecture):
        raise ValueError("provide a prebuilt native Linux CLI for this host architecture")
    inventory = source_inventory(args.runtime_root)
    cli_license = trusted_path(absolute(args.cli_license or args.runtime_root / "frontend/LICENSE"))
    cli_license_digest = file_digest(cli_license)
    for base in (args.install_root, args.state_root, args.units_root):
        absolute(base)
        if base == workspace.parent or base.is_relative_to(workspace.parent) or workspace.parent.is_relative_to(base):
            raise ValueError("native host code and control roots must be separate from the research tree")
    isolated = [args.runtime_root, args.install_root, args.state_root, args.units_root]
    if any(left.is_relative_to(right) or right.is_relative_to(left)
           for index, left in enumerate(isolated) for right in isolated[index + 1:]):
        raise ValueError("source, installation, control and unit roots must not overlap")
    if any(args.artifact_root.is_relative_to(base) or base.is_relative_to(args.artifact_root)
           for base in (args.install_root, args.state_root, args.units_root)):
        raise ValueError("reviewed artifact root must not overlap installation destinations")
    release_dir = new_target(args.install_root / args.actor / args.release)
    state_dir = new_target(args.state_root / args.actor / args.release)
    unit_name = f"quantcode-native-{args.actor}-{args.release}.service"
    unit = new_target(args.units_root / unit_name)
    trusted_path(args.units_root)
    # Installed manifests reserve ports even while their units are stopped.
    if args.install_root.exists():
        trusted_path(args.install_root)
        for manifest in args.install_root.glob("*/*/native-host.json"):
            previous = json.loads(trusted_path(manifest).read_text())
            if previous.get("port") == args.port:
                raise ValueError("loopback port is reserved by another installed native host")
    for filename in ("/proc/net/tcp", "/proc/net/tcp6"):
        for line in Path(filename).read_text().splitlines()[1:]:
            fields = line.split()
            if len(fields) > 3 and fields[3] == "0A" and int(fields[1].rsplit(":", 1)[1], 16) == args.port:
                raise ValueError("selected port is already listening; choose an unused isolated port")
    return {"version": 1, "mode": "prepare_only", "release": args.release, "port": args.port,
            "member": member, "gateway": args.gateway.rstrip("/"),
            "source": {"runtime_root": str(args.runtime_root), "binary": str(binary), "binary_sha256": args.binary_sha256,
                       "source_commit": args.source_commit, "files": inventory,
                       "cli_license": str(cli_license), "cli_license_sha256": cli_license_digest,
                       "artifact_root": str(args.artifact_root), "binary_name": binary.name, "artifacts": artifacts},
            "inputs": {"roster_sha256": file_digest(roster_file), "registry_sha256": file_digest(registry_file)},
            "paths": {"release": str(release_dir), "state": str(state_dir), "unit": str(unit),
                      "password_file": str(release_dir / "access.env")},
            "unit_name": unit_name, "execution": "not_started", "catalog": "not_published", "model": "not_configured"}


def host_environment(plan: dict) -> dict[str, str]:
    release, state = Path(plan["paths"]["release"]), Path(plan["paths"]["state"])
    backend = release / "backend"
    return {"OPENCODE_CHANNEL": "quantcode", "QUANTCODE_UNIFIED_RUNTIME": "1", "OPENCODE_SERVER_USERNAME": "quantcode",
            "PATH": "/usr/bin:/bin", "HOME": plan["member"]["workspace_path"], "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1", "QUANTCODE_ENV": "production", "QUANTCODE_SHARED_MEMORY": "gateway",
            "XDG_CONFIG_HOME": str(state / "config"), "XDG_DATA_HOME": str(state / "data"),
            "XDG_STATE_HOME": str(state / "state"), "XDG_CACHE_HOME": str(state / "cache"), "TMPDIR": str(state / "tmp"),
            "QUANTCODE_HOST_PYTHON": str(backend / ".venv/bin/python"), "QUANTCODE_BACKEND_ROOT": str(backend),
            "QUANTCODE_PUBLIC_KEY_FILE": str(release / "identity.pub"), "QUANTCODE_GATEWAY_URL": plan["gateway"],
            "QUANTCODE_IDENTITY_SESSION_FILE": str(state / "identity/session.json"),
            "QUANTCODE_GITHUB_CREDENTIALS_FILE": str(state / "github/credentials.json"),
            "QUANTCODE_WORKSPACES_FILE": str(state / "config/quantcode/workspaces.json"),
            "QUANTCODE_TOOL_CATALOG_FILE": str(state / "config/quantcode/tool-catalog.json"),
            "QUANTCODE_DISTILL_CANDIDATES_DIR": str(state / "knowledge/candidates"),
            "QUANTCODE_DISTILL_PUBLISH_ROOT": str(state / "knowledge/published"),
            "QUANTCODE_LEGACY_CHECKPOINTS_DB": str(state / "python/checkpoints.db"),
            "QUANTCODE_LEGACY_PROVENANCE_FILE": str(state / "python/legacy-provenance.json")}


def render_unit(plan: dict) -> str:
    member = plan["member"]
    release, state = plan["paths"]["release"], plan["paths"]["state"]
    return "\n".join([
        "[Unit]", "Description=QuantCode personal native research host", "After=network-online.target", "",
        "[Service]", "Type=simple", f"User={member['username']}", f"Group={member['gid']}",
        f'WorkingDirectory={member["workspace_path"]}', f'EnvironmentFile={release}/host.env',
        f'EnvironmentFile={release}/access.env',
        f'ExecStart="{release}/bin/{plan["source"]["binary_name"]}" serve --hostname 127.0.0.1 --port {plan["port"]} --no-mdns --cors oc://renderer',
        "Restart=no", "KillMode=control-group", "TimeoutStopSec=10", "UMask=0077", "NoNewPrivileges=true",
        "ProtectSystem=strict", "ProtectHome=read-only", "PrivateTmp=true", "RestrictSUIDSGID=true",
        f'ReadWritePaths="{member["workspace_path"]}" "{state}"', "RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX",
        "", "[Install]", "WantedBy=multi-user.target", "",
    ])


def write_new(path: Path, data: bytes, mode: int, *, uid: int = 0, gid: int = 0) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(descriptor, "wb") as handle:
        os.fchown(handle.fileno(), uid, gid)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def apply_plan(args: argparse.Namespace, expected: str) -> dict:
    if os.geteuid() != 0 or sys.platform != "linux":
        raise PermissionError("only the Linux administrator may prepare a native host installation")
    if not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise ValueError("apply requires the exact reviewed plan digest")
    if sha256_hex(canonical_json(build_plan(args))) != expected:
        raise ValueError("native host plan changed; no installation paths were created")
    from runner.execution_lock import execution_lock
    # Shared installer lock only; never a task execution scheduler.
    args.install_root.mkdir(parents=True, exist_ok=True, mode=0o755)
    trusted_path(args.install_root)
    with execution_lock(args.install_root / "native-installs.json", "install-native-host"):
        plan = build_plan(args)
        if sha256_hex(canonical_json(plan)) != expected:
            raise ValueError("native host plan changed; inspect a new plan before applying")
        release, state = Path(plan["paths"]["release"]), Path(plan["paths"]["state"])
        member = plan["member"]
        release.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        state.parent.mkdir(parents=True, exist_ok=True, mode=0o711)
        trusted_path(release.parent)
        trusted_path(state.parent)
        release.mkdir(mode=0o755)
        state.mkdir(mode=0o700)
        os.chown(state, member["uid"], member["gid"])
        for name in ("config", "config/quantcode", "data", "state", "cache", "tmp", "identity", "github", "python", "knowledge", "knowledge/candidates", "knowledge/published"):
            directory = state / name
            directory.mkdir(mode=0o700)
            os.chown(directory, member["uid"], member["gid"])
        (release / "bin").mkdir(mode=0o755)
        for relative, artifact in plan["source"]["artifacts"].items():
            destination = release / "bin" / relative
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            shutil.copyfile(args.artifact_root / relative, destination, follow_symlinks=False)
            destination.chmod(0o755 if artifact["executable"] else 0o644)
            if file_digest(destination) != artifact["sha256"]:
                raise ValueError("compiled artifact changed during installation; new unit has not been installed")
        backend = release / "backend"
        backend.mkdir(mode=0o755)
        for name in SOURCE_DIRS:
            (backend / name).mkdir(mode=0o755)
        for relative, expected_file in plan["source"]["files"].items():
            if relative.startswith(".venv/"):
                continue
            destination = backend / relative
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            shutil.copyfile(args.runtime_root / relative, destination, follow_symlinks=False)
            destination.chmod(0o755 if (args.runtime_root / relative).stat().st_mode & 0o111 else 0o644)
            if file_digest(destination) != expected_file:
                raise ValueError("source changed during installation; new unit has not been installed")
        (backend / ".venv").symlink_to(args.runtime_root / ".venv")
        shutil.copyfile(plan["source"]["cli_license"], release / "OPEN_CODE_LICENSE", follow_symlinks=False)
        if file_digest(release / "OPEN_CODE_LICENSE") != plan["source"]["cli_license_sha256"]:
            raise ValueError("compiled CLI license changed during installation")
        # Same per-user source view used by install_remote_mcp, with state
        # moved outside the model-writable research directory.
        (backend / ".quantcode").symlink_to(state / "python")
        write_new(release / "identity.pub", (member["public_key"] + "\n").encode(), 0o644)
        env = host_environment(plan)
        write_new(release / "host.env", "".join(f'{key}="{value}"\n' for key, value in env.items()).encode(), 0o600)
        write_new(release / "access.env", f"OPENCODE_SERVER_PASSWORD={secrets.token_urlsafe(48)}\n".encode(), 0o600)
        mcp = {"type": "local", "enabled": True, "command": [env["QUANTCODE_HOST_PYTHON"], "-I", "-B", "-c",
               "import sys; sys.path.insert(0, sys.argv[1]); from quantcode.mcp_server import main; main()", str(backend)],
               "cwd": str(backend), "environment": {key: value for key, value in env.items() if key.startswith("QUANTCODE_") or key in {"OPENCODE_CHANNEL", "PYTHONDONTWRITEBYTECODE"}}}
        write_new(state / "config/quantcode/opencode.json", (json.dumps({"mcp": {"quantcode": mcp}}, indent=2) + "\n").encode(),
                  0o600, uid=member["uid"], gid=member["gid"])
        manifest = {key: value for key, value in plan.items() if key != "member"}
        manifest["member"] = {key: value for key, value in member.items() if key != "public_key"}
        manifest["plan_digest"] = expected
        manifest["installed_at"] = datetime.now(timezone.utc).isoformat()
        write_new(release / "native-host.json", (json.dumps(manifest, indent=2) + "\n").encode(), 0o644)
        # Unit is installed last. No daemon-reload, start, enable or pointer
        # switch occurs here, including on success. Partial new dirs remain for
        # inspection on failure; no pre-existing host is removed or modified.
        write_new(Path(plan["paths"]["unit"]), render_unit(plan).encode(), 0o644)
        return {"status": "INSTALLED_NOT_STARTED", "unit": plan["unit_name"], "plan_digest": expected,
                "actor_id": args.actor, "url": f"http://127.0.0.1:{args.port}",
                "password_file": plan["paths"]["password_file"], "source_commit": args.source_commit,
                "catalog": "not_published", "model": "not_configured", "execution": "not_started"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True, help="Complete reviewed build output bin directory")
    parser.add_argument("--binary-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--cli-license", type=Path, help="Original incorporated CLI license; defaults to runtime-root/frontend/LICENSE")
    parser.add_argument("--release", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--fingerprint", required=True)
    parser.add_argument("--gateway", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--registry", type=Path, default=Path("/etc/quantcode/research-identities.json"))
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--install-root", type=Path, default=Path("/opt/quantcode/native-hosts"))
    parser.add_argument("--state-root", type=Path, default=Path("/var/lib/quantcode-native"))
    parser.add_argument("--units-root", type=Path, default=Path("/etc/systemd/system"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-plan")
    args = parser.parse_args()
    if args.apply:
        if not args.expected_plan:
            parser.error("--apply requires --expected-plan from the reviewed plan")
        result = apply_plan(args, args.expected_plan)
    else:
        plan = build_plan(args)
        result = {"status": "PLAN", "plan_digest": sha256_hex(canonical_json(plan)),
                  **{key: value for key, value in plan.items() if key not in {"member", "source"}},
                  "member": {key: value for key, value in plan["member"].items() if key != "public_key"},
                  "source": {key: value for key, value in plan["source"].items() if key not in {"files", "artifacts"}},
                  "artifact_files": len(plan["source"]["artifacts"]),
                  "source_files": len(plan["source"]["files"]), "unit_preview": render_unit(plan)}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
