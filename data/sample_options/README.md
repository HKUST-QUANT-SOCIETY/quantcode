# Options 样本数据（Day 1）

> **维护人**：刘炽（T3b）  
> **来源**：期权组 `DataStructure.md`（layer2 merged 表字段说明）  
> **生产路径（服务器）**：`/srv/quant/shared_data/options/merged/gc_options/{YYYY-MM-DD}.parquet`

## 本目录有什么

| 文件 | 说明 |
|------|------|
| `DataStructure.md` | 期权组提供的完整数据分层与 merged 字段文档（原文） |
| `gc_options_merged_sample.csv` | 按 **§6 Options 最终表** 关键列生成的 **mock 样本**（非真实行情） |

## 数据分层（摘要）

```
raw_data → decoded_data → cleaned_data → merged/
                                              ├── gc_futures/
                                              └── gc_options/   ← vol-surface / greeks 主要读这里
```

- 时间粒度：**1 分钟**（`datetime`）
- 期权筛选：`raw_symbol` 以 `OG` 开头，`underlying` 以 `GC` 开头
- options 表比 futures 多一组 `fut_*` 底层期货字段（见 `DataStructure.md` §6）

## `gc_options_merged_sample.csv` 列说明

样本 CSV 选取 vol-surface / greeks skill 最常用的列（完整列见 `DataStructure.md` §6）：

| 列 | 含义 |
|----|------|
| `datetime` | 分钟时间键 |
| `file_date` | 交易日 |
| `leaf_name` | 固定 `gc_options` |
| `instrument_id` | Databento 合约 ID |
| `symbol` | 标准期权符号 |
| `raw_symbol` | 原始符号（OG…） |
| `instrument_class` | `call` / `put` |
| `underlying` | 底层期货符号（GC…） |
| `expiration` | 期权到期 |
| `strike_price` | 行权价 |
| `bid_px`, `ask_px`, `mid_px` | 买卖价 / 中间价 |
| `close`, `volume` | 分钟 OHLCV 收盘价与量 |
| `spread_px` | 买卖价差 |
| `last_trade_price` | 最后一笔成交价 |
| `fut_symbol` | 底层期货符号（options 特有） |

## 给 `options:vol-surface` 的用法

1. 读 `gc_options_merged_sample.csv`（Day 1 mock）
2. 按 `file_date` + `underlying` 过滤
3. 用 `strike_price` × `expiration` × `instrument_class` 构链
4. Day 2 替换为真实 parquet：`merged/gc_options/{date}.parquet`

## 替换为真实数据

向期权组索取近期文件后：

```bash
# 示例：从 Server A 拷贝一日 merged 期权表（需 SSH 权限）
scp user@server:/srv/quant/shared_data/options/merged/gc_options/2026-06-27.parquet \
  data/sample_options/gc_options_2026-06-27.parquet
```

并在 README 标注 `data_quality=production`。

## 数据质量标记

当前样本：`data_quality=mock`（字段名与文档对齐，数值为示意，不可用于交易）
