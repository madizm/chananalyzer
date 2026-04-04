# AGENTS.md

Guidance for agentic coding assistants working in `chananalyzer`.

## Rule Sources
- No Cursor rules were found (`.cursor/rules/` and `.cursorrules` do not exist).
- No Copilot repository instruction file was found (`.github/copilot-instructions.md` does not exist).
- This file is the primary in-repo instruction source for coding agents.

## Project Overview
- Core Chan theory engine code is in top-level modules: `Bi/`, `Seg/`, `ZS/`, `KLine/`, `Math/`, `Plot/`, `Combiner/`, `BuySellPoint/`, `Common/`, `DataAPI/`.
- Higher-level orchestration and app-facing APIs live in `ChanAnalyzer/`.
- Command-line entry points: `scan_stocks.py`, `scan_stocks_cache.py`, `main.py`, and scripts under `scripts/`.
- FastAPI backend and static web UI live in `web/`.
- PyQt desktop scanner is `App/ashare_bsp_scanner_gui.py`.
- `Debug/` contains local experiments/demo scripts; avoid shipping production logic there.

## Environment and Setup
- Python: use a modern 3.9+ interpreter (project dependencies assume this range).
- Install deps: `pip install -r requirements.txt`.
- Required env var for market data: `TUSHARE_TOKEN`.
- Required env var for AI flows: `DEEPSEEK_API_KEY`.
- Optional config file for AI orchestration: `ai_config.yaml`.
- Keep `TUSHARE_PATH=/tmp` behavior in web/data scripts (used to avoid token file permission issues).

## Build / Run Commands
- Start web server (recommended): `python web/start_server.py`.
- Start API directly: `python web/api.py`.
- Start minimal API variant (debug/dev): `python web/api_simple.py`.
- Check service health: open `http://localhost:8000/api/health` after startup.
- Run cached scanner (faster, local DB): `python scan_stocks_cache.py --limit 50`.
- Run live scanner (Tushare API): `python scan_stocks.py --limit 50`.
- Cache stock metadata: `python -m scripts.cache_stock_info`.
- Preload K-line data sample: `python -m scripts.cache_all_stocks --all --kl-types DAY --limit 100`.
- Update cached K-line data: `python -m scripts.update_data --all`.
- Analyze one stock quickly: `python -m scripts.analyze_stock --code 000001`.

## Formatting / Linting / Type Commands
- Format all Python files: `python -m black .`.
- Format specific files: `python -m black path/to/file.py`.
- No repository-configured `ruff`, `flake8`, `isort`, or `mypy` config was found.
- Do not introduce new lint/type tools in PRs unless explicitly requested.
- Keep changes style-consistent with nearby code when formatter output would be too broad.

## Test Commands (Pytest)
- Run all tests: `python -m pytest`.
- Run verbose tests: `python -m pytest -v`.
- Run a single test file: `python -m pytest path/to/test_file.py`.
- Run one test case: `python -m pytest path/to/test_file.py::test_name`.
- Run one test method: `python -m pytest path/to/test_file.py::TestClass::test_method`.
- Filter by keyword: `python -m pytest -k "keyword" -v`.
- Stop on first failure: `python -m pytest -x`.
- The repo currently has little/no committed pytest suite; add targeted tests with each isolated logic change.

## Test File Placement and Scope
- Prefer adding tests near changed behavior using `tests/` if introduced, otherwise follow existing project conventions.
- Name files as `test_*.py` and functions as `test_*` for pytest discovery.
- Avoid broad integration tests that require full market downloads unless explicitly requested.
- For deterministic tests, mock network/data source boundaries (`tushare`, `baostock`, filesystem cache).
- Keep fixtures small and focused on one behavior.

## Manual Verification (When No Automated Tests)
- API changes: run `python web/start_server.py` and hit affected endpoints.
- Scanner changes: run `python scan_stocks_cache.py --codes 000001` for a quick smoke test.
- Data pipeline changes: run the exact script touched (for example `scripts/cache_all_stocks.py` or `scripts/update_data.py`) with a small `--limit`.
- Include manual verification steps in PR descriptions.

## Code Organization Rules
- Keep new modules inside existing package buckets; avoid creating new top-level directories casually.
- Prefer extending `ChanAnalyzer/` for app orchestration and `Common/` for reusable helpers.
- Keep CLI concerns in script/entry files, and core business logic in importable modules.
- Avoid cross-layer coupling (for example, do not put web-only response shaping into low-level analysis classes).

