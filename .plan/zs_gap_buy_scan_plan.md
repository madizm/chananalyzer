# 指定级别双中枢抬高买点扫描实施计划

## 目标

新增一个可配置级别的买点扫描算法，用于识别以下结构：

1. 指定级别至少存在 2 个中枢。
2. 取最近两个有效中枢。
3. 最近中枢的低点高于前一个中枢的高点。

当前目标是做成可复用策略函数、命令行扫描脚本和回放回测脚本；看板和图表标注作为后续扩展。

## 规则定义

### 数据级别

- 信号级别通过脚本参数 `--level` 指定，默认 `15M`。
- 支持级别：`1M`、`5M`、`15M`、`30M`、`60M/1H`、`DAY/D`、`WEEK/W`、`MON/MONTH`。
- 扫描数据源默认使用本地 `chan.db`，即 `DATA_SRC.CACHE_DB`。
- 当前只依赖单级别结构，不引入日线/30M 共振过滤。

### 中枢来源

- 使用 `chan[signal_idx].zs_list`，即指定级别的笔级中枢。
- 不使用 `segzs_list`，避免把“线段级中枢”和用户描述的普通中枢混在一起。
- 默认只使用已确认中枢：`zs.is_sure is True`。
- 可通过参数放开尾部不确定中枢，用于盘中实时观察。

### 中枢方向

不判定“上涨中枢 / 下跌中枢”，也不读取所属线段方向。有效中枢只按时间顺序和确认状态筛选。

### 高低点比较

首期使用中枢区间边界：

```python
latest_zs.low > previous_zs.high
```

其中：

- `CZS.low` 是中枢区间下沿。
- `CZS.high` 是中枢区间上沿。

暂不使用 `peak_low / peak_high`，因为它们表示中枢涉及元素的峰值范围，语义比“中枢低点/高点”更宽。后续如需要，可增加 `--range-mode zs|peak`。

### 最近和再往前

首期按时间顺序取过滤后的最近两个中枢：

1. 从 `zs_list` 中剔除不满足确认要求的中枢。
2. 取最后一个作为 `latest_zs`。
3. 取倒数第二个作为 `previous_zs`。
4. 要求 `latest_zs.low > previous_zs.high`。

这意味着“再往前一个中枢”是指最近中枢之前的相邻有效中枢，不跳过中间中枢。

## 已实现策略模块

### 文件

`strategies/zs_gap_buy.py`

### 数据结构

```python
@dataclass(frozen=True)
class ZSGapBuyHit:
    signal_time: datetime
    signal_date: str
    signal_price: float
    observation_time: datetime
    observation_date: str
    latest_zs: dict[str, Any]
    previous_zs: dict[str, Any]
    gap_abs: float
    gap_pct: float
```

### 核心函数

```python
def detect_zs_gap_buy(
    snapshot: CChan,
    signal_idx: int,
    observation_time: datetime,
    *,
    require_zs_sure: bool = True,
    min_gap_pct: float = 0.0,
) -> ZSGapBuyHit | None:
    ...
```

函数行为：

- 读取 `snapshot[signal_idx].zs_list`。
- 最近两个有效中枢满足规则时返回命中对象。
- `signal_time` 默认取最近中枢结束时间 `latest_zs.end.time`。
- `signal_price` 默认取指定级别最新 K 线收盘价。
- `gap_abs = latest_zs.low - previous_zs.high`。
- `gap_pct = gap_abs / previous_zs.high * 100`。
- 若 `min_gap_pct > 0`，要求 `gap_pct >= min_gap_pct`。

### 辅助函数

```python
def serialize_zs(zs) -> dict[str, Any]:
    ...
```

`serialize_zs()` 输出字段：

- `begin_time`
- `end_time`
- `begin_bi_idx`
- `end_bi_idx`
- `low`
- `high`
- `mid`
- `peak_low`
- `peak_high`
- `is_sure`

## 已实现扫描脚本

### 文件

`scripts/scan_zs_gap_buy.py`

### 职责

- 从 `chan.db` 读取可扫描股票列表。
- 对每只股票加载指定级别 Chan 结构。
- 调用 `detect_zs_gap_buy()`。
- 控制台输出命中股票。
- 可选写入现有扫描表 `scan_runs / scan_results / scan_signals`。

### 参数

```text
--codes              指定股票代码
--limit              未指定 codes 时扫描上限，默认 50
--all                扫描全部股票
--begin              K线加载开始日期，默认向前约 370 天
--end                K线加载结束日期，默认当前日期
--signal-begin       信号过滤开始日期
--signal-end         信号过滤结束日期
--level              扫描级别，默认 15M
--min-gap-pct        近中枢 low 高于前中枢 high 的最小百分比，默认 0
--include-unsure-zs  允许使用尾部未确认中枢
--bi-strict          启用严格笔
--no-db              仅控制台输出，不写入数据库
```

### 扫描配置

```python
CChanConfig({
    "trigger_step": False,
    "bi_strict": bi_strict,
    "print_warning": False,
})
```

`bs_type` 不需要配置，因为本规则不依赖买卖点对象。

### 扫描结果字段

每个命中结果建议包含：

- `code`
- `signal_time`
- `latest_price`
- `change_pct`
- `gap_abs`
- `gap_pct`
- `latest_zs`
- `previous_zs`
- `signals`

写入 `scan_signals` 时：

- `signal_type`: `zs_gap_buy`
- `direction`: `buy`
- `signal_date`: `hit.signal_time`
- `signal_price`: `hit.signal_price`
- `period`: 实际 `--level`

## 已实现回放回测

### 文件

`scripts/backtest_zs_gap_buy.py`

### 职责

