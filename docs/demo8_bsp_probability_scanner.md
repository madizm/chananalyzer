# 30M 买卖点概率选股说明

本文档说明 `Debug/scan_bsp_probability.py` 统一入口，以及 `Debug/scan_demo8_bsp_probability.py`、`Debug/scan_demo9_bsp_probability.py` 单模型入口的核心思想、缠论依据、模型使用方式，以及选股结果如何解释。

## 1. 程序定位

这套程序不是传统意义上的“直接给出买入清单”的黑箱选股器，而是一个基于缠论结构的候选信号排序器。

它做的事情是：

- 在 30M 级别上扫描近期已经确认的笔。
- 对确认下笔计算“一买/盘背买点”的模型概率。
- 对确认上笔计算“一卖/盘背卖点”的模型概率。
- 输出候选信号、概率、关键特征和阈值命中情况。
- 将结果保存为 CSV、JSON，并写入数据库表，便于后续展示、复盘和跟踪。

程序默认只关心近期信号，`--recent-bars 48` 表示只扫描最近 48 根 30M K 线内出现的确认笔。这样更符合实盘选股的使用方式，避免历史信号干扰当前判断。

## 2. 核心思想

核心思想可以概括为一句话：

> 先用缠论结构定义“候选位置”，再用模型评估该候选位置成为一类买卖点的概率。

这和直接用行情指标扫描所有 K 线不同。程序不会对每根 K 线都打分，而是先等缠论结构给出一个相对明确的位置：

- 买点候选：30M 级别的确认下笔结束位置。
- 卖点候选：30M 级别的确认上笔结束位置。

也就是说，模型只在“结构上可能有意义”的位置工作。它不是预测任意时间点涨跌，而是在缠论已经形成候选结构后，判断这个候选结构是否更像历史上的 `1/1p` 买卖点。

这种设计有三个好处：

- 降低噪声：不在无结构的位置打分。
- 保持解释性：每个信号都能追溯到一笔、父级别环境、子级别状态和背驰特征。
- 贴近交易动作：输出的是近期可能需要观察或处理的买卖点候选，而不是泛泛的涨跌预测。

## 3. 缠论的运用方式

程序使用的是多级别缠论结构：

- 主级别：30M
- 父级别：DAY
- 子级别：15M

主级别用于确定候选笔，父级别用于判断大环境，子级别用于补充细节结构。

### 3.1 主级别 30M

30M 是模型训练和扫描的核心级别。

程序遍历 `30M` 的确认笔：

- `bi.is_down()` 的确认下笔，对应买点方向。
- `bi.is_up()` 的确认上笔，对应卖点方向。

这里的“确认笔”很重要。程序不会使用尾部未确认笔作为训练和扫描对象，因为未确认结构会随着后续 K 线变化而重算。只在确认笔上训练和扫描，可以减少结构漂移带来的噪声。

### 3.2 一类买卖点和盘背

当前模型目标是 `1/1p`：

- `1`：一类买卖点，通常和趋势背驰、段末结构相关。
- `1p`：盘整背驰买卖点。

买卖方向遵循项目内缠论约定：

- 下笔结束位置对应买点方向。
- 上笔结束位置对应卖点方向。

因此：

- `strategy_demo8_buy` 模型评估确认下笔是否像目标买点 `1/1p`。
- `strategy_demo8_sell` 模型评估确认上笔是否像目标卖点 `1/1p`。

### 3.3 父级别 DAY

DAY 父级别用于描述大环境。模型特征中会包含父级别的涨跌、波动、位置、换手率、最近买卖点等信息。

这解决的是一个很实际的问题：同样一个 30M 背驰结构，在日线强势、震荡、弱势环境中的意义不同。父级别特征让模型能够区分这种背景差异。

### 3.4 子级别 15M

15M 子级别用于补充短线细节，例如子级别结构数量、最新买卖点、子级别收盘位置等。

