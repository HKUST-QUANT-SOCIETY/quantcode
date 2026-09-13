"""Install read-only SSH-to-workspace routing; never alter accounts, keys or runtimes."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import tempfile


def fingerprints(home):
    root = os.open(home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    ssh = None
    try:
        ssh = os.open('.ssh', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        fd = os.open('authorized_keys', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=ssh)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 262144:
                raise ValueError('invalid SSH key registry')
            raw = stream.read(262145).decode()
        result = set()
        for line in raw.splitlines():
            if line.lstrip().startswith('#'):
                continue
            match = re.search(r'(?:^|\s)(ssh-[\w@.+-]+|ecdsa-[\w@.+-]+|sk-[\w@.+-]+)\s+([A-Za-z0-9+/]+={0,2})(?:\s|$)', line)
            if not match:
                continue
            blob = base64.b64decode(match[2], validate=True)
            size = int.from_bytes(blob[:4], 'big')
            if blob[4:4 + size].decode() != match[1]:
                continue
            result.add('SHA256:' + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('='))
        return result
    finally:
        if ssh is not None:
            os.close(ssh)
        os.close(root)


def member_routes(user, keys, inventory, aliases):
    actors = {entry['actor_id'] for entry in inventory if keys.intersection(entry['fingerprints'])}
    if user.pw_name in aliases:
        actors.add(aliases[user.pw_name])
    if len(actors) > 1:
        raise ValueError(f'ambiguous member for SSH account {user.pw_name}')
    routes = [{key: entry[key] for key in ('serverId', 'username', 'fingerprints')}
              for entry in inventory if entry['actor_id'] in actors]
    if not routes:
        return None
    return {'version': 1, 'uid': user.pw_uid, 'username': user.pw_name, 'routes': routes}


def replace_owned(path, content, mode, backup):
    if path.is_symlink():
        raise PermissionError('refusing symlink destination')
    if path.exists():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o022:
            raise PermissionError('destination is not an administrator-owned regular file')
        before = path.read_bytes()
        if before == content:
            path.chmod(mode)
            return
        saved = backup / hashlib.sha256(str(path).encode()).hexdigest()
        if saved.exists():
            if saved.read_bytes() != before:
                raise ValueError('backup differs from the current source; re-plan before replacing')
        else:
            with saved.open('xb') as stream:
                stream.write(before)
            saved.chmod(0o600)
    descriptor, temporary = tempfile.mkstemp(prefix='.quantcode-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--helper', type=Path, required=True)
    parser.add_argument('--aliases', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--plan-digest')
    args = parser.parse_args()
    inventory = json.loads(args.inventory.read_text())
    aliases = json.loads(args.aliases.read_text()) if args.aliases else {}
    for item in inventory:
        if item['serverId'] not in ('server-a', 'server-b', 'server-c') or not re.fullmatch(r'[a-z_][a-z0-9_-]{0,63}', item['username']):
            raise ValueError('invalid organization route')
        if not item['fingerprints'] or any(not re.fullmatch(r'SHA256:[A-Za-z0-9+/]{43}', key) for key in item['fingerprints']):
            raise ValueError('invalid public fingerprint')
    mappings, conflicts = [], []
    for user in pwd.getpwall():
        if user.pw_uid < 1000 or user.pw_name in ('ubuntu', 'quantadmin', 'nobody') or user.pw_name.startswith('qc-'):
            continue
        try:
            keys = fingerprints(user.pw_dir)
            route = member_routes(user, keys, inventory, aliases)
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as error:
            conflicts.append({'user': user.pw_name, 'reason': type(error).__name__})
            continue
        if route:
            mappings.append(route)
    helper = args.helper.read_bytes()
    plan = {'mappings': mappings, 'conflicts': conflicts, 'helper_sha256': hashlib.sha256(helper).hexdigest()}
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    if args.apply:
        if os.geteuid() != 0 or args.plan_digest != digest:
            raise PermissionError('apply requires root and the current reviewed plan digest')
        root = Path('/etc/quantcode-ssh-workspaces')
        root.mkdir(parents=True, exist_ok=True, mode=0o755)
        for directory in (root.parent, root):
            info = directory.lstat()
            if directory.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
                raise PermissionError('registry directory is not administrator-owned')
        backup = Path('/var/lib/quantcode/ssh-discovery-backups') / digest
        backup.mkdir(parents=True, exist_ok=True, mode=0o700)
        for entry in mappings:
            replace_owned(root / f"{entry['uid']}.json", (json.dumps(entry, sort_keys=True) + '\n').encode(), 0o644, backup)
        replace_owned(Path('/usr/local/bin/quantcode-connect'), helper, 0o755, backup)
    print(json.dumps({'status': 'installed' if args.apply else 'planned', 'digest': digest,
                      'members': [entry['username'] for entry in mappings], 'conflicts': conflicts}))


if __name__ == '__main__':
    main()
