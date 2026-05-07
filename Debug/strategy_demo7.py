import argparse
import csv
import hashlib
import json
import math
import pickle
import sqlite3
import sys
from bisect import bisect_left
from dataclasses import dataclass
from pathlib import Path
from statistics import pstdev
from typing import Dict, Iterable, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_FIELD, DATA_SRC, KL_TYPE


MODEL_KL_TYPE = KL_TYPE.K_30M
CHILD_KL_TYPE = KL_TYPE.K_15M
PARENT_KL_TYPE = KL_TYPE.K_DAY
DB_KL_TYPE = "30M"
CHILD_DB_KL_TYPE = "15M"
PARENT_DB_KL_TYPE = "DAY"
TARGET_BSP_TYPES = {"1", "1p"}
MODEL_LV_IDX = 0
CHILD_LV_IDX = 1
PARENT_BSP_TYPES = ("1", "1p", "2", "2s", "3a", "3b")
MODEL_PARAMS = {
    "type": "RandomForestClassifier",
    "n_estimators": 300,
    "max_depth": 4,
    "min_samples_leaf": 5,
    "class_weight": "balanced_subsample",
}
POST_FILTER_RULES = (
    {
        "name": "entry_upper_shadow_le_0_3",
        "description": "entry_upper_shadow <= 0.3",
    },
    {
        "name": "entry_and_child_close_pos",
        "description": "entry_close_pos >= 0.5 and child_close_pos >= 0.4",
    },
    {
        "name": "entry_child_close_pos_upper_shadow",
        "description": "entry_close_pos >= 0.5 and child_close_pos >= 0.4 and entry_upper_shadow <= 0.3",
    },
    {
        "name": "entry_child_close_pos_upper_shadow_divergence",
        "description": "entry_close_pos >= 0.5 and child_close_pos >= 0.4 and entry_upper_shadow <= 0.3 and prev_bsp_divergence_rate <= 1.0",
    },
)


@dataclass
class SignalSample:
    code: str
    bsp_klu_idx: int
    open_klu_idx: int
    open_time: str
    entry_price: float
    feature: Dict[str, float]
    label: Optional[int] = None
    realized_return: Optional[float] = None
    forward_return: Optional[float] = None
    max_gain: Optional[float] = None
    max_drawdown: Optional[float] = None
    exit_reason: Optional[str] = None


def ctime_to_str(ctime_obj) -> str:
    return ctime_obj.to_str()


def ctime_to_date_str(ctime_obj) -> str:
    return f"{ctime_obj.year:04}/{ctime_obj.month:02}/{ctime_obj.day:02}"


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0 or denominator is None:
        return default
    return numerator / denominator


def trade_metric(klu, field_name: str) -> Optional[float]:
    value = klu.trade_info.metric.get(field_name)
    if value is None:
        return None
    return float(value)


def mean(values: Iterable[float]) -> float:
    values = list(values)
    if not values:
        return 0.0
    return sum(values) / len(values)


def window_before(klus: List, pos: int, window: int) -> List:
    begin = max(0, pos - window + 1)
    return klus[begin:pos + 1]


def recent_return(klus: List, pos: int, window: int) -> float:
    if pos - window < 0:
        return 0.0
    pre_close = float(klus[pos - window].close)
    return safe_div(float(klus[pos].close) - pre_close, pre_close)


def moving_average_dist(klus: List, pos: int, window: int) -> float:
    items = window_before(klus, pos, window)
    ma = mean(float(klu.close) for klu in items)
    return safe_div(float(klus[pos].close) - ma, ma)


def volatility(klus: List, pos: int, window: int) -> float:
    items = window_before(klus, pos, window)
    returns = []
    for pre, cur in zip(items, items[1:]):
        returns.append(safe_div(float(cur.close) - float(pre.close), float(pre.close)))
    if len(returns) < 2:
        return 0.0
    return pstdev(returns)


def ratio_to_recent_avg(klus: List, pos: int, field_name: str, window: int) -> float:
    cur_value = trade_metric(klus[pos], field_name)
    if cur_value is None:
        return 0.0
    items = window_before(klus, pos, window)
    values = [trade_metric(klu, field_name) for klu in items]
    values = [value for value in values if value is not None]
    avg_value = mean(values)
    return safe_div(cur_value - avg_value, avg_value)


def bi_bar_feature(klus: List, bi) -> Dict[str, float]:
    feature = {
        "bi_bar_count": 0.0,
        "bi_red_bar_pct": 0.0,
        "bi_green_bar_pct": 0.0,
        "bi_red_green_count_ratio": 0.0,
        "bi_red_green_amount_ratio": 0.0,
        "bi_red_amount_pct": 0.0,
        "bi_green_amount_pct": 0.0,
        "bi_amount_intensity_20": 0.0,
    }
    begin_idx = min(bi.get_begin_klu().idx, bi.get_end_klu().idx)
    end_idx = max(bi.get_begin_klu().idx, bi.get_end_klu().idx)
    bi_klus = [klu for klu in klus if begin_idx <= klu.idx <= end_idx]
    if not bi_klus:
        return feature

    red_count = 0
    green_count = 0
    red_amount = 0.0
    green_amount = 0.0
    for klu in bi_klus:
        amount = trade_metric(klu, DATA_FIELD.FIELD_TURNOVER) or 0.0
        if float(klu.close) >= float(klu.open):
            red_count += 1
            red_amount += amount
        else:
            green_count += 1
            green_amount += amount

    total_amount = red_amount + green_amount
    total_count = red_count + green_count
    ref_window = [klu for klu in klus if end_idx - 19 <= klu.idx <= end_idx]
    ref_amount_avg = mean((trade_metric(klu, DATA_FIELD.FIELD_TURNOVER) or 0.0) for klu in ref_window)
    bi_amount_avg = safe_div(total_amount, float(total_count))
    feature.update({
        "bi_bar_count": float(total_count),
        "bi_red_bar_pct": safe_div(float(red_count), float(total_count)),
        "bi_green_bar_pct": safe_div(float(green_count), float(total_count)),
        "bi_red_green_count_ratio": safe_div(float(red_count), float(green_count)),
        "bi_red_green_amount_ratio": safe_div(red_amount, green_amount),
        "bi_red_amount_pct": safe_div(red_amount, total_amount),
        "bi_green_amount_pct": safe_div(green_amount, total_amount),
        "bi_amount_intensity_20": safe_div(bi_amount_avg, ref_amount_avg),
    })
    return feature


def previous_bsp_feature(entry_klu, current_bsp, previous_bsp) -> Dict[str, float]:
    feature = {
        "prev_bsp_exists": 0.0,
        "prev_bsp_is_buy": 0.0,
        "prev_bsp_same_direction": 0.0,
        "prev_bsp_type_1": 0.0,
        "prev_bsp_type_1p": 0.0,
        "prev_bsp_type_2": 0.0,
        "prev_bsp_type_2s": 0.0,
        "prev_bsp_type_3a": 0.0,
        "prev_bsp_type_3b": 0.0,
        "prev_bsp_bi_gap": 0.0,
        "prev_bsp_klu_gap": 0.0,
        "prev_bsp_price_change": 0.0,
        "entry_vs_prev_bsp_price": 0.0,
        "prev_bsp_bi_amp": 0.0,
        "prev_bsp_bi_is_sure": 0.0,
        "prev_bsp_divergence_rate": 0.0,
    }
    if previous_bsp is None:
        return feature

    prev_price = float(previous_bsp.klu.close)
    cur_price = float(current_bsp.klu.close)
    feature.update({
        "prev_bsp_exists": 1.0,
        "prev_bsp_is_buy": float(bool(previous_bsp.is_buy)),
        "prev_bsp_same_direction": float(previous_bsp.is_buy == current_bsp.is_buy),
        "prev_bsp_bi_gap": float(current_bsp.bi.idx - previous_bsp.bi.idx),
        "prev_bsp_klu_gap": float(current_bsp.klu.idx - previous_bsp.klu.idx),
        "prev_bsp_price_change": safe_div(cur_price - prev_price, prev_price),
        "entry_vs_prev_bsp_price": safe_div(float(entry_klu.close) - prev_price, prev_price),
        "prev_bsp_bi_amp": float(previous_bsp.bi.amp()),
        "prev_bsp_bi_is_sure": float(bool(previous_bsp.bi.is_sure)),
    })
    for bsp_type in str(previous_bsp.type2str()).split(","):
        bsp_type = bsp_type.strip()
        if bsp_type:
            feature[f"prev_bsp_type_{bsp_type}"] = 1.0
    for feature_name, value in previous_bsp.features.items():
        if feature_name != "divergence_rate" or value is None:
            continue
        try:
            feature["prev_bsp_divergence_rate"] = float(value)
        except (TypeError, ValueError):
            pass
    return feature


