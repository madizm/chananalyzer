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
    normalize_cache_code,
)
from Debug.strategy_demo8 import (
    bi_matches_signal_side,
    confirmed_bi_feature,
    latest_previous_bsp,
)
from Debug.strategy_demo9 import (
    build_second_chan,
    latest_previous_first_bsp,
    second_bi_feature,
)


ROOT_DIR = Path(__file__).resolve().parent.parent
MODEL_GROUPS = {
    "first": {
        "name": "一类",
        "target_types": "1/1p",
        "paths": {
            "buy": [
                ROOT_DIR / "Debug" / "model_output" / "strategy_demo8_buy",
                ROOT_DIR / "Debug" / "model_output" / "strategy_demo8",
            ],
            "sell": [
                ROOT_DIR / "Debug" / "model_output" / "strategy_demo8_sell",
            ],
        },
    },
    "second": {
        "name": "二类",
        "target_types": "2/2s",
        "paths": {
            "buy": [
                ROOT_DIR / "Debug" / "model_output" / "strategy_demo9_buy",
            ],
            "sell": [
                ROOT_DIR / "Debug" / "model_output" / "strategy_demo9_sell",
            ],
        },
    },
}


def _model_dir(label_group: str, signal_side: str) -> Path:
    for model_dir in MODEL_GROUPS[label_group]["paths"][signal_side]:
        if (model_dir / "model.pkl").exists() and (model_dir / "feature.meta.json").exists():
            return model_dir
    group_name = MODEL_GROUPS[label_group]["name"]
    raise FileNotFoundError(f"未找到 {signal_side} 方向的{group_name}买卖点模型")


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


def _marker_payload(*, klu, probability: float, signal_side: str, label_group: str, price_span: float) -> Dict[str, Any]:
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
        "isSeg": False,
        "probability": probability,
        "signalSide": signal_side,
        "labelGroup": label_group,
        "targetTypes": MODEL_GROUPS[label_group]["target_types"],
        "rawTime": klu.time.to_str(),
    }


def _parent_context(parent_dates, parent_context_by_date, entry_klu):
    entry_date = ctime_to_date_str(entry_klu.time)
    parent_pos = bisect_left(parent_dates, entry_date) - 1
    return parent_context_by_date[parent_dates[parent_pos]] if parent_pos >= 0 else None


def _scan_first_group(code: str, begin: str, end: Optional[str], price_span: float, visible_from, visible_to):
    parent_dates, parent_context_by_date = build_parent_level_context(code, begin, end)
    chan = build_first_chan(code, begin, end)
    for _ in chan.step_load():
        pass

    level_chan = chan[MODEL_LV_IDX]
    child_level_chan = chan[CHILD_LV_IDX]
    final_klus = list(level_chan.klu_iter())
    pos_by_idx = {int(klu.idx): pos for pos, klu in enumerate(final_klus)}
    sorted_bsp_list = level_chan.bs_point_lst.getSortedBspList()
    markers: List[Dict[str, Any]] = []
    loaded_model_dirs: Dict[str, str] = {}

    for signal_side, target_is_buy in (("buy", True), ("sell", False)):
        for bi in level_chan.bi_list:
            if not bi.is_sure or not bi_matches_signal_side(bi, target_is_buy):
                continue
            entry_klu = bi.get_end_klu()
            marker_time = int(entry_klu.time.ts)
            if visible_from is not None and marker_time < visible_from:
                continue
            if visible_to is not None and marker_time > visible_to:
                continue
            pos = pos_by_idx.get(int(entry_klu.idx))
            if pos is None:
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
            probability, model_dir = _predict_probability("first", signal_side, feature)
            loaded_model_dirs[signal_side] = model_dir
            markers.append(_marker_payload(
                klu=entry_klu,
                probability=probability,
                signal_side=signal_side,
                label_group="first",
                price_span=price_span,
            ))
    return markers, loaded_model_dirs


def _scan_second_group(code: str, begin: str, end: Optional[str], price_span: float, visible_from, visible_to):
    parent_dates, parent_context_by_date = build_parent_level_context(code, begin, end)
    chan = build_second_chan(code, begin, end)
    for _ in chan.step_load():
        pass

    level_chan = chan[MODEL_LV_IDX]
    child_level_chan = chan[CHILD_LV_IDX]
    final_klus = list(level_chan.klu_iter())
    pos_by_idx = {int(klu.idx): pos for pos, klu in enumerate(final_klus)}
    sorted_bsp_list = level_chan.bs_point_lst.getSortedBspList()
    markers: List[Dict[str, Any]] = []
    loaded_model_dirs: Dict[str, str] = {}

    for signal_side, target_is_buy in (("buy", True), ("sell", False)):
        for bi in level_chan.bi_list:
            if not bi.is_sure or not bi_matches_signal_side(bi, target_is_buy):
                continue
            entry_klu = bi.get_end_klu()
            marker_time = int(entry_klu.time.ts)
            if visible_from is not None and marker_time < visible_from:
                continue
            if visible_to is not None and marker_time > visible_to:
                continue
            pos = pos_by_idx.get(int(entry_klu.idx))
            if pos is None:
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
            probability, model_dir = _predict_probability("second", signal_side, feature)
            loaded_model_dirs[signal_side] = model_dir
            markers.append(_marker_payload(
                klu=entry_klu,
                probability=probability,
                signal_side=signal_side,
                label_group="second",
                price_span=price_span,
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
            "reason": "仅30M级别输出买卖点模型概率",
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

    markers.sort(key=lambda item: (item["time"], item["signalSide"]))
    status = "ok" if any(model.get("status") == "ok" for model in models.values()) else "error"
    return {
        "enabled": True,
        "status": status,
        "code": model_code,
        "modelLevel": "30M",
        "models": models,
        "scoredCount": len(markers),
        "markers": markers,
    }
