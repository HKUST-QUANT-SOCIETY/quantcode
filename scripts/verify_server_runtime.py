"""Probe a staged Linux runtime inside its actual systemd sandbox.

This checks dependencies, filesystem isolation and unauthenticated MCP startup.
It does not certify authenticated research, shared Memory or a production rollout.
"""
from __future__ import annotations

import argparse
import errno
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--deny-read", type=Path, action="append", default=[])
    args = parser.parse_args()
    if any(not path.is_absolute() for path in [args.runtime_root, args.state_root, *args.deny_read]):
        parser.error("all probe paths must be absolute")
    if not sys.platform.startswith("linux"):
        parser.error("the deployed Linux sandbox must run this probe")

    checks: list[dict] = []

    def record(name: str, passed: bool, **details) -> None:
        checks.append({"check": name, "passed": passed, **details})

    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    record("unprivileged_uid", os.geteuid() != 0)
    record("no_new_privileges", status.get("NoNewPrivs", "").strip() == "1")
    record("no_effective_capabilities", int(status.get("CapEff", "1").strip(), 16) == 0)
    record("python_version", sys.version_info >= (3, 12), version=sys.version.split()[0])

    for module, distribution in [
        ("pydantic", "pydantic"), ("langgraph.graph", "langgraph"),
        ("langgraph.checkpoint.sqlite", "langgraph-checkpoint-sqlite"),
        ("langchain_openai", "langchain-openai"), ("chromadb", "chromadb"),
        ("pyarrow", "pyarrow"), ("paramiko", "paramiko"),
    ]:
        try:
            importlib.import_module(module)
            record(f"import:{module}", True, version=importlib.metadata.version(distribution))
        except Exception as exc:
            record(f"import:{module}", False, error=type(exc).__name__)

    try:
        with tempfile.TemporaryDirectory(prefix="runtime-probe-", dir=args.state_root) as directory:
            path = Path(directory) / "owned-state"
            path.write_bytes(b"quantcode-runtime-probe")
            record("private_state_writable", path.read_bytes() == b"quantcode-runtime-probe")
    except OSError as exc:
        record("private_state_writable", False, error=type(exc).__name__)

    try:
        with tempfile.TemporaryDirectory(prefix="runtime-probe-", dir=args.runtime_root):
            record("runtime_code_read_only", False)
    except OSError as exc:
        record("runtime_code_read_only", exc.errno in {errno.EACCES, errno.EPERM, errno.EROFS})

    for path in args.deny_read:
        try:
            descriptor = os.open(path, os.O_RDONLY)
        except OSError as exc:
            record(f"read_denied:{path}", exc.errno in {errno.EACCES, errno.EPERM})
        else:
            os.close(descriptor)
            record(f"read_denied:{path}", False)

    # A subprocess observes the deployed dependency graph and environment from
    # scratch. Do not use inherited credentials when probing authentication.
    env = {name: value for name, value in os.environ.items() if not name.startswith("QUANTCODE_")}
    env.update(QUANTCODE_ENV="production", PYTHONPATH=str(args.runtime_root))
    try:
        result = subprocess.run(
            [sys.executable, "-m", "quantcode.mcp_server"], env=env, cwd=args.runtime_root,
            input="", capture_output=True, text=True, timeout=30,
        )
        record("unauthenticated_mcp_denied", result.returncode != 0 and "AUTHENTICATION_REQUIRED" in result.stderr)
    except (OSError, subprocess.SubprocessError) as exc:
        record("unauthenticated_mcp_denied", False, error=type(exc).__name__)

    passed = all(check["passed"] for check in checks)
    print(json.dumps({"status": "PASS" if passed else "FAIL", "scope": "isolated_runtime_preflight", "checks": checks}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
