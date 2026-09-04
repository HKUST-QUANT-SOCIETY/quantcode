"""QuantEvaluator adapter.

The adapter never calculates factor metrics and never substitutes mock values.
When the canonical service is unavailable, it returns an explicit UNAVAILABLE
component envelope.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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
    url = os.environ.get("QUANT_EVALUATOR_API_URL", "").rstrip("/")
    token = os.environ.get("QUANT_EVALUATOR_API_KEY", "")
    if not url or not token:
        return _result(
            ComponentResultStatus.UNAVAILABLE,
            errors=["QuantEvaluator endpoint or credential is not configured"],
        )

    request = Request(
        f"{url}/evaluate",
        data=json.dumps({"factor_spec": args.spec, "version": "v1"}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=120) as response:  # noqa: S310 - URL is admin config
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        return _result(
            ComponentResultStatus.UNAVAILABLE,
            errors=[f"QuantEvaluator call failed: {type(exc).__name__}"],
        )
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


__all__ = ["QuantEvaluatorArgs", "quant_evaluator_tool", "quant_evaluator_execute"]
