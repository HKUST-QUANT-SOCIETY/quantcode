"""Evidence must retain useful output without retaining model reasoning or secrets."""
import json

import pytest

from run_serverc_native_members import Member, sanitize_evidence, transcript_evidence


def test_transcript_keeps_complete_success_output_and_sanitizes_failure():
    output = "actual safe output\n" * 3000
    messages = [{"info": {"id": "message-1", "role": "assistant", "tokens": {"input": 123, "output": 45},
                          "error": {"name": "APIError", "data": {"message": "QA credential disposable-secret rejected"}}},
                 "parts": [{"type": "reasoning", "text": "must not be recorded"},
                           {"type": "tool", "tool": "read", "state": {"status": "completed", "output": output}},
                           {"type": "tool", "tool": "example", "state": {"status": "error", "input": {"apiKey": "unknown-credential"},
                            "error": '{"requestHeaders":{"Authorization":"Bearer unknown-bearer"},"tokens_input":42}'}}]}]
    captured = transcript_evidence(messages, ["disposable-secret"])
    encoded = json.dumps(captured)
    assert captured[0]["parts"][0]["output"] == output
    assert captured[0]["tokens"] == {"input": 123, "output": 45}
    assert all(value not in encoded for value in ("must not be recorded", "disposable-secret", "unknown-credential", "unknown-bearer"))
    assert json.loads(captured[0]["parts"][1]["error"])["tokens_input"] == 42
    assert sanitize_evidence("-----BEGIN OPENSSH PRIVATE KEY-----\nprivate-value\n-----END OPENSSH PRIVATE KEY-----") == "[REDACTED PRIVATE KEY]"


def test_native_completion_does_not_override_step_result():
    member = Member({"group": "factor", "actor_id": "sim-factor"}, "test", {}, {}, 10)
    member.step("native_task_completed", status="completed", tokens_input=123)
    assert member.result["steps"] == [{"name": "native_task_completed", "status": "passed", "task_status": "completed", "tokens_input": 123}]


def test_runner_does_not_hide_lost_approval_by_approving_identical_proposal_again():
    member = Member({"group": "factor", "actor_id": "sim-factor"}, "test", {}, {}, 10)
    proposal = {"intent_hash": "same-intent", "inspection_hash": "same-inspections", "coverage": "none",
                "components": [], "reason": "file-only task", "proposal_hash": "first-hash"}
    approvals = []

    def request(method, endpoint, payload=None):
        if endpoint.endswith("/reuse"):
            return {"proposal": proposal}
        if method == "POST":
            approvals.append(payload)
        return {} if endpoint.endswith("/solution") else []

    member.request = request
    member.review_pending()
    proposal["proposal_hash"] = "second-hash"
    with pytest.raises(AssertionError, match="identical coverage proposal lost"):
        member.review_pending()
    assert len(approvals) == 1
