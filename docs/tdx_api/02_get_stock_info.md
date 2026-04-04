# get_stock_info

## Function signature

```python
get_stock_info(
    stock_code: str,
    field_list: List = []
) -> Dict
```

## Parameters

| Parameter | Required | Type | Description |
|---|---|---|---|
| `stock_code` | Yes | `str` | Security code. |
| `field_list` | Yes | `List[str]` | Field filter (doc states non-empty). |

## Return value

Returns security base info and financial base indicators.

Typical groups:

- Base attributes: `Name`, `Unit`, `VolBase`, `MinPrice`, `XsFlag`, `Fz`, `DelayMin`
- Flags: `BelongHS300`, `BelongRZRQ`, `BelongHSGT`, `IsHKGP`, `IsQH`, `IsQQ`, `IsSTGP`
- Financials: `ActiveCapital`, `J_zgb`, `J_zzc`, `J_ldzc`, `J_jzc`, `J_yysy`, `J_jly`, `J_mgsy`, `J_mgjzc`
- Industry/region: `tdx_dycode`, `tdx_dyname`, `rs_hycode_sim`, `rs_hyname`, `blockzscode`
- Others: `underly_setcode`, `underly_code`, `ErrorId`

## Example

```python
from tqcenter import tq

tq.initialize(__file__)

info = tq.get_stock_info(stock_code='688318.SH', field_list=[])
print(info)
```
