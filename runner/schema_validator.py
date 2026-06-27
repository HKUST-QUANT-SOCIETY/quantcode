"""JSON Schema 校验封装。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema


SCHEMA_DIR = Path(__file__).parent.parent / "schemas"


def validate_against_schema(payload: dict[str, Any], schema_name: str) -> None:
    """对 payload 做 schema 校验，失败抛 jsonschema.ValidationError。

    Args:
        payload: 待校验的 dict
        schema_name: 'risk-profile' / 'factor-report' / 'research-spec' / 'pipeline-task'
    """
    schema_path = SCHEMA_DIR / f"{schema_name}.schema.json"
    schema = json.loads(schema_path.read_text())
    jsonschema.validate(payload, schema)
