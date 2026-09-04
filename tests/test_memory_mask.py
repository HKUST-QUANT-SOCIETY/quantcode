"""P-07/F-04 权限 Mask 测试：无权限组检索不到被 Mask 的能力卡内容。

Mask 语义（复用 Memory GROUP 隔离，fail-closed，零 service.py 改动）：
- contract 卡（口径契约）→ Memory ``global`` scope：全组织 + 游客可检索；
- asset 卡（含数据字段清单类细节）→ Memory ``groups/<owner_group>`` scope：
  属组可检索；跨组 / 游客检索**命中 0 条**（行级过滤），
  显式 ``scope=groups`` 跨组读抛 ``MemoryPermissionError``。

端到端链路：``runner/distill/cards.distill_cards_to_memory`` 蒸馏落盘 →
不同 requester_group 的 ``MemoryService.search`` 验证可见性边界。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from runner.distill.cards import (
    card_memory_location,
    distill_cards_to_memory,
    load_cards,
)
from runner.memory.service import MemoryPermissionError, MemoryService

# 卡片正文里可作 FTS 查询词的 ASCII 关键 token（unicode61 分词稳定）。
_CONTRACT_TERM = "TargetReturnView"       # 契约卡 api_surface
_EVALUATOR_TERM = "EvaluationRequest"     # quant-evaluator（factor 属组）
_DATA_TERM = "get_store"                  # data-access（factor 属组，数据字段清单类）
_PLATFORM_TERM = "orchestrator"           # quant-platform（model 属组）


@pytest.fixture()
def distilled(tmp_path: Path) -> MemoryService:
    """Capability catalog 蒸馏进临时 Memory db。"""
    svc = MemoryService(tmp_path / "bb.db", root=tmp_path, auto_reconcile=False)
    written = distill_cards_to_memory(svc, load_cards())
    assert len(written) == 14
    return svc


def test_guest_cannot_search_asset_card_details(distilled):
    """游客组检索不到资产卡（数据字段清单类）细节——F-04 验收主断言。"""
    for term in (_EVALUATOR_TERM, _DATA_TERM, _PLATFORM_TERM):
        hits = distilled.search(query=term, requester_group=None)
        assert hits == [], f"游客检索到被 Mask 内容: term={term} hits={hits}"


def test_guest_can_search_contract_card(distilled):
    """契约卡落 global scope：游客（与任意组）都可检索口径。"""
    hits = distilled.search(query=_CONTRACT_TERM, requester_group=None)
    assert any("target-return-view-v1" in h.path for h in hits)


def test_owner_group_can_search_own_asset_cards(tmp_path: Path):
    svc = MemoryService(tmp_path / "bb.db", root=tmp_path, auto_reconcile=False)
    distill_cards_to_memory(svc, load_cards())
    hits = svc.search(query=_DATA_TERM, requester_group="factor")
    assert any("capability-card-data-access" in h.path for h in hits)


def test_cross_group_cannot_search_asset_card_details(tmp_path: Path):
    """跨组 fail-closed：model 组检索不到 factor 属组的资产卡细节（repo 权限同源）。"""
    svc = MemoryService(tmp_path / "bb.db", root=tmp_path, auto_reconcile=False)
    distill_cards_to_memory(svc, load_cards())
    for term in (_DATA_TERM, _EVALUATOR_TERM):
        assert svc.search(query=term, requester_group="model") == []
    # 反向：factor 组检索不到 model 属组的 quant-platform 卡细节。
    assert svc.search(query=_PLATFORM_TERM, requester_group="factor") == []


def test_explicit_groups_scope_cross_read_raises(tmp_path: Path):
    """显式 scope=groups 跨组读 → MemoryPermissionError（既有 GROUP 隔离 fail-closed）。"""
    svc = MemoryService(tmp_path / "bb.db", root=tmp_path, auto_reconcile=False)
    distill_cards_to_memory(svc, load_cards())
    with pytest.raises(MemoryPermissionError):
        svc.search(query=_DATA_TERM, scope="groups", scope_id="factor",
                   requester_group="model")
    with pytest.raises(MemoryPermissionError):
        svc.search(query=_DATA_TERM, scope="groups", scope_id="factor",
                   requester_group=None)  # 游客显式读属组 scope 同样拦截


def test_guest_digest_and_fts_are_consistently_masked(distilled):
    """纵深防御一致：常驻摘要（强保证）与 FTS 检索（弱保证）对游客同时 Mask 资产卡。"""
    from runner.distill.inject import capability_digest

    digest = capability_digest(None)
    assert "quant-evaluator" not in digest and "data-access" not in digest
    for term in (_EVALUATOR_TERM, _DATA_TERM):
        assert distilled.search(query=term, requester_group=None) == []


def test_memory_location_mapping_matches_isolation_semantics():
    """契约卡 → global（全可见）；资产卡 → groups/属组（隔离检索单元）。"""
    by_id = {c.id: c for c in load_cards()}
    assert card_memory_location(by_id["target-return-view-v1"])[0] == "global"
    for asset_id, owner in (
        ("quant-evaluator", "factor"),
        ("factor-engine", "factor"),
        ("data-access", "factor"),
        ("quant-platform", "model"),
        ("alpha-flow", "strategy"),
    ):
        scope, scope_id = card_memory_location(by_id[asset_id])
        assert (scope, scope_id) == ("groups", owner)
