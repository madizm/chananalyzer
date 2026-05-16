# Stability Model Feature Cleanup Plan

## 目标口径

stability 模型用于基于买卖点出现时的结构特征，预测该买卖点后续是否保留。

`decision_time` 只用于训练阶段生成 label，不应进入模型特征，也不应作为 scan/chart 概率解释的一部分。

scan 和 chart 应输出训练后的模型结果，不再依赖 `decision_time` 或 `stability_*` 上下文特征参与概率计算。

## 当前问题

现有 stability 训练样本把以下字段写入了 `sample.feature`：

- `stability_tail_distance_bars`
- `stability_tail_distance_bis`
- `stability_is_last_bi`
- `stability_is_in_last_seg`
- `stability_bsp_type_count`
- `stability_has_dependency_bsp`
- `stability_dependency_bsp_age_bars`
- `stability_seg_is_sure`
- `stability_zs_is_sure`
- `stability_distance_to_seg_end`

这些字段编码的是回放当前位置、尾部距离、当前线段状态等 as-of 上下文。它们会让模型学习训练回放位置或观察窗口副作用，而不是买卖点本身的稳定性。

## 实施步骤

0. 标准化候选背驰率特征

   文件：`Debug/strategy_demo8.py`

   `candidate_divergence_rate` 使用方案 A 直接替换原字段：

   ```python
   candidate_divergence_rate = log1p(clamp(raw_rate, 0, 20))
   ```

   其中 `raw_rate = out_metric / (in_metric + 1e-7)`。

   预期效果：

   - 保留单调性，背驰率越大，特征值越大。
   - 上限从无界压缩到 `log1p(20) ~= 3.0445`。
   - 不新增原始未压缩比值作为训练特征，避免极端值继续影响模型。

1. 修改训练采样

   文件：`Debug/bsp_point_in_time_label.py`

   在 `collect_bsp_stability_samples_for_code()` 中移除：

   ```python
   feature.update(stability_context_feature(...))
   ```

   `stability_*` 信息如需保留，只能作为样本审计元数据，不能进入 `sample.feature`。

2. 检查训练脚本特征来源

   文件：

   - `Debug/strategy_demo8.py`
   - `Debug/strategy_demo9.py`

   确认 `build_feature_meta(samples)` 只从 `sample.feature` 提取字段。

   `metrics.json` 可以继续记录 label 规则：

   - `label_task=stability`
   - `stability_bars`
   - `stability_bis`
   - `stability_days`
   - `stability_window_mode`

   这些字段只描述 label，不作为模型输入。

3. 重新训练四组 stability 模型

   重新生成：

   - `Debug/model_output/strategy_demo8_stability_buy`
   - `Debug/model_output/strategy_demo8_stability_sell`
   - `Debug/model_output/strategy_demo9_stability_buy`
   - `Debug/model_output/strategy_demo9_stability_sell`

   验证：

   ```text
   feature.meta.json 中不应出现 stability_ 前缀字段
   ```

   旧模型建议先备份到 `_bak` 或带日期目录，避免新旧特征口径混用。

4. 修改 scan 逻辑

   文件：

   - `Debug/bsp_probability_scan_common.py`
   - `Debug/scan_bsp_probability.py`

   要求：

   - 移除 scan 中对 `stability_context_feature()` 的调用。
   - 移除 `STABILITY_FEATURES` 写入 CSV 的配置。
   - scan 对当前结构中仍存在的一类/二类目标买卖点打分。
   - 不再为了 scan 模拟 first-seen replay scoring。

   输出字段建议：

   - `signal_time`: 买卖点对应笔结束时间。
   - `decision_time`: 兼容旧表可暂时保留，但不再解释为模型输入时点。
   - 后续可以新增 `score_time` 替代 `decision_time`，用于记录本次扫描数据截止时间。

5. 修改 chart 逻辑

   文件：`web/bsp_probability.py`

   要求：

   - 不再 `step_load()` 逐步 replay 打分。
   - 构建完整 chart chan 后，对最终结构中的目标买卖点打分。
   - 移除 `stability_context_feature()`。
   - tooltip 不再展示 `decision=...`。

   推荐 tooltip 口径：

   ```text
   二类 2/2s 买点稳定概率 86.7%; signal=2026/05/08 10:00
   ```

6. 清理展示和 API 文案

   文件：

   - `web/chart_payload.py`
   - `web/static/chart.js`
   - `web/static/signals.js`

   统一描述为“稳定概率”。

   避免继续使用以下描述解释模型概率：

   - `decision`
   - `as_of`
   - `point_in_time_stability`

7. 数据库兼容

   文件：`Debug/bsp_probability_scan_common.py`

   短期不强制迁移表结构。

   现有 `decision_time` 字段可以保留为兼容字段，但语义降级，不再作为模型输入时点解释。

   后续建议新增：

   - `score_time`
   - `model_feature_schema`

8. 验证

   单票 scan：

   ```powershell
   python Debug/scan_bsp_probability.py --target-group second --code 300274 --begin-time 2026-01-16 --end-time 2026-05-16 --recent-bars 48 --signal-side buy --min-prob 0.80 --workers 1 --no-save-db
   ```

   chart payload：

   ```text
   /api/chart/payload?code=300274&lv=30m&data_src=CACHE_DB&x_range=500&begin=2026-01-16&end=2026-05-16
   ```

   对比同一条信号：

   - `code`
   - `signal_time`
   - `target_group`
   - `signal_side`
   - `probability`
   - `model_dir`

   预期：scan 和 chart 概率一致。

9. 回归检查

   ```powershell
   python -m py_compile Debug/bsp_point_in_time_label.py Debug/bsp_probability_scan_common.py Debug/scan_bsp_probability.py web/bsp_probability.py
   node --check web/static/chart.js
   ```

   数据检查：

   - 新模型 `feature.meta.json` 无 `stability_*`
   - 新 scan CSV 无 `stability_*`
   - chart payload marker 不再用 `decisionTime` 解释概率口径

## 风险和约束

- 必须重新训练模型。只改 scan/chart 不够，因为旧 stability 模型的 `feature.meta.json` 仍期待 `stability_*` 字段。
- 旧 run_id 数据和新 run_id 不应直接混用，需要通过模型生成时间、schema 或 run 描述区分。
- 动态监控如果复用 stability 模型，也要同步确认不再传入 `stability_*` 特征。
- 在新模型训练完成前，scan/chart 若提前移除 `stability_*`，会造成模型输入特征缺失并改变概率口径。
