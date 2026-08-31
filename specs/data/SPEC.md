# SPEC — data 域：数据接入（P-01）

> §0 元信息：status=draft · owner=R3 数据回测代理 · source=P-01 · target=Q1 D1+D2-dev
> 上游依据：docs/audit/ROADMAP_LONGTERM.md §0（qs-cold 247 因子池勘察）、PRD §3.3"不造数据基建"。

## §1 范围与非目标

**范围**：只读接入 qs-cold 因子池 → 本地 staging dev 后端（COS 凭据解锁前的 dev 替身）→ FactorPanel/ReturnsDataset 契约对象 → Blackboard 共享。
**非目标**：不做行情写入/回测引擎（P-02/D3）、不做 qs-data 服务化（Q2 D2a）、不做权重计算（P-03/D4）。

## §2 契约

### 2.1 qs-cold 真实存储 schema（只读，实体勘察 2026-09-01）

parquet 长表 `factors/{factor_id}/year={Y}/data.parquet`，实测列（勘察快照 2026-09-01，位置=Server A `qs-data-ingest-hk-01:/srv/quant/data/migration-staging/20260814/hwudf/delivery_values_20260816/`，即 COS 桶 `qs-cold` 上传前 staging 副本）：`datetime`(datetime64, 交易日) / `asset`(string, A 股代码) / `value`(float32) / `calc_time`(timestamp, PIT 计算时刻) / `factor_version`(string) / `data_snapshot_id`(string) / `is_valid`(int64, 0=剔除) / `invalid_reason`(string)。单文件约 122 万行（因子×年）。
治理件（delivery_pool_all_maxcard/）：`selected_pool.csv`（247 行；列含 factor_name/family/factor_dir/factor_values_path/format/rank_ic_mean/abs_rank_ic/factor_direction/formula/code_hash）、`index.json`（算法 min_degree_greedy_tiebreak_abs_rank_ic、979 候选→247 入选、|corr|≤0.7、家族分布 lqtp_1014×158/abs_rankic×44/cogalpha×26/alphasage×17/quantalpha×2）、`admission_rule.json`、`screening_audit.csv`、`corr_matrix_selected.csv`。

### 2.2 Pydantic 契约 [新增 schemas/data_contracts.py + schemas/data-contracts.schema.json]

`FactorPanel`：`factor_id: str`、`factor_version: str`、`data_snapshot_id: str`、`dates: list[date]`、`assets: list[str]`、`values`（date×asset float32 矩阵）、`is_valid`（过滤标记）、`source_path: str`。
不变量：① `dates` 严格升序无重复；② `asset` 匹配 `^\d{6}\.(SH|SZ|BJ)$`；③ 载入剔除 `is_valid==0` 行，剔除数与 `invalid_reason` 分布记入 `meta.removed`；④ PIT：查询 as_of 仅保留 `calc_time <= as_of` 行；⑤ `_contract: FactorPanel/v1` 版本戳。
`ReturnsDataset`：`name: str`、`dates: list[date]`（严格升序无重复）、`returns: dict[asset, vec]`；NaN 白名单化、不允许 inf。注意：qs-cold 无收益表，首版用 backend 现有行情表（StockDailyBar.Return）——现有 schemas/factor.py 仅有 factor_version 字段，`calc_time/data_snapshot_id/invalid_reason` 的进 schema 属 [新增] 映射。

### 2.3 Blackboard key（PROJECT scope，`PROJECT_SESSION_ID`）

`shared.datasets.panel/{name}`、`shared.datasets.returns/{name}`——遵守 `runner/blackboard_keys.py` 的 `shared.` 归一（`make_read_key` 幂等）；值=契约对象+`_contract` 戳；LLM 只见 key+摘要。

### 2.4 四工具签名（[新增] tools/market/_register.py，风格对齐 tools/risk/_register.py）

- `list_factors(pool_filter: dict|None) -> list[dict]`（读 selected_pool.csv + index.json）
- `load_factor_panel(factor_id: str, year_start: int, year_end: int, as_of: datetime) -> dict`
- `load_returns(name: str, date_start: date, date_end: date) -> dict`
- `pool_browse(factor_id: str|None, family: str|None) -> dict`（只读池元数据）

## §3 数据流

```
qs-cold / staging-dev 后端（QS_DATA_BACKEND=staging 默认）
  → list_factors（因子清单+家族分布）
  → load_factor_panel(factor_id, as_of) → 剔 is_valid=0 + PIT 过滤
  → BlackboardEntry(PROJECT, shared.datasets.panel/{name}, _contract=FactorPanel/v1)
  → 下游工具按 key 读（回测 D3 / 组合 D4 就绪）
  → lens UI: panels.tsx Schema 卡片渲染 output_data 摘要
```

权限fail-closed：默认 backend=staging 不触网；未显式配置 COS 凭据时禁止网络。

## §4 机器可验证断言

- D1-A1: `FactorPanel(dates=[d, d])` 重复日期抛 ValidationError（[新增测试] tests/test_data_contracts.py::test_panel_rejects_duplicate_dates）
- D1-A2: dates 降序抛 ValidationError（同文件 test_panel_rejects_unsorted_dates）
- D1-A3: `asset="000001"`（缺后缀）抛 ValidationError；`"600519.SH"` 通过（test_panel_asset_format_a_share）
- D1-A4: `load_factor_panel(as_of=T)` 输出全满足 `calc_time <= T`（[新增测试] tests/test_market_tools.py::test_load_factor_panel_pit_filter）
- D1-A5: `is_valid==0` 行不出现在 values；`meta.removed` 计数与 fixture 一致（test_load_factor_panel_drops_invalid_rows）
- D1-A6: 默认 staging backend 四工具零网络（monkeypatch socket 即证）（test_staging_backend_network_fail_closed）
- D1-A7: 显式未知 backend 且无凭据抛 PermissionError|ValueError，绝不静默降级（test_unknown_backend_rejected）
- D1-A8: 返回值经 `FactorPanel.model_validate()` 通过且 `_contract=="FactorPanel/v1"`（[新增测试] tests/test_data_contracts.py::test_panel_output_matches_pydantic_contract）
- D1-A9: 写 `shared.datasets.panel/demo` 后 get_entry 读回同一契约对象（[新增测试] tests/test_blackboard_datasets.py::test_dataset_roundtrip_project_scope）
- D1-A10: 向 panel namespace 写入无 `_contract` 或版本不匹配的 dict，写入口抛 ValidationError（test_dataset_entry_version_stamp_enforced）

## §5 开放问题

- qs-cold 无 A 股收益表：ReturnsDataset 首版用 backend 现有行情表（owner: R3，截止 Q1 末）。
- staging 与 COS 的因子数据漂移监测（owner: R3，截止 D2a）。

## §6 verdict

| 断言 | 测试 | 结果 | 日期 |
|---|---|---|---|
| D1-A1..A3, A8 | tests/test_data_contracts.py | blocked | — |
| D1-A4..A7 | tests/test_market_tools.py | blocked | — |
| D1-A9..A10 | tests/test_blackboard_datasets.py | blocked | — |