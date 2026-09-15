"""Server-backed registration analysis and Markdown rendering (no remote writes)."""
from collections import defaultdict
from datetime import datetime, timezone
import json

SERVERS = ('server-a', 'server-b', 'server-c')
ROSTERS = ('/etc/quantcode-test-v1/roster.yaml', '/var/lib/quantcode-test-v1/gateway/roster.yaml')
SUDO = {'root': 'root', 'NOPASSWD_ALL': '免密全部命令', 'ALL': '全部命令', 'LIMITED': '指定命令', 'NONE': '无', 'UNKNOWN': '未核验'}


def now():
    return datetime.now(timezone.utc).isoformat()


def envelope(server, data=None, previous=None, error=None, attempted_at=None):
    """A failed attempt retains explicitly dated evidence, never fresh-looking data."""
    attempted_at = attempted_at or now()
    old = previous or {}
    if old.get('schema_version') != 2:
        old = {'data': old, 'last_success_at': old.get('observed_at_utc')}
    if data is None:
        return {'schema_version': 2, 'server': server, 'attempted_at': attempted_at, 'status': 'failed',
                'error': error or '本次采集未完成', 'data': old.get('data', {}), 'last_success_at': old.get('last_success_at')}
    observed = data.get('observed_at_utc', attempted_at)
    partial = bool(data.get('collection_errors'))
    return {'schema_version': 2, 'server': server, 'attempted_at': attempted_at,
            'status': 'partial' if partial else 'ok', 'data': data,
            'last_success_at': old.get('last_success_at') if partial else observed}


def normalize(server, value):
    if not value: return envelope(server, error='尚无本次采集结果')
    if value.get('server') != server or value.get('schema_version') == 2 and value.get('data', {}).get('server', server) != server:
        return envelope(server, error='快照服务器标识不一致，未采用该数据')
    return value if value.get('schema_version') == 2 else envelope(server, value, attempted_at=value.get('observed_at_utc'))


def fps(account):
    return {key['fingerprint'] for key in account.get('keys', []) if key.get('fingerprint')}


def private_file(info, uid):
    try: mode = int(info.get('mode', '0'), 8)
    except (ValueError, TypeError): return False
    return info.get('exists') is True and info.get('regular') is True and not info.get('symlink') and info.get('uid') in (0, uid) and not mode & 0o022


def identity_entries(data, path=ROSTERS[1]):
    value = data.get('rosters', {}).get(path, {})
    return value.get('bindings', []) if isinstance(value, dict) else []


def groups(entry):
    value = entry.get('groups') or [entry.get('group')]
    return value if isinstance(value, list) and all(isinstance(item, str) for item in value) else []


