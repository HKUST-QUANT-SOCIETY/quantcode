"""Prepare or install the single QuantCode administrator identity on Server C.

Run with the existing runtime's Python as root. No private SSH key is accepted.
Existing member hosts, data and model service are not restarted or replaced.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import time

ACTOR = "quantadmin"
FINGERPRINT = "SHA256:5NMccNoY0wL6Tj40RstXl3mY7YqaHWxzTsHnl3PXW2o"
RELEASE = "unified-admin-v1"
CONFIG = Path("/etc/quantcode-admin")
STATE = Path("/var/lib/quantcode-admin")
INSTALL = Path("/opt/quantcode-admin/native-hosts")
REFERENCE = Path("/opt/quantcode-test-v1/native-hosts/chenyuanheng/test-v1-20260909/native-host.json")
ROSTERS = [Path("/etc/quantcode-test-v1/roster.yaml"), Path("/var/lib/quantcode-test-v1/gateway/roster.yaml")]
MODEL_RUNTIME = Path("/opt/quantcode-test-v1/runtime/test-v1-20260909-03")


def bind_admin_github(roster: dict, subject: str) -> dict:
    """Bind only the verified administrator; never reassign a different account."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", subject):
        raise ValueError("Invalid GitHub account")
    result = copy.deepcopy(roster)
    matches = [item for item in result.get("bindings", []) if item.get("actor_id") == ACTOR]
    if len(matches) != 1 or matches[0].get("fingerprint") != FINGERPRINT or matches[0].get("role") != "admin":
        raise ValueError("Verified administrator enrollment required")
    if matches[0].get("github_subject") not in (None, subject):
        raise ValueError("Administrator is already bound to a different GitHub account")
    matches[0]["github_subject"] = subject
    return result


def extend_roster(roster: dict, entry: dict) -> dict:
    if roster.get("status") == "REVIEW_REQUIRED" or not isinstance(roster.get("bindings"), list):
        raise ValueError("Only an approved, valid roster may be extended")
    result = copy.deepcopy(roster)
    for previous in result["bindings"]:
        if previous.get("actor_id") == entry["actor_id"] or previous.get("fingerprint") == entry["fingerprint"]:
            if previous != entry:
                raise ValueError("Administrator enrollment conflicts with an existing identity; no overwrite is allowed")
            return result
    result["bindings"].append(entry)
    return result


def remap_paths(value, old_release: str, new_release: str, old_state: str, new_state: str):
    if isinstance(value, dict):
        return {key: remap_paths(item, old_release, new_release, old_state, new_state) for key, item in value.items()}
    if isinstance(value, list):
        return [remap_paths(item, old_release, new_release, old_state, new_state) for item in value]
    if isinstance(value, str):
        for old, new in [(old_release, new_release), (old_state, new_state)]:
            if value == old or value.startswith(old + "/"):
                return new + value[len(old):]
    return value


def rebind_catalog(catalog: dict, old_mcp: dict, new_mcp: dict) -> dict:
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    result = copy.deepcopy(catalog)
    for item in [*result.get("tools", []), *result.get("content", [])]:
        server = item["server"]
        if server not in old_mcp or server not in new_mcp:
            continue
        old_hash = digest(old_mcp[server])
        if item["status"] == "published" and item["server_config_hash"] != old_hash:
            raise ValueError("Reference catalog no longer matches its reviewed server configuration")
        if item["server_config_hash"] == old_hash:
            item["server_config_hash"] = digest(new_mcp[server])
    return result


