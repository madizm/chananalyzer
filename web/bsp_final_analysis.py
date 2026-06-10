from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from Common.CEnum import KL_TYPE
from Debug.bsp_point_in_time_label import bi_direction_text, target_bsp_by_key
from Debug.strategy_demo7 import (
    CHILD_LV_IDX,
    MODEL_LV_IDX,
    build_chan as build_first_chan,
    build_parent_level_context,
    ctime_to_date_str,
    ctime_to_str,
    normalize_cache_code,
)
from Debug.strategy_demo8 import confirmed_bi_feature, latest_previous_bsp
from Debug.strategy_demo9 import build_second_chan, latest_previous_first_bsp, second_bi_feature

from .bsp_probability import MODEL_GROUPS, _predict_probabilities
from .bsp_signal_identity import build_signal_key


ROOT_DIR = Path(__file__).resolve().parent.parent


def _parent_context(parent_dates, parent_context_by_date, entry_klu):
    entry_date = ctime_to_date_str(entry_klu.time)
    parent_pos = -1
    for idx, parent_date in enumerate(parent_dates):
        if parent_date >= entry_date:
            break
        parent_pos = idx
    return parent_context_by_date[parent_dates[parent_pos]] if parent_pos >= 0 else None


def _price_span(bars: List[Dict[str, Any]]) -> float:
    if not bars:
        return 1.0
    min_price = min(float(bar["low"]) for bar in bars)
    max_price = max(float(bar["high"]) for bar in bars)
    return max(max_price - min_price, max(abs(max_price), 1.0) * 0.03)


def _marker_payload(
    *,
    code: str,
    bsp,
    label_group: str,
    signal_side: str,
    price_span: float,
    status: str = "final_confirmed",
    probability: Optional[float] = None,
    model_dir: Optional[str] = None,
) -> Dict[str, Any]:
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
    is_disappeared = status == "replay_disappeared"
    color = "#f97316" if is_disappeared else ("#2563eb" if is_buy else "#0f766e")
    probability_text = f" {probability:.0%}" if probability is not None else ""
    badge = f"失{side_prefix}{suffix}{probability_text}" if is_disappeared else f"F{side_prefix}{suffix}"
    label_source = "as_of_replay" if is_disappeared else "chan_final_structure"
    tooltip_status = "曾出现但 final 已消失" if is_disappeared else "final 确认"
    probability_tooltip = f"; stability={probability:.1%}" if probability is not None else ""
    return {
        "signalKey": signal_key,
        "time": int(klu.time.ts),
        "price": price,
        "labelPrice": label_price,
        "shape": "arrow_up" if is_buy else "arrow_down",
        "color": color,
        "badge": badge,
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
        "status": status,
        "warningLevel": "medium" if is_disappeared else None,
        "probability": probability,
        "stabilityProbability": probability,
        "modelDir": model_dir,
        "scoringMode": "final_structure",
        "labelMode": "disappeared" if is_disappeared else "final",
        "labelSource": label_source,
        "tooltip": (
            f"{MODEL_GROUPS[label_group]['name']} {target_types} "
            f"{'买' if is_buy else '卖'}点 {tooltip_status}; signal={signal_time}"
            f"{probability_tooltip}"
        ),
        "rawTime": signal_time,
    }


def _build_stability_feature(
    *,
    code: str,
    label_group: str,
    signal_side: str,
    final_klus: List,
    pos_by_idx: Dict[int, int],
    bi,
    target_is_buy: bool,
    sorted_bsp_list: List,
    parent_dates,
    parent_context_by_date,
    child_level_chan,
) -> tuple[Optional[Dict[str, float]], Optional[str]]:
    entry_klu = bi.get_end_klu()
    pos = pos_by_idx.get(int(entry_klu.idx))
    if pos is None:
        return None, "missing_pos"
    try:
        if label_group == "first":
            feature = confirmed_bi_feature(
                final_klus,
                pos,
                bi,
                target_is_buy,
                latest_previous_bsp(sorted_bsp_list, bi.idx),
                _parent_context(parent_dates, parent_context_by_date, entry_klu),
                child_level_chan,
            )
        else:
            feature = second_bi_feature(
                final_klus,
                pos,
                bi,
                target_is_buy,
                latest_previous_bsp(sorted_bsp_list, bi.idx),
                latest_previous_first_bsp(sorted_bsp_list, bi.idx, target_is_buy),
                _parent_context(parent_dates, parent_context_by_date, entry_klu),
                child_level_chan,
            )
        return feature, None
    except Exception as exc:
        return None, str(exc)


def _apply_batch_probabilities(label_group: str, score_items_by_side: Dict[str, List[tuple[Dict[str, Any], Dict[str, float]]]]) -> None:
    for signal_side, items in score_items_by_side.items():
        if not items:
            continue
        features = [feature for _marker, feature in items]
        probabilities, model_dir = _predict_probabilities(label_group, signal_side, features)
        for (marker, _feature), probability in zip(items, probabilities):
            marker["probability"] = probability
            marker["stabilityProbability"] = probability
            marker["modelDir"] = model_dir