def parent_level_feature(entry_klu, parent_context: Optional[Dict[str, float]]) -> Dict[str, float]:
    feature = {
        "parent_exists": 0.0,
        "parent_return": 0.0,
        "parent_range": 0.0,
        "parent_close_pos": 0.0,
        "parent_volume_ratio_5": 0.0,
        "entry_vs_parent_close": 0.0,
        "parent_bi_count": 0.0,
        "parent_last_bi_dir_up": 0.0,
        "parent_last_bi_is_sure": 0.0,
        "parent_latest_bsp_exists": 0.0,
        "parent_latest_bsp_is_buy": 0.0,
        "parent_latest_bsp_price_change": 0.0,
        "parent_latest_bsp_bi_gap": 0.0,
        "parent_latest_bsp_klu_gap": 0.0,
        "parent_latest_bsp_divergence_rate": 0.0,
    }
    for bsp_type in PARENT_BSP_TYPES:
        feature[f"parent_latest_bsp_type_{bsp_type}"] = 0.0
    if not parent_context:
        return feature

    parent_close = float(parent_context.get("parent_close", 0.0))
    feature.update(parent_context)
    feature["parent_exists"] = 1.0
    feature["entry_vs_parent_close"] = safe_div(float(entry_klu.close) - parent_close, parent_close)
    feature.pop("parent_close", None)
    return feature


def child_level_feature(entry_klu, main_klc, child_level_chan) -> Dict[str, float]:
    feature = {
        "child_klc_count": 0.0,
        "child_klu_count": 0.0,
        "child_return": 0.0,
        "child_range": 0.0,
        "child_close_pos": 0.0,
        "child_bi_count": 0.0,
        "child_last_bi_dir_up": 0.0,
        "child_last_bi_is_sure": 0.0,
        "child_latest_bsp_exists": 0.0,
        "child_latest_bsp_is_buy": 0.0,
        "child_latest_bsp_price_change": 0.0,
        "child_latest_bsp_bi_gap": 0.0,
        "child_latest_bsp_klu_gap": 0.0,
        "child_latest_bsp_divergence_rate": 0.0,
    }
    for bsp_type in PARENT_BSP_TYPES:
        feature[f"child_latest_bsp_type_{bsp_type}"] = 0.0

    sub_klc_list = list(main_klc.GetSubKLC())
    sub_klu_list = [klu for klc in sub_klc_list for klu in klc.lst]
    if not sub_klu_list:
        return feature

    first_klu = sub_klu_list[0]
    last_klu = sub_klu_list[-1]
    high = max(float(klu.high) for klu in sub_klu_list)
    low = min(float(klu.low) for klu in sub_klu_list)
    feature.update({
        "child_klc_count": float(len(sub_klc_list)),
        "child_klu_count": float(len(sub_klu_list)),
        "child_return": safe_div(float(last_klu.close) - float(first_klu.open), float(first_klu.open)),
        "child_range": safe_div(high - low, float(first_klu.open)),
        "child_close_pos": safe_div(float(last_klu.close) - low, high - low, 0.5),
    })

    max_child_bi_idx = -1
    child_bi_cnt = 0
    for bi in child_level_chan.bi_list:
        if bi.get_end_klu().idx <= last_klu.idx:
            child_bi_cnt += 1
            max_child_bi_idx = max(max_child_bi_idx, bi.idx)
            last_child_bi = bi
        else:
            break
    if child_bi_cnt > 0:
        feature.update({
            "child_bi_count": float(child_bi_cnt),
            "child_last_bi_dir_up": float(bool(last_child_bi.is_up())),
            "child_last_bi_is_sure": float(bool(last_child_bi.is_sure)),
        })

    latest_child_bsp = None
    for bsp in child_level_chan.bs_point_lst.getSortedBspList():
        if bsp.klu.idx <= last_klu.idx:
            latest_child_bsp = bsp
        else:
            break
    if latest_child_bsp is None:
        return feature

    bsp_price = float(latest_child_bsp.klu.close)
    feature.update({
        "child_latest_bsp_exists": 1.0,
        "child_latest_bsp_is_buy": float(bool(latest_child_bsp.is_buy)),
        "child_latest_bsp_price_change": safe_div(float(entry_klu.close) - bsp_price, bsp_price),
        "child_latest_bsp_bi_gap": float(max_child_bi_idx - latest_child_bsp.bi.idx) if max_child_bi_idx >= 0 else 0.0,
        "child_latest_bsp_klu_gap": float(last_klu.idx - latest_child_bsp.klu.idx),
    })
    for bsp_type in str(latest_child_bsp.type2str()).split(","):
        bsp_type = bsp_type.strip()
        if bsp_type:
            feature[f"child_latest_bsp_type_{bsp_type}"] = 1.0
    for feature_name, value in latest_child_bsp.features.items():
        if feature_name != "divergence_rate" or value is None:
            continue
        try:
            feature["child_latest_bsp_divergence_rate"] = float(value)
        except (TypeError, ValueError):
            pass
    return feature


def strategy_feature(klus: List, pos: int, bsp, previous_bsp=None, parent_context=None, child_level_chan=None) -> Dict[str, float]:
    klu = klus[pos]
    high_low_range = float(klu.high) - float(klu.low)
    body_high = max(float(klu.open), float(klu.close))
    body_low = min(float(klu.open), float(klu.close))

    feature = {
        "entry_kline_return": safe_div(float(klu.close) - float(klu.open), float(klu.open)),
        "entry_close_pos": safe_div(float(klu.close) - float(klu.low), high_low_range, 0.5),
        "entry_upper_shadow": safe_div(float(klu.high) - body_high, high_low_range),
        "entry_lower_shadow": safe_div(body_low - float(klu.low), high_low_range),
        "ret_3": recent_return(klus, pos, 3),
        "ret_5": recent_return(klus, pos, 5),
        "ret_10": recent_return(klus, pos, 10),
        "ma_dist_5": moving_average_dist(klus, pos, 5),
        "ma_dist_10": moving_average_dist(klus, pos, 10),
        "ma_dist_20": moving_average_dist(klus, pos, 20),
        "volatility_10": volatility(klus, pos, 10),
        "volume_ratio_5": ratio_to_recent_avg(klus, pos, DATA_FIELD.FIELD_VOLUME, 5),
        "turnover_ratio_5": ratio_to_recent_avg(klus, pos, DATA_FIELD.FIELD_TURNOVER, 5),
        "turnrate_ratio_5": ratio_to_recent_avg(klus, pos, DATA_FIELD.FIELD_TURNRATE, 5),
        "bi_amp": float(bsp.bi.amp()),
        "bi_is_sure": float(bool(bsp.bi.is_sure)),
        "bi_idx": float(bsp.bi.idx),
    }

    for bsp_type in str(bsp.type2str()).split(","):
        bsp_type = bsp_type.strip()
        if bsp_type:
            feature[f"bsp_type_{bsp_type}"] = 1.0

    for feature_name, value in bsp.features.items():
        if value is None:
            continue
        try:
            feature[f"bsp_{feature_name}"] = float(value)
        except (TypeError, ValueError):
            continue

    feature.update(previous_bsp_feature(klu, bsp, previous_bsp))
    feature.update(bi_bar_feature(klus, bsp.bi))
    feature.update(parent_level_feature(klu, parent_context))
    if child_level_chan is not None:
        feature.update(child_level_feature(klu, bsp.klu.klc, child_level_chan))
    return feature


