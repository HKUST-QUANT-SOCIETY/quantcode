"""QuantEvaluator adapter.

The adapter never calculates factor metrics and never substitutes mock values.
When the canonical service is unavailable, it returns an explicit UNAVAILABLE
component envelope.
"""
from __future__ import annotations

import ipaddress
import json
import os
import socket
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field

from schemas.component_call_result import ComponentCallResult, ComponentResultStatus
from tools.registry import ToolDef


class QuantEvaluatorArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: dict = Field(description="Validated FactorSpec serialized as JSON")


def _result(
    status: ComponentResultStatus,
    *,
    output_data: dict | None = None,
    errors: list[str] | None = None,
) -> dict:
    return ComponentCallResult(
        component_id="quant-evaluator",
        component_version=os.environ.get("QUANT_EVALUATOR_VERSION", "unknown"),
        contract_version="component-call-result.v1",
        environment=os.environ.get("QUANT_EVALUATOR_ENV", "unavailable"),
        result_status=status,
        source=os.environ.get("QUANT_EVALUATOR_API_URL", "not-configured"),
        observed_at=datetime.now(timezone.utc),
        output_data=output_data,
        errors=errors or [],
    ).model_dump(mode="json")


def quant_evaluator_execute(args: QuantEvaluatorArgs, ctx: dict) -> dict:
    token = os.environ.get("QUANT_EVALUATOR_API_KEY", "")
    url = os.environ.get("QUANT_EVALUATOR_API_URL", "").rstrip("/")

    # SSRF 白名单边界（与请求同函数）：endpoint host 必须显式登记在
    # QUANT_EVALUATOR_API_ALLOWED_HOSTS（逗号分隔白名单，未配置即拒绝），
    # 协议仅允许 https，且白名单主机解析出的地址不得是环回/私有/保留地址。
    if url:
        allowed_hosts = {
            item.strip().lower()
            for item in os.environ.get("QUANT_EVALUATOR_API_ALLOWED_HOSTS", "").split(",")
            if item.strip()
        }
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host:
            return _result(
                ComponentResultStatus.UNAVAILABLE,
                errors=["QuantEvaluator endpoint must be an https URL with a host"],
            )
        if host not in allowed_hosts:
            return _result(
                ComponentResultStatus.UNAVAILABLE,
                errors=["QuantEvaluator endpoint host is not in the allowlist"],
            )
        port = parsed.port or 443
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError:
            return _result(
                ComponentResultStatus.UNAVAILABLE,
                errors=[f"QuantEvaluator endpoint host does not resolve: {host}"],
            )
        for info in sorted({address[4][0] for address in infos}):
            ip = ipaddress.ip_address(info)
            if (
                ip.is_loopback
                or ip.is_private
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
                or ip.is_unspecified
            ):
                return _result(
                    ComponentResultStatus.UNAVAILABLE,
                    errors=[f"QuantEvaluator endpoint host resolves to a forbidden address: {ip}"],
                )

    if not url or not token:
        return _result(
            ComponentResultStatus.UNAVAILABLE,
            errors=["QuantEvaluator endpoint or credential is not configured"],
        )

    try:
        with httpx.Client(timeout=120, follow_redirects=False) as client:
            response = client.post(
                f"{url}/evaluate",
                content=json.dumps({"factor_spec": args.spec, "version": "v1"}),
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
    except (httpx.HTTPError, ValueError) as exc:
        return _result(
            ComponentResultStatus.UNAVAILABLE,
            errors=[f"QuantEvaluator call failed: {type(exc).__name__}"],
        )
    if response.status_code != 200:
        return _result(
            ComponentResultStatus.UNAVAILABLE,
            errors=[f"QuantEvaluator call returned HTTP {response.status_code}"],
        )
    try:
        payload = json.loads(response.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _result(ComponentResultStatus.FAILED, errors=["invalid response object"])
    if not isinstance(payload, dict):
        return _result(ComponentResultStatus.FAILED, errors=["invalid response object"])
    return _result(ComponentResultStatus.SUCCEEDED, output_data=payload)


quant_evaluator_tool = ToolDef(
    id="quant_evaluator",
    description=(
        "Call the canonical QuantEvaluator with a validated FactorSpec. Returns a "
        "component envelope; unavailable services never fall back to mock metrics."
    ),
    schema=QuantEvaluatorArgs,
    execute=quant_evaluator_execute,
)
