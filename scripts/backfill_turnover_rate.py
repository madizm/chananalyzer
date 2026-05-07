"""
回填 kline_data.turnover_rate

默认只更新 turnover_rate 为空的 K 线记录，不覆盖已有值。

使用方法:
    python -m scripts.backfill_turnover_rate --codes 000001 600000 --kl-types DAY
    python -m scripts.backfill_turnover_rate --all --kl-types DAY 30M
    python -m scripts.backfill_turnover_rate --all --dry-run
    python -m scripts.backfill_turnover_rate --codes 000001 --force
"""

import argparse
import logging
import os
import sys
from typing import Dict, Iterable, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ChanAnalyzer.database import KLineData, get_db, init_db
from DataAPI.TdxAPI import CTdxAPI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def normalize_kl_type(kl_type: str) -> str:
    value = str(kl_type).strip().upper()
    aliases = {
        "K_DAY": "DAY",
        "K_WEEK": "WEEK",
        "K_MON": "MON",
        "K_1M": "1M",
        "K_5M": "5M",
        "K_15M": "15M",
        "K_30M": "30M",
        "K_60M": "60M",
        "DAY": "DAY",
        "WEEK": "WEEK",
        "MON": "MON",
        "1M": "1M",
        "5M": "5M",
        "15M": "15M",
        "30M": "30M",
        "60M": "60M",
    }
    if value not in aliases:
        raise ValueError(f"不支持的 kl_type: {kl_type}")
    return aliases[value]


def calc_turnover_rate(
    volume: Optional[float],
    active_capital: Optional[float],
) -> Optional[float]:
    return CTdxAPI._calc_turnover_rate(volume, active_capital)


def get_distinct_codes(
    codes: Optional[Iterable[str]],
    kl_types: Optional[List[str]],
    force: bool,
) -> List[str]:
    with get_db() as db:
        query = db.query(KLineData.code).distinct()
        if codes:
            query = query.filter(
                KLineData.code.in_([str(code).strip() for code in codes])
            )
        if kl_types:
            query = query.filter(KLineData.kl_type.in_(kl_types))
        if not force:
            query = query.filter(KLineData.turnover_rate.is_(None))
        return sorted(row[0] for row in query.all())


def backfill_turnover_rate(
    codes: Optional[Iterable[str]] = None,
    kl_types: Optional[List[str]] = None,
    force: bool = False,
    dry_run: bool = False,
    limit: Optional[int] = None,
) -> Dict[str, int]:
    init_db()

    if kl_types:
        kl_types = [normalize_kl_type(kl_type) for kl_type in kl_types]

    code_list = get_distinct_codes(codes, kl_types, force)
    if limit is not None:
        code_list = code_list[:limit]

    stats = {
        "codes": len(code_list),
        "updated": 0,
        "skipped_no_active_capital": 0,
        "skipped_no_rate": 0,
    }

    if not code_list:
        return stats

    CTdxAPI.do_init()
    try:
        for code in code_list:
            stock_code = CTdxAPI._normalize_code(code)
            active_capital = CTdxAPI._get_active_capital(stock_code)
            if active_capital is None:
                stats["skipped_no_active_capital"] += 1
                logger.warning("[%s] 无法获取 ActiveCapital，跳过", code)
                continue

            with get_db() as db:
                query = db.query(KLineData).filter(KLineData.code == code)
                if kl_types:
                    query = query.filter(KLineData.kl_type.in_(kl_types))
                if not force:
                    query = query.filter(KLineData.turnover_rate.is_(None))

                rows = query.order_by(KLineData.timestamp).all()
                updated_for_code = 0
                skipped_for_code = 0

                for row in rows:
                    turnrate = calc_turnover_rate(row.volume, active_capital)
                    if turnrate is None:
                        skipped_for_code += 1
                        continue
                    row.turnover_rate = turnrate
                    updated_for_code += 1

                if dry_run:
                    db.rollback()
                else:
                    db.commit()

                stats["updated"] += updated_for_code
                stats["skipped_no_rate"] += skipped_for_code
                action = "可更新" if dry_run else "已更新"
                logger.info("[%s] %s %s 条 turnover_rate", code, action, updated_for_code)
    finally:
        CTdxAPI.do_close()

    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只回填 kline_data.turnover_rate 字段")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--all", action="store_true", help="更新数据库中全部匹配记录")
    target.add_argument("--codes", nargs="+", help="只更新指定股票代码，需匹配数据库中的 code")
    parser.add_argument("--kl-types", nargs="+", help="限制周期，如 DAY 30M 60M")
    parser.add_argument("--force", action="store_true", help="覆盖已有 turnover_rate")
    parser.add_argument("--dry-run", action="store_true", help="只统计和打印，不提交数据库")
    parser.add_argument("--limit", type=int, help="最多处理多少个股票代码，便于试跑")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stats = backfill_turnover_rate(
        codes=args.codes,
        kl_types=args.kl_types,
        force=args.force,
        dry_run=args.dry_run,
        limit=args.limit,
    )
    logger.info(
        "完成: codes=%s updated=%s skipped_no_active_capital=%s skipped_no_rate=%s",
        stats["codes"],
        stats["updated"],
        stats["skipped_no_active_capital"],
        stats["skipped_no_rate"],
    )


if __name__ == "__main__":
    main()