def make_chan_config(bs_type: str, trigger_step: bool = True) -> CChanConfig:
    config = CChanConfig({
        "trigger_step": trigger_step,
        "bi_strict": True,
        "skip_step": 0,
        "kl_data_check": False,
        "divergence_rate": float("inf"),
        "bsp2_follow_1": False,
        "bsp3_follow_1": False,
        "min_zs_cnt": 0,
        "bs1_peak": False,
        "macd_algo": "peak",
        "bs_type": bs_type,
        "print_warning": True,
        "zs_algo": "normal",
    })
    return config


def build_chan(code: str, begin_time: str, end_time: Optional[str]) -> CChan:
    config = make_chan_config("1,1p", trigger_step=True)
    return CChan(
        code=code,
        begin_time=begin_time,
        end_time=end_time,
        data_src=DATA_SRC.CACHE_DB,
        lv_list=[MODEL_KL_TYPE, CHILD_KL_TYPE],
        config=config,
        autype=AUTYPE.QFQ,
    )


def build_parent_chan(code: str, begin_time: str, end_time: Optional[str]) -> CChan:
    config = make_chan_config("1,2,3a,1p,2s,3b", trigger_step=True)
    return CChan(
        code=code,
        begin_time=begin_time,
        end_time=end_time,
        data_src=DATA_SRC.CACHE_DB,
        lv_list=[PARENT_KL_TYPE],
        config=config,
        autype=AUTYPE.QFQ,
    )


def build_parent_level_context(code: str, begin_time: str, end_time: Optional[str]) -> Tuple[List[str], Dict[str, Dict[str, float]]]:
    context_by_date: Dict[str, Dict[str, float]] = {}
    parent_chan = build_parent_chan(code, begin_time, end_time)
    for parent_snapshot in parent_chan.step_load():
        parent_level = parent_snapshot[0]
        parent_klus = list(parent_level.klu_iter())
        if not parent_klus:
            continue
        last_klu = parent_klus[-1]
        pos = len(parent_klus) - 1
        high_low_range = float(last_klu.high) - float(last_klu.low)
        context = {
            "parent_close": float(last_klu.close),
            "parent_return": safe_div(float(last_klu.close) - float(last_klu.open), float(last_klu.open)),
            "parent_range": safe_div(float(last_klu.high) - float(last_klu.low), float(last_klu.open)),
            "parent_close_pos": safe_div(float(last_klu.close) - float(last_klu.low), high_low_range, 0.5),
            "parent_volume_ratio_5": ratio_to_recent_avg(parent_klus, pos, DATA_FIELD.FIELD_VOLUME, 5),
            "parent_bi_count": float(len(parent_level.bi_list)),
            "parent_last_bi_dir_up": 0.0,
            "parent_last_bi_is_sure": 0.0,
            "parent_latest_bsp_exists": 0.0,
            "parent_latest_bsp_is_buy": 0.0,
            "parent_latest_bsp_price_change": 0.0,
            "parent_latest_bsp_bi_gap": 0.0,
            "parent_latest_bsp_klu_gap": 0.0,
            "parent_latest_bsp_divergence_rate": 0.0,
        }
        for bsp_type in PARENT_BSP_TYPES:
            context[f"parent_latest_bsp_type_{bsp_type}"] = 0.0

        if len(parent_level.bi_list) > 0:
            last_bi = parent_level.bi_list[-1]
            context["parent_last_bi_dir_up"] = float(bool(last_bi.is_up()))
            context["parent_last_bi_is_sure"] = float(bool(last_bi.is_sure))

        latest_parent_bsp_list = parent_snapshot.get_latest_bsp(idx=0, number=1)
        if latest_parent_bsp_list:
            latest_parent_bsp = latest_parent_bsp_list[0]
            bsp_price = float(latest_parent_bsp.klu.close)
            context.update({
                "parent_latest_bsp_exists": 1.0,
                "parent_latest_bsp_is_buy": float(bool(latest_parent_bsp.is_buy)),
                "parent_latest_bsp_price_change": safe_div(float(last_klu.close) - bsp_price, bsp_price),
                "parent_latest_bsp_bi_gap": float(len(parent_level.bi_list) - 1 - latest_parent_bsp.bi.idx),
                "parent_latest_bsp_klu_gap": float(last_klu.idx - latest_parent_bsp.klu.idx),
            })
            for bsp_type in str(latest_parent_bsp.type2str()).split(","):
                bsp_type = bsp_type.strip()
                if bsp_type:
                    context[f"parent_latest_bsp_type_{bsp_type}"] = 1.0
            for feature_name, value in latest_parent_bsp.features.items():
                if feature_name != "divergence_rate" or value is None:
                    continue
                try:
                    context["parent_latest_bsp_divergence_rate"] = float(value)
                except (TypeError, ValueError):
                    pass

        context_by_date[ctime_to_date_str(last_klu.time)] = context
    parent_dates = sorted(context_by_date)
    return parent_dates, context_by_date


def pick_parent_context(parent_dates: List[str], context_by_date: Dict[str, Dict[str, float]], entry_klu) -> Optional[Dict[str, float]]:
    entry_date = ctime_to_date_str(entry_klu.time)
    pos = bisect_left(parent_dates, entry_date) - 1
    if pos < 0:
        return None
    return context_by_date[parent_dates[pos]]


def collect_buy_signals(
    chan: CChan,
    code: str,
    parent_dates: Optional[List[str]] = None,
    parent_context_by_date: Optional[Dict[str, Dict[str, float]]] = None,
) -> Tuple[List[SignalSample], List]:
    samples: List[SignalSample] = []
    seen_bsp_klu_idx = set()
    parent_dates = parent_dates or []
    parent_context_by_date = parent_context_by_date or {}

    for chan_snapshot in chan.step_load():
        level_chan = chan_snapshot[MODEL_LV_IDX]
        if len(level_chan) < 2:
            continue

        last_klu = level_chan[-1][-1]
        bsp_list = chan_snapshot.get_latest_bsp(idx=MODEL_LV_IDX)
        if not bsp_list:
            continue

        last_bsp = bsp_list[0]
        if not last_bsp.is_buy:
            continue
        bsp_types = {bsp_type.strip() for bsp_type in str(last_bsp.type2str()).split(",") if bsp_type.strip()}
        if not bsp_types & TARGET_BSP_TYPES:
            continue
        if last_bsp.klu.idx in seen_bsp_klu_idx:
            continue

        # 分型第三元素出现后，倒数第二根合并K线上的买点才是实盘可见信号。
        if level_chan[-2].idx != last_bsp.klu.klc.idx:
            continue

        sorted_bsp_list = level_chan.bs_point_lst.getSortedBspList()
        previous_bsp = None
        for idx, candidate_bsp in enumerate(sorted_bsp_list):
            if candidate_bsp.bi.idx == last_bsp.bi.idx:
                if idx > 0:
                    previous_bsp = sorted_bsp_list[idx - 1]
                break

        final_klus_so_far = list(level_chan.klu_iter())
        pos = len(final_klus_so_far) - 1
        parent_context = pick_parent_context(parent_dates, parent_context_by_date, last_klu)
        samples.append(
            SignalSample(
                code=code,
                bsp_klu_idx=int(last_bsp.klu.idx),
                open_klu_idx=int(last_klu.idx),
                open_time=ctime_to_str(last_klu.time),
                entry_price=float(last_klu.close),
                feature=strategy_feature(
                    final_klus_so_far,
                    pos,
                    last_bsp,
                    previous_bsp,
                    parent_context,
                    chan_snapshot[CHILD_LV_IDX],
                ),
            )
        )
        seen_bsp_klu_idx.add(last_bsp.klu.idx)

    final_klus = list(chan[MODEL_LV_IDX].klu_iter())
    return samples, final_klus


