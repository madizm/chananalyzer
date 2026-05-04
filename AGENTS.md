# AGENTS.md

Guidance for agentic coding assistants working in `chananalyzer`.

## Project Overview

- Core Chan theory engine code is in top-level modules: `Bi/`, `Seg/`, `ZS/`, `KLine/`, `Math/`, `Plot/`, `Combiner/`, `BuySellPoint/`, `Common/`, `DataAPI/`.
- Higher-level orchestration and app-facing APIs live in `ChanAnalyzer/`, `web/`, `App/`, `scripts/`, `strategies/`.
- 核心算法链路：`原始K线(CKLine_Unit) -> 合并K线(CKLine) -> 分型 -> 笔(CBi) -> 线段(CSeg) -> 中枢(CZS) -> 买卖点(CBS_Point)`。

## Core Architecture

### 1. 总调度：`Chan.py::CChan`

`CChan` 是缠论引擎入口，负责数据源选择、多级别递归加载、父子级别 K 线对齐、触发/回放模式和结果访问。

**关键成员变量**

- `code`, `begin_time`, `end_time`, `autype`, `data_src`: 标的、时间范围、复权和数据源。
- `lv_list: List[KL_TYPE]`: 周期列表，必须从高到低，例如 `[K_DAY, K_60M]`。
- `conf: CChanConfig`: 全局配置，内含笔/线段/中枢/买卖点/指标配置。
- `kl_datas: Dict[KL_TYPE, CKLine_List]`: 每个级别一套完整结构容器。
- `g_kl_iter: defaultdict(list)`: 各级别 K 线迭代器队列，可追加多个输入流。
- `klu_cache`, `klu_last_t`: 递归加载时的跨级别缓存和时间单调性检查。
- `kl_misalign_cnt`, `kl_inconsistent_detail`: 父子级别时间对齐/一致性异常统计。

**关键方法**

- `do_init()`: 为每个级别创建 `CKLine_List`。
- `GetStockAPI()`: 根据 `DATA_SRC` 或 `custom:package.Class` 获取数据源类。
- `load()`: 初始化数据源，创建各级别迭代器，调用 `load_iterator()`，非 step 模式最后统一计算线段/中枢/买卖点。
- `load_iterator(lv_idx, parent_klu, step)`: 核心递归加载逻辑；读取当前级别 KLU、写入 `CKLine_List`、建立父子级别关系，再递归加载子级别。
- `trigger_load(inp)`: 外部传入 `{KL_TYPE: [CKLine_Unit, ...]}` 的增量触发入口。
- `step_load()`: 回放模式生成每步快照。
- `add_new_kl()`, `set_klu_parent_relation()`, `check_kl_align()`, `check_kl_consitent()`: 数据写入和多级别校验。
- `__getitem__(KL_TYPE|int)`: 获取某级别 `CKLine_List`。
- `get_latest_bsp()`: 获取最新买卖点。
- `chan_dump_pickle()`, `chan_load_pickle()`: 序列化/恢复，恢复时重建 `pre/next` 链。

### 2. 配置中心：`ChanConfig.py::CChanConfig`

`CChanConfig` 统一解析配置并拒绝未知参数。

**关键成员变量**

- `bi_conf: CBiConfig`: 成笔算法、严格度、分型有效性、缺口、端点峰值规则。
- `seg_conf: CSegConfig`: 线段算法与尾部虚线段处理方式。
- `zs_conf: CZSConfig`: 中枢构造、合并和跨段策略。
- `bs_point_conf`, `seg_bs_point_conf`: 普通笔级买卖点和线段级买卖点配置。
- `trigger_step`, `skip_step`: 实时/回放模式。
- `kl_data_check`, `max_kl_misalgin_cnt`, `max_kl_inconsistent_cnt`, `auto_skip_illegal_sub_lv`: 多级别数据检查。
- `mean_metrics`, `trend_metrics`, `macd_config`, `boll_n`, `cal_demark`, `cal_rsi`, `cal_kdj`: 指标配置。

**关键方法**

- `GetMetricModel()`: 为每个 `CKLine_List` 创建独立指标状态机列表，默认包含 MACD 和 BOLL，可按配置加入均线、趋势、Demark、RSI、KDJ。
- `set_bsp_config()`: 解析买卖点配置，并支持 `xxx-buy` / `xxx-sell` / `xxx-segbuy` / `xxx-segsell` / `xxx-seg` 方向或层级覆盖。

