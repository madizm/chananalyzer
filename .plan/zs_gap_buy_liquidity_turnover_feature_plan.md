# ZS Gap Buy 随机森林新增成交额与换手率特征计划

## 目标

在 `scripts/train_zs_gap_buy_rf.py` 的随机森林训练链路中，新增成交额和换手率相关 feature，用于刻画信号入场前的流动性、放量状态和筹码活跃度。

该改动只增强模型训练特征，不改变：

- `strategies/zs_gap_buy.py` 原始买点规则。
- `scripts/backtest_zs_gap_buy.py` 信号回放和收益评估。
- 现有 CSV-only 基础特征。

## 设计原则

1. 默认关闭：通过独立开关启用，避免影响现有训练结果。
2. 严格 point-in-time：只使用 `entry_date` 之前的日线数据。
3. 优先相对特征：成交额用相对近期均值、分位/变化率；换手率用均值、变化率和相对位置。
4. 缺失保守处理：数据库没有 `amount` 或 `turnover_rate` 时填 `0.0`，并在指标中输出覆盖率。
5. 复用 K 线缓存：和 MA 特征共用 `kline_data` 批量读取，避免逐样本查询数据库。

## 字段来源

从 `chan.db.kline_data` 读取：

```text
code
timestamp
close
amount
turnover_rate
```

当前表结构已包含：

- `amount`: 成交额，可为空。
- `turnover_rate`: 换手率，可为空。

首期只做日线特征：

```sql
WHERE kl_type = 'DAY'
```

截止日期与 MA 特征一致：

- 使用 `entry_date` 之前的最后一根日线。
- 不使用 `entry_date` 当日收盘、成交额或换手率。

## 特征定义

### 成交额特征

新增：

```text
day_amount_ratio_5
day_amount_ratio_10
day_amount_ratio_20
day_amount_change_5_pct
day_amount_change_10_pct
day_amount_rank_20
```

计算口径：

```python
last_amount = amount[-1]
amount_maN = mean(valid_amount[-N:])
day_amount_ratio_N = last_amount / amount_maN
day_amount_change_N_pct = (last_amount - amount[-N]) / amount[-N] * 100
day_amount_rank_20 = percentile_rank(last_amount, valid_amount[-20:])
```

说明：

- `valid_amount` 只包含 `amount > 0` 的日线。
- 历史不足或分母为 0 时填 `0.0`。
- `day_amount_rank_20` 取值范围 `[0, 1]`，表示当前成交额在近 20 根有效成交额中的相对位置。

### 换手率特征

新增：

```text
day_turnover_rate
day_turnover_ratio_5
day_turnover_ratio_10
day_turnover_ratio_20
day_turnover_change_5_pct
day_turnover_rank_20
```

计算口径：

```python
last_turnover = turnover_rate[-1]
turnover_maN = mean(valid_turnover[-N:])
day_turnover_ratio_N = last_turnover / turnover_maN
day_turnover_change_5_pct = (last_turnover - turnover_rate[-5]) / turnover_rate[-5] * 100
day_turnover_rank_20 = percentile_rank(last_turnover, valid_turnover[-20:])
```

说明：

- `turnover_rate` 本身已经是相对指标，可以保留 `day_turnover_rate`。
- 历史不足、字段为空或分母为 0 时填 `0.0`。
- 若某只股票长期没有换手率数据，所有换手率特征为 `0.0`，并通过覆盖率统计暴露。

## CLI 设计

在 `scripts/train_zs_gap_buy_rf.py` 新增：

```text
--enable-liquidity-features      启用成交额/换手率特征
--liquidity-windows              默认 5,10,20
--db-path                        复用现有参数，默认 chan.db
```

与 MA 开关独立：

- `--enable-ma-features` 只加均线距离。
- `--enable-liquidity-features` 只加成交额/换手率。
- 两者可以同时启用，并共用一次日线数据缓存。

## 代码改造点

### 1. 扩展 KLineBar

当前：

```python
@dataclass(frozen=True)
class KLineBar:
    timestamp: datetime
    close: float
```

改为：

```python
@dataclass(frozen=True)
class KLineBar:
    timestamp: datetime
    close: float
    amount: float = 0.0
    turnover_rate: float = 0.0
```

### 2. 扩展数据读取

当前 `load_kline_bars_by_code()` 只读取：

```sql
SELECT code, timestamp, close
```

改为：

```sql
SELECT code, timestamp, close, amount, turnover_rate
```

要求：

- `close <= 0` 的 K 线仍跳过。
- `amount`、`turnover_rate` 为空时填 `0.0`。
- 保持原 MA 特征兼容。

### 3. 新增工具函数

```python
def valid_positive(values: Iterable[float]) -> list[float]:
    ...

def percentile_rank(value: float, values: Sequence[float]) -> float:
    ...
```

