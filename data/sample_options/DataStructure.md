# `layer2` 数据说明

这份文档主要说明 `/srv/quant/shared_data/options` 下面的数据分层、`cleaned_data` 的生成方式，以及最终 `merged` 表中 futures 和 options 字段的来源与含义。

## 1. 目录结构

下面是 `/srv/quant/shared_data/options` 的文件夹架构。这里只列文件夹，不展开具体文件；原始层里重复出现的大量 job 目录统一用 `<job_id>/` 表示。

```text
/srv/quant/shared_data/options/
├── raw_data/
│   ├── definition/
│   │   └── glbx_mdp3/
│   │       ├── gc_futures/
│   │       │   └── <job_id>/
│   │       └── gc_options/
│   │           ├── _checkpoints/
│   │           └── <job_id>/
│   ├── ohlcv-1m/
│   │   └── glbx_mdp3/
│   │       ├── gc_futures/
│   │       │   ├── _checkpoints/
│   │       │   └── <job_id>/
│   │       └── gc_options/
│   │           ├── _checkpoints/
│   │           └── <job_id>/
│   ├── tbbo/
│   │   └── glbx_mdp3/
│   │       ├── gc_futures/
│   │       │   ├── _checkpoints/
│   │       │   └── <job_id>/
│   │       └── gc_options/
│   │           ├── _checkpoints/
│   │           └── <job_id>/
│   └── statistics/
│       └── glbx_mdp3/
│           └── gc_futures/
│               └── _checkpoints/
├── decoded_data/
│   ├── definition/
│   └── daily/
│       ├── gc_futures/
│       │   ├── definition/
│       │   ├── ohlcv-1m/
│       │   └── tbbo/
│       └── gc_options/
│           ├── definition/
│           ├── ohlcv-1m/
│           └── tbbo/
├── cleaned_data/
│   ├── definition_merge_report/
│   ├── gc_futures/
│   │   ├── definition/
│   │   ├── ohlcv-1m/
│   │   ├── ohlcv_1m_aligned/
│   │   ├── tbbo_1m/
│   │   └── tbbo_1m_aligned/
│   └── gc_options/
│       ├── definition/
│       ├── ohlcv-1m/
│       ├── ohlcv_1m_aligned/
│       ├── tbbo_1m/
│       └── tbbo_1m_aligned/
└── merged/
    ├── definitions/
    ├── gc_futures/
    └── gc_options/
```

## 2. 各层的作用

| 层级 | 作用 | 粒度 | 说明 |
| --- | --- | --- | --- |
| `raw_data` | 保存 Databento 原始批量下载结果 | job 目录级 | 保留原始下载目录、sidecar 文件、checkpoint |
| `decoded_data/daily` | 稳定的日级解码层 | leaf/schema/date | 不再依赖 job id，而是按品种和日期组织 |
| `cleaned_data` | 下游直接使用的清洗层 | leaf/type/date | 保留 `definition`、保留 `ohlcv-1m`、把原始 `tbbo` 聚合成 `tbbo_1m`，再生成按分钟对齐后的 `_aligned` 数据 |
| `merged` | 最终研究用合并表 | leaf/date | 把分钟行情与 definition 快照合并到同一张表 |

## 3. `cleaned_data` 是怎么生成的

`cleaned_data` 是最终 `merged` 之前的最后一层标准化数据。

### 3.1 黄金筛选后的 `definition`

- 来源：`decoded_data/daily/{gc_futures|gc_options}/definition/{YYYY-MM-DD}.parquet`
- 生成方式：先按黄金相关规则筛选，再写到 `cleaned_data/{gc_futures|gc_options}/definition/`
- 含义：每个交易日一份“黄金相关标的”的 definition 快照

当前采用的黄金筛选规则如下。