### 3. K线层：`KLine/`

#### `KLine/KLine_Unit.py::CKLine_Unit`

最小行情数据单元，只承载单根 K 线数据、指标和多级别关系，不放高层结构判定。

**关键成员变量**

- `kl_type`, `idx`, `time`, `open`, `high`, `low`, `close`。
- `trade_info: CTradeInfo`: 成交量、成交额、换手率等扩展交易字段。
- `macd`, `boll`, `demark`, `rsi`, `kdj`, `trend`: 指标结果，部分字段按配置动态挂载。
- `sub_kl_list`, `sup_kl`: 子级别和父级别 KLU。
- `klc`: 所属合并 K 线 `CKLine`。
- `pre`, `next`: 同级别 KLU 链。

**关键方法**

- `check(autofix=False)`: 校验 OHLC 合法性。
- `set_metric(metric_model_lst)`: 更新所有指标模型并把结果挂到当前 KLU。
- `add_children()`, `set_parent()`, `get_children()`, `get_parent_klc()`, `include_sub_lv_time()`: 多级别关系维护。
- `set_pre_klu()`: 建立同级别前后链。

#### `KLine/KLine.py::CKLine`

合并 K 线，继承 `Combiner.KLine_Combiner`，由一个或多个 `CKLine_Unit` 组成。

**关键成员变量**

- `idx`, `kl_type`, `lst`, `dir`, `fx`, `high`, `low`, `time_begin`, `time_end`, `pre`, `next`。

**关键方法**

- `try_add(klu)`: 根据包含关系尝试合并 KLU。
- `update_fx(pre, next)`: 用前后合并 K 线更新当前分型（顶/底/未知）。
- `check_fx_valid(item2, method, for_virtual=False)`: 成笔前的分型有效性校验。
- `GetSubKLC()`: 遍历子级别合并 K 线。
- `get_high_peak_klu()`, `get_low_peak_klu()`, `has_gap_with_next()`。

#### `KLine/KLine_List.py::CKLine_List`

单级别完整结构容器，是每根新 KLU 进入算法后的主要处理点。

**关键成员变量**

- `lst: List[CKLine]`: 合并 K 线列表。
- `bi_list: CBiList`: 笔列表。
- `seg_list: CSegListComm[CBi]`: 笔级线段。
- `segseg_list: CSegListComm[CSeg]`: 线段的线段。
- `zs_list`, `segzs_list`: 笔级中枢和线段级中枢。
- `bs_point_lst`, `seg_bs_point_lst`: 笔级与线段级买卖点。
- `metric_model_lst`: 本级别指标状态机。
- `step_calculation`, `last_sure_seg_start_bi_idx`, `last_sure_segseg_start_bi_idx`: 增量重算边界。

**关键方法**

- `add_single_klu(klu)`: 指标计算、K 线合并、分型更新、笔更新；step 模式下增量计算后续结构。
- `cal_seg_and_zs()`: `笔 -> 线段 -> 中枢 -> 线段的线段 -> 线段级中枢 -> 买卖点` 的统一入口。
- `klu_iter()`: 遍历原始 KLU。
- 模块函数 `cal_seg()` 和 `update_zs_in_seg()` 负责线段归属和中枢挂接。

### 4. 合并器：`Combiner/`

- `CKLine_Combiner[T]`: 通用包含关系合并器，支持 `CKLine_Unit`、`CBi`、`CSeg` 这类有高低点的元素。
- 关键成员：`lst`, `high`, `low`, `dir`, `fx`, `pre`, `next`, `time_begin`, `time_end`。
- 关键方法：`test_combine()`, `try_add()`, `update_fx()`, `get_peak_klu()`。
- `CCombine_Item`: 适配器，把 `CKLine_Unit`、`CBi`、`CSeg` 统一暴露为 `time_begin/time_end/high/low`。

### 5. 笔层：`Bi/`

#### `Bi/Bi.py::CBi`

表示一笔，连接两个有效分型合并 K 线。

**关键成员变量**

- `begin_klc`, `end_klc`, `idx`, `dir`, `type`, `is_sure`, `sure_end`。
- `seg_idx`, `parent_seg`: 所属线段索引和对象。
- `bsp`: 该笔尾部关联的买卖点。
- `pre`, `next`: 笔链。