def label_samples(
    samples: List[SignalSample],
    final_klus: List,
    horizon: int,
    take_profit: float,
    stop_loss: float,
) -> List[SignalSample]:
    pos_by_idx = {int(klu.idx): pos for pos, klu in enumerate(final_klus)}
    labeled_samples: List[SignalSample] = []

    for sample in samples:
        if sample.open_klu_idx not in pos_by_idx:
            continue
        open_pos = pos_by_idx[sample.open_klu_idx]
        future = final_klus[open_pos + 1:open_pos + 1 + horizon]
        if len(future) < horizon:
            continue

        entry = sample.entry_price
        take_price = entry * (1 + take_profit)
        stop_price = entry * (1 - stop_loss)
        label = 0
        exit_reason = "timeout"

        for klu in future:
            hit_stop = float(klu.low) <= stop_price
            hit_take = float(klu.high) >= take_price
            if hit_stop:
                label = 0
                exit_reason = "stop_loss"
                break
            if hit_take:
                label = 1
                exit_reason = "take_profit"
                break

        sample.label = label
        sample.exit_reason = exit_reason
        sample.forward_return = safe_div(float(future[-1].close) - entry, entry)
        if exit_reason == "take_profit":
            sample.realized_return = take_profit
        elif exit_reason == "stop_loss":
            sample.realized_return = -stop_loss
        else:
            sample.realized_return = sample.forward_return
        sample.max_gain = safe_div(max(float(klu.high) for klu in future) - entry, entry)
        sample.max_drawdown = safe_div(min(float(klu.low) for klu in future) - entry, entry)
        labeled_samples.append(sample)

    return labeled_samples


def build_feature_meta(samples: List[SignalSample]) -> Dict[str, int]:
    feature_names = sorted({name for sample in samples for name in sample.feature})
    return {name: idx for idx, name in enumerate(feature_names)}


def build_matrix(samples: List[SignalSample], feature_meta: Dict[str, int]) -> List[List[float]]:
    matrix = []
    for sample in samples:
        row = [math.nan] * len(feature_meta)
        for name, value in sample.feature.items():
            if name in feature_meta:
                row[feature_meta[name]] = float(value)
        matrix.append(row)
    return matrix


def parse_code_list(code_text: Optional[str]) -> List[str]:
    if not code_text:
        return []
    return [normalize_cache_code(code) for code in code_text.split(",") if code.strip()]


def normalize_cache_code(code: str) -> str:
    code = code.strip().lower()
    if len(code) == 9 and code[2] == "." and code[:2] in {"sh", "sz"}:
        return code[3:]
    if len(code) == 8 and code[:2] in {"sh", "sz"}:
        return code[2:]
    return code


def get_stock_list_from_cache(kl_type: str = DB_KL_TYPE) -> List[str]:
    db_path = ROOT_DIR / "chan.db"
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT code FROM kline_data WHERE kl_type=? ORDER BY code",
            (kl_type,),
        ).fetchall()
    return [row[0] for row in rows]


def normalize_split_time(split_time: Optional[str]) -> Optional[str]:
    if not split_time:
        return None
    value = split_time.strip().replace("-", "/")
    if len(value) == 10:
        return f"{value} 00:00"
    return value


def split_by_time(
    samples: List[SignalSample],
    train_ratio: float,
    split_time: Optional[str] = None,
) -> Tuple[List[SignalSample], List[SignalSample], Dict[str, str]]:
    sorted_samples = sorted(samples, key=lambda sample: (sample.open_time, sample.code, sample.open_klu_idx))
    split_time = normalize_split_time(split_time)
    if split_time:
        train_samples = [sample for sample in sorted_samples if sample.open_time < split_time]
        test_samples = [sample for sample in sorted_samples if sample.open_time >= split_time]
        split_info = {
            "mode": "time",
            "split_time": split_time,
            "train_period": f"{train_samples[0].open_time} ~ {train_samples[-1].open_time}" if train_samples else "",
            "test_period": f"{test_samples[0].open_time} ~ {test_samples[-1].open_time}" if test_samples else "",
        }
    else:
        split_pos = max(1, min(len(sorted_samples) - 1, int(len(sorted_samples) * train_ratio)))
        train_samples = sorted_samples[:split_pos]
        test_samples = sorted_samples[split_pos:]
        split_info = {
            "mode": "time",
            "split_time": test_samples[0].open_time,
            "train_period": f"{train_samples[0].open_time} ~ {train_samples[-1].open_time}",
            "test_period": f"{test_samples[0].open_time} ~ {test_samples[-1].open_time}",
        }

    if not train_samples or not test_samples:
        raise ValueError(f"时间段划分失败，训练样本={len(train_samples)}，测试样本={len(test_samples)}")
    return train_samples, test_samples, split_info


def sample_period(sample: SignalSample) -> str:
    return sample.open_time[:7]


def normalize_period(period: str) -> str:
    return period.strip().replace("-", "/")[:7]


def period_start_time(period: str) -> str:
    return f"{normalize_period(period)}/01 00:00"


def next_period(period: str) -> str:
    year_text, month_text = normalize_period(period).split("/")
    year = int(year_text)
    month = int(month_text)
    if month == 12:
        return f"{year + 1:04}/01"
    return f"{year:04}/{month + 1:02}"


def period_end_time_exclusive(period: str) -> str:
    return f"{next_period(period)}/01 00:00"


def walk_forward_period_start(period: str, min_test_time: Optional[str]) -> str:
    period_start = period_start_time(period)
    if not min_test_time:
        return period_start
    return max(period_start, normalize_split_time(min_test_time))


def parse_period_list(period_text: Optional[str]) -> Optional[List[str]]:
    if not period_text:
        return None
    return [normalize_period(period) for period in period_text.split(",") if period.strip()]


def parse_float_list(value_text: Optional[str]) -> List[float]:
    if not value_text:
        return []
    return [float(value.strip()) for value in value_text.split(",") if value.strip()]


def metric_or_none(func, y_true, y_score) -> Optional[float]:
    try:
        value = float(func(y_true, y_score))
        if not math.isfinite(value):
            return None
        return value
    except ValueError:
        return None


def avg_optional(values: Iterable[Optional[float]]) -> float:
    real_values = [float(value) for value in values if value is not None]
    if not real_values:
        return 0.0
    return sum(real_values) / len(real_values)


def realized_return_after_cost(sample: SignalSample, trade_cost: float) -> Optional[float]:
    if sample.realized_return is None:
        return None
    return float(sample.realized_return) - trade_cost