def check_chain(snapshots, source_server, source, target_server, target_name, fingerprint, route=None):
    """Keep configuration, runtime/API checks and human login evidence separate."""
    result = {'source_id': f"{source_server}:{source['username']}", 'target_id': f'{target_server}:{target_name}',
              'fingerprint': fingerprint, 'route_exists': route is not None, 'configuration': 'complete',
              'interface': 'unknown', 'full_login': 'unverified', 'gaps': [], 'actor_id': None}
    def gap(message, unknown=False):
        result['gaps'].append(message)
        if not unknown or result['configuration'] == 'complete': result['configuration'] = 'unknown' if unknown else 'incomplete'
    stale = any(snapshots.get(server, {}).get('status') == 'failed' or server not in snapshots for server in {source_server, target_server, 'server-c'})
    def finish():
        if stale: result.update(configuration='unknown', interface='unknown')
        return result
    for server in {source_server, target_server, 'server-c'}:
        if server not in snapshots or snapshots[server].get('status') == 'failed': gap(server + ' 本次采集失败，历史值不能证明当前链路', True)
    data = snapshots.get(target_server, {}).get('data', {})
    target = next((user for user in data.get('accounts', []) if user['username'] == target_name), None)
    if source.get('collection_error') or any(key.get('error') for key in source.get('keys', [])): gap('旧账号 SSH 公钥未能读取', True)
    elif fingerprint not in fps(source): gap('旧账号未登记此公钥')
    if source.get('collection_error'): gap('旧账号资料采集失败', True)
    if not private_file(source.get('authorized_keys_metadata', {}), source.get('uid')): gap('旧账号公钥文件权限或归属未通过核验')
    if route is not None:
        if fingerprint not in route.get('fingerprints', []): gap('工作区描述未允许此公钥')
        meta = source.get('route_metadata', {})
        saved = source.get('route_file', {})
        if not private_file(meta, 0) or saved.get('uid') != source.get('uid') or saved.get('username') != source['username']:
            gap('工作区描述的归属或 UID 不一致')
        if route not in saved.get('routes', []): gap('工作区描述与实际读取结果不一致')
    if not target:
        gap('目标研究账号不存在或未采集')
        return finish()
    if target.get('collection_error'): gap('目标研究账号采集失败', True)
    if target.get('collection_error') or any(key.get('error') for key in target.get('keys', [])): gap('目标研究账号 SSH 公钥未能读取', True)
    elif fingerprint not in fps(target): gap('目标研究账号未登记此 SSH 公钥')
    if not private_file(target.get('authorized_keys_metadata', {}), target.get('uid')): gap('目标公钥文件权限或归属未通过核验')
    for field in ('home_metadata', 'ssh_directory'):
        meta = target.get(field, {})
        if meta.get('exists') is not True or meta.get('uid') not in (0, target.get('uid')) or meta.get('symlink') or int(meta.get('mode', '0'), 8) & 0o022:
            gap('目标 ' + field + ' 权限或归属未通过核验')
    sshd = target.get('sshd', {})
    if sshd.get('pubkeyauthentication') != 'yes' or sshd.get('allowtcpforwarding') not in ('yes', 'local') or sshd.get('disableforwarding') != 'no':
        gap('目标 SSH 公钥认证或端口转发未确认可用')
    authority = snapshots.get('server-c', {}).get('data', {})
    admin = target_name == 'quantadmin' and 'quant-admin' in target.get('groups', [])
    entries = [entry for entry in identity_entries(authority) if entry.get('fingerprint') == fingerprint and
               (entry.get('actor_id') == 'quantadmin' if admin else entry.get('workspace_path') == target.get('home'))]
    if len(entries) != 1:
        unavailable = not authority.get('rosters', {}).get(ROSTERS[1]) or authority.get('rosters', {}).get(ROSTERS[1], {}).get('error')
        gap('正式名册未能读取' if unavailable else '正式名册没有唯一匹配的公钥与工作区', bool(unavailable))
        return finish()
    entry = entries[0]
    if not entry.get('actor_id') or not groups(entry) or entry.get('role') not in ('admin', 'approver', 'analyst'):
        gap('正式名册成员或授权字段不完整'); return finish()
    actor = entry['actor_id']; result['actor_id'] = actor
    for path in ROSTERS:
        roster = authority.get('rosters', {}).get(path, {})
        matching = [row for row in roster.get('bindings', []) if row.get('fingerprint') == fingerprint]
        if roster.get('error') or not roster: gap('无法读取正式名册：' + path, True)
        elif roster.get('status') == 'REVIEW_REQUIRED' or matching != [entry] or not entry.get('public_key_matches_fingerprint'):
            gap('两份名册、公钥指纹或授权不一致')
    registry = data.get('admin_registry' if admin else 'research_registry', {})
    enrolled = registry.get('accounts', {}).get(actor, {})
    runtime_user = next((user for user in data.get('accounts', []) if user['username'] == enrolled.get('username')), None)
    if registry.get('error') or not registry: gap('研究账号注册表未采集', True)
    elif not private_file(registry.get('metadata', {}), 0): gap('研究账号注册表的权限或归属未核验', True)
    elif not runtime_user or fingerprint not in enrolled.get('fingerprints', []) or any(enrolled.get(key) != runtime_user.get(key) for key in ('username', 'uid', 'gid')) or enrolled.get('workspace_path') != entry.get('workspace_path'):
        gap('研究账号注册表、公钥或 Linux 身份不一致')
    profile = next((profile for profile in target.get('profiles', []) if profile.get('ssh_user') == target_name), None)
    if not profile or not profile.get('readable_by_account') or not profile.get('has_http_credentials') or profile.get('profile_error'):
        gap('个人连接 profile 缺失、损坏或当前 SSH 账号不可读')
    elif profile.get('valid_connection') is not True:
        gap('个人连接 profile 不符合客户端契约' if profile.get('valid_connection') is False else '个人连接 profile 契约尚未核验', profile.get('valid_connection') is not False)
    unit = next((unit for unit in data.get('native_units', []) if unit.get('User') == (runtime_user or target)['username']), None)
    configured_keys = {key.get('fingerprint') for file in (unit or {}).get('public_key_files', [])
                       if private_file(file.get('metadata', {}), (runtime_user or target).get('uid')) for key in file.get('keys', [])}
    if not unit or unit.get('inspection_error') or 'public_key_files' not in unit: gap('宿主配置未采集或无法读取', True)
    elif fingerprint not in configured_keys: gap('宿主公钥列表缺少此公钥')
    if unit and unit.get('ActiveState') != 'active': result['gaps'].append('宿主服务当前不是 active')
    if profile:
        declared = next((row for row in profile.get('identities', []) if row.get('fingerprint') == fingerprint), None)
        if profile.get('http_status') == 200 and not profile.get('has_identity_error') and declared and set(groups(declared)) == set(groups(entry)) and unit and unit.get('ActiveState') == 'active':
            result['interface'] = 'available'
        elif profile.get('http_status') or profile.get('http_error'):
            result['interface'] = 'unavailable'
            result['gaps'].append('身份接口不可用或授权列表不匹配：' + str(profile.get('http_status') or profile.get('http_error')))
    return finish()


