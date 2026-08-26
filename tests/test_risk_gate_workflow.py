"""Static trust-boundary contract for the agentic Server B Risk Gate."""
from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "risk-gate.yml"


def _workflow() -> dict:
    data = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _job(name: str) -> dict:
    return _workflow()["jobs"][name]


def _checkout_steps(name: str) -> list[dict]:
    return [
        step
        for step in _job(name)["steps"]
        if str(step.get("uses", "")).startswith("actions/checkout@")
    ]


def test_agentic_risk_jobs_are_parallel_server_b_pipeline() -> None:
    jobs = _workflow()["jobs"]
    assert set(jobs) == {
        "initialize-risk-gate",
        "plan-risk-gate",
        "execute-risk-gate",
        "review-risk-gate",
        "publish-risk-gate",
    }
    for job in jobs.values():
        assert job["runs-on"] == {
            "group": "quant-review-runners",
            "labels": "server-b-multiagent-review",
        }
    assert jobs["plan-risk-gate"]["needs"] == "initialize-risk-gate"
    assert jobs["execute-risk-gate"]["needs"] == "plan-risk-gate"
    assert jobs["review-risk-gate"]["needs"] == ["plan-risk-gate", "execute-risk-gate"]
    assert jobs["publish-risk-gate"]["needs"] == [
        "initialize-risk-gate",
        "plan-risk-gate",
        "execute-risk-gate",
        "review-risk-gate",
    ]


def test_workflow_is_base_owned_and_fixture_free() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "pull_request_target:" in text
    assert "branches: [main]" in text
    assert "pull_request:" not in text
    assert "workflow_dispatch:" not in text
    assert "ubuntu-latest" not in text
    assert "setup-python" not in text
    assert "pip install" not in text
    for obsolete in (
        "run_risk_gate_tool.py",
        "--scenario normal",
        "trusted-base-normal-fixture-smoke",
        "fixture smoke",
        "single-asset-backtrader-v1",
        "cta-benchmark-rb-1m",
        "dual_ma",
    ):
        assert obsolete not in text
    assert "scripts.ci.plan_risk_gate" in text
    assert "scripts.ci.run_agentic_backtest" in text
    assert "RISK_GATE_CATALOG_RELATIVE" in text


def test_permissions_split_planner_executor_review_and_token_publisher() -> None:
    jobs = _workflow()["jobs"]
    assert jobs["initialize-risk-gate"]["permissions"] == {"statuses": "write"}
    assert jobs["plan-risk-gate"]["permissions"] == {
        "contents": "read",
        "pull-requests": "read",
    }
    assert jobs["execute-risk-gate"]["permissions"] == {
        "actions": "read",
        "contents": "read",
    }
    assert jobs["review-risk-gate"]["permissions"] == {
        "actions": "read",
        "contents": "read",
    }
    assert jobs["publish-risk-gate"]["permissions"] == {
        "actions": "read",
        "issues": "write",
        "pull-requests": "read",
        "statuses": "write",
    }


def test_planner_reads_exact_head_but_executes_only_trusted_base_planner() -> None:
    checkouts = _checkout_steps("plan-risk-gate")
    assert len(checkouts) == 2
    by_path = {step["with"]["path"]: step["with"] for step in checkouts}
    assert by_path["pr-source"]["ref"] == "${{ env.HEAD_SHA }}"
    assert by_path["trusted-target"]["ref"] == "${{ env.BASE_SHA }}"
    for checkout in by_path.values():
        assert checkout["persist-credentials"] is False
        assert checkout["set-safe-directory"] is False

    planner = next(
        step for step in _job("plan-risk-gate")["steps"]
        if step.get("name") == "Spawn bounded dynamic Risk Scout subagent"
    )
    assert planner["working-directory"] == "${{ github.workspace }}/trusted-target"
    assert planner["env"]["PR_REPO"] == "${{ github.workspace }}/pr-source"
    assert planner["env"]["TRUSTED_REPO"] == "${{ github.workspace }}/trusted-target"
    assert planner["env"]["DEEPSEEK_API_KEY"] == "${{ secrets.DEEPSEEK_API_KEY }}"
    assert 'export PYTHONPATH="$TRUSTED_REPO"' in planner["run"]
    assert '"$RISK_CI_RUNTIME/bin/python" -m scripts.ci.discover_risk_gate' in planner["run"]
    assert 'discover_args+=(--preflight-error "$preflight_error")' in planner["run"]
    assert '"${discover_args[@]}"' in planner["run"]
    assert '"$RISK_CI_RUNTIME/bin/python" -m scripts.ci.plan_risk_gate' in planner["run"]
    assert planner["run"].index("unset DEEPSEEK_API_KEY") < planner["run"].index(
        '"$RISK_CI_RUNTIME/bin/python" -m scripts.ci.plan_risk_gate'
    )
    assert '--registry "$TRUSTED_REPO/$RISK_GATE_CATALOG_RELATIVE"' in planner["run"]
    assert '--catalog "$TRUSTED_REPO/$RISK_GATE_CATALOG_RELATIVE"' in planner["run"]
    assert '--task-artifact "$task"' in planner["run"]
    assert "risk-gate-task.json" in planner["run"]
    assert "jq -e '.execution_ready | type == \"boolean\"'" in planner["run"]
    assert 'execution_ready="$(jq -r \'.execution_ready\' "$task")"' in planner["run"]
    assert "jq -er '.execution_ready'" not in planner["run"]
    assert "pr-source/scripts" not in planner["run"]

    verify = next(
        step for step in _job("plan-risk-gate")["steps"]
        if step.get("name") == "Verify planner inputs and trusted authority"
    )
    assert "credential-like material" in verify["run"]
    assert "scripts/ci/discover_risk_gate.py" in verify["run"]
    assert "schemas/risk_gate_task.py" in verify["run"]


