"""Deterministic four-axis task classification for v5 P-10."""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class BusinessMode(StrEnum):
    RESEARCH_ANALYSIS = "research_analysis"
    ENGINEERING = "engineering"
    COMPONENT_ADAPTATION = "component_adaptation"
    ADMIN_OPERATIONS = "admin_operations"
    ADMIN_DEPLOY = "admin_deploy"


class Complexity(StrEnum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class ExecutionStrategy(StrEnum):
    PLAN = "plan"
    BUILD = "build"
    COMPOSE = "compose"


class Governance(StrEnum):
    READ_ONLY = "read_only"
    PERSONAL_WORKSPACE_WRITE = "personal_workspace_write"
    SHARED_WRITE = "shared_write"
    CROSS_GROUP_RESTRICTED_ACCESS = "cross_group_restricted_access"
    ADMIN_PRODUCTION_ACTION = "admin_production_action"


class TaskClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_mode: BusinessMode
    complexity: Complexity
    execution_strategy: ExecutionStrategy
    governance: Governance
    solution_required: bool


_QUERY_WORDS = ("查询", "查看", "读取", "状态", "search", "inspect", "list", "explain")
_ADAPTER_WORDS = ("adapter", "适配", "接入组件", "contract")
_ENGINEERING_WORDS = ("实现", "修改", "重构", "build", "fix", "code")


def classify_task(
    task: str,
    *,
    file_count: int = 0,
    cross_repo: bool = False,
    shared_write: bool = False,
    restricted_access: bool = False,
    admin: bool = False,
    deploy: bool = False,
) -> TaskClassification:
    """Classify without using complexity as a permission decision."""
    text = task.lower()
    if deploy:
        if not admin:
            raise PermissionError("admin_deploy requires an Admin Session Context")
        business = BusinessMode.ADMIN_DEPLOY
        governance = Governance.ADMIN_PRODUCTION_ACTION
    elif admin:
        business = BusinessMode.ADMIN_OPERATIONS
        governance = Governance.READ_ONLY
    elif any(word in text for word in _ADAPTER_WORDS):
        business = BusinessMode.COMPONENT_ADAPTATION
        governance = Governance.PERSONAL_WORKSPACE_WRITE
    elif any(word in text for word in _ENGINEERING_WORDS):
        business = BusinessMode.ENGINEERING
        governance = Governance.PERSONAL_WORKSPACE_WRITE
    else:
        business = BusinessMode.RESEARCH_ANALYSIS
        governance = Governance.READ_ONLY

    if restricted_access:
        governance = Governance.CROSS_GROUP_RESTRICTED_ACCESS
    if shared_write:
        governance = Governance.SHARED_WRITE

    if shared_write:
        complexity = Complexity.L3
    elif cross_repo or file_count > 1:
        complexity = Complexity.L2
    elif governance == Governance.READ_ONLY and any(word in text for word in _QUERY_WORDS):
        complexity = Complexity.L0
    else:
        complexity = Complexity.L1

    strategy = (
        ExecutionStrategy.PLAN
        if complexity == Complexity.L0
        else ExecutionStrategy.COMPOSE
        if business in {BusinessMode.RESEARCH_ANALYSIS, BusinessMode.COMPONENT_ADAPTATION}
        else ExecutionStrategy.BUILD
    )
    return TaskClassification(
        business_mode=business,
        complexity=complexity,
        execution_strategy=strategy,
        governance=governance,
        solution_required=complexity in {Complexity.L2, Complexity.L3},
    )


__all__ = [
    "BusinessMode",
    "Complexity",
    "ExecutionStrategy",
    "Governance",
    "TaskClassification",
    "classify_task",
]
