# ZS Gap Buy 随机森林新增均线斜率特征计划

## 目标

在 `scripts/train_zs_gap_buy_rf.py` 的随机森林训练链路中，新增均线斜率 feature，用于刻画信号入场前趋势方向和趋势加速度。

该改动只增强模型训练特征，不改变：

- `strategies/zs_gap_buy.py` 原始买点规则。
- `scripts/backtest_zs_gap_buy.py` 信号回放和收益评估。
- 现有 CSV-only 基础特征。

## 设计原则

1. 严格 point-in-time：只使用 `entry_date` 之前的日线。
2. 使用相对斜率：斜率统一按百分比变化表达，不用绝对价差。
3. 复用 MA 日线缓存：不新增逐样本数据库查询。
4. 默认跟随 MA 特征：首期可挂在 `--enable-ma-features` 下，也可以增加独立开关；实现前需明确。
5. 历史不足时填 `0.0`，避免改变训练流程稳定性。

## 特征定义

### 首期日线均线斜率

新增：

```text
day_ma5_slope_3_pct
day_ma10_slope_3_pct
day_ma20_slope_3_pct
day_ma5_slope_5_pct
day_ma10_slope_5_pct
day_ma20_slope_5_pct
```

含义：

- `day_maN_slope_K_pct` 表示当前 MA(N) 相比 K 个交易日前 MA(N) 的百分比变化。
- 当前时点仍然是 `entry_date` 之前的最后一个交易日。

计算口径：

```python
ma_now = mean(close[-N:])
ma_prev = mean(close[-N-K:-K])
day_maN_slope_K_pct = (ma_now - ma_prev) / ma_prev * 100
```

例如：

```python
day_ma20_slope_5_pct = (MA20[t] - MA20[t-5]) / MA20[t-5] * 100
```

历史要求：

- 至少需要 `N + K` 根日线。
- 不满足时填 `0.0`。

### 可选增强

第二阶段可加入：

```text
day_ma5_slope_accel_pct
day_ma10_slope_accel_pct
day_ma20_slope_accel_pct
```

计算近两段斜率差：

```python
slope_recent = (MA[t] - MA[t-K]) / MA[t-K]
slope_prev = (MA[t-K] - MA[t-2K]) / MA[t-2K]
accel = (slope_recent - slope_prev) * 100
```

首期不做 acceleration，先验证基础斜率是否有收益增益。

## CLI 设计

推荐新增独立开关，避免所有 MA 距离训练都自动加大量斜率字段：

```text
--enable-ma-slope-features       启用均线斜率特征
--ma-slope-windows               默认 5,10,20
--ma-slope-lookbacks             默认 3,5
```

与现有开关关系：

- `--enable-ma-features`：只加 MA 距离、MA 多空位置。
- `--enable-ma-slope-features`：只加 MA 斜率。
- 两者可以同时启用，并共用一次日线数据缓存。
- `--db-path` 继续复用现有参数。

如果希望少一个开关，也可以把 slope 纳入 `--enable-ma-features`，但需要同步更新旧 smoke 的 feature count 预期；不推荐。

## 代码改造点

### 1. 复用现有数据结构

继续使用：

```python
@dataclass(frozen=True)
class KLineBar:
    timestamp: datetime
    close: float
    amount: float = 0.0
    turnover_rate: float = 0.0
```

不需要新增数据库字段。

### 2. 新增 MA 序列工具函数

新增：

```python
def moving_average_at(values: Sequence[float], end_pos: int, window: int) -> Optional[float]:
    ...
```

语义：

- `end_pos` 是切片结束位置，Python 风格不包含自身。
- `moving_average_at(closes, len(closes), 20)` 表示当前 MA20。
- `moving_average_at(closes, len(closes) - 5, 20)` 表示 5 根前 MA20。

### 3. 新增斜率 feature 函数

新增：

```python
def build_day_ma_slope_features(
    sample: RFSample,
    day_bars_by_code: dict[str, list[KLineBar]],
    ma_windows: Sequence[int],
    lookbacks: Sequence[int],
) -> dict[str, float]:
    ...
```

行为：

