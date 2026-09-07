"""Server C SSH entrypoint for one authenticated, sandboxed research MCP process.

Installed code and enrollment/config files are administrator-owned. The wire
header carries only a short-lived token and expected session id, never a path,
command, Unix user, group override or private key.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import tempfile
import time
import uuid

from quantcode.identity_login import read_session_file

CONFIG = Path("/opt/quantcode/ops/remote-runtime.json")
ENROLLMENTS = Path("/opt/quantcode/enrollments")


def trusted_path(path: Path) -> Path:
    if not path.is_absolute() or path.resolve() != path:
        raise PermissionError("administrator path must be absolute without symlinks")
    for item in [path, *path.parents]:
        info = item.stat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise PermissionError("runtime configuration must be administrator-owned")
    return path


def read_header(descriptor: int, *, timeout: float = 15) -> dict:
    deadline = time.monotonic() + timeout
    data = bytearray()
    while len(data) < 4096:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([descriptor], [], [], remaining)[0]:
            raise TimeoutError("remote identity header not received")
        byte = os.read(descriptor, 1)
        if not byte:
            raise ValueError("identity header incomplete")
        if byte == b"\n":
            header = json.loads(data)
            if (not isinstance(header, dict) or set(header) != {"version", "token", "session_id"}
                    or header["version"] != 1
                    or not isinstance(header["token"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,512}", header["token"])
                    or not isinstance(header["session_id"], str) or not re.fullmatch(r"[a-f0-9]{32}", header["session_id"])):
                raise ValueError("invalid remote identity header")
            return header
        data.extend(byte)
    raise ValueError("identity header too large")


def validate_binding(context: dict, enrollment: dict, *, uid: int, username: str, home: str, session_id: str) -> None:
    if uid == 0 or enrollment.get("uid") != uid or enrollment.get("username") != username:
        raise PermissionError("Unix identity is not enrolled")
    if (context.get("session_id") != session_id or context.get("actor_id") != enrollment.get("actor_id")
            or context.get("workspace_id") != enrollment.get("workspace_id")
            or context.get("workspace_path") != enrollment.get("workspace_path")
            or home != enrollment.get("workspace_path")):
        raise PermissionError("gateway session does not belong to this research account")


def private_directory(path: Path, uid: int, *, create: bool = False) -> Path:
    if create:
        path.mkdir(mode=0o700, exist_ok=True)
    info = path.stat()
    if path.resolve() != path or info.st_uid != uid or info.st_mode & 0o077 or not path.is_dir():
        raise PermissionError("research directory must be private and owned by the enrolled account")
    return path


def sandbox_command(root: Path, workspace: Path, credential: Path, unit: str, ttl: int) -> list[str]:
    return ["/usr/bin/systemd-run", "--user", "--quiet", "--wait", "--pipe", "--collect", f"--unit={unit}",
            "--property=NoNewPrivileges=yes", "--property=PrivateUsers=yes", "--property=ProtectSystem=strict",
            "--property=ProtectHome=read-only", "--property=InaccessiblePaths=/home /root", "--property=PrivateTmp=yes",
            "--property=RestrictSUIDSGID=yes", "--property=UMask=0077",
            "--property=KillMode=control-group", "--property=TimeoutStopSec=10", f"--property=RuntimeMaxSec={ttl}",
            "--property=MemoryMax=2G", "--property=TasksMax=128", "--property=CPUQuota=200%",
            f"--property=WorkingDirectory={workspace}", f"--property=ReadWritePaths={workspace}",
            "/usr/bin/env", "-i", "PATH=/usr/bin:/bin", f"HOME={workspace}", "LANG=C.UTF-8",
            "PYTHONDONTWRITEBYTECODE=1", "QUANTCODE_ENV=production", "QUANTCODE_SHARED_MEMORY=gateway",
            f"QUANTCODE_IDENTITY_SESSION_FILE={credential}",
            str(root / ".venv/bin/python"), "-I", "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); from quantcode.remote_mcp import serve_runtime; serve_runtime()", str(root)]


def serve_runtime() -> None:
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    if (os.geteuid() == 0 or status.get("NoNewPrivs", "").strip() != "1"
            or int(status.get("CapEff", "1").strip(), 16) != 0):
        raise PermissionError("research runtime requires an unprivileged sandbox")
    from quantcode.mcp_server import main
    main()


def serve() -> int:
    import pwd

    user = pwd.getpwuid(os.getuid())
    config = json.loads(trusted_path(CONFIG).read_text())
    enrollment = json.loads(trusted_path(ENROLLMENTS / f"{user.pw_uid}.json").read_text())
    root = trusted_path(Path(config["runtime_root"]) / "users" / str(user.pw_uid))
    if config["gateway"] != "http://127.0.0.1:4097":
        raise PermissionError("remote gateway must be the local identity authority")
    if os.getgrouplist(user.pw_name, user.pw_gid) != [user.pw_gid]:
        raise PermissionError("research account acquired additional Unix groups")
    runtime = private_directory(Path(f"/run/user/{user.pw_uid}"), user.pw_uid)
    header = read_header(sys.stdin.fileno())
    with tempfile.TemporaryDirectory(prefix="quantcode-session-", dir=runtime) as folder:
        credential = Path(folder) / "identity.json"
        descriptor = os.open(credential, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            json.dump({"gateway": config["gateway"], "token": header["token"]}, output)
        context = read_session_file(credential)
        validate_binding(context, enrollment, uid=user.pw_uid, username=user.pw_name, home=user.pw_dir,
                         session_id=header["session_id"])
        workspace = private_directory(Path(user.pw_dir), user.pw_uid)
        private_directory(workspace / ".quantcode", user.pw_uid, create=True)
        if not (root / ".quantcode").is_symlink() or (root / ".quantcode").resolve() != workspace / ".quantcode":
            raise PermissionError("runtime state is not mapped to the enrolled workspace")
        expiry = datetime.fromisoformat(context["expires_at"])
        ttl = int((expiry - datetime.now(timezone.utc)).total_seconds())
        if ttl < 1:
            raise PermissionError("session expired")
        unit = "quantcode-mcp-" + uuid.uuid4().hex
        command = sandbox_command(root, workspace, credential, unit, ttl)
        env = {"PATH": "/usr/bin:/bin", "HOME": user.pw_dir, "LANG": "C.UTF-8", "XDG_RUNTIME_DIR": str(runtime),
               "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime}/bus"}
        previous = {}

        def stop(_signum, _frame):
            raise InterruptedError("SSH channel closed")

        for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            previous[sig] = signal.signal(sig, stop)
        try:
            with subprocess.Popen(command, env=env) as process:
                try:
                    return process.wait()
                finally:
                    subprocess.run(["/usr/bin/systemctl", "--user", "stop", unit], env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def main() -> int:
    try:
        return serve()
    except Exception as exc:
        print(f"Remote MCP denied ({type(exc).__name__}); verify gateway identity and research enrollment", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
