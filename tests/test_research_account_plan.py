from pathlib import Path
import subprocess

import pytest

from quantcode.identity import fingerprint_of_public_key
from scripts.provision_research_accounts import build_plan


@pytest.fixture
def approved(tmp_path):
    key = tmp_path / "key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True, capture_output=True)
    public = key.with_suffix(".pub").read_text()
    return {"actor_id": "member-test", "group": "model", "groups": ["model", "factor"],
            "workspace_path": "/srv/quant/users/member-test", "public_key": public,
            "fingerprint": fingerprint_of_public_key(public)}


def test_approved_keys_merge_into_one_unprivileged_research_identity(approved):
    plan = build_plan({"bindings": [approved, approved]}, Path("/srv/quant/users"))
    assert len(plan) == 1
    assert plan[0]["username"] == "qc-member-test"
    assert len(plan[0]["public_keys"]) == 1


@pytest.mark.parametrize("change", [
    {"actor_id": "other;command"}, {"workspace_path": "/etc/quantcode"},
    {"workspace_path": "/srv/quant/users/../other"}, {"fingerprint": "SHA256:wrong"},
    {"public_key": "SHA256:missing-full-key"}, {"groups": ["admin"]},
])
def test_incomplete_or_unsafe_enrollment_is_rejected(approved, change):
    with pytest.raises(ValueError):
        build_plan({"bindings": [{**approved, **change}]}, Path("/srv/quant/users"))


def test_shared_public_key_cannot_create_two_accounts(approved):
    with pytest.raises(ValueError, match="shared"):
        build_plan({"bindings": [approved, {**approved, "actor_id": "member-other",
            "workspace_path": "/srv/quant/users/member-other"}]}, Path("/srv/quant/users"))


def test_pending_roster_and_symlinked_workspace_root_are_rejected(approved, tmp_path):
    with pytest.raises(ValueError, match="review"):
        build_plan({"status": "REVIEW_REQUIRED", "bindings": [approved]}, Path("/srv/quant/users"))
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path)
    with pytest.raises(ValueError, match="symlinks"):
        build_plan({"bindings": [approved]}, alias)
