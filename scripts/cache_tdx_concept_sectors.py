"""
缓存通达信概念板块列表到 chan.db。

数据来源：
    tq.get_stock_list("12", list_type=1)

默认写入表：
    tdx_concept_sectors
    tdx_concept_sector_stocks
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_DB_PATH = PROJECT_ROOT / "chan.db"


def strip_market_suffix(code: str) -> str:
    """去除 .SZ/.SH 等市场后缀，和 stock_info.code 对齐。"""
    code = str(code or "").strip()
    if "." not in code:
        return code
    return code.split(".", 1)[0]


def normalize_sector_row(row: Any) -> dict[str, str]:
    """兼容 TDX 返回的 dict 或字符串格式。"""
    if isinstance(row, dict):
        code = str(
            row.get("Code")
            or row.get("code")
            or row.get("StockCode")
            or row.get("stock_code")
            or ""
        ).strip()
        name = str(
            row.get("Name")
            or row.get("name")
            or row.get("StockName")
            or row.get("stock_name")
            or ""
        ).strip()
        market = code.rsplit(".", 1)[1].upper() if "." in code else ""
        raw_json = json.dumps(row, ensure_ascii=False, sort_keys=True)
        return {"code": code, "name": name, "market": market, "raw_json": raw_json}

    text = str(row or "").strip()
    parts = text.replace("\t", ",").split(",")
    code = parts[0].strip() if parts else text
    name = parts[1].strip() if len(parts) > 1 else ""
    market = code.rsplit(".", 1)[1].upper() if "." in code else ""
    return {
        "code": code,
        "name": name,
        "market": market,
        "raw_json": json.dumps(row, ensure_ascii=False),
    }


def normalize_stock_row(row: Any) -> dict[str, str]:
    """兼容 TDX 成分股返回的 dict 或字符串格式。"""
    if isinstance(row, dict):
        code = str(
            row.get("Code")
            or row.get("code")
            or row.get("StockCode")
            or row.get("stock_code")
            or ""
        ).strip()
        name = str(
            row.get("Name")
            or row.get("name")
            or row.get("StockName")
            or row.get("stock_name")
            or ""
        ).strip()
        market = code.rsplit(".", 1)[1].upper() if "." in code else ""
        raw_json = json.dumps(row, ensure_ascii=False, sort_keys=True)
        return {"code": code, "name": name, "market": market, "raw_json": raw_json}

    text = str(row or "").strip()
    parts = text.replace("\t", ",").split(",")
    code = parts[0].strip() if parts else text
    name = parts[1].strip() if len(parts) > 1 else ""
    market = code.rsplit(".", 1)[1].upper() if "." in code else ""
    return {
        "code": code,
        "name": name,
        "market": market,
        "raw_json": json.dumps(row, ensure_ascii=False),
    }


def fetch_concept_sectors(dll_path: str = "") -> list[dict[str, str]]:
    """从 TDX 获取概念板块列表。"""
    from TdxLib.tqcenter import tq

    strategy_path = str(Path(__file__).resolve())
    dll_path = dll_path or os.environ.get("TPYTHCLIENT_DLL", "")

    try:
        tq.initialize(path=strategy_path, dll_path=dll_path)
        raw_rows = tq.get_stock_list("12", list_type=1)
        if not raw_rows:
            return []

        sectors: list[dict[str, str]] = []
        seen_codes: set[str] = set()
        for row in raw_rows:
            sector = normalize_sector_row(row)
            code = sector["code"]
            if not code or code in seen_codes:
                continue
            seen_codes.add(code)
            sectors.append(sector)
        return sectors
    finally:
        try:
            tq.close()
        except Exception:
            pass


def fetch_concept_data(
    dll_path: str = "",
    include_stocks: bool = True,
    delay: float = 0.0,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """从 TDX 获取概念板块及其成分股。"""
    from TdxLib.tqcenter import tq

    strategy_path = str(Path(__file__).resolve())
    dll_path = dll_path or os.environ.get("TPYTHCLIENT_DLL", "")

    try:
        tq.initialize(path=strategy_path, dll_path=dll_path)
        raw_rows = tq.get_stock_list("12", list_type=1)
        if not raw_rows:
            return [], []

        sectors: list[dict[str, str]] = []
        seen_codes: set[str] = set()
        for row in raw_rows:
            sector = normalize_sector_row(row)
            code = sector["code"]
            if not code or code in seen_codes:
                continue
            seen_codes.add(code)
            sectors.append(sector)

        if not include_stocks:
            return sectors, []

        sector_stocks: list[dict[str, str]] = []
        for idx, sector in enumerate(sectors, 1):
            sector_code = sector["code"]
            rows = tq.get_stock_list_in_sector(sector_code, block_type=0, list_type=1)
            if not rows:
                print(f"概念板块无成分股或获取失败: {sector_code} {sector['name']}")
                continue

            seen_stock_codes: set[str] = set()
            for row in rows:
                stock = normalize_stock_row(row)
                stock_code = stock["code"]
                if not stock_code or stock_code in seen_stock_codes:
                    continue
                seen_stock_codes.add(stock_code)
                sector_stocks.append(
                    {
                        "sector_code": sector_code,
                        "code": strip_market_suffix(stock_code),
                        "stock_code": stock_code,
                        "stock_name": stock["name"],
                        "market": stock["market"],
                        "raw_json": stock["raw_json"],
                    }
                )

            if idx % 25 == 0 or idx == len(sectors):
                print(f"成分股进度: {idx}/{len(sectors)}")
            if delay > 0:
                time.sleep(delay)

        return sectors, sector_stocks
    finally:
        try:
            tq.close()
        except Exception:
            pass


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tdx_concept_sectors (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            market TEXT NOT NULL DEFAULT '',
            source_market TEXT NOT NULL DEFAULT '12',
            raw_json TEXT,
            updated_at TIMESTAMP NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tdx_concept_sector_stocks (
            sector_code TEXT NOT NULL,
            code TEXT NOT NULL DEFAULT '',
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL DEFAULT '',
            market TEXT NOT NULL DEFAULT '',
            raw_json TEXT,
            updated_at TIMESTAMP NOT NULL,
            PRIMARY KEY (sector_code, stock_code)
        )
        """
    )
    try:
        conn.execute("ALTER TABLE tdx_concept_sector_stocks ADD COLUMN code TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise
    conn.execute(
        """
        UPDATE tdx_concept_sector_stocks
        SET code = CASE
            WHEN instr(stock_code, '.') > 0 THEN substr(stock_code, 1, instr(stock_code, '.') - 1)
            ELSE stock_code
        END
        WHERE code = ''
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tdx_concept_sector_stocks_stock
        ON tdx_concept_sector_stocks (stock_code)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tdx_concept_sector_stocks_code
        ON tdx_concept_sector_stocks (code)
        """
    )
    conn.commit()


def save_concept_sectors(
    sectors: list[dict[str, str]],
    db_path: Path,
    replace: bool = True,
) -> int:
    """保存概念板块列表，默认先清空旧数据再写入。"""
    if not sectors:
        return 0

    conn = sqlite3.connect(db_path)
    try:
        ensure_table(conn)
        if replace:
            conn.execute("DELETE FROM tdx_concept_sectors")

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.executemany(
            """
            INSERT OR REPLACE INTO tdx_concept_sectors
                (code, name, market, source_market, raw_json, updated_at)
            VALUES (?, ?, ?, '12', ?, ?)
            """,
            [
                (
                    sector["code"],
                    sector["name"],
                    sector["market"],
                    sector["raw_json"],
                    now,
                )
                for sector in sectors
            ],
        )
        conn.commit()
        return len(sectors)
    finally:
        conn.close()


def save_concept_data(
    sectors: list[dict[str, str]],
    sector_stocks: list[dict[str, str]],
    db_path: Path,
    replace: bool = True,
) -> tuple[int, int]:
    """保存概念板块和成分股关系。"""
    if not sectors:
        return 0, 0

    conn = sqlite3.connect(db_path)
    try:
        ensure_table(conn)
        if replace:
            conn.execute("DELETE FROM tdx_concept_sector_stocks")
            conn.execute("DELETE FROM tdx_concept_sectors")

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.executemany(
            """
            INSERT OR REPLACE INTO tdx_concept_sectors
                (code, name, market, source_market, raw_json, updated_at)
            VALUES (?, ?, ?, '12', ?, ?)
            """,
            [
                (
                    sector["code"],
                    sector["name"],
                    sector["market"],
                    sector["raw_json"],
                    now,
                )
                for sector in sectors
            ],
        )

        conn.executemany(
            """
            INSERT OR REPLACE INTO tdx_concept_sector_stocks
                (sector_code, code, stock_code, stock_name, market, raw_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item["sector_code"],
                    item["code"],
                    item["stock_code"],
                    item["stock_name"],
                    item["market"],
                    item["raw_json"],
                    now,
                )
                for item in sector_stocks
            ],
        )
        conn.commit()
        return len(sectors), len(sector_stocks)
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="缓存 TDX 概念板块列表到 SQLite")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="SQLite 数据库路径")
    parser.add_argument(
        "--dll-path",
        default="",
        help="TPythClient.dll 路径；为空时使用 TPYTHCLIENT_DLL 或 TdxLib 默认路径",
    )
    parser.add_argument("--append", action="store_true", help="不清空旧数据，改为追加/覆盖")
    parser.add_argument("--dry-run", action="store_true", help="只获取并打印，不写入数据库")
    parser.add_argument("--sectors-only", action="store_true", help="只保存概念板块，不拉取成分股")
    parser.add_argument("--delay", type=float, default=0.0, help="每个板块成分股请求之间的延迟秒数")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db_path).resolve()

    print("正在从 TDX 获取概念板块列表 market=12, list_type=1 ...")
    sectors, sector_stocks = fetch_concept_data(
        dll_path=args.dll_path,
        include_stocks=not args.sectors_only,
        delay=args.delay,
    )
    if not sectors:
        print("TDX 未返回概念板块数据，请检查客户端、DLL 和登录状态")
        return 1

    print(f"获取到 {len(sectors)} 个概念板块")
    if not args.sectors_only:
        print(f"获取到 {len(sector_stocks)} 条概念板块成分股关系")
    for sector in sectors[:10]:
        print(f"{sector['code']}\t{sector['name']}")

    if args.dry_run:
        return 0

    sector_count, stock_count = save_concept_data(
        sectors=sectors,
        sector_stocks=sector_stocks,
        db_path=db_path,
        replace=not args.append,
    )
    print(f"已保存 {sector_count} 个概念板块到 {db_path} 的 tdx_concept_sectors 表")
    if not args.sectors_only:
        print(f"已保存 {stock_count} 条成分股关系到 tdx_concept_sector_stocks 表")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
