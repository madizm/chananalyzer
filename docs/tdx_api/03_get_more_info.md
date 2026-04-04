# get_more_info

## Function signature

```python
def get_more_info(
    stock_code: str = '',
    field_list: List = []
)
```

## Parameters

| Parameter | Required | Type | Description |
|---|---|---|---|
| `stock_code` | Yes | `str` | Stock code. |
| `field_list` | No | `List[str]` | Field filter. Empty means all fields. |

## Return value

Provides more detailed market extension, valuation, flow, and event fields.

Typical groups:

- Market extension: `ZTPrice`, `DTPrice`, `HqDate`, `fHSL`, `fLianB`, `Wtb`, `ZAF`
- Market cap/volume: `Zsz`, `Ltsz`, `vzangsu`, `Fzhsl`, `FzAmo`
- Fund flow/orders: `Zjl`, `Zjl_HB`, `TotalBVol`, `TotalSVol`, `BCancel`, `SCancel`
- Return windows: `ZAFPre5`, `ZAFPre10`, `ZAFPre20`, `ZAFPre30`, `ZAFPre60`, `ZAFYear`
- Valuation: `DynaPE`, `MorePE`, `StaticPE_TTM`, `DYRatio`, `PB_MRQ`, `BetaValue`
- Flags/events: `IsT0Fund`, `IsZCZGP`, `IsKzz`, `ReportDate`, `ZTDate_Recent`, `DTDate_Recent`

Tip:
- Use `FCAmo` to determine limit status:
  - `FCAmo > 0`: up-limit
  - `FCAmo < 0`: down-limit

## Example

```python
from tqcenter import tq

tq.initialize(__file__)

more_info = tq.get_more_info(stock_code='688318.SH', field_list=[])
print(more_info)
```
