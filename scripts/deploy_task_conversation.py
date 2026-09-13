"""Install the model admission receipt in a versioned runtime and pin native trust."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-source", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    source = args.model_source.read_bytes()
    if hashlib.sha256(source).hexdigest() != args.sha256 or os.geteuid() != 0:
        raise ValueError("Use sudo with the reviewed model source digest")
    base = Path("/opt/quantcode-test-v1/runtime/test-v1-20260909-03")
    runtime = base.parent / "task-conversation-20260911"
    targets = []
    for prefix in ["/opt/quantcode-test-v1/native-hosts", "/opt/quantcode-admin/native-hosts"]:
        for path in Path(prefix).glob("*/*/native-host.json"):
            host = json.loads(path.read_text())
            config = json.loads((Path(host["paths"]["state"]) / "config/quantcode/opencode.json").read_text())
            url = config["provider"]["organization-qwen"]["options"]["baseURL"]
            if url not in {"http://127.0.0.1:6201/v1", "http://127.0.0.1:6202/v1"}:
                raise ValueError("Review a changed organization model endpoint before pinning trust")
            targets.append((host["unit_name"], url))
    print(json.dumps({"status": "PLAN", "hosts": len(targets), "model_sha256": args.sha256}), flush=True)
    if not args.apply:
        return
    connections = subprocess.check_output(["ss", "-Htn", "state", "established"], text=True)
    if any(line.split()[2].rsplit(":", 1)[-1] in {"6201", "6202"} for line in connections.splitlines()):
        raise ValueError("Wait for active model requests before activating this runtime")
    if not runtime.exists():
        runtime.mkdir(mode=0o755)
        shutil.copytree(base / "quantcode", runtime / "quantcode", copy_function=os.link,
                        ignore=shutil.ignore_patterns("__pycache__"))
        (runtime / ".venv").symlink_to(base / ".venv", target_is_directory=True)
        temporary = runtime / "quantcode/model_gateway.py.new"
        temporary.write_bytes(source)
        temporary.chmod(0o644)
        os.replace(temporary, runtime / "quantcode/model_gateway.py")
        (runtime / "model-build.json").write_text(json.dumps({"base": str(base), "model_sha256": args.sha256}))
    elif hashlib.sha256((runtime / "quantcode/model_gateway.py").read_bytes()).hexdigest() != args.sha256:
        raise ValueError("Versioned model runtime already differs")

    def install(path, content):
        if path.exists():
            if path.read_text() != content:
                raise ValueError("Existing activation differs: " + str(path))
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        path.chmod(0o644)

    for unit, url in targets:
        install(Path("/etc/systemd/system") / (unit + ".d/98-model-admission.conf"),
                f'[Service]\nEnvironment="QUANTCODE_MODEL_GATEWAY_URL={url}"\n')
    gateways = [("quantcode-admin-model.service", 6202, 2, 1), ("quantcode-test-v1-model.service", 6201, 4, 2)]
    for unit, port, concurrency, per_member in gateways:
        install(Path("/etc/systemd/system") / (unit + ".d/98-task-conversation.conf"),
                f"[Service]\nWorkingDirectory={runtime}\nExecStart=\nExecStart={runtime}/.venv/bin/python -B -m quantcode.model_gateway --port {port} --max-concurrency {concurrency} --per-member-concurrency {per_member} --max-tokens 4096 --max-request-bytes 2000000\n")
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    for unit, *_ in gateways:
        subprocess.run(["systemctl", "restart", unit], check=True)
    print(json.dumps({"status": "APPLIED", "hosts_pinned": len(targets), "runtime": str(runtime)}))


if __name__ == "__main__":
    main()
