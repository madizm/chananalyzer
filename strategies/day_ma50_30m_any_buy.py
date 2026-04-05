from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from Chan import CChan
from strategies.day_up_30m_any_buy import (
    DEFAULT_BUY_TYPES,
    StrategyHit,
    _normalize_bsp_types,
)


DB_PATH = Path(__file__).resolve().parent.parent / "chan.db"


def _load_day_ma_from_db(code: str, as_of_day: str, period: int) -> Optional[float]:
    if not DB_PATH.exists():
        return None

    if period <= 0:
        return None

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT close
        FROM kline_data
        WHERE code = ? AND kl_type = 'DAY' AND date <= ?
        ORDER BY date DESC
        LIMIT ?
        """,
        (code, as_of_day, period),
    )
    rows = cur.fetchall()
    conn.close()

    if len(rows) < period:
        return None

    closes = [float(row[0]) for row in rows]
    return sum(closes) / len(closes)


def is_day_above_ma(snapshot: CChan, day_idx: int, code: str, ma_period: int = 50) -> bool:
    day_kl = snapshot[day_idx]
    if len(day_kl) == 0:
        return False

    latest_klu = day_kl[-1][-1]
    ma_value = _load_day_ma_from_db(
        code=code,
        as_of_day=latest_klu.time.to_str(),
        period=ma_period,
    )
    if ma_value is None:
        return False

    return float(latest_klu.close) > float(ma_value)


def detect_day_ma_30m_any_buy(
    snapshot: CChan,
    day_idx: int,
    m30_idx: int,
    code: str,
    ma_period: int = 50,
    buy_types: Optional[Iterable[str]] = None,
) -> Optional[StrategyHit]:
    type_set = set(buy_types or DEFAULT_BUY_TYPES)
    if not is_day_above_ma(snapshot, day_idx, code, ma_period=ma_period):
        return None

    bsp_list = snapshot.get_latest_bsp(idx=m30_idx, number=1)
    if not bsp_list:
        return None

    bsp = bsp_list[0]
    if not bsp.is_buy:
        return None
    if not bsp.bi.is_sure:
        return None

    bsp_types = _normalize_bsp_types(bsp.type2str())
    if not any(t in type_set for t in bsp_types):
        return None

    signal_dt = datetime(
        bsp.klu.time.year,
        bsp.klu.time.month,
        bsp.klu.time.day,
        bsp.klu.time.hour,
        bsp.klu.time.minute,
    )
    day_latest_klu = snapshot[day_idx][-1][-1]
    observation_dt = datetime(
        day_latest_klu.time.year,
        day_latest_klu.time.month,
        day_latest_klu.time.day,
        day_latest_klu.time.hour,
        day_latest_klu.time.minute,
    )
    return StrategyHit(
        signal_time=signal_dt,
        signal_date=signal_dt.strftime("%Y-%m-%d"),
        observation_time=observation_dt,
        observation_date=observation_dt.strftime("%Y-%m-%d"),
        bsp_type=bsp.type2str(),
        signal_price=float(bsp.klu.close),
    )


def detect_day_ma50_30m_any_buy(
    snapshot: CChan,
    day_idx: int,
    m30_idx: int,
    code: str,
    buy_types: Optional[Iterable[str]] = None,
) -> Optional[StrategyHit]:
    return detect_day_ma_30m_any_buy(
        snapshot=snapshot,
        day_idx=day_idx,
        m30_idx=m30_idx,
        code=code,
        ma_period=50,
        buy_types=buy_types,
    )
