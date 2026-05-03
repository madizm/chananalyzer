# ChanAnalyzer 算法说明

本文档整理项目中与缠论算法相关的核心逻辑，包括：计算流程、买卖点定义、配置参数、结构化输出字段。

## 1. 核心算法链路

项目核心是分层结构识别与信号判定：

`K线 -> 分型 -> 笔 -> 线段 -> 中枢 -> 买卖点`

对应核心模块：

- `Chan.py`：`CChan` 总调度（多级别数据加载、递归推进、触发计算）
- `KLine/KLine_List.py`：K线合并、分型更新、结构计算入口
- `Bi/BiList.py`：成笔规则（严格/非严格、峰值更新、虚笔）
- `Seg/SegListChan.py`：`seg_algo="chan"` 线段识别
- `ZS/ZSList.py`：中枢构造与合并
- `BuySellPoint/BSPointList.py`：1/1p/2/2s/3a/3b 买卖点判定

## 2. 主流程（按调用顺序）

1. `CChan.__init__` 初始化后调用 `load()`（非 step 模式）
2. `load()` 内部选择数据源并初始化多周期迭代器
3. `load_iterator()` 递归读取各级别 K 线并调用 `add_new_kl()`
4. `CKLine_List.add_single_klu()` 执行：
   - K 线合并与分型更新
   - `bi_list.update_bi()` 生成/更新笔
   - step 模式下增量触发 `cal_seg_and_zs()`
5. 非 step 模式在全部数据加载完后统一执行 `cal_seg_and_zs()`：
   - `cal_seg(...)`：笔 -> 线段
   - `zs_list.cal_bi_zs(...)`：线段内中枢
   - `update_zs_in_seg(...)`：将中枢挂接到线段
   - `bs_point_lst.cal(...)`：计算买卖点

## 3. 买卖点定义（代码口径）

枚举定义见 `Common/CEnum.py`：`1`、`1p`、`2`、`2s`、`3a`、`3b`。

- 方向判定：
  - `bi.is_down() == True` 记为买点
  - `bi.is_up() == True` 记为卖点

- `1` 类（`T1`）：
  - 基于段末与中枢关系
  - 背驰判定核心：`zs.is_divergence(...)`
  - 可选破峰约束：`bs1_peak`

- `1p` 类（`T1P`）：
  - 盘整背驰分支
  - 通过前后笔的 MACD 度量比较判定

- `2` 类（`T2`）：
  - 常规为 1 类后回抽确认
  - 回撤比例：`retrace_rate <= max_bs2_rate`
  - 可配置是否必须跟随 1 类：`bsp2_follow_1`

- `2s` 类（`T2S`）：
  - 在 2 类基础上的延展类二
  - 需满足区间重叠且不破坏关键高低点

- `3a` 类（`T3A`）：
  - 中枢位于 1 类之后（after）
  - 需满足不回中枢（`bsp3_back2zs`）
  - 可选峰值约束：`bsp3_peak`

- `3b` 类（`T3B`）：
  - 中枢位于 1 类之前（before）
  - 同样要求不回中枢，受 `strict_bsp3` 等参数影响

实现入口：`BuySellPoint/BSPointList.py::CBSPointList.cal`

## 4. CChanConfig 参数

定义见 `ChanConfig.py`，下表说明项目默认值、可选值以及各取值含义。默认值以 `CChanConfig` 为准。

### 4.1 笔相关

| 参数 | 默认值 | 可选值 | 含义 |
| --- | --- | --- | --- |
| `bi_algo` | `normal` | `normal` / `fx` | 成笔算法。`normal` 会检查分型有效性、笔跨度和笔端峰值；`fx` 只按一顶一底/一底一顶分型成笔，跳过跨度约束，更敏感也更容易产生短笔。 |
| `bi_strict` | `true` | `true` / `false` | 仅在 `bi_algo="normal"` 下影响跨度。`true` 要求合并K线索引跨度至少 4；`false` 要求跨度至少 3，且中间原始K线数量至少 3。 |
| **bi_fx_check** | `strict` | `strict` / `loss` / `half` / `totally` | 分型有效性校验方式，见下方详细说明。 |
| `gap_as_kl` | `false` | `true` / `false` | 是否把相邻合并K线之间的缺口额外计入笔跨度。开启后，当普通跨度不足时，跳空缺口可补足跨度。 |
| `bi_end_is_peak` | `true` | `true` / `false` | 是否要求笔终点是从起点到终点区间内的极值：上笔终点不能被中途更高点超过；下笔终点不能被中途更低点超过。 |
| `bi_allow_sub_peak` | `true` | `true` / `false` | 是否允许次高/次低作为笔端。`true` 更宽松；`false` 会在后续出现更合适极值时尝试回退/更新笔端，使笔端更接近严格峰值。 |