def analyze(snapshots, annotations=None):
    annotations = annotations or {}
    snapshots = {server: normalize(server, snapshots.get(server, {})) for server in SERVERS}
    actors = defaultdict(list)
    for row in identity_entries(snapshots['server-c'].get('data', {})):
        if row.get('actor_id'): actors[row['actor_id']].append(row)
    records = []
    chains = []
    for server, snapshot in snapshots.items():
        for user in snapshot.get('data', {}).get('accounts', []):
            account_id = server + ':' + user['username']
            details = annotations.get('accounts', {}).get(account_id, {})
            system = user['username'] in ('root', 'ubuntu') or user['username'].startswith('qc-sim-')
            known_actor = next((actor for actor, entries in actors.items() if entries[0].get('workspace_path') == user.get('home')), None)
            row = {'server': server, 'id': account_id, 'account': user, 'observed_at': snapshot.get('data', {}).get('observed_at_utc'),
                   'current': snapshot.get('status') != 'failed', 'kind': '管理/测试账号' if system else '研究账号' if known_actor else '旧 SSH 账号',
                   'onboarding': details.get('onboarding', '无需普通成员入口' if system else '已开通' if known_actor else '待确认归属/是否需要产品入口'),
                   'name': details.get('name') or '人员归属待确认',
                   'owner': details.get('owner') or ('平台运维（未指定个人）' if system else '管理员待指派'),
                   'next_action': details.get('next_action') or ('系统管理/测试账号，无普通成员开通待办' if system else '核对账号归属、在用公钥及产品入口需求'),
                   'completed_at': details.get('completed_at') or ('不适用' if system else '未完成'), 'source': details.get('source') or '服务器采集；人员归属未确认'}
            records.append(row)
            routes = user.get('discovery', {}).get('routes', [])
            for route in routes:
                if route.get('serverId') not in SERVERS or not route.get('username'): continue
                for fp in sorted(fps(user) | set(route.get('fingerprints', []))):
                    chains.append(check_chain(snapshots, server, user, route['serverId'], route['username'], fp, route))
            if not routes and user.get('profiles'):
                for fp in sorted(fps(user)):
                    chain = check_chain(snapshots, server, user, server, user['username'], fp)
                    chain['entry_kind'] = '直接研究/管理员入口'
                    chains.append(chain)
            if not routes and not user.get('profiles') and not system and user['username'] != 'quantadmin' and not known_actor:
                for fp in sorted(fps(user)):
                    matched = [actor for actor, entries in actors.items() if any(entry.get('fingerprint') == fp for entry in entries)]
                    chains.append({'source_id': account_id, 'target_id': '未发现工作区入口', 'fingerprint': fp,
                                   'route_exists': False, 'entry_kind': 'missing', 'configuration': 'incomplete' if row['current'] else 'unknown',
                                   'interface': 'unknown', 'full_login': 'unverified', 'actor_id': matched[0] if len(matched) == 1 else None,
                                   'gaps': ['旧账号没有工作区描述或直接研究 profile']})
    for chain in chains:
        proofs = [proof for proof in annotations.get('login_checks', []) if proof.get('source_id') == chain['source_id'] and proof.get('fingerprint') == chain['fingerprint'] and proof.get('observed_at') and proof.get('source')]
        chain['last_login'] = max(proofs, key=lambda proof: proof['observed_at']) if proofs else None
        if chain['last_login']:
            proof = chain['last_login']
            chain['full_login'] = proof.get('result', 'unverified')
            if chain['full_login'] == 'passed' and (not proof.get('os') or not proof.get('client_version')):
                chain['full_login'] = 'reported-incomplete'
    for row in records:
        if row['onboarding'] == '待确认归属/是否需要产品入口' and any(chain.get('actor_id') for chain in chains if chain['source_id'] == row['id']):
            row['onboarding'] = '已有关联；以逐钥核验为准'
    return {'snapshots': snapshots, 'records': records, 'actors': dict(actors), 'chains': chains, 'annotations': annotations}