| leaf | definition 筛选规则 |
| --- | --- |
| `gc_options` | `raw_symbol` 以 `OG` 开头，且 `underlying` 以 `GC` 开头 |
| `gc_futures` | `asset == 'GC'`，或 `raw_symbol` / `symbol` / `underlying` 以 `GC` 开头 |

`cleaned_data` 下的分钟行情文件也按上述筛选后的 `instrument_id` 白名单过滤，只保留黄金相关 futures 和 options。

### 3.2 `ohlcv-1m`

- 来源：`decoded_data/daily/{gc_futures|gc_options}/ohlcv-1m/{YYYY-MM-DD}.parquet`
- 生成方式：按筛选后的 `instrument_id` 白名单过滤后，写到 `cleaned_data/{gc_futures|gc_options}/ohlcv-1m/`
- 含义：Databento 原生 1 分钟 OHLCV 数据，原始时间列为 `ts_event`

### 3.3 `tbbo_1m`

- 来源：`decoded_data/daily/{gc_futures|gc_options}/tbbo/{YYYY-MM-DD}.parquet`
- 生成方式：先把原始 `tbbo` 聚合到 1 分钟，再按筛选后的 `instrument_id` 白名单写到 `cleaned_data/{gc_futures|gc_options}/tbbo_1m/`
- 聚合键：`instrument_id + floor(ts_event, 'minute')`

`tbbo_1m` 目前是同一套逻辑同时对 `gc_futures` 和 `gc_options` 生成，不再只针对期权。

关键聚合规则如下：

| 输出列 | 聚合方式 |
| --- | --- |
| `bid_px_close`, `ask_px_close` | 该分钟最后一笔买一/卖一报价 |
| `bid_sz_last`, `ask_sz_last` | 该分钟最后一笔买一/卖一尺寸 |
| `bid_ct_last`, `ask_ct_last` | 该分钟最后一笔买一/卖一档位数量 |
| `mid_px_close`, `spread_px_close` | 该分钟最后一个 mid/spread |
| `trade_count` | 该分钟内成交笔数 |
| `trade_price_close` | 该分钟最后一笔成交价 |
| `trade_size_sum` | 该分钟成交量合计 |
| `trade_notional_sum` | 该分钟成交额合计 |

注意：原始 `tbbo` 不再复制到 `cleaned_data`，这里只保留 `tbbo_1m`。

### 3.4 `_aligned` 分钟对齐层

为了让下游 merge 和 IV 研究直接在统一分钟网格上读数，当前在 `cleaned_data` 下额外保留两类对齐后的目录：

- `cleaned_data/{leaf}/ohlcv_1m_aligned/{YYYY-MM-DD}.parquet`
- `cleaned_data/{leaf}/tbbo_1m_aligned/{YYYY-MM-DD}.parquet`

对齐逻辑同时应用于 `gc_futures` 和 `gc_options`，并且对 `ohlcv-1m` 与 `tbbo_1m` 都执行。

对齐方法如下：

1. 以单日、单 `leaf` 为单位处理。
2. 先收集该日 `ohlcv-1m` 与 `tbbo_1m` 的全部分钟键，取并集作为统一的 `datetime` 网格。
3. 再按 `instrument_id` 分组，把每个标的扩展到完整分钟网格。
4. 价格类字段采用前向填充，尽量保持分钟序列连续。
5. 成交量、成交笔数、成交额等流量型字段缺失时填 `0`。
6. 原始静态字段如 `symbol`、`publisher_id`、`leaf_name`、`file_date`、`source_schema` 等随标的保留。

常用填充口径可以概括为：

