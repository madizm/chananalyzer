"""
信号回放回测：指定级别双中枢抬高买点。

特点：
- signal-only 评估（不做仓位与撮合）
- 使用 CChan step replay，避免未来函数
- 输出信号明细 CSV + 统计 JSON
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from strategies.zs_gap_buy import detect_zs_gap_buy

DB_PATH = PROJECT_ROOT / "chan.db"
RULE_NAME = "zs_gap_buy"

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


@dataclass
class SignalEvent:
    code: str
    level: str
    signal_time: str
    signal_date: str
    signal_price: float
    observation_time: str
    observation_date: str
    observation_price: float
    signal_age_days: int
    signal_deviation_pct: float
    gap_abs: float
    gap_pct: float
    previous_zs_json: str
    latest_zs_json: str


@dataclass(frozen=True)
class CollectSignalsTask:
    idx: int
    total: int
    code: str
    signal_kl_type: KL_TYPE
    signal_level: str
    begin_date: Optional[str]
    end_date: Optional[str]
    signal_begin: Optional[str]
    signal_end: Optional[str]
    bi_strict: bool
    require_zs_sure: bool
    min_gap_pct: float
    max_signal_age_days: int
    max_signal_deviation_pct: Optional[float]


@dataclass
class CollectSignalsResult:
    idx: int
    total: int
    code: str
    events: List[SignalEvent]
    error: Optional[str] = None


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
    limit: Optional[int] = None,
    signal_level: str = "15M",
) -> List[str]:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"数据库不存在: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT d.code
        FROM kline_data d
        WHERE d.kl_type = 'DAY'
          AND d.code NOT LIKE '688%'
          AND d.code NOT LIKE '8%'
          AND d.code NOT LIKE '43%'
          AND EXISTS (
              SELECT 1
              FROM kline_data s
              WHERE s.code = d.code AND s.kl_type = ?
          )
        ORDER BY d.code
        """,
        (signal_level,),
    )
    rows = [row[0] for row in cur.fetchall()]
    conn.close()

    if limit is not None and limit > 0:
        return rows[:limit]
    return rows