def test_executor_never_checks_out_or_executes_pr_head_code() -> None:
    checkouts = _checkout_steps("execute-risk-gate")
    assert len(checkouts) == 1
    checkout = checkouts[0]["with"]
    assert checkout["ref"] == "${{ env.BASE_SHA }}"
    assert checkout["path"] == "trusted-target"
    assert checkout["persist-credentials"] is False
    assert checkout["set-safe-directory"] is False

    job_text = yaml.safe_dump(_job("execute-risk-gate"), sort_keys=False)
    assert "HEAD_SHA }}\n  path: pr-source" not in job_text
    assert "RISK_GATE_PR_SOURCE" not in job_text
    assert "DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}" not in job_text
    execute = next(
        step for step in _job("execute-risk-gate")["steps"]
        if step.get("name") == "Run trusted catalog materializer and executor"
    )
    validate = next(
        step for step in _job("execute-risk-gate")["steps"]
        if step.get("name") == "Validate trusted plan and execution infrastructure"
    )
    assert 'export PYTHONPATH="$TRUSTED_REPO"' in validate["run"]
    assert execute["working-directory"] == "${{ github.workspace }}/trusted-target"
    assert '"$RISK_GATE_EXECUTOR_PYTHON" -m scripts.ci.run_agentic_backtest' in execute["run"]
    assert '--plan "$PLAN_PATH"' in execute["run"]
    assert 'catalog_path="$TRUSTED_REPO/$RISK_GATE_CATALOG_RELATIVE"' in execute["run"]
    assert '--catalog "$catalog_path"' in execute["run"]
    assert '--snapshot-root "$RISK_GATE_SNAPSHOT_ROOT"' in execute["run"]
    assert '--engine-root "$RISK_GATE_ENGINE_ROOT"' in execute["run"]
    for boundary in (
        "/usr/bin/unshare",
        "--user",
        "--map-root-user",
        "--mount",
        "--net",
        "host_net_namespace",
        "Materialized snapshot is not mounted read-only",
        "/usr/bin/env -i",
    ):
        assert boundary in execute["run"]


def test_only_evaluable_canonical_plan_reaches_materializer_executor() -> None:
    job = _job("execute-risk-gate")
    assert job["if"] == (
        "${{ needs.plan-risk-gate.result == 'success' && "
        "needs.plan-risk-gate.outputs.applicability == 'evaluable' }}"
    )
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "RiskGatePlan.model_validate_json" in text
    assert "RiskGateTaskArtifact.model_validate_json" in text
    assert "RiskApplicability.EVALUABLE" in text
    assert "risk-gate-task.sha256" in text
    assert "risk-gate-plan.sha256" in text
    assert "backtest-evidence.sha256" in text
    assert "RISK_GATE_EXECUTOR_PYTHON_SHA256" in text
    assert "Risk execution input is not root-owned" in text
    assert "Risk execution input is writable by runner" in text
    assert "adapter_parameters" not in _job("execute-risk-gate").get("env", {})


def test_executor_reuses_pinned_root_owned_prebuilt_runtime_without_repo_variables() -> None:
    env = _workflow()["env"]
    assert env["RISK_GATE_EXECUTOR_RUNTIME"] == (
        "/srv/quant/envs/quant-risk-backtest-py310-57fbab-v1"
    )
    assert env["RISK_GATE_ENGINE_ROOT"] == (
        "/srv/quant/envs/quant-risk-engine-57fbab670666-v1"
    )
    assert env["RISK_GATE_SNAPSHOT_ROOT"] == (
        "/srv/quant/envs/quant-risk-snapshot-rb-1m-d31e17-v1"
    )
    assert env["RISK_GATE_EXECUTOR_PYTHON_TARGET"] == "/usr/bin/python3.10"
    for name in (
        "RISK_GATE_EXECUTOR_MANIFEST_SHA256",
        "RISK_GATE_EXECUTOR_PYTHON_SHA256",
        "RISK_GATE_EXECUTOR_RUNTIME_TREE_SHA256",
        "RISK_GATE_ENGINE_TREE_SHA256",
        "RISK_GATE_SNAPSHOT_TREE_SHA256",
    ):
        assert re.fullmatch(r"[0-9a-f]{64}", env[name])
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    for name in (
        "RISK_GATE_EXECUTOR_RUNTIME",
        "RISK_GATE_ENGINE_ROOT",
        "RISK_GATE_SNAPSHOT_ROOT",
    ):
        assert f"vars.{name}" not in text
    assert "payload_tree_sha256_excluding_manifest" in text
    assert "tree_sha" in text
    assert 'RISK_GATE_EXECUTOR_PYTHON="$(realpath' not in text
    assert '[[ -L "$executor_python"' in text
    assert "pip install" not in text