| 字段类别 | 代表字段 | 对齐填充方法 |
| --- | --- | --- |
| OHLC 价格 | `open`, `high`, `low`, `close` | 前向填充 |
| 报价价格 | `bid_px_close`, `ask_px_close`, `mid_px_close`, `spread_px_close` | 前向填充 |
| 报价尺寸/档位 | `bid_sz_last`, `ask_sz_last`, `bid_ct_last`, `ask_ct_last` | 前向填充 |
| 成交流量 | `volume`, `trade_count`, `trade_size_sum`, `trade_notional_sum`, `buy_aggressor_count`, `sell_aggressor_count`, `unknown_aggressor_count` | 缺失填 `0` |
| 时间戳/序列号 | `ts_event_first`, `ts_event_last`, `ts_recv_first`, `ts_recv_last`, `sequence_first`, `sequence_last` | 保留原值，缺失保持空 |

保留 `_aligned` 目录的原因是：

- 不覆盖原始清洗层，便于回溯和重新处理。
- 给 merge 和研究 notebook 提供统一分钟粒度输入。
- 避免在下游重复做分钟补齐。

## 4. 最终 `merged` 表的合并逻辑

最终输出文件位置：

- `/srv/quant/shared_data/options/merged/gc_futures/{YYYY-MM-DD}.parquet`
- `/srv/quant/shared_data/options/merged/gc_options/{YYYY-MM-DD}.parquet`

### 4.1 三个合并源

| 数据源 | 输入路径 | 时间粒度 | 在合并中的用途 |
| --- | --- | --- | --- |
| `ohlcv_1m_aligned` | `cleaned_data/{leaf}/ohlcv_1m_aligned/` | 1 分钟 | 时间键已经统一成 `datetime`，提供补齐后的 `open/high/low/close/volume` |
| `tbbo_1m_aligned` | `cleaned_data/{leaf}/tbbo_1m_aligned/` | 1 分钟 | 时间键已经统一成 `datetime`，提供补齐后的 bid/ask/size/spread/trade 汇总列 |
| `definition` | `cleaned_data/{leaf}/definition/` | 按日更新 | 先拼成长表，再为每个交易日构造“截至当日最新”的 definition 快照 |

### 4.2 合并步骤

1. 把所有日级 `definition` 文件拼成一张长表。
2. 对每个交易日，构造一张“截至当日最新 definition”的快照表。
3. 如果是 `gc_options`，再用 `underlying_id -> gc_futures.instrument_id` 把底层期货 definition 补进去。
4. 从 `ohlcv_1m_aligned` 和 `tbbo_1m_aligned` 读取分钟行情，并按 `instrument_id + datetime` 做 `outer join`。
5. 再把当天的 definition 快照按 `instrument_id` 左连接进去。
6. 每个 leaf、每个交易日写出一份 merged parquet。

## 5. Futures 最终表字段说明

当前 futures merged 文件包含以下列。

