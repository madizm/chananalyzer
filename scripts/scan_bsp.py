"""
通用买卖点扫描器。

按指定级别、K线加载区间、信号时间窗口和买卖点类型扫描股票。

示例:
    python scripts/scan_bsp.py --level 30M --begin 2026-01-01 --end 2026-05-05 --signal-begin 2026-05-01 --buy-types 1 2 3a --all
    python scripts/scan_bsp.py --level DAY --begin 2025-01-01 --signal-begin 2026-04-01 --direction sell --types 1 2 --codes 000001 600519 --no-db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple, cast

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from Chan import CChan
from ChanConfig import CChanConfig
from ChanAnalyzer.database import (
    ScanResult,
    ScanRun,
    ScanSignal,
    SessionLocal,
    init_db,
)
from Common.CEnum import AUTYPE, BSP_TYPE, DATA_SRC, KL_TYPE

DB_PATH = PROJECT_ROOT / "chan.db"
ALL_BSP_TYPES = [x.value for x in BSP_TYPE]

LEVEL_TO_KL_TYPE = {
    "1M": KL_TYPE.K_1M,
    "5M": KL_TYPE.K_5M,
    "15M": KL_TYPE.K_15M,
    "30M": KL_TYPE.K_30M,
    "60M": KL_TYPE.K_60M,
    "1H": KL_TYPE.K_60M,
    "DAY": KL_TYPE.K_DAY,
    "D": KL_TYPE.K_DAY,
    "WEEK": KL_TYPE.K_WEEK,
    "W": KL_TYPE.K_WEEK,
    "MON": KL_TYPE.K_MON,
    "MONTH": KL_TYPE.K_MON,
}

KL_TYPE_TO_LEVEL = {
    KL_TYPE.K_1M: "1M",
    KL_TYPE.K_5M: "5M",
    KL_TYPE.K_15M: "15M",
    KL_TYPE.K_30M: "30M",
    KL_TYPE.K_60M: "60M",
    KL_TYPE.K_DAY: "DAY",
    KL_TYPE.K_WEEK: "WEEK",
    KL_TYPE.K_MON: "MON",
}


def _to_json_text(value: Any) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False)


def _parse_dt(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    s = str(text).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return datetime.fromisoformat(s)


def _is_date_only(text: Optional[str]) -> bool:
    if not text:
        return False
    s = str(text).strip()
    return len(s) == 10 and (s[4], s[7]) in {("-", "-"), ("/", "/")}


def _end_of_day(dt: datetime) -> datetime:
    return datetime.combine(dt.date(), time(23, 59, 59))


def _parse_level(text: str) -> Tuple[KL_TYPE, str]:
    key = text.strip().upper().replace("-", "").replace("_", "")
    if key.startswith("K"):
        key = key[1:]
    if key in LEVEL_TO_KL_TYPE:
        kl_type = LEVEL_TO_KL_TYPE[key]
        return kl_type, KL_TYPE_TO_LEVEL[kl_type]
    supported = ", ".join(sorted(LEVEL_TO_KL_TYPE))
    raise ValueError(f"不支持的级别: {text}；支持: {supported}")


def _normalize_types(values: Optional[Sequence[str]]) -> List[str]:
    if values is None:
        return []
    result: List[str] = []
    valid = set(ALL_BSP_TYPES)
    for value in values:
        for raw in str(value).split(","):
            item = raw.strip()
            if not item:
                continue
            if item not in valid:
                raise ValueError(f"不支持的买卖点类型: {item}；支持: {', '.join(ALL_BSP_TYPES)}")
            if item not in result:
                result.append(item)
    return result


def _types_from_args(args: argparse.Namespace) -> Tuple[List[str], List[str]]:
    common_types = _normalize_types(args.types)
    buy_types = _normalize_types(args.buy_types)
    sell_types = _normalize_types(args.sell_types)

    if common_types:
        if args.direction in ("buy", "all"):
            buy_types = common_types
        if args.direction in ("sell", "all"):
            sell_types = common_types

    if not buy_types and not sell_types:
        if args.direction in ("buy", "all"):
            buy_types = list(ALL_BSP_TYPES)
        if args.direction in ("sell", "all"):
            sell_types = list(ALL_BSP_TYPES)

    return buy_types, sell_types


def get_stock_list_from_db(
    level_label: str,
    exclude_bj: bool = True,
    exclude_b_share: bool = True,
    exclude_cdr: bool = True,
    limit: Optional[int] = None,
) -> List[str]:
    """从本地数据库获取指定级别有缓存的股票列表。"""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"数据库文件不存在: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT code
        FROM kline_data
        WHERE kl_type = ?
        ORDER BY code
        """,
        (level_label,),
    )
    rows = cur.fetchall()
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


