# ZS Gap Buy 随机森林新增均线距离特征计划

## 目标

在 `scripts/train_zs_gap_buy_rf.py` 的随机森林训练链路中，新增均线距离类 feature，用于刻画信号入场时价格相对趋势均线的位置。

该改动只增强训练特征，不改变 `strategies/zs_gap_buy.py` 的原始买点规则，也不改变 `backtest_zs_gap_buy.py` 的信号回放逻辑。

## 设计原则

1. 严格 point-in-time：只使用 `observation_time` 或 `entry_date` 之前已经存在的 K 线。
2. 继续使用相对值：均线距离统一用百分比或比值，不使用绝对价差。
3. 默认先做日线均线：因为回测收益评估使用日线入场/退出，日线趋势环境更稳定。
4. 信号级别均线作为第二步：如果日线 MA feature 有增益，再补同级别 MA feature。
5. 训练端和未来扫描端必须共享同一套 feature 构造语义，否则模型无法安全上线。

## 特征定义

### 日线均线距离

从 `chan.db.kline_data` 读取 `kl_type='DAY'` 的历史日线，截止日期为 `entry_date` 之前的最后一个交易日。

首期新增：

```text
day_ma5_dist_pct
day_ma10_dist_pct
day_ma20_dist_pct
day_ma5_ma20_dist_pct
day_close_above_ma5
day_close_above_ma10
day_close_above_ma20
```

计算口径：

```python
day_maN = mean(close[-N:])
day_maN_dist_pct = (last_close - day_maN) / day_maN * 100
day_ma5_ma20_dist_pct = (day_ma5 - day_ma20) / day_ma20 * 100
day_close_above_maN = 1.0 if last_close >= day_maN else 0.0
```

其中：

- `last_close` 是 `entry_date` 前一个可用交易日的日线收盘价。
- 若历史不足 N 根，feature 填 `0.0`，同时可输出覆盖率统计。

### 可选信号级别均线距离

第二步再加：

```text
signal_ma5_dist_pct
signal_ma10_dist_pct
signal_ma20_dist_pct
signal_close_above_ma5
signal_close_above_ma10
signal_close_above_ma20
```

从 `kline_data` 读取样本 `level` 对应 `kl_type`，截止 `observation_time`，取最近一根已完成的同级别 K 线收盘价。

首期不默认启用，避免训练脚本一次性引入较多数据库查询复杂度。

## 数据读取方案

### 新增 CLI 参数

在 `scripts/train_zs_gap_buy_rf.py` 增加：

```text
--enable-ma-features        启用均线距离特征
--ma-feature-levels         默认 day；后续支持 day,signal
--ma-windows                默认 5,10,20
--db-path                   默认 chan.db
```

默认保持关闭，保证现有 CSV-only 训练流程不受影响。

### 数据缓存

为避免每条样本查询数据库：

1. 先收集输入 CSV 中涉及的 `code`。
2. 按 `code + kl_type` 一次性读取所需 K 线。
3. 在内存中按时间排序缓存：

```python
Dict[tuple[str, str], list[KLineBar]]
```

4. 每条样本通过二分查找定位截止点。

### 截止时间

日线 feature：

- 使用 `entry_date` 之前的最后一根日线。
- 不使用 `entry_date` 当日收盘，因为 `entry_mode=next_open` 时该收盘不可知。

信号级别 feature：

- 使用 `timestamp <= observation_time` 的最后一根同级别 K 线。
- 如果后续发现 `observation_time` 对应 K 线尚未完成，需要改为 `< observation_time`，以避免盘中未来数据。

## 代码改造点

### 1. 数据结构

新增轻量结构：

```python
@dataclass(frozen=True)
class KLineBar:
    timestamp: datetime
    close: float
```

### 2. 数据读取函数

新增：

```python
def load_kline_bars_by_code(
    db_path: Path,
    codes: Sequence[str],
    kl_type: str,
) -> dict[str, list[KLineBar]]:
    ...
```

要求：

- 只读取 `timestamp, close`。
- 按 `code, timestamp` 排序。
- 跳过非法 close。

### 3. Feature enrich 函数

新增：

```python
def enrich_ma_features(
    sample: RFSample,
    day_bars_by_code: dict[str, list[KLineBar]],
    ma_windows: Sequence[int],
) -> None:
    ...
```

更推荐返回新 dict：

```python
def build_ma_features(...) -> dict[str, float]:
    ...
```

然后在 `build_samples()` 后统一：

```python
sample.feature.update(build_ma_features(...))
```

避免 `build_features(row)` 直接依赖数据库。

### 4. 样本构建流程

保持两阶段：

1. `build_samples()` 只构造 CSV 可得特征。
2. `maybe_enrich_samples_with_ma()` 根据 CLI 参数追加 MA 特征。

这样单测和 CSV-only smoke 不受影响。

## 测试计划

新增或扩展 `tests/test_zs_gap_buy_rf.py`：

1. `test_build_day_ma_features_uses_previous_trade_day`
   - 构造 20 根日线。
   - 样本 `entry_date` 是第 21 天。
   - 验证 MA 使用前 20 根，不使用 entry 当天。

2. `test_build_day_ma_features_requires_enough_history`
   - 历史不足 MA20。
   - 验证 `day_ma20_dist_pct == 0.0`。

3. `test_ma_features_are_relative_not_absolute`
   - 验证输出字段为 `*_pct` 和 `above`。
   - 不出现 `day_ma5_abs_dist` 这类绝对价差字段。

4. `test_csv_only_features_unchanged_when_ma_disabled`
   - 不启用 `--enable-ma-features` 时，特征集合保持当前 15 个。

5. 可选集成 smoke：
   - 用小临时 SQLite 写入几只股票日线。
   - 运行训练脚本 `--enable-ma-features --db-path tmp.db`。

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
python scripts\train_zs_gap_buy_rf.py --input-csv outputs\30m_zs_gap_buy_rows_20260524_165339.csv --split-time 2026-04-01 --target-return-pct 2.0 --trade-cost-pct 0.1 --enable-ma-features --output-dir outputs\zs_gap_buy_rf_ma_smoke
```

## 验收标准

1. 不启用 `--enable-ma-features` 时，现有训练结果和 feature count 保持不变。
2. 启用后，`feature_meta.json` 包含：
   - `day_ma5_dist_pct`
   - `day_ma10_dist_pct`
   - `day_ma20_dist_pct`
   - `day_ma5_ma20_dist_pct`
   - `day_close_above_ma5`
   - `day_close_above_ma10`
   - `day_close_above_ma20`
3. `feature_importance.csv` 能正常输出新增字段的重要性。
4. 单测覆盖“entry 当天不可见”的防未来函数口径。
5. smoke 训练成功输出 `metrics.json`、`scored_samples.csv`、`top_buckets.csv`。

## 风险

1. 数据覆盖风险：部分股票日线历史不足 MA20，需监控默认填 0 的比例。
2. 时间口径风险：`entry_date`、`observation_time` 和日线 timestamp 格式可能不一致，需要统一解析。
3. 特征泄漏风险：日线 feature 不能使用 entry 当日收盘。
4. 线上一致性风险：如果未来扫描接入模型，也必须复用相同 MA 截止规则。
5. 训练耗时风险：全量 CSV + 全量日线读取会增加内存和时间，需要按 code 批量缓存而不是逐样本查库。