| 字段 | 来源 | 含义 |
| --- | --- | --- |
| `datetime` | `ohlcv_1m_aligned.datetime` 或 `tbbo_1m_aligned.datetime` | 最终行的分钟时间键 |
| `file_date` | merge 过程生成 | 输出文件所属交易日 |
| `leaf_name` | merge 过程生成 | 业务叶子节点，这里固定为 `gc_futures` |
| `instrument_id` | 三个源表共同键 | Databento 的合约唯一标识 |
| `symbol` | 优先用市场数据，缺失时回退到 definition | 合约标准符号 |
| `raw_symbol` | definition | Databento 原始符号 |
| `instrument_class` | definition | 合约类别，例如 futures、spread |
| `asset` | definition | 资产家族代码 |
| `exchange` | definition | 交易所代码 |
| `security_type` | definition | 证券类型 |
| `currency` | definition | 交易货币 |
| `settl_currency` | definition | 结算货币 |
| `underlying` | definition | 如果有的话，对应底层符号文本 |
| `underlying_id` | definition | 如果有的话，对应底层 instrument id |
| `expiration` | definition | 到期时间 |
| `strike_price` | definition | 行权价，futures 基本为空 |
| `strike_price_currency` | definition | 行权价货币，futures 基本为空 |
| `contract_multiplier` | definition | 合约乘数 |
| `min_price_increment` | definition | 最小报价单位 |
| `unit_of_measure` | definition | 交易单位 |
| `cfi` | definition | 产品分类码 |
| `md_security_trading_status` | definition | 交易状态码 |
| `definition_date` | definition 快照 | 本行使用的 definition 更新日期 |
| `open` | `ohlcv_1m_aligned` | 对齐后 1 分钟开盘价 |
| `high` | `ohlcv_1m_aligned` | 对齐后 1 分钟最高价 |
| `low` | `ohlcv_1m_aligned` | 对齐后 1 分钟最低价 |
| `close` | `ohlcv_1m_aligned` | 对齐后 1 分钟收盘价 |
| `volume` | `ohlcv_1m_aligned` | 对齐后 1 分钟成交量，缺失分钟补 `0` |
| `bid_px` | `tbbo_1m_aligned.bid_px_close` | 对齐后该分钟最后一个买一价 |
| `ask_px` | `tbbo_1m_aligned.ask_px_close` | 对齐后该分钟最后一个卖一价 |
| `bid_sz` | `tbbo_1m_aligned.bid_sz_last` | 对齐后该分钟最后一个买一量 |
| `ask_sz` | `tbbo_1m_aligned.ask_sz_last` | 对齐后该分钟最后一个卖一量 |
| `bid_ct` | `tbbo_1m_aligned.bid_ct_last` | 对齐后该分钟最后一个买一档位计数 |
| `ask_ct` | `tbbo_1m_aligned.ask_ct_last` | 对齐后该分钟最后一个卖一档位计数 |
| `mid_px` | `tbbo_1m_aligned.mid_px_close` | 对齐后该分钟最后一个中间价 |
| `spread_px` | `tbbo_1m_aligned.spread_px_close` | 对齐后该分钟最后一个买卖价差 |
| `trade_count` | `tbbo_1m_aligned` | 对齐后该分钟成交笔数，缺失分钟补 `0` |
| `last_trade_price` | `tbbo_1m_aligned.trade_price_close` | 对齐后该分钟最后一笔成交价 |
| `last_trade_size_sum` | `tbbo_1m_aligned.trade_size_sum` | 对齐后该分钟成交量合计，缺失分钟补 `0` |
| `trade_notional_sum` | `tbbo_1m_aligned.trade_notional_sum` | 对齐后该分钟成交额合计，缺失分钟补 `0` |
| `publisher_id` | 市场数据 | Databento publisher id |
| `definition_file` | definition 快照 | 本行对应 definition 来自哪一天的原始快照文件 |

## 6. Options 最终表字段说明

options merged 文件包含上面 futures 的公共字段，另外多出一组“底层期货补充字段”。