def exit_reason_summary(samples: List[SignalSample]) -> Dict:
    reasons = ("take_profit", "stop_loss", "timeout")
    counts = {reason: 0 for reason in reasons}
    counts["other"] = 0
    for sample in samples:
        if sample.exit_reason in counts:
            counts[sample.exit_reason] += 1
        else:
            counts["other"] += 1
    total = len(samples)
    return {
        "exit_reason_counts": counts,
        "exit_reason_rates": {
            reason: safe_div(float(count), float(total))
            for reason, count in counts.items()
        },
    }


def summarize_scored_group(
    scores: List[float],
    samples: List[SignalSample],
    trade_cost: float,
) -> Dict:
    sample_count = len(samples)
    if sample_count == 0:
        return {
            "sample_count": 0,
            "min_score": None,
            "avg_score": None,
            "hit_rate": None,
            "avg_realized_return": None,
            "avg_realized_return_after_cost": None,
            "avg_forward_return": None,
            "avg_max_gain": None,
            "avg_max_drawdown": None,
            **exit_reason_summary([]),
        }
    return {
        "sample_count": sample_count,
        "min_score": min(scores),
        "avg_score": sum(scores) / sample_count,
        "hit_rate": sum(int(sample.label) for sample in samples) / sample_count,
        "avg_realized_return": avg_optional(sample.realized_return for sample in samples),
        "avg_realized_return_after_cost": avg_optional(realized_return_after_cost(sample, trade_cost) for sample in samples),
        "avg_forward_return": avg_optional(sample.forward_return for sample in samples),
        "avg_max_gain": avg_optional(sample.max_gain for sample in samples),
        "avg_max_drawdown": avg_optional(sample.max_drawdown for sample in samples),
        **exit_reason_summary(samples),
    }


def summarize_score_buckets(
    test_prob,
    test_samples: List[SignalSample],
    buckets: Tuple[float, ...] = (0.05, 0.10, 0.20, 0.30),
    trade_cost: float = 0.0,
) -> List[Dict[str, float]]:
    ranked_samples = sorted(zip(test_prob, test_samples), key=lambda item: item[0], reverse=True)
    bucket_rows = []
    for bucket in buckets:
        top_n = max(1, int(len(ranked_samples) * bucket))
        top_items = ranked_samples[:top_n]
        top_scores = [float(score) for score, _ in top_items]
        top_samples = [sample for _, sample in top_items]
        bucket_rows.append({
            "top_pct": bucket,
            **summarize_scored_group(top_scores, top_samples, trade_cost),
        })
    return bucket_rows


def summarize_score_thresholds(
    test_prob,
    test_samples: List[SignalSample],
    thresholds: List[float],
    trade_cost: float,
) -> List[Dict]:
    scored_samples = [(float(score), sample) for score, sample in zip(test_prob, test_samples)]
    rows = []
    for threshold in thresholds:
        items = [(score, sample) for score, sample in scored_samples if score >= threshold]
        scores = [score for score, _ in items]
        samples = [sample for _, sample in items]
        rows.append({
            "threshold": threshold,
            **summarize_scored_group(scores, samples, trade_cost),
        })
    return rows


def sample_feature_value(sample: SignalSample, name: str, default: float = 0.0) -> float:
    value = sample.feature.get(name, default)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def pass_post_filter(sample: SignalSample, rule_name: str) -> bool:
    entry_close_pos = sample_feature_value(sample, "entry_close_pos")
    child_close_pos = sample_feature_value(sample, "child_close_pos")
    entry_upper_shadow = sample_feature_value(sample, "entry_upper_shadow")
    prev_divergence = sample_feature_value(sample, "prev_bsp_divergence_rate")

    if rule_name == "entry_upper_shadow_le_0_3":
        return entry_upper_shadow <= 0.3
    if rule_name == "entry_and_child_close_pos":
        return entry_close_pos >= 0.5 and child_close_pos >= 0.4
    if rule_name == "entry_child_close_pos_upper_shadow":
        return entry_close_pos >= 0.5 and child_close_pos >= 0.4 and entry_upper_shadow <= 0.3
    if rule_name == "entry_child_close_pos_upper_shadow_divergence":
        return (
            entry_close_pos >= 0.5
            and child_close_pos >= 0.4
            and entry_upper_shadow <= 0.3
            and prev_divergence <= 1.0
        )
    raise ValueError(f"未知后处理过滤规则：{rule_name}")


def metric_delta(baseline: Dict, filtered: Dict) -> Dict:
    return {
        "sample_keep_rate": safe_div(float(filtered["sample_count"]), float(baseline["sample_count"])) if baseline["sample_count"] else None,
        "hit_rate_delta": filtered["hit_rate"] - baseline["hit_rate"] if filtered["hit_rate"] is not None else None,
        "stop_loss_rate_delta": (
            filtered["exit_reason_rates"]["stop_loss"] - baseline["exit_reason_rates"]["stop_loss"]
            if filtered["sample_count"] else None
        ),
        "avg_realized_return_after_cost_delta": (
            filtered["avg_realized_return_after_cost"] - baseline["avg_realized_return_after_cost"]
            if filtered["avg_realized_return_after_cost"] is not None else None
        ),
        "avg_max_drawdown_delta": (
            filtered["avg_max_drawdown"] - baseline["avg_max_drawdown"]
            if filtered["avg_max_drawdown"] is not None else None
        ),
    }


def summarize_post_filter_metrics(
    test_prob,
    test_samples: List[SignalSample],
    score_thresholds: List[float],
    trade_cost: float,
    buckets: Tuple[float, ...] = (0.05, 0.10, 0.20, 0.30),
) -> Dict:
    scored_samples = sorted(
        [(float(score), sample) for score, sample in zip(test_prob, test_samples)],
        key=lambda item: item[0],
        reverse=True,
    )

    rows = {
        "rules": list(POST_FILTER_RULES),
        "score_buckets": [],
        "score_thresholds": [],
    }

    for bucket in buckets:
        top_n = max(1, int(len(scored_samples) * bucket))
        group = scored_samples[:top_n]
        baseline = summarize_scored_group([score for score, _ in group], [sample for _, sample in group], trade_cost)
        bucket_row = {
            "top_pct": bucket,
            "baseline": baseline,
            "filters": [],
        }
        for rule in POST_FILTER_RULES:
            filtered_group = [(score, sample) for score, sample in group if pass_post_filter(sample, rule["name"])]
            filtered = summarize_scored_group(
                [score for score, _ in filtered_group],
                [sample for _, sample in filtered_group],
                trade_cost,
            )
            bucket_row["filters"].append({
                "rule": rule["name"],
                "description": rule["description"],
                "filtered": filtered,
                "delta": metric_delta(baseline, filtered),
            })
        rows["score_buckets"].append(bucket_row)

    for threshold in score_thresholds:
        group = [(score, sample) for score, sample in scored_samples if score >= threshold]
        baseline = summarize_scored_group([score for score, _ in group], [sample for _, sample in group], trade_cost)
        threshold_row = {
            "threshold": threshold,
            "baseline": baseline,
            "filters": [],
        }
        for rule in POST_FILTER_RULES:
            filtered_group = [(score, sample) for score, sample in group if pass_post_filter(sample, rule["name"])]
            filtered = summarize_scored_group(
                [score for score, _ in filtered_group],
                [sample for _, sample in filtered_group],
                trade_cost,
            )
            threshold_row["filters"].append({
                "rule": rule["name"],
                "description": rule["description"],
                "filtered": filtered,
                "delta": metric_delta(baseline, filtered),
            })
        rows["score_thresholds"].append(threshold_row)

    return rows