**关键方法**

- `set()`, `update_new_end()`, `update_virtual_end()`, `restore_from_virtual_end()`。
- `get_begin_val()`, `get_end_val()`, `get_begin_klu()`, `get_end_klu()`, `_high()`, `_low()`, `amp()`。
- `is_up()`, `is_down()`。
- `cal_macd_metric(macd_algo, is_reverse)`: 买卖点背驰度量入口，支持 MACD 峰值/面积/斜率/振幅/成交量/RSI 等。

#### `Bi/BiList.py::CBiList`

维护笔序列和成笔逻辑。

**关键成员变量**

- `bi_list`, `last_end`, `config`, `free_klc_lst`。

**关键方法**

- `update_bi(klc, last_klc, cal_virtual)`: 外部更新入口。
- `update_bi_sure()`: 处理确定分型产生/更新确定笔。
- `try_add_virtual_bi()`, `delete_virtual_bi()`: 尾部虚笔处理。
- `try_create_first_bi()`, `can_make_bi()`, `satisfy_bi_span()`, `try_update_end()`, `update_peak()`。
- `end_is_peak()` 模块函数用于笔端极值约束。

### 6. 线段层：`Seg/`

#### `Seg/Seg.py::CSeg[LINE_TYPE]`

泛型线段，可由 `CBi` 组成，也可由下一级 `CSeg` 组成（线段的线段）。

**关键成员变量**

- `idx`, `start_bi`, `end_bi`, `dir`, `is_sure`, `reason`。
- `zs_lst`: 该线段内部中枢。
- `eigen_fx`: 线段特征序列分型。
- `seg_idx`, `parent_seg`, `pre`, `next`, `bsp`。
- `bi_list`: 线段内部元素列表；元素可能是笔或线段。
- `support_trend_line`, `resistance_trend_line`, `ele_inside_is_sure`。

**关键方法**

- `check()`, `update_bi_list()`, `add_zs()`, `clear_zs_lst()`。
- `is_up()`, `is_down()`, `get_begin_val()`, `get_end_val()`, `get_begin_klu()`, `get_end_klu()`。
- `cal_macd_metric()`: 线段级买卖点只支持 `slope` / `amp`。
- `get_first_multi_bi_zs()`, `get_final_multi_bi_zs()`, `get_multi_bi_zs_cnt()`。

#### `Seg/SegListComm.py` / `Seg/SegListChan.py`

- `CSegListComm`: 线段列表抽象基类，提供尾部虚线段收集、首段拆分、添加线段、剩余笔处理等通用逻辑。
- `CSegListChan`: 默认 `seg_algo="chan"` 实现，使用 `CEigenFX` 特征序列分型确认线段；`do_init()` 会删除尾部不确定线段后重算。
- 旧实现 `SegListDYH`、`SegListDef` 分别对应 `seg_algo="1+1"`、`seg_algo="break"`，代码已提示 deprecated。

### 7. 中枢层：`ZS/`

#### `ZS/ZS.py::CZS[LINE_TYPE]`

中枢由一组笔/线段重叠区间构成。

**关键成员变量**

- `begin`, `end`: 起止 KLU。
- `begin_bi`, `end_bi`: 中枢内部起止元素。
- `low`, `high`, `mid`: 中枢区间。
- `peak_low`, `peak_high`: 中枢涉及元素的峰值区间。
- `bi_in`, `bi_out`: 进/出中枢元素。
- `bi_lst`: 中枢内部元素列表。
- `sub_zs_lst`, `is_sure`。

**关键方法**

- `update_zs_range()`, `update_zs_end()`, `try_add_to_end()`。
- `combine(zs2, combine_mode)`: 按 `zs` 或 `peak` 模式合并中枢。
- `is_divergence(config, out_bi=None)`: 1 类买卖点背驰判断核心。
- `end_bi_break()`, `out_bi_is_peak()`, `is_inside()`。

#### `ZS/ZSList.py::CZSList`

维护中枢序列和增量重算边界。

**关键成员变量**

- `zs_lst`, `free_item_lst`, `last_sure_pos`, `last_seg_idx`, `config`。

**关键方法**

- `cal_bi_zs(bi_lst, seg_lst)`: 中枢计算主入口，支持 `normal`、`over_seg`、`auto`。
- `add_zs_from_bi_range()`, `try_construct_zs()`, `update_overseg_zs()`, `try_combine()`。

