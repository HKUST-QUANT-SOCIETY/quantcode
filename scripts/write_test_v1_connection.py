"""Receive a private Test V1 connection profile on stdin as its enrolled Unix user."""
from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import re
import stat
import sys


def main():
    user = pwd.getpwuid(os.getuid())
    if os.getuid() == 0 or not user.pw_name.startswith("qc-"):
        raise PermissionError("Run profile delivery as the enrolled research user")
    home = Path(user.pw_dir)
    if home != Path("/srv/quant/users") / user.pw_name[3:]:
        raise PermissionError("Research home does not match the enrolled actor")
    raw = sys.stdin.buffer.read(16385)
    if len(raw) > 16384:
        raise ValueError("Connection profile is too large")
    profile = json.loads(raw)
    required = {"version", "release", "ssh_host", "ssh_port", "ssh_user", "remote_port", "local_port", "url", "username", "password"}
    if not isinstance(profile, dict) or set(profile) != required or profile["version"] != 1:
        raise ValueError("Invalid connection profile fields")
    if profile["ssh_user"] != user.pw_name or profile["username"] != "quantcode":
        raise ValueError("Connection profile belongs to another member")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", profile["ssh_host"]) or profile["ssh_port"] != 22:
        raise ValueError("Invalid SSH destination")
    if any(type(profile[key]) is not int or not 1024 <= profile[key] <= 65535 for key in ("remote_port", "local_port")):
        raise ValueError("Invalid forwarded port")
    if profile["url"] != f"http://127.0.0.1:{profile['local_port']}" or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", profile["password"]):
        raise ValueError("Invalid local host connection")
    descriptors = [os.open(home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)]
    try:
        for name in (".quantcode", "test-v1"):
            try:
                os.mkdir(name, 0o700, dir_fd=descriptors[-1])
            except FileExistsError:
                pass
            descriptors.append(os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptors[-1]))
            info = os.fstat(descriptors[-1])
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise PermissionError("Connection directory must be member-owned and private")
        descriptor = os.open("connection.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=descriptors[-1])
        with os.fdopen(descriptor, "wb") as file:
            file.write((json.dumps(profile, indent=2) + "\n").encode())
            file.flush()
            os.fsync(file.fileno())
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
    print(json.dumps({"status": "DELIVERED", "username": user.pw_name,
                      "profile": str(home / ".quantcode/test-v1/connection.json"), "mode": "0600"}))


if __name__ == "__main__":
    main()
