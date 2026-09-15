import copy
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from scripts.server_account_register import ROSTERS, SERVERS, analyze, envelope, normalize, render, snapshot_changes
from scripts.sync_server_account_register import collect
from scripts import server_account_register_collect

FP = 'SHA256:' + 'a' * 43
TIME = '2026-09-15T00:00:00+00:00'


def metadata(uid=0, regular=True):
    return {'exists': True, 'uid': uid, 'gid': uid, 'mode': '0o600' if regular else '0o700', 'regular': regular, 'symlink': False}


def snapshots():
    entry = {'actor_id': 'member-fixture', 'fingerprint': FP, 'public_key_matches_fingerprint': True,
             'group': 'agent', 'groups': ['agent'], 'role': 'analyst', 'workspace_path': '/srv/fixture'}
    target = {'username': 'qc-fixture', 'uid': 1002, 'gid': 1002, 'home': '/srv/fixture', 'groups': ['qc-fixture'],
              'keys': [{'fingerprint': FP, 'algorithm': 'ssh-ed25519'}], 'authorized_keys_metadata': metadata(1002),
              'home_metadata': metadata(1002, False), 'ssh_directory': metadata(1002, False),
              'sshd': {'pubkeyauthentication': 'yes', 'allowtcpforwarding': 'yes', 'disableforwarding': 'no'},
              'profiles': [{'ssh_user': 'qc-fixture', 'readable_by_account': True, 'has_http_credentials': True, 'valid_connection': True,
                            'http_status': 200, 'has_session': True, 'identities': [{'fingerprint': FP, 'groups': ['agent']}]}]}
    route = {'serverId': 'server-c', 'username': 'qc-fixture', 'fingerprints': [FP]}
    source = {'username': 'fixture', 'uid': 1001, 'gid': 1001, 'home': '/home/fixture', 'groups': ['fixture'],
              'keys': [{'fingerprint': FP, 'algorithm': 'ssh-ed25519'}], 'authorized_keys_metadata': metadata(1001),
              'route_metadata': metadata(), 'route_file': {'uid': 1001, 'username': 'fixture', 'routes': [route]},
              'discovery': {'status': 'registered', 'routes': [route]}}
    raw = {server: {'server': server, 'observed_at_utc': TIME, 'accounts': []} for server in SERVERS}
    raw['server-b']['accounts'] = [source]
    raw['server-c'].update(accounts=[target],
        rosters={path: {'bindings': [copy.deepcopy(entry)]} for path in ROSTERS},
        research_registry={'metadata': metadata(), 'accounts': {'member-fixture': {
            'username': 'qc-fixture', 'uid': 1002, 'gid': 1002, 'workspace_path': '/srv/fixture', 'fingerprints': [FP]}}},
        native_units=[{'User': 'qc-fixture', 'ActiveState': 'active', 'public_key_files': [{'metadata': metadata(), 'keys': [{'fingerprint': FP}]}]}])
    return {server: envelope(server, data) for server, data in raw.items()}


def legacy(report):
    return next(chain for chain in report['chains'] if chain['source_id'] == 'server-b:fixture')


def test_a_real_target_ssh_key_is_required_even_if_roster_and_host_still_list_it():
    data = snapshots()
    assert legacy(analyze(data))['configuration'] == 'complete'
    data['server-c']['data']['accounts'][0]['keys'] = []
    report = analyze(data)
    assert legacy(report)['configuration'] == 'incomplete'
    assert '目标研究账号未登记此 SSH 公钥' in legacy(report)['gaps']
    assert '配置缺项' in render(report)


def test_unavailable_identity_endpoint_updates_report_without_turning_config_into_a_login_success():
    data = snapshots()
    data['server-c']['data']['accounts'][0]['profiles'][0].update(http_status=503, identities=[])
    report = analyze(data)
    assert legacy(report)['configuration'] == 'complete'
    assert legacy(report)['interface'] == 'unavailable'
    assert legacy(report)['full_login'] == 'unverified'
    document = render(report)
    assert '503' in document and '接口不可用' in document


def test_registry_profile_and_host_key_configuration_are_each_checked():
    for missing in ('registry', 'profile', 'host', 'profile-contract'):
        data = snapshots(); c = data['server-c']['data']
        if missing == 'registry': c['research_registry']['accounts']['member-fixture']['fingerprints'] = []
        if missing == 'profile': c['accounts'][0]['profiles'][0]['readable_by_account'] = False
        if missing == 'host': c['native_units'][0]['public_key_files'] = []
        if missing == 'profile-contract': c['accounts'][0]['profiles'][0]['valid_connection'] = False
        assert legacy(analyze(data))['configuration'] != 'complete'