### 8. 买卖点层：`BuySellPoint/`

#### `BS_Point.py::CBS_Point`

买卖点对象，挂在对应笔/线段尾部。

**关键成员变量**

- `bi`: 触发买卖点的笔/线段。
- `klu`: `bi.get_end_klu()`。
- `is_buy`: `bi.is_down()` 为买点，`bi.is_up()` 为卖点。
- `type: List[BSP_TYPE]`: 支持同一位置叠加多种类型。
- `relate_bsp1`: 关联的一类买卖点。
- `features: CFeatures`: 扩展特征，如 `divergence_rate`。
- `is_segbsp`: 是否线段级买卖点。

#### `BSPointList.py::CBSPointList`

买卖点列表和判定逻辑。

**关键成员变量**

- `bsp_store_dict`: 按类型和买/卖方向保存。
- `bsp_store_flat_dict`: 按 `bi.idx` 去重。
- `bsp1_list`, `bsp1_dict`: 一类/盘整背驰买卖点索引，用于二/三类跟随。
- `config`, `last_sure_pos`, `last_sure_seg_idx`。

**关键方法**

- `cal(bi_list, seg_list)`: 清理尾部不确定结果后计算 1/2/3 类买卖点。
- `add_bs()`: 去重、过滤目标类型、创建或合并买卖点。
- `cal_single_bs1point()`, `treat_bsp1()`, `treat_pz_bsp1()`。
- `treat_bsp2()`, `treat_bsp2s()`。
- `treat_bsp3_after()`、`treat_bsp3_before()`。
- `getSortedBspList()`, `get_latest_bsp()`。

### 9. 数据源层：`DataAPI/`

- 所有数据源继承 `DataAPI/CommonStockAPI.py::CCommonStockApi`。
- 必须实现：
  - `get_kl_data() -> Iterable[CKLine_Unit]`
  - `SetBasciInfo()`（代码沿用拼写）
  - `do_init()` / `do_close()` 类方法
- `CChan.GetStockAPI()` 支持内置 `BAO_STOCK`、`CCXT`、`CSV`、`AKSHARE`、`TUSHARE`、`CACHE_DB`、`TDX`，也支持 `data_src="custom:package.Class"` 动态加载 `DataAPI/package.py` 中的类。
- 数据源输出的 `CKLine_Unit` 必须时间递增，字段使用 `Common.CEnum.DATA_FIELD`，时间使用 `Common.CTime.CTime`。

### 10. 指标层：`Math/`

- 指标模型是有状态对象，每个级别独立实例化。
- 常见接口：`add(close)` 或 `update(...)`，返回当前 KLU 的指标对象/数值。
- 当前支持：`CMACD`、`BollModel`、`CTrendModel`、`CDemarkEngine`、`RSI`、`KDJ`。
- 接入路径：`CChanConfig.GetMetricModel()` 创建模型，`CKLine_Unit.set_metric()` 识别类型并挂载结果。

### 11. 绘图层：`Plot/`

- `PlotMeta.CChanPlotMeta` 将 `CKLine_List` 转成绘图元数据：K线、笔、线段、特征序列、中枢、买卖点。
- `PlotDriver.CPlotDriver` 使用 Matplotlib 绘制；配置解析支持字符串、列表、单级/多级字典。
- 扩展绘图时优先复用 `PlotMeta`，不要直接耦合底层算法对象。

### 12. 应用层：`ChanAnalyzer/`

- `ChanAnalyzer.analyzer.ChanAnalyzer`: 面向业务的封装，默认使用 `DATA_SRC.TUSHARE`，输出结构化 dict 和文本摘要。
- `MultiChanAnalyzer`: 默认周线 + 日线多周期分析。
- `DataManager`: SQLite K线缓存与增量更新，负责 `KLineData <-> CKLine_Unit` 转换。
- `AIAnalyzer` / `multi_ai_analyzer`: 将结构化分析结果格式化给 AI 服务。
- `formatter`, `stock_info`, `stock_pool`, `sector_flow`: 报告格式化、股票信息/池、板块与资金流辅助模块。

## Component Relationships