def test_executor_imports_only_trusted_base_and_immutable_engine_in_namespace() -> None:
    execute = next(
        step
        for step in _job("execute-risk-gate")["steps"]
        if step.get("name") == "Run trusted catalog materializer and executor"
    )
    run = execute["run"]
    assert (
        'PYTHONPATH="$TRUSTED_REPO:$RISK_GATE_ENGINE_ROOT:'
        '$RISK_GATE_ENGINE_ROOT/backtest_layer:'
        '$RISK_GATE_ENGINE_ROOT/factor_layer/factor_engine"'
    ) in run
    assert '"$RISK_GATE_EXECUTOR_RUNTIME"' in run
    assert "PYTHONHASHSEED=0" in run
    assert "OPENBLAS_NUM_THREADS=1" in run


def test_review_uses_trusted_reducer_and_emits_head_bound_artifact() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    review = next(
        step for step in _job("review-risk-gate")["steps"]
        if step.get("name") == "Build head-bound evidence review"
    )
    assert 'export PYTHONPATH="$TRUSTED_REPO"' in review["run"]
    assert '"$RISK_CI_RUNTIME/bin/python" -m scripts.ci.review_risk_evidence' in review["run"]
    assert '--task "$task"' in review["run"]
    assert '--policy "$TRUSTED_REPO/$RISK_GATE_CATALOG_RELATIVE"' in review["run"]
    assert 'review_args+=(--evidence "$evidence")' in review["run"]
    assert "RiskGateArtifact.model_validate_json" in review["run"]
    assert 'rules = policy.get("thresholds")' not in text
    assert 'limit: 0.15' not in text
    for field in (
        "task",
        "task_digest",
        "step_id",
        "request_id",
        "completed_step_ids",
        "artifact_sha256",
        "plan_digest",
        "evidence_digest",
        "policy_digest",
        "artifact_sha256",
        "catalog_sha256",
        "workflow_sha",
        "base_sha",
        "head_sha",
    ):
        assert field in text
    assert "risk-gate-review.json" in text
    assert "risk-gate-review.sha256" in text
    assert "risk-review-${{ github.run_id }}-${{ github.run_attempt }}" in text


def test_write_token_jobs_are_checkout_free_and_do_not_run_repo_code() -> None:
    for name in ("initialize-risk-gate", "publish-risk-gate"):
        steps = _job(name)["steps"]
        assert all("actions/checkout@" not in str(step.get("uses", "")) for step in steps)
        assert all("run" not in step for step in steps)
        assert all("working-directory" not in step for step in steps)
    publisher_text = yaml.safe_dump(_job("publish-risk-gate"), sort_keys=False)
    assert "pr-source" not in publisher_text
    assert "trusted-target" not in publisher_text
    publisher_script = next(
        step["with"]["script"]
        for step in _job("publish-risk-gate")["steps"]
        if str(step.get("uses", "")).startswith("actions/github-script@")
    )
    assert "childProcess.execFileSync" in publisher_script
    assert '["-I", "-S", "-c", canonicalValidator, artifactPath]' in publisher_script
    assert "...process.env" not in publisher_script


def test_publisher_revalidates_artifact_live_head_and_dedupes_comment() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert 'artifact_type: "agentic-risk-gate-review"' in text
    assert "canonical plan digest mismatch" in text
    assert "canonical evidence digest mismatch" in text
    assert "canonical review digest mismatch" in text
    assert "currentPull.head.sha === process.env.HEAD_SHA" in text
    assert "currentPull.base.sha === process.env.BASE_SHA" in text
    assert "expectedNestedBinding" in text
    assert "no-evidence verdict does not match plan applicability" in text
    assert "not_applicable review is not a clean no-execution result" in text
    assert "evaluable plan has no evidence" in text
    assert 'sha: process.env.HEAD_SHA' in text
    assert 'context: "Quant Risk Gate"' in text
    assert "quantcode:risk-gate:agentic" in text
    assert "github.paginate(github.rest.issues.listComments" in text
    assert 'comment.user?.type === "Bot"' in text
    assert 'verdict === "pass" || verdict === "not_applicable"' in text


def test_every_risk_action_is_pinned_to_a_full_commit_sha() -> None:
    uses = re.findall(
        r"^\s*uses:\s*([^\s#]+)",
        WORKFLOW_PATH.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert uses
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", item) for item in uses)
