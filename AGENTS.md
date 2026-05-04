# AGENTS.md

Guidance for agentic coding assistants working in `chananalyzer`.

## Rule Sources
- No Cursor rules were found (`.cursor/rules/` and `.cursorrules` do not exist).
- No Copilot repository instruction file was found (`.github/copilot-instructions.md` does not exist).
- This file is the primary in-repo instruction source for coding agents.

## Project Overview
- Core Chan theory engine code is in top-level modules: `Bi/`, `Seg/`, `ZS/`, `KLine/`, `Math/`, `Plot/`, `Combiner/`, `BuySellPoint/`, `Common/`, `DataAPI/`.
- Higher-level orchestration and app-facing APIs live in `ChanAnalyzer/`.

## TODO

- [] 配置背离度数
- [] 在线画图
