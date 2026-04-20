"""
选股扫描：30M 纯净 BSP 序列信号。

特点：
- 使用本地 chan.db（CACHE_DB）扫描
- 非回放模式（trigger_step=False），用于当前信号筛选
- 控制台输出 + 可选写入 scan_runs/scan_results/scan_signals
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

# 添加项目根目录到路径
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
from strategies.m30_bsp_sequence_buy import (
    STEPDef,
    detect_m30_bsp_sequence,
    is_day_last_bi_down,
    is_day_last_bi_down_sure,
    parse_sequence,
)

DB_PATH = PROJECT_ROOT / "chan.db"


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


def get_stock_list_from_db(
    exclude_bj: bool = True,
    exclude_b_share: bool = True,
    exclude_cdr: bool = True,
    limit: Optional[int] = None,
) -> List[str]:
    """从本地数据库获取股票列表。"""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"数据库文件不存在: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT code
        FROM kline_data
        WHERE kl_type = 'DAY'
        ORDER BY code
        """)
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


def _latest_price_from_chan(
    chan: CChan, kl_idx: int
) -> tuple[Optional[float], Optional[float]]:
    kl = chan[kl_idx]
    if len(kl) == 0:
        return None, None

    latest_close = float(kl[-1][-1].close)
    change_pct = None
    if len(kl) >= 2:
        prev_close = float(kl[-2][-1].close)
        if prev_close > 0:
            change_pct = (latest_close - prev_close) / prev_close * 100
    return latest_close, change_pct


def _extract_observation_time(chan: CChan, m30_idx: int) -> Optional[datetime]:
    """从 30M K线末尾提取观测时间。"""
    m30_kl = chan[m30_idx]
    if len(m30_kl) == 0:
        return None
    cur_time = m30_kl[-1][-1].time
    return datetime(
        cur_time.year,
        cur_time.month,
        cur_time.day,
        cur_time.hour,
        cur_time.minute,
    )