`bi_fx_check` 各取值含义（代码入口：`KLine/KLine.py::CKLine.check_fx_valid`）：

| 取值 | 校验范围 | 含义与严格程度 |
| --- | --- | --- |
| `loss` | 只比较起点分型K线和终点分型K线 | 最宽松。只要求顶到底时“起点顶高于终点高、终点低低于起点低”；底到顶反向同理。 |
| `half` | 起点分型K线 + 起点后一根，终点分型K线 + 终点前一根 | 中等。除分型自身外，还检查起点后一根、终点前一根，避免只靠单根K线轻微突破成笔。 |
| `strict` | 起点分型前/中/后三根，终点分型前/中/后三根 | 默认且较严格。顶到底要求起点顶区域压过终点区域，且终点底区域跌破起点区域；底到顶反向同理。 |
| `totally` | 与 `strict` 使用相同三根K线范围，但要求两端区域完全不重叠 | 最严格。顶到底要求起点顶K线低点仍高于终点三根K线最高点；底到顶要求起点底K线高点仍低于终点三根K线最低点。 |

### 4.2 线段相关

| 参数 | 默认值 | 可选值 | 含义 |
| --- | --- | --- | --- |
| `seg_algo` | `chan` | `chan` / `1+1` / `break` | 线段识别算法。推荐使用 `chan`；`1+1` 与 `break` 代码中已标记为 deprecated，不建议新配置使用。 |
| `left_seg_method` | `peak` | `peak` / `all` | 未确认剩余笔如何收尾成虚线段。`peak` 会按剩余笔中的极值递归拆分，更保守；`all` 把剩余部分整体收成一个虚线段，可能更快给出结构，但注释中提示较容易影响二类买卖点识别。 |

### 4.3 中枢相关

| 参数 | 默认值 | 可选值 | 含义 |
| --- | --- | --- | --- |
| `zs_combine` | `true` | `true` / `false` | 是否尝试合并相邻中枢。合并只在同一线段内发生，单笔中枢不会被合并。 |
| `zs_combine_mode` | `zs` | `zs` / `peak` | 中枢合并判定。`zs`：两个中枢区间 `[low, high]` 有重叠即合并；`peak`：两个中枢涉及笔的峰值区间 `[peak_low, peak_high]` 有重叠即合并，通常比 `zs` 更宽松。 |
| `one_bi_zs` | `false` | `true` / `false` | 是否允许单笔构成中枢。`false` 时普通中枢至少由两笔重叠构造；`true` 时一笔也可临时形成中枢，信号更敏感但稳定性更弱。`zs_algo="over_seg"` 要求该项为 `false`。 |
| `zs_algo` | `normal` | `normal` / `over_seg` / `auto` | 中枢构造算法，见下方详细说明。 |

`zs_algo` 各取值含义（代码入口：`ZS/ZSList.py::CZSList.cal_bi_zs`）：

| 取值 | 含义 | 适用场景 |
| --- | --- | --- |
| `normal` | 按线段内部构造中枢。对每个线段，只取与线段方向相反的笔参与中枢生成；默认用最近两笔重叠形成中枢（`one_bi_zs=true` 时可一笔形成）。线段结束后，会对最新未成段部分按反向虚线段逻辑继续尝试。 | 最标准、默认推荐，结构稳定。 |
| `over_seg` | 跨线段构造中枢。不按每个线段清空计算，而是从上一个中枢之后开始滑动检查连续笔，通常需要最近三笔有重叠才生成；可处理跨越线段边界的中枢。 | 想识别跨段/未明确归属线段的中枢时使用；不支持 `one_bi_zs=true`。 |
| `auto` | 自动混合。已确认线段按 `normal` 计算；遇到最新未确认线段或尾部不稳定区域时，切换为 `over_seg` 逻辑。 | 希望已确认结构稳定、尾部结构更敏感时使用。 |

