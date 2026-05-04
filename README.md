# ChanAnalyzer - A股缠论分析系统

> 本项目基于 [Vespa314/chan.py](https://github.com/Vespa314/chan.py) 进行二次开发

**原项目链接**: https://github.com/Vespa314/chan.py | **本项目仓库**: https://github.com/164149043/chananalyzer

---

## 在线画图

启动本地在线图表服务：

```bash
python scripts/run_chart_server.py --host 127.0.0.1 --port 8000
```

浏览器打开：

```text
http://127.0.0.1:8000/chart?code=002112&lv=30m&begin=2026-03-10&end=2026-04-28
```

常用参数：`code` 股票代码，`lv` 支持 `day/week/5m/15m/30m/60m`，`begin/end` 日期，`data_src` 默认 `TDX`，`x_range` 默认展示根数。

---

## 使用通达信 TDX 数据源（TPythClient）

```python
from Chan import CChan
from Common.CEnum import DATA_SRC, KL_TYPE, AUTYPE

# 可选：自定义 DLL 路径（默认 D:\tdx_new\PYPlugins\TPythClient.dll）
# import os
# os.environ["TPYTHCLIENT_DLL"] = r"D:\tdx_new\PYPlugins\TPythClient.dll"

chan = CChan(
    code="000001",  # 也支持 000001.SZ / sh600000 / sz000001
    begin_time="2026-01-01",
    end_time="2026-04-04",
    data_src=DATA_SRC.TDX,
    lv_list=[KL_TYPE.K_DAY],
    autype=AUTYPE.QFQ,
)
```

说明：

- `DATA_SRC.TDX` 对应 `DataAPI/TdxAPI.py`。
- 依赖 `TdxLib/tqcenter.py` 与 `TPythClient.dll`。
- 当前支持级别：`K_DAY/K_WEEK/K_MON/K_5M/K_15M/K_30M/K_60M`。

---