def _scan_group(
    *,
    code: str,
    label_group: str,
    begin: str,
    end: Optional[str],
    price_span: float,
    visible_from,
    visible_to,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    parent_dates, parent_context_by_date = build_parent_level_context(code, begin, end)
    chan = build_first_chan(code, begin, end) if label_group == "first" else build_second_chan(code, begin, end)
    final_markers: List[Dict[str, Any]] = []
    seen_markers_by_key: Dict[str, Dict[str, Any]] = {}
    score_items_by_side: Dict[str, List[tuple[Dict[str, Any], Dict[str, float]]]] = {"buy": [], "sell": []}
    target_types = set(MODEL_GROUPS[label_group]["target_types"].split("/"))

    for snapshot in chan.step_load():
        level_chan = snapshot[MODEL_LV_IDX]
        child_level_chan = snapshot[CHILD_LV_IDX]
        final_klus = list(level_chan.klu_iter())
        pos_by_idx = {int(klu.idx): pos for pos, klu in enumerate(final_klus)}
        sorted_bsp_list = level_chan.bs_point_lst.getSortedBspList()
        snapshot_markers: List[Dict[str, Any]] = []
        snapshot_keys = set()
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
                feature, score_error = _build_stability_feature(
                    code=code,
                    label_group=label_group,
                    signal_side=signal_side,
                    final_klus=final_klus,
                    pos_by_idx=pos_by_idx,
                    bi=bsp.bi,
                    target_is_buy=target_is_buy,
                    sorted_bsp_list=sorted_bsp_list,
                    parent_dates=parent_dates,
                    parent_context_by_date=parent_context_by_date,
                    child_level_chan=child_level_chan,
                )
                marker = _marker_payload(
                    code=code,
                    bsp=bsp,
                    label_group=label_group,
                    signal_side=signal_side,
                    price_span=price_span,
                )
                if score_error:
                    marker["stabilityScoreError"] = score_error
                if marker["signalKey"] in snapshot_keys:
                    continue
                snapshot_markers.append(marker)
                snapshot_keys.add(marker["signalKey"])
                if marker["signalKey"] not in seen_markers_by_key:
                    seen_markers_by_key[marker["signalKey"]] = marker
                    if feature is not None:
                        score_items_by_side[signal_side].append((marker, feature))
        final_markers = snapshot_markers

    _apply_batch_probabilities(label_group, score_items_by_side)
    for marker in final_markers:
        first_seen_marker = seen_markers_by_key.get(marker["signalKey"])
        if not first_seen_marker:
            continue
        for key in ("probability", "stabilityProbability", "modelDir", "stabilityScoreError"):
            if key in first_seen_marker:
                marker[key] = first_seen_marker[key]

    final_keys = {marker["signalKey"] for marker in final_markers}
    disappeared_markers = []
    for signal_key, marker in seen_markers_by_key.items():
        if signal_key in final_keys:
            continue
        disappeared = dict(marker)
        side_prefix = "B" if disappeared.get("signalSide") == "buy" else "S"
        group_suffix = "1" if label_group == "first" else "2"
        disappeared.update({
            "status": "replay_disappeared",
            "warningLevel": "medium",
            "color": "#f97316",
            "badge": (
                f"失{side_prefix}{group_suffix} {float(disappeared['stabilityProbability']):.0%}"
                if disappeared.get("stabilityProbability") is not None
                else f"失{side_prefix}{group_suffix}"
            ),
            "labelMode": "disappeared",
            "labelSource": "as_of_replay",
            "tooltip": (
                f"{MODEL_GROUPS[label_group]['name']} {MODEL_GROUPS[label_group]['target_types']} "
                f"{'买' if disappeared.get('signalSide') == 'buy' else '卖'}点曾在回放中出现，但 final 结构已消失; "
                f"signal={disappeared.get('signalTime')}"
                + (
                    f"; stability={float(disappeared['stabilityProbability']):.1%}"
                    if disappeared.get("stabilityProbability") is not None
                    else ""
                )
            ),
        })
        disappeared_markers.append(disappeared)
    return final_markers, disappeared_markers


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
    replay_disappeared_markers: List[Dict[str, Any]] = []
    groups: Dict[str, Dict[str, Any]] = {}

    for label_group in ("first", "second"):
        try:
            group_markers, group_disappeared_markers = _scan_group(
                code=model_code,
                label_group=label_group,
                begin=begin,
                end=end,
                price_span=price_span,
                visible_from=visible_from,
                visible_to=visible_to,
            )
            markers.extend(group_markers)
            replay_disappeared_markers.extend(group_disappeared_markers)
            groups[label_group] = {
                "status": "ok",
                "name": MODEL_GROUPS[label_group]["name"],
                "targetTypes": MODEL_GROUPS[label_group]["target_types"],
                "confirmedCount": len(group_markers),
                "replayDisappearedCount": len(group_disappeared_markers),
            }
        except Exception as exc:
            groups[label_group] = {
                "status": "error",
                "name": MODEL_GROUPS[label_group]["name"],
                "targetTypes": MODEL_GROUPS[label_group]["target_types"],
                "reason": str(exc),
                "confirmedCount": 0,
                "replayDisappearedCount": 0,
            }

    markers.sort(key=lambda item: (item["time"], item["labelGroup"], item["signalSide"]))
    replay_disappeared_markers.sort(key=lambda item: (item["time"], item["labelGroup"], item["signalSide"]))
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
        "replayDisappearedCount": len(replay_disappeared_markers),
        "markers": markers,
        "disappearedMarkers": replay_disappeared_markers,
        "signalWarnings": [
            {
                "level": marker.get("warningLevel") or "medium",
                "signalKey": marker.get("signalKey"),
                "labelGroup": marker.get("labelGroup"),
                "signalSide": marker.get("signalSide"),
                "targetTypes": marker.get("targetTypes"),
                "signalTime": marker.get("signalTime"),
                "stabilityProbability": marker.get("stabilityProbability"),
                "message": "回放中曾出现的信号在 final 结构中消失",
            }
            for marker in replay_disappeared_markers
        ],
    }
