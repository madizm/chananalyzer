"""
简单过滤：指定时间段内，上涨 K 线成交额总和大于下跌 K 线成交额总和。

上涨/下跌按单根 K 线 close > open / close < open 判断。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from strategies.amount_flow_filter import (  # noqa: E402
    DB_PATH,
    AmountFlowStats,
    filter_codes_by_up_amount,
    load_amount_flow_stats,
    normalize_level,
    parse_time,
)


def get_stock_list_from_db(
    db_path: Path = DB_PATH,
    exclude_bj: bool = True,
    exclude_b_share: bool = True,
    exclude_cdr: bool = True,
    limit: Optional[int] = None,
) -> List[str]:
    import sqlite3

    if not db_path.exists():
        raise FileNotFoundError(f"数据库文件不存在: {db_path}")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT DISTINCT code
            FROM kline_data
            WHERE kl_type = 'DAY'
            ORDER BY code
            """)
        rows = cur.fetchall()
    finally:
        conn.close()

    stock_list: List[str] = []
    for (code,) in rows:
        if exclude_bj and (code.startswith("8") or code.startswith("43")):
            continue
        if exclude_b_share and (code.startswith("200") or code.startswith("900")):
            continue
        if exclude_cdr and code.startswith("920"):
            continue
        stock_list.append(code)

    if limit is not None and limit > 0:
        return stock_list[:limit]
    return stock_list


def get_stock_names_bulk(
    stock_codes: List[str], db_path: Path = DB_PATH
) -> Dict[str, str]:
    if not stock_codes:
        return {}

    names = {code: code for code in stock_codes}
    if not db_path.exists():
        return names

    import sqlite3

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    try:
        placeholders = ",".join("?" * len(stock_codes))
        cur.execute(
            f"""
            SELECT code, name
            FROM stock_info
            WHERE code IN ({placeholders})
            """,
            stock_codes,
        )
        for code, name in cur.fetchall():
            names[code] = name or code
    except sqlite3.Error:
        return names
    finally:
        conn.close()

    return names


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="过滤上涨成交额总和大于下跌成交额总和的股票"
    )
    parser.add_argument("--codes", nargs="+", help="股票代码列表，如 000001 600519")
    parser.add_argument(
        "--begin", required=True, help="开始时间，如 2026-04-01 或 2026-04-01 09:30:00"
    )
    parser.add_argument(
        "--end", required=True, help="结束时间，如 2026-04-20 或 2026-04-20 15:00:00"
    )
    parser.add_argument(
        "--level",
        required=True,
        choices=["DAY", "WEEK", "MON", "5M", "15M", "30M"],
        help="K线级别",
    )
    parser.add_argument("--limit", type=int, default=50, help="未指定 codes 时扫描上限")
    parser.add_argument(
        "--all", action="store_true", help="扫描全部股票（忽略 --limit）"
    )
    parser.add_argument(
        "--db-path", default=str(DB_PATH), help="SQLite 数据库路径，默认 chan.db"
    )
    parser.add_argument(
        "--show-all",
        action="store_true",
        help="输出所有股票统计；默认只输出通过过滤的股票",
    )
    parser.add_argument(
        "--show-code-name-only",
        action="store_true",
        help="仅输出通过过滤的股票代码和名称，不输出统计明细和汇总",
    )
    return parser.parse_args()


def print_result(stats: AmountFlowStats, *, passed_only: bool) -> None:
    status = "通过" if stats.passed else "未通过"
    if passed_only and not stats.passed:
        return
    print(
        f"{status} {stats.code} {stats.level} "
        f"bars={stats.bar_count} "
        f"up={stats.up_amount:.2f} "
        f"down={stats.down_amount:.2f} "
        f"flat={stats.flat_amount:.2f} "
        f"net={stats.net_amount:.2f}"
    )


def main() -> None:
    args = parse_args()
    db_path = Path(args.db_path)
    begin = parse_time(args.begin)
    end = parse_time(args.end, end_of_day=True)
    if begin > end:
        raise ValueError("--begin 不能晚于 --end")

    level = normalize_level(args.level)
    if args.codes:
        stock_codes = args.codes
    else:
        stock_codes = get_stock_list_from_db(
            db_path=db_path,
            limit=None if args.all else args.limit,
        )

    if not stock_codes:
        print("没有可扫描的股票")
        return

    if args.show_code_name_only:
        results = filter_codes_by_up_amount(
            codes=stock_codes,
            begin=begin,
            end=end,
            level=level,
            db_path=db_path,
        )
        stock_names = get_stock_names_bulk(
            [stats.code for stats in results], db_path=db_path
        )
        for stats in results:
            print(f"{stats.code} {stock_names.get(stats.code, stats.code)}")
        return

    print(f"开始过滤，股票数量: {len(stock_codes)}")
    print("规则: 上涨K线(close > open)成交额总和 > 下跌K线(close < open)成交额总和")
    print(
        f"时间段: {begin.strftime('%Y-%m-%d %H:%M:%S')} ~ "
        f"{end.strftime('%Y-%m-%d %H:%M:%S')}；级别: {level}"
    )

    if args.show_all:
        results: List[AmountFlowStats] = []
        for code in stock_codes:
            stats = load_amount_flow_stats(
                code=code,
                begin=begin,
                end=end,
                level=level,
                db_path=db_path,
            )
            results.append(stats)
            print_result(stats, passed_only=False)
        passed_count = sum(1 for stats in results if stats.passed)
    else:
        results = filter_codes_by_up_amount(
            codes=stock_codes,
            begin=begin,
            end=end,
            level=level,
            db_path=db_path,
        )
        for stats in results:
            print_result(stats, passed_only=True)
        passed_count = len(results)

    print("\n过滤完成")
    print(f"扫描股票数: {len(stock_codes)}")
    print(f"通过股票数: {passed_count}")


if __name__ == "__main__":
    # python scripts/filter_up_amount.py --codes 000001 600519 --begin 2026-04-01 --end 2026-04-20 --level 30M
    main()
