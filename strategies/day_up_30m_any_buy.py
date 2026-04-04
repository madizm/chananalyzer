from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional

from Chan import CChan
from Common.CEnum import BI_DIR


DEFAULT_BUY_TYPES = ["1", "1p", "2", "2s", "3a", "3b"]


@dataclass
class StrategyHit:
    signal_time: datetime
    signal_date: str
    bsp_type: str
    signal_price: float


def _normalize_bsp_types(type_text: str) -> List[str]:
    return [x.strip() for x in str(type_text).split(",") if x.strip()]


def is_day_uptrend(snapshot: CChan, day_idx: int) -> bool:
    day_kl = snapshot[day_idx]
    # if len(day_kl.seg_list) > 0:
    #     return day_kl.seg_list[-1].dir == BI_DIR.UP
    if len(day_kl.bi_list) > 0:
        return day_kl.bi_list[-1].dir == BI_DIR.UP
    return False


def detect_day_up_30m_any_buy(
    snapshot: CChan,
    day_idx: int,
    m30_idx: int,
    buy_types: Optional[Iterable[str]] = None,
) -> Optional[StrategyHit]:
    type_set = set(buy_types or DEFAULT_BUY_TYPES)
    if not is_day_uptrend(snapshot, day_idx):
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
    return StrategyHit(
        signal_time=signal_dt,
        signal_date=signal_dt.strftime("%Y-%m-%d"),
        bsp_type=bsp.type2str(),
        signal_price=float(bsp.klu.close),
    )
