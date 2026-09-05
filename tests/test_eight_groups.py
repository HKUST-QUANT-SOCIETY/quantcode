import pytest

from schemas import GroupName
from schemas.groups import GROUP_IDS
from quantcode.roster import GROUP_ALIASES
from runner.distill.cards import RESEARCH_GROUPS
from tools.subagent._register import VALID_GROUPS


def test_platform_group_boundaries_agree():
    assert set(GROUP_IDS) == {group.value for group in GroupName} == RESEARCH_GROUPS == set(VALID_GROUPS)
    assert {"infra", "agent"} <= set(GROUP_IDS)


@pytest.mark.parametrize("group", ["infra", "agent"])
def test_new_groups_have_published_skill_and_capability_ownership(group):
    from quantcode.mcp_server import _list_skills_execute, ListSkillsArgs
    from schemas.capability_card import OwnerGroup
    from typing import get_args

    assert group in get_args(OwnerGroup)
    result = _list_skills_execute(ListSkillsArgs(group=group), {"group": group})
    assert any(item["id"] == group for item in result["skills"])
    # Tool admission is covered by real eight-group subprocess smoke tests;
    # unrelated unit suites intentionally clear the process-global registry.


def test_user_group_aliases():
    for label, group in [("基建组", "infra"), ("ai agent", "agent"), ("agent开发", "agent"),
                         ("风控组", "risk"), ("rl工程落地组", "factor"), ("因子挖掘组", "factor"), ("模型组", "model")]:
        assert GROUP_ALIASES[label] == group
