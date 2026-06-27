"""QuantCode acceptance runner.

吃一个符合 schema 的 JSON，吐 pass / fail 结论。
所有 skill 共用本 runner，避免每个 skill 各写一套验收逻辑。
"""

from .acceptance import run_acceptance
from .schema_validator import validate_against_schema

__all__ = ["run_acceptance", "validate_against_schema"]
__version__ = "0.0.1"
