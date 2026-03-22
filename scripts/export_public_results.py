"""
Export public scan results for the standalone static site.

This script keeps scanning on the Python side and writes compact JSON files
for a public, read-only frontend:
    - buy_scan_results.json
    - sell_scan_results.json
    - manifest.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import scan_stocks_cache


DEFAULT_BUY_TYPES = ["1", "1p", "2", "3a", "3b"]
DEFAULT_SELL_TYPES = ["1s", "2s", "3a", "3b"]


def normalize_amount_yi(value: Any) -> float | None:
    """Convert raw amount to yi yuan for the public payload."""
    if value is None:
        return None

    amount = float(value)
    if amount <= 0:
        return None
    return amount / scan_stocks_cache.AMOUNT_YI_UNIT


def get_latest_signal(signals: Sequence[Dict[str, Any]]) -> Dict[str, Any] | None:
    """Return the most recent signal by date string."""
    if not signals:
        return None
    return sorted(signals, key=lambda item: item.get("date", ""), reverse=True)[0]


def format_scan_results(
    results: Sequence[Dict[str, Any]],
    stock_info: Dict[str, Dict[str, Any]],
    trade_metrics: Dict[str, Dict[str, Any]] | None = None,
    cache_time: str | None = None,
) -> Dict[str, Any]:
    """Convert raw scan output to the public JSON contract."""
    formatted_stocks: List[Dict[str, Any]] = []
    trade_metrics = trade_metrics or {}

    for item in results:
        code = item["code"]
        info = stock_info.get(code, {})
        metrics = trade_metrics.get(code, {})
        signals = item.get("signals", [])
        formatted_stocks.append(
            {
                "code": code,
                "name": info.get("name", ""),
                "industry": info.get("industry", ""),
                "current_price": item.get("latest_price"),
                "amount": normalize_amount_yi(metrics.get("amount")),
                "turnover_rate": metrics.get("turnover_rate"),
                "change_pct": item.get("change_pct"),
                "signals": signals,
                "latest_signal": get_latest_signal(signals),
            }
        )

    return {
        "cache_time": cache_time or datetime.now().isoformat(),
        "stocks": formatted_stocks,
    }


def build_manifest(
    buy_payload: Dict[str, Any],
    sell_payload: Dict[str, Any],
    version: str = "1",
) -> Dict[str, Any]:
    """Build manifest metadata for the published site."""
    generated_at = max(
        buy_payload.get("cache_time", ""),
        sell_payload.get("cache_time", ""),
    )
    return {
        "generated_at": generated_at or datetime.now().isoformat(),
        "buy_count": len(buy_payload.get("stocks", [])),
        "sell_count": len(sell_payload.get("stocks", [])),
        "version": version,
    }


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    """Write JSON with UTF-8 and stable formatting."""
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def export_payloads(
    output_dir: Path,
    buy_payload: Dict[str, Any],
    sell_payload: Dict[str, Any],
    version: str = "1",
) -> None:
    """Persist all publishable JSON artifacts to the output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "buy_scan_results.json", buy_payload)
    write_json(output_dir / "sell_scan_results.json", sell_payload)
    write_json(output_dir / "manifest.json", build_manifest(buy_payload, sell_payload, version=version))


def filter_stock_codes_by_trade_metrics(
    stock_codes: Iterable[str],
    min_amount_yi: float | None = None,
    max_amount_yi: float | None = None,
    min_turnover_rate: float | None = None,
    max_turnover_rate: float | None = None,
) -> List[str]:
    """Filter stock codes by latest amount/turnover metrics using export CLI units."""
    return scan_stocks_cache.filter_stocks_by_trade_metrics(
        stock_codes=list(stock_codes),
        min_amount=(
            min_amount_yi * scan_stocks_cache.AMOUNT_YI_UNIT
            if min_amount_yi is not None
            else None
        ),
        max_amount=(
            max_amount_yi * scan_stocks_cache.AMOUNT_YI_UNIT
            if max_amount_yi is not None
            else None
        ),
        min_turnover_rate=min_turnover_rate,
        max_turnover_rate=max_turnover_rate,
    )


def scan_and_format(
    stock_codes: Iterable[str],
    buy_types: Sequence[str],
    sell_types: Sequence[str],
    cache_time: str | None = None,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Run buy/sell scans and convert them into public payloads."""
    stock_codes = list(stock_codes)

    buy_results = scan_stocks_cache.scan_stocks(
        stock_codes=stock_codes,
        buy_types=list(buy_types),
        sell_types=[],
        verbose=False,
    )
    # sell_results = scan_stocks_cache.scan_stocks(
    #     stock_codes=stock_codes,
    #     buy_types=[],
    #     sell_types=list(sell_types),
    #     verbose=False,
    # )
    sell_results = []

    codes = sorted(
        {
            *[item["code"] for item in buy_results],
            *[item["code"] for item in sell_results],
        }
    )
    stock_info = scan_stocks_cache.get_stock_info_bulk(codes) if codes else {}
    trade_metrics = scan_stocks_cache.get_latest_trade_metrics_bulk(codes) if codes else {}

    buy_payload = format_scan_results(
        buy_results,
        stock_info,
        trade_metrics=trade_metrics,
        cache_time=cache_time,
    )
    sell_payload = format_scan_results(
        sell_results,
        stock_info,
        trade_metrics=trade_metrics,
        cache_time=cache_time,
    )
    return buy_payload, sell_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export public scan results")
    parser.add_argument(
        "--output-dir",
        default="dist/publish",
        help="Directory for generated public JSON files",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Number of stock codes to scan, <= 0 means all",
    )
    parser.add_argument(
        "--buy-types",
        nargs="+",
        default=DEFAULT_BUY_TYPES,
        help="Buy signal types to include",
    )
    parser.add_argument(
        "--sell-types",
        nargs="+",
        default=DEFAULT_SELL_TYPES,
        help="Sell signal types to include",
    )
    parser.add_argument(
        "--version",
        default="1",
        help="Manifest version string",
    )
    parser.add_argument("--min-amount", type=float, help="最小最新成交额（亿元）")
    parser.add_argument("--max-amount", type=float, help="最大最新成交额（亿元）")
    parser.add_argument("--min-turnover-rate", type=float, help="最小最新换手率（%%）")
    parser.add_argument("--max-turnover-rate", type=float, help="最大最新换手率（%%）")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    all_codes = scan_stocks_cache.get_stock_list_from_db()
    stock_codes = all_codes if args.limit <= 0 else all_codes[: args.limit]
    stock_codes = filter_stock_codes_by_trade_metrics(
        stock_codes=stock_codes,
        min_amount_yi=args.min_amount,
        max_amount_yi=args.max_amount,
        min_turnover_rate=args.min_turnover_rate,
        max_turnover_rate=args.max_turnover_rate,
    )

    cache_time = datetime.now().isoformat()
    buy_payload, sell_payload = scan_and_format(
        stock_codes=stock_codes,
        buy_types=args.buy_types,
        sell_types=args.sell_types,
        cache_time=cache_time,
    )
    export_payloads(Path(args.output_dir), buy_payload, sell_payload, version=args.version)

    print(f"Exported public scan results to {args.output_dir}")
    print(f"Scanned codes: {len(stock_codes)}")
    print(f"Buy count: {len(buy_payload['stocks'])}")
    print(f"Sell count: {len(sell_payload['stocks'])}")


if __name__ == "__main__":
    main()
