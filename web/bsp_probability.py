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
    sample_key,
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
from .bsp_signal_identity import build_signal_key


ROOT_DIR = Path(__file__).resolve().parent.parent
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
    deprecated_features = sorted(name for name in feature_meta if name.startswith("stability_"))
    if deprecated_features:
        raise ValueError(
            f"模型仍包含已废弃的 stability_* 特征，请重新训练后再使用：{model_dir.relative_to(ROOT_DIR)}"
        )
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
    probabilities, model_dir = _predict_probabilities(label_group, signal_side, [feature])
    return probabilities[0], model_dir


def _predict_probabilities(label_group: str, signal_side: str, features: List[Dict[str, float]]) -> tuple[List[float], str]:
    model, feature_meta, model_dir = _load_model_bundle(label_group, signal_side)
    rows = [_feature_row(feature, feature_meta) for feature in features]
    probabilities = [float(item[1]) for item in model.predict_proba(rows)]
    return probabilities, str(model_dir.relative_to(ROOT_DIR))


def _price_span(bars: List[Dict[str, Any]]) -> float:
    if not bars:
        return 1.0
    min_price = min(float(bar["low"]) for bar in bars)
    max_price = max(float(bar["high"]) for bar in bars)
    return max(max_price - min_price, max(abs(max_price), 1.0) * 0.03)


def _marker_payload(
    *,
    code: str,
    klu,
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
    signal_time = klu.time.to_str()
    bi_begin_time = ctime_to_str(bi.get_begin_klu().time)
    bi_end_time = ctime_to_str(bi.get_end_klu().time)
    bi_direction = bi_direction_text(bi)
    signal_key = build_signal_key(
        code=code,
        level="30M",
        label_group=label_group,
        signal_side=signal_side,
        target_types=MODEL_GROUPS[label_group]["target_types"],
        signal_time=signal_time,
        bi_begin_time=bi_begin_time,
        bi_end_time=bi_end_time,
        bi_direction=bi_direction,
    )
    return {
        "signalKey": signal_key,
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
        "signalTime": signal_time,
        "biBeginTime": bi_begin_time,
        "biEndTime": bi_end_time,
        "biDirection": bi_direction,
        "status": "stable_predicted",
        "stabilityProbability": probability,
        "labelMode": "stability",
        "labelSource": "trained_model",
        "scoringMode": "final_structure",
        "modelDir": model_dir,
        "tooltip": (
            f"{MODEL_GROUPS[label_group]['name']} {MODEL_GROUPS[label_group]['target_types']} "
            f"{'买' if is_buy else '卖'}点稳定概率 {probability:.1%}; "
            f"signal={klu.time.to_str()}"
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

    for _ in chan.step_load():
        pass
    level_chan = chan[MODEL_LV_IDX]
    child_level_chan = chan[CHILD_LV_IDX]
    final_klus = list(level_chan.klu_iter())
    if not final_klus:
        return markers, loaded_model_dirs
    pos_by_idx = {int(klu.idx): pos for pos, klu in enumerate(final_klus)}
    sorted_bsp_list = level_chan.bs_point_lst.getSortedBspList()

    for signal_side, target_is_buy in (("buy", True), ("sell", False)):
        entries = []
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
            entries.append((entry_klu, bi, feature))
        if entries:
            probabilities, model_dir = _predict_probabilities("first", signal_side, [item[2] for item in entries])
            loaded_model_dirs[signal_side] = model_dir
            for (entry_klu, bi, _feature), probability in zip(entries, probabilities):
                markers.append(_marker_payload(
                    code=code,
                    klu=entry_klu,
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

    for _ in chan.step_load():
        pass
    level_chan = chan[MODEL_LV_IDX]
    child_level_chan = chan[CHILD_LV_IDX]
    final_klus = list(level_chan.klu_iter())
    if not final_klus:
        return markers, loaded_model_dirs
    pos_by_idx = {int(klu.idx): pos for pos, klu in enumerate(final_klus)}
    sorted_bsp_list = level_chan.bs_point_lst.getSortedBspList()

    for signal_side, target_is_buy in (("buy", True), ("sell", False)):
        entries = []
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
            entries.append((entry_klu, bi, feature))
        if entries:
            probabilities, model_dir = _predict_probabilities("second", signal_side, [item[2] for item in entries])
            loaded_model_dirs[signal_side] = model_dir
            for (entry_klu, bi, _feature), probability in zip(entries, probabilities):
                markers.append(_marker_payload(
                    code=code,
                    klu=entry_klu,
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

    markers.sort(key=lambda item: (item["time"], item["signalSide"]))
    status = "ok" if any(model.get("status") == "ok" for model in models.values()) else "error"
    return {
        "enabled": True,
        "status": status,
        "code": model_code,
        "modelLevel": "30M",
        "scoringMode": "final_structure",
        "labelMode": "stability",
        "labelSource": "trained_model",
        "models": models,
        "scoredCount": len(markers),
        "markers": markers,
    }
