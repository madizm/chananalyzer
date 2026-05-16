# 买卖点 point-in-time label 改造计划

## 背景

当前 demo8/demo9 的买卖点识别模型，label 是在完整 `begin/end` 区间跑完后生成的。

现有流程大致是：

1. 使用 `chan.step_load()` 跑完整段数据。
2. 读取最终状态下的 `level_chan.bs_point_lst.getSortedBspList()`。
3. 遍历最终确认笔。
4. 如果同一个 `bi.idx` 上存在目标买卖点，则 `label=1`，否则 `label=0`。

这会导致一个问题：缠论结构尾部会随着后续 K 线不断重算，某个历史买卖点可能在后续数据加入后消失、变更类型，或者挂载到不同的笔上。用最终结构回头给历史位置贴 label，会把未来信息引入历史样本。

最近在在线图中已经观察到类似现象：同一个 `2026/05/12 10:00` 的 marker，在 `end=2026-05-12` 和 `end=2026-05-13` 下概率不同。进一步排查发现，当前笔自身行情特征没有变化，变化来自最终结构重算后的 `prev_bsp_*` 上下文。

## 改造目标

将买卖点模型 label 从“最终结构视角”改为“当时可见结构视角”。

核心目标：

- 每个样本只使用 `decision_time` 当时已经可见的数据和结构。
- 历史样本的 label 一旦在 replay 中生成，不再被未来结构重算改写。
- 区分“当时是否识别为买卖点”和“后续是否稳定保留”两个不同任务。
- demo8 一类模型和 demo9 二类模型统一采用 point-in-time 采样框架。

## 核心概念

### signal_time

买卖点信号挂载的 K 线时间，也就是图上 marker 显示的位置。

例如某个买点挂在 `2026/05/12 10:00` 的确认下笔结束位置，则：

```text
signal_time = 2026/05/12 10:00
```

### decision_time

算法第一次能够在当前可见结构中识别或判断该候选笔的时间。

对于缠论结构，`decision_time` 通常晚于或等于 `signal_time`。训练特征和 label 必须以 `decision_time` 为准，不能用更晚数据。

### sample_key

为了避免 replay 中重复采样，需要为候选笔构造稳定 key。

建议使用：

```text
(code, signal_side, bi_begin_time, bi_end_time, bi_direction)
```

不要只使用 `bi.idx`，因为 `bi.idx` 在不同 replay 截面中可能因尾部结构重算出现偏移。

## 模型任务拆分

### 任务一：买卖点实时识别模型

回答的问题：

```text
在 decision_time 当时可见的 Chan 结构中，这根确认笔是否已经被算法识别为目标买卖点？
```

候选样本：

- 买点模型：当前截面中所有确认下笔。
- 卖点模型：当前截面中所有确认上笔。

label 规则：

```text
label = 1:
  当前 decision_time 的 as-of 结构中，
  同一根候选确认笔上存在目标 BSP，
  BSP 方向匹配，
  BSP 类型匹配，
  BSP 挂载笔为确认笔。

label = 0:
  当前 decision_time 的 as-of 结构中，
  候选确认笔已经可判断，
  方向匹配，
  但同一根候选确认笔上不存在目标 BSP。
```

demo8：

```text
target_bsp_types = 1,1p
```

demo9：

```text
target_bsp_types = 2,2s
dependency_bsp_types = 1,1p
```

这个任务不关心信号后续是否消失。只要当时结构中出现过目标 BSP，就应该记录当时的 `label=1`。

### 任务二：买卖点稳定性模型

回答的问题：

```text
当时已经出现的买卖点，后续是否稳定保留下来？
```

候选样本：

- 只包含任务一中 `label=1` 的样本。

label 规则可选：

```text
label = 1:
  经过固定观察窗口后，目标 BSP 仍存在，方向和类型仍匹配。

label = 0:
  固定观察窗口内，目标 BSP 消失、方向改变、类型改变，或挂载笔被重算掉。
```

观察窗口建议先做参数化：

- `--stability-bars 16`：观察后续 16 根 30M K 线。
- `--stability-bis 2`：观察后续 2 根确认笔。

第一阶段先实现任务一。任务二作为后续扩展，不和当前 demo8/demo9 主模型混在一起。

## 实施步骤

### 第一步：新增 replay 采样公共模块

新增文件：

```text
Debug/bsp_point_in_time_label.py
```

职责：

