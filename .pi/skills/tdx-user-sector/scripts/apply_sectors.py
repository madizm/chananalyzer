#!/usr/bin/env python
"""Apply TDX watchlist/custom-sector updates from a JSON config.

Run from project root:
    python .pi/skills/tdx-user-sector/scripts/apply_sectors.py sectors.json --replace
    python .pi/skills/tdx-user-sector/scripts/apply_sectors.py sectors.json --merge
    python .pi/skills/tdx-user-sector/scripts/apply_sectors.py sectors.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List


def find_project_root() -> Path:
    cwd = Path.cwd().resolve()
    for p in [cwd, *cwd.parents]:
        if (p / "TdxLib" / "tqcenter.py").exists() and (p / "DataAPI" / "TdxAPI.py").exists():
            return p
    raise RuntimeError("Cannot find project root containing TdxLib/tqcenter.py and DataAPI/TdxAPI.py")


PROJECT_ROOT = find_project_root()
sys.path.insert(0, str(PROJECT_ROOT))

from DataAPI.TdxAPI import CTdxAPI  # noqa: E402
from TdxLib.tqcenter import tq  # noqa: E402


def normalize_stock_code(code: str) -> str:
    value = str(code).strip().upper()
    if not value:
        raise ValueError("empty stock code")

    if "." in value:
        left, right = value.split(".", 1)
        if left in {"SH", "SZ", "BJ"} and right.isdigit():
            return f"{right}.{left}"
        return f"{left}.{right}"

    lower = value.lower()
    if lower.startswith(("sh", "sz", "bj")) and len(value) == 8:
        return f"{value[2:]}.{value[:2].upper()}"

    digits = re.sub(r"\D", "", value)
    if len(digits) != 6:
        raise ValueError(f"unsupported stock code format: {code}")
    if digits.startswith("6"):
        return f"{digits}.SH"
    if digits.startswith(("8", "4")):
        return f"{digits}.BJ"
    return f"{digits}.SZ"


def load_config(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("config must be a JSON list")

    sectors: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("each sector must be an object")
        block_code = str(item.get("block_code", "")).strip().upper()
        block_name = str(item.get("block_name", block_code)).strip() or block_code
        stocks = item.get("stocks", [])
        if not block_code:
            raise ValueError("block_code is required")
        if not isinstance(stocks, list):
            raise ValueError(f"stocks for {block_code} must be a list")
        sectors.append(
            {
                "block_code": block_code,
                "block_name": block_name,
                "stocks": [normalize_stock_code(c) for c in stocks],
            }
        )
    return sectors


def init_tdx() -> None:
    dll_path = os.getenv("TPYTHCLIENT_DLL", CTdxAPI._dll_path)
    tq.initialize(path=str(Path(__file__).resolve()), dll_path=dll_path)


def display_result(action: str, result: Any) -> None:
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            pass
    print(f"{action}: {result}")


def apply_sectors(sectors: Iterable[Dict[str, Any]], replace: bool, show: bool, dry_run: bool) -> None:
    for sector in sectors:
        block_code = sector["block_code"]
        block_name = sector["block_name"]
        stocks = sector["stocks"]

        print(f"\n== {block_code} {block_name} ({len(stocks)} stocks) ==")
        print(", ".join(stocks))
        if dry_run:
            continue

        if block_code != "ZXG":
            display_result("create", tq.create_sector(block_code=block_code, block_name=block_name))
            if replace:
                display_result("clear", tq.clear_sector(block_code=block_code))
        elif replace:
            # Built-in watchlist: clear by sending an empty list to ZXG.
            display_result("clear", tq.send_user_block(block_code="ZXG", stocks=[], show=False))

        display_result("add", tq.send_user_block(block_code=block_code, stocks=stocks, show=show))


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply TDX user-sector/watchlist updates from JSON")
    parser.add_argument("config", type=Path, help="JSON config path")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--replace", action="store_true", help="clear existing constituents before adding; default")
    mode.add_argument("--merge", action="store_true", help="append/add stocks without clearing")
    parser.add_argument("--show", action="store_true", help="switch TDX client to the target sector after adding")
    parser.add_argument("--dry-run", action="store_true", help="print parsed operations without calling TDX")
    args = parser.parse_args()

    sectors = load_config(args.config)
    replace = not args.merge

    if args.dry_run:
        apply_sectors(sectors, replace=replace, show=args.show, dry_run=True)
        return

    init_tdx()
    try:
        apply_sectors(sectors, replace=replace, show=args.show, dry_run=False)
        display_result("\nuser sectors", tq.get_user_sector())
    finally:
        tq.close()


if __name__ == "__main__":
    main()
