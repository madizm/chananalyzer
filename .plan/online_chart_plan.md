# 在线画图功能实施计划

## 实施状态

已完成首期实现：新增 FastAPI 在线服务、动态 payload 接口、TradingView 在线页面、启动脚本和 README 使用说明。

## 目标

新增一个在线缠论图表页面：浏览器打开 URL 后，通过参数传入股票代码、级别等信息，在线加载并展示 K 线走势、合并 K 线、笔、线段、中枢、买卖点等指标。

示例访问：

```text
http://127.0.0.1:8000/chart?code=002112&lv=30m&begin=2026-03-10&end=2026-04-28
```

## 参考与复用

- 复用 `Plot/TradingViewDriver.py` 中已有的 TradingView payload 生成逻辑和前端绘制思路。
- 复用 `charting_library/` 本地 TradingView 静态资源。
- 复用 `CChan`、`CChanConfig`、`GetPlotMeta`、`parse_plot_config` 等现有结构计算与元数据转换能力。

## 功能范围

### 首期必须支持

1. HTTP 服务启动后可访问在线图表页面。
2. URL 参数指定：
   - `code`: 股票代码，如 `002112`、`000001.SZ`。
   - `lv`: 周期级别，如 `day`、`week`、`5m`、`15m`、`30m`、`60m`。
   - `begin`: 开始日期，默认可选。
   - `end`: 结束日期，默认可选。
   - `data_src`: 数据源，默认 `TDX`，可选扩展 `TUSHARE` / `CACHE_DB`。
3. 页面展示：
   - K 线；
   - 合并 K 线；
   - 笔；
   - 线段；
   - 中枢；
   - 买卖点 / 段买卖点；
   - 可选均线。
4. 图层开关沿用 `TradingViewDriver` 的按钮逻辑。
5. 后端返回结构化 JSON payload，前端动态渲染，不再依赖每次生成静态 HTML 文件。

### 首期暂不做

1. WebSocket 实时推送。
2. 用户登录、权限、个性化配置持久化。
3. 多股票同屏对比。
4. 前端工程化打包；优先使用简单静态 HTML + JS。

## 推荐架构

```text
Browser
  └─ GET /chart?code=002112&lv=30m&begin=...&end=...
       └─ 返回在线图表 HTML

Browser
  └─ GET /api/chart/payload?code=002112&lv=30m&begin=...&end=...
       └─ FastAPI 后端
            ├─ 参数解析和校验
            ├─ 构建 CChan
            ├─ 复用 TradingView payload 构建器
            └─ 返回 JSON

Static
  └─ /charting_library/* -> charting_library/charting_library
```

## 文件规划

### 新增文件

1. `web/__init__.py`
2. `web/chart_server.py`
   - FastAPI 应用入口。
   - 暴露 `/chart`、`/api/chart/payload`。
   - 挂载 TradingView 静态资源。
3. `web/chart_params.py`
   - URL 参数解析。
   - `lv` 到 `KL_TYPE` 映射。
   - `data_src` 到 `DATA_SRC` 映射。
4. `web/chart_payload.py`
   - 在线图表 payload 构建服务。
   - 封装 `CChan` 创建、默认配置、缓存策略。
5. `web/static/chart.html`
   - 在线图表页面模板。
6. `web/static/chart.js`
   - 前端 datafeed 和绘图逻辑。
   - 从 `TradingViewDriver._render_html()` 中抽离 JavaScript 逻辑。
7. `scripts/run_chart_server.py`
   - 本地启动脚本，方便执行：`python scripts/run_chart_server.py --host 127.0.0.1 --port 8000`。

### 修改文件

1. `Plot/TradingViewDriver.py`
   - 抽离/新增公共方法，只负责 payload 生成，避免在线服务复用私有 HTML 模板。
   - 建议新增：
     - `build_payload()` 或保持 `payload` 属性稳定；
     - 可选 `render_payload_json()`。
2. `requirements.txt`
   - 已包含 `fastapi`、`uvicorn`，首期无需新增依赖。
3. `README.md`
   - 增加在线画图启动和访问说明。

## 后端接口设计

### `GET /chart`

返回 HTML 页面。

参数直接透传给前端，由前端再请求 `/api/chart/payload`。

### `GET /api/chart/payload`

请求参数：

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `code` | 是 | - | 股票代码 |
| `lv` | 否 | `day` | 周期级别 |
| `begin` | 否 | 近一年或配置默认 | 开始日期 |
| `end` | 否 | 当前日期 | 结束日期 |
| `data_src` | 否 | `TDX` | 数据源 |
| `autype` | 否 | `QFQ` | 复权方式 |
| `x_range` | 否 | `200` | 默认展示 K 线数量 |
| `indicators` | 否 | 默认全开 | 可选图层配置 |

响应：

```json
{
  "title": "002112/30M",
  "symbol": "002112",
  "resolution": "30",
  "symbolInfo": {},
  "bars": [],
  "visibleRange": {},
  "klc": [],
  "bi": [],
  "seg": [],
  "zs": [],
  "mean": [],
  "bspMarkers": [],
  "customMarkers": []
}
```

错误响应：

```json
{
  "detail": "invalid lv: 2h"
}
```

## 参数映射

`lv` 支持：

