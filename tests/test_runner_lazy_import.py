import importlib
import sys


def test_memory_import_does_not_register_or_compile_all_flows(monkeypatch, tmp_path):
    import runner

    sys.modules.pop("runner.compose_executor", None)
    monkeypatch.setattr(runner.langgraph_base, "PROJECT_ROOT", tmp_path)
    import runner.memory.service
    assert "runner.compose_executor" not in sys.modules


def test_compose_exports_remain_available_on_demand():
    import runner

    module = importlib.import_module("runner.compose_executor")
    assert runner.execute_compose_flow is module.execute_compose_flow