| 字段 | 来源 | 含义 |
| --- | --- | --- |
| `datetime` | `ohlcv_1m_aligned.datetime` 或 `tbbo_1m_aligned.datetime` | 最终行的分钟时间键 |
| `file_date` | merge 过程生成 | 输出文件所属交易日 |
| `leaf_name` | merge 过程生成 | 业务叶子节点，这里固定为 `gc_options` |
| `instrument_id` | 三个源表共同键 | Databento 的期权 instrument id |
| `symbol` | 优先用市场数据，缺失时回退到 definition | 期权标准符号 |
| `raw_symbol` | definition | Databento 原始期权符号 |
| `instrument_class` | definition | 期权类别，通常是 call/put |
| `asset` | definition | 期权产品资产家族 |
| `exchange` | definition | 交易所代码 |
| `security_type` | definition | 证券类型 |
| `currency` | definition | 交易货币 |
| `settl_currency` | definition | 结算货币 |
| `underlying` | definition | 底层期货符号文本 |
| `underlying_id` | definition | 底层期货 instrument id |
| `expiration` | definition | 期权到期时间 |
| `strike_price` | definition | 行权价 |
| `strike_price_currency` | definition | 行权价货币 |
| `contract_multiplier` | definition | 期权合约乘数 |
| `min_price_increment` | definition | 期权最小报价单位 |
| `unit_of_measure` | definition | 交易单位 |
| `cfi` | definition | 期权分类码 |
| `md_security_trading_status` | definition | 交易状态码 |
| `definition_date` | definition 快照 | 本行使用的 option definition 更新日期 |
| `fut_instrument_id` | futures definition 快照补充 | 底层期货的 instrument id |
| `fut_symbol` | futures definition 快照补充 | 底层期货符号 |
| `fut_raw_symbol` | futures definition 快照补充 | 底层期货原始符号 |
| `fut_expiration` | futures definition 快照补充 | 底层期货到期时间 |
| `fut_contract_multiplier` | futures definition 快照补充 | 底层期货合约乘数 |
| `fut_min_price_increment` | futures definition 快照补充 | 底层期货最小报价单位 |
| `fut_asset` | futures definition 快照补充 | 底层期货资产家族 |
| `fut_exchange` | futures definition 快照补充 | 底层期货交易所 |
| `open` | `ohlcv_1m_aligned` | 对齐后 1 分钟开盘价 |
| `high` | `ohlcv_1m_aligned` | 对齐后 1 分钟最高价 |
| `low` | `ohlcv_1m_aligned` | 对齐后 1 分钟最低价 |
| `close` | `ohlcv_1m_aligned` | 对齐后 1 分钟收盘价 |
| `volume` | `ohlcv_1m_aligned` | 对齐后 1 分钟成交量，缺失分钟补 `0` |
| `bid_px` | `tbbo_1m_aligned.bid_px_close` | 对齐后该分钟最后一个买一价 |
| `ask_px` | `tbbo_1m_aligned.ask_px_close` | 对齐后该分钟最后一个卖一价 |
| `bid_sz` | `tbbo_1m_aligned.bid_sz_last` | 对齐后该分钟最后一个买一量 |
| `ask_sz` | `tbbo_1m_aligned.ask_sz_last` | 对齐后该分钟最后一个卖一量 |
| `bid_ct` | `tbbo_1m_aligned.bid_ct_last` | 对齐后该分钟最后一个买一档位计数 |
| `ask_ct` | `tbbo_1m_aligned.ask_ct_last` | 对齐后该分钟最后一个卖一档位计数 |
| `mid_px` | `tbbo_1m_aligned.mid_px_close` | 对齐后该分钟最后一个中间价 |
| `spread_px` | `tbbo_1m_aligned.spread_px_close` | 对齐后该分钟最后一个买卖价差 |
| `trade_count` | `tbbo_1m_aligned` | 对齐后该分钟成交笔数，缺失分钟补 `0` |
| `last_trade_price` | `tbbo_1m_aligned.trade_price_close` | 对齐后该分钟最后一笔成交价 |
| `last_trade_size_sum` | `tbbo_1m_aligned.trade_size_sum` | 对齐后该分钟成交量合计，缺失分钟补 `0` |
| `trade_notional_sum` | `tbbo_1m_aligned.trade_notional_sum` | 对齐后该分钟成交额合计，缺失分钟补 `0` |
| `publisher_id` | 市场数据 | Databento publisher id |
| `definition_file` | definition 快照 | 本行对应的 option definition 原始快照文件 |

## 7. 其他说明

- `merged/definitions/*_definition_long.parquet` 保存的是全量拼接后的 definition 历史长表。
- `merged/definitions/*_definition_latest.parquet` 保存的是 merge 流程构造出的最新非空 definition 快照。
- `cleaned_data/definition_merge_report/` 是之前做 definition 检查时生成的辅助报告。
- `statistics` 目前只保存在原始归档层，没有进入本文描述的最终 merged 表。
- 当前 layer2 notebook 默认从 `_aligned` 目录读取分钟行情，因此 merge 输出已经基于“分钟补齐后的 futures/options 行情”。