这部分主要帮助判断 30M 候选笔结束时，内部更小级别是否已经出现配合。例如，一个 30M 买点候选如果子级别收盘位置过低、短线结构仍弱，历史上更容易成为“高分但失败”的样本。

## 4. 模型依据

扫描器依赖 `strategy_demo8` 训练出的两个模型：

- `Debug/model_output/strategy_demo8_buy/model.pkl`
- `Debug/model_output/strategy_demo8_sell/model.pkl`

对应特征定义来自：

- `Debug/strategy_demo8.py::confirmed_bi_feature`
- `Debug/strategy_demo8.py::bi_matches_signal_side`
- `Debug/strategy_demo8.py::latest_previous_bsp`

扫描器复用训练时的特征构造逻辑，而不是重新写一套特征。这一点很关键，因为它保证了：

- 训练和扫描的特征口径一致。
- 模型输入字段和顺序由 `feature.meta.json` 控制。
- 后续训练新增特征后，扫描器可以继续使用同一套元数据。

## 5. 关键特征解释

扫描结果中会保留一组关键特征，帮助解释模型为什么给出较高或较低概率。

| 字段 | 含义 | 解读方式 |
| --- | --- | --- |
| `candidate_divergence_rate` | 候选笔与前同向笔的 MACD 峰值强弱比 | 买点中偏低常表示下跌力度衰竭，卖点中偏低常表示上涨力度衰竭 |
| `candidate_break_prev_extreme` | 候选笔是否突破前同向笔极值 | 买点为是否创新低，卖点为是否创新高 |
| `entry_close_pos` | 入场 30M K 线收盘在高低区间中的位置 | 买点中偏高通常更强，偏低说明承接不足 |
| `child_close_pos` | 15M 子级别收盘位置 | 用于观察更小级别是否配合主级别候选 |
| `parent_range` | 日线振幅 | 反映父级别波动环境，过大时可能代表风险较高 |
| `ma_dist_10` | 当前价格相对 10 周期均线距离 | 反映短期趋势位置 |
| `prev_bsp_divergence_rate` | 上一个买卖点的背驰强弱 | 用于判断前一个结构对当前结构的影响 |

这些字段不是单独的交易规则，而是解释模型评分时的重要线索。

## 6. 选股结果如何解释

扫描器输出的核心字段是 `probability`。

它的含义是：

> 在当前特征条件下，这个确认笔类似历史目标一类买卖点样本的概率。

它不表示：

- 未来上涨或下跌的确定概率。
- 一定可以买入或卖出的交易建议。
- 二类、三类买卖点概率。

当前模型只针对 `1/1p` 目标训练。因此：

- `signal_side=buy` 且高概率，表示这个确认下笔更像历史上的一买/盘背买点。
- `signal_side=sell` 且高概率，表示这个确认上笔更像历史上的一卖/盘背卖点。

默认阈值：

- `0.55`：开始具备观察价值。
- `0.60`：进入重点候选。
- `0.65`：高分候选，需要进一步人工复核。

阈值不是固定交易规则。它应该结合近期模型表现、行情阶段和人工复盘动态调整。

## 7. 可解释性路径

每条扫描结果都可以按以下路径解释：

1. 看 `signal_side`
   - `buy`：确认下笔候选买点。
   - `sell`：确认上笔候选卖点。

2. 看 `open_time`、`bi_idx`、`klu_idx`
   - 定位信号发生在哪一根 30M K 线、哪一笔。

3. 看 `probability`
   - 判断模型给出的排序强度。

4. 看 `candidate_divergence_rate`
   - 判断是否存在力度衰竭特征。

5. 看 `entry_close_pos` 和 `child_close_pos`
   - 判断当前 30M 和 15M 是否有足够的短线确认。

6. 看 `parent_range` 和 `ma_dist_10`
   - 判断父级别环境和短期趋势位置是否异常。

