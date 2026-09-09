"""Export the reviewed tools' actual MCP wire schemas without calling tools.

Run from the trusted QuantCode source checkout with its installed Python
dependencies: python -m quantcode.catalog.export --output /private/schemas.json
This neither discovers a remote service nor publishes a runtime grant.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    review_file = root / "quantcode/catalog/organization-tools.review.json"
    review_bytes = review_file.read_bytes()
    review = json.loads(review_bytes)
    sources: dict[Path, str] = {}
    for relative, expected in review["reviewed_sources"].items():
        source = root / relative
        if not source.resolve().is_relative_to(root) or source.is_symlink():
            raise ValueError("Review source must remain inside the trusted checkout")
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Reviewed implementation changed: {relative}; review it before exporting schemas")
        sources[source] = expected

    # Reuse the very same converter and registry as tools/list. Import performs
    # registration only; no _get_model, list_tools, identity or execute call.
    from quantcode.mcp_server import tool_def_to_mcp
    from tools.registry import registry

    names = [entry["tool"] for entry in review["tools"]]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate reviewed tool declarations")
    tools = []
    for entry in review["tools"]:
        tool = registry.get(entry["tool"])
        # The implementation binding is explicit, including decorated legacy
        # executors; names and annotations do not determine the effect policy.
        implementation = tool.execute
        if (implementation.__module__.replace(".", "/") + ".py" != entry["source"]["file"]
                or implementation.__name__ != entry["source"]["symbol"]):
            raise ValueError(f"Tool implementation module changed: {entry['tool']}")
        tools.append(tool_def_to_mcp(tool))
    for source, expected in sources.items():
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError("Reviewed source changed during schema export")
    if review_file.read_bytes() != review_bytes:
        raise ValueError("Effect review changed during schema export")
    output = args.output
    if os.name == "nt":
        raise PermissionError("Host schema export requires Windows ACL verification on this platform")
    if not output.is_absolute() or output.parent.resolve() != output.parent:
        raise ValueError("Output must use an absolute canonical private directory")
    info = output.parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise PermissionError("Schema output directory must be private and owned by the host account")
    payload = {"version": 1, "review_digest": hashlib.sha256(review_bytes).hexdigest(), "tools": tools}
    content = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps({"tools": len(tools), "digest": hashlib.sha256(content).hexdigest()}))


if __name__ == "__main__":
    main()