`percentile_rank` 可用简单口径：

```python
sum(1 for item in values if item <= value) / len(values)
```

### 4. 新增 feature 构造函数

```python
def build_day_liquidity_features(
    sample: RFSample,
    day_bars_by_code: dict[str, list[KLineBar]],
    windows: Sequence[int],
) -> dict[str, float]:
    ...
```

并提供：

```python
def enrich_samples_with_day_liquidity_features(...):
    ...
```

样本构建流程保持两阶段：

1. `build_samples()` 只构造 CSV 可得基础特征。
2. 根据 CLI 参数追加 MA / liquidity 特征。

### 5. 共享日线缓存

当前启用 MA 时会读取一次 day bars。实现 liquidity 时应调整为：

```python
needs_day_bars = args.enable_ma_features or args.enable_liquidity_features
if needs_day_bars:
    day_bars_by_code = load_kline_bars_by_code(...)
```

然后分别 enrich：

```python
if args.enable_ma_features:
    enrich_samples_with_day_ma_features(...)

if args.enable_liquidity_features:
    enrich_samples_with_day_liquidity_features(...)
```

## 测试计划

扩展 `tests/test_zs_gap_buy_rf.py`：

1. `test_build_day_liquidity_features_uses_previous_trade_day`
   - 构造 entry 当天异常大成交额。
   - 验证 feature 不使用 entry 当天。

2. `test_build_day_liquidity_features_amount_ratios`
   - 构造近 20 日递增成交额。
   - 验证 `day_amount_ratio_5/10/20` 和 `day_amount_rank_20`。

3. `test_build_day_liquidity_features_turnover_ratios`
   - 构造换手率序列。
   - 验证 `day_turnover_rate`、`day_turnover_ratio_5`、`day_turnover_rank_20`。

4. `test_liquidity_features_missing_values_default_zero`
   - `amount=None` 或 `0`，`turnover_rate=None`。
   - 验证相关 feature 为 `0.0`，无异常。

5. `test_csv_only_feature_count_unchanged_when_liquidity_disabled`
   - 不启用新开关时，基础 feature count 不变。

6. 可选 SQLite 集成测试
   - 临时建 `kline_data` 表，写入 `amount/turnover_rate`。
   - 调用 `load_kline_bars_by_code()` 验证字段读取。

## 验证命令

单测：

```powershell
python -m pytest tests\test_zs_gap_buy_rf.py tests\test_zs_gap_buy.py
```

编译：

```powershell
python -m py_compile scripts\train_zs_gap_buy_rf.py
```

真实 CSV smoke：

```powershell
python scripts\train_zs_gap_buy_rf.py --input-csv outputs\30m_zs_gap_buy_rows_20260524_165339.csv --split-time 2026-04-01 --target-return-pct 2.0 --trade-cost-pct 0.1 --enable-liquidity-features --output-dir outputs\zs_gap_buy_rf_liquidity_smoke
```

MA + liquidity 同时启用：

```powershell
python scripts\train_zs_gap_buy_rf.py --input-csv outputs\30m_zs_gap_buy_rows_20260524_165339.csv --split-time 2026-04-01 --target-return-pct 2.0 --trade-cost-pct 0.1 --enable-ma-features --enable-liquidity-features --output-dir outputs\zs_gap_buy_rf_ma_liquidity_smoke
```

## 验收标准

1. 默认不启用时，现有基础 feature count 保持不变。
2. 启用 `--enable-liquidity-features` 后，`feature_meta.json` 至少包含：
   - `day_amount_ratio_5`
   - `day_amount_ratio_10`
   - `day_amount_ratio_20`
   - `day_amount_change_5_pct`
   - `day_amount_change_10_pct`
   - `day_amount_rank_20`
   - `day_turnover_rate`
   - `day_turnover_ratio_5`
   - `day_turnover_ratio_10`
   - `day_turnover_ratio_20`
   - `day_turnover_change_5_pct`
   - `day_turnover_rank_20`
3. `feature_importance.csv` 能正常输出新字段。
4. 单测覆盖 entry 当天不可见，防止成交额/换手率未来函数。
5. smoke 训练成功输出 `metrics.json`、`scored_samples.csv`、`top_buckets.csv`。

## 风险与注意事项

1. `amount` 覆盖风险：不同数据源成交额口径可能不同，需确认单位是否一致。
2. `turnover_rate` 缺失风险：历史数据可能没有回填换手率，缺失比例需要监控。
3. 极端值风险：成交额容易受停牌复牌、涨跌停、指数调整影响；首期用比值和 rank 降低极端值影响。
4. 特征冗余风险：`amount_ratio` 与 `turnover_ratio` 可能高度相关，需要看 feature importance 和 walk-forward 稳定性。
5. 线上一致性风险：未来扫描接入模型时，必须复用同样的前一交易日截止口径。
