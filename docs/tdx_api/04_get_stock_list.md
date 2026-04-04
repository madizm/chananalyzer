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
from tqcenter import tq

tq.initialize(__file__)

stock_list = tq.get_stock_list('16')
print(stock_list)

stock_list2 = tq.get_stock_list('16', list_type=1)
print(stock_list2)
```