1. 初始化所有 `day_ma{window}_slope_{lookback}_pct = 0.0`。
2. 获取 `entry_date` 前的日线 close。
3. 对每个 `(window, lookback)` 计算当前 MA 和 lookback 前 MA。
4. 分母不足或为 0 时保持 `0.0`。

新增 enrich：

```python
def enrich_samples_with_day_ma_slope_features(...):
    ...
```

### 4. 共享日线缓存

当前逻辑：

```python
if args.enable_ma_features or args.enable_liquidity_features:
    day_bars_by_code = load_kline_bars_by_code(...)
```

改成：

```python
if args.enable_ma_features or args.enable_ma_slope_features or args.enable_liquidity_features:
    day_bars_by_code = load_kline_bars_by_code(...)
```

然后按开关分别 enrich：

```python
if args.enable_ma_features:
    enrich_samples_with_day_ma_features(...)

if args.enable_ma_slope_features:
    enrich_samples_with_day_ma_slope_features(...)
```

### 5. Metrics 元信息

`metrics.json` 增加：

```json
{
  "ma_slope_features_enabled": true,
  "ma_slope_windows": [5, 10, 20],
  "ma_slope_lookbacks": [3, 5]
}
```

## 测试计划

扩展 `tests/test_zs_gap_buy_rf.py`：

1. `test_build_day_ma_slope_features_uses_previous_trade_day`
   - 构造 entry 当天极端 close。
   - 验证 slope 不使用 entry 当天。

2. `test_build_day_ma_slope_features_calculates_relative_slope`
   - 构造递增 close。
   - 验证 `day_ma5_slope_3_pct` 符合 `(MA_now - MA_prev) / MA_prev * 100`。

3. `test_build_day_ma_slope_features_requires_enough_history`
   - 历史不足 `N + K`。
   - 验证对应 slope 为 `0.0`。

4. `test_ma_slope_features_are_pct_not_abs`
   - 验证字段后缀为 `_pct`。
   - 不出现 `abs` 或绝对价差字段。

5. `test_enrich_samples_with_day_ma_slope_features_adds_fields`
   - 验证 feature_meta 包含默认 6 个 slope 字段。

6. `test_csv_only_feature_count_unchanged_when_slope_disabled`
   - 默认不开启 slope 时，基础 feature count 保持不变。

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
python scripts\train_zs_gap_buy_rf.py --input-csv outputs\30m_zs_gap_buy_rows_20260524_165339.csv --split-time 2026-04-01 --target-return-pct 2.0 --trade-cost-pct 0.1 --enable-ma-slope-features --output-dir outputs\zs_gap_buy_rf_ma_slope_smoke
```

MA 距离 + MA 斜率 + liquidity 同时启用：

```powershell
python scripts\train_zs_gap_buy_rf.py --input-csv outputs\30m_zs_gap_buy_rows_20260524_165339.csv --split-time 2026-04-01 --target-return-pct 2.0 --trade-cost-pct 0.1 --enable-ma-features --enable-ma-slope-features --enable-liquidity-features --output-dir outputs\zs_gap_buy_rf_all_features_smoke
```

## 验收标准

1. 默认不启用时，现有基础 feature count 不变。
2. 只启用 `--enable-ma-slope-features` 后，`feature_meta.json` 包含：
   - `day_ma5_slope_3_pct`
   - `day_ma10_slope_3_pct`
   - `day_ma20_slope_3_pct`
   - `day_ma5_slope_5_pct`
   - `day_ma10_slope_5_pct`
   - `day_ma20_slope_5_pct`
3. 新字段进入 `feature_importance.csv`。
4. 单测覆盖 entry 当天不可见，避免未来函数。
5. smoke 训练成功输出 `metrics.json`、`scored_samples.csv`、`top_buckets.csv`。

## 风险与注意事项

1. 特征冗余：MA 斜率和 MA 距离可能高度相关，需要用 feature importance 和 walk-forward 观察增益。
2. 窗口敏感：`lookback=3/5` 对短期噪声敏感，后续可尝试 `10`。
3. 历史不足：新股或短历史样本 slope 为 0，需关注覆盖率。
4. 过拟合：斜率字段会增加维度，必须以 walk-forward Top 分层收益为准。
5. 线上一致性：未来扫描接入模型时必须复用同样的 `entry_date` 前一交易日口径。
