# TDX Concept Sector Tables

本文档整理通达信概念板块相关缓存表设计。数据由
`scripts/cache_tdx_concept_sectors.py` 写入 `chan.db`。

## Data source

| Data | TDX interface | Parameters |
|---|---|---|
| 概念板块列表 | `tq.get_stock_list` | `market="12", list_type=1` |
| 概念板块成分股 | `tq.get_stock_list_in_sector` | `block_code=<sector_code>, block_type=0, list_type=1` |

刷新命令：

```powershell
python scripts/cache_tdx_concept_sectors.py
```

只刷新概念板块，不拉取成分股：

```powershell
python scripts/cache_tdx_concept_sectors.py --sectors-only
```

## Tables

### `tdx_concept_sectors`

保存概念板块本身，一行一个概念板块。

```sql
CREATE TABLE IF NOT EXISTS tdx_concept_sectors (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    market TEXT NOT NULL DEFAULT '',
    source_market TEXT NOT NULL DEFAULT '12',
    raw_json TEXT,
    updated_at TIMESTAMP NOT NULL
);
```

| Column | Type | Key | Description |
|---|---|---|---|
| `code` | `TEXT` | PK | 板块完整代码，例如 `880506.SH`。 |
| `name` | `TEXT` | | 板块名称，例如 `5G概念`。 |
| `market` | `TEXT` | | 板块市场后缀，例如 `SH`。 |
| `source_market` | `TEXT` | | TDX `get_stock_list` 分类代码；概念板块固定为 `12`。 |
| `raw_json` | `TEXT` | | TDX 原始返回行 JSON，便于追溯字段变化。 |
| `updated_at` | `TIMESTAMP` | | 本地更新时间。 |

### `tdx_concept_sector_stocks`

保存概念板块和成分股的多对多关系。一只股票可属于多个概念板块。

```sql
CREATE TABLE IF NOT EXISTS tdx_concept_sector_stocks (
    sector_code TEXT NOT NULL,
    code TEXT NOT NULL DEFAULT '',
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL DEFAULT '',
    market TEXT NOT NULL DEFAULT '',
    raw_json TEXT,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (sector_code, stock_code)
);

CREATE INDEX IF NOT EXISTS idx_tdx_concept_sector_stocks_stock
ON tdx_concept_sector_stocks (stock_code);

CREATE INDEX IF NOT EXISTS idx_tdx_concept_sector_stocks_code
ON tdx_concept_sector_stocks (code);
```

| Column | Type | Key | Description |
|---|---|---|---|
| `sector_code` | `TEXT` | PK | 所属概念板块完整代码，对应 `tdx_concept_sectors.code`。 |
| `code` | `TEXT` | Index | 去掉市场后缀的股票代码，例如 `000001`；用于对齐 `stock_info.code`。 |
| `stock_code` | `TEXT` | PK, Index | TDX 返回的完整股票代码，例如 `000001.SZ`。 |
| `stock_name` | `TEXT` | | TDX 返回的股票名称。 |
| `market` | `TEXT` | | 股票市场后缀，例如 `SZ`、`SH`。 |
| `raw_json` | `TEXT` | | TDX 原始返回行 JSON。 |
| `updated_at` | `TIMESTAMP` | | 本地更新时间。 |

`stock_code` 保留 TDX 原始完整代码，`code` 专门用于和项目已有 `stock_info.code`
对齐：

```sql
SELECT t.sector_code, t.code, t.stock_code, s.name
FROM tdx_concept_sector_stocks t
LEFT JOIN stock_info s ON s.code = t.code;
```

## Refresh behavior

默认刷新是全量替换：

1. 拉取 `market="12"` 的概念板块列表。
2. 逐个调用 `get_stock_list_in_sector` 拉取成分股。
3. 删除旧的 `tdx_concept_sector_stocks` 和 `tdx_concept_sectors` 数据。
4. 写入新数据。

使用 `--append` 时不清空旧数据，改为按主键 `INSERT OR REPLACE`。

## Current snapshot

截至最近一次本地刷新：

| Metric | Count |
|---|---:|
| 概念板块 | 269 |
| 板块-成分股关系 | 45679 |
| 去重股票数 | 5393 |
| 可匹配 `stock_info.code` 的去重股票数 | 5091 |

成分股最多的概念板块示例：

| Sector code | Name | Stock count |
|---|---|---:|
| `880904.SH` | 机器人概念 | 1170 |
| `880948.SH` | 人工智能 | 1049 |
| `880951.SH` | 新能源车 | 1038 |
| `880730.SH` | 储能 | 875 |
| `880952.SH` | 芯片 | 874 |

## Common queries

查询某个概念板块的成分股：

```sql
SELECT t.code, t.stock_code, COALESCE(s.name, t.stock_name) AS name
FROM tdx_concept_sector_stocks t
LEFT JOIN stock_info s ON s.code = t.code
WHERE t.sector_code = '880506.SH'
ORDER BY t.code;
```

查询某只股票所属概念：

```sql
SELECT s.code AS sector_code, s.name AS sector_name
FROM tdx_concept_sector_stocks t
JOIN tdx_concept_sectors s ON s.code = t.sector_code
WHERE t.code = '000001'
ORDER BY s.code;
```

按成分股数量统计概念板块：

```sql
SELECT s.code, s.name, COUNT(t.code) AS stock_count
FROM tdx_concept_sectors s
LEFT JOIN tdx_concept_sector_stocks t ON t.sector_code = s.code
GROUP BY s.code, s.name
ORDER BY stock_count DESC, s.code;
```

查询股票基础信息并附带概念数量：

```sql
SELECT si.code, si.name, si.industry, COUNT(t.sector_code) AS concept_count
FROM stock_info si
LEFT JOIN tdx_concept_sector_stocks t ON t.code = si.code
GROUP BY si.code, si.name, si.industry
ORDER BY concept_count DESC, si.code;
```