- 封装 point-in-time replay 采样逻辑。
- 提供统一的候选笔遍历、样本去重、label 生成、decision_time 记录。
- 支持 demo8/demo9 通过配置传入目标类型和特征构造函数。

核心数据结构建议：

```python
@dataclass(frozen=True)
class PointInTimeLabelConfig:
    model_name: str
    target_group: str
    target_bsp_types: tuple[str, ...]
    dependency_bsp_types: tuple[str, ...]
    main_bs_type: str
    build_chan: Callable
    build_feature: Callable
```

样本字段建议扩展：

```text
code
signal_side
signal_time
decision_time
bi_begin_time
bi_end_time
bi_direction
open_klu_idx
entry_price
label
feature
label_source = point_in_time
```

### 第二步：实现 as-of 采样逻辑

核心流程：

```python
seen = set()

for _ in chan.step_load():
    level_chan = chan[MODEL_LV_IDX]
    child_level_chan = chan[CHILD_LV_IDX]
    current_time = latest_loaded_klu.time

    final_klus = list(level_chan.klu_iter())
    sorted_bsp_list = level_chan.bs_point_lst.getSortedBspList()
    target_bsp_by_sample_key = build_current_target_bsp_map(...)

    for bi in level_chan.bi_list:
        if not bi.is_sure:
            continue
        if not bi_matches_signal_side(bi, target_is_buy):
            continue

        key = make_sample_key(code, signal_side, bi)
        if key in seen:
            continue

        if not candidate_is_decidable_now(bi, current_time):
            continue

        bsp = target_bsp_by_sample_key.get(key)
        label = 1 if bsp is not None else 0
        feature = build_feature_from_current_snapshot(...)
        save_sample(...)
        seen.add(key)
```

`candidate_is_decidable_now` 第一版可以定义为：

```text
bi.is_sure == True
且 bi.get_end_klu() 已经不在当前尾部未完成 K 线中
```

如果后续发现过早采样导致噪声较大，可以增加确认延迟参数：

```text
--decision-delay-bars N
```

含义是候选笔结束后至少经过 N 根主级别 K 线才采样。

### 第三步：改造 demo8

目标文件：

```text
Debug/strategy_demo8.py
```

改造点：

- 保留现有最终结构采样函数，短期可命名为 legacy。
- 新增参数：

```text
--label-mode point_in_time|final
```

默认建议改为：

```text
point_in_time
```

兼容评估时可保留：

```text
final
```

demo8 point-in-time label：

```text
label=1：decision_time 截面中，当前确认笔存在 1/1p 买卖点。
label=0：decision_time 截面中，当前确认笔不存在 1/1p 买卖点。
```

输出参数记录中新增：

```json
{
  "label_mode": "point_in_time",
  "label_decision_delay_bars": 0,
  "label_target_bsp_types": ["1", "1p"]
}
```

### 第四步：改造 demo9

目标文件：

```text
Debug/strategy_demo9.py
```

demo9 应复用同一个 point-in-time 采样模块。

demo9 point-in-time label：

```text
label=1：decision_time 截面中，当前确认笔存在 2/2s 买卖点。
label=0：decision_time 截面中，当前确认笔不存在 2/2s 买卖点。
```

特征中 `previous_first_bsp` 也必须来自同一个 `decision_time` 截面的 `sorted_bsp_list`，不能使用最终结构里的前序一类买卖点。

### 第五步：更新训练输出

训练输出中新增字段：

```text
decision_time
signal_time
bi_begin_time
bi_end_time
label_mode
label_source
```

CSV 样本导出应能区分：

- 图上信号时间：`signal_time`
- 实际判断时间：`decision_time`

metrics.json 中新增：

```json
{
  "label_mode": "point_in_time",
  "label_definition": "1 means target BSP exists in as-of structure at decision_time",
  "decision_delay_bars": 0,
  "target_bsp_types": ["1", "1p"]
}
```

### 第六步：验证 label 不回溯

设计一个固定回归测试场景：

```text
code = 002015
begin = 2026-01-13
end_a = 2026-05-12
end_b = 2026-05-13
signal_time = 2026/05/12 10:00
```

验证目标：

- 在 point-in-time 模式下，`end_a` 和 `end_b` 对同一个已采样样本的 `decision_time`、`label`、核心 feature 应一致。
- 如果 `end_b` 新增了更晚样本，只能追加新样本，不能改写旧样本。
- `prev_bsp_*`、`prev_first_bsp_*` 必须来自 `decision_time` 截面，而不是 `end_b` 最终截面。

建议新增 smoke 命令：

