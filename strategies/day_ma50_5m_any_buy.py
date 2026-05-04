from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from Chan import CChan
from strategies.day_ma50_30m_any_buy import is_day_above_ma
from strategies.day_up_30m_any_buy import (
    DEFAULT_BUY_TYPES,
    StrategyHit,
    _normalize_bsp_types,
)


def detect_day_ma_5m_any_buy(
    snapshot: CChan,
    day_idx: int,
    m5_idx: int,
    code: str,
    ma_period: int = 50,
    buy_types: Optional[Iterable[str]] = None,
) -> Optional[StrategyHit]:
    type_set = set(buy_types or DEFAULT_BUY_TYPES)
    if not is_day_above_ma(snapshot, day_idx, code, ma_period=ma_period):
        return None

    bsp_list = snapshot.get_latest_bsp(idx=m5_idx, number=1)
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


def detect_day_ma50_5m_any_buy(
    snapshot: CChan,
    day_idx: int,
    m5_idx: int,
    code: str,
    buy_types: Optional[Iterable[str]] = None,
) -> Optional[StrategyHit]:
    return detect_day_ma_5m_any_buy(
        snapshot=snapshot,
        day_idx=day_idx,
        m5_idx=m5_idx,
        code=code,
        ma_period=50,
        buy_types=buy_types,
    )
