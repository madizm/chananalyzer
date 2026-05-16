from __future__ import annotations

import json
import math
import pickle
from bisect import bisect_left
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from Common.CEnum import KL_TYPE
from Debug.strategy_demo7 import (
    CHILD_LV_IDX,
    MODEL_LV_IDX,
    build_chan as build_first_chan,
    build_parent_level_context,
    ctime_to_date_str,
    ctime_to_str,
    normalize_cache_code,
)
from Debug.bsp_point_in_time_label import (
    bi_direction_text,
    latest_confirmed_bi_idx,
    sample_key,
    stability_context_feature,
    target_bsp_by_key,
)
from Debug.strategy_demo8 import (
    confirmed_bi_feature,
    latest_previous_bsp,
)
from Debug.strategy_demo9 import (
    build_second_chan,
    latest_previous_first_bsp,
    second_bi_feature,
)


ROOT_DIR = Path(__file__).resolve().parent.parent
LABEL_MIN_PROBABILITY = 0.55
LABEL_COLLISION_WINDOW_SECONDS = 2 * 24 * 60 * 60
LABEL_LANE_STEP = 0.035
LABEL_GROUP_PRIORITY = {"first": 0, "second": 1}
MODEL_GROUPS = {
    "first": {
        "name": "一类",
        "target_types": "1/1p",
        "dependency_types": set(),
        "paths": {
            "buy": [
                ROOT_DIR / "Debug" / "model_output" / "strategy_demo8_stability_buy",
            ],
            "sell": [
                ROOT_DIR / "Debug" / "model_output" / "strategy_demo8_stability_sell",
            ],
        },
    },
    "second": {
        "name": "二类",
        "target_types": "2/2s",
        "dependency_types": {"1", "1p"},
        "paths": {
            "buy": [
                ROOT_DIR / "Debug" / "model_output" / "strategy_demo9_stability_buy",
            ],
            "sell": [
                ROOT_DIR / "Debug" / "model_output" / "strategy_demo9_stability_sell",
            ],
        },
    },
}


def _model_dir(label_group: str, signal_side: str) -> Path:
    for model_dir in MODEL_GROUPS[label_group]["paths"][signal_side]:
        if (model_dir / "model.pkl").exists() and (model_dir / "feature.meta.json").exists():
            return model_dir
    group_name = MODEL_GROUPS[label_group]["name"]
    raise FileNotFoundError(f"未找到 {signal_side} 方向的{group_name}买卖点 stability 模型")


@lru_cache(maxsize=8)
def _load_model_bundle(label_group: str, signal_side: str):
    model_dir = _model_dir(label_group, signal_side)
    with (model_dir / "model.pkl").open("rb") as fid:
        model = pickle.load(fid)
    with (model_dir / "feature.meta.json").open("r", encoding="utf-8") as fid:
        feature_meta = json.load(fid)
    return model, feature_meta, model_dir


def _feature_row(feature: Dict[str, float], feature_meta: Dict[str, int]) -> List[float]:
    row = [math.nan] * len(feature_meta)
    for name, value in feature.items():
        idx = feature_meta.get(name)
        if idx is None:
            continue
        try:
            row[idx] = float(value)
        except (TypeError, ValueError):
            row[idx] = math.nan
    return row


def _predict_probability(label_group: str, signal_side: str, feature: Dict[str, float]) -> tuple[float, str]:
    model, feature_meta, model_dir = _load_model_bundle(label_group, signal_side)
    row = _feature_row(feature, feature_meta)
    probability = float(model.predict_proba([row])[0][1])
    return probability, str(model_dir.relative_to(ROOT_DIR))


def _price_span(bars: List[Dict[str, Any]]) -> float:
    if not bars:
        return 1.0
    min_price = min(float(bar["low"]) for bar in bars)
    max_price = max(float(bar["high"]) for bar in bars)
    return max(max_price - min_price, max(abs(max_price), 1.0) * 0.03)


def _group_short_name(label_group: str) -> str:
    return "1" if label_group == "first" else "2"


def _label_component(marker: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "labelGroup": marker["labelGroup"],
        "targetTypes": marker["targetTypes"],
        "probability": marker["probability"],
        "modelDir": marker["modelDir"],
    }


def _component_badge(signal_side: str, component: Dict[str, Any]) -> str:
    prefix = "B" if signal_side == "buy" else "S"
    return f"{prefix}{_group_short_name(component['labelGroup'])} {component['probability']:.0%}"


