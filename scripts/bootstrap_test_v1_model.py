"""Initialize one fresh host's model stores as its enrolled Unix user before start."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import sys
import tempfile

PROVIDER = "organization-qwen"
MODEL = "qwen3.7-flash"
URL = "http://127.0.0.1:6201/v1"


def verify_existing(config_file: Path, auth_file: Path):
    values = []
    for path in (config_file, auth_file):
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as file:
            info = os.fstat(file.fileno())
            if info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 2_000_000:
                raise PermissionError("Existing bootstrap files must be private and member-owned")
            values.append(json.load(file))
    config, auth = values
    if set(auth) != {PROVIDER}:
        raise ValueError("Existing model credentials are not this installation's bootstrap")
    credential = auth[PROVIDER]
    token = credential.get("key", "")
    if credential != {"type": "api", "key": token, "metadata": {"quantcode_base_url": URL}} or not re.fullmatch(r"qcv1_[A-Za-z0-9_-]{43}", token):
        raise ValueError("Existing credential is not a Test V1 member proxy token")
    connection = config.get("provider", {}).get(PROVIDER, {})
    if (set(config.get("provider", {})) != {PROVIDER} or connection.get("npm") != "@ai-sdk/openai-compatible"
            or connection.get("options") != {"baseURL": URL} or set(connection.get("models", {})) != {MODEL}
            or config.get("model") != f"{PROVIDER}/{MODEL}" or config.get("small_model") != f"{PROVIDER}/{MODEL}"):
        raise ValueError("Existing model configuration changed; refusing to overwrite it")
    return hashlib.sha256(token.encode()).hexdigest()


def bootstrap(config_file: Path, auth_file: Path, expected: str, token: str):
    if not re.fullmatch(r"qcv1_[A-Za-z0-9_-]{43}", token):
        raise ValueError("Only an installation-generated member proxy token is accepted")
    with os.fdopen(os.open(config_file, os.O_RDONLY | os.O_NOFOLLOW), "rb") as source:
        before = source.read(2_000_001)
        snapshot = os.fstat(source.fileno())
    if len(before) > 2_000_000 or hashlib.sha256(before).hexdigest() != expected:
        raise ValueError("Fresh host configuration changed since installation")
    config = json.loads(before)
    if set(config) != {"mcp"} or not isinstance(config["mcp"], dict) or "quantcode" not in config["mcp"]:
        raise ValueError("Model bootstrap only accepts a fresh operator MCP configuration")
    if auth_file.exists() or auth_file.is_symlink():
        raise FileExistsError("Model credentials already exist; use authenticated product settings")
    auth_file.parent.mkdir(mode=0o700, exist_ok=True)
    for directory in (config_file.parent, auth_file.parent):
        info = directory.lstat()
        if directory.resolve() != directory or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise PermissionError("Host model directories must remain private and member-owned")
    credential = {PROVIDER: {"type": "api", "key": token, "metadata": {"quantcode_base_url": URL}}}
    fd = os.open(auth_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(credential, output, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    config.update(provider={PROVIDER: {"name": "Organization Qwen", "npm": "@ai-sdk/openai-compatible",
        "options": {"baseURL": URL}, "models": {MODEL: {"name": MODEL, "tool_call": True,
            "limit": {"context": 65536, "output": 4096}}}}}, model=f"{PROVIDER}/{MODEL}", small_model=f"{PROVIDER}/{MODEL}")
    fd, temporary = tempfile.mkstemp(prefix=".test-v1-model-", dir=config_file.parent)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(config, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        current = config_file.lstat()
        if (current.st_dev, current.st_ino, current.st_mtime_ns, current.st_size) != \
                (snapshot.st_dev, snapshot.st_ino, snapshot.st_mtime_ns, snapshot.st_size):
            raise ValueError("Host configuration changed; unused proxy credential retained for repair")
        os.replace(temporary, config_file)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--expected-config-sha256")
    parser.add_argument("--verify-existing", action="store_true")
    args = parser.parse_args()
    user = pwd.getpwuid(os.getuid())
    if os.getuid() == 0 or not user.pw_name.startswith("qc-"):
        raise PermissionError("Run bootstrap as the enrolled research user")
    expected_parent = Path("/var/lib/quantcode-test-v1/native") / user.pw_name[3:]
    if args.state.parent != expected_parent or args.state.resolve() != args.state:
        raise PermissionError("Host state does not belong to this enrolled actor")
    if (args.state / "identity/session.json").exists():
        raise PermissionError("Model bootstrap cannot modify an already authenticated host")
    config, auth = args.state / "config/quantcode/opencode.json", args.state / "data/quantcode/auth.json"
    if not args.verify_existing:
        if not args.expected_config_sha256:
            raise ValueError("Fresh bootstrap requires the reviewed config digest")
        token = sys.stdin.read(4097).strip()
        bootstrap(config, auth, args.expected_config_sha256, token)
    digest = verify_existing(config, auth)
    print(json.dumps({"status": "VERIFIED", "username": user.pw_name, "provider": PROVIDER, "model": MODEL,
                      "token_sha256": digest}))


if __name__ == "__main__":
    main()
