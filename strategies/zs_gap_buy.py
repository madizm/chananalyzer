from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from Chan import CChan


@dataclass(frozen=True)
class ZSGapBuyHit:
    signal_time: datetime
    signal_date: str
    signal_price: float
    observation_time: datetime
    observation_date: str
    latest_zs: dict[str, Any]
    previous_zs: dict[str, Any]
    gap_abs: float
    gap_pct: float


def _to_datetime(time_obj: Any) -> datetime:
    if isinstance(time_obj, datetime):
        return time_obj
    return datetime(
        int(time_obj.year),
        int(time_obj.month),
        int(time_obj.day),
        int(getattr(time_obj, "hour", 0)),
        int(getattr(time_obj, "minute", 0)),
        int(getattr(time_obj, "second", 0)),
    )


def _time_to_str(time_obj: Any) -> str:
    if hasattr(time_obj, "to_str"):
        return str(time_obj.to_str())
    return _to_datetime(time_obj).strftime("%Y-%m-%d %H:%M:%S")


def _latest_close(level_kl: Any, fallback: float) -> float:
    try:
        if len(level_kl) == 0:
            return fallback
        return float(level_kl[-1][-1].close)
    except Exception:
        return fallback


def serialize_zs(zs: Any) -> dict[str, Any]:
    return {
        "begin_time": _time_to_str(zs.begin.time),
        "end_time": _time_to_str(zs.end.time),
        "begin_bi_idx": int(zs.begin_bi.idx),
        "end_bi_idx": int(zs.end_bi.idx),
        "low": float(zs.low),
        "high": float(zs.high),
        "mid": float(zs.mid),
        "peak_low": float(zs.peak_low),
        "peak_high": float(zs.peak_high),
        "is_sure": bool(zs.is_sure),
    }


def _iter_effective_zs(
    level_kl: Any,
    *,
    require_zs_sure: bool,
) -> list[Any]:
    result: list[Any] = []
    for zs in level_kl.zs_list:
        if require_zs_sure and not bool(zs.is_sure):
            continue
        result.append(zs)
    return result


def detect_zs_gap_buy(
    snapshot: CChan,
    signal_idx: int,
    observation_time: datetime,
    *,
    require_zs_sure: bool = True,
    min_gap_pct: float = 0.0,
) -> Optional[ZSGapBuyHit]:
    if min_gap_pct < 0:
        raise ValueError("min_gap_pct 不能小于 0")

    level_kl = snapshot[signal_idx]
    effective_zs = _iter_effective_zs(
        level_kl,
        require_zs_sure=require_zs_sure,
    )
    if len(effective_zs) < 2:
        return None

    previous_zs = effective_zs[-2]
    latest_zs = effective_zs[-1]

    gap_abs = float(latest_zs.low) - float(previous_zs.high)
    if gap_abs <= 0:
        return None

    previous_high = float(previous_zs.high)
    if previous_high <= 0:
        return None

    gap_pct = gap_abs / previous_high * 100
    if gap_pct < min_gap_pct:
        return None

    signal_time = _to_datetime(latest_zs.end.time)
    signal_price = _latest_close(level_kl, fallback=float(latest_zs.end.close))

    return ZSGapBuyHit(
        signal_time=signal_time,
        signal_date=signal_time.strftime("%Y-%m-%d"),
        signal_price=signal_price,
        observation_time=observation_time,
        observation_date=observation_time.strftime("%Y-%m-%d"),
        latest_zs=serialize_zs(latest_zs),
        previous_zs=serialize_zs(previous_zs),
        gap_abs=gap_abs,
        gap_pct=gap_pct,
    )