def summarize_time_period_metrics(
    test_prob,
    test_samples: List[SignalSample],
    buckets: Tuple[float, ...] = (0.05, 0.10, 0.20),
    trade_cost: float = 0.0,
) -> List[Dict]:
    period_items: Dict[str, List[Tuple[float, SignalSample]]] = {}
    for score, sample in zip(test_prob, test_samples):
        period = sample.open_time[:7]
        period_items.setdefault(period, []).append((float(score), sample))

    period_rows = []
    for period in sorted(period_items):
        items = period_items[period]
        period_scores = [score for score, _ in items]
        period_samples = [sample for _, sample in items]
        y_true = [int(sample.label) for sample in period_samples]
        has_two_classes = len(set(y_true)) == 2
        score_buckets = summarize_score_buckets(period_scores, period_samples, buckets, trade_cost)
        bucket_by_pct = {row["top_pct"]: row for row in score_buckets}

        period_rows.append({
            "period": period,
            "sample_count": len(period_samples),
            "positive_rate": sum(y_true) / len(y_true),
            "auc": metric_or_none(roc_auc_score, y_true, period_scores) if has_two_classes else None,
            "average_precision": metric_or_none(average_precision_score, y_true, period_scores) if has_two_classes else None,
            "avg_score": sum(period_scores) / len(period_scores),
            "avg_realized_return": avg_optional(sample.realized_return for sample in period_samples),
            "avg_realized_return_after_cost": avg_optional(realized_return_after_cost(sample, trade_cost) for sample in period_samples),
            "avg_forward_return": avg_optional(sample.forward_return for sample in period_samples),
            "top5pct_hit_rate": bucket_by_pct[0.05]["hit_rate"],
            "top5pct_avg_realized_return": bucket_by_pct[0.05]["avg_realized_return"],
            "top10pct_hit_rate": bucket_by_pct[0.10]["hit_rate"],
            "top10pct_avg_realized_return": bucket_by_pct[0.10]["avg_realized_return"],
            "top20pct_hit_rate": bucket_by_pct[0.20]["hit_rate"],
            "top20pct_avg_realized_return": bucket_by_pct[0.20]["avg_realized_return"],
            "score_buckets": score_buckets,
        })
    return period_rows


def weighted_avg(rows: List[Dict], value_key: str, weight_key: str = "sample_count") -> Optional[float]:
    value_weight_pairs = [
        (float(row[value_key]), float(row[weight_key]))
        for row in rows
        if row.get(value_key) is not None and row.get(weight_key)
    ]
    total_weight = sum(weight for _, weight in value_weight_pairs)
    if not total_weight:
        return None
    return sum(value * weight for value, weight in value_weight_pairs) / total_weight


def simple_avg(rows: List[Dict], value_key: str) -> Optional[float]:
    values = [float(row[value_key]) for row in rows if row.get(value_key) is not None]
    if not values:
        return None
    return sum(values) / len(values)


def summarize_walk_forward_top_buckets(
    walk_forward_rows: List[Dict],
    buckets: Tuple[float, ...] = (0.05, 0.10, 0.20),
) -> Dict:
    rows = []
    target_buckets = set(buckets)
    for window in walk_forward_rows:
        if window.get("status") != "ok":
            continue
        for bucket in window.get("score_buckets", []):
            top_pct = bucket["top_pct"]
            if top_pct not in target_buckets:
                continue
            exit_rates = bucket["exit_reason_rates"]
            rows.append({
                "test_period": window["test_period"],
                "test_start_time": window.get("test_start_time"),
                "test_end_time_exclusive": window.get("test_end_time_exclusive"),
                "test_time_range": window.get("test_time_range"),
                "train_samples": window["train_samples"],
                "test_samples": window["test_samples"],
                "top_pct": top_pct,
                "selected_samples": bucket["sample_count"],
                "min_score": bucket["min_score"],
                "avg_score": bucket["avg_score"],
                "hit_rate": bucket["hit_rate"],
                "avg_realized_return_after_cost": bucket["avg_realized_return_after_cost"],
                "avg_forward_return": bucket["avg_forward_return"],
                "avg_max_drawdown": bucket["avg_max_drawdown"],
                "take_profit_rate": exit_rates["take_profit"],
                "stop_loss_rate": exit_rates["stop_loss"],
                "timeout_rate": exit_rates["timeout"],
            })

    aggregate_rows = []
    for bucket in buckets:
        bucket_rows = [row for row in rows if row["top_pct"] == bucket]
        aggregate_rows.append({
            "top_pct": bucket,
            "window_count": len(bucket_rows),
            "total_selected_samples": sum(row["selected_samples"] for row in bucket_rows),
            "weighted_hit_rate": weighted_avg(bucket_rows, "hit_rate", "selected_samples"),
            "mean_hit_rate": simple_avg(bucket_rows, "hit_rate"),
            "weighted_avg_realized_return_after_cost": weighted_avg(
                bucket_rows,
                "avg_realized_return_after_cost",
                "selected_samples",
            ),
            "mean_avg_realized_return_after_cost": simple_avg(bucket_rows, "avg_realized_return_after_cost"),
            "weighted_stop_loss_rate": weighted_avg(bucket_rows, "stop_loss_rate", "selected_samples"),
            "mean_stop_loss_rate": simple_avg(bucket_rows, "stop_loss_rate"),
            "weighted_take_profit_rate": weighted_avg(bucket_rows, "take_profit_rate", "selected_samples"),
            "mean_take_profit_rate": simple_avg(bucket_rows, "take_profit_rate"),
            "weighted_timeout_rate": weighted_avg(bucket_rows, "timeout_rate", "selected_samples"),
            "mean_timeout_rate": simple_avg(bucket_rows, "timeout_rate"),
        })

    return {
        "rows": rows,
        "aggregate": aggregate_rows,
    }


def run_walk_forward_validation(
    samples: List[SignalSample],
    test_periods: List[str],
    random_state: int,
    min_train_samples: int,
    min_test_samples: int,
    trade_cost: float,
    score_thresholds: List[float],
    min_test_time: Optional[str] = None,
) -> List[Dict]:
    sorted_samples = sorted(samples, key=lambda sample: (sample.open_time, sample.code, sample.open_klu_idx))
    rows = []
    for period in sorted(dict.fromkeys(test_periods)):
        period = normalize_period(period)
        test_start_time = walk_forward_period_start(period, min_test_time)
        test_end_time = period_end_time_exclusive(period)
        train_samples = [sample for sample in sorted_samples if sample.open_time < test_start_time]
        test_samples = [
            sample
            for sample in sorted_samples
            if test_start_time <= sample.open_time < test_end_time
        ]
        row = {
            "mode": "expanding_window",
            "test_period": period,
            "test_start_time": test_start_time,
            "test_end_time_exclusive": test_end_time,
            "train_period": f"{train_samples[0].open_time} ~ {train_samples[-1].open_time}" if train_samples else "",
            "test_time_range": f"{test_samples[0].open_time} ~ {test_samples[-1].open_time}" if test_samples else "",
            "train_samples": len(train_samples),
            "test_samples": len(test_samples),
            "train_code_count": len({sample.code for sample in train_samples}),
            "test_code_count": len({sample.code for sample in test_samples}),
        }

        if len(train_samples) < min_train_samples:
            row["status"] = "skipped"
            row["skip_reason"] = f"训练样本不足：{len(train_samples)} < {min_train_samples}"
            rows.append(row)
            continue
        if len(test_samples) < min_test_samples:
            row["status"] = "skipped"
            row["skip_reason"] = f"测试样本不足：{len(test_samples)} < {min_test_samples}"
            rows.append(row)
            continue
        train_classes = {sample.label for sample in train_samples}
        test_classes = {sample.label for sample in test_samples}
        if len(train_classes) < 2:
            row["status"] = "skipped"
            row["skip_reason"] = f"训练集只有一个类别：{sorted(train_classes)}"
            rows.append(row)
            continue
        if len(test_classes) < 2:
            row["status"] = "skipped"
            row["skip_reason"] = f"测试集只有一个类别：{sorted(test_classes)}"
            rows.append(row)
            continue

        feature_meta = build_feature_meta(train_samples)
        _, window_metrics, _ = train_model(
            train_samples,
            test_samples,
            feature_meta,
            random_state,
            trade_cost,
            score_thresholds,
        )
        window_metrics.pop("time_period_metrics", None)
        row.update(window_metrics)
        row["status"] = "ok"
        row["feature_count"] = len(feature_meta)
        rows.append(row)
    return rows


