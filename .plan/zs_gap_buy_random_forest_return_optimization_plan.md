# 双中枢抬高买点随机森林收益优化实施计划

## 目标

在现有 `zs_gap_buy` 规则信号基础上，增加一层随机森林排序模型，用于筛选更高预期收益的买点。

首期目标不是替代原始买点规则，而是做成“规则命中 -> 模型打分 -> 按分数/Top 分层筛选”的增强链路：

1. 继续用 `strategies/zs_gap_buy.py` 产生候选买点。
2. 基于回放回测样本生成训练数据，避免未来函数。
3. 用 `RandomForestClassifier` 或 `RandomForestRegressor` 学习候选信号的未来收益质量。
4. 输出 Top 5% / 10% / 20% 分层收益、固定阈值收益、walk-forward 稳定性和特征重要性。
5. 后续扫描时可选择只保留模型高分信号。

## 总体思路

首期采用分类模型作为主线：

- 标签：未来收益是否达到可交易收益阈值，扣除交易成本后仍为正。
- 分数：`predict_proba(...)[1]` 作为买点质量分。
- 优化目标：不是单纯提高 AUC，而是提高 Top 分层的平均收益和扣成本后收益。

分类模型优先于回归模型的原因：

- 当前回测输出已经有 `return_pct`、`is_win`、`exit_reason`，改造成本较低。
- 随机森林分类概率可直接用于信号排序。
- 对极端收益样本不如回归敏感，更适合作为第一版稳定基线。

第二阶段再补充 `RandomForestRegressor`，直接预测 `return_pct_after_cost`，用于和分类排序结果对照。

## 数据来源

### 输入

基于现有回测脚本生成候选样本：

```powershell
python scripts\backtest_zs_gap_buy.py --level 15M --all --begin 2025-01-01 --end 2026-05-24 --horizon 5 --workers 4 --output-dir outputs\zs_gap_buy_rf_source
```

也可对不同级别分别生成：

```powershell
python scripts\backtest_zs_gap_buy.py --level 30M --all --begin 2025-01-01 --end 2026-05-24 --horizon 5 --workers 4 --output-dir outputs\zs_gap_buy_rf_source
```

首期训练脚本读取回测 CSV，而不是重新跑 Chan 引擎。这样可以先验证模型价值，避免训练逻辑和回放逻辑耦合过重。

### 样本单位

每一行已评估收益的 `zs_gap_buy` 信号是一条样本。

必备字段：

- `code`
- `level`
- `signal_time`
- `observation_time`
- `entry_date`
- `entry_open` 或 `entry_close`
- `exit_date`
- `exit_reason`
- `return_pct`
- `is_win`
- `gap_abs`
- `gap_pct`
- `signal_age_days`
- `signal_deviation_pct`
- `previous_zs_json`
- `latest_zs_json`

## 标签设计

### 首期分类标签

新增训练参数：

```text
--target-return-pct       默认 2.0
--trade-cost-pct          默认 0.1
```

标签定义：

```python
return_after_cost_pct = return_pct - trade_cost_pct
label = 1 if return_after_cost_pct >= target_return_pct else 0
```

默认 `target_return_pct=2.0` 的原因：

- 只预测正收益容易让模型学到“微利但不可交易”的样本。
- 双中枢抬高买点属于结构型信号，应优先筛选有明显空间的候选。

### 评估收益字段

训练输出中保留：

- `return_pct`
- `return_after_cost_pct`
- `label`
- `score`
- `exit_reason`

评估时同时看命中率和真实收益，不用单一分类指标决定模型好坏。

## 特征设计

### 归一化原则

随机森林是树模型，不要求像线性模型、SVM 那样做 `StandardScaler` 或 MinMax 标准化。但股票横截面里，绝对价格和绝对宽度容易引入价格档位偏差，因此训练特征优先使用相对值：

- 百分比：相对价格、中枢中轴、入场价的变化比例。
- 比值：当前宽度 / 历史宽度，当前量能 / 最近均量。
- 位置：价格在中枢区间内外的位置。
- 分位数：后续可加入横截面或滚动窗口分位。

绝对值字段可以保留在样本明细中用于审计和诊断，但默认不进入核心训练特征，除非后续实验能证明它在 walk-forward 中稳定增益。

### 首期可直接从回测 CSV 提取的特征

这些特征无需重新加载 Chan 快照：