def get_stock_info_bulk(stock_codes: List[str]) -> Dict[str, Dict[str, str]]:
    """批量获取名称/行业/地区。"""
    if not stock_codes:
        return {}

    result: Dict[str, Dict[str, str]] = {}
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        placeholders = ",".join("?" * len(stock_codes))
        cur.execute(
            f"""
            SELECT code, name, industry, area
            FROM stock_info
            WHERE code IN ({placeholders})
            """,
            stock_codes,
        )
        rows = cur.fetchall()
        conn.close()

        for code, name, industry, area in rows:
            result[code] = {
                "name": name or code,
                "industry": industry or "",
                "area": area or "",
            }
    except Exception as e:
        print(f"读取 stock_info 失败: {e}")

    for code in stock_codes:
        if code not in result:
            result[code] = {"name": code, "industry": "", "area": ""}
    return result


def _datetime_from_klu_time(klu_time: Any) -> datetime:
    return datetime(
        klu_time.year,
        klu_time.month,
        klu_time.day,
        klu_time.hour,
        klu_time.minute,
        getattr(klu_time, "second", 0),
    )


def _latest_price_from_chan(chan: CChan, level_idx: int) -> Tuple[Optional[float], Optional[float]]:
    kl_data = chan[level_idx]
    if len(kl_data) == 0:
        return None, None

    latest_close = float(kl_data[-1][-1].close)
    change_pct = None
    if len(kl_data) >= 2:
        prev_close = float(kl_data[-2][-1].close)
        if prev_close > 0:
            change_pct = (latest_close - prev_close) / prev_close * 100
    return latest_close, change_pct


def _iter_matched_signals(
    chan: CChan,
    level_idx: int,
    signal_begin: datetime,
    signal_end: datetime,
    buy_types: Set[str],
    sell_types: Set[str],
    include_seg_bsp: bool,
) -> Iterable[Dict[str, Any]]:
    kl_data = chan[level_idx]
    bsp_lists = [kl_data.bs_point_lst]
    if include_seg_bsp:
        bsp_lists.append(kl_data.seg_bs_point_lst)

    seen: Set[Tuple[int, bool, str, bool]] = set()
    for bsp_list in bsp_lists:
        for bsp in bsp_list.bsp_iter():
            direction = "buy" if bsp.is_buy else "sell"
            allowed_types = buy_types if bsp.is_buy else sell_types
            matched_types = [t.value for t in bsp.type if t.value in allowed_types]
            if not matched_types:
                continue

            signal_dt = _datetime_from_klu_time(bsp.klu.time)
            if signal_dt < signal_begin or signal_dt > signal_end:
                continue

            for bsp_type in matched_types:
                key = (bsp.bi.idx, bsp.is_buy, bsp_type, bool(bsp.is_segbsp))
                if key in seen:
                    continue
                seen.add(key)
                yield {
                    "type": bsp_type,
                    "direction": direction,
                    "date": signal_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "price": float(bsp.klu.close),
                    "period": KL_TYPE_TO_LEVEL.get(chan.lv_list[level_idx], str(chan.lv_list[level_idx])),
                    "bi_idx": int(bsp.bi.idx),
                    "is_sure": bool(bsp.bi.is_sure),
                    "is_seg_bsp": bool(bsp.is_segbsp),
                }


def analyze_stock(
    code: str,
    begin_date: str,
    end_date: str,
    signal_begin: datetime,
    signal_end: datetime,
    kl_type: KL_TYPE,
    buy_types: List[str],
    sell_types: List[str],
    bi_strict: bool,
    include_seg_bsp: bool,
    only_latest: bool,
) -> Optional[Dict[str, Any]]:
    config = CChanConfig(
        {
            "trigger_step": False,
            "bi_strict": bi_strict,
            "bs_type": ",".join(ALL_BSP_TYPES),
            "print_warning": False,
        }
    )

    chan = CChan(
        code=code,
        begin_time=begin_date,
        end_time=end_date,
        data_src=DATA_SRC.CACHE_DB,
        lv_list=[kl_type],
        config=config,
        autype=AUTYPE.QFQ,
    )

    if kl_type not in chan.lv_list:
        return None

    level_idx = chan.lv_list.index(kl_type)
    signals = sorted(
        _iter_matched_signals(
            chan=chan,
            level_idx=level_idx,
            signal_begin=signal_begin,
            signal_end=signal_end,
            buy_types=set(buy_types),
            sell_types=set(sell_types),
            include_seg_bsp=include_seg_bsp,
        ),
        key=lambda sig: (sig["date"], sig["bi_idx"], sig["type"]),
        reverse=True,
    )
    if not signals:
        return None

    if only_latest:
        signals = signals[:1]

    latest_price, change_pct = _latest_price_from_chan(chan, level_idx)
    return {
        "code": code,
        "signal_time": signals[0]["date"],
        "latest_price": latest_price,
        "change_pct": change_pct,
        "signals": signals,
    }