- 使用 `trigger_step=True` 和 `chan.step_load()`，避免未来函数。
- 并行按股票收集信号，每个子进程内部用 snapshot 调用同一个策略函数。
- 父进程串行读取日线、评估收益并写出 CSV/JSON，避免并发写文件。
- 用最近两个中枢的起止笔索引和起止时间去重，避免同一结构在后续 snapshot 重复计数。
- 按日线数据做 N 日后收益评估，支持次日开盘/收盘入场、固定止损和 horizon 退出。
- 输出信号明细 CSV 和统计 JSON。

### 参数

```text
--codes                       指定股票代码
--limit                       未指定 codes 时回测上限，默认 50
--all                         回测全部股票
--begin                       K线加载开始日期
--end                         K线加载结束日期
--signal-begin                信号过滤开始日期
--signal-end                  信号过滤结束日期
--level                       信号级别，默认 15M
--min-gap-pct                 近中枢 low 高于前中枢 high 的最小百分比，默认 0
--include-unsure-zs           允许使用尾部未确认中枢
--max-signal-age-days         信号最大允许账龄，默认 2 个交易日
--max-signal-deviation-pct    观测价相对信号价最大偏离百分比
--horizon                     N日后收益评估窗口，默认 5
--entry-mode                  next_open 或 next_close
--stop-loss-pct               固定止损百分比，默认 5.0；0 表示关闭
--output-dir                  输出目录，默认 outputs
--bi-strict                   启用严格笔
--workers                     并行收集信号的进程数，默认 min(4, CPU核数)；1 表示串行
```

## 测试计划

### 单元测试

新增 `tests/test_zs_gap_buy.py`：

1. 最近两个有效中枢满足 `latest.low > previous.high`，应命中。
2. 中枢数量少于 2，不命中。
3. 不判定中枢方向，只要 gap 满足即可命中。
4. `latest.low <= previous.high`，不命中。
5. `require_zs_sure=True` 时跳过未确认中枢。
6. `min_gap_pct` 大于实际 gap 时不命中。

单测使用轻量 fake 对象构造 `level_kl.zs_list`，不需要真实跑完整 Chan 引擎。

### 集成验证

用少量股票跑扫描：

```powershell
python scripts\scan_zs_gap_buy.py --level 15M --codes 000001 600519 --begin 2025-01-01 --no-db
```

用较小样本跑全库扫描：

```powershell
python scripts\scan_zs_gap_buy.py --level 30M --limit 50 --begin 2025-01-01 --no-db
```

检查点：

- 无异常跳过。
- 命中股票能打印两个中枢的时间、区间和 gap。
- 手工打开 `/chart?code=<code>&lv=15m&data_src=CACHE_DB&x_range=500` 能复核结构。

回测脚本基础验证：

```powershell
python scripts\backtest_zs_gap_buy.py --level 15M --limit 1 --begin 2026-01-01 --end 2026-02-01 --horizon 3 --output-dir outputs\zs_gap_buy_smoke
```

已执行的验证：

```powershell
python -m pytest tests\test_zs_gap_buy.py
python -m py_compile strategies\zs_gap_buy.py scripts\scan_zs_gap_buy.py scripts\backtest_zs_gap_buy.py
python scripts\scan_zs_gap_buy.py --level 15M --limit 1 --begin 2026-01-01 --no-db
python scripts\scan_zs_gap_buy.py --level 30M --limit 1 --begin 2026-01-01 --no-db
python scripts\backtest_zs_gap_buy.py --level 15M --limit 1 --begin 2026-01-01 --end 2026-02-01 --horizon 3 --output-dir outputs\zs_gap_buy_smoke
python scripts\backtest_zs_gap_buy.py --level 15M --limit 2 --begin 2026-01-01 --end 2026-02-01 --horizon 3 --workers 2 --output-dir outputs\zs_gap_buy_smoke
python scripts\backtest_zs_gap_buy.py --level 30M --limit 2 --begin 2026-01-01 --end 2026-02-01 --horizon 3 --workers 2 --output-dir outputs\zs_gap_buy_smoke
```

## 实施状态

1. 已新增 `strategies/zs_gap_buy.py`，只实现结构检测和序列化，不做数据库逻辑；当前提供通用 `detect_zs_gap_buy()`。
2. 已新增 `tests/test_zs_gap_buy.py`，覆盖相邻中枢、确认状态和 gap 条件。
3. 已新增 `scripts/scan_zs_gap_buy.py`，复用现有扫描脚本的股票列表、价格提取和落库模式，并支持 `--level`。
4. 已新增 `scripts/backtest_zs_gap_buy.py`，用 step replay 做无未来函数回测，并支持 `--level`。
5. 已将回测脚本的信号收集阶段按股票并行化，支持 `--workers` 控制进程数。
6. 已完成单测、语法编译、扫描小样本、串行回测小样本和并行回测小样本验证。
7. 如命中样本过多或过少，再评估是否增加 `min_gap_pct`、只看确认线段、或附加日线趋势过滤。

## 风险与待确认点

1. 当前不判定“上涨/下跌中枢”，只比较最近两个有效中枢的区间是否完全上移。
2. “近中枢低点高于前中枢高点”当前使用 `CZS.low/high`。如果实际想比较中枢涉及笔的极值，应改为 `peak_low > peak_high` 或增加参数。
3. 非回放扫描会使用完整历史结构，适合当前截面选股；严谨历史验证必须用 `trigger_step=True` 回放脚本。
4. 尾部未确认中枢会反复重算。默认只用确认中枢，盘中模式再通过参数显式打开。
5. 入场日期如何确认？？？--出现双中枢后进去观察池，等待底分入场 --放量直接入场

## 例外

1. 若 previous 中枢前还有中枢 p2，且满足 previous.low > p2.high 。不命中
