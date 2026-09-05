"""Canonical session groups; roles and GitHub teams remain separate authorities."""
from typing import Literal, get_args

GroupId = Literal["fundamental", "factor", "model", "risk", "strategy", "options", "infra", "agent"]
GROUP_IDS: tuple[str, ...] = get_args(GroupId)