### 4.4 计算模式与数据检查

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `trigger_step` | `false` | 逐步回放模式。开启后每加入一根K线就触发结构计算，适合回放/实时场景；关闭时加载完成后统一计算。 |
| `skip_step` | `0` | step 模式下跳过前 N 步，常用于忽略预热阶段。 |
| `kl_data_check` | `true` | 是否检查多级别K线时间对齐与一致性。 |
| `max_kl_misalgin_cnt` | `2` | 允许的多级别对齐异常次数。参数名沿用代码拼写 `misalgin`。 |
| `max_kl_inconsistent_cnt` | `5` | 允许的父子级别时间不一致次数。 |
| `auto_skip_illegal_sub_lv` | `false` | 子级别数据非法时是否自动跳过，而不是直接报错中断。 |
| `print_warning` | `true` | 是否输出警告信息。 |
| `print_err_time` | `true` | 是否在异常信息中打印相关时间。 |

### 4.5 指标相关

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `macd` | `{fast: 12, slow: 26, signal: 9}` | MACD 参数。 |
| `mean_metrics` | `[]` | 需要计算的均线周期列表，例如 `[5, 10, 20]`。 |
| `trend_metrics` | `[]` | 需要计算的趋势通道周期列表，会同时计算对应周期的最高/最低趋势。 |
| `boll_n` | `20` | BOLL 周期。 |
| `cal_demark` + `demark` | `false` + 默认配置 | 是否计算 Demark 指标及其参数。 |
| `cal_rsi` + `rsi_cycle` | `false` + `14` | 是否计算 RSI 及周期。若买卖点 `macd_algo="rsi"`，需要开启 RSI。 |
| `cal_kdj` + `kdj_cycle` | `false` + `9` | 是否计算 KDJ 及周期。 |

### 4.6 买卖点参数

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `bs_type` | `1,1p,2,2s,3a,3b` | 启用的买卖点类型，支持字符串逗号分隔或列表。可选：`1`、`1p`、`2`、`2s`、`3a`、`3b`。 |
| **divergence_rate** | `inf` | 背驰阈值。`out_metric <= divergence_rate * in_metric` 视为背驰；大于 100 时等同“保送”，只要突破中枢即可通过背驰检查。 |
| `min_zs_cnt` | `1` | 触发 1 类买卖点前要求的最少中枢数量。 |
| `bsp1_only_multibi_zs` | `true` | 1 类买卖点是否只允许多笔中枢，排除单笔中枢。 |
| `max_bs2_rate` | `0.9999` | 2 类买卖点最大回撤比例，代码要求 `<= 1`。 |
| `macd_algo` | `peak` | 背驰力度度量方式，见下方取值说明。 |
| `bs1_peak` | `true` | 1 类买卖点出中枢一笔是否必须是相对峰值。 |
| `bsp2_follow_1` | `true` | 2 类买卖点是否必须跟随已有 1 类买卖点。 |
| `bsp3_follow_1` | `true` | 3 类买卖点是否必须跟随已有 1 类买卖点。 |
| `bsp3_peak` | `false` | 3 类买卖点是否要求离开/回抽相关笔满足峰值约束。 |
| `bsp2s_follow_2` | `false` | 2s 类买卖点是否必须跟随已有 2 类买卖点。 |
| `max_bsp2s_lv` | `None` | 2s 类买卖点最大递归层级；`None` 表示不限制。 |
| `strict_bsp3` | `false` | 是否使用更严格的 3 类买卖点判定。 |
| `bsp3a_max_zs_cnt` | `1` | 3a 类买卖点允许回看/关联的最大中枢数量，代码要求 `>= 1`。 |

`macd_algo` 各取值含义（用于背驰力度/笔力度比较）：

| 取值 | 含义 |
| --- | --- |
| `peak` | 笔内同向 MACD 柱绝对值峰值。默认值。 |
| `area` | 笔的后半段/反向比较口径下的同向 MACD 柱面积。 |
| `full_area` | 笔从起点到终点的同向 MACD 柱总面积。 |
| `diff` | 笔内 MACD 柱最大值与最小值之差。 |
| `slope` | 笔价格斜率；线段级买卖点默认强制使用该口径。 |
| `amp` | 笔价格振幅。 |
| `amount` | 笔内成交额合计。 |
| `volumn` | 笔内成交量合计。注意代码中沿用拼写 `volumn`。 |
| `amount_avg` | 笔内平均成交额。 |
| `volumn_avg` | 笔内平均成交量。 |
| `turnrate_avg` | 设计含义为笔内平均换手率；当前 `BSPointConfig` 中该字符串映射到 `amount_avg` 口径，使用前需注意实现差异。 |
| `rsi` | 使用 RSI 强弱作为力度；需要开启 `cal_rsi=true`。 |

