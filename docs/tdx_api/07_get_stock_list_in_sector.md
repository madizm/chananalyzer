# get_stock_list_in_sector

官方文档：

- https://help.tdx.com.cn/quant/docs/markdown/mindoc-1ctuhttn72svo/mindoc-1h10r92mchgug.html

## Function signature

```python
get_stock_list_in_sector(
    block_code: str,
    block_type: int = 0,
    list_type: int = 0
) -> List
```

## Parameters

| Parameter | Required | Type | Description |
|---|---|---|---|
| `block_code` | Yes | `str` | 板块代码或板块名称；当 `block_type=1` 时传自定义板块简称。 |
| `block_type` | No | `int` | `0`: 使用板块代码或名称；`1`: 使用自定义板块简称。 |
| `list_type` | No | `int` | `0`: 仅返回代码；`1`: 返回代码和名称。 |

## Notes

- 支持板块指数或客户端自定义板块。
- 不支持 `所有A股`、`所有ETF` 这类股票列表分类。
- 概念板块可先通过 `get_stock_list("12", list_type=1)` 获取板块代码，再逐个传给本接口。

## Example

```python
from TdxLib.tqcenter import tq

try:
    tq.initialize(__file__)
    stocks = tq.get_stock_list_in_sector("880506.SH", block_type=0, list_type=1)
    print(stocks)
finally:
    tq.close()
```

自定义板块示例：

```python
from TdxLib.tqcenter import tq

try:
    tq.initialize(__file__)
    stocks = tq.get_stock_list_in_sector("CSBK", block_type=1, list_type=1)
    print(stocks)
finally:
    tq.close()
```

## Local cache

本项目用以下脚本缓存概念板块及其成分股：

```powershell
python scripts/cache_tdx_concept_sectors.py
```

写入两张表：

```sql
CREATE TABLE IF NOT EXISTS tdx_concept_sectors (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    market TEXT NOT NULL DEFAULT '',
    source_market TEXT NOT NULL DEFAULT '12',
    raw_json TEXT,
    updated_at TIMESTAMP NOT NULL
);

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
```

其中 `stock_code` 保留 TDX 返回的完整代码（如 `000001.SZ`），`code` 去掉市场后缀
（如 `000001`），用于和 `stock_info.code` 对齐。
