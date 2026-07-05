"""Model-group tools for PR metadata extraction and risk handoff."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

from schemas import BlackboardScope, GroupName, ModelSpec, WritePolicy

try:
    from runner.blackboard import DEFAULT_SESSION_ID, BlackboardService
except ModuleNotFoundError as exc:
    if exc.name != "langgraph":
        raise
    import importlib.util

    blackboard_path = Path(__file__).resolve().parents[1] / "runner" / "blackboard.py"
    spec = importlib.util.spec_from_file_location("_quantcode_blackboard", blackboard_path)
    if spec is None or spec.loader is None:
        raise
    blackboard_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(blackboard_module)
    DEFAULT_SESSION_ID = blackboard_module.DEFAULT_SESSION_ID
    BlackboardService = blackboard_module.BlackboardService

MODEL_GROUP = GroupName.MODEL
RISK_GROUP = GroupName.RISK
DEFAULT_TASK_ID = "T1"


def _safe_key_part(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._:/-]+", "_", value.strip())
    return cleaned.strip("._:/-") or "model"


def _dump_spec(spec: ModelSpec) -> dict[str, Any]:
    return spec.model_dump(mode="json")


def _read_text_from_pr_input(pr: dict[str, Any] | str | Path) -> tuple[str, str | None, str | None]:
    if isinstance(pr, dict):
        return str(pr.get("body", "")), pr.get("pr_url"), pr.get("source")
    path = Path(pr)
    if path.exists():
        return path.read_text(encoding="utf-8"), None, str(path)
    return str(pr), None, None


def _find_pr_url(text: str) -> str | None:
    match = re.search(r"https?://[^\s)>\]]+", text)
    return match.group(0).rstrip(".,") if match else None


def _extract_first_json_object(text: str, *, marker: str = "ModelSpec") -> dict[str, Any]:
    start_at = text.lower().find(marker.lower())
    if start_at < 0:
        start_at = 0
    decoder = json.JSONDecoder()
    start = text.find("{", start_at)
    while start >= 0:
        try:
            obj, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        if not isinstance(obj, dict):
            raise ValueError("ModelSpec JSON block must be an object")
        return obj
    raise ValueError("Could not find a ModelSpec JSON object in the PR body")


def read_pr(pr_path: str | Path) -> dict[str, Any]:
    """Read a PR fixture/body from disk and return text plus detected URL."""

    path = Path(pr_path)
    body = path.read_text(encoding="utf-8")
    return {
        "source": str(path),
        "body": body,
        "pr_url": _find_pr_url(body),
    }


def extract_metadata(pr: dict[str, Any] | str | Path) -> dict[str, Any]:
    """Extract the first JSON ModelSpec block from a PR body."""

    body, pr_url, _source = _read_text_from_pr_input(pr)
    metadata = _extract_first_json_object(body)
    detected_pr_url = pr_url or _find_pr_url(body)
    if detected_pr_url and not metadata.get("pr_url"):
        metadata["pr_url"] = detected_pr_url
    return metadata


def generate_model_spec(metadata: dict[str, Any] | ModelSpec) -> ModelSpec:
    """Validate extracted metadata against the Day 1 ModelSpec schema."""

    if isinstance(metadata, ModelSpec):
        return metadata
    return ModelSpec.model_validate(metadata)


def write_blackboard(
    spec: dict[str, Any] | ModelSpec,
    *,
    db_path: str | Path | None = None,
    session_id: str = DEFAULT_SESSION_ID,
    task_id: str = DEFAULT_TASK_ID,
    blackboard: BlackboardService | None = None,
) -> dict[str, Any]:
    """Write private GROUP data and public PROJECT data for a model PR."""

    model_spec = generate_model_spec(spec)
    service = blackboard or BlackboardService(
        db_path,
        session_id=session_id,
        requester_group=MODEL_GROUP,
    )
    spec_value = _dump_spec(model_spec)
    model_key = _safe_key_part(model_spec.model_name)

    private_entry = service.write_value(
        scope=BlackboardScope.GROUP,
        group=MODEL_GROUP,
        key=f"model.private_specs.{model_key}",
        value=spec_value,
        write_policy=WritePolicy.OWNER,
        written_by_task_id=task_id,
        written_by_group=MODEL_GROUP,
        requester_group=MODEL_GROUP,
    )
    project_entry = service.write_value(
        scope=BlackboardScope.PROJECT,
        key=f"shared.model_specs.{model_key}",
        value=spec_value,
        write_policy=WritePolicy.GROUP_APPEND,
        written_by_task_id=task_id,
        written_by_group=MODEL_GROUP,
        requester_group=MODEL_GROUP,
    )

    return {
        "private_entry_key": private_entry.key,
        "project_entry_key": project_entry.key,
        "private_version": private_entry.version,
        "project_version": project_entry.version,
        "model_spec": spec_value,
    }


def trigger_risk_flow(
    spec: dict[str, Any] | ModelSpec,
    *,
    db_path: str | Path | None = None,
    session_id: str = DEFAULT_SESSION_ID,
    task_id: str = DEFAULT_TASK_ID,
    blackboard: BlackboardService | None = None,
) -> dict[str, Any]:
    """Queue a PROJECT-scope risk review handoff for the risk group."""

    model_spec = generate_model_spec(spec)
    service = blackboard or BlackboardService(
        db_path,
        session_id=session_id,
        requester_group=MODEL_GROUP,
    )
    model_key = _safe_key_part(model_spec.model_name)
    queue_key = "shared.pending_risk_reviews"
    existing = service.get_entry(
        BlackboardScope.PROJECT,
        None,
        queue_key,
        requester_group=MODEL_GROUP,
    )
    reviews: dict[str, Any] = {}
    if existing and isinstance(existing.value, dict):
        raw_reviews = existing.value.get("reviews", {})
        if isinstance(raw_reviews, dict):
            reviews.update(raw_reviews)

    review_id = model_spec.pr_url or model_spec.commit_sha or model_spec.model_name
    reviews[review_id] = {
        "from_group": MODEL_GROUP.value,
        "to_group": RISK_GROUP.value,
        "status": "pending",
        "model_name": model_spec.model_name,
        "model_spec_key": f"shared.model_specs.{model_key}",
        "pr_url": model_spec.pr_url,
        "commit_sha": model_spec.commit_sha,
    }
    queue_entry = service.write_value(
        scope=BlackboardScope.PROJECT,
        key=queue_key,
        value={"reviews": reviews},
        write_policy=WritePolicy.GROUP_APPEND,
        written_by_task_id=task_id,
        written_by_group=MODEL_GROUP,
        requester_group=MODEL_GROUP,
    )
    return {
        "risk_queue_key": queue_entry.key,
        "risk_queue_version": queue_entry.version,
        "review_id": review_id,
        "review": reviews[review_id],
    }


def _tool_result(value: Any) -> dict[str, Any]:
    if isinstance(value, ModelSpec):
        return _dump_spec(value)
    return value


def _dispatch_tool(name: str, arguments: dict[str, Any]) -> Any:
    dispatch: dict[str, Callable[..., Any]] = {
        "read_pr": read_pr,
        "extract_metadata": extract_metadata,
        "generate_model_spec": generate_model_spec,
        "write_blackboard": write_blackboard,
        "trigger_risk_flow": trigger_risk_flow,
    }
    if name not in dispatch:
        raise ValueError(f"Unknown tool: {name}")
    return _tool_result(dispatch[name](**arguments))


def _mcp_tools() -> list[dict[str, Any]]:
    string_arg = {"type": "string"}
    return [
        {
            "name": "read_pr",
            "description": "Read a local PR markdown fixture and detect its PR URL.",
            "inputSchema": {
                "type": "object",
                "properties": {"pr_path": string_arg},
                "required": ["pr_path"],
            },
        },
        {
            "name": "extract_metadata",
            "description": "Extract ModelSpec JSON metadata from PR text or read_pr output.",
            "inputSchema": {
                "type": "object",
                "properties": {"pr": {}},
                "required": ["pr"],
            },
        },
        {
            "name": "generate_model_spec",
            "description": "Validate metadata against schemas.model.ModelSpec.",
            "inputSchema": {
                "type": "object",
                "properties": {"metadata": {"type": "object"}},
                "required": ["metadata"],
            },
        },
        {
            "name": "write_blackboard",
            "description": "Write model private GROUP data and public PROJECT ModelSpec.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "spec": {"type": "object"},
                    "db_path": string_arg,
                    "session_id": string_arg,
                    "task_id": string_arg,
                },
                "required": ["spec"],
            },
        },
        {
            "name": "trigger_risk_flow",
            "description": "Queue PROJECT-scope shared.pending_risk_reviews for risk.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "spec": {"type": "object"},
                    "db_path": string_arg,
                    "session_id": string_arg,
                    "task_id": string_arg,
                },
                "required": ["spec"],
            },
        },
    ]


def _send_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _run_mcp_server() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        request = json.loads(line)
        method = request.get("method")
        request_id = request.get("id")
        if request_id is None:
            continue
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "quantcode-model-tools",
                        "version": "0.1.0",
                    },
                }
            elif method == "tools/list":
                result = {"tools": _mcp_tools()}
            elif method == "tools/call":
                params = request.get("params") or {}
                value = _dispatch_tool(
                    params["name"],
                    params.get("arguments") or {},
                )
                result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(value, ensure_ascii=False),
                        }
                    ],
                    "isError": False,
                }
            else:
                raise ValueError(f"Unsupported MCP method: {method}")
            _send_json({"jsonrpc": "2.0", "id": request_id, "result": result})
        except Exception as exc:  # noqa: BLE001
            _send_json(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32000, "message": str(exc)},
                }
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QuantCode model-group tools")
    parser.add_argument("pr_path", nargs="?")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--session-id", default=DEFAULT_SESSION_ID)
    parser.add_argument("--task-id", default=DEFAULT_TASK_ID)
    parser.add_argument("--mcp", action="store_true")
    args = parser.parse_args(argv)

    if args.mcp:
        _run_mcp_server()
        return 0
    if not args.pr_path:
        parser.error("pr_path is required unless --mcp is passed")
    pr = read_pr(args.pr_path)
    metadata = extract_metadata(pr)
    spec = generate_model_spec(metadata)
    service = BlackboardService(
        args.db_path,
        session_id=args.session_id,
        requester_group=MODEL_GROUP,
    )
    result = {
        "pr": {"source": pr["source"], "pr_url": pr["pr_url"]},
        "model_spec": _dump_spec(spec),
        "blackboard": write_blackboard(
            spec,
            blackboard=service,
            session_id=args.session_id,
            task_id=args.task_id,
        ),
        "risk_trigger": trigger_risk_flow(
            spec,
            blackboard=service,
            session_id=args.session_id,
            task_id=args.task_id,
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