此外支持方向/层级覆写：

- `xxx-buy`：只覆盖普通买点配置，例如 `divergence_rate-buy=0.8`。
- `xxx-sell`：只覆盖普通卖点配置。
- `xxx-segbuy`：只覆盖线段级买点配置。
- `xxx-segsell`：只覆盖线段级卖点配置。
- `xxx-seg`：同时覆盖线段级买点和卖点配置。

## 5. 结构化分析结果字段

参考 `ChanAnalyzer/analyzer.py::get_analysis()`。

### 5.1 顶层字段

- `code`：股票代码
- `name`：股票名称（当前默认与代码一致）
- `multi`：是否多周期结果
  - `false`：单周期，字段直接在顶层
  - `true`：多周期，详细结果在 `levels` 数组
- `levels`：多周期结果数组（`multi=true` 时存在）

### 5.2 单周期公共字段

- `kl_type`：周期名称（如 `日线`、`周线`）
- `kl_type_enum`：周期枚举对象（代码内使用）
- `start_date` / `end_date`：该周期分析时间范围
- `kline_count`：K线根数
- `current_price`：最新收盘价
- `macd`：最新K线 MACD 数据
  - `macd`：柱值
  - `dif`：DIF
  - `dea`：DEA

### 5.3 结构字段（重点）

#### `bi_list`（笔列表）

每个元素包含：

- `idx`：笔序号
- `dir`：方向
  - 在 `ChanAnalyzer.get_analysis()` 输出里：`向上` / `向下`
  - 在 `main.py` 的结构化输出里：`up` / `down`
- `start_date` / `end_date`：笔起止时间
- `start_price` / `end_price`：笔起止价格
- `is_sure`：是否确认笔
  - `true`：已确认，不会因后续K线轻易变化
  - `false`：未确认（虚笔/临时状态），后续可能被修正
- `macd`：笔终点对应 K 线的 MACD 值（`ChanAnalyzer` 输出包含）

#### `seg_list`（线段列表）

每个元素包含：

- `idx`：线段序号
- `dir`：方向（同上，`向上/向下` 或 `up/down`）
- `start_date` / `end_date`：线段起止时间
- `start_price` / `end_price`：线段起止价格
- `bi_count`：该线段包含的笔数量
- `is_sure`：是否确认线段
  - `true`：线段结构已确认
  - `false`：线段仍可能随新数据变化

#### `zs_list`（中枢列表）

每个元素包含：

- `idx`：中枢起始笔索引（便于定位）
- `start_date` / `end_date`：中枢时间范围
- `high` / `low`：中枢上沿/下沿
- `center`：中枢中轴（`(high+low)/2`）
- `bi_count`：中枢涉及笔数

### 5.4 买卖点字段

`buy_signals` 与 `sell_signals` 元素字段：

- `type`：买卖点类型（`1`、`1p`、`2`、`2s`、`3a`、`3b`）
- `type_raw`：原始类型对象（仅 `ChanAnalyzer` 输出）
- `is_buy`：是否买点
  - `true`：买点
  - `false`：卖点
- `date`：信号时间
- `price`：信号价格
- `klu_idx`：对应K线索引

### 5.5 状态与辅助字段

- `latest`：最新结构快照
  - `latest.bi`：最新一笔
  - `latest.seg`：最新线段
  - `latest.zs`：最新中枢
- `zs_position`：当前价格相对最新中枢位置
  - `中枢上方（强势）`
  - `中枢内部`
  - `中枢下方（弱势）`
  - `无中枢`
- `volume_analysis`：量价辅助分析
  - `current_vol`、`avg_vol`、`vol_ratio`、`vol_status`
  - `k_vol_price`：近5根K线量价组合描述
  - `vol_price_rel`：量价配合结论

### 5.6 字段取值说明（快速对照）

- 方向字段 `dir`：
  - `up` / `向上`：上行结构
  - `down` / `向下`：下行结构
- 确认字段 `is_sure`：
  - `true`：结构已确认
  - `false`：结构未确认，后续可能变化
- 买卖字段 `is_buy`：
  - `true`：买点
  - `false`：卖点
