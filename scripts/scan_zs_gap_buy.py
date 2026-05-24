"""
选股扫描：指定级别双中枢抬高买点。

规则：
- 指定级别笔级中枢至少 2 个
- 最近有效中枢 low > 前一个有效中枢 high
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

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
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from strategies.zs_gap_buy import ZSGapBuyHit, detect_zs_gap_buy

DB_PATH = PROJECT_ROOT / "chan.db"
SCAN_SOURCE = "scan_zs_gap_buy"
SIGNAL_TYPE = "zs_gap_buy"

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


def _parse_level(text: str) -> tuple[KL_TYPE, str]:
    key = str(text).strip().upper().replace("-", "").replace("_", "")
    if key.startswith("K"):
        key = key[1:]
    if key in LEVEL_TO_KL_TYPE:
        kl_type = LEVEL_TO_KL_TYPE[key]
        return kl_type, KL_TYPE_TO_LEVEL[kl_type]
    supported = ", ".join(sorted(LEVEL_TO_KL_TYPE))
    raise ValueError(f"不支持的级别: {text}；支持: {supported}")


def get_stock_list_from_db(
    level_label: str,
    exclude_bj: bool = True,
    exclude_b_share: bool = True,
    exclude_cdr: bool = True,
    limit: Optional[int] = None,
) -> List[str]:
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
    result: Dict[str, Dict[str, str]] = {}
    if not stock_codes:
        return result

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
    except Exception as exc:
        print(f"读取 stock_info 失败: {exc}")

    for code in stock_codes:
        if code not in result:
            result[code] = {"name": code, "industry": "", "area": ""}
    return result


def _extract_observation_time(chan: CChan, signal_idx: int) -> Optional[datetime]:
    signal_kl = chan[signal_idx]
    if len(signal_kl) == 0:
        return None
    cur_time = signal_kl[-1][-1].time
    return datetime(
        cur_time.year,
        cur_time.month,
        cur_time.day,
        cur_time.hour,
        cur_time.minute,
        getattr(cur_time, "second", 0),
    )


def _latest_price_from_chan(
    chan: CChan,
    signal_idx: int,
) -> tuple[Optional[float], Optional[float]]:
    signal_kl = chan[signal_idx]
    if len(signal_kl) == 0:
        return None, None

    latest_close = float(signal_kl[-1][-1].close)
    change_pct = None
    if len(signal_kl) >= 2:
        prev_close = float(signal_kl[-2][-1].close)
        if prev_close > 0:
            change_pct = (latest_close - prev_close) / prev_close * 100
    return latest_close, change_pct


def _hit_to_result(
    code: str,
    chan: CChan,
    signal_idx: int,
    hit: ZSGapBuyHit,
    signal_level: str,
) -> Dict[str, Any]:
    latest_price, change_pct = _latest_price_from_chan(chan, signal_idx)
    return {
        "code": code,
        "signal_time": hit.signal_time.strftime("%Y-%m-%d %H:%M:%S"),
        "latest_price": latest_price,
        "change_pct": change_pct,
        "gap_abs": hit.gap_abs,
        "gap_pct": hit.gap_pct,
        "latest_zs": hit.latest_zs,
        "previous_zs": hit.previous_zs,
        "signals": [
            {
                "type": SIGNAL_TYPE,
                "direction": "buy",
                "date": hit.signal_time.strftime("%Y-%m-%d %H:%M:%S"),
                "price": float(hit.signal_price),
                "period": signal_level,
            }
        ],
    }


def analyze_stock(
    code: str,
    begin_date: str,
    end_date: str,
    signal_begin: datetime,
    signal_end: datetime,
    min_gap_pct: float,
    require_zs_sure: bool,
    bi_strict: bool,
    signal_kl_type: KL_TYPE,
    signal_level: str,
) -> Optional[Dict[str, Any]]:
    config = CChanConfig(
        {
            "trigger_step": False,
            "bi_strict": bi_strict,
            "print_warning": False,
        }
    )

    chan = CChan(
        code=code,
        begin_time=begin_date,
        end_time=end_date,
        data_src=DATA_SRC.CACHE_DB,
        lv_list=[signal_kl_type],
        config=config,
        autype=AUTYPE.QFQ,
    )

    if signal_kl_type not in chan.lv_list:
        return None

    signal_idx = chan.lv_list.index(signal_kl_type)
    observation_time = _extract_observation_time(chan, signal_idx)
    if observation_time is None:
        return None

    hit = detect_zs_gap_buy(
        snapshot=chan,
        signal_idx=signal_idx,
        observation_time=observation_time,
        require_zs_sure=require_zs_sure,
        min_gap_pct=min_gap_pct,
    )
    if hit is None:
        return None

    if hit.signal_time < signal_begin or hit.signal_time > signal_end:
        return None

    return _hit_to_result(code, chan, signal_idx, hit, signal_level)


def print_results(
    results: List[Dict[str, Any]],
    stock_info: Dict[str, Dict[str, str]],
    signal_level: str,
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
        latest_zs = stock["latest_zs"]
        previous_zs = stock["previous_zs"]

        print(f"\n股票: {code} {name}")
        if industry or area:
            print(f"  行业/地区: {industry} {area}".strip())

        latest_price = stock.get("latest_price")
        if latest_price is not None:
            text = f"  最新价格: {latest_price:.2f}"
            if stock.get("change_pct") is not None:
                text += f" ({stock['change_pct']:+.2f}%)"
            print(text)

        print(
            f"  信号: {signal_level} {SIGNAL_TYPE} "
            f"{stock['signal_time']} gap={stock['gap_abs']:.4f} "
            f"({stock['gap_pct']:.2f}%)"
        )
        print(
            "  前中枢: "
            f"{previous_zs['begin_time']}~{previous_zs['end_time']} "
            f"[{previous_zs['low']:.2f}, {previous_zs['high']:.2f}]"
        )
        print(
            "  近中枢: "
            f"{latest_zs['begin_time']}~{latest_zs['end_time']} "
            f"[{latest_zs['low']:.2f}, {latest_zs['high']:.2f}]"
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

    rule_meta = {
        "rule": SIGNAL_TYPE,
        "level": scan_params.get("level"),
        "require_zs_sure": scan_params.get("require_zs_sure"),
        "min_gap_pct": scan_params.get("min_gap_pct"),
        "gap_rule": "latest_zs.low > previous_zs.high",
    }

    db = SessionLocal()
    try:
        scan_run = ScanRun(
            source=SCAN_SOURCE,
            started_at=started_at,
            finished_at=finished_at,
            scanned_count=scanned_count,
            result_count=len(results),
            buy_types=_to_json_text([SIGNAL_TYPE]),
            sell_types="[]",
            begin_date=scan_params.get("begin"),
            end_date=scan_params.get("end"),
            use_weekly=0,
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
            sequence_json=_to_json_text(rule_meta),
            max_gap_days=None,
            bi_mode="zs_sure" if scan_params.get("require_zs_sure") else "include_unsure_zs",
            signal_level=scan_params.get("level"),
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
                        period=sig["period"],
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
    parser = argparse.ArgumentParser(description="选股扫描：指定级别双中枢抬高买点")
    parser.add_argument("--codes", nargs="+", help="指定股票代码列表")
    parser.add_argument("--limit", type=int, default=50, help="未指定 codes 时扫描上限")
    parser.add_argument("--all", action="store_true", help="扫描全部股票（忽略 --limit）")
    parser.add_argument("--begin", help="K线加载开始日期 YYYY-MM-DD")
    parser.add_argument("--end", help="K线加载结束日期 YYYY-MM-DD")
    parser.add_argument("--signal-begin", help="信号过滤开始时间 YYYY-MM-DD[ HH:MM:SS]")
    parser.add_argument("--signal-end", help="信号过滤结束时间 YYYY-MM-DD[ HH:MM:SS]")
    parser.add_argument("--level", default="15M", help="扫描级别，如 5M/15M/30M/60M/DAY，默认 15M")
    parser.add_argument(
        "--min-gap-pct",
        type=float,
        default=0.0,
        help="近中枢 low 高于前中枢 high 的最小百分比，默认 0",
    )
    parser.add_argument(
        "--include-unsure-zs",
        action="store_true",
        help="允许使用尾部未确认中枢；默认只用确认中枢",
    )
    parser.add_argument("--bi-strict", action="store_true", help="启用严格笔")
    parser.add_argument("--no-db", action="store_true", help="仅控制台输出，不写入数据库")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    started_at = datetime.now()

    if args.min_gap_pct < 0:
        raise ValueError("--min-gap-pct 不能小于 0")
    signal_kl_type, signal_level = _parse_level(args.level)

    end_dt = _parse_dt(args.end) or datetime.now()
    begin_dt = _parse_dt(args.begin) or (end_dt - timedelta(days=370))
    signal_end_dt = _parse_dt(args.signal_end) or end_dt
    if _is_date_only(args.signal_end) or (args.signal_end is None and _is_date_only(args.end)):
        signal_end_dt = _end_of_day(signal_end_dt)
    signal_begin_dt = _parse_dt(args.signal_begin) or (signal_end_dt - timedelta(days=5))

    if signal_begin_dt > signal_end_dt:
        raise ValueError("--signal-begin 不能晚于 --signal-end")

    begin_date = begin_dt.strftime("%Y-%m-%d")
    end_date = end_dt.strftime("%Y-%m-%d")
    require_zs_sure = not args.include_unsure_zs

    if args.codes:
        stock_codes = args.codes
    else:
        stock_codes = get_stock_list_from_db(
            level_label=signal_level,
            limit=None if args.all else args.limit,
        )

    if not stock_codes:
        print("没有可扫描的股票")
        return

    sure_text = "确认中枢" if require_zs_sure else "允许未确认中枢"
    print(f"开始扫描，股票数量: {len(stock_codes)}")
    print(
        f"规则: {signal_level} 双中枢抬高买点，"
        f"近中枢low > 前中枢high，min_gap_pct={args.min_gap_pct:.2f}%，{sure_text}"
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
                min_gap_pct=args.min_gap_pct,
                require_zs_sure=require_zs_sure,
                bi_strict=args.bi_strict,
                signal_kl_type=signal_kl_type,
                signal_level=signal_level,
            )
            if hit is not None:
                results.append(hit)
                print(
                    f"[{idx}/{len(stock_codes)}] {code}: 命中 "
                    f"{SIGNAL_TYPE} ({hit['signal_time']}) "
                    f"gap={hit['gap_pct']:.2f}%"
                )
        except Exception as exc:
            print(f"[{idx}/{len(stock_codes)}] {code}: 跳过 ({exc})")

    hit_codes = [x["code"] for x in results]
    stock_info = get_stock_info_bulk(hit_codes)
    print_results(results, stock_info, signal_level)

    finished_at = datetime.now()
    if args.no_db:
        print("\n已按 --no-db 跳过数据库写入")
    else:
        run_id = save_results_to_database(
            results=results,
            stock_info=stock_info,
            scan_params={
                "begin": begin_date,
                "end": end_date,
                "bi_strict": args.bi_strict,
                "require_zs_sure": require_zs_sure,
                "min_gap_pct": args.min_gap_pct,
                "level": signal_level,
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