def print_results(
    results: List[Dict[str, Any]], stock_info: Dict[str, Dict[str, str]]
) -> None:
    if not results:
        print("\n未找到符合条件的股票")
        return

    print(f"\n找到 {len(results)} 只符合条件的股票:")
    print("=" * 80)

    for stock in sorted(results, key=lambda x: x.get("signal_time", ""), reverse=True):
        code = stock["code"]
        info = stock_info.get(code, {})
        name = info.get("name", code)
        industry = info.get("industry", "")
        area = info.get("area", "")

        print(f"\n股票: {code} {name}")
        if industry or area:
            print(f"  行业/地区: {industry} {area}".strip())

        latest_price = stock.get("latest_price")
        if latest_price is not None:
            text = f"  最新价格: {latest_price:.2f}"
            if stock.get("change_pct") is not None:
                text += f" ({stock['change_pct']:+.2f}%)"
            print(text)

        print("  信号:")
        for sig in stock.get("signals", []):
            seg_text = " 线段级" if sig.get("is_seg_bsp") else ""
            sure_text = "已确认" if sig.get("is_sure") else "未确认"
            print(
                f"    - {sig['period']}{seg_text} {sig['direction']} {sig['type']}类: "
                f"{sig['date']} @ {sig['price']:.2f} ({sure_text})"
            )


