"""
选股扫描：日线收盘在 MA50 之上 + 30M 任意买点。

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
from strategies.day_ma50_30m_any_buy import detect_day_ma_30m_any_buy

DB_PATH = PROJECT_ROOT / "chan.db"
DEFAULT_BUY_TYPES = ["1", "1p", "2", "3a", "3b"]


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
    chan: CChan, day_idx: int
) -> tuple[Optional[float], Optional[float]]:
    day_kl = chan[day_idx]
    if len(day_kl) == 0:
        return None, None

    latest_close = float(day_kl[-1][-1].close)
    change_pct = None
    if len(day_kl) >= 2:
        prev_close = float(day_kl[-2][-1].close)
        if prev_close > 0:
            change_pct = (latest_close - prev_close) / prev_close * 100
    return latest_close, change_pct


def analyze_stock(
    code: str,
    begin_date: str,
    end_date: str,
    signal_begin: datetime,
    signal_end: datetime,
    ma_period: int,
    buy_types: List[str],
    bi_strict: bool,
) -> Optional[Dict[str, Any]]:
    config = CChanConfig(
        {
            "trigger_step": False,
            "bi_strict": bi_strict,
            "bs_type": "1,1p,2,3a,3b",
            "print_warning": False,
        }
    )

    chan = CChan(
        code=code,
        begin_time=begin_date,
        end_time=end_date,
        data_src=DATA_SRC.CACHE_DB,
        lv_list=[KL_TYPE.K_DAY, KL_TYPE.K_30M],
        config=config,
        autype=AUTYPE.QFQ,
    )

    if KL_TYPE.K_DAY not in chan.lv_list or KL_TYPE.K_30M not in chan.lv_list:
        return None

    day_idx = chan.lv_list.index(KL_TYPE.K_DAY)
    m30_idx = chan.lv_list.index(KL_TYPE.K_30M)

    hit = detect_day_ma_30m_any_buy(
        snapshot=chan,
        day_idx=day_idx,
        m30_idx=m30_idx,
        code=code,
        ma_period=ma_period,
        buy_types=buy_types,
    )
    if hit is None:
        return None

    if hit.signal_time < signal_begin or hit.signal_time > signal_end:
        return None

    latest_price, change_pct = _latest_price_from_chan(chan, day_idx=day_idx)
    return {
        "code": code,
        "signal_time": hit.signal_time.strftime("%Y-%m-%d %H:%M:%S"),
        "latest_price": latest_price,
        "change_pct": change_pct,
        "signals": [
            {
                "type": hit.bsp_type,
                "direction": "buy",
                "date": hit.signal_time.strftime("%Y-%m-%d %H:%M:%S"),
                "price": float(hit.signal_price),
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

    def _sig_time(stock: Dict[str, Any]) -> str:
        signals = stock.get("signals", [])
        return signals[0]["date"] if signals else ""

    for stock in sorted(results, key=_sig_time, reverse=True):
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
            print(
                f"    - {sig['period']} {sig['direction']} {sig['type']}类: {sig['date']} @ {sig['price']:.2f}"
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
            source="scan_day_ma50_signal",
            started_at=started_at,
            finished_at=finished_at,
            scanned_count=scanned_count,
            result_count=len(results),
            buy_types=_to_json_text(scan_params.get("buy_types", [])),
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
            ma_period=scan_params.get("ma_period"),
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
        description="选股扫描：日线收盘在 MA50 之上 + 30M 任意买点"
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
    parser.add_argument(
        "--buy-types",
        nargs="+",
        default=DEFAULT_BUY_TYPES,
        help="允许的30M买点类型，默认: 1 1p 2 3a 3b",
    )
    parser.add_argument(
        "--ma-period", type=int, default=50, help="日线均线周期，默认 50"
    )
    parser.add_argument("--bi-strict", action="store_true", help="启用严格笔")
    parser.add_argument(
        "--no-db", action="store_true", help="仅控制台输出，不写入数据库"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    started_at = datetime.now()

    if args.ma_period <= 0:
        raise ValueError("--ma-period 必须大于 0")

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

    print(f"开始扫描，股票数量: {len(stock_codes)}")
    print(
        f"规则: 日线收盘在 MA{args.ma_period} 之上 + 30M任意买点({', '.join(args.buy_types)})"
    )
    print(
        f"数据窗口: {begin_date} ~ {end_date}；信号窗口: {signal_begin_dt.strftime('%Y-%m-%d')} ~ {signal_end_dt.strftime('%Y-%m-%d')}"
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
                ma_period=args.ma_period,
                buy_types=args.buy_types,
                bi_strict=args.bi_strict,
            )
            if hit is not None:
                results.append(hit)
                sig = hit["signals"][0]
                print(
                    f"[{idx}/{len(stock_codes)}] {code}: 命中 {sig['type']}类 ({sig['date']})"
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
                "buy_types": args.buy_types,
                "begin": begin_date,
                "end": end_date,
                "bi_strict": args.bi_strict,
                "ma_period": args.ma_period,
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
    # python scripts/scan_day_ma50_signal.py --ma-period 21 --buy-types 1 1p --begin 2026-01-20 --end 2026-04-04 --all
    # python scripts/scan_day_ma50_signal.py --codes 000001 600519 --signal-begin 2026-04-01
    main()
