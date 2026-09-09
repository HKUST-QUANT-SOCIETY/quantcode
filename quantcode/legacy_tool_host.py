"""One archived component invocation inside the existing OS process sandbox.

The trusted controller keeps graph, Gate, checkpoints and write receipts. This
worker receives no credentials or control database paths and never runs a graph.
Its archive copy is read-only; only the admitted workspace files can be written.
"""
from __future__ import annotations

import base64
import importlib
import importlib.abc
import importlib.machinery
import json
import os
from pathlib import Path
import sys


def _inert(value) -> None:
    if value is None or type(value) in {str, bool, int, float}:
        return
    if type(value) is list:
        for item in value:
            _inert(item)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _inert(item)
        return
    raise ValueError("legacy component result requires an unsupported custom type")


class _Archive(importlib.abc.MetaPathFinder):
    def __init__(self, root: Path):
        self.root = root
        self.packages = {item.relative_to(root).parts[0].removesuffix(".py") for item in root.rglob("*.py")}

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] not in self.packages:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if not spec or not spec.origin or not Path(spec.origin).resolve().is_relative_to(self.root):
            raise ImportError("component imported unregistered archive module: " + fullname)
        return spec


def main() -> None:
    output = sys.stdout
    sys.stdout = sys.stderr
    try:
        raw = sys.stdin.buffer.read(8_000_001)
        if len(raw) > 8_000_000:
            raise ValueError("legacy component invocation is too large")
        value = json.loads(raw)
        root = Path(os.environ["TMPDIR"]) / "executor"
        workspace = Path(value["context"]["workspace_path"])
        if not workspace.is_absolute() or workspace.resolve() != workspace:
            raise PermissionError("component workspace is not canonical")
        for library in value["python_paths"]:
            sys.path.insert(0, library)
        sys.path.insert(0, str(root))
        sys.meta_path.insert(0, _Archive(root))
        os.environ["OPENCODE_CHANNEL"] = "quantcode"
        os.environ["QUANTCODE_UNIFIED_RUNTIME"] = "1"
        # -I/-B plus the OS sandbox prevent workspace imports, bytecode writes,
        # network access, and access to original host credentials/control state.
        mcp = importlib.import_module("quantcode.mcp_server")
        registry = mcp.registry
        allowed = {item.id for item in mcp._tools_for_session(value["context"]["group"], value["context"]["role"])}
        if value["tool_id"] not in allowed:
            raise PermissionError("component is not in the archived owner allowlist")
        if value["tool_id"] in {
            "run_agent", "spawn_subagent", "spawn_agent_python", "run_compose", "spawn_parallel_agents",
            "check_subagent", "kill_subagent", "list_subagents", "match_main", "gen_schema", "llm_complete", "llm_chat",
        }:
            raise PermissionError("an archived component cannot start another executor")
        # Existing quant tools already use tools.registry.PROJECT_ROOT for
        # data/output locations. Keep policy/template paths bound to the
        # immutable archive while directing those ordinary files to workspace.
        for name, module in tuple(sys.modules.items()):
            if name.startswith("tools.") and getattr(module, "PROJECT_ROOT", None) == root:
                module.PROJECT_ROOT = workspace
        result = registry.call(value["tool_id"], value["args"], ctx=value["context"])
        # Only inert base types cross back into the privileged controller.
        # JsonPlus custom constructors belong to its own checkpoint store,
        # never to an isolated tool's response.
        if result is None:
            kind, payload = "null", b""
        elif isinstance(result, (bytes, bytearray)):
            kind, payload = "bytes" if isinstance(result, bytes) else "bytearray", bytes(result)
        else:
            _inert(result)
            kind, payload = "json", json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
        response = {"ok": True, "kind": kind, "payload_base64": base64.b64encode(payload).decode("ascii")}
        if len(json.dumps(response).encode()) > 8_000_000:
            raise ValueError("component result exceeds the compatibility transport limit")
    except PermissionError:
        response = {"ok": False, "reason": "该旧组件需要超出当前冻结方案的文件权限、宿主凭据或网络；隔离执行未获准。"}
    except BaseException as error:
        # GraphInterrupt is meaningful only inside the original controller's
        # graph. Never flatten it into a successful result or retry a write.
        kind = type(error).__name__
        response = {"ok": False, "reason": f"旧组件在隔离宿主中不可用（{kind}）；请核对原调用回执后继续。"}
    print(json.dumps(response, ensure_ascii=False), file=output, flush=True)


if __name__ == "__main__":
    main()