```powershell
python Debug\strategy_demo8.py --codes 002015 --begin-time 2026-01-13 --end-time 2026-05-12 --label-mode point_in_time --output-dir Debug\model_output\label_pit_0512

python Debug\strategy_demo8.py --codes 002015 --begin-time 2026-01-13 --end-time 2026-05-13 --label-mode point_in_time --output-dir Debug\model_output\label_pit_0513
```

然后对比：

```text
(code, signal_side, bi_begin_time, bi_end_time, bi_direction)
```

相同 key 的样本，label 和特征应稳定。

## 风险点

- `bi.idx` 不能作为跨截面的唯一标识，必须使用时间和方向组成 key。
- 尾部虚笔、未确认线段、中枢重算会影响候选是否首次可判断。
- 如果过早采样，可能把尚不稳定的确认笔纳入负例，导致噪声偏大。
- point-in-time 样本数量可能比最终结构样本更多，需要重新评估正负样本比例。
- 训练结果指标可能下降，但这是更真实的在线可用指标，不应和原最终结构指标直接横向比较。

## 验收标准

- demo8/demo9 均支持 `--label-mode point_in_time`。
- 默认训练输出记录 label 模式、目标类型、decision delay。
- 同一历史样本不会因为扩大 `end_time` 而被改写 label。
- 在线图中概率解释与训练 label 口径一致：模型学习的是当时结构下的识别概率，而不是未来最终结构。
- 保留旧 final 模式仅用于对照实验，不能作为默认在线模型训练口径。

## 后续扩展

- 新增稳定性模型，专门识别“当时出现但后续消失”的买卖点。
- 将扫描结果表增加 `decision_time`、`signal_time` 字段。
- 在线图 probability marker 增加 tooltip，展示模型 label 口径。
- 对比 final label 与 point-in-time label 的样本差异，定位最容易回溯变化的结构类型。

## 实施状态：2026-05-15

第一阶段已实施：

- 新增 `Debug/bsp_point_in_time_label.py`，封装 as-of replay 采样逻辑。
- `Debug/strategy_demo8.py` 支持 `--label-mode point_in_time|final`，默认 `point_in_time`。
- `Debug/strategy_demo9.py` 支持 `--label-mode point_in_time|final`，默认 `point_in_time`。
- 新增 `--decision-delay-bars` 参数，默认 `0`。
- `samples.csv` 新增 `decision_time`、`signal_time`、`bi_begin_time`、`bi_end_time`、`bi_direction`、`label_mode`、`label_source`。
- `metrics.json` 和 `run_config` 记录 `label_mode`、`label_source`、`label_decision_delay_bars`、`label_target_bsp_types`。

已验证：

- `002015` 在 `end=2026-05-12` 与 `end=2026-05-13` 下，point-in-time 模式共同样本的 `label`、`decision_time`、`feature` 保持一致。
- demo8 一类买点 point-in-time smoke training 通过。
- demo9 二类买点 point-in-time smoke training 通过。

尚未实施：

- 稳定性模型。
- final label 与 point-in-time label 的全量差异分析。

## 实施状态：2026-05-16

第二阶段已实施：

- `Debug/bsp_probability_scan_common.py` 的扫描 CSV 新增 `signal_time`、`decision_time`。
- 通用扫描表 `bsp_probability_scan_signals` 新增 `signal_time`、`decision_time` 字段，并对旧表做自动 `ALTER TABLE` 迁移。
- `web/signal_payload.py` 的信号时间过滤优先使用 `signal_time`。
- `web/static/signals.js` 在信号列表中展示 `signal_time`，并用 `title` 展示 `decision_time`。
- `web/bsp_probability.py` 的在线图概率 marker 改为 point-in-time replay 首次可见口径。
- 在线图 marker payload 新增 `signalTime`、`decisionTime`、`biBeginTime`、`biEndTime`、`biDirection`、`labelMode`、`labelSource`、`scoringMode`、`modelDir`、`tooltip`。

已验证：

- `002015` 的 `2026/05/12 10:00` 买点 marker 在 `end=2026-05-12` 与 `end=2026-05-13` 下概率一致。
- 上述 marker 的 `decisionTime` 固定为 `2026/05/12 10:30`，`scoringMode=point_in_time_replay`。
- 扫描脚本 smoke test 通过，CSV 与 SQLite 均包含 `signal_time`、`decision_time`。

尚未实施：

- 稳定性模型。
- final label 与 point-in-time label 的全量差异分析。
