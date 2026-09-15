"""Read A/B/C into a dated, error-tolerant local registration document."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

if __package__:
    from .server_account_register import SERVERS, analyze, envelope, normalize, now, render, snapshot_changes
else:
    from server_account_register import SERVERS, analyze, envelope, normalize, now, render, snapshot_changes

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_HOSTS = dict(zip(SERVERS, ('qs-data', 'qs-compute', 'qs-gpu')))


def write(path, content, private=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.register-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            os.fchmod(stream.fileno(), 0o600 if private else 0o644)
            stream.write(content); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_json(path, default=None):
    try: return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError): return {} if default is None else default


def collect(server, host, user, previous, code, timeout=90, run=subprocess.run):
    attempted = now()
    try:
        result = run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', '-l', user, host,
                      'sudo -n python3 - ' + server], input=code, capture_output=True, text=True, encoding='utf-8', timeout=timeout)
        if result.returncode:
            message = 'SSH/采集命令失败，退出码 ' + str(result.returncode)
            if 'Permission denied' in result.stderr: message = 'SSH 管理账号认证失败'
            if 'Host key verification' in result.stderr: message = 'SSH 主机公钥核验失败'
            return envelope(server, previous=previous, error=message, attempted_at=attempted)
        data = json.loads(result.stdout)
        if not isinstance(data, dict) or data.get('server') != server or not isinstance(data.get('accounts'), list) or not data.get('observed_at_utc'):
            raise ValueError('invalid snapshot')
        data['ssh_collection_alias'] = host
        config = run(['ssh', '-G', '-l', user, host], capture_output=True, text=True, encoding='utf-8', timeout=5)
        settings = dict(line.split(' ', 1) for line in config.stdout.splitlines() if ' ' in line)
        data['ssh_endpoint'] = {'host': settings.get('hostname', host), 'port': settings.get('port', '未核验')}
        return envelope(server, data, previous, attempted_at=attempted)
    except subprocess.TimeoutExpired:
        return envelope(server, previous=previous, error='SSH 采集超时', attempted_at=attempted)
    except (OSError, ValueError):
        return envelope(server, previous=previous, error='无法执行采集或解析本次结果', attempted_at=attempted)


def latest_release():
    if not shutil.which('gh'): return {'status': 'unknown', 'checked_at': now(), 'reason': 'gh unavailable'}
    try:
        result = subprocess.run(['gh', 'api', 'repos/HKUST-QUANT-SOCIETY/quantcode/releases?per_page=10'], capture_output=True, text=True, encoding='utf-8', timeout=15, check=True)
        releases = [item for item in json.loads(result.stdout) if not item.get('draft') and item.get('published_at')]
        item = max(releases, key=lambda item: item['published_at'])
        return {'status': 'published', 'tag': item['tag_name'], 'url': item['html_url'], 'published_at': item['published_at'], 'prerelease': item.get('prerelease'), 'checked_at': now()}
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        return {'status': 'unknown', 'checked_at': now(), 'reason': 'release lookup failed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, default=PROJECT / '.quantcode/server-account-register')
    parser.add_argument('--output', type=Path, default=PROJECT / 'docs/ops/SERVER_ACCOUNT_REGISTER.md')
    parser.add_argument('--annotations', type=Path)
    parser.add_argument('--offline', action='store_true', help='render existing snapshots without SSH or GitHub requests')
    parser.add_argument('--host', action='append', default=[], help='override a known server alias, e.g. server-a=qs-data')
    parser.add_argument('--ssh-user', default='ubuntu')
    args = parser.parse_args()
    hosts = dict(DEFAULT_HOSTS)
    for mapping in args.host:
        name, value = mapping.split('=', 1)
        if name not in hosts or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.:-]*', value): parser.error('invalid server alias')
        hosts[name] = value
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,63}', args.ssh_user): parser.error('invalid SSH administrator username')
    state = args.state_dir.resolve(); state.mkdir(parents=True, exist_ok=True); state.chmod(0o700)
    before = {server: read_json(state / (server + '.json')) for server in SERVERS}
    if args.offline:
        snapshots = {server: normalize(server, value) for server, value in before.items()}
        release = read_json(state / 'release.json')
    else:
        code = (Path(__file__).parent / 'server_account_register_collect.py').read_text(encoding='utf-8')
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {server: pool.submit(collect, server, hosts[server], args.ssh_user, before[server], code) for server in SERVERS}
            snapshots = {server: future.result() for server, future in futures.items()}
        release = latest_release()
    annotations_path = args.annotations or state / 'annotations.json'
    annotations = {}
    if annotations_path.exists():
        try:
            annotations = json.loads(annotations_path.read_text(encoding='utf-8'))
            if not isinstance(annotations, dict) or any(not isinstance(annotations.get(key, {}), dict) for key in ('actors', 'accounts', 'keys')) or not isinstance(annotations.get('login_checks', []), list): raise ValueError('invalid annotation structure')
        except (OSError, ValueError): raise SystemExit('人工登记文件结构无效；请修复文件，原文档保留。')
    report = analyze(snapshots, annotations)
    changes = [] if args.offline else snapshot_changes(before, snapshots)
    content = render(report, changes, release)
    version = 'unknown'; dirty = None
    if shutil.which('git'):
        version = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=PROJECT, capture_output=True, text=True).stdout.strip() or 'unknown'
        dirty = bool(subprocess.run(['git', 'status', '--porcelain', '--', 'scripts/server_account_register.py', 'scripts/server_account_register_collect.py', 'scripts/sync_server_account_register.py'], cwd=PROJECT, capture_output=True, text=True).stdout.strip())
    content += f'\n工具来源提交：{version}；工具有未提交改动：{dirty}。确切脚本哈希、快照与差异保存在本次 manifest.json。\n'
    run_id = now().replace(':', '').replace('+', '-') + '-' + uuid.uuid4().hex[:6]
    manifest = {'run_id': run_id, 'generated_at': now(), 'tool_commit': version, 'tool_dirty': dirty,
                'tool_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in Path(__file__).parent.glob('*server_account_register*.py')},
                'document_sha256': hashlib.sha256(content.encode()).hexdigest(), 'changes': changes,
                'servers': {server: {key: snap.get(key) for key in ('status', 'attempted_at', 'last_success_at', 'error')} for server, snap in snapshots.items()}}
    history = state / 'history' / run_id
    for server, snapshot in snapshots.items():
        serialized = json.dumps(snapshot, ensure_ascii=False, indent=2)
        write(history / (server + '.json'), serialized)
        write(state / (server + '.json'), serialized)
    for filename, value in [('manifest.json', manifest), ('analysis.json', report), ('release.json', release)]:
        serialized = json.dumps(value, ensure_ascii=False, indent=2)
        write(history / filename, serialized); write(state / filename, serialized)
    write(args.output, content, private=False)
    failed = [server for server, snapshot in snapshots.items() if snapshot['status'] != 'ok']
    print(json.dumps({'document': str(args.output.resolve()), 'run_id': run_id, 'records': len(report['records']), 'chains': len(report['chains']),
                      'servers_requiring_attention': failed, 'changes': len(changes)}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
