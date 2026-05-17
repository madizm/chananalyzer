# 30M BSP 序列扫描结果看板实施计划

## 目标

为 `scripts/scan_m30_bsp_sequence.py` 的扫描结果新增一个 Web 看板页面，用于查看最近扫描批次、命中股票、序列规则和基础统计，并支持一键跳转现有 `/chart` 页面复盘。

首期只做扫描结果列表和复盘链接，不新增 TradingView 图表组件，不扩展图表叠加层。

## 当前现状

- `scripts/scan_m30_bsp_sequence.py` 扫描分钟级 BSP 纯净序列，默认序列为 `S3 B1`。
- 扫描结果写入现有通用表：
  - `scan_runs`
  - `scan_results`
  - `scan_signals`
- `scan_results.signal_time` 保存命中时间。
- `scan_signals` 当前只保存最终触发步骤。
- 完整 `matched_steps` 目前只用于控制台打印，没有落库。
- `web/chart_server.py` 已有：
  - `/chart` 在线图表页面
  - `/signals` 模型概率信号看板
  - `/api/chart/payload` 图表 payload 接口

## 首期范围

### 必须支持

1. 新增 BSP 序列扫描看板页面。
2. 可选择扫描批次，默认展示最新一次 `source='scan_m30_bsp_sequence'` 的扫描结果。
3. 展示扫描批次摘要：
   - run id
   - 扫描时间
   - 扫描股票数
   - 命中股票数
   - 数据窗口
   - BSP 序列
   - 信号级别
   - 最大间隔
   - 笔过滤模式
4. 展示命中股票列表：
   - 股票代码
   - 名称
   - 行业
   - 地区
   - 最新价
   - 涨跌幅
   - 信号时间
   - 最终信号类型
   - 最终信号方向
   - 最终信号价格
   - 复盘链接
5. 复盘链接跳转现有 `/chart`：

   ```text
   /chart?code=000001&lv=30m&data_src=CACHE_DB&x_range=500
   ```

6. 看板支持基础过滤：
   - 扫描批次
   - 行业
   - 开始日期
   - 结束日期
   - 返回数量

### 首期暂不做

1. 不新增 TradingView 图表组件。
2. 不新增图表 marker 图层。
3. 不在 `/chart` 中高亮本次命中的序列步骤。
4. 不做回测收益统计。
5. 不做概率模型评分。
6. 不做实时扫描触发。

## 数据存储方案

### 首期推荐

复用现有 `scan_runs / scan_results / scan_signals`，不新增表。

理由：

- 当前看板只需要展示最终命中结果和跳转复盘。
- `scan_m30_bsp_sequence.py` 已经把最终触发点写入 `scan_signals`。
- 不需要在图表中还原完整序列步骤，所以无需落库 `matched_steps`。

### 需要补充的元数据

为了让页面准确展示扫描规则，建议在 `scan_runs` 上补充以下可选字段：

- `sequence_json TEXT`
- `max_gap_days INTEGER`
- `bi_mode VARCHAR(20)`
- `signal_level VARCHAR(20)`

如果希望首期保持最小改动，也可以先从既有字段推导：

- `source='scan_m30_bsp_sequence'`
- `buy_types` / `sell_types` 显示命中序列涉及的买卖类型，但无法完整表达顺序。
- `begin_date` / `end_date`
- `bi_strict`

推荐首期增加字段，因为序列顺序是该扫描任务的核心信息。

## 后端设计

### 新增文件：`web/sequence_payload.py`

职责：

1. 查询序列扫描批次。
2. 查询指定批次命中结果。
3. 生成页面所需统计和过滤选项。
4. 为每条结果生成复盘 URL。

建议函数：

```python
def list_sequence_runs(limit: int = 20) -> dict[str, Any]:
    ...

def build_sequence_dashboard(
    *,
    run_id: int | None = None,
    industry: str = "all",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    ...
```

### 修改文件：`web/chart_server.py`

新增路由：