def snapshot_changes(before, after):
    changes = []
    for server in SERVERS:
        old, new = normalize(server, before.get(server, {})), normalize(server, after.get(server, {}))
        if new.get('status') == 'failed':
            changes.append({'server': server, 'kind': 'collection_failed', 'detail': new.get('error')}); continue
        if not old.get('data'): continue
        previous = {u['username']: u for u in old['data'].get('accounts', [])}
        current = {u['username']: u for u in new['data'].get('accounts', [])}
        for user in sorted(previous.keys() | current.keys()):
            account_id = server + ':' + user
            if user not in previous: changes.append({'server': server, 'account_id': account_id, 'kind': 'account_added'}); continue
            if user not in current:
                if not new['data'].get('collection_errors'): changes.append({'server': server, 'account_id': account_id, 'kind': 'account_removed'})
                continue
            for fp in sorted(fps(current[user]) - fps(previous[user])): changes.append({'server': server, 'account_id': account_id, 'kind': 'key_added', 'fingerprint': fp})
            for fp in sorted(fps(previous[user]) - fps(current[user])):
                if not current[user].get('collection_error') and not any(key.get('error') or key.get('invalid') for key in current[user].get('keys', [])):
                    changes.append({'server': server, 'account_id': account_id, 'kind': 'key_removed', 'fingerprint': fp})
            for field in ('uid', 'gid', 'home', 'shell', 'groups', 'discovery', 'profiles', 'sudo_policy', 'home_metadata', 'ssh_directory', 'authorized_keys_metadata', 'route_metadata'):
                if previous[user].get(field) != current[user].get(field):
                    changes.append({'server': server, 'account_id': account_id, 'kind': 'profile_observation_changed' if field == 'profiles' else field + '_changed'})
        old_grants = {(row.get('actor_id'), row.get('fingerprint')): row for row in identity_entries(old['data'])}
        new_roster = new['data'].get('rosters', {}).get(ROSTERS[1], {})
        if not new_roster.get('error'):
            new_grants = {(row.get('actor_id'), row.get('fingerprint')): row for row in identity_entries(new['data'])}
            for key in old_grants.keys() | new_grants.keys():
                if old_grants.get(key) != new_grants.get(key):
                    changes.append({'server': server, 'kind': 'organization_grant_changed', 'actor_id': key[0], 'fingerprint': key[1]})
    return changes


def cell(value):
    return str(value if value is not None else '未记录').replace('|', '\\|').replace('\r', ' ').replace('\n', ' ').replace('<', '&lt;').replace('>', '&gt;').replace('`', '')


