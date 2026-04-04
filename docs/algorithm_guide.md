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

定义见 `ChanConfig.py`，常用项如下。

### 4.1 笔相关

- `bi_algo`：成笔算法
- `bi_strict`：是否严格笔
- `bi_fx_check`：分型校验（`strict/loss/half/totally`）
- `gap_as_kl`：缺口是否按 K 线计入跨度
- `bi_end_is_peak`：笔终点是否要求峰值
- `bi_allow_sub_peak`：是否允许次级峰值更新

### 4.2 线段/中枢相关

- `seg_algo`：线段算法（默认 `chan`）
- `left_seg_method`：剩余线段处理方式（`peak/all`）
- `zs_combine`：是否合并中枢
- `zs_combine_mode`：中枢合并模式（如 `zs/peak`）
- `one_bi_zs`：是否允许单笔中枢
- `zs_algo`：中枢算法（`normal/over_seg/auto`）

### 4.3 计算模式与数据检查

- `trigger_step`：逐步回放模式
- `skip_step`：回放跳过步数
- `kl_data_check`：多级别一致性检查
- `max_kl_misalgin_cnt`：允许对齐异常次数
- `max_kl_inconsistent_cnt`：允许时间不一致次数
- `auto_skip_illegal_sub_lv`：子级别非法时自动跳过
- `print_warning` / `print_err_time`：日志开关

### 4.4 指标相关

- `macd`：MACD 参数（`fast/slow/signal`）
- `mean_metrics`、`trend_metrics`
- `boll_n`
- `cal_demark` + `demark`
- `cal_rsi` + `rsi_cycle`
- `cal_kdj` + `kdj_cycle`

### 4.5 买卖点参数

- `bs_type`：启用类型（如 `1,1p,2,2s,3a,3b`）
- `divergence_rate`
- `min_zs_cnt`
- `bsp1_only_multibi_zs`
- `max_bs2_rate`
- `macd_algo`
- `bs1_peak`
- `bsp2_follow_1`
- `bsp3_follow_1`
- `bsp3_peak`
- `bsp2s_follow_2`
- `max_bsp2s_lv`
- `strict_bsp3`
- `bsp3a_max_zs_cnt`

此外支持方向/层级覆写：`xxx-buy`、`xxx-sell`、`xxx-segbuy`、`xxx-segsell`、`xxx-seg`。

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