def train_model(
    train_samples: List[SignalSample],
    test_samples: List[SignalSample],
    feature_meta: Dict[str, int],
    random_state: int,
    trade_cost: float,
    score_thresholds: List[float],
):
    x_train = build_matrix(train_samples, feature_meta)
    y_train = [int(sample.label) for sample in train_samples]
    x_test = build_matrix(test_samples, feature_meta)
    y_test = [int(sample.label) for sample in test_samples]

    model = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("clf", RandomForestClassifier(
            n_estimators=MODEL_PARAMS["n_estimators"],
            max_depth=MODEL_PARAMS["max_depth"],
            min_samples_leaf=MODEL_PARAMS["min_samples_leaf"],
            class_weight=MODEL_PARAMS["class_weight"],
            random_state=random_state,
        )),
    ])
    model.fit(x_train, y_train)

    test_prob = model.predict_proba(x_test)[:, 1]
    test_pred = [int(prob >= 0.5) for prob in test_prob]
    train_positive_rate = sum(y_train) / len(y_train)
    test_positive_rate = sum(y_test) / len(y_test)

    score_buckets = summarize_score_buckets(test_prob, test_samples, trade_cost=trade_cost)
    top20_bucket = next(row for row in score_buckets if row["top_pct"] == 0.20)

    metrics = {
        "train_samples": len(train_samples),
        "test_samples": len(test_samples),
        "feature_count": len(feature_meta),
        "train_positive_rate": train_positive_rate,
        "test_positive_rate": test_positive_rate,
        "test_auc": metric_or_none(roc_auc_score, y_test, test_prob),
        "test_average_precision": metric_or_none(average_precision_score, y_test, test_prob),
        "test_accuracy_at_0_5": float(accuracy_score(y_test, test_pred)),
        "test_precision_at_0_5": float(precision_score(y_test, test_pred, zero_division=0)),
        "test_recall_at_0_5": float(recall_score(y_test, test_pred, zero_division=0)),
        "test_avg_realized_return": avg_optional(sample.realized_return for sample in test_samples),
        "test_avg_realized_return_after_cost": avg_optional(realized_return_after_cost(sample, trade_cost) for sample in test_samples),
        "test_avg_forward_return": avg_optional(sample.forward_return for sample in test_samples),
        "test_top20pct_hit_rate": top20_bucket["hit_rate"],
        "test_top20pct_avg_realized_return": top20_bucket["avg_realized_return"],
        "test_top20pct_avg_realized_return_after_cost": top20_bucket["avg_realized_return_after_cost"],
        "test_exit_reason_summary": exit_reason_summary(test_samples),
        "score_buckets": score_buckets,
        "score_thresholds": summarize_score_thresholds(test_prob, test_samples, score_thresholds, trade_cost),
        "post_filter_metrics": summarize_post_filter_metrics(test_prob, test_samples, score_thresholds, trade_cost),
        "time_period_metrics": summarize_time_period_metrics(test_prob, test_samples, trade_cost=trade_cost),
    }
    return model, metrics, test_prob


def write_libsvm(path: Path, samples: List[SignalSample], feature_meta: Dict[str, int]) -> None:
    with path.open("w", encoding="utf-8") as fid:
        for sample in samples:
            features = []
            for name, value in sample.feature.items():
                if name in feature_meta:
                    features.append((feature_meta[name], value))
            features.sort(key=lambda item: item[0])
            feature_str = " ".join(f"{idx}:{value}" for idx, value in features)
            fid.write(f"{sample.label} {feature_str}\n")


def write_samples_csv(path: Path, samples: List[SignalSample], score_by_key: Optional[Dict[Tuple[str, int], float]] = None) -> None:
    score_by_key = score_by_key or {}
    with path.open("w", newline="", encoding="utf-8") as fid:
        writer = csv.DictWriter(
            fid,
            fieldnames=[
                "open_time",
                "code",
                "open_klu_idx",
                "bsp_klu_idx",
                "entry_price",
                "label",
                "score",
                "realized_return",
                "forward_return",
                "max_gain",
                "max_drawdown",
                "exit_reason",
            ],
        )
        writer.writeheader()
        for sample in samples:
            writer.writerow({
                "open_time": sample.open_time,
                "code": sample.code,
                "open_klu_idx": sample.open_klu_idx,
                "bsp_klu_idx": sample.bsp_klu_idx,
                "entry_price": sample.entry_price,
                "label": sample.label,
                "score": score_by_key.get((sample.code, sample.open_klu_idx)),
                "realized_return": sample.realized_return,
                "forward_return": sample.forward_return,
                "max_gain": sample.max_gain,
                "max_drawdown": sample.max_drawdown,
                "exit_reason": sample.exit_reason,
            })


def get_feature_importance(model, feature_meta: Dict[str, int]) -> List[Dict[str, float]]:
    clf = model.named_steps["clf"]
    idx_to_name = {idx: name for name, idx in feature_meta.items()}
    rows = [
        {
            "feature": idx_to_name[idx],
            "importance": float(importance),
        }
        for idx, importance in enumerate(clf.feature_importances_)
    ]
    rows.sort(key=lambda row: row["importance"], reverse=True)
    return rows


