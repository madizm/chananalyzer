#!/usr/bin/env python
"""Query TDX custom sector constituents.

Run from project root:
    python .pi/skills/tdx-user-sector/scripts/query_sector.py 持仓股
    python .pi/skills/tdx-user-sector/scripts/query_sector.py HOLDING
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, List, Tuple


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


def parse_result(result: Any) -> Any:
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return result
    return result


def init_tdx() -> None:
    dll_path = os.getenv("TPYTHCLIENT_DLL", CTdxAPI._dll_path)
    tq.initialize(path=str(PROJECT_ROOT), dll_path=dll_path)


def find_matching_sectors(query: str, sectors: Any) -> List[Tuple[str, str]]:
    q = query.strip().upper()
    matches: List[Tuple[str, str]] = []
    if isinstance(sectors, list):
        for item in sectors:
            if not isinstance(item, dict):
                continue
            code = str(item.get("Code", "")).strip()
            name = str(item.get("Name", "")).strip()
            if q in {code.upper(), name.upper()} or query in name:
                matches.append((code, name))
    return matches


def main() -> None:
    parser = argparse.ArgumentParser(description="Query TDX custom-sector constituents")
    parser.add_argument("sector", nargs="?", default="持仓股", help="custom sector code or name; default: 持仓股")
    parser.add_argument("--json", action="store_true", help="print raw JSON only")
    args = parser.parse_args()

    init_tdx()
    try:
        sectors = parse_result(tq.get_user_sector())
        matches = find_matching_sectors(args.sector, sectors)
        if not matches:
            # TDX also accepts custom sector short name directly with block_type=1.
            matches = [(args.sector, args.sector)]

        output = []
        for code, name in matches:
            stocks = parse_result(tq.get_stock_list_in_sector(code, block_type=1, list_type=1))
            output.append({"block_code": code, "block_name": name, "stocks": stocks})

        if args.json:
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return

        for sector in output:
            stocks = sector["stocks"]
            count = len(stocks) if isinstance(stocks, list) else 0
            print(f"\n== {sector['block_code']} {sector['block_name']} ({count} stocks) ==")
            if isinstance(stocks, list):
                for item in stocks:
                    if isinstance(item, dict):
                        print(f"{item.get('Code', '')}\t{item.get('Name', '')}")
                    else:
                        print(item)
            else:
                print(stocks)
    finally:
        tq.close()


if __name__ == "__main__":
    main()