## Python Style and Formatting
- 4-space indentation, UTF-8 source, and Black-compatible formatting.
- Use snake_case for functions/variables/modules; use CamelCase for classes.
- Keep functions focused and reasonably short; extract helpers for repeated logic.
- Write concise docstrings for public functions/classes and non-obvious behavior.
- Prefer explicit returns and guard clauses over deeply nested conditionals.

## Imports
- Group imports by standard library, third-party, then local modules.
- Prefer absolute imports from repo root packages (for example `from ChanAnalyzer...`, `from Common...`).
- Avoid wildcard imports.
- Keep import side effects intentional; this repo has a few (env/token patching) patterns that must run early.
- In hot paths or startup-sensitive modules, lazy imports are acceptable when they avoid heavy import chains.
- When touching scripts that patch `tushare`, keep patch setup before code paths that instantiate API clients.

## Typing Guidelines
- Add type hints for new/changed function signatures where practical.
- Use `dict[str, Any]`, `list[T]`, and `Optional[T]`/`T | None` consistently with surrounding file style.
- Prioritize typing at module boundaries (public APIs, data transforms, DB/web interfaces).
- Avoid over-complicated type gymnastics; readability is preferred.

## Naming Conventions
- Follow domain naming already used by the project (for example Chan-related abbreviations like `kl`, `bi`, `zs`, `bsp`).
- Preserve established class prefixes where present (`CChan`, `CChanConfig`, etc.) instead of renaming for style purity.
- Name booleans clearly (`is_...`, `has_...`, `enable_...`).
- Name CLI flags and config keys to match existing conventions.

## Error Handling
- Raise specific exceptions for invalid input/state (`ValueError`, `FileNotFoundError`, etc.).
- In core Chan engine paths, prefer `CChanException` + `ErrCode` where that pattern already exists.
- Avoid bare `except:`; catch explicit exception types when possible.
- If catching broad exceptions at boundaries (CLI/API), include context in message/logs.
- Do not silently swallow exceptions unless intentionally best-effort (and then log appropriately).
- Keep user-facing API errors stable and actionable.

## API and CLI Behavior
- Preserve existing CLI flag semantics; prefer additive flags over breaking renames.
- Keep FastAPI response shapes backward-compatible unless a change is explicitly requested.
- Return clear error messages for invalid params (date ranges, level combinations, empty code lists).
- For long-running scans, preserve progress/status reporting patterns instead of replacing them.

## Logging and Output
- Use `logging` for long-running scripts/services; use `print` only for user-facing CLI progress where already established.
- Keep logs concise and include key identifiers (stock code, period, data source) for debugging.
- Avoid noisy per-item logs in large loops unless behind a verbose/debug option.

## Data and Config Safety
- Never hardcode secrets or tokens.
- Read configuration from env vars or existing config files.
- Keep `.env` local and uncommitted; `.env.example` is for placeholders only.
- For scripts that touch external APIs, preserve existing rate-limit and delay controls.

## Database and I/O Practices
- SQLite (`chan.db`) is the default local cache DB; preserve compatibility.
- Use context-appropriate DB/session helpers from `ChanAnalyzer.database` where available.
- Keep file paths project-root aware (`pathlib.Path` preferred for new code).
- Validate file existence and input ranges before expensive operations.

## PR and Commit Expectations
- Use concise conventional commit prefixes seen in history (`fix:`, `feat:`, `chore:`, `refactor:`, `docs:`, `test:`).
- Keep commits focused to one logical change.
- In PRs, include: what changed, why, affected modules, and verification steps.
- For web UI changes, include screenshots or short recordings when possible.

## Agent Workflow Expectations
- Before editing, read nearby code to match local conventions.
- Prefer minimal, targeted diffs over broad rewrites.
- Run formatter/tests for changed scope whenever feasible.
- If tests are absent, run a relevant smoke command and document it.
- Do not perform destructive git operations unless explicitly requested.

## Change Review Checklist
- Verify commands in docs/scripts still run from repository root.
- Verify imports do not introduce circular dependencies in `ChanAnalyzer/`.
- Verify env var behavior (`TUSHARE_TOKEN`, `DEEPSEEK_API_KEY`, `TUSHARE_PATH`) is preserved.
- Verify JSON/file outputs remain UTF-8 and backward compatible.
- Prefer small commits with clear scope and conventional message prefix.
