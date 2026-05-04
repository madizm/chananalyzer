from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Union

from Common.CEnum import KL_TYPE

DB_PATH = Path(__file__).resolve().parent.parent / "chan.db"

LevelInput = Union[str, KL_TYPE]
TimeInput = Union[str, datetime]

_KL_TYPE_TO_DB = {
    KL_TYPE.K_DAY: "DAY",
    KL_TYPE.K_WEEK: "WEEK",
    KL_TYPE.K_MON: "MON",
    KL_TYPE.K_5M: "5M",
    KL_TYPE.K_15M: "15M",
    KL_TYPE.K_30M: "30M",
}

_LEVEL_ALIASES = {
    "DAY": "DAY",
    "D": "DAY",
    "1D": "DAY",
    "WEEK": "WEEK",
    "W": "WEEK",
    "MON": "MON",
    "MONTH": "MON",
    "M": "MON",
    "5M": "5M",
    "15M": "15M",
    "30M": "30M",
}


@dataclass(frozen=True)
class AmountFlowStats:
    code: str
    level: str
    begin: datetime
    end: datetime
    up_amount: float
    down_amount: float
    flat_amount: float
    bar_count: int
    amount_bar_count: int

    @property
    def net_amount(self) -> float:
        return self.up_amount - self.down_amount

    @property
    def passed(self) -> bool:
        return (
            self.bar_count > 0
            and self.amount_bar_count > 0
            and self.up_amount > self.down_amount
        )


def normalize_level(level: LevelInput) -> str:
    if isinstance(level, KL_TYPE):
        if level not in _KL_TYPE_TO_DB:
            raise ValueError(f"不支持的级别: {level}")
        return _KL_TYPE_TO_DB[level]

    key = str(level).strip().upper()
    if key.startswith("K_"):
        key = key[2:]
    if key not in _LEVEL_ALIASES:
        allowed = ", ".join(sorted(_LEVEL_ALIASES))
        raise ValueError(f"不支持的级别: {level}，可选: {allowed}")
    return _LEVEL_ALIASES[key]


def parse_time(value: TimeInput, *, end_of_day: bool = False) -> datetime:
    if isinstance(value, datetime):
        return value

    text = str(value).strip()
    if not text:
        raise ValueError("时间不能为空")

    date_only = False
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass

    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(text, fmt)
            date_only = True
            break
        except ValueError:
            continue
    else:
        dt = datetime.fromisoformat(text)

    if end_of_day and date_only:
        return datetime.combine(dt.date(), time.max)
    return dt


def load_amount_flow_stats(
    code: str,
    begin: TimeInput,
    end: TimeInput,
    level: LevelInput,
    db_path: Union[str, Path] = DB_PATH,
) -> AmountFlowStats:
    """统计指定时间段内上涨/下跌/平盘 K 线的成交额。"""
    begin_dt = parse_time(begin)
    end_dt = parse_time(end, end_of_day=True)
    if begin_dt > end_dt:
        raise ValueError("begin 不能晚于 end")

    level_text = normalize_level(level)
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"数据库文件不存在: {path}")

    conn = sqlite3.connect(path)
    try:
        return _load_amount_flow_stats_from_conn(
            conn=conn,
            code=code,
            begin_dt=begin_dt,
            end_dt=end_dt,
            level_text=level_text,
        )
    finally:
        conn.close()


def passes_up_amount_filter(
    code: str,
    begin: TimeInput,
    end: TimeInput,
    level: LevelInput,
    db_path: Union[str, Path] = DB_PATH,
) -> bool:
    """判断上涨 K 线成交额总和是否大于下跌 K 线成交额总和。"""
    return load_amount_flow_stats(code, begin, end, level, db_path=db_path).passed


def filter_codes_by_up_amount(
    codes: Iterable[str],
    begin: TimeInput,
    end: TimeInput,
    level: LevelInput,
    db_path: Union[str, Path] = DB_PATH,
) -> List[AmountFlowStats]:
    """批量过滤股票，返回通过条件的统计结果。"""
    begin_dt = parse_time(begin)
    end_dt = parse_time(end, end_of_day=True)
    if begin_dt > end_dt:
        raise ValueError("begin 不能晚于 end")

    level_text = normalize_level(level)
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"数据库文件不存在: {path}")

    results: List[AmountFlowStats] = []
    conn = sqlite3.connect(path)
    try:
        for code in codes:
            stats = _load_amount_flow_stats_from_conn(
                conn=conn,
                code=code,
                begin_dt=begin_dt,
                end_dt=end_dt,
                level_text=level_text,
            )
            if stats.passed:
                results.append(stats)
    finally:
        conn.close()

    return results


def _load_amount_flow_stats_from_conn(
    conn: sqlite3.Connection,
    code: str,
    begin_dt: datetime,
    end_dt: datetime,
    level_text: str,
) -> AmountFlowStats:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            COUNT(*) AS bar_count,
            SUM(CASE WHEN amount IS NOT NULL THEN 1 ELSE 0 END) AS amount_bar_count,
            COALESCE(SUM(CASE WHEN close > open THEN COALESCE(amount, 0) ELSE 0 END), 0) AS up_amount,
            COALESCE(SUM(CASE WHEN close < open THEN COALESCE(amount, 0) ELSE 0 END), 0) AS down_amount,
            COALESCE(SUM(CASE WHEN close = open THEN COALESCE(amount, 0) ELSE 0 END), 0) AS flat_amount
        FROM kline_data
        WHERE code = ?
          AND kl_type = ?
          AND timestamp >= ?
          AND timestamp <= ?
        """,
        (
            code,
            level_text,
            _format_sql_time(begin_dt),
            _format_sql_time(end_dt),
        ),
    )
    row: Tuple[
        int, Optional[int], Optional[float], Optional[float], Optional[float]
    ] = cur.fetchone()
    bar_count, amount_bar_count, up_amount, down_amount, flat_amount = row
    return AmountFlowStats(
        code=code,
        level=level_text,
        begin=begin_dt,
        end=end_dt,
        up_amount=float(up_amount or 0),
        down_amount=float(down_amount or 0),
        flat_amount=float(flat_amount or 0),
        bar_count=int(bar_count or 0),
        amount_bar_count=int(amount_bar_count or 0),
    )


def _format_sql_time(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")
