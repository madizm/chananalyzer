# get_stock_list

## Function signature

```python
get_stock_list(
    market=None,
    list_type: int = 0
) -> List
```

## Parameters

| Parameter | Required | Type | Description |
|---|---|---|---|
| `market` | Yes | `str` | Category or market selector code. |
| `list_type` | Yes | `int` | Return format: `0` codes only, `1` code and name. |

## `market` values

- `0`: watchlist
- `1`: positions
- `5`: all A shares
- `6`: SSE index constituents
- `7`: SSE main board
- `8`: SZSE main board
- `9`: key indexes
- `10`: all sector indexes
- `11`: default industry sectors
- `12`: concept sectors
- `13`: style sectors
- `14`: regional sectors
- `15`: default industry + concept sectors
- `16`: research industry level 1
- `17`: research industry level 2
- `18`: research industry level 3
- `21`: includes H shares
- `22`: includes convertibles
- `23`: CSI 300
- `24`: CSI 500
- `25`: CSI 1000
- `26`: CNI 2000
- `27`: CSI 2000
- `28`: CSI A500
- `30`: REITs
- `31`: ETF
- `32`: convertibles
- `33`: LOF
- `34`: all tradable funds
- `35`: all SH/SZ funds
- `36`: T+0 funds
- `49`: financial enterprises
- `50`: SH/SZ A shares
- `51`: ChiNext
- `52`: STAR market
- `53`: Beijing exchange
- `91`: ETF-tracked indexes
- `92`: domestic futures main contracts
- `101`: domestic futures
- `102`: Hong Kong stocks
- `103`: US stocks

## Example

```python
from TdxLib.tqcenter import tq

tq.initialize(__file__)

stock_list = tq.get_stock_list('16')
print(stock_list)

stock_list2 = tq.get_stock_list('16', list_type=1)
print(stock_list2)
```

## Concept sectors

`market='12'` 返回概念板块列表：

```python
from TdxLib.tqcenter import tq

try:
    tq.initialize(__file__)
    concept_sectors = tq.get_stock_list("12", list_type=1)
    print(concept_sectors)
finally:
    tq.close()
```

本项目提供入库脚本，会保存到 `chan.db` 的 `tdx_concept_sectors` 表：

```powershell
python scripts/cache_tdx_concept_sectors.py
```

默认还会调用 `get_stock_list_in_sector` 保存每个概念板块的成分股关系到
`tdx_concept_sector_stocks` 表。只想刷新概念板块本身时使用：

```powershell
python scripts/cache_tdx_concept_sectors.py --sectors-only
```

如 `TPythClient.dll` 不在默认位置：

```powershell
python scripts/cache_tdx_concept_sectors.py --dll-path D:\tdx_new\PYPlugins\TPythClient.dll
```

表结构：

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