def test_failed_collection_retains_dated_evidence_and_cannot_count_as_current_or_remove_keys():
    previous = snapshots(); current = copy.deepcopy(previous)
    current['server-b'] = envelope('server-b', previous=previous['server-b'], error='SSH 采集超时', attempted_at='2026-09-16T00:00:00+00:00')
    report = analyze(current)
    assert legacy(report)['configuration'] == 'unknown' and legacy(report)['interface'] == 'unknown'
    document = render(report)
    assert TIME in document and '2026-09-16T00:00:00+00:00' in document
    assert '本次采集失败；显示历史值' in document
    changes = snapshot_changes(previous, current)
    assert [change['kind'] for change in changes] == ['collection_failed']
    restored = envelope('server-b', previous['server-b']['data'], current['server-b'])
    assert restored['status'] == 'ok' and 'error' not in restored


def test_personal_login_proof_requires_explicit_version_os_and_provenance_not_a_host_session():
    data = snapshots()
    report = analyze(data)
    assert legacy(report)['full_login'] == 'unverified'
    assert '实际安装版本未回报' in render(report)
    proof = {'actor_id': 'member-fixture', 'source_id': 'server-b:fixture', 'fingerprint': FP, 'os': 'Windows',
             'client_version': '1.2.0-test.4', 'result': 'passed', 'stage': 'workspace-entered', 'observed_at': TIME, 'source': 'member acceptance record'}
    report = analyze(data, {'login_checks': [proof]})
    assert legacy(report)['full_login'] == 'passed'
    assert 'Windows / 1.2.0-test.4 / passed' in render(report)
    proof['client_version'] = None
    assert legacy(analyze(data, {'login_checks': [proof]}))['full_login'] == 'reported-incomplete'


def test_partial_server_failure_does_not_stop_cli_from_replacing_the_old_document(tmp_path):
    data = snapshots()
    data['server-a'] = envelope('server-a', previous=data['server-a'], error='SSH 认证失败', attempted_at='2026-09-16T00:00:00+00:00')
    for server, snapshot in data.items(): (tmp_path / (server + '.json')).write_text(json.dumps(snapshot))
    document = tmp_path / 'report.md'; document.write_text('OLD_DOCUMENT')
    script = Path(__file__).resolve().parents[1] / 'scripts/sync_server_account_register.py'
    result = subprocess.run([sys.executable, str(script), '--offline', '--state-dir', str(tmp_path), '--output', str(document)], capture_output=True, text=True)
    assert result.returncode == 1
    assert 'SSH 认证失败' in document.read_text() and 'OLD_DOCUMENT' not in document.read_text()
    assert (tmp_path / 'manifest.json').exists()


def test_transport_failure_is_sanitized_and_retains_last_success():
    prior = snapshots()['server-b']
    result = collect('server-b', 'fixture-host', 'ubuntu', prior, 'fixture code',
                     run=lambda *args, **kwargs: SimpleNamespace(returncode=255, stderr='Permission denied; sensitive diagnostic content', stdout=''))
    assert result['status'] == 'failed' and result['last_success_at'] == prior['last_success_at']
    assert 'sensitive' not in json.dumps(result)


def test_one_account_inspection_exception_does_not_escape_the_collector(monkeypatch):
    user = SimpleNamespace(pw_name='fixture', pw_uid=1000, pw_gid=1000, pw_dir='/home/fixture', pw_shell='/bin/bash')
    def fail(_user): raise PermissionError('private diagnostic must not be returned')
    monkeypatch.setattr(server_account_register_collect, 'account_details', fail)
    result = server_account_register_collect.account(user)
    assert result['collection_error'] == 'PermissionError'
    assert 'private diagnostic' not in json.dumps(result)


def test_root_and_test_accounts_are_not_default_member_onboarding_debts():
    data = snapshots()
    data['server-a']['data']['accounts'] = [{'username': 'root', 'uid': 0, 'gid': 0, 'home': '/root'},
        {'username': 'qc-sim-agent-260909', 'uid': 1111, 'gid': 1111, 'home': '/home/test'}]
    rows = [row for row in analyze(data)['records'] if row['server'] == 'server-a']
    assert all(row['onboarding'] == '无需普通成员入口' for row in rows)


def test_changes_use_full_fingerprints_and_notice_group_permission_changes():
    previous = snapshots(); current = copy.deepcopy(previous)
    for path in ROSTERS: current['server-c']['data']['rosters'][path]['bindings'][0]['role'] = 'approver'
    changes = snapshot_changes(previous, current)
    assert any(change['kind'] == 'organization_grant_changed' and change['fingerprint'] == FP for change in changes)


def test_wrong_server_snapshot_is_not_adopted_as_fresh_data():
    value = snapshots()['server-b']
    result = normalize('server-c', value)
    assert result['status'] == 'failed'
    assert result['data'] == {}


def test_unreadable_roster_and_stopped_host_still_render_current_unknowns():
    for failure in ('roster', 'host'):
        data = snapshots()
        c = data['server-c']['data']
        if failure == 'roster': c['rosters'][ROSTERS[1]] = {'error': 'PermissionError'}
        else:
            c['native_units'][0].update(ActiveState='inactive')
            c['native_units'][0].pop('public_key_files')
            c['accounts'][0]['profiles'][0].update(http_status=None, http_error='URLError')
        report = analyze(data)
        assert legacy(report)['configuration'] == 'unknown'
        assert '当前未核验' in render(report)