```python
@app.get("/sequence", include_in_schema=False)
def sequence_page():
    return FileResponse(STATIC_DIR / "sequence.html")

@app.get("/api/sequence/runs")
def sequence_runs(limit: int = Query(20, ge=1, le=100)):
    return list_sequence_runs(limit=limit)

@app.get("/api/sequence/latest")
def sequence_latest(...):
    return build_sequence_dashboard(...)
```

### API 返回结构

`GET /api/sequence/latest` 返回：

```json
{
  "available": true,
  "message": "",
  "runs": [],
  "selected_run": {},
  "summary": {
    "scanned_count": 50,
    "result_count": 3,
    "sequence": "S3 B1",
    "signal_level": "30M",
    "max_gap_days": 5,
    "bi_mode": "off"
  },
  "results": [],
  "industry_options": [],
  "filters": {}
}
```

每条 `results`：

```json
{
  "code": "000001",
  "name": "平安银行",
  "industry": "银行",
  "area": "深圳",
  "latest_price": 12.34,
  "change_pct": 1.23,
  "signal_time": "2026-05-15 14:30:00",
  "signal_type": "1",
  "direction": "buy",
  "signal_price": 12.10,
  "period": "30M",
  "chart_url": "/chart?code=000001&lv=30m&data_src=CACHE_DB&x_range=500"
}
```

## 前端设计

### 新增文件：`web/static/sequence.html`

页面结构：

- 顶部导航：
  - `在线画图`
  - `模型信号`
  - `BSP序列`
- 过滤区：
  - 扫描批次
  - 行业
  - 开始日期
  - 结束日期
  - 数量
  - 刷新按钮
- 摘要区：
  - 扫描股票数
  - 命中数量
  - 序列
  - 信号级别
  - 最大间隔
  - 笔过滤
  - 数据窗口
  - 运行 ID
- 结果表：
  - 名称 / 代码
  - 行业
  - 地区
  - 信号时间
  - 信号
  - 价格
  - 涨跌幅
  - 复盘

### 新增文件：`web/static/sequence.js`

职责：

1. 加载 `/api/sequence/runs`。
2. 加载 `/api/sequence/latest`。
3. 渲染批次下拉、行业过滤、摘要和结果表。
4. 点击“复盘”直接打开现有 `/chart`。

## 扫描脚本改造

文件：`scripts/scan_m30_bsp_sequence.py`

建议修改：

1. `save_results_to_database()` 写入 `ScanRun` 时补充：
   - `sequence_json`
   - `max_gap_days`
   - `bi_mode`
   - `signal_level`
2. `scan_params` 已经包含：
   - `sequence_steps`
   - `max_gap_days`
   - `bi_mode`
   - `level`
3. 若暂时不加数据库字段，至少保证 `source="scan_m30_bsp_sequence"` 稳定，便于 Web 查询筛选。

## 文件清单

### 新增

- `web/sequence_payload.py`
- `web/static/sequence.html`
- `web/static/sequence.js`

### 修改

- `web/chart_server.py`
- `scripts/scan_m30_bsp_sequence.py`
- `ChanAnalyzer/database.py`

## 验证步骤

1. 执行小样本扫描：

   ```powershell
   python scripts/scan_m30_bsp_sequence.py --sequence S3 B1 --level 30M --limit 20
   ```

2. 启动 Web 服务：

   ```powershell
   uvicorn web.chart_server:app --reload
   ```

3. 浏览器访问：

   ```text
   http://127.0.0.1:8000/sequence
   ```

4. 验证：

   - 默认展示最新序列扫描批次。
   - 摘要信息与控制台扫描结果一致。
   - 命中列表能展示股票名称、行业、信号时间和最终信号。
   - “复盘”跳转 `/chart` 后能正常加载 30M 图。
   - 不影响现有 `/chart` 和 `/signals` 页面。

## 后续扩展

如果首期使用后确认需要在图表中定位完整序列，再单独做第二阶段：

1. 将 `matched_steps` 落库。
2. 在 `/chart` payload 中复用 `customMarkers` 追加序列步骤。
3. 仍不新增 TradingView 组件，只复用现有“标记”图层。