def load_day_bars(code: str) -> List[tuple[datetime, float, float, float, float]]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT timestamp, open, high, low, close
        FROM kline_data
        WHERE code = ? AND kl_type = 'DAY'
        ORDER BY timestamp
        """,
        (code,),
    )
    rows = cur.fetchall()
    conn.close()

    bars: List[tuple[datetime, float, float, float, float]] = []
    for ts, open_price, high_price, low_price, close_price in rows:
        try:
            bars.append(
                (
                    _parse_dt(ts),
                    float(open_price),
                    float(high_price),
                    float(low_price),
                    float(close_price),
                )
            )
        except Exception:
            continue
    return bars


def _extract_trading_dates_from_level(level_kl: Any) -> List[date]:
    days = {
        date(klc[0].time.year, klc[0].time.month, klc[0].time.day)
        for klc in level_kl
        if len(klc) > 0
    }
    return sorted(days)


def _signal_age_days(
    signal_date: date,
    observation_date: date,
    trading_dates: List[date],
) -> int:
    if observation_date < signal_date:
        return 0
    return sum(1 for d in trading_dates if signal_date < d <= observation_date)


def _observation_time_from_level(level_kl: Any) -> Optional[datetime]:
    if len(level_kl) == 0:
        return None
    cur_time = level_kl[-1][-1].time
    return datetime(
        cur_time.year,
        cur_time.month,
        cur_time.day,
        cur_time.hour,
        cur_time.minute,
        getattr(cur_time, "second", 0),
    )


def _dedup_key(hit) -> tuple[Any, ...]:
    prev_zs = hit.previous_zs
    latest_zs = hit.latest_zs
    return (
        prev_zs["begin_bi_idx"],
        prev_zs["end_bi_idx"],
        prev_zs["begin_time"],
        prev_zs["end_time"],
        latest_zs["begin_bi_idx"],
        latest_zs["end_bi_idx"],
        latest_zs["begin_time"],
        latest_zs["end_time"],
    )


def collect_signals_by_replay(
    code: str,
    begin_date: Optional[str],
    end_date: Optional[str],
    signal_begin: Optional[str],
    signal_end: Optional[str],
    bi_strict: bool,
    require_zs_sure: bool,
    min_gap_pct: float,
    max_signal_age_days: int,
    max_signal_deviation_pct: Optional[float],
    signal_kl_type: KL_TYPE,
    signal_level: str,
) -> List[SignalEvent]:
    config = CChanConfig(
        {
            "trigger_step": True,
            "bi_strict": True,
            "bi_algo": "fx",
            "bi_fx_check": "half",
            "skip_step": 0,
            "divergence_rate": float("inf"),
            "min_zs_cnt": 0,
            "bs1_peak": False,
            "macd_algo": "peak",
            "bs_type": "1,2,3a,1p,2s,3b",
            "print_warning": True,
            "zs_algo": "auto",
            "one_bi_zs": False,
            "left_seg_method": "all",
            "bsp2_follow_1": False,
            "bsp3_follow_1": False,
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
        return []

    signal_idx = chan.lv_list.index(signal_kl_type)
    begin_dt = _parse_dt(signal_begin) if signal_begin else None
    end_dt = _parse_dt(signal_end) if signal_end else None

    seen_keys = set()
    events: List[SignalEvent] = []

    for snapshot in chan.step_load():
        signal_kl = snapshot[signal_idx]
        observation_dt = _observation_time_from_level(signal_kl)
        if observation_dt is None:
            continue

        hit = detect_zs_gap_buy(
            snapshot=snapshot,
            signal_idx=signal_idx,
            observation_time=observation_dt,
            require_zs_sure=require_zs_sure,
            min_gap_pct=min_gap_pct,
        )
        if hit is None:
            continue

        if begin_dt and hit.observation_time < begin_dt:
            continue
        if end_dt and hit.observation_time > end_dt:
            continue

        trading_dates = _extract_trading_dates_from_level(signal_kl)
        signal_age_days = _signal_age_days(
            signal_date=hit.signal_time.date(),
            observation_date=hit.observation_time.date(),
            trading_dates=trading_dates,
        )
        if signal_age_days > max_signal_age_days:
            continue

        observation_price = float(signal_kl[-1][-1].close)
        if hit.signal_price == 0:
            continue
        signal_deviation_pct = abs(
            (observation_price - hit.signal_price) / hit.signal_price * 100
        )
        if (
            max_signal_deviation_pct is not None
            and signal_deviation_pct > max_signal_deviation_pct
        ):
            continue

        key = _dedup_key(hit)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        events.append(
            SignalEvent(
                code=code,
                level=signal_level,
                signal_time=hit.signal_time.strftime("%Y-%m-%d %H:%M:%S"),
                signal_date=hit.signal_date,
                signal_price=hit.signal_price,
                observation_time=hit.observation_time.strftime("%Y-%m-%d %H:%M:%S"),
                observation_date=hit.observation_date,
                observation_price=observation_price,
                signal_age_days=signal_age_days,
                signal_deviation_pct=signal_deviation_pct,
                gap_abs=hit.gap_abs,
                gap_pct=hit.gap_pct,
                previous_zs_json=json.dumps(hit.previous_zs, ensure_ascii=False),
                latest_zs_json=json.dumps(hit.latest_zs, ensure_ascii=False),
            )
        )

    return events


def _collect_signals_worker(task: CollectSignalsTask) -> CollectSignalsResult:
    try:
        events = collect_signals_by_replay(
            code=task.code,
            begin_date=task.begin_date,
            end_date=task.end_date,
            signal_begin=task.signal_begin,
            signal_end=task.signal_end,
            bi_strict=task.bi_strict,
            require_zs_sure=task.require_zs_sure,
            min_gap_pct=task.min_gap_pct,
            max_signal_age_days=task.max_signal_age_days,
            max_signal_deviation_pct=task.max_signal_deviation_pct,
            signal_kl_type=task.signal_kl_type,
            signal_level=task.signal_level,
        )
        return CollectSignalsResult(
            idx=task.idx,
            total=task.total,
            code=task.code,
            events=events,
        )
    except Exception as exc:
        return CollectSignalsResult(
            idx=task.idx,
            total=task.total,
            code=task.code,
            events=[],
            error=str(exc),
        )


def iter_signal_collection_results(
    tasks: List[CollectSignalsTask],
    workers: int,
) -> Iterator[CollectSignalsResult]:
    if workers <= 1:
        for task in tasks:
            yield _collect_signals_worker(task)
        return

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_collect_signals_worker, task) for task in tasks]
        for future in as_completed(futures):
            yield future.result()


def evaluate_signal_events(
    events: Iterable[SignalEvent],
    day_bars: List[tuple[datetime, float, float, float, float]],
    horizon_days: int,
    entry_mode: str,
    stop_loss_pct: float,
) -> List[Dict[str, Any]]:
    if not day_bars:
        return []

    day_dates = [d.date() for d, _, _, _, _ in day_bars]
    day_opens = [o for _, o, _, _, _ in day_bars]
    day_lows = [l for _, _, _, l, _ in day_bars]
    day_closes = [c for _, _, _, _, c in day_bars]
    rows: List[Dict[str, Any]] = []

    for event in events:
        observation_date = _parse_dt(event.observation_date).date()

        entry_idx = None
        for i, d in enumerate(day_dates):
            if d > observation_date:
                entry_idx = i
                break
        if entry_idx is None:
            continue

        horizon_exit_idx = entry_idx + horizon_days
        if horizon_exit_idx >= len(day_closes):
            continue

        if entry_mode == "next_open":
            entry_price = day_opens[entry_idx]
            entry_price_field = "entry_open"
        else:
            entry_price = day_closes[entry_idx]
            entry_price_field = "entry_close"

        stop_price = (
            entry_price * (1 - stop_loss_pct / 100) if stop_loss_pct > 0 else None
        )
        exit_idx = horizon_exit_idx
        exit_price = day_closes[horizon_exit_idx]
        exit_reason = "horizon"
        if stop_price is not None:
            for i in range(entry_idx, horizon_exit_idx + 1):
                if day_lows[i] <= stop_price:
                    exit_idx = i
                    exit_price = stop_price
                    exit_reason = "stop_loss"
                    break

        ret = (exit_price - entry_price) / entry_price
        row = {
            "code": event.code,
            "level": event.level,
            "rule": RULE_NAME,
            "signal_time": event.signal_time,
            "signal_date": event.signal_date,
            "signal_price": round(event.signal_price, 4),
            "observation_time": event.observation_time,
            "observation_date": event.observation_date,
            "observation_price": round(event.observation_price, 4),
            "signal_age_days": event.signal_age_days,
            "signal_deviation_pct": round(event.signal_deviation_pct, 4),
            "gap_abs": round(event.gap_abs, 4),
            "gap_pct": round(event.gap_pct, 4),
            "previous_zs_json": event.previous_zs_json,
            "latest_zs_json": event.latest_zs_json,
            "entry_date": day_dates[entry_idx].strftime("%Y-%m-%d"),
            "exit_date": day_dates[exit_idx].strftime("%Y-%m-%d"),
            "exit_close": round(exit_price, 4),
            "exit_reason": exit_reason,
            "stop_loss_pct": round(stop_loss_pct, 4),
            "stop_price": round(stop_price, 4) if stop_price is not None else None,
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
            "stop_loss_count": 0,
            "stop_loss_rate": 0.0,
            "avg_return_stop_loss": 0.0,
            "avg_return_horizon": 0.0,
        }

    rets = [r["return_pct"] for r in rows]
    wins = [r for r in rows if r["is_win"]]
    stop_loss_rows = [r for r in rows if r.get("exit_reason") == "stop_loss"]
    horizon_rows = [r for r in rows if r.get("exit_reason") == "horizon"]
    return {
        "scanned_codes": scanned_codes,
        "evaluated_signals": len(rows),
        "win_rate": round(len(wins) / len(rows) * 100, 2),
        "avg_return_pct": round(sum(rets) / len(rets), 4),
        "max_return_pct": round(max(rets), 4),
        "min_return_pct": round(min(rets), 4),
        "stop_loss_count": len(stop_loss_rows),
        "stop_loss_rate": round(len(stop_loss_rows) / len(rows) * 100, 2),
        "avg_return_stop_loss": (
            round(sum(r["return_pct"] for r in stop_loss_rows) / len(stop_loss_rows), 4)
            if stop_loss_rows
            else 0.0
        ),
        "avg_return_horizon": (
            round(sum(r["return_pct"] for r in horizon_rows) / len(horizon_rows), 4)
            if horizon_rows
            else 0.0
        ),
    }


def save_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    headers = [
        "code",
        "level",
        "rule",
        "signal_time",
        "signal_date",
        "signal_price",
        "observation_time",
        "observation_date",
        "observation_price",
        "signal_age_days",
        "signal_deviation_pct",
        "gap_abs",
        "gap_pct",
        "previous_zs_json",
        "latest_zs_json",
        "entry_date",
        "entry_open",
        "entry_close",
        "exit_date",
        "exit_close",
        "exit_reason",
        "stop_loss_pct",
        "stop_price",
        "return_pct",
        "is_win",
    ]

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="信号回放回测：指定级别双中枢抬高买点",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--codes", nargs="+", help="指定股票代码列表")
    parser.add_argument("--limit", type=int, default=50, help="未指定 codes 时的扫描数量上限")
    parser.add_argument("--all", action="store_true", help="扫描全部股票（忽略 --limit）")
    parser.add_argument("--begin", help="K线加载开始日期 YYYY-MM-DD")
    parser.add_argument("--end", help="K线加载结束日期 YYYY-MM-DD")
    parser.add_argument("--signal-begin", help="信号过滤开始日期 YYYY-MM-DD")
    parser.add_argument("--signal-end", help="信号过滤结束日期 YYYY-MM-DD")
    parser.add_argument("--level", default="15M", help="信号级别，如 5M/15M/30M/60M/DAY，默认 15M")
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
    parser.add_argument(
        "--max-signal-age-days",
        type=int,
        default=2,
        help="信号最大允许账龄（按交易日），默认 2",
    )
    parser.add_argument(
        "--max-signal-deviation-pct",
        type=float,
        default=None,
        help="观测时价格相对信号价的最大偏离百分比；不设置则不限制",
    )
    parser.add_argument("--horizon", type=int, default=5, help="N日后收益评估窗口，默认5")
    parser.add_argument(
        "--entry-mode",
        choices=["next_open", "next_close"],
        default="next_open",
        help="信号后执行价模式，默认 next_open",
    )
    parser.add_argument(
        "--stop-loss-pct",
        type=float,
        default=5.0,
        help="强制止损百分比，默认 5.0；设为 0 表示关闭止损",
    )
    parser.add_argument("--output-dir", default="outputs", help="输出目录")
    parser.add_argument("--bi-strict", action="store_true", help="启用严格笔")
    parser.add_argument(
        "--workers",
        type=int,
        default=min(4, os.cpu_count() or 1),
        help="并行收集信号的进程数，默认 min(4, CPU核数)；设为 1 表示串行",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.horizon <= 0:
        raise ValueError("--horizon 必须大于 0")
    if args.stop_loss_pct < 0:
        raise ValueError("--stop-loss-pct 不能小于 0")
    if args.min_gap_pct < 0:
        raise ValueError("--min-gap-pct 不能小于 0")
    if args.max_signal_age_days < 0:
        raise ValueError("--max-signal-age-days 不能小于 0")
    if args.max_signal_deviation_pct is not None and args.max_signal_deviation_pct < 0:
        raise ValueError("--max-signal-deviation-pct 不能小于 0")
    if args.workers <= 0:
        raise ValueError("--workers 必须大于 0")
    signal_kl_type, signal_level = _parse_level(args.level)

    if args.codes:
        stock_codes = args.codes
    else:
        stock_codes = get_stock_list_from_db(
            limit=None if args.all else args.limit,
            signal_level=signal_level,
        )

    if not stock_codes:
        print("没有可回测的股票")
        return

    require_zs_sure = not args.include_unsure_zs
    sure_text = "确认中枢" if require_zs_sure else "允许未确认中枢"
    deviation_text = (
        f"，信号偏离<={args.max_signal_deviation_pct}%"
        if args.max_signal_deviation_pct is not None
        else ""
    )

    print(f"开始回测，股票数量: {len(stock_codes)}")
    print(
        f"规则: {signal_level} 双中枢抬高买点，min_gap_pct={args.min_gap_pct:.2f}%，"
        f"{sure_text}，N={args.horizon}日信号评估，入场={args.entry_mode}，"
        f"止损={args.stop_loss_pct}%，信号账龄<={args.max_signal_age_days}交易日"
        f"{deviation_text}"
    )
    print(f"信号收集并行进程数: {args.workers}")

    all_rows: List[Dict[str, Any]] = []
    total_signals = 0

    tasks = [
        CollectSignalsTask(
            idx=idx,
            total=len(stock_codes),
            code=code,
            signal_kl_type=signal_kl_type,
            signal_level=signal_level,
            begin_date=args.begin,
            end_date=args.end,
            signal_begin=args.signal_begin,
            signal_end=args.signal_end,
            bi_strict=args.bi_strict,
            require_zs_sure=require_zs_sure,
            min_gap_pct=args.min_gap_pct,
            max_signal_age_days=args.max_signal_age_days,
            max_signal_deviation_pct=args.max_signal_deviation_pct,
        )
        for idx, code in enumerate(stock_codes, start=1)
    ]

    completed = 0
    for result in iter_signal_collection_results(tasks, workers=args.workers):
        completed += 1
        if result.error is not None:
            print(f"[{completed}/{len(stock_codes)}] {result.code}: 跳过 ({result.error})")
            continue

        events = result.events
        total_signals += len(events)
        if not events:
            print(f"[{completed}/{len(stock_codes)}] {result.code}: 无信号")
            continue

        try:
            day_bars = load_day_bars(result.code)
            rows = evaluate_signal_events(
                events,
                day_bars,
                horizon_days=args.horizon,
                entry_mode=args.entry_mode,
                stop_loss_pct=args.stop_loss_pct,
            )
            all_rows.extend(rows)
            print(
                f"[{completed}/{len(stock_codes)}] {result.code}: "
                f"信号 {len(events)} 个, 可评估 {len(rows)} 个"
            )
        except Exception as exc:
            print(f"[{completed}/{len(stock_codes)}] {result.code}: 评估跳过 ({exc})")

    summary = build_summary(all_rows, scanned_codes=len(stock_codes))
    summary["raw_signals"] = total_signals
    summary["horizon_days"] = args.horizon
    summary["entry_mode"] = args.entry_mode
    summary["stop_loss_pct"] = args.stop_loss_pct
    summary["rule"] = RULE_NAME
    summary["level"] = signal_level
    summary["require_zs_sure"] = require_zs_sure
    summary["min_gap_pct"] = args.min_gap_pct
    summary["max_signal_age_days"] = args.max_signal_age_days
    summary["max_signal_deviation_pct"] = args.max_signal_deviation_pct
    summary["bi_strict"] = args.bi_strict
    summary["workers"] = args.workers
    summary["begin"] = args.begin
    summary["end"] = args.end
    summary["shift_bars"] = 1
    summary["exec_policy"] = f"{args.entry_mode}_shift_1_bar"
    summary["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    level_slug = signal_level.lower()
    csv_path = out_dir / f"{level_slug}_zs_gap_buy_rows_{ts}.csv"
    json_path = out_dir / f"{level_slug}_zs_gap_buy_summary_{ts}.json"

    save_csv(csv_path, all_rows)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n回测完成")
    print(f"原始信号数: {summary['raw_signals']}")
    print(f"可评估信号数: {summary['evaluated_signals']}")
    print(f"胜率: {summary['win_rate']:.2f}%")
    print(f"平均收益: {summary['avg_return_pct']:.4f}%")
    print(f"止损触发: {summary['stop_loss_count']} ({summary['stop_loss_rate']:.2f}%)")
    print(f"最大收益: {summary['max_return_pct']:.4f}%")
    print(f"最小收益: {summary['min_return_pct']:.4f}%")
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")


if __name__ == "__main__":
    main()