def write_feature_importance(path: Path, importance_rows: List[Dict[str, float]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fid:
        writer = csv.DictWriter(fid, fieldnames=["feature", "importance"])
        writer.writeheader()
        writer.writerows(importance_rows)


def write_walk_forward_top_buckets(path: Path, summary: Dict) -> None:
    rows = summary.get("rows", [])
    fieldnames = [
        "test_period",
        "test_start_time",
        "test_end_time_exclusive",
        "test_time_range",
        "train_samples",
        "test_samples",
        "top_pct",
        "selected_samples",
        "min_score",
        "avg_score",
        "hit_rate",
        "avg_realized_return_after_cost",
        "avg_forward_return",
        "avg_max_drawdown",
        "take_profit_rate",
        "stop_loss_rate",
        "timeout_rate",
    ]
    with path.open("w", newline="", encoding="utf-8") as fid:
        writer = csv.DictWriter(fid, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def codes_digest(codes: List[str]) -> str:
    joined_codes = "\n".join(sorted(codes))
    return hashlib.sha256(joined_codes.encode("utf-8")).hexdigest()


def build_run_config(args, codes: List[str], split_info: Dict[str, str]) -> Dict:
    model_params = dict(MODEL_PARAMS)
    model_params["random_state"] = args.random_state
    return {
        "begin_time": args.begin_time,
        "end_time": args.end_time,
        "horizon": args.horizon,
        "take_profit": args.take_profit,
        "stop_loss": args.stop_loss,
        "target_bsp_types": sorted(TARGET_BSP_TYPES),
        "main_bs_type": "1,1p",
        "parent_bs_type": "1,2,3a,1p,2s,3b",
        "data_src": DATA_SRC.CACHE_DB.name,
        "model_kl_type": DB_KL_TYPE,
        "parent_kl_type": PARENT_DB_KL_TYPE,
        "child_kl_type": CHILD_DB_KL_TYPE,
        "split_mode": split_info["mode"],
        "split_time": split_info["split_time"],
        "train_ratio": args.train_ratio,
        "trade_cost": args.trade_cost,
        "score_thresholds": parse_float_list(args.score_thresholds),
        "post_filter_rules": list(POST_FILTER_RULES),
        "walk_forward": bool(args.walk_forward),
        "walk_forward_test_periods": parse_period_list(args.walk_forward_test_periods),
        "walk_forward_min_test_time": split_info["split_time"],
        "walk_forward_min_train_samples": args.walk_forward_min_train_samples,
        "walk_forward_min_test_samples": args.walk_forward_min_test_samples,
        "all_codes": bool(args.all),
        "requested_code": args.code,
        "requested_codes": args.codes,
        "code_count": len(codes),
        "codes_sha256": codes_digest(codes),
        "model": model_params,
    }


def ensure_two_classes(samples: List[SignalSample], name: str) -> None:
    classes = {sample.label for sample in samples}
    if len(classes) < 2:
        raise ValueError(f"{name} 只有一个类别，无法训练/评估二分类模型：{classes}")


def parse_args():
    parser = argparse.ArgumentParser(description="训练一个按未来收益打标签的30M买点质量模型。")
    parser.add_argument("--code", default="sz.000001")
    parser.add_argument("--codes", default=None, help="逗号分隔的股票列表；传入后会覆盖 --code。")
    parser.add_argument("--all", action="store_true", help="从缓存数据库读取所有有30M数据的股票。")
    parser.add_argument("--split-time", default=None, help="测试集起始时间，例如 2026-03-01 或 2026/03/01 10:00。")
    parser.add_argument("--begin-time", default="2015-01-01")
    parser.add_argument("--end-time", default=None)
    parser.add_argument("--horizon", type=int, default=20, help="向后观察多少根30M K线。")
    parser.add_argument("--take-profit", type=float, default=0.05, help="先触发该收益则标签为1。")
    parser.add_argument("--stop-loss", type=float, default=0.03, help="先触发该回撤则标签为0。")
    parser.add_argument("--train-ratio", type=float, default=0.7, help="未指定 --split-time 时，按时间排序后的训练样本占比。")
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--trade-cost", type=float, default=0.001, help="单笔交易买卖合计成本；仅用于评估扣成本后收益，默认0.001。")
    parser.add_argument("--score-thresholds", default="0.55,0.60,0.65", help="固定分数阈值评估，逗号分隔。")
    parser.add_argument("--walk-forward", action=argparse.BooleanOptionalAction, default=True, help="是否输出按月份滚动训练验证结果。")
    parser.add_argument("--walk-forward-test-periods", default=None, help="逗号分隔的 walk-forward 测试月份，例如 2026/03,2026/04；默认使用主测试集覆盖的月份。")
    parser.add_argument("--walk-forward-min-train-samples", type=int, default=100, help="walk-forward 单个窗口最少训练样本数。")
    parser.add_argument("--walk-forward-min-test-samples", type=int, default=50, help="walk-forward 单个窗口最少测试样本数。")
    parser.add_argument("--output-dir", default="Debug/model_output/strategy_demo7")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    output_dir = Path(args.output_dir)

    if args.all:
        codes = get_stock_list_from_cache(DB_KL_TYPE)
        if not codes:
            raise ValueError("缓存数据库中没有找到30M股票数据。")
        print(f"从缓存数据库读取股票数量: {len(codes)}")
    else:
        codes = parse_code_list(args.codes or args.code)
    samples: List[SignalSample] = []
    for code in codes:
        try:
            parent_dates, parent_context_by_date = build_parent_level_context(code, args.begin_time, args.end_time)
            chan = build_chan(code, args.begin_time, args.end_time)
            code_samples, final_klus = collect_buy_signals(chan, code, parent_dates, parent_context_by_date)
            labeled_code_samples = label_samples(code_samples, final_klus, args.horizon, args.take_profit, args.stop_loss)
            samples.extend(labeled_code_samples)
            print(f"{code}: 有效样本 {len(labeled_code_samples)}")
        except Exception as err:
            print(f"{code}: 加载或样本生成失败，已跳过：{err}")

    if not samples:
        raise ValueError("没有生成任何有效样本，请检查数据源连接、股票代码或时间范围。")
    if len(samples) < 20:
        raise ValueError(f"有效样本太少：{len(samples)}，请扩大时间范围或降低标签条件。")

    train_samples, test_samples, split_info = split_by_time(
        samples,
        args.train_ratio,
        args.split_time,
    )
    ensure_two_classes(train_samples, "训练集")
    ensure_two_classes(test_samples, "测试集")

    feature_meta = build_feature_meta(train_samples)
    score_thresholds = parse_float_list(args.score_thresholds)
    model, metrics, test_prob = train_model(
        train_samples,
        test_samples,
        feature_meta,
        args.random_state,
        args.trade_cost,
        score_thresholds,
    )
    metrics["kl_type"] = DB_KL_TYPE
    metrics["parent_kl_type"] = PARENT_DB_KL_TYPE
    metrics["child_kl_type"] = CHILD_DB_KL_TYPE
    metrics["split_mode"] = split_info["mode"]
    metrics["split_time"] = split_info["split_time"]
    metrics["train_period"] = split_info["train_period"]
    metrics["test_period"] = split_info["test_period"]
    metrics["train_code_count"] = len({sample.code for sample in train_samples})
    metrics["test_code_count"] = len({sample.code for sample in test_samples})
    metrics["run_config"] = build_run_config(args, codes, split_info)
    if args.walk_forward:
        walk_forward_test_periods = parse_period_list(args.walk_forward_test_periods)
        if walk_forward_test_periods is None:
            walk_forward_test_periods = sorted({sample_period(sample) for sample in test_samples})
        metrics["walk_forward_metrics"] = run_walk_forward_validation(
            samples,
            walk_forward_test_periods,
            args.random_state,
            args.walk_forward_min_train_samples,
            args.walk_forward_min_test_samples,
            args.trade_cost,
            score_thresholds,
            split_info["split_time"],
        )
        metrics["walk_forward_top_bucket_summary"] = summarize_walk_forward_top_buckets(metrics["walk_forward_metrics"])
    feature_importance = get_feature_importance(model, feature_meta)

    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "model.pkl").open("wb") as fid:
        pickle.dump(model, fid)
    with (output_dir / "feature.meta.json").open("w", encoding="utf-8") as fid:
        json.dump(feature_meta, fid, ensure_ascii=False, indent=2)
    with (output_dir / "metrics.json").open("w", encoding="utf-8") as fid:
        json.dump(metrics, fid, ensure_ascii=False, indent=2)
    with (output_dir / "feature_importance.json").open("w", encoding="utf-8") as fid:
        json.dump(feature_importance, fid, ensure_ascii=False, indent=2)

    score_by_key = {
        (sample.code, sample.open_klu_idx): float(score)
        for sample, score in zip(test_samples, test_prob)
    }
    write_samples_csv(output_dir / "samples.csv", samples, score_by_key)
    write_libsvm(output_dir / "samples.libsvm", samples, feature_meta)
    write_feature_importance(output_dir / "feature_importance.csv", feature_importance)
    if "walk_forward_top_bucket_summary" in metrics:
        write_walk_forward_top_buckets(
            output_dir / "walk_forward_top_buckets.csv",
            metrics["walk_forward_top_bucket_summary"],
        )

    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"模型文件: {output_dir / 'model.pkl'}")
    print(f"特征映射: {output_dir / 'feature.meta.json'}")
    print(f"特征重要性: {output_dir / 'feature_importance.csv'}")
    print(f"样本明细: {output_dir / 'samples.csv'}")
