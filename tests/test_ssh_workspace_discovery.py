from types import SimpleNamespace
import pytest
from scripts.install_ssh_workspace_discovery import member_routes


def test_old_ssh_account_resolves_to_only_its_authorized_workspace():
    user = SimpleNamespace(pw_name='old-name', pw_uid=1001)
    inventory = [
        {'actor_id': 'member-a', 'serverId': 'server-c', 'username': 'qc-member-a', 'fingerprints': ['key-a']},
        {'actor_id': 'member-b', 'serverId': 'server-c', 'username': 'qc-member-b', 'fingerprints': ['key-b']},
    ]
    result = member_routes(user, {'key-a'}, inventory, {})
    assert result['uid'] == 1001
    assert [route['username'] for route in result['routes']] == ['qc-member-a']
    assert member_routes(user, {'unregistered'}, inventory, {}) is None


def test_reviewed_alias_explains_conflict_without_authorizing_the_old_key():
    user = SimpleNamespace(pw_name='old-name', pw_uid=1001)
    inventory = [{'actor_id': 'member-a', 'serverId': 'server-c', 'username': 'qc-member-a', 'fingerprints': ['registered-key']}]
    result = member_routes(user, {'old-key'}, inventory, {'old-name': 'member-a'})
    assert result['routes'][0]['fingerprints'] == ['registered-key']
    assert 'old-key' not in result['routes'][0]['fingerprints']


def test_ambiguous_account_is_not_silently_assigned_to_a_member():
    inventory = [{'actor_id': actor, 'serverId': 'server-c', 'username': actor, 'fingerprints': ['shared']} for actor in ('a', 'b')]
    with pytest.raises(ValueError, match='ambiguous'):
        member_routes(SimpleNamespace(pw_name='legacy', pw_uid=1001), {'shared'}, inventory, {})