```text
1m  -> KL_TYPE.K_1M
3m  -> KL_TYPE.K_3M
5m  -> KL_TYPE.K_5M
15m -> KL_TYPE.K_15M
30m -> KL_TYPE.K_30M
60m -> KL_TYPE.K_60M
day,d,1d -> KL_TYPE.K_DAY
week,w,1w -> KL_TYPE.K_WEEK
mon,month,m,1M -> KL_TYPE.K_MON
```

默认 `lv_list` 首期只使用单级别：`[selected_lv]`。后续如要展示多周期，可扩展为 `lv=day,30m` 并按照从大到小排序。

## 默认缠论配置

首期建议默认配置与 `main_tradingview.py` 保持一致：

```python
CChanConfig({
    "bi_strict": True,
    "trigger_step": False,
    "skip_step": 0,
    "divergence_rate": float("inf"),
    "min_zs_cnt": 0,
    "bs1_peak": False,
    "macd_algo": "peak",
    "bs_type": "1,2,3a,1p,2s,3b",
    "print_warning": True,
    "zs_algo": "normal",
})
```

默认绘图配置：

```python
{
    "plot_kline": True,
    "plot_kline_combine": True,
    "plot_bi": True,
    "plot_seg": True,
    "plot_zs": True,
    "plot_mean": False,
    "plot_bsp": True,
    "plot_segbsp": True,
    "plot_marker": False,
}
```

## 缓存策略

首期可做简单内存缓存，避免每次刷新都重新计算：

- key: `(code, lv, begin, end, data_src, autype, config_hash)`。
- value: payload JSON。
- TTL: 60 ~ 300 秒。
- 后续可扩展为 SQLite/磁盘缓存。

## 实施步骤

### 阶段 1：抽离 payload 生成

1. 梳理 `CTradingViewDriver._build_payload()` 依赖项。
2. 保持 `save_html()` 兼容现有静态 HTML 用法。
3. 新增可由 Web 服务调用的公共函数，例如：

```python
def build_tradingview_payload(chan, plot_config, plot_para) -> dict:
    return CTradingViewDriver(chan, plot_config, plot_para).payload
```

验收：`main_tradingview.py` 仍能正常生成 `image/test_tv.html`。

### 阶段 2：实现 FastAPI 服务

1. 新增 `web/chart_server.py`。
2. 实现 `/api/chart/payload`。
3. 实现参数解析和异常处理。
4. 挂载静态资源：
   - `/static` -> `web/static`
   - `/charting_library` -> `charting_library/charting_library`

验收：

```bash
uvicorn web.chart_server:app --reload --host 127.0.0.1 --port 8000
curl "http://127.0.0.1:8000/api/chart/payload?code=002112&lv=30m"
```

能返回包含 `bars`、`bi`、`seg`、`bspMarkers` 的 JSON。

### 阶段 3：实现在线图表页面

1. 新增 `web/static/chart.html`。
2. 新增 `web/static/chart.js`。
3. 将 `TradingViewDriver._render_html()` 里的：
   - datafeed；
   - shape 绘制；
   - 图层开关；
   - visibleRange 设置；
   抽成前端 JS。
4. 页面初始化时读取 URL 参数并请求 `/api/chart/payload`。

验收：打开：

```text
http://127.0.0.1:8000/chart?code=002112&lv=30m&begin=2026-03-10&end=2026-04-28
```

页面成功展示图表和缠论指标。

### 阶段 4：启动脚本和文档

1. 新增 `scripts/run_chart_server.py`。
2. 更新 `README.md`，说明：
   - 如何启动；
   - URL 参数；
   - 示例；
   - 常见错误，如 TradingView 静态资源未找到、TDX 数据源不可用。

验收：新用户按 README 可启动并访问页面。

### 阶段 5：测试和健壮性

1. 单元测试：
   - `lv` 参数映射；
   - `data_src` 参数映射；
   - payload 基础字段存在。
2. 接口测试：
   - 缺少 `code` 返回 422；
   - 非法 `lv` 返回 400；
   - 无数据返回明确错误。
3. 手动测试多个周期：
   - `day`、`60m`、`30m`、`15m`。

## 风险与注意事项

1. `CChan` 计算可能较慢，需要缓存和合理默认时间范围。
2. TDX 数据源依赖本机环境，在线服务启动时应给出清晰错误信息。
3. TradingView 本地资源必须通过 HTTP 访问，不能直接用 `file://`。
4. 单次返回过多 K 线会导致 payload 很大，建议默认限制 `x_range=200`，同时允许 begin/end 控制。
5. `CChanConfig` 会拒绝未知参数，前端传入图层配置应和算法配置分离。

## 验收标准

1. 运行：

```bash
python scripts/run_chart_server.py --host 127.0.0.1 --port 8000
```

2. 打开：

```text
http://127.0.0.1:8000/chart?code=002112&lv=30m&begin=2026-03-10&end=2026-04-28
```

3. 浏览器页面可见：
   - K 线蜡烛图；
   - 合并 K 线区域；
   - 笔、线段；
   - 中枢矩形；
   - 买卖点箭头和文本；
   - 图层开关可正常显示/隐藏。

## 后续增强

1. 支持多级别联动：`lv=day,30m`。
2. 支持 WebSocket 实时追加 K 线。
3. 支持指标配置通过 URL 或页面控件传入。
4. 支持保存常用股票和级别。
5. 支持导出当前图表截图或 payload。
