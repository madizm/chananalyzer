"""
简化版信号回放回测：日线向上 + 30M 任意买点。

特点：
- 只做 signal-only 评估（不做仓位与撮合）
- 使用 CChan step replay，避免未来函数
- 输出信号明细 CSV + 统计 JSON，便于后续分析
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from strategies.day_up_30m_any_buy import detect_day_up_30m_any_buy


DB_PATH = PROJECT_ROOT / "chan.db"
DEFAULT_BUY_TYPES = ["1", "1p", "2", "3a", "3b"]


@dataclass
class SignalEvent:
    code: str
    signal_time: str
    signal_date: str
    bsp_type: str
    signal_price: float


def _parse_dt(text: Any) -> datetime:
    if isinstance(text, datetime):
        return text
    s = str(text).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return datetime.fromisoformat(s)


def get_stock_list_from_db(limit: Optional[int] = None) -> List[str]:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"数据库不存在: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT code
        FROM kline_data
        WHERE kl_type = 'DAY'
        ORDER BY code
        """
    )
    rows = [row[0] for row in cur.fetchall()]
    conn.close()

    if limit is not None and limit > 0:
        return rows[:limit]
    return rows


def load_day_bars(code: str) -> List[tuple[datetime, float, float]]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT timestamp, open, close
        FROM kline_data
        WHERE code = ? AND kl_type = 'DAY'
        ORDER BY timestamp
        """,
        (code,),
    )
    rows = cur.fetchall()
    conn.close()

    bars: List[tuple[datetime, float, float]] = []
    for ts, open_price, close_price in rows:
        try:
            bars.append((_parse_dt(ts), float(open_price), float(close_price)))
        except Exception:
            continue
    return bars


def collect_signals_by_replay(
    code: str,
    begin_date: Optional[str],
    end_date: Optional[str],
    buy_types: List[str],
    signal_begin: Optional[str],
    signal_end: Optional[str],
    bi_strict: bool,
) -> List[SignalEvent]:
    config = CChanConfig(
        {
            "trigger_step": True,
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
        return []

    day_idx = chan.lv_list.index(KL_TYPE.K_DAY)
    m30_idx = chan.lv_list.index(KL_TYPE.K_30M)
    begin_dt = _parse_dt(signal_begin) if signal_begin else None
    end_dt = _parse_dt(signal_end) if signal_end else None

    seen_keys = set()
    events: List[SignalEvent] = []

    for snapshot in chan.step_load():
        hit = detect_day_up_30m_any_buy(
            snapshot=snapshot,
            day_idx=day_idx,
            m30_idx=m30_idx,
            buy_types=buy_types,
        )
        if hit is None:
            continue

        signal_dt = hit.signal_time
        if begin_dt and signal_dt < begin_dt:
            continue
        if end_dt and signal_dt > end_dt:
            continue

        key = (signal_dt.isoformat(), hit.bsp_type)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        events.append(
            SignalEvent(
                code=code,
                signal_time=signal_dt.strftime("%Y-%m-%d %H:%M:%S"),
                signal_date=signal_dt.strftime("%Y-%m-%d"),
                bsp_type=hit.bsp_type,
                signal_price=hit.signal_price,
            )
        )

    return events


def evaluate_signal_events(
    events: Iterable[SignalEvent],
    day_bars: List[tuple[datetime, float, float]],
    horizon_days: int,
    entry_mode: str,
) -> List[Dict[str, Any]]:
    if not day_bars:
        return []

    day_dates = [d.date() for d, _, _ in day_bars]
    day_opens = [o for _, o, _ in day_bars]
    day_closes = [c for _, _, c in day_bars]
    rows: List[Dict[str, Any]] = []

    for event in events:
        signal_date = _parse_dt(event.signal_date).date()

        entry_idx = None
        for i, d in enumerate(day_dates):
            if d > signal_date:
                entry_idx = i
                break
        if entry_idx is None:
            continue

        exit_idx = entry_idx + horizon_days
        if exit_idx >= len(day_closes):
            continue

        if entry_mode == "next_open":
            entry_price = day_opens[entry_idx]
            entry_price_field = "entry_open"
        else:
            entry_price = day_closes[entry_idx]
            entry_price_field = "entry_close"
        exit_price = day_closes[exit_idx]
        ret = (exit_price - entry_price) / entry_price

        row = {
            "code": event.code,
            "signal_time": event.signal_time,
            "signal_date": event.signal_date,
            "bsp_type": event.bsp_type,
            "signal_price": round(event.signal_price, 4),
            "entry_date": day_dates[entry_idx].strftime("%Y-%m-%d"),
            "exit_date": day_dates[exit_idx].strftime("%Y-%m-%d"),
            "exit_close": round(exit_price, 4),
            "return_pct": round(ret * 100, 4),
            "is_win": ret > 0,
        }
        row[entry_price_field] = round(entry_price, 4)
        rows.append(row)

    return rows


def build_summary(rows: List[Dict[str, Any]], scanned_codes: int) -> Dict[str, Any]:
    if not rows:
        return {
            "scanned_codes": scanned_codes,
            "evaluated_signals": 0,
            "win_rate": 0.0,
            "avg_return_pct": 0.0,
            "max_return_pct": 0.0,
            "min_return_pct": 0.0,
        }

    rets = [r["return_pct"] for r in rows]
    wins = [r for r in rows if r["is_win"]]
    return {
        "scanned_codes": scanned_codes,
        "evaluated_signals": len(rows),
        "win_rate": round(len(wins) / len(rows) * 100, 2),
        "avg_return_pct": round(sum(rets) / len(rets), 4),
        "max_return_pct": round(max(rets), 4),
        "min_return_pct": round(min(rets), 4),
    }


def save_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        headers = [
            "code",
            "signal_time",
            "signal_date",
            "bsp_type",
            "signal_price",
            "entry_date",
            "entry_open",
            "entry_close",
            "exit_date",
            "exit_close",
            "return_pct",
            "is_win",
        ]
    else:
        headers = list(rows[0].keys())

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="信号回放回测：日线向上 + 30M 任意买点",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--codes", nargs="+", help="指定股票代码列表")
    parser.add_argument("--limit", type=int, default=50, help="未指定 codes 时的扫描数量上限")
    parser.add_argument("--all", action="store_true", help="扫描全部股票（忽略 --limit）")
    parser.add_argument("--begin", help="K线加载开始日期 YYYY-MM-DD")
    parser.add_argument("--end", help="K线加载结束日期 YYYY-MM-DD")
    parser.add_argument("--signal-begin", help="信号过滤开始日期 YYYY-MM-DD")
    parser.add_argument("--signal-end", help="信号过滤结束日期 YYYY-MM-DD")
    parser.add_argument(
        "--buy-types",
        nargs="+",
        default=DEFAULT_BUY_TYPES,
        help="允许的30M买点类型，默认: 1 1p 2 2s 3a 3b",
    )
    parser.add_argument("--horizon", type=int, default=5, help="N日后收益评估窗口，默认5")
    parser.add_argument(
        "--entry-mode",
        choices=["next_open", "next_close"],
        default="next_open",
        help="信号后执行价模式，默认 next_open",
    )
    parser.add_argument("--output-dir", default="outputs", help="输出目录")
    parser.add_argument("--bi-strict", action="store_true", help="启用严格笔")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.horizon <= 0:
        raise ValueError("--horizon 必须大于 0")

    if args.codes:
        stock_codes = args.codes
    else:
        stock_codes = get_stock_list_from_db(limit=None if args.all else args.limit)

    if not stock_codes:
        print("没有可回测的股票")
        return

    print(f"开始回测，股票数量: {len(stock_codes)}")
    print(
        f"规则: 日线向上 + 30M任意买点({', '.join(args.buy_types)})，N={args.horizon}日信号评估，入场={args.entry_mode}"
    )

    all_rows: List[Dict[str, Any]] = []
    total_signals = 0

    for idx, code in enumerate(stock_codes, start=1):
        try:
            events = collect_signals_by_replay(
                code=code,
                begin_date=args.begin,
                end_date=args.end,
                buy_types=args.buy_types,
                signal_begin=args.signal_begin,
                signal_end=args.signal_end,
                bi_strict=args.bi_strict,
            )
            total_signals += len(events)
            if not events:
                print(f"[{idx}/{len(stock_codes)}] {code}: 无信号")
                continue

            day_bars = load_day_bars(code)
            rows = evaluate_signal_events(
                events,
                day_bars,
                horizon_days=args.horizon,
                entry_mode=args.entry_mode,
            )
            all_rows.extend(rows)
            print(
                f"[{idx}/{len(stock_codes)}] {code}: 信号 {len(events)} 个, 可评估 {len(rows)} 个"
            )
        except Exception as e:
            print(f"[{idx}/{len(stock_codes)}] {code}: 跳过 ({e})")

    summary = build_summary(all_rows, scanned_codes=len(stock_codes))
    summary["raw_signals"] = total_signals
    summary["horizon_days"] = args.horizon
    summary["buy_types"] = args.buy_types
    summary["entry_mode"] = args.entry_mode
    summary["shift_bars"] = 1
    summary["exec_policy"] = f"{args.entry_mode}_shift_1_bar"
    summary["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = out_dir / f"day_up_30m_signal_rows_{ts}.csv"
    json_path = out_dir / f"day_up_30m_signal_summary_{ts}.json"

    save_csv(csv_path, all_rows)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n回测完成")
    print(f"原始信号数: {summary['raw_signals']}")
    print(f"可评估信号数: {summary['evaluated_signals']}")
    print(f"胜率: {summary['win_rate']:.2f}%")
    print(f"平均收益: {summary['avg_return_pct']:.4f}%")
    print(f"最大收益: {summary['max_return_pct']:.4f}%")
    print(f"最小收益: {summary['min_return_pct']:.4f}%")
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")


if __name__ == "__main__":
    # python scripts/backtest_day_up_30m_signal.py --begin 2025-12-25 --end 2026-03-03 --horizon 5 --entry-mode next_open --output-dir outputs
    # python scripts/backtest_day_up_30m_signal.py --limit 200 --begin 2026-03-20 --end 2026-03-27 --horizon 5 --entry-mode next_open --output-dir outputs
    main()
