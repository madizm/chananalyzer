# TDX Interface Documents

This folder contains organized markdown documents generated from the following TDX docs pages:

- `get_market_data`
- `get_stock_info`
- `get_more_info`
- `get_stock_list`
- `get_stock_list_in_sector`
- `什么是量化交易`（回测及模拟交易）

## Local Wrapper Usage

本项目通过 [TdxLib/tqcenter.py](../../TdxLib/tqcenter.py) 中的 `tq` 类调用通达信 `TPythClient.dll`。

### 运行前提

- 先启动并登录通达信客户端。
- 确保 Python 进程能加载 `TPythClient.dll`。`TdxLib` 默认按以下顺序查找：
  1. `tq.initialize(..., dll_path=...)` 传入的显式路径。
  2. 环境变量 `TPYTHCLIENT_DLL`。
  3. `D:\tdx_new\PYPlugins\TPythClient.dll`。
  4. 项目根目录下的 `TPythClient.dll`。
- 股票代码使用标准格式：`6位代码.市场后缀`，例如 `688318.SH`、`000001.SZ`。
- 时间参数使用 `YYYYMMDD` 或 `YYYYMMDDHHMMSS`。

### 基本调用模板

```python
from pathlib import Path

from TdxLib.tqcenter import tq

try:
    tq.initialize(str(Path(__file__).resolve()))
    data = tq.get_market_data(
        stock_list=["688318.SH"],
        period="1d",
        count=5,
        dividend_type="none",
        field_list=["Open", "High", "Low", "Close"],
    )
    print(data["Close"].tail())
finally:
    tq.close()
```

如果脚本不在项目根目录执行，需要先把项目根目录加入 `sys.path`。可参考 [tdxdata_test.py](./tdxdata_test.py)。

### 示例脚本

```powershell
python docs/tdx_api/tdxdata_test.py kline --code 688318.SH --count 5
python docs/tdx_api/tdxdata_test.py more --code 880544.SH --fields ZTGPNum
python docs/tdx_api/tdxdata_test.py stock-info --code 688318.SH
python docs/tdx_api/tdxdata_test.py stock-list --market 31 --list-type 1
python docs/tdx_api/tdxdata_test.py sector-stocks --block 880081.SH
```

如 DLL 不在默认位置：

```powershell
python docs/tdx_api/tdxdata_test.py --dll-path D:\tdx_new\PYPlugins\TPythClient.dll kline
```

### 常用接口摘要

- `tq.initialize(path, dll_path="")`: 初始化连接。所有接口调用前必须先执行。
- `tq.close()`: 断开连接。建议放在 `finally` 中。
- `tq.get_market_data(...)`: 获取 K 线，返回 `{字段名: DataFrame}`；DataFrame 的 index 是时间，columns 是股票代码。
- `tq.get_more_info(stock_code, field_list=[])`: 获取涨跌停、资金流、估值、事件等扩展字段。
- `tq.get_stock_info(stock_code, field_list=[])`: 获取基础证券信息和基础财务字段。
- `tq.get_stock_list(market="5", list_type=0)`: 获取股票/基金/板块等列表。
- `tq.get_sector_list(list_type=0)`: 获取板块列表。
- `tq.get_stock_list_in_sector(block_code, block_type=0, list_type=0)`: 获取板块成分股。
- `tq.refresh_cache(force=False, market="AG")`: 刷新行情缓存。
- `tq.refresh_kline(stock_list, period)`: 缓存历史 K 线，目前主要用于 `1m`、`5m`、`1d`。

### 参数要点

- `get_market_data.period`: 常用值包括 `1m`、`5m`、`15m`、`30m`、`1h`、`1d`、`1w`、`1mon`。
- `get_market_data.dividend_type`: `none` 不复权，`front` 前复权，`back` 后复权。
- `get_market_data.count > 0` 时按 `end_time` 向前取指定数量；未传 `end_time` 时使用当前时间。
- `field_list=[]` 表示返回全部字段；传入字段名列表则只返回匹配字段。
- 大部分接口异常时会返回 `{}` 或 `[]`，参数格式错误通常会抛出 `ValueError`。

## File list

- `docs/tdx_api/01_get_market_data.md`
- `docs/tdx_api/02_get_stock_info.md`
- `docs/tdx_api/03_get_more_info.md`
- `docs/tdx_api/04_get_stock_list.md`
- `docs/tdx_api/05_what_is_quant_trading.md`
- `docs/tdx_api/06_user_sector.md`
- `docs/tdx_api/07_get_stock_list_in_sector.md`
- `docs/tdx_api/08_concept_sector_schema.md`

## Sources

- https://help.tdx.com.cn/quant/docs/markdown/mindoc-1ctuhthaq5qmg/mindoc-1h10g60jt68sc.html
- https://help.tdx.com.cn/quant/docs/markdown/mindoc-1ctuhthaq5qmg/mindoc-1h10jj7r7jol4.html
- https://help.tdx.com.cn/quant/docs/markdown/mindoc-1ctuhthaq5qmg/mindoc-1h3rtq1hij0ac.html
- https://help.tdx.com.cn/quant/docs/markdown/mindoc-1ctuhttn72svo/mindoc-1h10qo3uj48fg.html
- https://help.tdx.com.cn/quant/docs/markdown/mindoc-1h12t4q6fg29o.html
- https://help.tdx.com.cn/quant/docs/markdown/mindoc-1h139a4ckchkk/
- https://help.tdx.com.cn/quant/docs/markdown/mindoc-1ctuhttn72svo/mindoc-1h10r92mchgug.html
