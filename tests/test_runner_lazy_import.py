import importlib
import sys


def test_memory_import_does_not_load_execution_engine():
    sys.modules.pop("runner.langgraph_base", None)
    sys.modules.pop("runner.compose_executor", None)
    import runner.memory.service

    assert "runner.langgraph_base" not in sys.modules
    assert "runner.compose_executor" not in sys.modules


def test_compose_exports_remain_available_on_demand():
    import runner

    module = importlib.import_module("runner.compose_executor")
    assert runner.execute_compose_flow is module.execute_compose_flow
