"""P-07 能力卡片契约测试（specs/FUNCTIONAL_SPEC.md P-07 / F-04）。

覆盖：
- CapabilityCard 契约：type 枚举 / 必填 / extra=forbid / source_commit 默认；
- v2 能力目录从 configs/capabilities.yaml 加载（Step 0 实读蒸馏，见
  docs/audit/ASSET_INVENTORY.md）；
- 权限 Mask：游客组（None/guest/未知组）仅 contract 卡可见（fail-closed）；
- 常驻摘要：每卡一行 id+name+when_to_use、限长、摘要不含 api_surface 细节；
- JSON Schema（schemas/capability-card.schema.json）与 pydantic 契约一致性；
- list_capabilities 元工具（_meta 通道）经 ctx.group Mask。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from runner.distill.cards import (
    CAPABILITIES_CONFIG,
    card_memory_location,
    load_cards,
    strict_reuse_enabled,
    visible_cards,
)
from runner.distill.inject import (
    DEFAULT_DIGEST_MAX_CHARS,
    append_capability_digest,
    capability_digest,
)
from schemas.capability_card import CapabilityCard

PROJECT_ROOT = Path(__file__).resolve().parent.parent
YAML_PATH = PROJECT_ROOT / "configs" / "capabilities.yaml"
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "capability-card.schema.json"

# v2 catalog: one global contract plus the canonical chain and deploy scaffold.
EXPECTED_IDS = {
    "target-return-view-v1",
    "quant-evaluator",
    "factor-engine",
    "data-access",
    "quant-platform",
    "alpha-flow",
    "factor-optimizer",
    "factor-assets",
    "factor-preprocess",
    "modeling",
    "barra-engine",
    "riskfolio-qs",
    "vectorbt-qs",
    "platform-web",
}


# ---------------------------------------------------------------------------
# CapabilityCard 契约
# ---------------------------------------------------------------------------

_VALID_MINIMAL = {
    "id": "test-card",
    "name": "测试卡",
    "type": "asset",
    "when_to_use": "测试时",
    "when_not_to_reinvent": "已有测试卡时",
    "owner_group": "factor",
    "distilled_at": "2026-09-01",
}


def test_card_minimal_valid():
    card = CapabilityCard.model_validate(_VALID_MINIMAL)
    assert card.type == "asset"
    assert card.api_surface == []          # 默认空列表
    assert card.source_commit == ""        # in-repo 契约卡允许留空


def test_catalog_and_policy_refresh_without_restarting_process(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTCODE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("QUANTCODE_ENV", "test")
    path = tmp_path / "capabilities.yaml"
    path.write_text(yaml.safe_dump({"strict_reuse": False, "cards": [_VALID_MINIMAL]}))
    assert load_cards()[0].integration_status == "UNVERIFIED"
    assert strict_reuse_enabled() is False
    path.write_text(yaml.safe_dump({"strict_reuse": True, "cards": [{**_VALID_MINIMAL, "integration_status": "UNAVAILABLE"}]}))
    assert load_cards()[0].integration_status == "UNAVAILABLE"
    assert strict_reuse_enabled() is True
    path.write_text("cards: [broken")
    with pytest.raises(ValueError):
        load_cards()
    assert strict_reuse_enabled() is True


def test_duplicate_catalog_ids_are_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTCODE_CONFIG_DIR", str(tmp_path))
    (tmp_path / "capabilities.yaml").write_text(yaml.safe_dump({"cards": [_VALID_MINIMAL, _VALID_MINIMAL]}))
    with pytest.raises(ValueError, match="重复"):
        load_cards()


def test_admin_contract_is_not_visible_to_guests():
    card = CapabilityCard.model_validate({**_VALID_MINIMAL, "type": "contract", "visibility": "admin"})
    assert visible_cards([card], None) == []
    assert visible_cards([card], "factor", "analyst") == []
    assert visible_cards([card], "factor", "admin") == [card]


def test_card_type_enum_enforced():
    bad = dict(_VALID_MINIMAL, type="meeting-notes")  # 会议记忆不是合法蒸馏物
    with pytest.raises(ValidationError):
        CapabilityCard.model_validate(bad)
    for ok in ("asset", "contract"):
        CapabilityCard.model_validate(dict(_VALID_MINIMAL, type=ok))


def test_card_required_fields_enforced():
    for missing in ("id", "name", "type", "when_to_use", "when_not_to_reinvent",
                    "owner_group", "distilled_at"):
        broken = {k: v for k, v in _VALID_MINIMAL.items() if k != missing}
        with pytest.raises(ValidationError):
            CapabilityCard.model_validate(broken)


def test_card_extra_forbid():
    with pytest.raises(ValidationError):
        CapabilityCard.model_validate(dict(_VALID_MINIMAL, meeting_summary="凭会议记忆手写的内容"))


def test_card_distilled_at_iso_date_pattern():
    with pytest.raises(ValidationError):
        CapabilityCard.model_validate(dict(_VALID_MINIMAL, distilled_at="2026/09/01"))


# ---------------------------------------------------------------------------
# 能力目录从 yaml 加载
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def six_cards() -> list[CapabilityCard]:
    return load_cards()


def test_yaml_exists_and_loads_catalog(six_cards):
    assert YAML_PATH.is_file()
    assert {c.id for c in six_cards} == EXPECTED_IDS
    assert len(six_cards) == 14


def test_yaml_has_one_contract_and_truthful_asset_statuses(six_cards):
    by_id = {c.id: c for c in six_cards}
    assert by_id["target-return-view-v1"].type == "contract"
    assets = [c for c in six_cards if c.type == "asset"]
    assert len(assets) == 13
    for c in assets:
        assert c.canonical_repo
        assert c.maturity_status
        assert c.integration_status
        if not c.source_commit:
            assert c.integration_status == "UNVERIFIED"


def test_contract_card_references_target_return_view(six_cards):
    contract = next(c for c in six_cards if c.type == "contract")
    assert "TargetReturnView/v1" in json.dumps(contract.api_surface, ensure_ascii=False)
    assert contract.owner_group == "all"


def test_quant_evaluator_card_metric_count_from_step0(six_cards):
    """Step 0 实测口径：注册指标 60（CSV 实测），spec v0.2 的 51 为旧口径——卡片须登记差异。"""
    card = next(c for c in six_cards if c.id == "quant-evaluator")
    blob = json.dumps(card.api_surface + [card.when_to_use], ensure_ascii=False)
    assert "60" in blob


def test_yaml_strict_reuse_flag_present():
    # P-07 复用纪律开关：开发/测试可由 YAML 控制，生产运行时强制开启。
    assert isinstance(strict_reuse_enabled(), bool)


def test_production_defaults_to_strict_reuse(monkeypatch, tmp_path):
    """A stale false config must not disable the production reuse boundary."""
    (tmp_path / "capabilities.yaml").write_text("strict_reuse: false\ncards: []\n", encoding="utf-8")
    monkeypatch.setenv("QUANTCODE_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("QUANTCODE_ENV", raising=False)
    from runner import config_loader

    config_loader.load_yaml.cache_clear()
    try:
        assert strict_reuse_enabled() is True
    finally:
        config_loader.load_yaml.cache_clear()


def test_malformed_reuse_policy_fails_closed(monkeypatch, tmp_path):
    (tmp_path / "capabilities.yaml").write_text("strict_reuse: [broken\n", encoding="utf-8")
    monkeypatch.setenv("QUANTCODE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("QUANTCODE_ENV", "test")
    from runner import config_loader

    config_loader.load_yaml.cache_clear()
    try:
        assert strict_reuse_enabled() is True
    finally:
        config_loader.load_yaml.cache_clear()


def test_invalid_card_in_yaml_fails_fast(tmp_path, monkeypatch):
    # 坏卡 fail-fast（契约完整性）；inject 侧另行 best-effort 兜底。
    bad_yaml = "cards:\n  - id: bad-card\n    type: wrong-type\n"
    monkeypatch.setenv("QUANTCODE_CONFIG_DIR", str(tmp_path))
    (tmp_path / f"{CAPABILITIES_CONFIG}.yaml").write_text(bad_yaml, encoding="utf-8")
    from runner import config_loader

    config_loader.load_yaml.cache_clear()
    try:
        with pytest.raises(ValueError):
            load_cards()
    finally:
        config_loader.load_yaml.cache_clear()


# ---------------------------------------------------------------------------
# 权限 Mask（游客组仅 contract 可见，fail-closed）
# ---------------------------------------------------------------------------

def test_guest_group_sees_only_contract_cards(six_cards):
    for guest in (None, "", "guest", "unknown-group", "admin"):  # 未知组一律收紧
        visible = visible_cards(six_cards, guest)
        assert [c.id for c in visible] == ["target-return-view-v1"], f"group={guest!r}"


def test_authenticated_group_sees_all_cards(six_cards):
    for group in ("factor", "model", "strategy", "risk", "options", "fundamental"):
        assert {c.id for c in visible_cards(six_cards, group)} == EXPECTED_IDS - {"alpha-flow"}
    assert {c.id for c in visible_cards(six_cards, "strategy", "admin")} == EXPECTED_IDS


def test_asset_card_memory_location_is_groups_scope(six_cards):
    by_id = {c.id: c for c in six_cards}
    assert card_memory_location(by_id["target-return-view-v1"]) == ("global", None)
    assert card_memory_location(by_id["data-access"]) == ("groups", "factor")
    assert card_memory_location(by_id["quant-platform"]) == ("groups", "model")
    assert card_memory_location(by_id["alpha-flow"]) == ("groups", "strategy")


def test_asset_card_with_non_group_owner_rejected():
    card = CapabilityCard.model_validate(dict(_VALID_MINIMAL, owner_group="all"))
    with pytest.raises(ValueError):
        card_memory_location(card)  # asset 细节必须有具体属组才能落 groups scope


# ---------------------------------------------------------------------------
# 常驻摘要（限长 + 一行式 + 不含细节）
# ---------------------------------------------------------------------------

def test_digest_contains_one_line_per_card(six_cards):
    digest = capability_digest("factor", max_chars=10000)
    for card in visible_cards(six_cards, "factor"):
        assert f"- {card.id} | {card.name} | " in digest, f"缺 {card.id} 摘要行"
    assert "- alpha-flow | " not in digest
    # api_surface 细节不进常驻摘要（数据字段清单类细节 Mask 的实现之一）。
    assert "EvaluationRequest" not in digest
    assert "get_store" not in digest


def test_digest_guest_has_no_asset_lines(six_cards):
    digest = capability_digest(None)
    assert "target-return-view-v1" in digest
    for asset_id in EXPECTED_IDS - {"target-return-view-v1"}:
        assert asset_id not in digest, f"游客摘要泄漏了资产卡 {asset_id}"


def test_digest_respects_configured_char_limit(six_cards):
    cfg = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
    max_chars = int(cfg.get("digest_max_chars") or DEFAULT_DIGEST_MAX_CHARS)
    assert len(capability_digest("model")) <= max_chars


def test_digest_truncates_with_marker_when_forced(six_cards):
    digest = capability_digest("model", max_chars=400)
    assert len(digest) <= 400
    assert "目录已截断" in digest
    assert "target-return-view-v1" in digest  # 首条（契约）卡优先保留


def test_digest_reuse_discipline_always_present(six_cards):
    for group in ("factor", None):
        digest = capability_digest(group)
        assert "覆盖不全先向人征询" in digest
        assert "不许直接跳自造方案" in digest


def test_append_capability_digest_never_raises_on_broken_config(tmp_path, monkeypatch):
    # 注入 seam 的 best-effort 契约：坏 yaml → 原样返回，不砸 run。
    (tmp_path / f"{CAPABILITIES_CONFIG}.yaml").write_text("cards: {not-a-list}", encoding="utf-8")
    from runner import config_loader

    monkeypatch.setenv("QUANTCODE_CONFIG_DIR", str(tmp_path))
    config_loader.load_yaml.cache_clear()
    try:
        assert append_capability_digest("BASE", group="factor") == "BASE"
    finally:
        config_loader.load_yaml.cache_clear()


def test_agent_engine_build_seam_appends_digest():
    """注入 seam 真实生效：AgentRunner.run 组装的 system_prompt 带常驻摘要。

    最小验证：append_capability_digest 在 run()/stream() 的指令组装点被调用
    （seam 位于 runner/agent_engine.py——build() 的拼装历史上有"拼而不发"的
    既成事实，故注入落在真正喂给 init_agent_state 的两处组装点之后）。
    """
    import inspect

    from runner import agent_engine

    run_src = inspect.getsource(agent_engine.AgentRunner.run)
    stream_src = inspect.getsource(agent_engine.AgentRunner.stream)
    assert "append_capability_digest" in run_src
    assert "append_capability_digest" in stream_src


# ---------------------------------------------------------------------------
# JSON Schema 一致性
# ---------------------------------------------------------------------------

def test_cards_validate_against_json_schema(six_cards):
    import jsonschema

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    for card in six_cards:
        jsonschema.validate(card.model_dump(), schema)


def test_json_schema_matches_pydantic_contract():
    """schema json 与 pydantic 契约同源：required 集合与 type 枚举一致。"""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    pyd_schema = CapabilityCard.model_json_schema()
    assert set(schema["required"]) == set(pyd_schema["required"])
    assert schema["properties"]["type"]["enum"] == ["asset", "contract"]
    assert schema["properties"]["owner_group"]["enum"] == list(pyd_schema["properties"]["owner_group"]["enum"])
    assert schema["additionalProperties"] is False
