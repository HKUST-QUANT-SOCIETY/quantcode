"""Read-only cohort audit. Never serialize passwords, tokens or private keys."""
import base64
import concurrent.futures
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import sys

ERRORS = []

def failure(stage, error):
    ERRORS.append({"stage": stage, "kind": type(error).__name__})

def read_text(path, limit=1048576):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("unsupported input file")
        raw = stream.read(limit + 1)
        if len(raw) > limit: raise ValueError("oversize input")
        return raw.decode("utf-8")
import subprocess
import urllib.error
import urllib.request

def metadata(path):
    try:
        st = path.lstat()
        return {'exists': True, 'uid': st.st_uid, 'gid': st.st_gid, 'mode': oct(stat.S_IMODE(st.st_mode)),
                'symlink': stat.S_ISLNK(st.st_mode), 'regular': stat.S_ISREG(st.st_mode)}
    except FileNotFoundError:
        return {'exists': False}
    except OSError as error:
        failure('stat:' + str(path), error)
        return {'exists': None, 'error': type(error).__name__}

def keys(path):
    result = []
    try: content = read_text(path, 262144)
    except FileNotFoundError: return result
    except (OSError, UnicodeError, ValueError) as error:
        failure('keys:' + str(path), error)
        return [{'error': type(error).__name__}]
    for line in content.splitlines():
        if not line.strip() or line.lstrip().startswith('#'): continue
        match = re.search(r'(?:^|\s)(ssh-[\w@.+-]+|ecdsa-[\w@.+-]+|sk-[\w@.+-]+)\s+([A-Za-z0-9+/]+={0,2})(?:\s|$)', line)
        if not match:
            result.append({'invalid': True}); continue
        try:
            blob = base64.b64decode(match[2], validate=True)
            n = int.from_bytes(blob[:4], 'big')
            assert blob[4:4+n].decode() == match[1]
            fp = 'SHA256:' + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('=')
            checked = subprocess.run(['/usr/bin/ssh-keygen', '-lf', '-'], input=match[1] + ' ' + match[2] + '\n',
                                     capture_output=True, text=True, timeout=3)
            if checked.returncode or fp not in checked.stdout:
                result.append({'invalid': True}); continue
            result.append({'fingerprint': fp, 'algorithm': match[1], 'comment': line[match.end():].strip(),
                           'has_options': bool(line[:match.start()].strip())})
        except (OSError, subprocess.SubprocessError) as error:
            failure('key-validation:' + str(path), error)
            result.append({'error': type(error).__name__})
        except Exception: result.append({'invalid': True})
    return result

def profile(path, user):
    result = {'path': str(path), **metadata(path)}
    if not result['exists']: return result
    result['readable_by_account'] = subprocess.run(['runuser', '-u', user, '--', 'test', '-r', str(path)], capture_output=True, timeout=5).returncode == 0
    try:
        value = json.loads(read_text(path, 16384))
        result.update({key: value.get(key) for key in ['version', 'ssh_host', 'ssh_port', 'ssh_user', 'remote_port', 'local_port']})
        result['has_http_credentials'] = bool(value.get('username') and value.get('password'))
        fields = {'version', 'release', 'ssh_host', 'ssh_port', 'ssh_user', 'remote_port', 'local_port', 'url', 'username', 'password'}
        result['valid_connection'] = (set(value) == fields and type(value.get('version')) is int and value['version'] == 1
            and value.get('ssh_port') == 22 and value.get('ssh_user') == user
            and isinstance(value.get('release'), str) and bool(value['release'])
            and isinstance(value.get('ssh_host'), str) and bool(value['ssh_host'])
            and all(type(value.get(key)) is int and 1024 <= value[key] <= 65535 for key in ('remote_port', 'local_port'))
            and value.get('url') == 'http://127.0.0.1:' + str(value.get('local_port')) and value.get('username') == 'quantcode'
            and isinstance(value.get('password'), str) and bool(re.fullmatch(r'[A-Za-z0-9_-]{32,128}', value['password'])))
        port = value.get('remote_port')
        if isinstance(port, int) and 0 < port < 65536 and result['has_http_credentials']:
            headers = {'Authorization': 'Basic ' + base64.b64encode((value['username'] + ':' + value['password']).encode()).decode()}
            url = 'http://127.0.0.1:' + str(port) + '/experimental/quantcode/identities'
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=8) as response:
                    raw = response.read(65537)
                    if len(raw) > 65536: raise ValueError('oversize identity response')
                    data = json.loads(raw)
                    result['http_status'] = response.status
                result['identities'] = [{k: entry.get(k) for k in ['fingerprint', 'group', 'groups']} for entry in data.get('identities', [])]
                result['has_session'] = bool(data.get('session'))
                result['has_identity_error'] = bool(data.get('error'))
            except urllib.error.HTTPError as error: result['http_status'] = error.code
            except Exception as error: result['http_error'] = type(error).__name__
    except Exception as error: result['profile_error'] = type(error).__name__
    return result

