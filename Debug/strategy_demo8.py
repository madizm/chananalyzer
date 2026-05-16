import argparse
import csv
import json
import math
import os
import pickle
import sys
from bisect import bisect_left
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
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

from Common.CEnum import DATA_FIELD, MACD_ALGO
from Debug.strategy_demo7 import (
    CHILD_LV_IDX,
    DB_KL_TYPE,
    MODEL_LV_IDX,
    MODEL_PARAMS,
    PARENT_BSP_TYPES,
    PARENT_DB_KL_TYPE,
    CHILD_DB_KL_TYPE,
    TARGET_BSP_TYPES,
    SignalSample,
    avg_optional,
    bi_bar_feature,
    build_chan,
    build_feature_meta,
    build_matrix,
    build_parent_level_context,
    child_level_feature,
    codes_digest,
    ctime_to_date_str,
    ctime_to_str,
    get_feature_importance,
    get_stock_list_from_cache,
    mean,
    metric_or_none,
    moving_average_dist,
    normalize_period,
    normalize_split_time,
    parent_level_feature,
    parse_code_list,
    parse_period_list,
    period_end_time_exclusive,
    recent_return,
    ratio_to_recent_avg,
    safe_div,
    sample_period,
    split_by_time,
    trade_metric,
    volatility,
    walk_forward_period_start,
    write_feature_importance,
    write_libsvm,
)
from Debug.bsp_point_in_time_label import collect_bsp_stability_samples_for_code, collect_point_in_time_samples_for_code


DIVERGENCE_RATE_CAP = 20.0


def normalize_candidate_divergence_rate(value: float, cap: float = DIVERGENCE_RATE_CAP) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(number):
        return 0.0
    if math.isinf(number):
        number = cap if number > 0 else 0.0
    return math.log1p(min(max(number, 0.0), cap))


def signal_side_is_buy(signal_side: str) -> bool:
    return signal_side == "buy"


def signal_side_bi_name(target_is_buy: bool) -> str:
    return "下笔" if target_is_buy else "上笔"


def signal_side_point_name(target_is_buy: bool) -> str:
    return "买点" if target_is_buy else "卖点"


def label_target_name(target_is_buy: bool) -> str:
    return "confirmed_bi_is_target_buy_point" if target_is_buy else "confirmed_bi_is_target_sell_point"


def label_definition_text(target_is_buy: bool, label_mode: str = "point_in_time", label_task: str = "recognition") -> str:
    bi_name = signal_side_bi_name(target_is_buy)
    point_name = signal_side_point_name(target_is_buy)
    if label_task == "stability":
        return f"1 表示 decision_time 当时已出现的一类{point_name}(1/1p)在稳定性观察窗口结束时仍保留，0 表示窗口内消失、迁移或类型不再匹配。"
    if label_mode == "point_in_time":
        return f"1 表示确认{bi_name}在 decision_time 当时可见结构中存在目标{point_name}(1/1p)，0 表示当时可见结构中不是目标{point_name}。"
    return f"1 表示确认{bi_name}最终存在目标{point_name}(1/1p)，0 表示确认{bi_name}不是目标{point_name}。"


def bi_matches_signal_side(bi, target_is_buy: bool) -> bool:
    return bi.is_down() if target_is_buy else bi.is_up()


def target_bsp_type_hit(bsp, target_is_buy: bool) -> bool:
    if bsp is None or bool(bsp.is_buy) != target_is_buy:
        return False
    bsp_types = {bsp_type.strip() for bsp_type in str(bsp.type2str()).split(",") if bsp_type.strip()}
    return bool(bsp_types & TARGET_BSP_TYPES)


