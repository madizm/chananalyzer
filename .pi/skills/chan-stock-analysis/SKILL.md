---
name: chan-stock-analysis
description: Analyze specified A-share stocks with the project's Chan theory engine and 30M buy/sell probability scanners (demo8 first-class 1/1p, demo9 second-class 2/2s). Use when the user asks to analyze a stock, scan指定股票, 判断缠论买卖点, 一买/一卖/二买/二卖/盘背概率, or produce a Chan-based trading observation report.
---

# Chan Stock Analysis Skill

依据项目内缠论引擎和 30M 买卖点概率扫描器，对用户指定股票做缠论结构候选信号排序，并输出可解释的观察报告。

优先使用统一入口 `Debug/scan_bsp_probability.py`；如只需要一类买卖点，也可使用单模型入口 `Debug/scan_demo8_bsp_probability.py`。

## When to use

Use this skill when the user asks for any of:

- 分析指定股票的缠论结构或买卖点
- 扫描某些股票近期是否有一买/一卖/二买/二卖/盘背候选
- 给出 30M 买点/卖点概率、候选排序、关键特征解读
- 依据缠论判断某股票是否值得跟踪

## Core model/Chan basis

- 主级别：`30M`，用于定位确认笔候选。
- 父级别：`DAY`，用于判断大环境。
- 子级别：`15M`，用于补充短线结构。
- 买点候选：30M 确认下笔结束。
- 卖点候选：30M 确认上笔结束。
- `target_group=first`：`demo8`，目标 `1/1p`，即一类买卖点和盘整背驰买卖点。
- `target_group=second`：`demo9`，目标 `2/2s`，即二类买卖点；依赖前序 `1/1p` 结构特征。
- 概率含义：候选笔类似历史目标买卖点样本的概率，不是未来涨跌的确定概率。

## Required environment

- 本项目缓存数据库中已有对应股票的 `DAY`、`30M`、`15M` K 线数据。
- `chan.db` 中存在 `stock_info` 表，可用于把中文股票名解析为 6 位缓存代码，并在报告中补充名称、行业、地区。
- 一类模型文件存在：
  - `Debug/model_output/strategy_demo8_buy/model.pkl`
  - `Debug/model_output/strategy_demo8_sell/model.pkl`
  - 对应 `feature.meta.json`
- 如扫描二类信号，还需要：
  - `Debug/model_output/strategy_demo9_buy/model.pkl`
  - `Debug/model_output/strategy_demo9_sell/model.pkl`
  - 对应 `feature.meta.json`
- 在项目根目录运行命令。

## Standard workflow

1. Parse stock codes from user input.
   - Accept `000001`、`000001.SZ`、`sz.000001`、中文股票名、逗号分隔列表等。
   - 如果用户给出中文名，先通过 `stock_info` 表精确匹配 `name`，转换为 6 位 `code` 后再传给扫描器；避免直接把中文名传给底层扫描器导致“最高级别没有获得任何数据”。
   - 如果名称无法解析或匹配不唯一，先提示用户确认 `stock_info` 或改用 6 位代码，不要继续扫描。
   - 报告中使用 `stock_info` 补充股票名称、行业和地区。
2. Choose scan parameters.
   - 默认 `--target-group first,second`；用户只问一类/一买/一卖/盘背时用 `first`，只问二类/二买/二卖时用 `second`。
   - 默认 `--begin-time 2026-04-01`，必要时按用户要求调整；如果数据不足可放宽到更早日期。
   - 默认只看最近 `--recent-bars 48` 根 30M K 线。
   - 默认 `--signal-side both`，用户明确只看买点/卖点时改为 `buy` / `sell`。
   - 默认重点阈值 `--min-prob 0.60`。
3. Run helper script or scanner.
4. Read `signals_filtered.csv`、`signals_all.csv`、`summary.json`。
5. Produce a concise report: 结论、候选信号、概率、关键特征解释、风险边界。

## Helper command

Preferred helper for specified stocks:

```bash
python .pi/skills/chan-stock-analysis/scripts/analyze_chan_stock.py --codes 000001,600000 --target-group first,second --begin-time 2026-04-01 --recent-bars 48 --min-prob 0.6

# 也支持中文股票名，helper 会先查 chan.db:stock_info 转为缓存代码
python .pi/skills/chan-stock-analysis/scripts/analyze_chan_stock.py --codes 大元泵业,博杰股份 --target-group first --begin-time 2026-04-01 --recent-bars 48 --min-prob 0.6
```

Common variants:

```bash
# 只看一类买点
python .pi/skills/chan-stock-analysis/scripts/analyze_chan_stock.py --codes 000001 --target-group first --signal-side buy --min-prob 0.6

# 只看二类卖点
python .pi/skills/chan-stock-analysis/scripts/analyze_chan_stock.py --codes 000001 --target-group second --signal-side sell --min-prob 0.6

# 放宽观察阈值
python .pi/skills/chan-stock-analysis/scripts/analyze_chan_stock.py --codes 000001 --min-prob 0.55

# 扫描全历史候选
python .pi/skills/chan-stock-analysis/scripts/analyze_chan_stock.py --codes 000001 --recent-bars 0
```

Direct scanner commands if needed:

```bash
# 统一扫描一类和二类近期信号
python Debug/scan_bsp_probability.py --target-group first,second --codes 000001,600000 --begin-time 2026-04-01 --recent-bars 48 --min-prob 0.6 --workers 1 --output-dir Debug/model_output/bsp_probability_scan/manual

# 只跑一类 demo8
python Debug/scan_demo8_bsp_probability.py --codes 000001,600000 --begin-time 2026-04-01 --recent-bars 48 --min-prob 0.6 --workers 1 --output-dir Debug/model_output/strategy_demo8_scan/manual

# 只跑二类 demo9
python Debug/scan_demo9_bsp_probability.py --codes 000001,600000 --begin-time 2026-04-01 --recent-bars 48 --min-prob 0.6 --workers 1 --output-dir Debug/model_output/strategy_demo9_scan/manual
```

## Interpreting output

Use these thresholds as observation tiers:

- `>=0.55`：有观察价值。
- `>=0.60`：重点候选。
- `>=0.65`：高分候选，需要人工复核。

Explain key fields:

- `target_group=first`：一类/盘背目标，来自 `demo8`。
- `target_group=second`：二类目标，来自 `demo9`，要结合前序一类结构复核。
- `signal_side=buy`：30M 确认下笔候选买点。
- `signal_side=sell`：30M 确认上笔候选卖点。
- `probability`：类似历史目标买卖点样本的概率。
- `candidate_divergence_rate`：候选笔相对前同向笔的力度比，偏低通常代表力度衰竭。
- `candidate_break_prev_extreme`：买点看是否创新低，卖点看是否创新高。
- `entry_close_pos`：30M 入场 K 线收盘位置，买点偏高通常更强。
- `child_close_pos`：15M 子级别收盘位置，用于看短线是否配合。
- `parent_range`：日线振幅，过大提示父级别风险。
- `ma_dist_10`：价格相对 10 周期均线距离。
- `prev_bsp_divergence_rate`：上一个买卖点背驰强弱。
- 二类特征：`prev_first_bsp_exists`、`prev_first_bsp_bi_gap`、`prev_first_bsp_klu_gap`、`entry_vs_prev_first_bsp_price`、`retracement_from_prev_first`、`prev_first_bsp_divergence_rate` 用于解释当前二类候选与前序一类信号的距离、回撤和强弱关系。

## Data outputs

- CSV：`signals_all.csv` 保存所有近期候选，`signals_filtered.csv` 保存达到 `--min-prob` 的候选。
- JSON：`summary.json` 保存扫描参数、候选数量、失败股票、阈值统计等。
- SQLite：默认写入 `chan.db` 的通用表 `bsp_probability_scan_runs` 和 `bsp_probability_scan_signals`；可用 `--no-save-db` 禁止写入。
- 统一入口会在总输出目录生成合并版结果，并在 `first/`、`second/` 子目录保留各目标组的单独结果。

## Report template

```markdown
## 缠论概率扫描结论

- 股票：...
- 区间：...，范围：最近 ... 根 30M K 线
- 目标：first/second
- 结论：无高分候选 / 存在买点候选 / 存在卖点候选

### 候选信号
| 股票 | 目标 | 方向 | 时间 | 价格 | 概率 | 笔idx | 解读 |
| --- | --- | --- | --- | ---: | ---: | ---: | --- |
| ... |

### 关键解释
- 背驰力度：...
- 30M/15M 配合：...
- 日线环境：...
- 若为二类：前序一类距离、回撤和强弱关系：...

### 使用边界
该结果是候选排序，不是交易指令；需结合走势图、止损和仓位管理人工复核。
```

## Important cautions

- 不要把高概率解释为必涨/必跌。
- `first` 只覆盖 `1/1p`，`second` 只覆盖 `2/2s`，不代表所有缠论买卖点。
- 数据覆盖不足或缓存过旧会导致失败或误判。
- 尾部未确认结构不会作为候选，近期快速变化可能需要重新扫描。
- 扫描结果更适合作为候选池，不是自动交易指令。