- `gap_pct`: 最近中枢低点高于前中枢高点的幅度。
- `gap_abs`: 绝对抬高幅度，仅保留为诊断字段，默认不进入核心训练特征。
- `signal_age_days`: 信号出现后到观察时点的交易日账龄。
- `signal_deviation_pct`: 观察价相对信号价偏离。
- `zs_width_prev_pct`: 前一个中枢相对宽度，`(previous.high - previous.low) / previous.mid`。
- `zs_width_latest_pct`: 最近中枢相对宽度，`(latest.high - latest.low) / latest.mid`。
- `zs_width_ratio`: 最近中枢绝对宽度 / 前一个中枢绝对宽度。
- `zs_mid_lift_pct`: 最近中枢中轴相对前一个中枢中轴抬高比例。
- `zs_peak_range_prev_pct`: 前一个中枢峰值区间相对宽度，`(previous.peak_high - previous.peak_low) / previous.mid`。
- `zs_peak_range_latest_pct`: 最近中枢峰值区间相对宽度，`(latest.peak_high - latest.peak_low) / latest.mid`。
- `latest_zs_is_sure`: 最近中枢是否确认。
- `previous_zs_is_sure`: 前一个中枢是否确认。
- `entry_gap_to_latest_low_pct`: 入场价相对最近中枢下沿距离，`(entry_price - latest.low) / latest.low`。
- `entry_gap_to_latest_high_pct`: 入场价相对最近中枢上沿距离，`(entry_price - latest.high) / latest.high`。
- `entry_pos_in_latest_zs`: 入场价在最近中枢区间的位置，`(entry_price - latest.low) / (latest.high - latest.low)`。

### 第二阶段补充的行情特征

如果首期 CSV 特征有排序能力，再从 `chan.db` 增补行情上下文：

- 入场日前 5/10/20 日收益率。
- 入场日前 5/10/20 日波动率。
- 入场日前成交量相对 5/10/20 日均量。
- 入场 K 线实体比例、上影线比例、下影线比例。
- 日线均线距离：MA5 / MA10 / MA20。
- 所属级别最近 N 根 K 线收益、波动和量能。

第二阶段建议单独做 `feature_enrich`，不要在第一版训练脚本里一次性堆太多数据读取。

## 模型方案

### 随机森林分类基线

使用 `sklearn.pipeline.Pipeline`：

```python
Pipeline([
    ("imputer", SimpleImputer(strategy="median")),
    ("clf", RandomForestClassifier(...)),
])
```

初始参数：

```python
{
    "n_estimators": 300,
    "max_depth": 4,
    "min_samples_leaf": 5,
    "max_features": "sqrt",
    "class_weight": "balanced_subsample",
    "random_state": 42,
}
```

小范围调参：

- `max_depth`: `3`, `4`, `5`, `None`
- `min_samples_leaf`: `3`, `5`, `10`, `20`
- `max_features`: `"sqrt"`, `"log2"`, `0.5`
- `n_estimators`: `300`, `500`

选择标准：

1. walk-forward Top20% 扣成本后平均收益。
2. Top10% / Top20% 在不同月份是否稳定。
3. 止损率是否明显低于全体样本。
4. AUC / Average Precision 只作为辅助指标。

### 可选回归对照

第二阶段增加：

```python
RandomForestRegressor
```

目标：

```python
y = return_after_cost_pct
```

排序分数直接使用预测收益。仅当回归模型在 walk-forward Top 分层收益上明显优于分类模型时，才考虑切换主模型。

## 拆分与验证

### 时间切分

必须按时间切分，禁止随机打乱。

默认：

- `--split-time`: 主测试集起点，例如 `2026-03-01`。
- 训练集：`observation_time < split_time`
- 测试集：`observation_time >= split_time`

### Walk-forward

新增参数：

```text
--walk-forward-period month
--min-train-samples 500
```

采用 expanding window：

1. 用测试窗口之前的全部样本训练。
2. 预测当前月份。
3. 输出该月份 Top 分层收益。
4. 滚动到下一个月份。

输出重点：

- 每个窗口样本数。
- 每个窗口正样本率。
- Top5% / Top10% / Top20% 平均收益。
- Top5% / Top10% / Top20% 扣成本后平均收益。
- Top 分层止损率、horizon 退出率。
- 固定阈值 `score >= 0.55 / 0.60 / 0.65` 的表现。

## 新增脚本计划

### 文件

新增：

```text
scripts/train_zs_gap_buy_rf.py
```

职责：

1. 读取 `backtest_zs_gap_buy.py` 输出的 CSV。
2. 解析 `previous_zs_json` 和 `latest_zs_json`。
3. 构造特征矩阵和标签。
4. 按时间切分训练/测试。
5. 训练随机森林模型。
6. 输出模型、特征元信息、样本明细、指标 JSON、特征重要性 CSV、Top 分层 CSV。

### CLI 参数

```text
--input-csv                 回测明细 CSV，可重复传入
--output-dir                输出目录，默认 outputs/zs_gap_buy_rf
--split-time                主测试集开始时间
--target-return-pct         正样本收益阈值，默认 2.0
--trade-cost-pct            单笔买卖合计成本，默认 0.1
--random-state              默认 42
--walk-forward              开启 walk-forward 验证
--walk-forward-period       默认 month
--score-thresholds          默认 0.55,0.60,0.65
--top-pcts                  默认 0.05,0.10,0.20,0.30
--model-kind                classifier 或 regressor，默认 classifier
```

