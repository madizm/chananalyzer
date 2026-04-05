from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, List, Optional

from Chan import CChan


DEFAULT_BUY_TYPES = ["1", "1p", "2", "2s", "3a", "3b"]


@dataclass(frozen=True)
class BSPCandidate:
    level: str
    bsp_key: str
    signal_time: datetime
    signal_date: str
    bsp_type: str
    signal_price: float


@dataclass
class ResonanceHit:
    signal_time: datetime
    signal_date: str
    signal_price: float
    observation_time: datetime
    observation_date: str
    day_bsp_key: str
    day_bsp_time: datetime
    day_bsp_type: str
    day_signal_price: float
    m30_bsp_key: str
    m30_bsp_time: datetime
    m30_bsp_type: str
    m30_signal_price: float
    resonance_gap_days: int


class BSPPool:
    def __init__(self, max_size: int = 3):
        self.max_size = max(1, int(max_size))
        self._items: List[BSPCandidate] = []
        self._keys = set()

    def add(self, item: BSPCandidate) -> bool:
        if item.bsp_key in self._keys:
            return False
        self._items.append(item)
        self._keys.add(item.bsp_key)
        while len(self._items) > self.max_size:
            old = self._items.pop(0)
            self._keys.discard(old.bsp_key)
        return True

    def items(self) -> List[BSPCandidate]:
        return list(self._items)


def _normalize_bsp_types(type_text: str) -> List[str]:
    return [x.strip() for x in str(type_text).split(",") if x.strip()]


def _to_datetime(ctime_obj) -> datetime:
    return datetime(
        ctime_obj.year,
        ctime_obj.month,
        ctime_obj.day,
        ctime_obj.hour,
        ctime_obj.minute,
    )


def _make_bsp_key(level: str, signal_dt: datetime, bsp_type: str, bi_idx: int) -> str:
    return f"{level}|{signal_dt.isoformat()}|{bsp_type}|{bi_idx}"


def extract_latest_buy_candidates(
    snapshot: CChan,
    idx: int,
    level: str,
    buy_types: Optional[Iterable[str]],
    require_bi_sure: bool,
    number: int,
) -> List[BSPCandidate]:
    type_set = set(buy_types or DEFAULT_BUY_TYPES)
    result: List[BSPCandidate] = []

    bsp_list = snapshot.get_latest_bsp(idx=idx, number=number)
    for bsp in reversed(bsp_list):
        if not bsp.is_buy:
            continue
        if require_bi_sure and not bsp.bi.is_sure:
            continue

        bsp_type = bsp.type2str()
        bsp_types = _normalize_bsp_types(bsp_type)
        if not any(t in type_set for t in bsp_types):
            continue

        signal_dt = _to_datetime(bsp.klu.time)
        candidate = BSPCandidate(
            level=level,
            bsp_key=_make_bsp_key(level, signal_dt, bsp_type, bsp.bi.idx),
            signal_time=signal_dt,
            signal_date=signal_dt.strftime("%Y-%m-%d"),
            bsp_type=bsp_type,
            signal_price=float(bsp.klu.close),
        )
        result.append(candidate)

    return result


def trading_day_gap(d1: date, d2: date, trading_dates: List[date]) -> int:
    if d1 == d2:
        return 0

    unique_days = sorted(set(trading_dates))
    day_pos = {d: i for i, d in enumerate(unique_days)}
    if d1 in day_pos and d2 in day_pos:
        return abs(day_pos[d1] - day_pos[d2])
    return abs((d2 - d1).days)


def _build_resonance_hit(
    day_item: BSPCandidate,
    m30_item: BSPCandidate,
    observation_time: datetime,
    gap_days: int,
) -> ResonanceHit:
    if day_item.signal_time >= m30_item.signal_time:
        signal_time = day_item.signal_time
        signal_price = day_item.signal_price
    else:
        signal_time = m30_item.signal_time
        signal_price = m30_item.signal_price

    return ResonanceHit(
        signal_time=signal_time,
        signal_date=signal_time.strftime("%Y-%m-%d"),
        signal_price=signal_price,
        observation_time=observation_time,
        observation_date=observation_time.strftime("%Y-%m-%d"),
        day_bsp_key=day_item.bsp_key,
        day_bsp_time=day_item.signal_time,
        day_bsp_type=day_item.bsp_type,
        day_signal_price=day_item.signal_price,
        m30_bsp_key=m30_item.bsp_key,
        m30_bsp_time=m30_item.signal_time,
        m30_bsp_type=m30_item.bsp_type,
        m30_signal_price=m30_item.signal_price,
        resonance_gap_days=gap_days,
    )


def detect_resonance_hits(
    new_day_items: List[BSPCandidate],
    new_m30_items: List[BSPCandidate],
    day_pool: BSPPool,
    m30_pool: BSPPool,
    observation_time: datetime,
    trading_dates: List[date],
    resonance_window_days: int,
) -> List[ResonanceHit]:
    hits: List[ResonanceHit] = []
    pair_seen = set()

    for day_item in new_day_items:
        for m30_item in m30_pool.items():
            gap = trading_day_gap(day_item.signal_time.date(), m30_item.signal_time.date(), trading_dates)
            if gap > resonance_window_days:
                continue
            pair_key = (day_item.bsp_key, m30_item.bsp_key)
            if pair_key in pair_seen:
                continue
            pair_seen.add(pair_key)
            hits.append(_build_resonance_hit(day_item, m30_item, observation_time, gap))

    for m30_item in new_m30_items:
        for day_item in day_pool.items():
            gap = trading_day_gap(day_item.signal_time.date(), m30_item.signal_time.date(), trading_dates)
            if gap > resonance_window_days:
                continue
            pair_key = (day_item.bsp_key, m30_item.bsp_key)
            if pair_key in pair_seen:
                continue
            pair_seen.add(pair_key)
            hits.append(_build_resonance_hit(day_item, m30_item, observation_time, gap))

    return hits