```text
CChan
  ├─ CChanConfig
  │   ├─ CBiConfig / CSegConfig / CZSConfig
  │   └─ CBSPointConfig + Metric models
  ├─ DataAPI.CCommonStockApi -> CKLine_Unit stream
  └─ kl_datas[KL_TYPE] -> CKLine_List
        ├─ lst: CKLine[] -> CKLine_Unit[]
        ├─ bi_list: CBiList -> CBi[]
        ├─ seg_list: CSegListComm[CBi] -> CSeg[CBi][]
        ├─ zs_list: CZSList[CBi]
        ├─ segseg_list: CSegListComm[CSeg]
        ├─ segzs_list: CZSList[CSeg]
        ├─ bs_point_lst: CBSPointList[CBi]
        └─ seg_bs_point_lst: CBSPointList[CSeg]
```

多级别关系由 `CKLine_Unit.sup_kl` / `sub_kl_list` 建立；同级时序关系由 `pre` / `next` 链建立。`CChan.load_iterator()` 是这些关系的主要维护者。

## Extension Points

1. **新增数据源**
   - 在 `DataAPI/` 下新增类继承 `CCommonStockApi`。
   - 实现 `get_kl_data()` 生成 `CKLine_Unit`，保证时间严格递增。
   - 在 `CChan.GetStockAPI()` 增加枚举分支，或使用 `data_src="custom:xxx.YourApi"`。

2. **新增指标**
   - 在 `Math/` 实现状态模型。
   - 在 `CChanConfig.GetMetricModel()` 按配置创建。
   - 在 `CKLine_Unit.set_metric()` 挂载指标结果；如需 deepcopy，同步更新 `__deepcopy__()`。
   - 若买卖点力度需要使用新指标，在 `Common.CEnum.MACD_ALGO`、`BSPointConfig.SetMacdAlgo()`、`CBi.cal_macd_metric()` 中补充分支。

3. **新增/替换成笔规则**
   - 首选扩展 `CBiConfig` 参数和 `CBiList.can_make_bi()` / `satisfy_bi_span()` / `check_fx_valid()`。
   - 注意虚笔逻辑：`try_add_virtual_bi()`、`delete_virtual_bi()` 会影响 step 模式和尾部信号。

4. **新增线段算法**
   - 新建 `SegListXxx(CSegListComm)` 并实现 `update(bi_lst)`。
   - 在 `KLine/KLine_List.py::get_seglist_instance()` 注册 `seg_algo`。
   - 保持 `CSeg.update_bi_list()`、`parent_seg`、`pre/next`、`is_sure` 语义一致。

5. **新增中枢算法**
   - 扩展 `CZSConfig.zs_algo` 和 `CZSList.cal_bi_zs()` / `try_construct_zs()`。
   - 保证 `update_zs_in_seg()` 能正确设置 `bi_in`、`bi_out`、`bi_lst`。

6. **新增买卖点类型或特征**
   - 扩展 `Common.CEnum.BSP_TYPE` 和 `CPointConfig.parse_target_type()`。
   - 在 `CBSPointList.cal()` 中加入计算分支。
   - 使用 `CBS_Point.features` 保存额外特征，避免新增大量顶层字段。

7. **新增业务输出/API**
   - 优先基于 `ChanAnalyzer.analyzer.ChanAnalyzer.get_analysis()` 或直接读取 `CChan[lv]` 的结构对象。
   - 不要在业务层修改底层 `pre/next`、`parent_seg`、`bsp` 等结构关系。

8. **新增绘图能力**
   - 优先扩展 `PlotMeta` 的元数据对象，再在 `PlotDriver` 或 Web 前端中渲染。

## Development Notes

- 周期列表必须从大到小，入口会调用 `check_kltype_order()`。
- `trigger_step=True` 时每根顶级 K 线触发一次结构计算；非 step 模式在全部加载完成后统一调用 `cal_seg_and_zs()`。
- 尾部未确认结构会被反复删除和重算；修改线段/中枢/买卖点逻辑时要关注 `last_sure_pos`、`last_sure_seg_idx`、`is_sure`。
- `CBi.is_down()` 对应买点，`CBi.is_up()` 对应卖点，是买卖点方向判定的核心约定。
- 配置解析会删除已消费 key，未知参数会抛出 `CChanException(PARA_ERROR)`。
- 交易字段统一放在 `CTradeInfo.metric`，字段名来自 `Common.CEnum.DATA_FIELD` / `TRADE_INFO_LST`。

## TODO

- [] 配置背离度数
- [] 在线画图
