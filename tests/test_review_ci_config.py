from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / ".review-ci"
ALLOWED_SEVERITIES = {"info", "nit", "important", "blocker"}
ALLOWED_STATUSES = {"pass", "warn", "block", "skipped", "error"}
REQUIRED_PROFILE_FIELDS = {
    "description",
    "repo_name_hints",
    "execution_zone",
    "runner_labels",
    "allowed_write_roots",
    "categories",
    "protected_outputs",
    "artifact_manifest_required_fields",
    "smoke_commands",
}


def _load(name: str) -> dict:
    path = CONFIG_DIR / name
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), f"{name} must contain a YAML mapping"
    return payload


def test_gate_policy_contract() -> None:
    policy = _load("gate_policy.yaml")
    gates = policy.get("gates")
    assert isinstance(gates, dict) and gates
    assert any(settings.get("required") is True for settings in gates.values())

    for name, settings in gates.items():
        assert isinstance(settings, dict), name
        assert isinstance(settings.get("enabled"), bool), name
        assert isinstance(settings.get("required"), bool), name
        assert settings.get("block_on") in ALLOWED_SEVERITIES, name

    commands = policy.get("pytest_commands")
    assert isinstance(commands, list)
    for item in commands:
        assert isinstance(item.get("categories"), list)
        command = item.get("command")
        assert isinstance(command, list) and command
        assert all(isinstance(part, str) and part for part in command)


def test_reviewer_matrix_references_registered_gates() -> None:
    matrix = _load("reviewer_matrix.yaml")
    gates = set(_load("gate_policy.yaml")["gates"])
    reviewers = matrix.get("reviewers")
    assert isinstance(reviewers, dict) and reviewers

    for reviewer_id, reviewer in reviewers.items():
        context = reviewer.get("context")
        assert isinstance(context, dict), reviewer_id
        assert context.get("mission"), reviewer_id
        assert isinstance(context.get("categories"), list) and context["categories"], reviewer_id

        for binding in reviewer.get("programmatic_gate_bindings", []):
            assert binding.get("name") in gates, reviewer_id
            assert isinstance(binding.get("required"), bool), reviewer_id
            statuses = binding.get("on_status", ["block", "error", "skipped"])
            assert set(statuses) <= ALLOWED_STATUSES, reviewer_id


def test_repo_profiles_are_complete_and_quantcode_is_selectable() -> None:
    payload = _load("repo_profiles.yaml")
    profiles = payload.get("profiles")
    assert isinstance(profiles, dict) and {"quantcode", "generic"} <= set(profiles)

    for profile_name, profile in profiles.items():
        assert REQUIRED_PROFILE_FIELDS <= set(profile), profile_name
        assert isinstance(profile["artifact_manifest_required_fields"], list), profile_name
        assert isinstance(profile["categories"], dict), profile_name
        for category, patterns in profile["categories"].items():
            assert isinstance(category, str) and category
            assert isinstance(patterns, list), f"{profile_name}.{category}"
            assert all(isinstance(pattern, str) and pattern for pattern in patterns)

    assert "quantcode" in profiles["quantcode"]["repo_name_hints"]


def test_artifact_manifest_fields_match_policy() -> None:
    policy_fields = set(
        _load("gate_policy.yaml")["artifact_contract"]["manifest_required_fields"]
    )
    quantcode_fields = set(
        _load("repo_profiles.yaml")["profiles"]["quantcode"][
            "artifact_manifest_required_fields"
        ]
    )
    assert policy_fields <= quantcode_fields