def render(report, changes=None, release=None):
    snapshots, records, chains = report['snapshots'], report['records'], report['chains']
    annotations = report['annotations']
    keyset = sorted({fp for row in records for fp in fps(row['account'])} | {entry['fingerprint'] for rows in report['actors'].values() for entry in rows if entry.get('fingerprint')})
    key_ids = {fp: f'K{i:03d}' for i, fp in enumerate(keyset, 1)}
    ref = lambda values: ', '.join(key_ids.get(fp, fp) for fp in sorted(set(values))) or '无'
    attempt = max((s.get('attempted_at') or '' for s in snapshots.values()), default='')
    lines = ['# Server A / B / C 实际账号登记', '', f'本次同步尝试：**{cell(attempt)}**（时间含时区）。服务器实际账号和公钥为登记事实来源；产品角色、组和工作目录取自正式组织授权。', '',
             '稳定标识为“服务器 ID:登录名”和完整 SHA256 公钥指纹。K 编号仅用于本文索引。姓名、责任人、密钥用途和登录实测来自独立人工登记，缺少确认时明确留空；它们不会反向修改服务器授权。', '',
             '## 采集状态与来源', '', '| 服务器 | 本次采集 | 尝试时间 | 显示数据时间 | 最后完整采集成功 | 账号记录 | 错误 |', '| --- | --- | --- | --- | --- | ---: | --- |']
    for server, snapshot in snapshots.items():
        data = snapshot.get('data', {})
        status = {'ok': '本次成功', 'partial': '本次部分采集失败', 'failed': '本次采集失败；显示历史值'}[snapshot['status']]
        errors = snapshot.get('error') or '; '.join(e.get('stage', '') + ':' + e.get('kind', '') for e in data.get('collection_errors', [])) or '无'
        lines.append('| ' + ' | '.join(map(cell, [server, status, snapshot.get('attempted_at'), data.get('observed_at_utc'), snapshot.get('last_success_at'), len(data.get('accounts', [])), errors])) + ' |')
    current = sum(row['current'] for row in records)
    lines += ['', f'本次当前账号记录 {current} 条；保留历史记录 {len(records)-current} 条。显示 {len(keyset)} 把公钥、{len(report["actors"])} 个可读取/保留的产品身份。C 的名册采集异常时，身份总数未完整核验；历史值不计作本次验证成功。', '',
              '核验分四层：①路由是否存在；②具体公钥的配置链路是否齐全（含目标 SSH 公钥、注册表、profile、宿主公钥和正式名册）；③当前接口是否可用；④本人是否完成登录。接口返回 200 或存在会话均不自动计为本人完整登录。', '',
              '| 服务器 | 主机名 / SSH 地址 | 系统 | SSH 密码认证 / root 登录 / 转发 |', '| --- | --- | --- | --- |']
    for server, snapshot in snapshots.items():
        data = snapshot.get('data', {}); policy = data.get('ssh_policy', {}); endpoint = data.get('ssh_endpoint', {})
        address = str(endpoint.get('host', data.get('ssh_collection_alias', '未采集'))) + ':' + str(endpoint.get('port', '未核验'))
        lines.append('| ' + ' | '.join(map(cell, [server, str(data.get('hostname', '未采集')) + ' / ' + address, data.get('operating_system'), ' / '.join(str(policy.get(key, '未核验')) for key in ('passwordauthentication', 'permitrootlogin', 'allowtcpforwarding'))])) + ' |')
    lines += ['', '## 客户端发布与成员使用视图', '']
    if release and release.get('status') == 'published':
        lines.append(f"已核对发布版本：**{cell(release.get('tag'))}**，状态：{'公开预发布' if release.get('prerelease') else '公开发布'}；核对时间 {cell(release.get('checked_at'))}。成员实际安装版本必须单独记录。[发布页]({release['url']})。")
    else: lines.append('本次未取得最新发布状态；不从源码版本推断成员已经安装更新。')
    lines += ['', '| 产品身份 | 姓名/确认来源 | 业务组；工作目录 | 旧用户名与本次数据时间 | 在用/备用密钥 | 最近本人登录：系统 / 版本 / 结果 / 阶段 | 责任人 |', '| --- | --- | --- | --- | --- | --- | --- |']
    for actor, entries in sorted(report['actors'].items()):
        meta = annotations.get('actors', {}).get(actor, {})
        related = [chain for chain in chains if chain.get('actor_id') == actor]
        account_ids = sorted({chain['source_id'] for chain in related if chain.get('entry_kind') != '直接研究/管理员入口'})
        times = {row['id']: row['observed_at'] for row in records}
        key_roles = [key_ids[entry['fingerprint']] + '：' + annotations.get('keys', {}).get(entry['fingerprint'], {}).get('usage', '本人在用/备用用途未确认') for entry in entries]
        direct = sorted({chain['source_id'] for chain in related if chain.get('entry_kind') == '直接研究/管理员入口'})
        ports = sorted({str(profile.get('remote_port', '未记录')) for row in records if row['id'] in direct for profile in row['account'].get('profiles', [])})
        proofs = [p for p in annotations.get('login_checks', []) if p.get('actor_id') == actor]
        proof = max(proofs, key=lambda p: p.get('observed_at', '')) if proofs else None
        login = '未实测；系统/实际安装版本未回报' if not proof else ' / '.join(str(proof.get(k) or '未回报') for k in ('os', 'client_version', 'result', 'stage')) + '；' + str(proof.get('observed_at'))
        lines.append('| ' + ' | '.join(map(cell, [actor + '；直接入口：' + (', '.join(direct) or '未核验') + '；HTTP 端口：' + ', '.join(ports), (meta.get('name') or '姓名待确认') + '；' + (meta.get('source') or '待提供确认来源'), str(entries[0].get('role')) + '；' + ', '.join(groups(entries[0])) + '；' + str(entries[0].get('workspace_path')) + ' @ ' + str(snapshots['server-c'].get('data', {}).get('observed_at_utc')), '; '.join(key + ' @ ' + str(times.get(key)) for key in account_ids) or '没有匹配的旧入口', '; '.join(key_roles), login, meta.get('owner') or '管理员待指派'])) + ' |')
    lines += ['', '## 逐把公钥的入口核验', '', '| 源账号 → 目标账号 | 公钥 | 路由存在 | 配置链路 | 当前接口 | 本人完整登录 | 缺项或未核验项 |', '| --- | --- | --- | --- | --- | --- | --- |']
    for chain in chains:
        verification = {'unverified': '本人未实测', 'passed': '本人历史记录通过', 'failed': '本人历史记录失败', 'reported-incomplete': '本人报告资料不全'}.get(chain['full_login'], chain['full_login'])
        lines.append('| ' + ' | '.join(map(cell, [chain['source_id'] + ' → ' + chain['target_id'], ref([chain['fingerprint']]), '是' if chain['route_exists'] else '否' if chain.get('entry_kind') == 'missing' else '直接入口', {'complete': '配置链路齐全', 'incomplete': '配置缺项', 'unknown': '当前未核验'}[chain['configuration']], {'available': '接口可用', 'unavailable': '接口不可用', 'unknown': '未核验'}[chain['interface']], verification, '; '.join(chain['gaps']) or '无已发现缺项；仍需本人签名登录'])) + ' |')
    lines += ['', '## 逐台账号、权限与登记待办', '', '| 稳定账号标识 | UID/GID；类型 | Linux 组；sudo | 实际公钥 | 开通状态 | 责任人；下一步；完成时间 | 来源 |', '| --- | --- | --- | --- | --- | --- | --- |']
    for row in records:
        user = row['account']
        key_state = '公钥采集失败，未核验' if user.get('collection_error') or any(key.get('error') for key in user.get('keys', [])) else ref(fps(user))
        lines.append('| ' + ' | '.join(map(cell, [row['id'] + '；' + row['name'], f"{user.get('uid')}/{user.get('gid')}；{row['kind']}；{user.get('home')}；{user.get('shell')}", ', '.join(user.get('groups', [])) + '；' + SUDO.get(user.get('sudo_policy', {}).get('kind'), '未核验'), key_state, row['onboarding'], row['owner'] + '；' + row['next_action'] + '；' + row['completed_at'], row['source'] + ' @ ' + str(row['observed_at']) + ('；历史值' if not row['current'] else '')])) + ' |')
    lines += ['', '## 公钥稳定标识与使用状态', '', '| K 编号 | 完整公钥指纹 | 算法与原始公钥备注 | 实际 SSH 账号 | 本人确认的用途 / 启停 | 确认来源 |', '| --- | --- | --- | --- | --- | --- |']
    for fp in keyset:
        meta = annotations.get('keys', {}).get(fp, {})
        sources = [row['id'] + ' @ ' + str(row['observed_at']) + ('（历史）' if not row['current'] else '') for row in records if fp in fps(row['account'])]
        notes = sorted({str(key.get('algorithm', '')) + ' / ' + str(key.get('comment', '')) for row in records for key in row['account'].get('keys', []) if key.get('fingerprint') == fp})
        lines.append('| ' + ' | '.join(map(cell, [key_ids[fp], fp, '; '.join(notes), '; '.join(sources) or '无旧 SSH 接受记录', meta.get('usage', '用途待确认') + ' / ' + meta.get('state', '以所列服务器登记为准；本人启停未确认'), meta.get('source') or '尚未提供'])) + ' |')
    lines += ['', '## 本次快照变更', '']
    lines.extend('- ' + cell(json.dumps(change, ensure_ascii=False)) for change in (changes or []))
    if not changes: lines.append('没有已确认的账号/公钥配置变更，或本次尚无可比较的旧快照。采集失败不记作账号删除。')
    lines += ['', '## 维护方式', '', '```sh', 'python3 scripts/sync_server_account_register.py', '```', '',
              '工具代码位于 scripts/；快照、历史差异和人工登记位于本机 .quantcode/server-account-register/。人工登记格式见 configs/server-account-register.example.json。离线复核可用 --offline --state-dir 指定快照目录。', '',
              '采集失败仍生成本次报告，显示失败时间和最后成功数据时间；部分账号或接口异常不会中止其他结果。服务器登录失败返回非零退出状态供管理员注意，报告仍可查看。没有采集或保存私钥、HTTP 访问密码与会话令牌。', '']
    return '\n'.join(lines)