def _serialize_steps(matched_steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """将 matched_steps 中的 datetime 转为字符串，便于 JSON 序列化。"""
    serialized = []
    for step in matched_steps:
        s = dict(step)
        if isinstance(s.get("time"), datetime):
            s["time"] = s["time"].strftime("%Y-%m-%d %H:%M:%S")
        serialized.append(s)
    return serialized


def analyze_stock(
    code: str,
    begin_date: str,
    end_date: str,
    signal_begin: datetime,
    signal_end: datetime,
    sequence: List[STEPDef],
    sequence_str: str,
    max_gap_days: int,
    day_bi_mode: str,
    bi_strict: bool,
) -> Optional[Dict[str, Any]]:
    need_day = day_bi_mode != "off"
    lv_list = [KL_TYPE.K_DAY, KL_TYPE.K_30M] if need_day else [KL_TYPE.K_30M]

    config = CChanConfig(
        {
            "trigger_step": False,
            "bi_strict": bi_strict,
            "bs_type": "1,1p,2,2s,3a,3b",
            "print_warning": False,
        }
    )

    chan = CChan(
        code=code,
        begin_time=begin_date,
        end_time=end_date,
        data_src=DATA_SRC.CACHE_DB,
        lv_list=lv_list,
        config=config,
        autype=AUTYPE.QFQ,
    )

    if KL_TYPE.K_30M not in chan.lv_list:
        return None

    m30_idx = chan.lv_list.index(KL_TYPE.K_30M)
    day_idx = chan.lv_list.index(KL_TYPE.K_DAY) if need_day else None

    observation_time = _extract_observation_time(chan, m30_idx)
    if observation_time is None:
        return None

    hit = detect_m30_bsp_sequence(
        snapshot=chan,
        m30_idx=m30_idx,
        observation_time=observation_time,
        sequence=sequence,
        max_gap_days=max_gap_days,
        require_bi_sure=True,
    )
    if hit is None:
        return None

    # Apply day bi filter
    if need_day and day_idx is not None:
        if day_bi_mode == "down_sure":
            if not is_day_last_bi_down_sure(chan, day_idx):
                return None
        elif day_bi_mode == "down":
            if not is_day_last_bi_down(chan, day_idx):
                return None

    # Filter by signal time window
    if hit.signal_time < signal_begin or hit.signal_time > signal_end:
        return None

    # Get latest price from the most granular level (30M or day)
    price_idx = m30_idx
    latest_price, change_pct = _latest_price_from_chan(chan, price_idx)

    # The final (trigger) step
    last_step = hit.matched_steps[-1]
    last_step_direction = "buy" if last_step["is_buy"] else "sell"

    return {
        "code": code,
        "signal_time": hit.signal_time.strftime("%Y-%m-%d %H:%M:%S"),
        "latest_price": latest_price,
        "change_pct": change_pct,
        "sequence_str": sequence_str,
        "gap_days": hit.gap_days,
        "matched_steps": _serialize_steps(hit.matched_steps),
        # Final trigger step info (for DB ScanSignal)
        "signals": [
            {
                "type": last_step["type"],
                "direction": last_step_direction,
                "date": hit.signal_time.strftime("%Y-%m-%d %H:%M:%S"),
                "price": float(last_step["price"]),
                "period": "30M",
            }
        ],
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

        seq_str = stock.get("sequence_str", "")
        gap = stock.get("gap_days", 0)
        print(f"  序列: {seq_str}  间隔: {gap} 交易日")

        steps = stock.get("matched_steps", [])
        if steps:
            print("  步骤:")
            for step in steps:
                direction = "买" if step.get("is_buy") else "卖"
                print(
                    f"    步骤{step['step']} [{step['label']}/{step['type']}] {direction}: "
                    f"{step['time']} @ {float(step['price']):.2f}"
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

    # Separate sequence labels into buy/sell types for storage
    sequence: List[STEPDef] = scan_params.get("sequence_steps", [])
    buy_labels = [label for is_buy, _, label in sequence if is_buy]
    sell_labels = [label for is_buy, _, label in sequence if not is_buy]

    db = SessionLocal()
    try:
        scan_run = ScanRun(
            source="scan_m30_bsp_sequence",
            started_at=started_at,
            finished_at=finished_at,
            scanned_count=scanned_count,
            result_count=len(results),
            buy_types=_to_json_text(buy_labels),
            sell_types=_to_json_text(sell_labels),
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
    parser = argparse.ArgumentParser(
        description="选股扫描：30M 纯净 BSP 序列信号",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--sequence",
        nargs="+",
        default=["S3", "B1"],
        help="BSP 序列，如 S3a B1 或 S3 B2 B1，默认 S3 B1",
    )
    parser.add_argument(
        "--day-bi-mode",
        choices=["off", "down", "down_sure"],
        default="off",
        help=(
            "日线笔过滤模式（默认 off）：\n"
            "  off       不检查日线\n"
            "  down      日线最新笔为下跌即可（含虚笔，信号当日可确认）\n"
            "  down_sure 日线最新笔为下跌且已确认（严格，信号次日才能确认）"
        ),
    )
    parser.add_argument(
        "--max-gap-days",
        type=int,
        default=5,
        help="序列首尾最大间隔(交易日)，默认 5",
    )
    parser.add_argument("--codes", nargs="+", help="指定股票代码列表")
    parser.add_argument("--limit", type=int, default=50, help="未指定 codes 时扫描上限")
    parser.add_argument(
        "--all", action="store_true", help="扫描全部股票（忽略 --limit）"
    )
    parser.add_argument("--begin", default="2026-01-20", help="K线加载开始日期 YYYY-MM-DD")
    parser.add_argument("--end", help="K线加载结束日期 YYYY-MM-DD")
    parser.add_argument("--signal-begin", help="信号过滤开始日期 YYYY-MM-DD")
    parser.add_argument("--signal-end", help="信号过滤结束日期 YYYY-MM-DD")
    parser.add_argument("--bi-strict", action="store_true", help="启用严格笔")
    parser.add_argument(
        "--no-db", action="store_true", help="仅控制台输出，不写入数据库"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    started_at = datetime.now()

    sequence = parse_sequence(args.sequence)
    sequence_str = " ".join(step[2] for step in sequence)

    if args.max_gap_days < 0:
        raise ValueError("--max-gap-days 不能小于 0")

    end_dt = _parse_dt(args.end) or datetime.now()
    begin_dt = _parse_dt(args.begin) or (end_dt - timedelta(days=370))

    signal_end_dt = _parse_dt(args.signal_end) or end_dt
    signal_begin_dt = _parse_dt(args.signal_begin) or (
        signal_end_dt - timedelta(days=5)
    )

    if signal_begin_dt > signal_end_dt:
        raise ValueError("--signal-begin 不能晚于 --signal-end")

    begin_date = begin_dt.strftime("%Y-%m-%d")
    end_date = end_dt.strftime("%Y-%m-%d")

    if args.codes:
        stock_codes = args.codes
    else:
        stock_codes = get_stock_list_from_db(limit=None if args.all else args.limit)

    if not stock_codes:
        print("没有可扫描的股票")
        return

    day_bi_text = {
        "down": "，需日线最新笔下跌(含虚笔)",
        "down_sure": "，需日线最新笔下跌且确认",
    }.get(args.day_bi_mode, "")

    print(f"开始扫描，股票数量: {len(stock_codes)}")
    print(
        f"规则: 30M纯净序列 {sequence_str}，最大间隔<={args.max_gap_days}个交易日{day_bi_text}"
    )
    print(
        f"数据窗口: {begin_date} ~ {end_date}；"
        f"信号窗口: {signal_begin_dt.strftime('%Y-%m-%d')} ~ {signal_end_dt.strftime('%Y-%m-%d')}"
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
                sequence=sequence,
                sequence_str=sequence_str,
                max_gap_days=args.max_gap_days,
                day_bi_mode=args.day_bi_mode,
                bi_strict=args.bi_strict,
            )
            if hit is not None:
                results.append(hit)
                sig = hit["signals"][0]
                print(
                    f"[{idx}/{len(stock_codes)}] {code}: 命中序列 {sequence_str} "
                    f"触发={sig['type']}类 ({sig['date']})"
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
                "sequence_steps": sequence,
                "begin": begin_date,
                "end": end_date,
                "bi_strict": args.bi_strict,
                "max_gap_days": args.max_gap_days,
                "day_bi_mode": args.day_bi_mode,
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
    # python scripts/scan_m30_bsp_sequence.py --sequence S3 B1 --codes 000001 600519
    # python scripts/scan_m30_bsp_sequence.py --sequence S3 B1 --day-bi-mode down --limit 100 --no-db
    # python scripts/scan_m30_bsp_sequence.py --sequence S3 B1 --all --signal-begin 2026-04-07
    main()
