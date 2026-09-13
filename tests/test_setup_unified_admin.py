from copy import deepcopy
import pytest
from scripts.setup_unified_admin import extend_roster, remap_paths, rebind_catalog
from scripts.setup_unified_admin import ACTOR, FINGERPRINT, bind_admin_github
import hashlib
import json


def test_github_binding_preserves_other_members_and_rejects_reassignment():
    admin = {"actor_id": ACTOR, "fingerprint": FINGERPRINT, "role": "admin", "groups": ["agent", "model"]}
    member = {"actor_id": "member", "github_subject": "member-account"}
    roster = {"bindings": [member, admin]}
    bound = bind_admin_github(roster, "admin-account")
    assert bound["bindings"] == [member, {**admin, "github_subject": "admin-account"}]
    assert "github_subject" not in admin
    assert bind_admin_github(bound, "admin-account") == bound
    with pytest.raises(ValueError, match="different"):
        bind_admin_github(bound, "someone-else")
    with pytest.raises(ValueError, match="Verified"):
        bind_admin_github({"bindings": [{**admin, "fingerprint": "another-key"}]}, "admin-account")

def test_enrollment_preserves_members_and_is_idempotent():
    member = {"actor_id": "member", "fingerprint": "key-member", "role": "analyst"}
    admin = {"actor_id": "quantadmin", "fingerprint": "key-admin", "role": "admin"}
    roster = {"bindings": [member], "metadata": {"approved": True}}
    before = deepcopy(roster)
    added = extend_roster(roster, admin)
    assert roster == before
    assert added["bindings"][0] == member
    assert added["metadata"] == roster["metadata"]
    assert extend_roster(added, admin) == added

def test_reassignment_and_role_overwrites_are_rejected():
    admin = {"actor_id": "quantadmin", "fingerprint": "key-admin", "role": "admin"}
    for existing in [{**admin, "role": "analyst"}, {**admin, "actor_id": "other"}, {**admin, "fingerprint": "other-key"}]:
        with pytest.raises(ValueError, match="conflicts"):
            extend_roster({"bindings": [existing]}, admin)
    with pytest.raises(ValueError, match="approved"):
        extend_roster({"status": "REVIEW_REQUIRED", "bindings": []}, admin)

def test_catalog_only_remaps_the_reference_path_trees():
    source = {"command": ["/old/install/backend/python", "/old/state/config"], "source": "/old/install-other", "digest": "unchanged"}
    assert remap_paths(source, "/old/install", "/new/install", "/old/state", "/new/state") == {
        "command": ["/new/install/backend/python", "/new/state/config"], "source": "/old/install-other", "digest": "unchanged"}
    assert source["command"][0] == "/old/install/backend/python"


def test_catalog_rebinds_configuration_without_changing_published_permissions():
    old = {"quantcode": {"command": ["/old/python"], "enabled": True}}
    new = {"quantcode": {"command": ["/new/python"], "enabled": True}}
    digest = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    entry = {"server": "quantcode", "tool": "list_capabilities", "server_config_hash": digest(old["quantcode"]),
             "status": "published", "roles": ["admin"], "effect": "read", "input_schema_hash": "unchanged"}
    catalog = {"tools": [entry]}
    result = rebind_catalog(catalog, old, new)
    assert result["tools"] == [{**entry, "server_config_hash": digest(new["quantcode"])}]
    assert catalog["tools"][0] == entry
    with pytest.raises(ValueError, match="reviewed"):
        rebind_catalog({"tools": [{**entry, "server_config_hash": "unreviewed"}]}, old, new)
