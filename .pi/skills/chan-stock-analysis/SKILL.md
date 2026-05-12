---
name: chan-stock-analysis
description: Analyze specified A-share stocks with the project's Chan theory engine and demo8 30M 1/1p buy/sell probability scanner. Use when the user asks to analyze a stock, scan指定股票, 判断缠论买卖点, 一买/一卖/盘背概率, or produce a Chan-based trading observation report.
---

# Chan Stock Analysis Skill

依据项目内缠论引擎和 `Debug/scan_demo8_bsp_probability.py`，对用户指定股票做 30M 级别一类买卖点/盘整背驰概率分析，并输出可解释的观察报告。

## When to use

Use this skill when the user asks for any of:

- 分析指定股票的缠论结构或买卖点
- 扫描某些股票近期是否有一买/一卖/盘背候选
- 给出 30M 买点/卖点概率、候选排序、关键特征解读
- 依据缠论判断某股票是否值得跟踪

## Core model/Chan basis

- 主级别：`30M`，用于定位确认笔候选。
- 父级别：`DAY`，用于判断大环境。
- 子级别：`15M`，用于补充短线结构。
- 买点候选：30M 确认下笔结束。
- 卖点候选：30M 确认上笔结束。
- 模型目标：`1/1p`，即一类买卖点和盘整背驰买卖点。
- 概率含义：候选笔类似历史 `1/1p` 样本的概率，不是未来涨跌的确定概率。

## Required environment

- 本项目缓存数据库中已有对应股票的 `DAY`、`30M`、`15M` K 线数据。
- `chan.db` 中存在 `stock_info` 表，可用于把中文股票名解析为 6 位缓存代码，并在报告中补充名称、行业、地区。
- 模型文件存在：
  - `Debug/model_output/strategy_demo8_buy/model.pkl`
  - `Debug/model_output/strategy_demo8_sell/model.pkl`
  - 对应 `feature.meta.json`
- 在项目根目录运行命令。

## Standard workflow

1. Parse stock codes from user input.
   - Accept `000001`、`000001.SZ`、`sz.000001`、中文股票名、逗号分隔列表等。
   - 如果用户给出中文名，先通过 `stock_info` 表精确匹配 `name`，转换为 6 位 `code` 后再传给扫描器；避免直接把中文名传给底层扫描器导致“最高级别没有获得任何数据”。
   - 如果名称无法解析或匹配不唯一，先提示用户确认 `stock_info` 或改用 6 位代码，不要继续扫描。
   - 报告中使用 `stock_info` 补充股票名称、行业和地区。
2. Choose scan parameters.
   - 默认 `--begin-time 2026-01-01`，必要时按用户要求调整。
   - 默认只看最近 `--recent-bars 48` 根 30M K 线。
   - 默认 `--signal-side both`，用户明确只看买点/卖点时改为 `buy` / `sell`。
   - 默认重点阈值 `--min-prob 0.60`。
3. Run helper script or scanner.
4. Read `signals_filtered.csv`、`signals_all.csv`、`summary.json`。
5. Produce a concise report: 结论、候选信号、概率、关键特征解释、风险边界。

## Helper command

Preferred helper for specified stocks:

```bash
python .pi/skills/chan-stock-analysis/scripts/analyze_chan_stock.py --codes 000001,600000 --begin-time 2026-01-01 --recent-bars 48 --min-prob 0.6

# 也支持中文股票名，helper 会先查 chan.db:stock_info 转为缓存代码
python .pi/skills/chan-stock-analysis/scripts/analyze_chan_stock.py --codes 大元泵业,博杰股份 --begin-time 2026-01-01 --recent-bars 48 --min-prob 0.6
```

Common variants:

```bash
# 只看买点
python .pi/skills/chan-stock-analysis/scripts/analyze_chan_stock.py --codes 000001 --signal-side buy --min-prob 0.6

# 放宽观察阈值
python .pi/skills/chan-stock-analysis/scripts/analyze_chan_stock.py --codes 000001 --min-prob 0.55

# 扫描全历史候选
python .pi/skills/chan-stock-analysis/scripts/analyze_chan_stock.py --codes 000001 --recent-bars 0
```

Direct scanner command if needed:

```bash
python Debug/scan_demo8_bsp_probability.py --codes 000001,600000 --begin-time 2026-01-01 --recent-bars 48 --min-prob 0.6 --workers 1 --output-dir Debug/model_output/strategy_demo8_scan/manual
```

## Interpreting output

Use these thresholds as observation tiers:

- `>=0.55`：有观察价值。
- `>=0.60`：重点候选。
- `>=0.65`：高分候选，需要人工复核。

Explain key fields:

- `signal_side=buy`：30M 确认下笔候选买点。
- `signal_side=sell`：30M 确认上笔候选卖点。
- `probability`：类似历史一买/一卖/盘背样本的概率。
- `candidate_divergence_rate`：候选笔相对前同向笔的力度比，偏低通常代表力度衰竭。
- `candidate_break_prev_extreme`：买点看是否创新低，卖点看是否创新高。
- `entry_close_pos`：30M 入场 K 线收盘位置，买点偏高通常更强。
- `child_close_pos`：15M 子级别收盘位置，用于看短线是否配合。
- `parent_range`：日线振幅，过大提示父级别风险。
- `ma_dist_10`：价格相对 10 周期均线距离。
- `prev_bsp_divergence_rate`：上一个买卖点背驰强弱。

## Report template

```markdown
## 缠论概率扫描结论

- 股票：...
- 区间：...，范围：最近 ... 根 30M K 线
- 结论：无高分候选 / 存在买点候选 / 存在卖点候选

### 候选信号
| 股票 | 方向 | 时间 | 价格 | 概率 | 笔idx | 解读 |
| --- | --- | --- | ---: | ---: | ---: | --- |
| ... |

### 关键解释
- 背驰力度：...
- 30M/15M 配合：...
- 日线环境：...

### 使用边界
该结果是候选排序，不是交易指令；需结合走势图、止损和仓位管理人工复核。
```

## Important cautions

- 不要把高概率解释为必涨/必跌。
- 当前只覆盖 `1/1p`，不代表二类、三类买卖点。
- 数据覆盖不足或缓存过旧会导致失败或误判。
- 尾部未确认结构不会作为候选，近期快速变化可能需要重新扫描。
