# Repository Guidelines

## Project Structure & Module Organization
Core analysis logic lives in top-level packages such as `Bi/`, `Seg/`, `ZS/`, `KLine/`, `Math/`, `Plot/`, `DataAPI/`, and `Common/`. The higher-level orchestration layer is in `ChanAnalyzer/`, including AI prompts under `ChanAnalyzer/prompts/`. Entry-point scripts sit at the repository root (`scan_stocks.py`, `scan_stocks_cache.py`, `main.py`) and in `scripts/` for data sync and batch jobs. The FastAPI app and static assets are under `web/`, and `App/` contains the PyQt6 desktop scanner. `Debug/` is for local experiments, not production code.

## Build, Test, and Development Commands
Install dependencies with `pip install -r requirements.txt`.
Run the web app locally with `python web/start_server.py` or `python web/api.py`.
Refresh stock metadata with `python -m scripts.cache_stock_info`.
Preload market data with `python -m scripts.cache_all_stocks --all --kl-types DAY --limit 100`.
Run cached scanning with `python scan_stocks_cache.py --limit 50` or live scanning with `python scan_stocks.py --limit 50`.
If you add tests, run them with `pytest`.

## Coding Style & Naming Conventions
Follow existing Python style: 4-space indentation, snake_case for functions/modules, CamelCase for classes, and concise docstrings where behavior is non-obvious. Keep new modules aligned with the current package layout instead of introducing new top-level buckets casually. Prefer small helpers in `Common/` for shared utilities. `black` is listed in dependencies; format changed Python files with `black .` before submitting.

## Testing Guidelines
This repository currently does not include a dedicated `tests/` suite. For contributor changes, add focused `pytest` tests when you introduce isolated logic, using `test_*.py` naming. For integration-heavy changes, document manual verification steps in the PR, for example: `python web/start_server.py`, `python scan_stocks_cache.py --codes 000001`, or the relevant `scripts/` command.

## Commit & Pull Request Guidelines
Recent history uses short conventional prefixes such as `fix:` and `chore:`. Continue with clear, imperative subjects like `fix: handle empty sector flow response`. Keep commits scoped to one change. PRs should include a short summary, affected modules, verification steps, and screenshots for `web/` UI changes. Link the related issue when one exists.

## Configuration Tips
Set `TUSHARE_TOKEN` before data operations. AI features also require `DEEPSEEK_API_KEY` and `ai_config.yaml`. The web startup script forces `TUSHARE_PATH=/tmp` to avoid local permission issues; preserve that behavior in related changes.