def save_results_to_database(
    results: List[Dict[str, Any]],
    stock_info: Dict[str, Dict[str, str]],
    scan_params: Dict[str, Any],
    started_at: datetime,
    finished_at: datetime,
    scanned_count: int,
) -> int:
    init_db()

    db = SessionLocal()
    try:
        scan_run = ScanRun(
            source="scan_bsp",
            started_at=started_at,
            finished_at=finished_at,
            scanned_count=scanned_count,
            result_count=len(results),
            buy_types=_to_json_text(scan_params.get("buy_types", [])),
            sell_types=_to_json_text(scan_params.get("sell_types", [])),
            begin_date=scan_params.get("begin"),
            end_date=scan_params.get("end"),
            use_weekly=1 if scan_params.get("level") == "WEEK" else 0,
            bi_strict=1 if scan_params.get("bi_strict") else 0,
            industry_filters="[]",
            area_filters="[]",
            exclude_st=0,
            group_by="none",
            min_amount=None,
            max_amount=None,
            min_turnover_rate=None,
            max_turnover_rate=None,
            show_money_flow=0,
            sort_by_money_flow=0,
            min_money_flow=0,
            ma_period=None,
        )
        db.add(scan_run)
        db.flush()

        for stock in results:
            code = stock["code"]
            info = stock_info.get(code, {})
            row = ScanResult(
                run_id=scan_run.id,
                code=code,
                name=info.get("name", code),
                industry=info.get("industry", ""),
                area=info.get("area", ""),
                latest_price=stock.get("latest_price"),
                change_pct=stock.get("change_pct"),
                money_flow_net_amount=None,
                money_flow_net_main_amount=None,
                money_flow_error=None,
                signal_time=stock.get("signal_time"),
            )
            db.add(row)
            db.flush()

            for sig in stock.get("signals", []):
                db.add(
                    ScanSignal(
                        result_id=row.id,
                        run_id=scan_run.id,
                        code=code,
                        signal_type=sig["type"],
                        direction=sig["direction"],
                        signal_date=sig["date"],
                        signal_price=float(sig["price"]),
                        period=sig["period"] + ("_SEG" if sig.get("is_seg_bsp") else ""),
                    )
                )

        db.commit()
        return cast(int, scan_run.id)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="通用买卖点扫描：按级别、时间区间和 BSP 类型扫描股票"
    )
    parser.add_argument("--codes", nargs="+", help="指定股票代码列表")
    parser.add_argument("--limit", type=int, default=50, help="未指定 codes 时扫描上限")
    parser.add_argument("--all", action="store_true", help="扫描全部股票（忽略 --limit）")
    parser.add_argument("--level", required=True, help="扫描级别，如 5M/15M/30M/60M/DAY/WEEK")
    parser.add_argument("--begin", help="K线加载开始日期 YYYY-MM-DD")
    parser.add_argument("--end", help="K线加载结束日期 YYYY-MM-DD")
    parser.add_argument("--signal-begin", help="信号过滤开始时间 YYYY-MM-DD[ HH:MM:SS]")
    parser.add_argument("--signal-end", help="信号过滤结束时间 YYYY-MM-DD[ HH:MM:SS]")
    parser.add_argument(
        "--direction",
        choices=["buy", "sell", "all"],
        default="all",
        help="配合 --types 使用的方向，默认 all",
    )
    parser.add_argument(
        "--types",
        nargs="+",
        help="买卖点类型，配合 --direction 作用到买点/卖点/全部，如 1 1p 2 3a 3b",
    )
    parser.add_argument("--buy-types", nargs="+", help="买点类型，如 1 1p 2 3a 3b")
    parser.add_argument("--sell-types", nargs="+", help="卖点类型，如 1 1p 2 3a 3b")
    parser.add_argument("--bi-strict", action="store_true", help="启用严格笔")
    parser.add_argument("--include-seg-bsp", action="store_true", help="同时扫描线段级买卖点")
    parser.add_argument(
        "--all-signals",
        action="store_true",
        help="保留每只股票在窗口内的全部命中；默认只保留最新一条",
    )
    parser.add_argument("--no-db", action="store_true", help="仅控制台输出，不写入数据库")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    started_at = datetime.now()

    kl_type, level_label = _parse_level(args.level)
    buy_types, sell_types = _types_from_args(args)
    if not buy_types and not sell_types:
        raise ValueError("至少需要指定一种买点或卖点类型")

    end_dt = _parse_dt(args.end) or datetime.now()
    if args.begin:
        begin_dt = _parse_dt(args.begin)
    elif level_label in {"1M", "5M", "15M", "30M"}:
        begin_dt = end_dt - timedelta(days=120)
    elif level_label == "DAY":
        begin_dt = end_dt - timedelta(days=730)
    else:
        begin_dt = end_dt - timedelta(days=365 * 5)

    if begin_dt is None:
        raise ValueError("--begin 格式不正确")

    signal_end_dt = _parse_dt(args.signal_end) or end_dt
    if _is_date_only(args.signal_end) or (args.signal_end is None and _is_date_only(args.end)):
        signal_end_dt = _end_of_day(signal_end_dt)
    signal_begin_dt = _parse_dt(args.signal_begin) or begin_dt

    if signal_begin_dt > signal_end_dt:
        raise ValueError("--signal-begin 不能晚于 --signal-end")

    begin_date = begin_dt.strftime("%Y-%m-%d")
    end_date = end_dt.strftime("%Y-%m-%d")

    if args.codes:
        stock_codes = args.codes
    else:
        stock_codes = get_stock_list_from_db(
            level_label=level_label,
            limit=None if args.all else args.limit,
        )

    if not stock_codes:
        print("没有可扫描的股票")
        return

    print(f"开始扫描，股票数量: {len(stock_codes)}")
    print(
        f"规则: {level_label}；买点({', '.join(buy_types) or '-'})；"
        f"卖点({', '.join(sell_types) or '-'})"
    )
    print(
        f"数据窗口: {begin_date} ~ {end_date}；信号窗口: "
        f"{signal_begin_dt.strftime('%Y-%m-%d %H:%M:%S')} ~ "
        f"{signal_end_dt.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    results: List[Dict[str, Any]] = []
    for idx, code in enumerate(stock_codes, start=1):
        try:
            hit = analyze_stock(
                code=code,
                begin_date=begin_date,
                end_date=end_date,
                signal_begin=signal_begin_dt,
                signal_end=signal_end_dt,
                kl_type=kl_type,
                buy_types=buy_types,
                sell_types=sell_types,
                bi_strict=args.bi_strict,
                include_seg_bsp=args.include_seg_bsp,
                only_latest=not args.all_signals,
            )
            if hit is not None:
                results.append(hit)
                sig = hit["signals"][0]
                print(
                    f"[{idx}/{len(stock_codes)}] {code}: 命中 "
                    f"{sig['direction']} {sig['type']}类 ({sig['date']})"
                )
        except Exception as e:
            print(f"[{idx}/{len(stock_codes)}] {code}: 跳过 ({e})")

    hit_codes = [x["code"] for x in results]
    stock_info = get_stock_info_bulk(hit_codes)
    print_results(results, stock_info)

    finished_at = datetime.now()
    if args.no_db:
        print("\n已按 --no-db 跳过数据库写入")
    else:
        run_id = save_results_to_database(
            results=results,
            stock_info=stock_info,
            scan_params={
                "level": level_label,
                "buy_types": buy_types,
                "sell_types": sell_types,
                "begin": begin_date,
                "end": end_date,
                "bi_strict": args.bi_strict,
            },
            started_at=started_at,
            finished_at=finished_at,
            scanned_count=len(stock_codes),
        )
        print(f"\n扫描结果已写入数据库，run_id={run_id}")

    print("\n扫描完成")
    print(f"扫描股票数: {len(stock_codes)}")
    print(f"命中股票数: {len(results)}")


if __name__ == "__main__":
    main()
