from runner.acceptance import run_acceptance


def test_risk_gate_pass():
    payload = {
        "max_drawdown": 0.12,
        "position_limit": 0.20,
        "correlation_with_existing": 0.30,
        "tail_risk_var_99": -0.05,
    }
    result = run_acceptance("risk-gate", payload)
    assert result.verdict == "pass", [c.message for c in result.checks if not c.passed]


def test_risk_gate_fail_var_missing():
    payload = {
        "max_drawdown": 0.12,
        "position_limit": 0.20,
        "correlation_with_existing": 0.30,
        "tail_risk_var_99": None,
    }
    result = run_acceptance("risk-gate", payload)
    assert result.verdict == "fail"
    assert any(c.name == "var_99_present" and not c.passed for c in result.checks)


def test_factor_eval_pass():
    payload = {
        "ic_metrics": {"ic_mean": 0.05, "ir": 0.7, "t_stat": 2.5},
        "turnover": {"monthly": 0.5},
    }
    result = run_acceptance("factor-eval", payload)
    assert result.verdict == "pass"


def test_pit_rag_lookahead_detected():
    payload = {
        "as_of_date": "2024-03-15",
        "documents": [
            {"id": "ok", "published_at": "2024-02-20"},
            {"id": "leak", "published_at": "2024-04-01"},
        ],
    }
    result = run_acceptance("pit-rag", payload)
    assert result.verdict == "fail"
    assert "leak" in result.checks[0].message


def test_unknown_skill():
    result = run_acceptance("not-a-skill", {})
    assert result.verdict == "fail"
