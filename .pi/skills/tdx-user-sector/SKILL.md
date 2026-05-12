---
name: tdx-user-sector
description: Add stocks to 通达信自选股 or create/update 通达信自定义板块 using the project's bundled TDX API. Use when the user asks to create custom sectors, add watchlist stocks, group stock codes into TDX blocks, or update 自选股/自定义板块 or query 持仓股.
---

# TDX User Sector Skill

用于把用户给出的股票清单/主题表格整理成通达信自选股或自定义板块，并通过项目内置 `TdxLib.tqcenter` 写入/查询通达信客户端自定义板块。

## When to use

Use this skill when the user asks for any of:

- 创建通达信自定义板块 / 自选股板块
- 添加股票到自选股 `ZXG`
- 按行业、主题、表格分组创建板块
- 修改、清空、重命名、删除通达信自定义板块
- 查询自定义板块成分股，尤其是“持仓股”板块
- 使用 TDX API / `send_user_block` / `create_sector` / `get_user_sector` / `get_stock_list_in_sector`

## Required environment

- 通达信客户端已启动并登录。
- 项目内 `TdxLib/tqcenter.py` 可用。
- 初始化方式应参考 `scripts/update_data.py` 与 `DataAPI/TdxAPI.py`：使用项目内置 `TdxLib.tqcenter`，不要直接依赖外部 `tqcenter` 包。
- 如 DLL 路径不是默认值，使用环境变量 `TPYTHCLIENT_DLL`。

## Query workflow

当用户说“查询持仓股”、“持仓股有哪些”、“查询持仓股板块”时，优先按**自定义板块**查询，而不是用 `get_stock_list('1')` 查询交易账户持仓。

1. 初始化 TDX：使用项目内置 `DataAPI.TdxAPI.CTdxAPI._dll_path` 和 `TdxLib.tqcenter.tq.initialize(...)`。
2. 调用 `tq.get_user_sector()` 获取自定义板块列表。
3. 在结果中查找 `Name == '持仓股'` 或名称包含“持仓”的板块；当前常用代码为 `HOLDING`。
4. 调用 `tq.get_stock_list_in_sector(block_code, block_type=1, list_type=1)` 查询成分股。
5. 向用户输出 `Code` + `Name` 列表。

可直接运行 helper：

```bash
python .pi/skills/tdx-user-sector/scripts/query_sector.py 持仓股
```

输出 JSON：

```bash
python .pi/skills/tdx-user-sector/scripts/query_sector.py 持仓股 --json
```

> 注意：`tq.get_stock_list('1', list_type=1)` 是交易账户持仓分类，可能返回空；用户提到“自定义板块叫持仓股”时必须使用上面的自定义板块查询流程。

## Update workflow

1. Parse the user's stocks into sectors.
   - A 股代码统一转换为 `000001.SZ` / `600000.SH` / `688001.SH` / `430xxx.BJ` 格式。
   - 保留用户给出的分组语义作为板块名称。
2. Choose short ASCII `block_code` values for TDX custom sectors.
   - Prefer 3-8 uppercase letters/numbers, e.g. `CCL`, `HPCB`, `UPCB`.
   - 自选股固定 `block_code='ZXG'`。
3. Decide update mode:
   - 默认“精确同步/替换”：创建板块 -> 清空板块 -> 添加当前股票清单。
   - 如果用户明确说“追加”，不要清空，直接添加。
4. If applying directly, generate a temporary JSON config and run:

```bash
python .pi/skills/tdx-user-sector/scripts/apply_sectors.py path/to/sectors.json --replace
```

Use `--merge` for append mode, `--dry-run` for preview only.

## JSON config format

```json
[
  {
    "block_code": "CCL",
    "block_name": "覆铜板CCL",
    "stocks": ["600183.SH", "688519.SH"]
  },
  {
    "block_code": "ZXG",
    "block_name": "自选股",
    "stocks": ["000001.SZ"]
  }
]
```

Notes:

- `block_code='ZXG'` is the built-in watchlist. Do not call `create_sector` for `ZXG`; only call `send_user_block`.
- For custom sectors, call `create_sector`; ignore/print failure if it already exists, then update constituents.
- Use `clear_sector` only in replace mode.

## Helper script

See `scripts/apply_sectors.py` in this skill. It:

- Loads JSON sector config.
- Initializes TDX using the project wrapper and `TPYTHCLIENT_DLL`.
- Creates custom sectors when needed.
- Replaces or merges constituents using `clear_sector` and `send_user_block`.
- Closes TDX connection in `finally`.

See `scripts/query_sector.py` in this skill. It:

- Finds custom sectors via `tq.get_user_sector()`.
- Matches sector code/name, defaulting to `持仓股`.
- Queries constituents with `tq.get_stock_list_in_sector(..., block_type=1, list_type=1)`.
- Prints tabular output or raw JSON with `--json`.

## API reference

Project docs:

- `docs/tdx_api/06_user_sector.md`
- `docs/tdx_api/07_get_stock_list_in_sector.md`

Core functions:

- `tq.create_sector(block_code, block_name)`
- `tq.clear_sector(block_code)`
- `tq.send_user_block(block_code, stocks, show=False)`
- `tq.get_user_sector()`
- `tq.get_stock_list_in_sector(block_code, block_type=1, list_type=1)`
- `tq.delete_sector(block_code)`
- `tq.rename_sector(block_code, block_name)`
