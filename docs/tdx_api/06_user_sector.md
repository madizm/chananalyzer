# User sector / watchlist APIs

Source: https://help.tdx.com.cn/quant/docs/markdown/mindoc-1h139a4ckchkk/

通达信自选股/自定义板块相关接口。

## Create custom sector

```python
create_sector(block_code: str = '', block_name: str = '')
```

### Parameters

| Parameter | Required | Type | Description |
|---|---|---|---|
| `block_code` | Yes | `str` | 自定义板块简称 |
| `block_name` | Yes | `str` | 自定义板块名称 |

### Example

```python
from tqcenter import tq

tq.initialize(__file__)
create_ptr = tq.create_sector(block_code='CSBK2', block_name='测试板块2')
print(create_ptr)
```

### Sample response

```json
{
  "Error": "创建CSBK2板块成功",
  "ErrorId": "0",
  "run_id": "1"
}
```

## Delete custom sector

```python
delete_sector(block_code: str = '')
```

### Parameters

| Parameter | Required | Type | Description |
|---|---|---|---|
| `block_code` | Yes | `str` | 自定义板块简称 |

### Example

```python
from tqcenter import tq

tq.initialize(__file__)
delete_ptr = tq.delete_sector(block_code='CSBK')
print(delete_ptr)
```

### Sample response

```json
{
  "Error": "删除CSBK板块成功",
  "ErrorId": "0",
  "run_id": "1"
}
```

## Rename custom sector

```python
rename_sector(block_code: str = '', block_name: str = '')
```

### Parameters

| Parameter | Required | Type | Description |
|---|---|---|---|
| `block_code` | Yes | `str` | 自定义板块简称 |
| `block_name` | Yes | `str` | 重命名后的自定义板块名称 |

### Example

```python
from tqcenter import tq

tq.initialize(__file__)
rename_ptr = tq.rename_sector(block_code='CSBK', block_name='测试板块重命名')
print(rename_ptr)
```

### Sample response

```json
{
  "Error": "重命名CSBK板块成功",
  "ErrorId": "0",
  "run_id": "1"
}
```

## Clear custom sector constituents

```python
clear_sector(block_code: str = '')
```

### Parameters

| Parameter | Required | Type | Description |
|---|---|---|---|
| `block_code` | Yes | `str` | 自定义板块简称 |

### Example

```python
from tqcenter import tq

tq.initialize(__file__)
clear_ptr = tq.clear_sector(block_code='CSBK')
print(clear_ptr)
```

### Sample response

```json
{
  "Error": "清空CSBK板块成功",
  "ErrorId": "0",
  "run_id": "1"
}
```

## Add custom sector constituents

```python
send_user_block(
    block_code: str = '',
    stocks: List[str] = [],
    show: bool = False,
) -> Dict
```

### Parameters

| Parameter | Required | Type | Description |
|---|---|---|---|
| `block_code` | Yes | `str` | 自定义板块简称 |
| `stocks` | Yes | `List[str]` | 添加的自选股 |
| `show` | No | `bool` | 客户端是否切换至对应板块界面 |

Notes:

- `block_code` 为客户端已有的自定义板块简称，如果不存在则无效果；为空则添加到临时条件股。
- `block_code` 存在且传入空列表表示清空该板块所有股票；否则为添加新股票。
- 自选股的 `block_code` 为 `ZXG`。

### Example

```python
from tqcenter import tq

tq.initialize(__file__)
zxg_result = tq.send_user_block(
    block_code='CSBK',
    stocks=['600000.SH', '600004.SH', '000001.SZ', '000002.SZ'],
)
print(zxg_result)
```

### Sample response

```python
{'Error': 'Add User Block Completed', 'ErrorId': '0', 'run_id': '1'}
```

## Get custom sector list

```python
get_user_sector() -> List
```

获取自定义板块代码列表。

### Example

```python
from tqcenter import tq

tq.initialize(__file__)
user_list = tq.get_user_sector()
print(user_list)
print(len(user_list))
```

### Sample response

```python
[{'Code': 'CSBK', 'Name': '测试板块'}, {'Code': 'CSBK2', 'Name': '测试板块2'}]
```