def load_helper(name: str, root: Path):
    spec = importlib.util.spec_from_file_location(name, root / "scripts" / f"{name}.py")
    if spec is None or spec.loader is None:
        raise ValueError("Installation helper is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def private_directory(path: Path, uid=0, gid=0, mode=0o700):
    if uid and path.parent.exists() and path.parent.stat().st_uid != 0:
        program = "from pathlib import Path; import os,sys; p=Path(sys.argv[1]); p.mkdir(parents=True,exist_ok=True,mode=int(sys.argv[2])); assert not p.is_symlink() and p.resolve()==p and p.stat().st_uid==os.getuid(); p.chmod(int(sys.argv[2]))"
        subprocess.run(["runuser", "-u", pwd.getpwuid(uid).pw_name, "--", "/usr/bin/python3", "-c", program, str(path), str(mode)], check=True, capture_output=True)
        return
    path.mkdir(parents=True, exist_ok=True, mode=mode)
    info = path.lstat()
    if path.is_symlink() or not path.is_dir() or path.resolve() != path:
        raise PermissionError("Installation directories must be canonical directories")
    if info.st_uid not in (0, uid):
        raise PermissionError("Installation directory belongs to another account")
    os.chown(path, uid, gid)
    path.chmod(mode)


def write_once(path: Path, data: bytes, uid=0, gid=0, mode=0o600):
    if uid and os.geteuid() == 0:
        program = """from pathlib import Path
import os,sys,stat
p=Path(sys.argv[1]); mode=int(sys.argv[2]); data=sys.stdin.buffer.read()
assert p.parent.resolve()==p.parent
if p.exists() or p.is_symlink():
 info=p.lstat()
 assert stat.S_ISREG(info.st_mode) and not p.is_symlink() and info.st_uid==os.getuid() and info.st_mode&0o777==mode and info.st_nlink==1 and p.read_bytes()==data
else:
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
 with os.fdopen(fd,'wb') as out: out.write(data); out.flush(); os.fsync(out.fileno())
"""
        subprocess.run(["runuser", "-u", pwd.getpwuid(uid).pw_name, "--", "/usr/bin/python3", "-c", program, str(path), str(mode)], input=data, check=True, capture_output=True)
        return
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_gid != gid or info.st_mode & 0o777 != mode or path.read_bytes() != data:
            raise PermissionError(f"Existing configuration differs: {path}")
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as output:
        os.fchown(output.fileno(), uid, gid)
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def replace_roster(path: Path, before: bytes, after: bytes):
    info = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise PermissionError("Roster must remain a private regular file")
    if before == after:
        return
    backup = path.with_name(path.name + ".before-unified-admin-" + hashlib.sha256(before).hexdigest()[:12])
    write_once(backup, before, info.st_uid, info.st_gid)
    fd, temporary = tempfile.mkstemp(prefix=".admin-roster-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            os.fchown(output.fileno(), info.st_uid, info.st_gid)
            output.write(after)
            output.flush()
            os.fsync(output.fileno())
        if path.read_bytes() != before:
            raise ValueError("Roster changed during setup; review before retrying")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--helpers", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--github-subject", help="Administrator's verified GitHub login (not a token)")
    args = parser.parse_args()
    if sys.platform != "linux" or os.geteuid() != 0:
        raise PermissionError("Run this reviewed setup with sudo on Server C")
    manifest = json.loads(REFERENCE.read_text())
    runtime = Path(manifest["source"]["runtime_root"])
    sys.path.insert(0, str(runtime))
    import yaml
    import httpx
    from quantcode.roster import normalize_public_key
    from schemas.groups import GROUP_IDS
    from schemas.evidence_chain import canonical_json, sha256_hex
    installer = load_helper("install_native_host", args.helpers)
    provision = load_helper("provision_research_accounts", args.helpers)
    public, fingerprint = normalize_public_key(args.public_key.read_text())
    if fingerprint != FINGERPRINT:
        raise ValueError("The public key differs from the authorized quantadmin key")
    workspace = Path("/srv/quant/users") / ACTOR
    originals = {path: path.read_bytes() for path in ROSTERS}
    rosters = {path: yaml.safe_load(raw) for path, raw in originals.items()}
    scopes = sorted({scope for roster in rosters.values() for binding in roster["bindings"]
                     if binding.get("role") == "admin" for scope in binding.get("resource_scopes", [])})
    entry = {"actor_id": ACTOR, "fingerprint": fingerprint, "public_key": public, "role": "admin", "group": "agent",
             "groups": list(GROUP_IDS), "workspace_id": "admin-quantadmin", "workspace_path": str(workspace), "resource_scopes": scopes}
    if args.github_subject:
        entry = bind_admin_github({"bindings": [entry]}, args.github_subject)["bindings"][0]
    updated = {path: extend_roster(roster, entry) for path, roster in rosters.items()}
    source = manifest["source"]
    if installer.file_digest(Path(source["binary"])) != source["binary_sha256"]:
        raise ValueError("Reviewed native executable has changed")
    reference_state = Path(manifest["paths"]["state"])
    catalog = json.loads((reference_state / "config/quantcode/tool-catalog.json").read_text())
    if not isinstance(catalog.get("tools"), list) or not catalog["tools"]:
        raise ValueError("The reference reviewed tool catalog is missing")
    upstream_key = Path("/etc/quantcode-test-v1/credentials/dashscope-api-key")
    if not upstream_key.is_file():
        raise ValueError("The existing organization model credential is missing")
    admin = pwd.getpwnam("quantadmin")
    model_user = pwd.getpwnam("quantcode-model-v1")
    release = INSTALL / ACTOR / RELEASE
    state = STATE / "native" / ACTOR / RELEASE
    unit_name = f"quantcode-native-{ACTOR}-{RELEASE}.service"
    for port, unit in [(6096, unit_name), (6202, "quantcode-admin-model.service")]:
        active = subprocess.run(["systemctl", "is-active", "--quiet", unit]).returncode == 0
        for network in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
            for line in network.read_text().splitlines()[1:]:
                fields = line.split()
                if fields[3] == "0A" and int(fields[1].rsplit(":", 1)[1], 16) == port and not active:
                    raise ValueError("An administrator service port is occupied by another listener")
    if not args.apply:
        print(json.dumps({"status": "PLAN", "actor": ACTOR, "role": "admin", "groups": list(GROUP_IDS),
          "fingerprint": fingerprint, "gateway": "http://127.0.0.1:5098", "native_port": 6096, "model_port": 6202,
          "unit": unit_name, "existing_member_hosts": "unchanged", "existing_model_service": "unchanged"}, ensure_ascii=False))
        return
    print(json.dumps({"stage": "preflight", "status": "passed"}), flush=True)
    private_directory(CONFIG)
    private_directory(STATE, mode=0o755)
    write_once(CONFIG / "roster.yaml", yaml.safe_dump({"bindings": [entry]}, sort_keys=False).encode())
    account_plan = provision.build_plan({"bindings": [entry]}, Path("/srv/quant/users"))
    provision.apply_plan(account_plan, CONFIG / "registry.json", Path("/srv/quant/users"))
    native_args = argparse.Namespace(runtime_root=runtime, artifact_root=Path(source["artifact_root"]), binary=Path(source["binary"]),
      binary_sha256=source["binary_sha256"], source_commit=source["source_commit"], cli_license=runtime / "frontend/LICENSE",
      release=RELEASE, actor=ACTOR, fingerprint=fingerprint, gateway="http://127.0.0.1:5098", port=6096,
      roster=CONFIG / "roster.yaml", registry=CONFIG / "registry.json", install_root=INSTALL, state_root=STATE / "native", units_root=Path("/etc/systemd/system"))
    installed = release / "native-host.json"
    if not installed.exists():
        plan = installer.build_plan(native_args)
        installer.apply_plan(native_args, sha256_hex(canonical_json(plan)))
    else:
        previous = json.loads(installed.read_text())
        if previous.get("member", {}).get("actor_id") != ACTOR or previous.get("port") != 6096 or previous.get("source", {}).get("binary_sha256") != source["binary_sha256"]:
            raise ValueError("Existing administrator installation differs")
    print(json.dumps({"stage": "native_host", "status": "installed"}), flush=True)
    user = pwd.getpwnam("qc-" + ACTOR)
    config_path = state / "config/quantcode/opencode.json"
    auth_path = state / "data/quantcode/auth.json"
    private_directory(auth_path.parent, user.pw_uid, user.pw_gid)
    if auth_path.exists():
        info = auth_path.lstat()
        if auth_path.is_symlink() or info.st_uid != user.pw_uid or info.st_mode & 0o077 or info.st_nlink != 1:
            raise PermissionError("Administrator model credentials must be private and owned by the runtime")
        token = json.loads(auth_path.read_text())["organization-qwen"]["key"]
    else:
        token = "qcv1_" + secrets.token_urlsafe(32)
    url = "http://127.0.0.1:6202/v1"
    bootstrap_file = release / "bootstrap-model.py"
    write_once(bootstrap_file, (args.helpers / "scripts/bootstrap_test_v1_model.py").read_bytes(), mode=0o644)
    program = """import importlib.util,sys,hashlib
from pathlib import Path
spec=importlib.util.spec_from_file_location('bootstrap',sys.argv[1]); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
module.URL=sys.argv[2]; config=Path(sys.argv[3]); auth=Path(sys.argv[4])
if auth.exists(): module.verify_existing(config,auth)
else: module.bootstrap(config,auth,hashlib.sha256(config.read_bytes()).hexdigest(),sys.stdin.read().strip())
"""
    subprocess.run(["runuser", "-u", user.pw_name, "--", str(runtime / ".venv/bin/python"), "-I", "-B", "-c", program,
                    str(bootstrap_file), url, str(config_path), str(auth_path)], input=token, text=True, check=True, capture_output=True)
    write_once(state / "config/quantcode/workspaces.json", json_bytes({"version": 1, "grants": [
      {"actor_id": ACTOR, "group": group, "workspace_id": entry["workspace_id"], "root": str(workspace), "access": "write"} for group in GROUP_IDS]}), user.pw_uid, user.pw_gid)
    mapped = remap_paths(catalog, manifest["paths"]["release"], str(release), str(reference_state), str(state))
    mapped = rebind_catalog(mapped, json.loads((reference_state / "config/quantcode/opencode.json").read_text())["mcp"],
                           json.loads(config_path.read_text())["mcp"])
    write_once(state / "config/quantcode/tool-catalog.json", json_bytes(mapped), user.pw_uid, user.pw_gid)
    private_directory(STATE / "model", model_user.pw_uid, model_user.pw_gid)
    write_once(CONFIG / "model-tokens.json", json_bytes({"token_sha256": {ACTOR: hashlib.sha256(token.encode()).hexdigest()}}))
    model_unit = f'''[Unit]
Description=QuantCode unified administrator model gateway
After=network-online.target
[Service]
Type=simple
User=quantcode-model-v1
Group=quantcode-model-v1
WorkingDirectory={MODEL_RUNTIME}
Environment=PYTHONDONTWRITEBYTECODE=1
LoadCredential=dashscope-api-key:{upstream_key}
LoadCredential=member-tokens.json:{CONFIG}/model-tokens.json
ExecStart={MODEL_RUNTIME}/.venv/bin/python -B -m quantcode.model_gateway --port 6202 --max-concurrency 2 --per-member-concurrency 1 --max-tokens 4096 --max-request-bytes 2000000
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths={STATE}/model
MemoryMax=512M
TasksMax=128
Restart=on-failure
[Install]
WantedBy=multi-user.target
'''
    write_once(Path("/etc/systemd/system/quantcode-admin-model.service"), model_unit.encode(), mode=0o644)
    dropin = Path("/etc/systemd/system") / (unit_name + ".d")
    private_directory(dropin, mode=0o755)
    write_once(dropin / "90-admin.conf", b"[Service]\nAppArmorProfile=quantcode-test-v1-native\nRestart=on-failure\nMemoryMax=1G\nTasksMax=256\n", mode=0o644)
    for path in ROSTERS:
        after = originals[path] if updated[path] == rosters[path] else yaml.safe_dump(updated[path], allow_unicode=True, sort_keys=False).encode()
        replace_roster(path, originals[path], after)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", "quantcode-admin-model.service", unit_name], check=True, capture_output=True)
    access = (release / "access.env").read_text().strip().split("=", 1)[1]
    with httpx.Client(base_url="http://127.0.0.1:6096", auth=("quantcode", access), trust_env=False, timeout=10) as client:
        deadline = time.monotonic() + 60
        while True:
            try:
                response = client.get("/global/health")
                if response.status_code == 200 and response.json().get("healthy") is True: break
            except httpx.HTTPError: pass
            if time.monotonic() >= deadline: raise RuntimeError("Administrator native host did not become healthy")
            time.sleep(.25)
        identities = client.get("/experimental/quantcode/identities").json()
        if not any(item.get("fingerprint") == fingerprint for item in identities.get("identities", [])):
            raise RuntimeError("The administrator identity is not available through the native host")
        provider = client.get("/provider").json()
        if "organization-qwen" not in provider.get("connected", []): raise RuntimeError("Administrator model is not connected")
    private_directory(Path(admin.pw_dir) / ".quantcode", admin.pw_uid, admin.pw_gid)
    profile_dir = Path(admin.pw_dir) / ".quantcode/admin"
    private_directory(profile_dir, admin.pw_uid, admin.pw_gid)
    write_once(profile_dir / "connection.json", json_bytes({"version": 1, "release": RELEASE, "ssh_host": "150.109.115.216", "ssh_port": 22,
      "ssh_user": "quantadmin", "remote_port": 6096, "local_port": 48199, "url": "http://127.0.0.1:48199", "username": "quantcode", "password": access}), admin.pw_uid, admin.pw_gid)
    write_once(CONFIG / "completed.json", json_bytes({"actor": ACTOR, "role": "admin", "fingerprint": fingerprint, "unit": unit_name, "model_unit": "quantcode-admin-model.service"}))
    print(json.dumps({"status": "READY", "actor": ACTOR, "role": "admin", "groups": list(GROUP_IDS), "profile": str(profile_dir / "connection.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