def account_details(user):
    home = Path(user.pw_dir)
    path = home / '.ssh/authorized_keys'
    result = {'username': user.pw_name, 'uid': user.pw_uid, 'gid': user.pw_gid, 'home': user.pw_dir,
              'shell': user.pw_shell, 'comment': user.pw_gecos, 'home_metadata': metadata(home),
              'ssh_directory': metadata(home / '.ssh'), 'authorized_keys_metadata': metadata(path), 'keys': keys(path),
              'groups': [grp.getgrgid(gid).gr_name for gid in os.getgrouplist(user.pw_name, user.pw_gid)]}
    result['profiles'] = [profile(p, user.pw_name) for p in [home / '.quantcode/test-v1/connection.json', home / '.quantcode/admin/connection.json'] if p.exists()]
    route = Path('/etc/quantcode-ssh-workspaces') / (str(user.pw_uid) + '.json')
    result['route_metadata'] = metadata(route)
    if route.exists():
        try: result['route_file'] = json.loads(read_text(route, 32768))
        except Exception as error: result['route_error'] = type(error).__name__
    if not user.pw_name.startswith('qc-'):
        try:
            process = subprocess.run(['runuser', '-u', user.pw_name, '--', '/usr/local/bin/quantcode-connect'], capture_output=True, text=True, timeout=4)
            result['discovery'] = json.loads(process.stdout) if process.returncode == 0 else {'error': 'exit ' + str(process.returncode)}
        except Exception as error: result['discovery'] = {'error': type(error).__name__}
    process = subprocess.run(['/usr/sbin/sshd', '-T', '-C', 'user=' + user.pw_name + ',host=localhost,addr=127.0.0.1'], capture_output=True, text=True, timeout=4)
    if process.returncode == 0:
        settings = dict(line.split(' ', 1) for line in process.stdout.splitlines() if ' ' in line)
        result['sshd'] = {key: settings[key] for key in ['pubkeyauthentication', 'authorizedkeysfile', 'authorizedkeyscommand',
            'allowtcpforwarding', 'disableforwarding', 'permitopen', 'forcecommand', 'allowusers', 'denyusers', 'allowgroups', 'denygroups', 'authenticationmethods'] if key in settings}
    else: result['sshd_error'] = process.returncode
    return result



def account(user):
    try: return account_details(user)
    except Exception as error:
        failure('account:' + user.pw_name, error)
        return {'username': user.pw_name, 'uid': user.pw_uid, 'gid': user.pw_gid, 'home': user.pw_dir,
                'shell': user.pw_shell, 'keys': [], 'profiles': [], 'groups': [], 'collection_error': type(error).__name__}

