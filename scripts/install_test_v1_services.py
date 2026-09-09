"""Install the reviewed Server C Test V1 deployment in explicit independent stages.

Existing research accounts, the formal roster and gateway 4097 are read-only.
Upstream model credentials are supplied separately through systemd credentials.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import secrets
import subprocess
import sys
import time

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.install_native_host import apply_plan, build_plan, file_digest, write_new  # noqa: E402
from schemas.evidence_chain import canonical_json, sha256_hex  # noqa: E402

CONFIG = Path("/etc/quantcode-test-v1")
STATE = Path("/var/lib/quantcode-test-v1")
UNITS = Path("/etc/systemd/system")
GATEWAY_USER = "quantcode-test-v1"
MODEL_USER = "quantcode-model-v1"
PROVIDER = "organization-qwen"
MODEL = "qwen3.7-flash"
CLIENT_PORT = 48196


def infrastructure_file(path, data, mode, *, uid=0, gid=0):
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if path.is_symlink() or not path.is_file() or info.st_uid != uid or info.st_gid != gid or info.st_mode & 0o777 != mode or path.read_bytes() != data:
            raise PermissionError("An existing Test V1 infrastructure file differs from the reviewed content")
        return
    write_new(path, data, mode, uid=uid, gid=gid)


def account(name, home):
    try:
        user = pwd.getpwnam(name)
    except KeyError:
        subprocess.run(["useradd", "--system", "--user-group", "--no-create-home", "--home-dir", str(home),
                        "--shell", "/usr/sbin/nologin", name], check=True, capture_output=True)
        user = pwd.getpwnam(name)
    if user.pw_uid == 0 or user.pw_dir != str(home) or user.pw_shell != "/usr/sbin/nologin":
        raise PermissionError("Existing service account does not match this deployment")
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chown(home, user.pw_uid, user.pw_gid)
    return user


def infrastructure(spec, layout):
    for directory, mode in ((CONFIG, 0o700), (CONFIG / "credentials", 0o700), (STATE, 0o755)):
        directory.mkdir(mode=mode, exist_ok=True)
        info = directory.lstat()
        if directory.is_symlink() or not directory.is_dir() or info.st_uid != 0 or info.st_mode & 0o777 != mode:
            raise PermissionError("Test V1 infrastructure directory ownership or privacy changed")
    gateway = account(GATEWAY_USER, STATE / "gateway")
    account(MODEL_USER, STATE / "model")
    roster = Path(spec["roster"]).read_bytes()
    infrastructure_file(CONFIG / "roster.yaml", roster, 0o600)
    infrastructure_file(STATE / "gateway/roster.yaml", roster, 0o600, uid=gateway.pw_uid, gid=gateway.pw_gid)
    runtime = Path(spec["runtime_root"])
    python = runtime / ".venv/bin/python"
    environment = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(runtime)}
    subprocess.run(["/usr/sbin/runuser", "-u", GATEWAY_USER, "--", str(python), "-B", str(runtime / "scripts/initialize_shared_memory.py"),
                    "--root", str(STATE / "gateway/shared-memory")], env=environment, cwd=runtime, check=True)
    infrastructure_file(Path("/etc/apparmor.d/quantcode-test-v1-native"),
              b"abi <abi/4.0>,\ninclude <tunables/global>\nprofile quantcode-test-v1-native flags=(unconfined) {\n  userns,\n}\n", 0o644)
    subprocess.run(["apparmor_parser", "-r", "/etc/apparmor.d/quantcode-test-v1-native"], check=True)
    common = ("Restart=on-failure\nRestartSec=3\nUMask=0077\nNoNewPrivileges=true\nProtectSystem=strict\n"
              "ProtectHome=true\nPrivateTmp=true\nRestrictSUIDSGID=true\nRestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX\n")
    gateway_unit = ("[Unit]\nDescription=QuantCode Test V1 organization gateway\nAfter=network-online.target\n"
        "StartLimitIntervalSec=60\nStartLimitBurst=3\n\n[Service]\nType=simple\n"
        f"User={GATEWAY_USER}\nGroup={GATEWAY_USER}\nWorkingDirectory={runtime}\n"
        "Environment=PYTHONDONTWRITEBYTECODE=1\nEnvironment=QUANTCODE_ENV=production\n"
        f"ExecStart={python} -B -m quantcode.gateway --roster {STATE}/gateway/roster.yaml --database {STATE}/gateway/gateway.db --port 5098 --github-sync-interval 0 --dream-interval 0\n"
        + common + f"ReadWritePaths={STATE}/gateway\nMemoryMax=1G\nTasksMax=256\n\n[Install]\nWantedBy=multi-user.target\n")
    infrastructure_file(UNITS / "quantcode-test-v1-gateway.service", gateway_unit.encode(), 0o644)
    model_unit = ("[Unit]\nDescription=QuantCode Test V1 organization model gateway\nAfter=network-online.target\n"
        f"ConditionPathExists={CONFIG}/credentials/dashscope-api-key\nConditionPathExists={CONFIG}/credentials/member-tokens.json\n"
        "StartLimitIntervalSec=60\nStartLimitBurst=3\n\n[Service]\nType=simple\n"
        f"User={MODEL_USER}\nGroup={MODEL_USER}\nWorkingDirectory={runtime}\nEnvironment=PYTHONDONTWRITEBYTECODE=1\n"
        f"LoadCredential=dashscope-api-key:{CONFIG}/credentials/dashscope-api-key\n"
        f"LoadCredential=member-tokens.json:{CONFIG}/credentials/member-tokens.json\n"
        f"ExecStart={python} -B -m quantcode.model_gateway --port 6201 --max-concurrency 4 --per-member-concurrency 2 --max-tokens 4096 --max-request-bytes 2000000\n"
        + common + f"ReadWritePaths={STATE}/model\nMemoryMax=512M\nTasksMax=128\n\n[Install]\nWantedBy=multi-user.target\n")
    infrastructure_file(UNITS / "quantcode-test-v1-model.service", model_unit.encode(), 0o644)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", "quantcode-test-v1-gateway.service"], check=True)
    print(json.dumps({"stage": "infrastructure", "gateway_port": 5098, "model_port": 6201,
                      "model_key_status": "supplied separately through LoadCredential"}), flush=True)


def host_args(spec, item, roster):
    entry = sorted((entry for entry in roster["bindings"] if entry["actor_id"] == item["actor_id"]), key=lambda entry: entry["fingerprint"])[0]
    runtime, artifact = Path(spec["runtime_root"]), Path(spec["artifact_root"])
    return argparse.Namespace(runtime_root=runtime, artifact_root=artifact, binary=artifact / "opencode",
        binary_sha256=spec["binary_sha256"], source_commit=spec["source_commit"], cli_license=runtime / "frontend/LICENSE",
        release=item["install"].rsplit("/", 1)[1], actor=item["actor_id"], fingerprint=entry["fingerprint"],
        gateway="http://127.0.0.1:5098", port=item["native_port"], registry=Path(spec["registry"]),
        roster=CONFIG / "roster.yaml", install_root=Path("/opt/quantcode-test-v1/native-hosts"),
        state_root=STATE / "native", units_root=UNITS)


def install_hosts(spec, layout):
    roster = yaml.safe_load((CONFIG / "roster.yaml").read_text())
    plans = [(host_args(spec, item, roster), item) for item in layout["members"]]
    reviewed = {args.actor: sha256_hex(canonical_json(build_plan(args))) for args, _ in plans}
    write_new(CONFIG / "native-plan-digests.json", (json.dumps(reviewed, indent=2) + "\n").encode(), 0o600)
    for args, item in plans:
        result = apply_plan(args, reviewed[args.actor])
        install = Path(item["install"])
        saved = json.loads((install / "native-host.json").read_text())
        for relative, artifact in saved["source"]["artifacts"].items():
            source, target = args.artifact_root / relative, install / "bin" / relative
            if file_digest(source) != artifact["sha256"] or file_digest(target) != artifact["sha256"]:
                raise ValueError("Shared CLI bytes changed")
            temporary = target.with_name(target.name + ".shared")
            os.link(source, temporary)
            os.replace(temporary, target)
        entries = sorted((entry for entry in roster["bindings"] if entry["actor_id"] == args.actor), key=lambda entry: entry["fingerprint"])
        public_files = []
        for index, entry in enumerate(entries):
            file = install / f"identity-{index}.pub"
            write_new(file, (" ".join(entry["public_key"].split()[:2]) + "\n").encode(), 0o644)
            public_files.append(str(file))
        dropin = UNITS / (item["unit"] + ".d")
        dropin.mkdir(mode=0o755)
        text = ("[Unit]\nStartLimitIntervalSec=60\nStartLimitBurst=3\n[Service]\n"
            "AppArmorProfile=quantcode-test-v1-native\nRestart=on-failure\nRestartSec=3\nMemoryMax=1G\nCPUQuota=100%\nTasksMax=256\n"
            f"Environment=QUANTCODE_PUBLIC_KEY_FILES={','.join(public_files[1:])}\n")
        write_new(dropin / "90-test-v1.conf", text.encode(), 0o644)
        print(json.dumps({"stage": "hosts", "actor": args.actor, "port": args.port,
                          "key_count": len(entries), "status": result["status"], "binary_shared": True}), flush=True)


def host_client(item):
    raw = (Path(item["install"]) / "access.env").read_text().strip()
    password = raw.split("=", 1)[1]
    return httpx.Client(base_url=item["native_url"], auth=("quantcode", password), trust_env=False, timeout=45)


def configure(spec, layout):
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    tokens = {}
    for item in layout["members"]:
        running = subprocess.run(["systemctl", "is-active", "--quiet", item["unit"]]).returncode == 0
        config_file = Path(item["state"]) / "config/quantcode/opencode.json"
        config_digest = hashlib.sha256(config_file.read_bytes()).hexdigest()
        command = ["runuser", "-u", item["username"], "--", "/usr/bin/python3", "-B",
                   spec.get("model_bootstrap", str(Path(spec["runtime_root"]) / "scripts/bootstrap_test_v1_model.py")),
                   "--state", item["state"]]
        if (Path(item["state"]) / "data/quantcode/auth.json").exists():
            initialized = subprocess.run([*command, "--verify-existing"], text=True, capture_output=True)
        else:
            if running:
                raise ValueError("Fresh model bootstrap requires an inactive host")
            token = "qcv1_" + secrets.token_urlsafe(32)
            initialized = subprocess.run([*command, "--expected-config-sha256", config_digest], input=token, text=True, capture_output=True)
        if initialized.returncode:
            raise RuntimeError("Offline model bootstrap failed for " + item["actor_id"])
        token_digest = json.loads(initialized.stdout)["token_sha256"]
        subprocess.run(["systemctl", "enable", "--now", item["unit"]], check=True, capture_output=True)
        with host_client(item) as client:
            deadline = time.monotonic() + 45
            attempts = 0
            while True:
                attempts += 1
                try:
                    response = client.get("/global/health", timeout=3)
                    if response.status_code == 200 and response.json().get("healthy") is True:
                        break
                    print(json.dumps({"stage": "readiness", "actor": item["actor_id"], "attempt": attempts,
                                      "http_status": response.status_code}), flush=True)
                except httpx.TransportError as error:
                    print(json.dumps({"stage": "readiness", "actor": item["actor_id"], "attempt": attempts,
                                      "transport_error": type(error).__name__}), flush=True)
                if time.monotonic() >= deadline:
                    raise RuntimeError("Native host failed to become ready: " + item["actor_id"])
                time.sleep(0.2)
            response = client.get("/experimental/quantcode/identities")
            if response.status_code != 200:
                raise RuntimeError(f"Host identity readiness failed: HTTP {response.status_code}")
            identities = response.json()
            if identities.get("session") is not None or len(identities["identities"]) != item["public_key_count"]:
                raise ValueError("Fresh host identity list does not match enrollment")
            if any(identity["group"] != item["group"] for identity in identities["identities"]):
                raise ValueError("Host group differs from enrollment")
            config = client.get("/global/config")
            if config.status_code != 200 or config.json().get("model") != f"{PROVIDER}/{MODEL}" or "qcv1_" in config.text:
                raise ValueError("Public model configuration is unavailable or disclosed a credential")
            providers = client.get("/provider")
            if providers.status_code != 200 or PROVIDER not in providers.json().get("connected", []):
                raise ValueError("Bootstrapped provider is not connected in the native host")
            tokens[item["actor_id"]] = token_digest
        print(json.dumps({"stage": "configure", "actor": item["actor_id"], "status": "configured", "key_count": item["public_key_count"]}), flush=True)
    write_new(CONFIG / "credentials/member-tokens.json", (json.dumps({"token_sha256": tokens}, indent=2) + "\n").encode(), 0o600)
    subprocess.run(["systemctl", "enable", "quantcode-test-v1-model.service"], check=True, capture_output=True)


def deliver(spec, layout):
    if subprocess.run(["systemctl", "is-active", "--quiet", "quantcode-test-v1-model.service"]).returncode:
        raise RuntimeError("The organization model service is not active")
    for item in layout["members"]:
        state = Path(item["state"])
        catalog = json.loads((state / "config/quantcode/tool-catalog.json").read_text())
        if sum(entry["status"] == "published" for entry in catalog["tools"]) != 9 or len(catalog["tools"]) != 22:
            raise ValueError("Reviewed tool catalog is incomplete")
        password = (Path(item["install"]) / "access.env").read_text().strip().split("=", 1)[1]
        profile = {"version": 1, "release": layout["release"], "ssh_host": spec["ssh_host"], "ssh_port": 22,
                   "ssh_user": item["username"], "remote_port": item["native_port"], "local_port": CLIENT_PORT,
                   "url": f"http://127.0.0.1:{CLIENT_PORT}", "username": "quantcode", "password": password}
        command = ["runuser", "-u", item["username"], "--", "/usr/bin/python3", "-B", spec["connection_writer"]]
        result = subprocess.run(command, input=json.dumps(profile), text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError("Private profile delivery failed for " + item["actor_id"])
        print(result.stdout.strip(), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--stage", choices=("infrastructure", "hosts", "configure", "deliver"), required=True)
    args = parser.parse_args()
    if os.geteuid() != 0 or sys.platform != "linux":
        raise PermissionError("Test V1 installation requires the Server C administrator")
    spec, layout = json.loads(args.spec.read_text()), json.loads(args.layout.read_text())
    for field, expected in (("roster", layout["roster_sha256"]), ("registry", layout["registry_sha256"])):
        if hashlib.sha256(Path(spec[field]).read_bytes()).hexdigest() != expected:
            raise ValueError("Real member enrollment changed since review")
    if layout["status"] != "PLAN_ONLY" or layout["member_count"] != 36 or layout["public_key_count"] != 38:
        raise ValueError("Use the reviewed 36-member Test V1 layout")
    if not Path(spec["runtime_root"]).is_relative_to("/opt/quantcode-test-v1/runtime") or not Path(spec["artifact_root"]).is_relative_to("/opt/quantcode-test-v1/artifacts"):
        raise ValueError("Test V1 source and binary must use isolated immutable installations")
    if args.stage == "infrastructure":
        infrastructure(spec, layout)
    elif args.stage == "hosts":
        install_hosts(spec, layout)
    elif args.stage == "configure":
        configure(spec, layout)
    else:
        deliver(spec, layout)


if __name__ == "__main__":
    main()