def _merged_badge(signal_side: str, components: List[Dict[str, Any]]) -> str:
    ordered = sorted(
        components,
        key=lambda item: (LABEL_GROUP_PRIORITY.get(item["labelGroup"], 99), -float(item["probability"])),
    )
    return " ".join(_component_badge(signal_side, component) for component in ordered)


def _combined_tooltip(marker: Dict[str, Any], components: List[Dict[str, Any]]) -> str:
    side_name = "买" if marker["signalSide"] == "buy" else "卖"
    detail = "；".join(
        f"{MODEL_GROUPS[item['labelGroup']]['name']} {item['targetTypes']} {side_name}点稳定概率 {item['probability']:.1%}"
        for item in sorted(
            components,
            key=lambda component: (LABEL_GROUP_PRIORITY.get(component["labelGroup"], 99), -float(component["probability"])),
        )
    )
    return (
        f"{detail}; signal={marker['signalTime']}; decision={marker['decisionTime']}; "
        "label=point-in-time-stability"
    )


def _primary_component(components: List[Dict[str, Any]]) -> Dict[str, Any]:
    return max(
        components,
        key=lambda item: (LABEL_GROUP_PRIORITY.get(item["labelGroup"], -1), float(item["probability"])),
    )


def _merge_same_signal_markers(markers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged_by_key: Dict[tuple, Dict[str, Any]] = {}
    for marker in markers:
        key = (
            marker["time"],
            marker["signalSide"],
            marker["biBeginTime"],
            marker["biEndTime"],
            marker["biDirection"],
        )
        component = _label_component(marker)
        if key not in merged_by_key:
            merged = dict(marker)
            merged["components"] = [component]
            merged_by_key[key] = merged
            continue

        merged = merged_by_key[key]
        merged["components"].append(component)
        primary = _primary_component(merged["components"])
        merged["labelGroup"] = primary["labelGroup"]
        merged["targetTypes"] = "/".join(
            sorted({item["targetTypes"] for item in merged["components"]})
        )
        merged["probability"] = max(float(item["probability"]) for item in merged["components"])
        merged["modelDir"] = primary["modelDir"]
        merged["badge"] = _merged_badge(marker["signalSide"], merged["components"])
        merged["tooltip"] = _combined_tooltip(merged, merged["components"])
    return list(merged_by_key.values())


def _layout_probability_labels(markers: List[Dict[str, Any]], price_span: float) -> List[Dict[str, Any]]:
    markers = _merge_same_signal_markers(markers)
    visible_labels: List[Dict[str, Any]] = []
    for marker in sorted(markers, key=lambda item: (item["time"], item["signalSide"], -float(item["probability"]))):
        marker["showText"] = float(marker["probability"]) >= LABEL_MIN_PROBABILITY
        marker["labelLane"] = 0
        if not marker["showText"]:
            continue

        nearby = [
            item for item in visible_labels
            if item["signalSide"] == marker["signalSide"]
            and abs(int(item["time"]) - int(marker["time"])) <= LABEL_COLLISION_WINDOW_SECONDS
        ]
        lane = 0
        used_lanes = {int(item.get("labelLane", 0)) for item in nearby}
        while lane in used_lanes:
            lane += 1
        marker["labelLane"] = lane
        direction = -1 if marker["signalSide"] == "buy" else 1
        base_offset = 0.075 if marker["labelGroup"] == "first" else 0.105
        marker["labelPrice"] = float(marker["price"]) + direction * price_span * (base_offset + lane * LABEL_LANE_STEP)
        visible_labels.append(marker)
    return sorted(markers, key=lambda item: (item["time"], item["signalSide"]))


def _marker_payload(
    *,
    klu,
    decision_klu,
    bi,
    probability: float,
    signal_side: str,
    label_group: str,
    price_span: float,
    model_dir: str,
) -> Dict[str, Any]:
    is_buy = signal_side == "buy"
    price = float(klu.low if is_buy else klu.high)
    label_offset = 0.07 if label_group == "first" else 0.105
    label_price = price - price_span * label_offset if is_buy else price + price_span * label_offset
    prefix = "B" if is_buy else "S"
    suffix = "1 " if label_group == "first" else "2 "
    color = "#b91c1c" if is_buy else "#15803d"
    return {
        "time": int(klu.time.ts),
        "price": price,
        "labelPrice": label_price,
        "shape": "arrow_up" if is_buy else "arrow_down",
        "color": color,
        "badge": f"{prefix}{suffix}{probability:.0%}",
        "showText": True,
        "labelLane": 0,
        "components": [],
        "isSeg": False,
        "probability": probability,
        "signalSide": signal_side,
        "labelGroup": label_group,
        "targetTypes": MODEL_GROUPS[label_group]["target_types"],
        "signalTime": klu.time.to_str(),
        "decisionTime": decision_klu.time.to_str(),
        "biBeginTime": ctime_to_str(bi.get_begin_klu().time),
        "biEndTime": ctime_to_str(bi.get_end_klu().time),
        "biDirection": bi_direction_text(bi),
        "labelMode": "point_in_time_stability",
        "labelSource": "as_of_replay_stability",
        "scoringMode": "stability_replay",
        "modelDir": model_dir,
        "tooltip": (
            f"{MODEL_GROUPS[label_group]['name']} {MODEL_GROUPS[label_group]['target_types']} "
            f"{'买' if is_buy else '卖'}点稳定概率 {probability:.1%}; "
            f"signal={klu.time.to_str()}; decision={decision_klu.time.to_str()}; "
            "label=point-in-time-stability"
        ),
        "rawTime": klu.time.to_str(),
    }


def _parent_context(parent_dates, parent_context_by_date, entry_klu):
    entry_date = ctime_to_date_str(entry_klu.time)
    parent_pos = bisect_left(parent_dates, entry_date) - 1
    return parent_context_by_date[parent_dates[parent_pos]] if parent_pos >= 0 else None


def _scan_first_group(code: str, begin: str, end: Optional[str], price_span: float, visible_from, visible_to):
    parent_dates, parent_context_by_date = build_parent_level_context(code, begin, end)
    chan = build_first_chan(code, begin, end)
    markers: List[Dict[str, Any]] = []
    loaded_model_dirs: Dict[str, str] = {}
    seen = set()

    for snapshot in chan.step_load():
        level_chan = snapshot[MODEL_LV_IDX]
        child_level_chan = snapshot[CHILD_LV_IDX]
        final_klus = list(level_chan.klu_iter())
        if not final_klus:
            continue
        decision_klu = final_klus[-1]
        decision_klu_idx = int(decision_klu.idx)
        pos_by_idx = {int(klu.idx): pos for pos, klu in enumerate(final_klus)}
        sorted_bsp_list = level_chan.bs_point_lst.getSortedBspList()
        latest_bi_idx = latest_confirmed_bi_idx(level_chan)

        for signal_side, target_is_buy in (("buy", True), ("sell", False)):
            bsps = target_bsp_by_key(
                code=code,
                signal_side=signal_side,
                sorted_bsp_list=sorted_bsp_list,
                target_is_buy=target_is_buy,
                target_bsp_types=set(MODEL_GROUPS["first"]["target_types"].split("/")),
            )
            for bsp in sorted(bsps.values(), key=lambda item: int(item.bi.idx)):
                bi = bsp.bi
                key = sample_key(code, signal_side, bi)
                if key in seen:
                    continue
                entry_klu = bi.get_end_klu()
                pos = pos_by_idx.get(int(entry_klu.idx))
                if pos is None:
                    continue
                seen.add(key)
                marker_time = int(entry_klu.time.ts)
                if visible_from is not None and marker_time < visible_from:
                    continue
                if visible_to is not None and marker_time > visible_to:
                    continue
                feature = confirmed_bi_feature(
                    final_klus,
                    pos,
                    bi,
                    target_is_buy,
                    latest_previous_bsp(sorted_bsp_list, bi.idx),
                    _parent_context(parent_dates, parent_context_by_date, entry_klu),
                    child_level_chan,
                )
                feature.update(stability_context_feature(
                    final_klus=final_klus,
                    pos=pos,
                    level_chan=level_chan,
                    bi=bi,
                    bsp=bsp,
                    target_is_buy=target_is_buy,
                    sorted_bsp_list=sorted_bsp_list,
                    dependency_bsp_types=MODEL_GROUPS["first"]["dependency_types"],
                    decision_klu_idx=decision_klu_idx,
                    latest_bi_idx=latest_bi_idx,
                ))
                probability, model_dir = _predict_probability("first", signal_side, feature)
                loaded_model_dirs[signal_side] = model_dir
                markers.append(_marker_payload(
                    klu=entry_klu,
                    decision_klu=decision_klu,
                    bi=bi,
                    probability=probability,
                    signal_side=signal_side,
                    label_group="first",
                    price_span=price_span,
                    model_dir=model_dir,
                ))
    return markers, loaded_model_dirs


def _scan_second_group(code: str, begin: str, end: Optional[str], price_span: float, visible_from, visible_to):
    parent_dates, parent_context_by_date = build_parent_level_context(code, begin, end)
    chan = build_second_chan(code, begin, end)
    markers: List[Dict[str, Any]] = []
    loaded_model_dirs: Dict[str, str] = {}
    seen = set()

    for snapshot in chan.step_load():
        level_chan = snapshot[MODEL_LV_IDX]
        child_level_chan = snapshot[CHILD_LV_IDX]
        final_klus = list(level_chan.klu_iter())
        if not final_klus:
            continue
        decision_klu = final_klus[-1]
        decision_klu_idx = int(decision_klu.idx)
        pos_by_idx = {int(klu.idx): pos for pos, klu in enumerate(final_klus)}
        sorted_bsp_list = level_chan.bs_point_lst.getSortedBspList()
        latest_bi_idx = latest_confirmed_bi_idx(level_chan)

        for signal_side, target_is_buy in (("buy", True), ("sell", False)):
            bsps = target_bsp_by_key(
                code=code,
                signal_side=signal_side,
                sorted_bsp_list=sorted_bsp_list,
                target_is_buy=target_is_buy,
                target_bsp_types=set(MODEL_GROUPS["second"]["target_types"].split("/")),
            )
            for bsp in sorted(bsps.values(), key=lambda item: int(item.bi.idx)):
                bi = bsp.bi
                key = sample_key(code, signal_side, bi)
                if key in seen:
                    continue
                entry_klu = bi.get_end_klu()
                pos = pos_by_idx.get(int(entry_klu.idx))
                if pos is None:
                    continue
                seen.add(key)
                marker_time = int(entry_klu.time.ts)
                if visible_from is not None and marker_time < visible_from:
                    continue
                if visible_to is not None and marker_time > visible_to:
                    continue
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
                feature.update(stability_context_feature(
                    final_klus=final_klus,
                    pos=pos,
                    level_chan=level_chan,
                    bi=bi,
                    bsp=bsp,
                    target_is_buy=target_is_buy,
                    sorted_bsp_list=sorted_bsp_list,
                    dependency_bsp_types=MODEL_GROUPS["second"]["dependency_types"],
                    decision_klu_idx=decision_klu_idx,
                    latest_bi_idx=latest_bi_idx,
                ))
                probability, model_dir = _predict_probability("second", signal_side, feature)
                loaded_model_dirs[signal_side] = model_dir
                markers.append(_marker_payload(
                    klu=entry_klu,
                    decision_klu=decision_klu,
                    bi=bi,
                    probability=probability,
                    signal_side=signal_side,
                    label_group="second",
                    price_span=price_span,
                    model_dir=model_dir,
                ))
    return markers, loaded_model_dirs


def build_bsp_probability_payload(
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
            "reason": "仅30M级别输出买卖点 stability 模型概率",
            "markers": [],
        }

    model_code = normalize_cache_code(code)
    price_span = _price_span(bars)
    visible_from = visible_range.get("from") if visible_range else None
    visible_to = visible_range.get("to") if visible_range else None

    markers: List[Dict[str, Any]] = []
    models: Dict[str, Dict[str, Any]] = {}
    scanners = {
        "first": _scan_first_group,
        "second": _scan_second_group,
    }
    for label_group, scanner in scanners.items():
        try:
            group_markers, loaded_model_dirs = scanner(model_code, begin, end, price_span, visible_from, visible_to)
            markers.extend(group_markers)
            models[label_group] = {
                "status": "ok",
                "name": MODEL_GROUPS[label_group]["name"],
                "targetTypes": MODEL_GROUPS[label_group]["target_types"],
                "modelDirs": loaded_model_dirs,
                "scoredCount": len(group_markers),
            }
        except Exception as exc:
            models[label_group] = {
                "status": "error",
                "name": MODEL_GROUPS[label_group]["name"],
                "targetTypes": MODEL_GROUPS[label_group]["target_types"],
                "reason": str(exc),
                "scoredCount": 0,
            }

    raw_scored_count = len(markers)
    markers = _layout_probability_labels(markers, price_span)
    status = "ok" if any(model.get("status") == "ok" for model in models.values()) else "error"
    return {
        "enabled": True,
        "status": status,
        "code": model_code,
        "modelLevel": "30M",
        "scoringMode": "stability_replay",
        "labelMode": "point_in_time_stability",
        "labelSource": "as_of_replay_stability",
        "labelMinProbability": LABEL_MIN_PROBABILITY,
        "rawScoredCount": raw_scored_count,
        "models": models,
        "scoredCount": len(markers),
        "visibleLabelCount": sum(1 for marker in markers if marker.get("showText")),
        "markers": markers,
    }
