# TDX user-sector API notes

Use project-local imports:

```python
from DataAPI.TdxAPI import CTdxAPI
from TdxLib.tqcenter import tq
```

Initialize:

```python
import os
from pathlib import Path

dll_path = os.getenv('TPYTHCLIENT_DLL', CTdxAPI._dll_path)
tq.initialize(path=str(Path(__file__).resolve()), dll_path=dll_path)
```

Close in `finally`:

```python
try:
    ...
finally:
    tq.close()
```

Functions:

```python
tq.create_sector(block_code='CCL', block_name='覆铜板CCL')
tq.clear_sector(block_code='CCL')
tq.send_user_block(block_code='CCL', stocks=['600183.SH'], show=False)
tq.get_user_sector()
tq.rename_sector(block_code='CCL', block_name='新名称')
tq.delete_sector(block_code='CCL')
```

Built-in watchlist:

```python
tq.send_user_block(block_code='ZXG', stocks=['600183.SH'], show=False)
```

Stock code suffixes:

- Shanghai: `600xxx.SH`, `601xxx.SH`, `603xxx.SH`, `605xxx.SH`, `688xxx.SH`
- Shenzhen: `000xxx.SZ`, `001xxx.SZ`, `002xxx.SZ`, `003xxx.SZ`, `300xxx.SZ`
- Beijing: `4xxxxx.BJ`, `8xxxxx.BJ`