def previous_bsp_context_feature(entry_klu, current_bi, previous_bsp, target_is_buy: bool) -> Dict[str, float]:
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
    feature.update({
        "prev_bsp_exists": 1.0,
        "prev_bsp_is_buy": float(bool(previous_bsp.is_buy)),
        "prev_bsp_same_direction": float(bool(previous_bsp.is_buy) == target_is_buy),
        "prev_bsp_bi_gap": float(current_bi.idx - previous_bsp.bi.idx),
        "prev_bsp_klu_gap": float(entry_klu.idx - previous_bsp.klu.idx),
        "prev_bsp_price_change": safe_div(float(entry_klu.close) - prev_price, prev_price),
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


def candidate_divergence_feature(bi) -> Dict[str, float]:
    feature = {
        "candidate_divergence_exists": 0.0,
        "candidate_divergence_rate": 0.0,
        "candidate_in_metric_peak": 0.0,
        "candidate_out_metric_peak": 0.0,
        "candidate_break_prev_extreme": 0.0,
        "candidate_prev_same_dir_amp": 0.0,
    }
    if bi.idx < 2 or bi.pre is None or bi.pre.pre is None:
        return feature

    pre_same_dir_bi = bi.pre.pre
    if pre_same_dir_bi.is_down() != bi.is_down():
        return feature

    try:
        in_metric = float(pre_same_dir_bi.cal_macd_metric(MACD_ALGO.PEAK, is_reverse=False))
        out_metric = float(bi.cal_macd_metric(MACD_ALGO.PEAK, is_reverse=True))
    except Exception:
        return feature

    feature.update({
        "candidate_divergence_exists": 1.0,
        "candidate_divergence_rate": normalize_candidate_divergence_rate(safe_div(out_metric, in_metric + 1e-7)),
        "candidate_in_metric_peak": in_metric,
        "candidate_out_metric_peak": out_metric,
        "candidate_break_prev_extreme": float(bool(bi._low() <= pre_same_dir_bi._low())) if bi.is_down() else float(bool(bi._high() >= pre_same_dir_bi._high())),
        "candidate_prev_same_dir_amp": float(pre_same_dir_bi.amp()),
    })
    return feature


def confirmed_bi_feature(
    klus: List,
    pos: int,
    bi,
    target_is_buy: bool,
    previous_bsp=None,
    parent_context=None,
    child_level_chan=None,
) -> Dict[str, float]:
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
        "bi_amp": float(bi.amp()),
        "bi_is_sure": float(bool(bi.is_sure)),
        "bi_idx": float(bi.idx),
    }

    feature.update(previous_bsp_context_feature(klu, bi, previous_bsp, target_is_buy))
    feature.update(candidate_divergence_feature(bi))
    feature.update(bi_bar_feature(klus, bi))
    feature.update(parent_level_feature(klu, parent_context))
    if child_level_chan is not None:
        feature.update(child_level_feature(klu, klu.klc, child_level_chan))
    return feature


def latest_previous_bsp(sorted_bsp_list: List, bi_idx: int):
    previous_bsp = None
    for bsp in sorted_bsp_list:
        if bsp.bi.idx >= bi_idx:
            break
        previous_bsp = bsp
    return previous_bsp


def point_in_time_feature_builder(
    final_klus: List,
    pos: int,
    bi,
    target_is_buy: bool,
    sorted_bsp_list: List,
    parent_context=None,
    child_level_chan=None,
) -> Dict[str, float]:
    return confirmed_bi_feature(
        final_klus,
        pos,
        bi,
        target_is_buy,
        latest_previous_bsp(sorted_bsp_list, bi.idx),
        parent_context,
        child_level_chan,
    )


def collect_confirmed_bi_samples_for_code(
    code: str,
    begin_time: str,
    end_time: Optional[str],
    target_is_buy: bool,
    label_mode: str = "point_in_time",
    decision_delay_bars: int = 0,
    label_task: str = "recognition",
    stability_bars: int = 16,
    stability_bis: int = 0,
    stability_days: int = 0,
    stability_window_mode: str = "any",
) -> Tuple[str, List[SignalSample]]:
    if label_task == "stability":
        if label_mode != "point_in_time":
            raise ValueError("稳定性模型只支持 --label-mode point_in_time")
        return collect_bsp_stability_samples_for_code(
            code=code,
            begin_time=begin_time,
            end_time=end_time,
            target_is_buy=target_is_buy,
            target_bsp_types=set(TARGET_BSP_TYPES),
            dependency_bsp_types=set(),
            build_chan_fn=build_chan,
            feature_builder=point_in_time_feature_builder,
            decision_delay_bars=decision_delay_bars,
            stability_bars=stability_bars,
            stability_bis=stability_bis,
            stability_days=stability_days,
            stability_window_mode=stability_window_mode,
        )
    if label_task != "recognition":
        raise ValueError(f"不支持的 label_task: {label_task}")
    if label_mode == "point_in_time":
        point_name = "buy_point" if target_is_buy else "sell_point"
        return collect_point_in_time_samples_for_code(
            code=code,
            begin_time=begin_time,
            end_time=end_time,
            target_is_buy=target_is_buy,
            target_bsp_types=set(TARGET_BSP_TYPES),
            build_chan_fn=build_chan,
            feature_builder=point_in_time_feature_builder,
            exit_reason_positive=f"correct_{point_name}",
            exit_reason_negative=f"not_{point_name}",
            decision_delay_bars=decision_delay_bars,
        )
    if label_mode != "final":
        raise ValueError(f"不支持的 label_mode: {label_mode}")

    parent_dates, parent_context_by_date = build_parent_level_context(code, begin_time, end_time)
    chan = build_chan(code, begin_time, end_time)
    for _ in chan.step_load():
        pass

    level_chan = chan[MODEL_LV_IDX]
    child_level_chan = chan[CHILD_LV_IDX]
    final_klus = list(level_chan.klu_iter())
    pos_by_idx = {int(klu.idx): pos for pos, klu in enumerate(final_klus)}
    sorted_bsp_list = level_chan.bs_point_lst.getSortedBspList()
    target_bsp_by_bi_idx = {
        int(bsp.bi.idx): bsp
        for bsp in sorted_bsp_list
        if target_bsp_type_hit(bsp, target_is_buy) and bool(bsp.bi.is_sure)
    }

    samples: List[SignalSample] = []
    for bi in level_chan.bi_list:
        if not bi.is_sure:
            continue
        if not bi_matches_signal_side(bi, target_is_buy):
            continue

        entry_klu = bi.get_end_klu()
        pos = pos_by_idx.get(int(entry_klu.idx))
        if pos is None:
            continue
        bsp = target_bsp_by_bi_idx.get(int(bi.idx))
        previous_bsp = latest_previous_bsp(sorted_bsp_list, bi.idx)
        entry_date = ctime_to_date_str(entry_klu.time)
        parent_pos = bisect_left(parent_dates, entry_date) - 1
        parent_context = parent_context_by_date[parent_dates[parent_pos]] if parent_pos >= 0 else None

        sample = SignalSample(
            code=code,
            bsp_klu_idx=int(bsp.klu.idx) if bsp is not None else int(entry_klu.idx),
            open_klu_idx=int(entry_klu.idx),
            open_time=ctime_to_str(entry_klu.time),
            entry_price=float(entry_klu.close),
            feature=confirmed_bi_feature(
                final_klus,
                pos,
                bi,
                target_is_buy,
                previous_bsp,
                parent_context,
                child_level_chan,
            ),
            label=1 if bsp is not None else 0,
            signal_time=ctime_to_str(entry_klu.time),
            decision_time=ctime_to_str(entry_klu.time),
            bi_begin_time=ctime_to_str(bi.get_begin_klu().time),
            bi_end_time=ctime_to_str(entry_klu.time),
            bi_direction="down" if bi.is_down() else "up",
            label_mode="final",
            label_source="final_structure",
        )
        point_name = "buy_point" if target_is_buy else "sell_point"
        sample.exit_reason = f"correct_{point_name}" if sample.label == 1 else f"not_{point_name}"
        samples.append(sample)

    return code, samples


def resolve_signal_workers(requested_workers: int, code_count: int) -> int:
    if requested_workers < 0:
        raise ValueError("--signal-workers 不能小于 0。")
    if code_count <= 1:
        return 1
    if requested_workers > 0:
        return min(requested_workers, code_count)
    cpu_count = os.cpu_count() or 2
    return max(1, min(cpu_count - 1, code_count, 6))


def collect_confirmed_bi_samples(
    codes: List[str],
    begin_time: str,
    end_time: Optional[str],
    signal_workers: int,
    target_is_buy: bool,
    label_mode: str = "point_in_time",
    decision_delay_bars: int = 0,
    label_task: str = "recognition",
    stability_bars: int = 16,
    stability_bis: int = 0,
    stability_days: int = 0,
    stability_window_mode: str = "any",
) -> List[SignalSample]:
    worker_count = resolve_signal_workers(signal_workers, len(codes))
    samples_by_code: Dict[str, List[SignalSample]] = {}
    bi_name = signal_side_bi_name(target_is_buy)

    if worker_count == 1:
        for code in codes:
            try:
                _, code_samples = collect_confirmed_bi_samples_for_code(
                    code,
                    begin_time,
                    end_time,
                    target_is_buy,
                    label_mode,
                    decision_delay_bars,
                    label_task,
                    stability_bars,
                    stability_bis,
                    stability_days,
                    stability_window_mode,
                )
                samples_by_code[code] = code_samples
                print(f"{code}: 确认{bi_name}样本 {len(code_samples)}")
            except Exception as err:
                print(f"{code}: 加载或样本生成失败，已跳过：{err}")
    else:
        print(f"并行生成确认笔样本: workers={worker_count}, codes={len(codes)}")
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            future_to_code = {
                executor.submit(
                    collect_confirmed_bi_samples_for_code,
                    code,
                    begin_time,
                    end_time,
                    target_is_buy,
                    label_mode,
                    decision_delay_bars,
                    label_task,
                    stability_bars,
                    stability_bis,
                    stability_days,
                    stability_window_mode,
                ): code
                for code in codes
            }
            for future in as_completed(future_to_code):
                code = future_to_code[future]
                try:
                    _, code_samples = future.result()
                    samples_by_code[code] = code_samples
                    print(f"{code}: 确认{bi_name}样本 {len(code_samples)}")
                except Exception as err:
                    print(f"{code}: 加载或样本生成失败，已跳过：{err}")

    samples: List[SignalSample] = []
    for code in codes:
        samples.extend(samples_by_code.get(code, []))
    return samples


def correctness_summary(samples: List[SignalSample]) -> Dict:
    total = len(samples)
    correct_count = sum(int(sample.label) for sample in samples)
    return {
        "correct_bsp_count": correct_count,
        "not_bsp_count": total - correct_count,
        "correct_bsp_rate": safe_div(float(correct_count), float(total)),
    }


def stability_summary(samples: List[SignalSample]) -> Dict:
    def count_by_attr(attr_name: str) -> Dict[str, int]:
        result: Dict[str, int] = {}
        for sample in samples:
            value = getattr(sample, attr_name, None)
            key = str(value) if value not in {None, ""} else "stable"
            result[key] = result.get(key, 0) + 1
        return result

    stable_count = sum(1 for sample in samples if int(sample.label) == 1)
    unstable_count = len(samples) - stable_count
    return {
        "stability_sample_count": len(samples),
        "stable_count": stable_count,
        "unstable_count": unstable_count,
        "stable_rate": safe_div(float(stable_count), float(len(samples))),
        "unstable_reason_counts": count_by_attr("unstable_reason"),
        "match_level_counts": count_by_attr("match_level"),
        "window_close_reason_counts": count_by_attr("window_close_reason"),
    }


def summarize_scored_correctness(scores: List[float], samples: List[SignalSample]) -> Dict:
    sample_count = len(samples)
    if sample_count == 0:
        return {
            "sample_count": 0,
            "min_score": None,
            "avg_score": None,
            "hit_rate": None,
            **correctness_summary([]),
        }
    return {
        "sample_count": sample_count,
        "min_score": min(scores),
        "avg_score": sum(scores) / sample_count,
        "hit_rate": sum(int(sample.label) for sample in samples) / sample_count,
        **correctness_summary(samples),
    }


def summarize_score_buckets(test_prob, test_samples: List[SignalSample], buckets=(0.05, 0.10, 0.20, 0.30)) -> List[Dict]:
    ranked_samples = sorted(zip(test_prob, test_samples), key=lambda item: item[0], reverse=True)
    rows = []
    for bucket in buckets:
        top_n = max(1, int(len(ranked_samples) * bucket))
        top_items = ranked_samples[:top_n]
        rows.append({
            "top_pct": bucket,
            **summarize_scored_correctness(
                [float(score) for score, _ in top_items],
                [sample for _, sample in top_items],
            ),
        })
    return rows


def summarize_score_thresholds(test_prob, test_samples: List[SignalSample], thresholds: List[float]) -> List[Dict]:
    scored_samples = [(float(score), sample) for score, sample in zip(test_prob, test_samples)]
    rows = []
    for threshold in thresholds:
        items = [(score, sample) for score, sample in scored_samples if score >= threshold]
        rows.append({
            "threshold": threshold,
            **summarize_scored_correctness(
                [score for score, _ in items],
                [sample for _, sample in items],
            ),
        })
    return rows


def summarize_time_period_metrics(test_prob, test_samples: List[SignalSample]) -> List[Dict]:
    period_items: Dict[str, List[Tuple[float, SignalSample]]] = {}
    for score, sample in zip(test_prob, test_samples):
        period_items.setdefault(sample_period(sample), []).append((float(score), sample))

    rows = []
    for period in sorted(period_items):
        items = period_items[period]
        scores = [score for score, _ in items]
        samples = [sample for _, sample in items]
        y_true = [int(sample.label) for sample in samples]
        score_buckets = summarize_score_buckets(scores, samples, buckets=(0.05, 0.10, 0.20))
        rows.append({
            "period": period,
            "sample_count": len(samples),
            "positive_rate": sum(y_true) / len(y_true),
            "auc": metric_or_none(roc_auc_score, y_true, scores) if len(set(y_true)) == 2 else None,
            "average_precision": metric_or_none(average_precision_score, y_true, scores) if len(set(y_true)) == 2 else None,
            "score_buckets": score_buckets,
        })
    return rows


def train_correctness_model(
    train_samples: List[SignalSample],
    test_samples: List[SignalSample],
    feature_meta: Dict[str, int],
    random_state: int,
    score_thresholds: List[float],
    target_is_buy: bool,
    label_mode: str = "point_in_time",
    label_task: str = "recognition",
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
    score_buckets = summarize_score_buckets(test_prob, test_samples)
    top20_bucket = next(row for row in score_buckets if row["top_pct"] == 0.20)
    metrics = {
        "train_samples": len(train_samples),
        "test_samples": len(test_samples),
        "feature_count": len(feature_meta),
        "train_positive_rate": sum(y_train) / len(y_train),
        "test_positive_rate": sum(y_test) / len(y_test),
        "test_auc": metric_or_none(roc_auc_score, y_test, test_prob),
        "test_average_precision": metric_or_none(average_precision_score, y_test, test_prob),
        "test_accuracy_at_0_5": float(accuracy_score(y_test, test_pred)),
        "test_precision_at_0_5": float(precision_score(y_test, test_pred, zero_division=0)),
        "test_recall_at_0_5": float(recall_score(y_test, test_pred, zero_division=0)),
        "test_top20pct_hit_rate": top20_bucket["hit_rate"],
        "score_buckets": score_buckets,
        "score_thresholds": summarize_score_thresholds(test_prob, test_samples, score_thresholds),
        "time_period_metrics": summarize_time_period_metrics(test_prob, test_samples),
        "label_definition": label_definition_text(target_is_buy, label_mode, label_task),
    }
    return model, metrics, test_prob


def run_walk_forward_validation(
    samples: List[SignalSample],
    test_periods: List[str],
    random_state: int,
    min_train_samples: int,
    min_test_samples: int,
    score_thresholds: List[float],
    target_is_buy: bool,
    min_test_time: Optional[str] = None,
    label_mode: str = "point_in_time",
    label_task: str = "recognition",
) -> List[Dict]:
    sorted_samples = sorted(samples, key=lambda sample: (sample.open_time, sample.code, sample.open_klu_idx))
    rows = []
    for period in sorted(dict.fromkeys(test_periods)):
        period = normalize_period(period)
        test_start_time = walk_forward_period_start(period, min_test_time)
        test_end_time = period_end_time_exclusive(period)
        train_samples = [sample for sample in sorted_samples if sample.open_time < test_start_time]
        test_samples = [sample for sample in sorted_samples if test_start_time <= sample.open_time < test_end_time]
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
        if len({sample.label for sample in train_samples}) < 2:
            row["status"] = "skipped"
            row["skip_reason"] = "训练集只有一个类别"
            rows.append(row)
            continue
        if len({sample.label for sample in test_samples}) < 2:
            row["status"] = "skipped"
            row["skip_reason"] = "测试集只有一个类别"
            rows.append(row)
            continue

        feature_meta = build_feature_meta(train_samples)
        _, window_metrics, _ = train_correctness_model(
            train_samples,
            test_samples,
            feature_meta,
            random_state,
            score_thresholds,
            target_is_buy,
            label_mode,
            label_task,
        )
        window_metrics.pop("time_period_metrics", None)
        row.update(window_metrics)
        row["status"] = "ok"
        row["feature_count"] = len(feature_meta)
        rows.append(row)
    return rows


def write_samples_csv(path: Path, samples: List[SignalSample], score_by_key: Optional[Dict[Tuple[str, int], float]] = None) -> None:
    score_by_key = score_by_key or {}
    with path.open("w", newline="", encoding="utf-8") as fid:
        writer = csv.DictWriter(
            fid,
            fieldnames=[
                "open_time",
                "decision_time",
                "signal_time",
                "code",
                "open_klu_idx",
                "bsp_klu_idx",
                "bi_begin_time",
                "bi_end_time",
                "bi_direction",
                "entry_price",
                "label",
                "label_mode",
                "label_source",
                "score",
                "exit_reason",
            ],
        )
        writer.writeheader()
        for sample in samples:
            writer.writerow({
                "open_time": sample.open_time,
                "decision_time": sample.decision_time,
                "signal_time": sample.signal_time,
                "code": sample.code,
                "open_klu_idx": sample.open_klu_idx,
                "bsp_klu_idx": sample.bsp_klu_idx,
                "bi_begin_time": sample.bi_begin_time,
                "bi_end_time": sample.bi_end_time,
                "bi_direction": sample.bi_direction,
                "entry_price": sample.entry_price,
                "label": sample.label,
                "label_mode": sample.label_mode,
                "label_source": sample.label_source,
                "score": score_by_key.get((sample.code, sample.open_klu_idx)),
                "exit_reason": sample.exit_reason,
            })


def write_stability_samples_csv(path: Path, samples: List[SignalSample], score_by_key: Optional[Dict[Tuple[str, int], float]] = None) -> None:
    score_by_key = score_by_key or {}
    with path.open("w", newline="", encoding="utf-8") as fid:
        writer = csv.DictWriter(
            fid,
            fieldnames=[
                "open_time",
                "decision_time",
                "signal_time",
                "code",
                "open_klu_idx",
                "bsp_klu_idx",
                "bi_begin_time",
                "bi_end_time",
                "bi_direction",
                "entry_price",
                "label",
                "stability_label",
                "label_task",
                "label_mode",
                "label_source",
                "score",
                "first_seen_bsp_types",
                "first_seen_bsp_side",
                "stability_bars",
                "stability_bis",
                "stability_days",
                "stability_window_mode",
                "window_close_time",
                "window_close_reason",
                "last_match_time",
                "last_match_bi_begin_time",
                "last_match_bi_end_time",
                "last_match_bsp_types",
                "match_level",
                "unstable_reason",
                "exit_reason",
            ],
        )
        writer.writeheader()
        for sample in samples:
            writer.writerow({
                "open_time": sample.open_time,
                "decision_time": sample.decision_time,
                "signal_time": sample.signal_time,
                "code": sample.code,
                "open_klu_idx": sample.open_klu_idx,
                "bsp_klu_idx": sample.bsp_klu_idx,
                "bi_begin_time": sample.bi_begin_time,
                "bi_end_time": sample.bi_end_time,
                "bi_direction": sample.bi_direction,
                "entry_price": sample.entry_price,
                "label": sample.label,
                "stability_label": getattr(sample, "stability_label", sample.label),
                "label_task": getattr(sample, "label_task", None),
                "label_mode": sample.label_mode,
                "label_source": sample.label_source,
                "score": score_by_key.get((sample.code, sample.open_klu_idx)),
                "first_seen_bsp_types": getattr(sample, "first_seen_bsp_types", None),
                "first_seen_bsp_side": getattr(sample, "first_seen_bsp_side", None),
                "stability_bars": getattr(sample, "stability_bars", None),
                "stability_bis": getattr(sample, "stability_bis", None),
                "stability_days": getattr(sample, "stability_days", None),
                "stability_window_mode": getattr(sample, "stability_window_mode", None),
                "window_close_time": getattr(sample, "window_close_time", None),
                "window_close_reason": getattr(sample, "window_close_reason", None),
                "last_match_time": getattr(sample, "last_match_time", None),
                "last_match_bi_begin_time": getattr(sample, "last_match_bi_begin_time", None),
                "last_match_bi_end_time": getattr(sample, "last_match_bi_end_time", None),
                "last_match_bsp_types": getattr(sample, "last_match_bsp_types", None),
                "match_level": getattr(sample, "match_level", None),
                "unstable_reason": getattr(sample, "unstable_reason", None),
                "exit_reason": sample.exit_reason,
            })


def ensure_two_classes(samples: List[SignalSample], name: str) -> None:
    classes = {sample.label for sample in samples}
    if len(classes) < 2:
        raise ValueError(f"{name} 只有一个类别，无法训练/评估二分类模型：{classes}")


def build_run_config(args, codes: List[str], split_info: Dict[str, str]) -> Dict:
    model_params = dict(MODEL_PARAMS)
    model_params["random_state"] = args.random_state
    target_is_buy = signal_side_is_buy(args.signal_side)
    return {
        "begin_time": args.begin_time,
        "end_time": args.end_time,
        "signal_side": args.signal_side,
        "label_task": args.label_task,
        "label_target": label_target_name(target_is_buy),
        "label_mode": args.label_mode,
        "label_source": "as_of_replay_stability" if args.label_task == "stability" else ("as_of_replay" if args.label_mode == "point_in_time" else "final_structure"),
        "label_definition": label_definition_text(target_is_buy, args.label_mode, args.label_task),
        "label_decision_delay_bars": args.decision_delay_bars,
        "stability_bars": args.stability_bars,
        "stability_bis": args.stability_bis,
        "stability_days": args.stability_days,
        "stability_window_mode": args.stability_window_mode,
        "target_bsp_types": sorted(TARGET_BSP_TYPES),
        "main_bs_type": "1,1p",
        "data_src": "CACHE_DB",
        "model_kl_type": DB_KL_TYPE,
        "parent_kl_type": PARENT_DB_KL_TYPE,
        "child_kl_type": CHILD_DB_KL_TYPE,
        "split_mode": split_info["mode"],
        "split_time": split_info["split_time"],
        "train_ratio": args.train_ratio,
        "score_thresholds": [float(value) for value in args.score_thresholds.split(",") if value.strip()],
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
        "signal_workers": args.signal_workers,
        "effective_signal_workers": resolve_signal_workers(args.signal_workers, len(codes)),
        "model": model_params,
    }


def parse_args():
    parser = argparse.ArgumentParser(description="训练一个识别确认笔是否为目标买/卖点的30M结构模型。")
    parser.add_argument("--code", default="sz.000001")
    parser.add_argument("--codes", default=None, help="逗号分隔的股票列表；传入后会覆盖 --code。")
    parser.add_argument("--all", action="store_true", help="从缓存数据库读取所有有30M数据的股票。")
    parser.add_argument("--signal-side", choices=["buy", "sell"], default="buy", help="训练买点还是卖点识别。buy 使用确认下笔，sell 使用确认上笔。")
    parser.add_argument("--split-time", default=None, help="测试集起始时间，例如 2026-03-01 或 2026/03/01 10:00。")
    parser.add_argument("--begin-time", default="2015-01-01")
    parser.add_argument("--end-time", default=None)
    parser.add_argument("--train-ratio", type=float, default=0.7)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--score-thresholds", default="0.55,0.60,0.65")
    parser.add_argument("--walk-forward", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--walk-forward-test-periods", default=None)
    parser.add_argument("--walk-forward-min-train-samples", type=int, default=100)
    parser.add_argument("--walk-forward-min-test-samples", type=int, default=50)
    parser.add_argument("--signal-workers", type=int, default=0)
    parser.add_argument("--label-task", choices=["recognition", "stability"], default="recognition", help="recognition 训练买卖点识别模型；stability 只使用已出现的买卖点训练后续保留概率。")
    parser.add_argument("--label-mode", choices=["point_in_time", "final"], default="point_in_time", help="point_in_time 使用当时可见结构贴标签；final 使用完整区间最终结构贴标签。")
    parser.add_argument("--decision-delay-bars", type=int, default=0, help="point_in_time 模式下，候选笔结束后至少等待 N 根30M K线再采样。")
    parser.add_argument("--stability-bars", type=int, default=16, help="stability 任务中，观察后续 N 根30M K线后贴稳定性标签。")
    parser.add_argument("--stability-bis", type=int, default=0, help="stability 任务中，观察后续 N 根确认笔后贴稳定性标签。")
    parser.add_argument("--stability-days", type=int, default=0, help="stability 任务中，观察后续 N 个自然日后贴稳定性标签。")
    parser.add_argument("--stability-window-mode", choices=["any", "all"], default="any", help="多个稳定性窗口同时配置时，any 表示任一满足即关闭，all 表示全部满足才关闭。")
    parser.add_argument("--output-dir", default=None)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    target_is_buy = signal_side_is_buy(args.signal_side)
    if args.label_task == "stability":
        default_output_dir = "Debug/model_output/strategy_demo8_stability_buy" if target_is_buy else "Debug/model_output/strategy_demo8_stability_sell"
    else:
        default_output_dir = "Debug/model_output/strategy_demo8_buy" if target_is_buy else "Debug/model_output/strategy_demo8_sell"
    output_dir = Path(args.output_dir or default_output_dir)
    bi_name = signal_side_bi_name(target_is_buy)
    if args.decision_delay_bars < 0:
        raise ValueError("--decision-delay-bars 不能小于 0")
    if args.stability_bars < 0 or args.stability_bis < 0 or args.stability_days < 0:
        raise ValueError("--stability-bars/--stability-bis/--stability-days 不能小于 0")
    if args.label_task == "stability" and args.label_mode != "point_in_time":
        raise ValueError("--label-task stability 只支持 --label-mode point_in_time")

    if args.all:
        codes = get_stock_list_from_cache(DB_KL_TYPE)
        if not codes:
            raise ValueError("缓存数据库中没有找到30M股票数据。")
        print(f"从缓存数据库读取股票数量: {len(codes)}")
    else:
        codes = parse_code_list(args.codes or args.code)

    samples = collect_confirmed_bi_samples(
        codes,
        args.begin_time,
        args.end_time,
        args.signal_workers,
        target_is_buy,
        args.label_mode,
        args.decision_delay_bars,
        args.label_task,
        args.stability_bars,
        args.stability_bis,
        args.stability_days,
        args.stability_window_mode,
    )
    if not samples:
        raise ValueError(f"没有生成任何确认{bi_name}样本，请检查数据源连接、股票代码、时间范围或稳定性观察窗口。")
    if len(samples) < 20:
        raise ValueError(f"确认{bi_name}样本太少：{len(samples)}，请扩大时间范围。")

    train_samples, test_samples, split_info = split_by_time(samples, args.train_ratio, args.split_time)
    ensure_two_classes(train_samples, "训练集")
    ensure_two_classes(test_samples, "测试集")

    feature_meta = build_feature_meta(train_samples)
    score_thresholds = [float(value) for value in args.score_thresholds.split(",") if value.strip()]
    model, metrics, test_prob = train_correctness_model(
        train_samples,
        test_samples,
        feature_meta,
        args.random_state,
        score_thresholds,
        target_is_buy,
        args.label_mode,
        args.label_task,
    )
    metrics.update({
        "kl_type": DB_KL_TYPE,
        "parent_kl_type": PARENT_DB_KL_TYPE,
        "child_kl_type": CHILD_DB_KL_TYPE,
        "label_task": args.label_task,
        "label_mode": args.label_mode,
        "label_source": "as_of_replay_stability" if args.label_task == "stability" else ("as_of_replay" if args.label_mode == "point_in_time" else "final_structure"),
        "label_decision_delay_bars": args.decision_delay_bars,
        "label_target_bsp_types": sorted(TARGET_BSP_TYPES),
        "stability_bars": args.stability_bars,
        "stability_bis": args.stability_bis,
        "stability_days": args.stability_days,
        "stability_window_mode": args.stability_window_mode,
        "split_mode": split_info["mode"],
        "split_time": split_info["split_time"],
        "train_period": split_info["train_period"],
        "test_period": split_info["test_period"],
        "train_code_count": len({sample.code for sample in train_samples}),
        "test_code_count": len({sample.code for sample in test_samples}),
        "run_config": build_run_config(args, codes, split_info),
    })
    if args.label_task == "stability":
        metrics["stability_summary"] = stability_summary(samples)
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
            score_thresholds,
            target_is_buy,
            split_info["split_time"],
            args.label_mode,
            args.label_task,
        )

    feature_importance = get_feature_importance(model, feature_meta)
    score_by_key = {
        (sample.code, sample.open_klu_idx): float(score)
        for sample, score in zip(test_samples, test_prob)
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "model.pkl").open("wb") as fid:
        pickle.dump(model, fid)
    with (output_dir / "feature.meta.json").open("w", encoding="utf-8") as fid:
        json.dump(feature_meta, fid, ensure_ascii=False, indent=2)
    with (output_dir / "metrics.json").open("w", encoding="utf-8") as fid:
        json.dump(metrics, fid, ensure_ascii=False, indent=2)
    with (output_dir / "feature_importance.json").open("w", encoding="utf-8") as fid:
        json.dump(feature_importance, fid, ensure_ascii=False, indent=2)
    if args.label_task == "stability":
        with (output_dir / "stability_metrics.json").open("w", encoding="utf-8") as fid:
            json.dump(metrics, fid, ensure_ascii=False, indent=2)
        write_stability_samples_csv(output_dir / "stability_samples.csv", samples, score_by_key)
        write_stability_samples_csv(output_dir / "samples.csv", samples, score_by_key)
    else:
        write_samples_csv(output_dir / "samples.csv", samples, score_by_key)
    write_libsvm(output_dir / "samples.libsvm", samples, feature_meta)
    write_feature_importance(output_dir / "feature_importance.csv", feature_importance)

    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"模型文件: {output_dir / 'model.pkl'}")