7. 看 `prev_bsp_divergence_rate`
   - 判断前一个买卖点结构是否可能影响当前信号质量。

这种路径让模型输出不只是一个分数，而是可以被交易者复盘、质疑和过滤的结构化判断。

## 8. 数据保存

扫描器默认将结果保存到三类位置。

### 8.1 CSV

- `signals_all.csv`：所有近期候选信号。
- `signals_filtered.csv`：达到 `--min-prob` 的候选信号。

### 8.2 JSON

- `summary.json`：本次扫描参数、股票数量、候选数量、失败股票、阈值统计等。

### 8.3 SQLite

默认写入 `chan.db`，可通过 `--db-path` 指定。

新扫描结果统一写入通用表：

- `bsp_probability_scan_runs`
- `bsp_probability_scan_signals`

运行表记录扫描参数和汇总。信号表记录每条候选买卖点的概率、阈值命中，并通过 `feature_snapshot_json` 保存解释特征。

旧版本曾写入过模型专用表，例如 `demo8_bsp_probability_scan_*` 和 `demo9_bsp_probability_scan_*`。这些旧表保留历史数据，新版本不再继续写入。

如果不希望写数据库，可以使用：

```powershell
python Debug\scan_demo8_bsp_probability.py --no-save-db
```

## 9. 常用命令

统一扫描一类和二类近期信号：

```powershell
python Debug\scan_bsp_probability.py --target-group first,second --all --begin-time 2026-04-01 --end-time 2026-05-10 --recent-bars 48 --min-prob 0.6 --workers 4 --output-dir Debug\model_output\bsp_probability_scan
```

统一入口会在总输出目录下生成合并版 `signals_all.csv`、`signals_filtered.csv`、`summary.json`，同时在 `first/`、`second/` 子目录保留各自的扫描结果。数据库仍写入同一组通用表，并用 `model_name`、`target_group` 区分一类、二类信号。

扫描全市场最近信号：

```powershell
python Debug\scan_demo8_bsp_probability.py --all --begin-time 2026-04-01 --end-time 2026-05-10 --recent-bars 48 --min-prob 0.6 --workers 4 --output-dir Debug\model_output\strategy_demo8_scan
```

只扫描买点：

```powershell
python Debug\scan_demo8_bsp_probability.py --all --signal-side buy --begin-time 2026-04-01 --recent-bars 48 --min-prob 0.6
```

只扫描卖点：

```powershell
python Debug\scan_demo8_bsp_probability.py --all --signal-side sell --begin-time 2026-04-01 --recent-bars 48 --min-prob 0.6
```

扫描全历史候选：

```powershell
python Debug\scan_demo8_bsp_probability.py --codes 000001,000002 --begin-time 2026-01-01 --recent-bars 0
```

## 10. 使用边界

这套程序的价值在于排序和筛选，不在于替代交易判断。

需要特别注意：

- 模型输出依赖训练样本和历史行情阶段，行情切换时可能失效。
- 高概率信号仍可能失败，需要结合风险控制和人工复核。
- 当前只识别 `1/1p`，不代表二类、三类买卖点概率。
- 扫描结果更适合作为候选池，而不是自动交易指令。
- 数据完整性会影响结果，尤其是 30M、15M、DAY 三个级别的数据覆盖。

比较稳妥的使用方式是：

1. 用扫描器生成近期高分候选池。
2. 在在线图中查看 30M 结构和概率标记。
3. 检查日线环境、15M 子结构和关键解释特征。
4. 结合止损、仓位和交易计划决定是否跟踪。

## 11. 后续优化方向

后续可以继续增强：

- 将扫描结果接入 web 页面，展示最新高分候选。
- 增加行业、题材、成交额和换手率过滤。
- 对高分失败样本继续做特征复盘，形成后置过滤规则。
- 分行情阶段维护不同阈值。
- 训练二类、三类买卖点模型，和当前一类模型形成多信号体系。