### 输出文件

```text
outputs/zs_gap_buy_rf/
  model.pkl
  feature_meta.json
  metrics.json
  samples.csv
  scored_samples.csv
  feature_importance.csv
  top_buckets.csv
  walk_forward_metrics.json
  walk_forward_top_buckets.csv
```

## 扫描链路落地计划

模型验证通过后，再改扫描脚本，不在首期训练 PR 中直接改实盘筛选逻辑。

后续 `scripts/scan_zs_gap_buy.py` 增加：

```text
--model-path
--min-model-score
--model-feature-meta
```

扫描流程：

1. 原始规则先命中 `ZSGapBuyHit`。
2. 构造与训练一致的特征。
3. 加载模型打分。
4. 若 `score < min_model_score`，不输出或标记为低分。
5. 输出字段增加 `model_score`、`model_version`。

注意：只有 CSV 可提取特征才能直接用于扫描。如果训练中加入第二阶段行情特征，扫描端必须实现完全相同的 point-in-time 特征构造。

## 实施步骤

### 阶段 1：训练样本与计划落地

1. 固定 `backtest_zs_gap_buy.py` 的输出字段作为训练输入契约。
2. 新增 `scripts/train_zs_gap_buy_rf.py`。
3. 实现 JSON 中枢字段解析和基础特征构造。
4. 实现分类标签和扣成本收益字段。
5. 增加单元测试覆盖特征构造、标签构造、时间切分。

### 阶段 2：模型训练与指标输出

1. 实现 `RandomForestClassifier` 训练。
2. 输出主测试集指标：
   - AUC
   - Average Precision
   - 正样本率
   - Top 分层收益
   - 固定分数阈值收益
   - exit reason 分布
3. 输出特征重要性。
4. 增加小样本 smoke test，确保脚本能在少量 CSV 上跑通。

### 阶段 3：Walk-forward 验证

1. 实现按月 expanding window。
2. 输出每个窗口的 Top 分层表现。
3. 对比不同 `target_return_pct`、`horizon`、`level`。
4. 选出稳定阈值或 Top 分层策略。

### 阶段 4：接入扫描

1. 只有当 walk-forward Top20% 扣成本收益稳定优于全体样本时才接入扫描。
2. 扫描脚本增加模型加载和打分参数。
3. 输出数据库信号时保存模型分数。
4. 给看板或后续报表预留 `model_score` 字段。

## 验收标准

训练脚本：

- 能读取现有回测 CSV 并生成训练样本。
- 能在 `--model-kind classifier` 下完成训练并输出 `metrics.json`。
- `feature_importance.csv` 非空。
- `scored_samples.csv` 包含每条样本的 `score`。
- 核心训练特征默认使用百分比、比值或位置特征；`gap_abs` 等绝对值只作为诊断列保留。

模型效果：

- 主测试集 Top20% 扣成本后平均收益高于全体样本。
- walk-forward 至少两个测试窗口中，Top20% 扣成本后平均收益不显著劣于全体样本。
- Top 分层止损率不高于全体样本，或收益提升足以覆盖止损率上升。

代码质量：

- 不改变 `strategies/zs_gap_buy.py` 的原始规则语义。
- 不让训练标签或未来退出信息进入特征。
- 单元测试覆盖特征、标签、切分。

## 风险与注意事项

1. 样本量风险：双中枢抬高信号可能较少，按级别拆开后训练样本不足。
2. 标签偏差：`horizon=5` 可能过短，结构型信号收益释放可能需要更长窗口。
3. 未来函数风险：第二阶段行情特征必须严格使用 `observation_time` 之前的数据。
4. 过拟合风险：固定阈值在单月表现好不代表稳定，必须看 walk-forward。
5. 交易成本风险：A 股真实滑点、停牌、涨跌停未完全反映，模型收益需留安全边际。
6. 绝对值偏差风险：价格和中枢绝对宽度可能让模型学习股票价格档位，而不是结构质量；默认应使用相对值特征。

## 建议首轮实验命令

先生成 15M 样本：

```powershell
python scripts\backtest_zs_gap_buy.py --level 15M --all --begin 2025-01-01 --end 2026-05-24 --horizon 5 --workers 4 --output-dir outputs\zs_gap_buy_rf_source
```

再训练：

```powershell
python scripts\train_zs_gap_buy_rf.py --input-csv outputs\zs_gap_buy_rf_source\15m_zs_gap_buy_rows_*.csv --split-time 2026-03-01 --target-return-pct 2.0 --trade-cost-pct 0.1 --walk-forward --output-dir outputs\zs_gap_buy_rf
```

若 15M 样本不足，再追加 30M：

```powershell
python scripts\backtest_zs_gap_buy.py --level 30M --all --begin 2025-01-01 --end 2026-05-24 --horizon 5 --workers 4 --output-dir outputs\zs_gap_buy_rf_source_30m
```
