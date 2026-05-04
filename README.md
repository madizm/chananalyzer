# ChanAnalyzer - A股缠论分析系统

> 本项目基于 [Vespa314/chan.py](https://github.com/Vespa314/chan.py) 进行二次开发

**原项目链接**: https://github.com/Vespa314/chan.py | **本项目仓库**: https://github.com/164149043/chananalyzer

---

## 二次开发内容

基于原始 chan.py 项目，本版本进行了以下增强和改进：

- 🤖 **AI 智能分析模块** - 集成多个 AI 模型进行协作分析
- 📡 **多数据源支持** - 支持 Tushare、Akshare 等多种数据源
- 🌐 **FastAPI Web 界面** - 现代化的 Web 分析平台
- 🖥️ **A股买卖点扫描器 GUI** - PyQt6 图形化扫描工具
- ⚡ **缓存优化** - 数据库缓存提升分析速度
- 📊 **可视化增强** - 改进的图表和交互体验

---

基于缠论（缠中说禅）技术分析的 A 股行情分析工具，支持笔、线段、中枢、买卖点自动识别。

## 特性

- **缠论核心分析**：自动识别笔、线段、中枢结构
- **多买卖点检测**：支持一/二/三类买卖点识别
- **多周期分析**：支持 1分钟到周线多级别联立
- **技术指标**：MACD、布林带、RSI、KDJ 等
- **本地缓存**：SQLite 本地缓存，离线快速分析
- **批量扫描**：一键扫描全市场买卖点信号
- **AI 智能分析**：多 AI 协作分析，给出交易策略建议
- **GUI 界面**：可视化 K 线图表，缠论结构一目了然
- **Web 界面**：基于浏览器的一站式分析平台 ⭐新增

## 快速开始

### 方式一：Web 界面（推荐）

```bash
# 启动 Web 服务器
python web/start_server.py

# 或直接启动 API
cd web && python api.py
```

然后访问：**http://localhost:8000**

Web 功能包括：
- 📊 **仪表盘** - 市场概况、买卖点统计、热门板块
- 📈 **个股分析** - 输入股票代码，多 AI 协作分析
- ⚡ **买点扫描** - 一买、二买、三买批量扫描
- 💰 **卖点扫描** - 二卖批量扫描

### 方式二：命令行

#### 1. 安装依赖

```bash
pip install -r requirements.txt
```

#### 2. 配置 Token

```bash
# Windows PowerShell
$env:TUSHARE_TOKEN="你的token"

# Linux/Mac
export TUSHARE_TOKEN="你的token"
```

> 获取 Token：访问 [Tushare Pro](https://tushare.pro) 注册并获取 API Token

#### 2.5 配置 AI API（可选）

如需使用 AI 智能分析功能，配置 DeepSeek API Key：

```bash
# Windows PowerShell
$env:DEEPSEEK_API_KEY="your_deepseek_key"

# Linux/Mac
export DEEPSEEK_API_KEY="your_deepseek_key"
```

> 获取 API Key：访问 [DeepSeek Platform](https://platform.deepseek.com/api_keys) 注册并获取 API Key

#### 3. 运行分析

```python
from ChanAnalyzer import ChanAnalyzer

analyzer = ChanAnalyzer(code="000001")
print(analyzer.get_summary())
```

---

## 命令行使用

### 扫描器选择

系统提供两种扫描器，可根据需求选择：

| 扫描器 | 数据源 | 速度 | 功能 | 适用场景 |
|--------|--------|------|------|----------|
| `scan_stocks_cache.py` | 本地数据库 + Tushare | **快** | 买卖点+行业/地区+资金流向 | **推荐日常使用** |
| `scan_stocks.py` | Tushare API | 慢 | 全功能 | 需要实时数据 |

### 本地缓存扫描器（推荐）

使用本地 `chan.db` 进行 K 线分析，速度快无需联网（可选获取行业/资金流向）。

```bash
# 扫描所有股票（从本地数据库）
python scan_stocks_cache.py

# 扫描指定股票
python scan_stocks_cache.py --codes 000001 000002 600000

# 按行业筛选
python scan_stocks_cache.py --industry 电子 计算机

# 按地区筛选
python scan_stocks_cache.py --area 深圳 上海

# 排除ST股票
python scan_stocks_cache.py --exclude-st

# 显示资金流向并排序
python scan_stocks_cache.py --show-money-flow --sort-by-money-flow

# 筛选特定买点
python scan_stocks_cache.py --buy 1 2 3a

# 保存结果
python scan_stocks_cache.py --output results.txt

# 按行业分组显示
python scan_stocks_cache.py --group-by industry

# 组合使用：电子行业 + 二买三买 + 主力流入
python scan_stocks_cache.py --industry 电子 --buy 2 3a 3b --min-money-flow 500 --sort-by-money-flow
```

### 在线扫描器（原版）

直接调用 Tushare API，数据实时但速度较慢。

```bash

### 首次使用完整流程

```bash
# 1. 同步股票基本信息（名称、行业、地区）- 首次使用必做
python -m scripts.cache_stock_info

# 2. 查看所有行业（确认股票池正常）
python scan_stocks.py --list-industries

# 2. 测试缓存 100 只股票
python -m scripts.cache_all_stocks --all --kl-types DAY --limit 100 --delay 0.3

# 3. 扫描前 50 只股票测试
python scan_stocks.py --limit 50
```

### 批量扫描买卖点

```bash
# 按行业筛选扫描
python scan_stocks.py --industry 半导体 --limit 50
python scan_stocks.py --industry 元器件 半导体 --limit 100

# 按地区筛选扫描
python scan_stocks.py --area 深圳 上海 --limit 50

# 复合筛选（行业 + 地区 + 排除ST）
python scan_stocks.py --industry 电子 --area 深圳 --exclude-st --limit 50

# 按市场筛选
python scan_stocks.py --market 创业板 科创板 --limit 50

# 指定股票扫描
python scan_stocks.py --codes 000001 000002 600000

# 扫描所有A股（限制数量）
python scan_stocks.py --limit 100

# 筛选特定买卖点类型
python scan_stocks.py --limit 100 --buy 2 3a 3b

# 按行业分组显示结果
python scan_stocks.py --industry 半导体 --limit 50 --group-by industry
```

### 股票池查询

```bash
# 列出所有行业及股票数量
python scan_stocks.py --list-industries

# 显示板块资金流向（需要 Tushare 一定权限）
python scan_stocks.py --show-flow
```

### 资金流向分析（需要 2000 积分权限）

```bash
# 扫描时显示个股资金流向
python scan_stocks.py --codes 000001 000002 --show-money-flow

# 按主力净流入排序（主力=特大单+大单）
python scan_stocks.py --industry 半导体 --limit 50 --sort-by-money-flow

# 筛选主力净流入大于 1000 万的股票
python scan_stocks.py --industry 电子 --min-money-flow 1000 --limit 100

# 组合使用：二买+三买 + 主力流入
python scan_stocks.py --buy 2 3a 3b --min-money-flow 500 --sort-by-money-flow
```

**资金流向说明**：
- **主力资金** = 特大单 + 大单（机构、大户资金）
- **散户资金** = 中单 + 小单
- 正数表示净流入，负数表示净流出
- 数据缓存 10 分钟，避免频繁 API 调用

### 分析单只股票

```bash
# 查看文本摘要
python -c "
from ChanAnalyzer import ChanAnalyzer
analyzer = ChanAnalyzer(code='000001')
print(analyzer.get_summary())
"
```

### AI 智能分析

系统提供两种 AI 分析模式：

#### 单 AI 分析

使用单个 AI 模型分析缠论数据：

```bash
# 交互模式
python -m scripts.ai_analyze

# 命令行模式
python -m scripts.ai_analyze --code 000001

# 多周期分析
python -m scripts.ai_analyze --code 000001 --multi

# 保存结果
python -m scripts.ai_analyze --code 000001 --output report.txt
```

#### 多 AI 协作分析

两个分析师 AI 并行分析 + 一个决策者 AI 综合判断：

```bash
# 基本用法
python -m scripts.multi_ai_analyze --code 000001

# 多周期分析
python -m scripts.multi_ai_analyze --code 000001 --multi

# 使用自定义配置
python -m scripts.multi_ai_analyze --code 000001 --config my_config.yaml

# 保存结果
python -m scripts.multi_ai_analyze --code 000001 --output report.txt
```

**多 AI 分析流程**：
```
缠论数据 → [分析师A + 分析师B] 并行分析 → 决策者综合 → 最终建议
           (deepseek-chat)                   (deepseek-reasoner)
           温度: 0.4 / 0.7
```

**配置文件** (`ai_config.yaml`)：

```yaml
# 分析师配置
analysts:
  model: deepseek-chat
  temperatures: [0.4, 0.7]  # 两个分析师的温度
  max_tokens: 2000

# 决策者配置
decision_maker:
  model: deepseek-reasoner
  temperature: 0.3
  max_tokens: 2000

# 提示词配置
prompts:
  analyst_system: |
    你是一位专业的股票技术分析师，精通缠论理论...
  decision_maker_system: |
    你是一位资深的投资决策专家...
```

### Web 界面 ⭐推荐

基于浏览器的现代化分析平台，采用 Neumorphism 设计风格。

#### 启动 Web 服务

```bash
# 方式1：使用启动脚本（推荐）
python web/start_server.py

# 方式2：直接运行 API
cd web && python api.py
```

然后访问：**http://localhost:8000**

#### 功能模块

| 模块 | 功能 | 说明 |
|------|------|------|
| 📊 仪表盘 | 市场概览 | 指数概览、买卖点统计、热门板块、买点推荐 |
| 📈 个股分析 | AI 分析 | 双分析师 + 决策者模式，支持温度调节 |
| ⚡ 买点扫描 | 批量扫描 | 一买、二买、三买 A/B |
| 💰 卖点扫描 | 批量扫描 | 二卖（当前仅支持二卖） |
| 🗂️ 行业筛选 | 行业过滤 | 按行业筛选股票（开发中） |
| 📉 K线图表 | 可视化 | K 线图表展示（开发中） |

#### Web API 端点

```bash
# 买卖点扫描 API
POST /api/scan/buy/start   # 启动买点扫描
POST /api/scan/sell/start  # 启动卖点扫描
GET  /api/scan/status      # 获取扫描状态
GET  /api/scan/buy/results # 获取买点扫描结果
GET  /api/scan/sell/results # 获取卖点扫描结果

# 个股分析 API
POST /api/ai/analyze       # AI 分析股票
GET  /api/ai/config        # 获取 AI 配置

# 股票信息 API
GET  /api/stock/info/:code # 获取股票信息
GET  /api/stock/analysis/:code # 获取股票分析数据
```

#### Web 扫描参数

**买点扫描**：
- 买点类型：一买(1)、二买(2)、三买A(3a)、三买B(3b)
- 扫描数量：前100只 / 前500只 / 前1000只 / 全市场

**卖点扫描**：
- 卖点类型：二卖(2s)
- 扫描数量：前100只 / 前500只 / 前1000只 / 全市场

#### 扫描结果展示

结果按**最新信号日期排序**（最近的在前），包含：
- 股票代码和名称
- 当前价格
- 买点/卖点类型
- 信号日期
- 信号价格

### 批量扫描买卖点

```bash
# 扫描指定股票（有缓存时无需延迟）
python scan_stocks.py --codes 000001 000002 600000

# 扫描所有A股（限制数量）
python scan_stocks.py --limit 100

# 筛选二买、三买股票
python scan_stocks.py --limit 300 --buy 2 3a 3b

# 保存结果
python scan_stocks.py --limit 100 --output results.txt
```

**提示**：扫描前请先执行 `cache_all_stocks.py` 缓存数据，扫描时将直接从 SQLite 读取，无需调用 API。

### 数据缓存管理

#### 首次批量缓存（推荐先用）

```bash
# 只缓存日线数据（推荐：API 调用少，速度快）
python -m scripts.cache_all_stocks --all --kl-types DAY --delay 0.3

# 缓存日线 + 周线数据
python -m scripts.cache_all_stocks --all --kl-types DAY WEEK --delay 0.3

# 测试：先缓存 100 只股票
python -m scripts.cache_all_stocks --all --kl-types DAY --limit 100 --delay 0.3

# 缓存指定股票
python -m scripts.cache_all_stocks --codes 000001 000002 --kl-types DAY
```

**参数说明**：
- `--kl-types DAY` - 只缓存日线（推荐：约 5000 次调用）
- `--kl-types DAY WEEK` - 缓存日线+周线（约 10000 次调用）
- `--delay 0.3` - 每股间隔 0.3 秒，避免触发频次限制
- `--limit 100` - 限制数量，测试用

#### 日常更新数据

```bash
# 更新所有已缓存的股票（每日收盘后执行）
python -m scripts.update_data --all

# 更新指定股票
python -m scripts.update_data --codes 000001 000002

# 清除缓存后重新获取
python -m scripts.update_data --codes 000001 --refresh
```

### 多周期分析

```python
from ChanAnalyzer import MultiChanAnalyzer

# 同时分析周线、日线
analyzer = MultiChanAnalyzer(code="000001")
print(analyzer.get_summary())
```

---

## 项目结构

```
chan.py/
├── ChanAnalyzer/           # 分析模块
│   ├── analyzer.py         # 核心分析器
│   ├── ai_analyzer.py      # AI分析器
│   ├── multi_ai_analyzer.py # 多AI协作分析器
│   ├── prompts/            # AI提示词模板
│   │   ├── analyst.py      # 分析师提示词
│   │   └── decision_maker.py # 决策者提示词
│   ├── database.py         # 数据库模型
│   ├── data_manager.py     # 数据管理器
│   └── formatter.py        # 格式化输出
├── Common/                 # 公共模块
│   ├── CEnum.py           # 枚举定义
│   └── CTime.py           # 时间处理
├── KLine/                  # K线处理
│   ├── KLine_Unit.py      # K线单元
│   ├── KLine_List.py      # K线列表
│   └── KLine.py           # K线实体
├── Bi/                     # 笔
├── Seg/                    # 线段
├── Zs/                     # 中枢
├── Math/                   # 技术指标
├── DataAPI/                # 数据源
│   ├── TushareAPI.py      # Tushare 接口
│   ├── AkshareAPI.py      # Akshare 接口
│   ├── TdxAPI.py          # 通达信 TDX/TPythClient 接口
│   └── CacheDBAPI.py      # 本地数据库接口
├── App/                    # GUI应用
│   └── ashare_bsp_scanner_gui.py  # 缠论买点扫描器GUI
├── web/                    # Web界面 ⭐新增
│   ├── api.py             # FastAPI 后端
│   ├── start_server.py    # 服务器启动脚本
│   ├── static/            # 前端静态文件
│   │   ├── index.html     # 主页面（Neumorphism设计）
│   │   ├── app.js         # 仪表盘逻辑
│   │   ├── individual.js  # 个股分析逻辑
│   │   └── scan.js        # 扫描功能逻辑
│   └── cache/             # 扫描结果缓存
├── scripts/                # 脚本工具
│   ├── ai_analyze.py      # AI分析脚本
│   ├── multi_ai_analyze.py # 多AI协作分析脚本
│   ├── cache_all_stocks.py # 批量缓存K线数据
│   ├── cache_stock_info.py # 缓存股票基本信息
│   └── update_data.py     # 数据更新脚本
├── scan_stocks.py         # 在线扫描器（Tushare API）
├── scan_stocks_cache.py   # 本地缓存扫描器
├── ai_config.yaml         # AI配置文件
├── test_analyzer.py       # 测试脚本
└── chan.db                # 本地K线缓存数据库
```

---

## 缓存机制

系统使用 SQLite (`chan.db`) 存储历史 K 线数据，避免重复 API 调用：

| 场景 | 首次运行 | 再次运行 |
|------|----------|----------|
| 000001 日线 | 0.25s | 0.01s |
| 加速比 | - | **42.5x** |

### 本地数据库结构

```sql
CREATE TABLE kline_data (
    code VARCHAR(10),        -- 股票代码
    kl_type VARCHAR(10),     -- K线类型 (DAY/WEEK)
    date VARCHAR(20),        -- 日期
    open FLOAT,              -- 开盘价
    high FLOAT,              -- 最高价
    low FLOAT,               -- 最低价
    close FLOAT,             -- 收盘价
    volume FLOAT,            -- 成交量
    amount FLOAT,            -- 成交额
    ...
);
```

### 缓存策略

- **存储位置**: `./chan.db`
- **支持周期**: 日线(DAY)、周线(WEEK)
- **数据来源**: Tushare Pro API
- **更新方式**: 使用 `cache_all_stocks.py` 或 `update_data.py`

### 默认数据范围

| 周期 | 默认开始日期 | 说明 |
|------|-------------|------|
| 日线 | 2023-01-01 | 约 3 年历史数据 |
| 周线 | 2023-01-01 | 建议与日线保持一致 |

> **注意**：首次缓存周线数据时，确保使用 `--begin 2023-01-01` 参数，否则可能只获取最近几天的数据。

### 使用本地数据库

```python
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import DATA_SRC, KL_TYPE, AUTYPE

# 方式1：直接使用本地数据库
chan = CChan(
    code="000001",
    begin_time="2024-01-01",
    end_time="2024-12-31",
    data_src=DATA_SRC.CACHE_DB,  # 使用本地数据库
    lv_list=[KL_TYPE.K_DAY],
    autype=AUTYPE.QFQ,
)

# 获取买卖点
bsp_list = chan.get_latest_bsp(number=0)
for bsp in bsp_list:
    print(f"{bsp.type2str()}: {bsp.klu.time}")
```

### 使用通达信 TDX 数据源（TPythClient）

```python
from Chan import CChan
from Common.CEnum import DATA_SRC, KL_TYPE, AUTYPE

# 可选：自定义 DLL 路径（默认 D:\tdx_new\PYPlugins\TPythClient.dll）
# import os
# os.environ["TPYTHCLIENT_DLL"] = r"D:\tdx_new\PYPlugins\TPythClient.dll"

chan = CChan(
    code="000001",  # 也支持 000001.SZ / sh600000 / sz000001
    begin_time="2026-01-01",
    end_time="2026-04-04",
    data_src=DATA_SRC.TDX,
    lv_list=[KL_TYPE.K_DAY],
    autype=AUTYPE.QFQ,
)
```

说明：
- `DATA_SRC.TDX` 对应 `DataAPI/TdxAPI.py`。
- 依赖 `TdxLib/tqcenter.py` 与 `TPythClient.dll`。
- 当前支持级别：`K_DAY/K_WEEK/K_MON/K_5M/K_15M/K_30M/K_60M`。


---

### 常用行业名称

| 行业 | 说明 |
|------|------|
| 半导体 | 芯片行业 |
| 元器件 | 电子元器件 |
| 通信设备 | 通信设备制造 |
| 软件 | 软件服务 |
| 电气设备 | 电力设备 |

> 查看完整行业列表：`python scan_stocks.py --list-industries`

---

## 命令参数完整说明

### scan_stocks_cache.py 参数（本地缓存版，推荐）

| 参数 | 说明 | 示例 |
|------|------|------|
| `--codes` | 指定股票代码 | `--codes 000001 000002` |
| `--buy` | 筛选买入类型 | `--buy 2 3a 3b` |
| `--sell` | 筛选卖出类型 | `--sell 2s 3a` |
| `--weekly` | 使用周线分析 | `--weekly` |
| `--no-strict` | 关闭笔严格模式 | `--no-strict` |
| `--industry` | 按行业筛选 | `--industry 电子 半导体` |
| `--area` | 按地区筛选 | `--area 深圳 上海` |
| `--exclude-st` | 排除ST股票 | `--exclude-st` |
| `--group-by` | 按行业/地区分组 | `--group-by industry` |
| `--show-money-flow` | 显示个股资金流向 | `--show-money-flow` |
| `--sort-by-money-flow` | 按主力净流入排序 | `--sort-by-money-flow` |
| `--min-money-flow` | 最小主力净流入（万元） | `--min-money-flow 1000` |
| `--output` | 保存结果到文件 | `--output results.txt` |

### scan_stocks.py 参数（在线版）

| 参数 | 说明 | 示例 |
|------|------|------|
| `--codes` | 指定股票代码 | `--codes 000001 000002` |
| `--industry` | 按行业筛选 | `--industry 半导体 元器件` |
| `--area` | 按地区筛选 | `--area 深圳 上海` |
| `--exclude-st` | 排除ST股票 | `--exclude-st` |
| `--market` | 按市场筛选 | `--market 创业板 科创板` |
| `--limit` | 限制扫描数量 | `--limit 100` |
| `--buy` | 筛选买入类型 | `--buy 2 3a 3b` |
| `--sell` | 筛选卖出类型 | `--sell 2s 3a` |
| `--group-by` | 按行业/地区分组 | `--group-by industry` |
| `--list-industries` | 列出所有行业 | `--list-industries` |
| `--show-flow` | 显示板块资金流向 | `--show-flow` |
| `--show-money-flow` | 显示个股资金流向 | `--show-money-flow` |
| `--sort-by-money-flow` | 按主力净流入排序 | `--sort-by-money-flow` |
| `--min-money-flow` | 最小主力净流入（万元） | `--min-money-flow 1000` |
| `--output` | 保存结果到文件 | `--output results.txt` |

### cache_all_stocks.py 参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `--all` | 缓存所有A股 | `--all` |
| `--codes` | 指定股票代码 | `--codes 000001` |
| `--limit` | 限制数量 | `--limit 100` |
| `--kl-types` | K线周期类型 | `--kl-types DAY WEEK` |
| `--delay` | 请求延迟（秒） | `--delay 0.3` |
| `--begin` | 开始日期（默认2023-01-01） | `--begin 2023-01-01` |
| `--end` | 结束日期（默认今天） | `--end 2024-12-31` |

### update_data.py 参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `--all` | 更新所有已缓存股票 | `--all` |
| `--codes` | 指定股票代码 | `--codes 000001` |
| `--kl-types` | K线周期类型 | `--kl-types DAY WEEK` |
| `--refresh` | 清除缓存后重新获取 | `--refresh` |
| `--verbose` | 显示详细日志 | `--verbose` |
| `--only-missing` | 只补齐已缓存日线中的历史缺失区间 | `--all --only-missing` |

---

## 配置选项

### 环境变量 (.env)

```bash
# Tushare Token
TUSHARE_TOKEN=your_token_here

# DeepSeek API Key（AI 分析功能）
DEEPSEEK_API_KEY=your_deepseek_key_here

# 数据库（可选，默认 SQLite）
DATABASE_URL=sqlite:///./chan.db

# Redis（可选，用于高级缓存）
REDIS_URL=redis://localhost:6379/0
```

### 缠论配置

```python
from ChanAnalyzer import ChanAnalyzer
from Common.CEnum import KL_TYPE

config = {
    "bi_strict": True,           # 严格笔模式
    "bs_type": "1,1p,2,2s,3a,3b",  # 买卖点类型
    "macd": {"fast": 12, "slow": 26, "signal": 9},  # MACD 参数
}

analyzer = ChanAnalyzer(
    code="000001",
    kl_types=KL_TYPE.K_DAY,
    begin_date="2024-01-01",
    config=config
)
```

## 定时任务

### Windows 任务计划

```bat
# 每个交易日 15:30 更新数据
schtasks /create /tn "更新K线数据" /tr "python C:\path\to\scripts\update_data.py --all" /sc weekly /d mon-fri /st 15:30
```

### Linux Cron

```bash
# 每个交易日 15:30 更新数据
30 15 * * 1-5 cd /path/to/chan.py && python -m scripts.update_data --all
```

---
