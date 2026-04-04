# 什么是量化交易

来源：
- https://help.tdx.com.cn/quant/docs/markdown/mindoc-1h12t4q6fg29o.html

## 概念

量化交易是利用计算机技术和数学模型，把投资理念转成可执行策略并持续验证优化的过程。核心链路：

`投资想法 -> 可执行策略 -> 代码程序 -> 回测/模拟验证 -> 实盘迭代`

## 五个步骤

## Step 1 从投资想法出发

先提出一个可能有效的交易想法，例如：

- 金叉买入
- 死叉卖出

## Step 2 细化为可执行策略

把模糊想法变成可度量、可计算、可复现的规则，至少明确：

- `Security`：交易标的范围
- `Condition`：触发买卖条件
- `Quantity`：买卖数量或金额

示例（文档思路）：

- 监测某个股票池（如沪深300成分）
- 收盘价上穿 MA5 买入
- MA5 上穿收盘价卖出

判定标准：不同人依据策略描述，在相同情景下应得到一致操作。

## Step 3 写成可执行代码

将策略翻译为程序，基于历史/实时数据生成交易信号并执行。文档给出的是一个 `tq.get_market_data + vectorbt` 的回测示例，典型流程：

- 获取行情（收盘/开盘）
- 计算指标（如 MA）
- 生成并对齐信号（常见做法是信号后移一根）
- 运行组合回测并输出统计结果

## Step 4 回测与模拟交易验证

- 回测：用历史数据模拟执行策略
- 模拟交易：用未来真实行情做仿真执行

核心区别：

- 回测检验“历史有效性”
- 模拟检验“实时执行稳定性”

两者都通过后再考虑进入实盘。

## Step 5 实盘并持续优化

实盘使用真实资金自动执行，需持续监控策略表现并根据市场变化调整参数与逻辑。

## 文档中的实践提示

- 先保证规则明确，再谈收益优化
- 回测结果不佳时先定位原因再改策略
- 回测良好并不等于实盘可用，需经过模拟交易阶段
- 实盘是持续迭代过程，不是一次性完成

## 与本仓库的对应关系（建议）

- 行情拉取：`tq.get_market_data`（已在 TDX 适配中使用）
- 全量标的：`tq.get_stock_list`
- 基本面字段：`tq.get_stock_info` / `tq.get_more_info`
- 批量缓存入口：`scripts/cache_all_stocks.py`、`scripts/cache_stock_info.py`

## 示例代码（vectorbt）

下面给出一个可直接参考的 MA 交叉回测示例（与官方页面思路一致）。

```python
import pandas as pd
import vectorbt as vbt

from TdxLib.tqcenter import tq


def main():
    tq.initialize(__file__)

    stock_code_list = ["688318.SH"]
    target_start = "20240930"
    target_end = "20250930"
    window = 5

    # 为 MA 预留足够历史窗口
    start_time = (
        pd.to_datetime(target_start) - pd.Timedelta(days=window + 10)
    ).strftime("%Y%m%d")

    # 1) 获取行情
    market = tq.get_market_data(
        field_list=["Close", "Open"],
        stock_list=stock_code_list,
        start_time=start_time,
        end_time=target_end,
        dividend_type="front",
        period="1d",
        fill_data=True,
    )
    close_df = tq.price_df(market, "Close", column_names=stock_code_list)
    open_df = tq.price_df(market, "Open", column_names=stock_code_list)

    # 2) 生成信号
    ma = vbt.MA.run(close_df, window=window).ma
    ma.columns = close_df.columns

    entries_raw = close_df.vbt.crossed_above(ma)
    exits_raw = close_df.vbt.crossed_below(ma)

    # 下个 bar 执行
    entries = entries_raw.shift(1).fillna(False).astype(bool)
    exits = exits_raw.shift(1).fillna(False).astype(bool)

    # 3) 回测
    portfolio = vbt.Portfolio.from_signals(
        close=close_df,
        entries=entries,
        exits=exits,
        price=open_df,
        init_cash=100000,
        fees=0.0003,
        freq="D",
        size_granularity=100,
    )

    # 4) 输出
    print("\n====== 投资组合回测表现 ======")
    print(portfolio.stats())
    print("\n====== 交易记录 ======")
    print(portfolio.trades.records_readable)

    tq.close()


if __name__ == "__main__":
    main()
```

## 运行说明

- 安装依赖：`pip install -r requirements.txt`
- 确保 TDX 客户端和 `TPythClient.dll` 可用（如有必要配置 `TPYTHCLIENT_DLL`）
- 将代码保存为脚本后运行：`python your_backtest.py`

## 可选框架

- 当前示例采用 `vectorbt`（仓库已包含依赖）
- 你也可以用 `backtrader` 完成同样流程：拉取 `tq` 数据 -> 生成信号 -> 回测评估
