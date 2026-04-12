from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional

from Chan import CChan

S3_TYPES = {"3a", "3b"}
B1_TYPES = {"1", "1p"}


@dataclass
class SequenceHit:
    signal_time: datetime
    signal_date: str
    signal_price: float
    observation_time: datetime
    observation_date: str
    s3_type: str
    s3_time: datetime
    s3_price: float
    b1_type: str
    b1_time: datetime
    b1_price: float
    gap_days: int


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


def _pick_hit_type(candidates: List[str], target_types: set[str]) -> str:
    for t in candidates:
        if t in target_types:
            return t
    return ""


def _extract_trading_dates(level_kl) -> List[date]:
    days = {
        date(klc[0].time.year, klc[0].time.month, klc[0].time.day)
        for klc in level_kl
        if len(klc) > 0
    }
    return sorted(days)


def _trading_day_gap(d1: date, d2: date, trading_dates: List[date]) -> int:
    if d1 == d2:
        return 0
    positions = {d: i for i, d in enumerate(trading_dates)}
    if d1 in positions and d2 in positions:
        return abs(positions[d1] - positions[d2])
    return abs((d2 - d1).days)


def detect_m30_s3_b1_buy(
    snapshot: CChan,
    m30_idx: int,
    observation_time: datetime,
    max_gap_days: int = 5,
    require_bi_sure: bool = True,
) -> Optional[SequenceHit]:
    bsp_list = snapshot[m30_idx].bs_point_lst.getSortedBspList()
    if not bsp_list:
        return None
    


    b1_pos = -1
    b1_bsp = None
    for i in range(len(bsp_list) - 1, -1, -1):
        bsp = bsp_list[i]
        if not bsp.is_buy:
            continue
        if require_bi_sure and not bsp.bi.is_sure:
            continue
        bsp_types = _normalize_bsp_types(bsp.type2str())
        if not any(t in B1_TYPES for t in bsp_types):
            continue
        b1_pos = i
        b1_bsp = bsp
        break

    if b1_bsp is None:
        return None

    s3_pos = -1
    s3_bsp = None
    for i in range(b1_pos - 1, -1, -1):
        bsp = bsp_list[i]
        if bsp.is_buy:
            continue
        bsp_types = _normalize_bsp_types(bsp.type2str())
        if not any(t in S3_TYPES for t in bsp_types):
            continue
        s3_pos = i
        s3_bsp = bsp
        break

    if s3_bsp is None:
        return None

    #这一行是在做“纯净序列”校验。
    # b1_pos 是最新 B1 在 bsp_list 里的位置，s3_pos 是它之前最近 S3 的位置。  
    # 所以：
    # - b1_pos - s3_pos == 1：表示 S3 和 B1 紧挨着，中间没有任何其他 BSP
    if b1_pos - s3_pos != 1:
        return None

    s3_time = _to_datetime(s3_bsp.klu.time)
    b1_time = _to_datetime(b1_bsp.klu.time)
    trading_dates = _extract_trading_dates(snapshot[m30_idx])
    gap_days = _trading_day_gap(s3_time.date(), b1_time.date(), trading_dates)
    if gap_days < 0 or gap_days > max_gap_days:
        return None

    s3_type = _pick_hit_type(_normalize_bsp_types(s3_bsp.type2str()), S3_TYPES)
    b1_type = _pick_hit_type(_normalize_bsp_types(b1_bsp.type2str()), B1_TYPES)

    # print("BSP List:")
    # for bsp in bsp_list:
    #     print(f"  {bsp.type2str()} - {'Buy' if bsp.is_buy else 'Sell'} - {bsp.klu.time.to_str()} - Close: {bsp.klu.close} - BI Sure: {bsp.bi.is_sure}")

    return SequenceHit(
        signal_time=b1_time,
        signal_date=b1_time.strftime("%Y-%m-%d"),
        signal_price=float(b1_bsp.klu.close),
        observation_time=observation_time,
        observation_date=observation_time.strftime("%Y-%m-%d"),
        s3_type=s3_type,
        s3_time=s3_time,
        s3_price=float(s3_bsp.klu.close),
        b1_type=b1_type,
        b1_time=b1_time,
        b1_price=float(b1_bsp.klu.close),
        gap_days=gap_days,
    )
