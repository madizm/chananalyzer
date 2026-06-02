from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from Common.CEnum import KL_TYPE
from Debug.bsp_point_in_time_label import bi_direction_text, target_bsp_by_key
from Debug.strategy_demo7 import (
    MODEL_LV_IDX,
    build_chan as build_first_chan,
    ctime_to_str,
    normalize_cache_code,
)
from Debug.strategy_demo9 import build_second_chan

from .bsp_probability import MODEL_GROUPS
from .bsp_signal_identity import build_signal_key


ROOT_DIR = Path(__file__).resolve().parent.parent


def _price_span(bars: List[Dict[str, Any]]) -> float:
    if not bars:
        return 1.0
    min_price = min(float(bar["low"]) for bar in bars)
    max_price = max(float(bar["high"]) for bar in bars)
    return max(max_price - min_price, max(abs(max_price), 1.0) * 0.03)


def _marker_payload(*, code: str, bsp, label_group: str, signal_side: str, price_span: float) -> Dict[str, Any]:
    bi = bsp.bi
    klu = bi.get_end_klu()
    is_buy = signal_side == "buy"
    signal_time = klu.time.to_str()
    bi_begin_time = ctime_to_str(bi.get_begin_klu().time)
    bi_end_time = ctime_to_str(bi.get_end_klu().time)
    bi_direction = bi_direction_text(bi)
    target_types = MODEL_GROUPS[label_group]["target_types"]
    signal_key = build_signal_key(
        code=code,
        level="30M",
        label_group=label_group,
        signal_side=signal_side,
        target_types=target_types,
        signal_time=signal_time,
        bi_begin_time=bi_begin_time,
        bi_end_time=bi_end_time,
        bi_direction=bi_direction,
    )
    price = float(klu.low if is_buy else klu.high)
    label_offset = 0.135 if label_group == "first" else 0.17
    label_price = price - price_span * label_offset if is_buy else price + price_span * label_offset
    suffix = "1" if label_group == "first" else "2"
    side_prefix = "B" if is_buy else "S"
    color = "#2563eb" if is_buy else "#0f766e"
    return {
        "signalKey": signal_key,
        "time": int(klu.time.ts),
        "price": price,
        "labelPrice": label_price,
        "shape": "arrow_up" if is_buy else "arrow_down",
        "color": color,
        "badge": f"F{side_prefix}{suffix}",
        "isSeg": False,
        "signalSide": signal_side,
        "labelGroup": label_group,
        "targetTypes": target_types,
        "signalTime": signal_time,
        "biBeginTime": bi_begin_time,
        "biEndTime": bi_end_time,
        "biDirection": bi_direction,
        "biIdx": int(bi.idx),
        "kluIdx": int(klu.idx),
        "status": "final_confirmed",
        "scoringMode": "final_structure",
        "labelMode": "final",
        "labelSource": "chan_final_structure",
        "tooltip": (
            f"{MODEL_GROUPS[label_group]['name']} {target_types} "
            f"{'买' if is_buy else '卖'}点 final 确认; signal={signal_time}"
        ),
        "rawTime": signal_time,
    }


def _scan_group(
    *,
    code: str,
    label_group: str,
    begin: str,
    end: Optional[str],
    price_span: float,
    visible_from,
    visible_to,
) -> List[Dict[str, Any]]:
    chan = build_first_chan(code, begin, end) if label_group == "first" else build_second_chan(code, begin, end)
    for _ in chan.step_load():
        pass
    level_chan = chan[MODEL_LV_IDX]
    sorted_bsp_list = level_chan.bs_point_lst.getSortedBspList()
    markers: List[Dict[str, Any]] = []
    seen = set()
    target_types = set(MODEL_GROUPS[label_group]["target_types"].split("/"))

    for signal_side, target_is_buy in (("buy", True), ("sell", False)):
        bsps = target_bsp_by_key(
            code=code,
            signal_side=signal_side,
            sorted_bsp_list=sorted_bsp_list,
            target_is_buy=target_is_buy,
            target_bsp_types=target_types,
        )
        for bsp in sorted(bsps.values(), key=lambda item: int(item.bi.idx)):
            marker_time = int(bsp.bi.get_end_klu().time.ts)
            if visible_from is not None and marker_time < visible_from:
                continue
            if visible_to is not None and marker_time > visible_to:
                continue
            marker = _marker_payload(
                code=code,
                bsp=bsp,
                label_group=label_group,
                signal_side=signal_side,
                price_span=price_span,
            )
            if marker["signalKey"] in seen:
                continue
            markers.append(marker)
            seen.add(marker["signalKey"])
    return markers


def build_bsp_final_payload(
    *,
    code: str,
    lv: KL_TYPE,
    begin: str,
    end: Optional[str],
    bars: List[Dict[str, Any]],
    visible_range: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    if lv != KL_TYPE.K_30M:
        return {
            "enabled": False,
            "status": "skipped",
            "reason": "仅30M级别输出 final 买卖点分析",
            "markers": [],
        }

    model_code = normalize_cache_code(code)
    price_span = _price_span(bars)
    visible_from = visible_range.get("from") if visible_range else None
    visible_to = visible_range.get("to") if visible_range else None
    markers: List[Dict[str, Any]] = []
    groups: Dict[str, Dict[str, Any]] = {}

    for label_group in ("first", "second"):
        try:
            group_markers = _scan_group(
                code=model_code,
                label_group=label_group,
                begin=begin,
                end=end,
                price_span=price_span,
                visible_from=visible_from,
                visible_to=visible_to,
            )
            markers.extend(group_markers)
            groups[label_group] = {
                "status": "ok",
                "name": MODEL_GROUPS[label_group]["name"],
                "targetTypes": MODEL_GROUPS[label_group]["target_types"],
                "confirmedCount": len(group_markers),
            }
        except Exception as exc:
            groups[label_group] = {
                "status": "error",
                "name": MODEL_GROUPS[label_group]["name"],
                "targetTypes": MODEL_GROUPS[label_group]["target_types"],
                "reason": str(exc),
                "confirmedCount": 0,
            }

    markers.sort(key=lambda item: (item["time"], item["labelGroup"], item["signalSide"]))
    status = "ok" if any(group.get("status") == "ok" for group in groups.values()) else "error"
    return {
        "enabled": True,
        "status": status,
        "code": model_code,
        "modelLevel": "30M",
        "scoringMode": "final_structure",
        "labelSource": "chan_final_structure",
        "groups": groups,
        "confirmedCount": len(markers),
        "markers": markers,
    }
