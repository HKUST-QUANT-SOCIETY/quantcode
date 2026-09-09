"""Compatibility transport around the archived Runner, never another agent loop.

The host selects the model and supplies each completion over private stdio. The
original graph owns checkpoints, Gate replay and tool receipts. This small
ledger covers only provider calls made after compatibility recovery begins.
"""
from __future__ import annotations

import hashlib
import base64
import importlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import signal
import sqlite3
import sys
import time
import uuid
from quantcode.legacy_contract import RuntimeDefinition, graph_state, verify_runtime
from quantcode.legacy_usage import usage_state
from runner.run_history import legacy_checkpoint_binding


class _SourceLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Load the registered archive bytes, without mixing installed Runner code."""

    def __init__(self, entry: dict):
        self.root = Path(entry["source_root"])
        self.files = {}
        self.resources = {}
        total = 0
        for relative, digest in entry["source_files"].items():
            source = self.root / relative
            content = source.read_bytes()
            if hashlib.sha256(content).hexdigest() != digest:
                raise PermissionError("archived executor source changed before load")
            total += len(content)
            if total > 64_000_000:
                raise ValueError("registered executor source exceeds the compatibility limit")
            if relative.endswith(".py"):
                name = relative[:-3].replace("/", ".")
                package = name.endswith(".__init__")
                name = name.removesuffix(".__init__")
                if name in self.files:
                    raise ValueError("archived source has conflicting Python module names")
                self.files[name] = (str(source), content, package)
            else:
                self.resources[source] = digest
        self.packages = {name.split(".")[0] for name in self.files}

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] not in self.packages:
            relative = self.root.joinpath(*fullname.split("."))
            if relative.is_dir() or relative.with_suffix(".py").exists():
                raise ImportError("archived executor imported an unregistered package: " + fullname)
            return None
        if fullname not in self.files:
            raise ImportError("archived executor imported an unregistered source: " + fullname)
        filename, _, package = self.files[fullname]
        return importlib.util.spec_from_file_location(fullname, filename, loader=self,
                                                     submodule_search_locations=[str(Path(filename).parent)] if package else None)

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        filename, content, _ = self.files[module.__name__]
        exec(compile(content, filename, "exec", dont_inherit=True), module.__dict__)

    def verify_resources(self):
        for path, digest in self.resources.items():
            if not path.resolve().is_relative_to(self.root) or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise PermissionError("archived executor resource changed")


class _Bridge:
    def __init__(self, database: Path, binding: dict, context: dict, credential: bytes, values: dict, source: _SourceLoader, approval_check=None):
        self.database = database
        self.binding = binding
        self.context = context
        self.credential = credential
        self.source = source
        self.approval_check = approval_check
        self.sequence = 0
        self.output = sys.__stdout__
        self.input = sys.stdin.buffer
        # Third-party tool prints are not protocol frames or browser output.
        sys.stdout = sys.stderr
        self.provider = self.exchange("ready", {})
        if set(self.provider) != {"provider", "model", "max_output"} or not isinstance(self.provider["max_output"], int) or self.provider["max_output"] <= 0:
            raise ValueError("invalid host Provider preparation")
        limit = os.environ.get("QUANTCODE_TOKEN_BUDGET", "200000")
        if not limit.isdigit():
            raise ValueError("invalid host token budget")
        self.limit = int(limit) or None
        from runner.agent_nodes import budget_total
        old_limit = budget_total(values)
        if old_limit:
            self.limit = min(old_limit, self.limit) if self.limit else old_limit
        self.path = database.with_suffix(".legacy-usage.db")
        # Exclusive task admission is held by legacy_host for this lifecycle.
        if self.path.exists():
            usage_state(database, binding["thread_id"], binding["owner_digest"])
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("CREATE TABLE IF NOT EXISTS legacy_usage_owner (thread_id TEXT PRIMARY KEY,owner_digest TEXT NOT NULL,baseline INTEGER NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS legacy_model_usage (thread_id TEXT NOT NULL,request_id TEXT PRIMARY KEY,provider TEXT NOT NULL,model TEXT NOT NULL,created REAL NOT NULL,reserved INTEGER NOT NULL,input INTEGER,output INTEGER,total INTEGER,cost REAL)")
            conn.execute("INSERT OR IGNORE INTO legacy_usage_owner VALUES(?,?,?)", (binding["thread_id"], binding["owner_digest"], int(values.get("budget_used") or 0)))
        self.guard()

    def exchange(self, kind: str, payload: dict) -> dict:
        self.sequence += 1
        message = {"type": kind, "sequence": self.sequence, **payload}
        raw = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        if len(raw.encode()) > 8_000_000:
            raise ValueError("legacy Provider request exceeds the transport limit")
        self.output.write(raw + "\n")
        self.output.flush()
        reply = self.input.readline(8_000_001)
        if not reply or len(reply) > 8_000_000 or not reply.endswith(b"\n"):
            raise InterruptedError("legacy host disconnected; unresolved reservations remain recorded")
        value = json.loads(reply)
        if not isinstance(value, dict) or value.get("sequence") != self.sequence:
            raise PermissionError("legacy host response does not match its request")
        if value.get("error"):
            raise InterruptedError(str(value["error"]))
        return value["result"]

    def guard(self) -> None:
        self.source.verify_resources()
        path = Path(os.environ["QUANTCODE_IDENTITY_SESSION_FILE"])
        if path.is_symlink() or path.read_bytes() != self.credential:
            raise PermissionError("legacy recovery login changed")
        self.exchange("authorize", {})
        if self.approval_check:
            self.approval_check()
        state = usage_state(self.database, self.binding["thread_id"], self.binding["owner_digest"])
        if state["unconfirmed_requests"]:
            raise PermissionError("legacy model usage is unknown; reconcile the original request before continuation")
        if self.limit is not None and state["used_tokens"] >= self.limit:
            raise PermissionError("stopped_budget: legacy task token budget exhausted")

    def model(self, messages, tools=None):
        self.guard()
        wire = []
        for message in messages:
            kind = getattr(message, "type", "")
            content = getattr(message, "content", "")
            # URLs and structured media would require provider-specific token
            # accounting and attachment authorization; never coerce them to text.
            if not isinstance(content, str) or kind not in {"system", "human", "ai", "tool"}:
                raise ValueError("archived message format is not supported by the registered compatibility bridge")
            wire.append({"type": kind, "content": content, "tool_calls": getattr(message, "tool_calls", []) or [],
                         "tool_call_id": getattr(message, "tool_call_id", None), "name": getattr(message, "name", None)})
        definitions = [{"name": item.id, "description": item.description, "schema": item.schema.model_json_schema()} for item in tools or []]
        estimate = len(json.dumps({"messages": wire, "tools": definitions}, ensure_ascii=False).encode()) + 1024 + 64 * (len(wire) + len(definitions))
        state = usage_state(self.database, self.binding["thread_id"], self.binding["owner_digest"])
        remaining = None if self.limit is None else self.limit - state["used_tokens"] - state["reserved_tokens"]
        if remaining is not None and estimate >= remaining:
            raise PermissionError("stopped_budget: legacy task cannot reserve the next model request")
        output_limit = min(self.provider["max_output"], remaining - estimate) if remaining is not None else self.provider["max_output"]
        request_id = uuid.uuid4().hex
        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("INSERT INTO legacy_model_usage(thread_id,request_id,provider,model,created,reserved) VALUES(?,?,?,?,?,?)",
                         (self.binding["thread_id"], request_id, self.provider["provider"], self.provider["model"], time.time(), estimate + output_limit))
        result = self.exchange("model", {"request_id": request_id, "messages": wire, "tools": definitions, "max_output": output_limit})
        usage = result.get("usage", {})
        if any(type(usage.get(key)) is not int or usage[key] < 0 for key in ("input", "output", "total")) or usage["total"] < usage["input"] + usage["output"]:
            raise ValueError("host Provider did not return an actual usage receipt; reservation retained")
        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA synchronous=FULL")
            cursor = conn.execute("UPDATE legacy_model_usage SET input=?,output=?,total=?,cost=? WHERE request_id=? AND thread_id=? AND total IS NULL",
                                 (usage["input"], usage["output"], usage["total"], usage.get("cost"), request_id, self.binding["thread_id"]))
            if cursor.rowcount != 1:
                raise ValueError("legacy model usage was already settled or lost")
        # Persist actual spend even if authorization was revoked in flight.
        self.exchange("authorize", {})
        from langchain_core.messages import AIMessage
        return AIMessage(content=result["text"], tool_calls=result["tool_calls"], usage_metadata={
            "input_tokens": usage["input"], "output_tokens": usage["output"], "total_tokens": usage["total"]})


def resume_checkpoint(value, binding: dict, recovery: dict, entry: dict, context: dict, database: Path, credential: bytes, record_continuation, approval_check=None) -> dict:
    """Call the original exact-source graph with resume=True, never init state."""
    source = _SourceLoader(entry)
    runtime = RuntimeDefinition.model_validate(entry.get("runtime"))
    workspace = Path(context["workspace_path"]).resolve()
    if source.root.resolve().is_relative_to(workspace):
        raise PermissionError("archived executable sources must be kept outside the writable task workspace")
    sys.stdout = sys.stderr
    # Preserve current host references on this stack; all archived imports use
    # the complete registered source map from this point onward.
    for name in list(sys.modules):
        if name.split(".")[0] in source.packages:
            del sys.modules[name]
    sys.meta_path.insert(0, source)
    installed = str(Path(__file__).resolve().parent.parent)
    sys.path[:] = [item for item in sys.path if str(Path(item).resolve()) != installed]
    sys.path.insert(0, str(source.root))
    os.environ["QUANTCODE_EVIDENCE_DIR"] = str(database.parent / "evidence")
    engine = importlib.import_module("runner.agent_engine")
    base = importlib.import_module("runner.langgraph_base")
    channel = importlib.import_module("runner.stream_channel")
    channel.STREAMS_DIR = database.parent / "streams"
    metrics = importlib.import_module("runner.metrics")
    metrics.METRICS_PATH = database.parent / "metrics.jsonl"
    evidence = importlib.import_module("runner.evidence")
    evidence.EVIDENCE_DIR = database.parent / "evidence"
    blackboard = importlib.import_module("runner.blackboard")
    blackboard.DEFAULT_BLACKBOARD_DB = database.parent / "blackboard.db"
    workflow = importlib.import_module("runner.solution_workflow")
    workflow.SOLUTIONS_DIR = workspace / "artifacts" / "solutions"
    mcp = importlib.import_module("quantcode.mcp_server")
    config = {"configurable": {"thread_id": binding["thread_id"]}}
    saved = base.get_checkpointer(database).get_tuple(config)
    if saved is None or saved.config["configurable"].get("checkpoint_id") != binding["checkpoint_id"]:
        raise ValueError("archived executor checkpoint changed")
    values = saved.checkpoint["channel_values"]
    if values.get("_blackboard_db_path") and not Path(values["_blackboard_db_path"]).is_file():
        raise ValueError("original legacy Blackboard store is unavailable")
    if values.get("solution_id") and not Path(values.get("_blackboard_db_path") or blackboard.DEFAULT_BLACKBOARD_DB).is_file():
        raise ValueError("original legacy solution store is unavailable")
    approval = approval_check() if approval_check else None
    decision = approval["decision"]["decision"] if approval else None
    if decision:
        gate_module = importlib.import_module("runner.human_gate")
        gate = gate_module.pending_gate_from_writes(saved.pending_writes)
        if not gate or gate.get("gate_id") != value.expected_gate_id:
            raise PermissionError("legacy Gate changed before recovery")
    bridge = _Bridge(database, binding, context, credential, values, source, approval_check)
    def interrupted(signum, frame):
        # Unwind the original graph once. Tool receipt STARTED rows survive;
        # never turn a cancellation into a retryable model/tool exception.
        raise KeyboardInterrupt("legacy recovery cancelled")

    previous_signal = signal.signal(signal.SIGTERM, interrupted)
    original_command = engine.Command
    original_admission = getattr(engine, "_quantcode_legacy_recovery_admission", None)
    try:
        # Reuse the installed graph's registry and group/role filtering. Each
        # archived tool is reauthorized immediately before its original call.
        allowed = {item.id for item in mcp._tools_for_session(context["group"], context["role"])}
        excluded = set(getattr(mcp, "_NATIVE_EXCLUDED_TOOLS", ())) | {
            "run_agent", "spawn_subagent", "spawn_agent_python", "run_compose", "spawn_parallel_agents",
            "check_subagent", "kill_subagent", "list_subagents", "match_main", "gen_schema", "llm_complete", "llm_chat",
        }
        allowed -= excluded
        if runtime.constructor.allowed_tool_ids is not None:
            allowed &= set(runtime.constructor.allowed_tool_ids)
        original_call = mcp.registry.call

        def call(tool_id, args, ctx=None):
            bridge.guard()
            if tool_id not in allowed:
                raise PermissionError("tool is not available to legacy compatibility recovery")
            if any((ctx or {}).get(field) != context.get(field) for field in ("actor_id", "group", "role", "workspace_id", "workspace_path", "github_subject")):
                raise PermissionError("legacy tool context differs from the current owner")
            # Reauthorize with this login while preserving the checkpoint's
            # creator session for audit; receipt identity excludes login IDs.
            controlled = {**(ctx or {}), "session_id": context["session_id"],
                          "legacy_creator_session_id": binding["owner"].get("session_id")}
            # These reviewed control tools only change graph state or suspend
            # its own Gate. Domain implementations always run in the host's
            # isolated component process; they never receive these stores.
            if tool_id in {"request_human_review", "mark_task_done"}:
                return original_call(tool_id, args, controlled)
            readonly = workflow.is_readonly_tool(tool_id)
            write_paths = []
            if not readonly:
                current = base.get_checkpointer(database).get_tuple(config)
                state = current.checkpoint["channel_values"] if current else {}
                document = workflow.SolutionStore(blackboard_db_path=state.get("_blackboard_db_path")).get(str(state.get("solution_id") or ""))
                if document is None or str(document.status.value) != "frozen":
                    raise PermissionError("legacy component writes require the original frozen solution and exact file scope")
                write_paths = list(document.file_impact)
                if not write_paths:
                    raise PermissionError("legacy frozen solution has no component write scope")
            result = bridge.exchange("tool", {"tool_id": tool_id, "args": args,
                "context": {field: controlled.get(field) for field in (
                    "actor_id", "role", "group", "workspace_id", "workspace_path", "github_subject", "resource_scopes", "session_id", "thread_id")},
                "source_root": entry["source_root"], "source_files": entry["source_files"],
                "write_paths": write_paths, "readonly": readonly})
            if result.get("ok") is not True:
                raise PermissionError(str(result.get("reason") or "legacy component did not return an execution receipt"))
            payload = base64.b64decode(result["payload_base64"], validate=True)
            # Sandbox output is data. JsonPlus constructor extension hooks
            # must never instantiate arbitrary worker-supplied classes here.
            if result["kind"] == "json":
                return json.loads(payload)
            if result["kind"] == "bytes":
                return payload
            if result["kind"] == "bytearray":
                return bytearray(payload)
            if result["kind"] == "null" and not payload:
                return None
            raise ValueError("legacy component returned an unsupported result type")

        mcp.registry.call = call
        loop_detector = importlib.import_module("tools.loop_detector").LoopDetector(**runtime.constructor.loop_detector.model_dump())
        constructor = runtime.constructor.model_dump(exclude={"registry", "allowed_tool_ids", "loop_detector"})
        runner = engine.AgentRunner(group=context["group"], model=bridge.model, registry=mcp.registry, loop_detector=loop_detector,
                                    checkpoint_db=database, allowed_tool_ids=allowed,
                                    **constructor,
                                    **{key: context.get(key) for key in ("actor_id", "role", "session_id", "workspace_id", "workspace_path", "github_subject", "resource_scopes")})
        arguments = {"thread_id": binding["thread_id"], "system_prompt": values.get("system_prompt") or "",
                     "flow_name": values.get("flow_name") or "agent"}
        def admit_archived(instance, operation, request):
            if instance is not runner or Path(instance.checkpoint_db).resolve() != database.resolve():
                raise PermissionError("legacy admission belongs to another archived runner")
            if operation == "build":
                bridge.guard()
                return
            if operation != "stream" or request.get("thread_id") != binding["thread_id"] or request.get("resume") is not True or \
                    request.get("task") or request.get("skill_name") or request.get("meta_skills"):
                raise PermissionError("verified legacy recovery cannot admit a new task or another thread")
            bridge.guard()

        # Only this already verified archive receives an admission capability.
        # The installed Runner and any other instance remain retired in native
        # mode; no client flag or ordinary resume=True can create this binding.
        engine._quantcode_legacy_recovery_admission = admit_archived
        bridge.guard()
        app = runner.build(system_prompt=arguments["system_prompt"])
        snapshot = app.get_state(config)
        verify_runtime(runtime, app, snapshot)
        if not getattr(snapshot, "next", ()):
            raise ValueError("the archived graph has no pending execution to resume")
        if approval:
            original_validate = runner._validate_resume_checkpoint
            def validated_resume(app, thread_id, *, decision):
                if not decision:
                    return original_validate(app, thread_id, decision=False)
                bridge.guard()
                if thread_id != binding["thread_id"] or legacy_checkpoint_binding(context, thread_id=thread_id, db_path=database) != binding:
                    raise PermissionError("legacy approval checkpoint changed before Command admission")
                current = app.get_state(config)
                verify_runtime(runtime, app, current)
                engine.validate_execution_skill(current.values)
                receipts = importlib.import_module("runner.tool_receipts")
                if receipts.unresolved_receipts(database.with_suffix(".tool-receipts.db"), thread_id):
                    raise PermissionError("legacy approval cannot replay an unresolved tool outcome")
                return current.values

            def approved_command(**kwargs):
                current = approval_check()
                payload = kwargs.get("resume")
                if set(kwargs) != {"resume"} or not isinstance(payload, dict) or payload.get("gate_id") != value.expected_gate_id:
                    raise PermissionError("legacy approval does not match the original Command Gate")
                gate_module = importlib.import_module("runner.human_gate")
                if gate_module.normalize_external_decision(payload.get("decision")) != current["decision"]["decision"]:
                    raise PermissionError("legacy Command decision differs from the gateway receipt")
                evidence.append_event(binding["thread_id"], "output_data", {"legacy_gateway_decision": {
                    "gate_id": current["gate_id"], "legacy_gate_id": value.expected_gate_id,
                    "record_digest": current["record_digest"], "decision": current["decision"],
                }}, database.parent / "evidence", required=True)
                return original_command(resume={**payload, "decided_by": current["decision"]["reviewer"]})

            # Compatibility seams only: the original graph, node functions,
            # Owner role and tool contexts remain unchanged. The gateway is
            # the authority for this exact resume Command, never model text.
            runner._validate_resume_checkpoint = validated_resume
            engine.Command = approved_command
        try:
            final = runner.stream(task="", resume_decision=decision, **arguments) if decision else runner.stream(
                task="", resume=True, **arguments)
        finally:
            # A handled interruption/error can still leave a valid new
            # checkpoint. Record the executor that actually wrote it, while
            # holding the original writer lock, without clearing uncertainty.
            after = graph_state(app, app.get_state(config))
            latest = record_continuation({key: after[key] for key in ("next_nodes", "pending_tasks")})
        bridge.exchange("authorize", {})
        usage = usage_state(database, binding["thread_id"], binding["owner_digest"])
        return {"engine": "legacy-python", "thread_id": binding["thread_id"], "checkpoint_id": binding["checkpoint_id"],
                "latest_checkpoint_id": latest["checkpoint_id"], "resumed": True, "read_only": False,
                "status": "rejected" if decision == "reject" else engine._run_status(final),
                "recovery": {**recovery, "available": False, "gate_available": False, "usage": usage,
                             "blockers": [{"code": "reload_required", "message": "恢复已结束；继续前需重新核对最新检查点。"}]}}
    finally:
        engine.Command = original_command
        if original_admission is None:
            engine.__dict__.pop("_quantcode_legacy_recovery_admission", None)
        else:
            engine._quantcode_legacy_recovery_admission = original_admission
        signal.signal(signal.SIGTERM, previous_signal)
        sys.stdout = bridge.output