def collect(server):
    global SERVER
    SERVER = server
    ERRORS.clear()
    users = [user for user in pwd.getpwall() if user.pw_uid == 0 or 1000 <= user.pw_uid < 65534 or (Path(user.pw_dir) / '.ssh/authorized_keys').is_file()]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        accounts = list(pool.map(account, users))
    result = {'server': SERVER, 'accounts': accounts, 'host_keys': keys(Path('/etc/ssh/ssh_host_ed25519_key.pub')),
              'helper_metadata': metadata(Path('/usr/local/bin/quantcode-connect')),
              'registry_directory': metadata(Path('/etc/quantcode-ssh-workspaces'))}
    if SERVER == 'server-c':
        try: import yaml
        except ImportError as error: failure('yaml', error)
        result['rosters'] = {}
        for filename in ['/etc/quantcode-test-v1/roster.yaml', '/var/lib/quantcode-test-v1/gateway/roster.yaml']:
            try:
                path = Path(filename)
                content = read_text(path).encode()
                roster = yaml.safe_load(content)
                sanitized = [{k: value for k, value in entry.items() if k != 'public_key'} for entry in roster['bindings']]
                for source, target in zip(roster['bindings'], sanitized):
                    try:
                        blob = base64.b64decode(source['public_key'].split()[1], validate=True)
                        target['public_key_matches_fingerprint'] = source['fingerprint'] == 'SHA256:' + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('=')
                    except Exception: target['public_key_matches_fingerprint'] = False
                result['rosters'][filename] = {'metadata': metadata(path), 'sha256': hashlib.sha256(content).hexdigest(),
                                            'status': roster.get('status'), 'bindings': sanitized}
            except Exception as error:
                failure('roster:' + filename, error)
                result['rosters'][filename] = {'error': type(error).__name__}
        try:
            registry_path = Path('/etc/quantcode/research-identities.json')
            registry = json.loads(read_text(registry_path))
            result['research_registry'] = {'metadata': metadata(registry_path), 'accounts': {actor: {key: value for key, value in account.items() if key in ['username', 'uid', 'gid', 'workspace_path', 'fingerprints', 'runtime_status', 'runtime_commit']} for actor, account in registry['accounts'].items()}}
        except Exception as error:
            failure('research_registry', error)
            result['research_registry'] = {'accounts': {}, 'error': type(error).__name__}
        try:
            registry_path = Path('/etc/quantcode-admin/registry.json')
            registry = json.loads(read_text(registry_path))
            result['admin_registry'] = {'metadata': metadata(registry_path), 'accounts': {actor: {key: value for key, value in account.items() if key in ['username', 'uid', 'gid', 'workspace_path', 'fingerprints']} for actor, account in registry['accounts'].items()}}
        except Exception as error:
            failure('admin_registry', error)
            result['admin_registry'] = {'accounts': {}, 'error': type(error).__name__}
        try:
            unit_rows = subprocess.check_output(['systemctl', 'list-units', '--all', '--no-legend', '--no-pager', 'quantcode-native-*'], text=True, timeout=5).splitlines()
            units = []
            for row in unit_rows:
                unit = next(value for value in row.split() if value.endswith('.service'))
                try:
                    info = dict(line.split('=', 1) for line in subprocess.check_output(['systemctl', 'show', unit, '-p', 'Id', '-p', 'User', '-p', 'ActiveState', '-p', 'MainPID'], text=True, timeout=5).splitlines() if '=' in line)
                    pid = info.get('MainPID')
                    if pid and pid != '0':
                        try:
                            environ = dict(entry.split('=', 1) for entry in Path('/proc/' + pid + '/environ').read_text().split('\0') if '=' in entry)
                            key_files = [environ.get('QUANTCODE_PUBLIC_KEY_FILE', ''), *environ.get('QUANTCODE_PUBLIC_KEY_FILES', '').split(',')]
                            info['public_key_files'] = [{'path': name, 'keys': keys(Path(name)), 'metadata': metadata(Path(name))} for name in dict.fromkeys(key_files) if name]
                        except Exception as error: info['inspection_error'] = type(error).__name__
                    units.append(info)
                except Exception as error:
                    failure('unit:' + unit, error)
                    units.append({'Id': unit, 'inspection_error': type(error).__name__})
            result['native_units'] = units
        except Exception as error:
            failure('native_units', error)
            result['native_units'] = []
    from datetime import datetime, timezone
    import socket
    result['observed_at_utc'] = datetime.now(timezone.utc).isoformat()
    result['hostname'] = socket.gethostname()
    result['kernel'] = os.uname().release
    os_release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    result['operating_system'] = os_release.get('PRETTY_NAME', '').strip(chr(34))
    settings = dict(line.split(' ', 1) for line in subprocess.check_output(['/usr/sbin/sshd', '-T'], text=True, timeout=5).splitlines() if ' ' in line)
    result['ssh_ports'] = [line.split(' ', 1)[1] for line in subprocess.check_output(['/usr/sbin/sshd', '-T'], text=True, timeout=5).splitlines() if line.startswith('port ')]
    result['ssh_policy'] = {k: settings.get(k) for k in ['permitrootlogin', 'pubkeyauthentication', 'passwordauthentication', 'allowtcpforwarding', 'disableforwarding', 'permitopen', 'authorizedkeysfile', 'authorizedkeyscommand', 'trustedusercakeys']}
    result['authorized_keys2'] = [{'username': user.pw_name, 'keys': keys(Path(user.pw_dir) / '.ssh/authorized_keys2')} for user in users if (Path(user.pw_dir) / '.ssh/authorized_keys2').exists()]
    for user in result['accounts']:
        try:
            proc = subprocess.run(['sudo', '-n', '-l', '-U', user['username']], capture_output=True, text=True, timeout=5)
            rules = [line.strip() for line in proc.stdout.splitlines() if line.strip().startswith('(')]
            all_rules = [rule for rule in rules if re.match(r'^\(ALL(?:\s*:\s*ALL)?\)\s*(?:NOPASSWD:\s*)?ALL$', rule)]
            if user['uid'] == 0: value = 'root'
            elif any('NOPASSWD:' in rule for rule in all_rules): value = 'NOPASSWD_ALL'
            elif all_rules: value = 'ALL'
            elif rules: value = 'LIMITED'
            elif proc.returncode == 0 and 'not allowed' in proc.stdout: value = 'NONE'
            elif 'not allowed' in proc.stdout + proc.stderr: value = 'NONE'
            else: value = 'UNKNOWN'
            user['sudo_policy'] = {'kind': value, 'rule_count': len(rules)}
        except Exception as error: user['sudo_policy'] = {'kind': 'UNKNOWN', 'error': type(error).__name__}
    result['collection_errors'] = sorted(ERRORS, key=lambda error: error['stage'])
    return result


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in ('server-a', 'server-b', 'server-c'):
        raise SystemExit('expected server-a, server-b or server-c')
    print(json.dumps(collect(sys.argv[1]), ensure_ascii=False))
