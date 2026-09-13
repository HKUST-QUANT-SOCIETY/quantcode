#!/usr/bin/python3
"""Describe only the current Unix user's administrator-installed workspace routes."""
import json
import os
from pathlib import Path
import pwd
import stat


def describe(uid, root=Path('/etc/quantcode-ssh-workspaces')):
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parent = os.fstat(directory)
        if parent.st_uid != 0 or parent.st_mode & 0o022:
            raise PermissionError('workspace registry must be administrator-owned')
        fd = os.open(f'{uid}.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_size > 32768:
                raise PermissionError('workspace routes must be administrator-owned')
            value = json.loads(stream.read(32769))
        if not isinstance(value, dict) or value.get('uid') != uid or value.get('username') != pwd.getpwuid(uid).pw_name:
            raise PermissionError('workspace routes do not match the SSH account')
        return {'version': 1, 'status': 'registered', 'routes': value['routes']}
    finally:
        os.close(directory)


if __name__ == '__main__':
    try:
        result = describe(os.getuid())
    except FileNotFoundError:
        result = {'version': 1, 'status': 'not_configured', 'routes': []}
    except (OSError, ValueError, KeyError):
        result = {'version': 1, 'status': 'invalid', 'routes': []}
    print(json.dumps(result))
