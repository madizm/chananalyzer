# get_market_data

## Function signature

```python
get_market_data(
    field_list: List[str] = [],
    stock_list: List[str] = [],
    period: str = '',
    start_time: str = '',
    end_time: str = '',
    count: int = -1,
    dividend_type: Optional[str] = None,
    fill_data: bool = True
) -> Dict
```

## Parameters

| Parameter | Required | Type | Description |
|---|---|---|---|
| `field_list` | No | `List[str]` | Field filter. Empty means all fields. |
| `stock_list` | Yes | `List[str]` | Security code list. |
| `period` | Yes | `str` | K-line period. |
| `start_time` | No | `str` | Start time. |
| `end_time` | No | `str` | End time. |
| `count` | No | `int` | Number of records per stock. |
| `dividend_type` | No | `str` | Rights adjustment: `none`, `front`, `back`. |
| `fill_data` | No | `bool` | Whether to backfill missing data. |

Notes:
- If `count <= 0`, it returns all data between `start_time` and `end_time`.

## Return value

- Returns a dict: `{field_name: DataFrame}`.
- Each DataFrame uses stock list as index and time list as columns.
- All returned fields share the same shape and index.
- `ForwardFactor` is effective when `dividend_type='none'`.
- Back-adjusted results are calculated only within the returned data range.
- Maximum records per call are about 24000. Minute data should be fetched in batches.
- For futures, `Amount` is 0; for non-futures, `VolInStock` is 0.

## Common return fields

- `Date`
- `Time`
- `Open`
- `High`
- `Low`
- `Close`
- `Volume`
- `Amount`
- `ForwardFactor`
- `VolInStock`

## Example

```python
from tqcenter import tq

tq.initialize(__file__)

data = tq.get_market_data(
    field_list=[],
    stock_list=['688318.SH'],
    period='1d',
    start_time='20251220',
    end_time='',
    count=1,
    dividend_type='none',
    fill_data=True,
)

print(data)
```
