from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, List, Optional, Sequence, Tuple

from Chan import CChan
from Common.CEnum import BI_DIR

STEPDef = Tuple[bool, set[str], str]

VALID_BSP_LABELS = {
    "B1",
    "B1p",
    "B2",
    "B2s",
    "B3",
    "B3a",
    "B3b",
    "S1",
    "S1p",
    "S2",
    "S2s",
    "S3",
    "S3a",
    "S3b",
}

WILDCARD_TYPE_MAP: dict[str, set[str]] = {
    "1": {"1", "1p"},
    "2": {"2", "2s"},
    "3": {"3a", "3b"},
}

EXACT_SUFFIX_MAP: dict[str, set[str]] = {
    "1p": {"1p"},
    "2s": {"2s"},
    "3a": {"3a"},
    "3b": {"3b"},
}


@dataclass
class SequenceHit:
    signal_time: datetime
    signal_date: str
    signal_price: float
    observation_time: datetime
    observation_date: str
    sequence_str: str
    matched_steps: List[dict[str, Any]]
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


def parse_bsp_label(label: str) -> STEPDef:
    text = str(label).strip()
    if len(text) < 2:
        raise ValueError(f"非法 BSP 标签: {label}")

    prefix = text[0].upper()
    body = text[1:].lower()

    if prefix not in {"B", "S"}:
        raise ValueError(f"非法 BSP 标签: {label}")

    digit = body[0]
    suffix = body[1:]
    if digit not in {"1", "2", "3"}:
        raise ValueError(f"非法 BSP 标签: {label}")

    if suffix == "":
        bsp_types = set(WILDCARD_TYPE_MAP[digit])
        canonical = f"{prefix}{digit}"
    else:
        typed_key = f"{digit}{suffix}"
        if typed_key not in EXACT_SUFFIX_MAP:
            raise ValueError(f"非法 BSP 标签: {label}")
        bsp_types = set(EXACT_SUFFIX_MAP[typed_key])
        canonical = f"{prefix}{typed_key}"
        canonical = canonical[0] + canonical[1:].lower()

    if canonical not in VALID_BSP_LABELS:
        raise ValueError(f"非法 BSP 标签: {label}")

    is_buy = prefix == "B"
    return is_buy, bsp_types, canonical


def parse_sequence(tokens: Sequence[str]) -> List[STEPDef]:
    if not tokens:
        raise ValueError("--sequence 至少需要 2 个标签")

    parsed = [parse_bsp_label(token) for token in tokens]
    if len(parsed) < 2:
        raise ValueError("--sequence 至少需要 2 个标签")
    return parsed


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


def is_day_last_bi_down_sure(snapshot: CChan, day_idx: int) -> bool:
    day_kl = snapshot[day_idx]
    if len(day_kl.bi_list) == 0:
        return False
    last_bi = day_kl.bi_list[-1]
    return last_bi.dir == BI_DIR.DOWN and last_bi.is_sure


def detect_m30_bsp_sequence(
    snapshot: CChan,
    m30_idx: int,
    observation_time: datetime,
    sequence: Sequence[STEPDef],
    max_gap_days: int = 5,
    require_bi_sure: bool = True,
) -> Optional[SequenceHit]:
    if len(sequence) < 2:
        return None

    bsp_list = snapshot[m30_idx].bs_point_lst.getSortedBspList()
    if len(bsp_list) < len(sequence):
        return None

    positions = [-1] * len(sequence)
    matched_bsps = [None] * len(sequence)
    search_end = len(bsp_list) - 1

    for step_idx in range(len(sequence) - 1, -1, -1):
        step_is_buy, step_types, _ = sequence[step_idx]
        found = False
        for pos in range(search_end, -1, -1):
            bsp = bsp_list[pos]
            if require_bi_sure and not bsp.bi.is_sure:
                continue
            if bsp.is_buy != step_is_buy:
                continue
            bsp_types = _normalize_bsp_types(bsp.type2str())
            if not any(t in step_types for t in bsp_types):
                continue
            positions[step_idx] = pos
            matched_bsps[step_idx] = bsp
            search_end = pos - 1
            found = True
            break
        if not found:
            return None

    for idx in range(1, len(positions)):
        if positions[idx] - positions[idx - 1] != 1:
            return None

    first_bsp = matched_bsps[0]
    last_bsp = matched_bsps[-1]
    if first_bsp is None or last_bsp is None:
        return None

    first_time = _to_datetime(first_bsp.klu.time)
    signal_time = _to_datetime(last_bsp.klu.time)
    trading_dates = _extract_trading_dates(snapshot[m30_idx])
    gap_days = _trading_day_gap(first_time.date(), signal_time.date(), trading_dates)
    if gap_days < 0 or gap_days > max_gap_days:
        return None

    matched_steps: List[dict[str, Any]] = []
    for seq_idx, (bsp, step_def) in enumerate(zip(matched_bsps, sequence), start=1):
        if bsp is None:
            return None
        _, step_types, step_label = step_def
        bsp_types = _normalize_bsp_types(bsp.type2str())
        hit_type = _pick_hit_type(bsp_types, step_types)
        step_time = _to_datetime(bsp.klu.time)
        matched_steps.append(
            {
                "step": seq_idx,
                "label": step_label,
                "type": hit_type,
                "is_buy": bool(bsp.is_buy),
                "time": step_time,
                "price": float(bsp.klu.close),
            }
        )

    sequence_str = " ".join(step[2] for step in sequence)

    return SequenceHit(
        signal_time=signal_time,
        signal_date=signal_time.strftime("%Y-%m-%d"),
        signal_price=float(last_bsp.klu.close),
        observation_time=observation_time,
        observation_date=observation_time.strftime("%Y-%m-%d"),
        sequence_str=sequence_str,
        matched_steps=matched_steps,
        gap_days=gap_days,
    )
