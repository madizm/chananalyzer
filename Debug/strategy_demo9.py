from __future__ import annotations

import argparse
import csv
import json
import pickle
import sys
from bisect import bisect_left
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Chan import CChan
from Common.CEnum import AUTYPE, DATA_SRC
from Debug.strategy_demo7 import (
    CHILD_DB_KL_TYPE,
    CHILD_KL_TYPE,
    CHILD_LV_IDX,
    DB_KL_TYPE,
    MODEL_KL_TYPE,
    MODEL_LV_IDX,
    MODEL_PARAMS,
    PARENT_DB_KL_TYPE,
    SignalSample,
    build_feature_meta,
    build_matrix,
    build_parent_level_context,
    codes_digest,
    ctime_to_date_str,
    ctime_to_str,
    get_feature_importance,
    get_stock_list_from_cache,
    make_chan_config,
    metric_or_none,
    normalize_period,
    parse_code_list,
    parse_period_list,
    period_end_time_exclusive,
    safe_div,
    sample_period,
    split_by_time,
    walk_forward_period_start,
    write_feature_importance,
    write_libsvm,
)
from Debug.bsp_point_in_time_label import collect_point_in_time_samples_for_code
from Debug.strategy_demo8 import (
    bi_matches_signal_side,
    confirmed_bi_feature,
    ensure_two_classes,
    latest_previous_bsp,
    resolve_signal_workers,
    signal_side_bi_name,
    signal_side_is_buy,
    signal_side_point_name,
    summarize_score_buckets,
    summarize_score_thresholds,
    summarize_time_period_metrics,
    write_samples_csv,
)
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


TARGET_BSP_TYPES = {"2", "2s"}
FIRST_BSP_TYPES = {"1", "1p"}
MAIN_BS_TYPE = "1,1p,2,2s"
LABEL_GROUP = "second"


def label_target_name(target_is_buy: bool) -> str:
    return "confirmed_bi_is_target_second_buy_point" if target_is_buy else "confirmed_bi_is_target_second_sell_point"


def label_definition_text(target_is_buy: bool, label_mode: str = "point_in_time") -> str:
    bi_name = signal_side_bi_name(target_is_buy)
    point_name = signal_side_point_name(target_is_buy)
    if label_mode == "point_in_time":
        return f"1 表示确认{bi_name}在 decision_time 当时可见结构中存在目标二类{point_name}(2/2s)，0 表示当时可见结构中不是目标二类{point_name}。"
    return f"1 表示确认{bi_name}最终存在目标二类{point_name}(2/2s)，0 表示确认{bi_name}不是目标二类{point_name}。"


def build_second_chan(code: str, begin_time: str, end_time: Optional[str]) -> CChan:
    config = make_chan_config(MAIN_BS_TYPE, trigger_step=True)
    return CChan(
        code=code,
        begin_time=begin_time,
        end_time=end_time,
        data_src=DATA_SRC.CACHE_DB,
        lv_list=[MODEL_KL_TYPE, CHILD_KL_TYPE],
        config=config,
        autype=AUTYPE.QFQ,
    )


def bsp_type_set(bsp) -> set[str]:
    if bsp is None:
        return set()
    return {bsp_type.strip() for bsp_type in str(bsp.type2str()).split(",") if bsp_type.strip()}


def target_bsp_type_hit(bsp, target_is_buy: bool) -> bool:
    if bsp is None or bool(bsp.is_buy) != target_is_buy:
        return False
    return bool(bsp_type_set(bsp) & TARGET_BSP_TYPES)


def latest_previous_first_bsp(sorted_bsp_list: List, bi_idx: int, target_is_buy: bool):
    previous_first_bsp = None
    for bsp in sorted_bsp_list:
        if bsp.bi.idx >= bi_idx:
            break
        if bool(bsp.is_buy) == target_is_buy and bsp_type_set(bsp) & FIRST_BSP_TYPES:
            previous_first_bsp = bsp
    return previous_first_bsp


def previous_first_bsp_feature(entry_klu, current_bi, previous_first_bsp) -> Dict[str, float]:
    feature = {
        "prev_first_bsp_exists": 0.0,
        "prev_first_bsp_type_1": 0.0,
        "prev_first_bsp_type_1p": 0.0,
        "prev_first_bsp_bi_gap": 0.0,
        "prev_first_bsp_klu_gap": 0.0,
        "entry_vs_prev_first_bsp_price": 0.0,
        "retracement_from_prev_first": 0.0,
        "prev_first_bsp_divergence_rate": 0.0,
    }
    if previous_first_bsp is None:
        return feature

    prev_price = float(previous_first_bsp.klu.close)
    entry_price = float(entry_klu.close)
    if previous_first_bsp.is_buy:
        retracement = safe_div(entry_price - prev_price, max(float(current_bi.amp()), 1e-7))
    else:
        retracement = safe_div(prev_price - entry_price, max(float(current_bi.amp()), 1e-7))

    feature.update({
        "prev_first_bsp_exists": 1.0,
        "prev_first_bsp_bi_gap": float(current_bi.idx - previous_first_bsp.bi.idx),
        "prev_first_bsp_klu_gap": float(entry_klu.idx - previous_first_bsp.klu.idx),
        "entry_vs_prev_first_bsp_price": safe_div(entry_price - prev_price, prev_price),
        "retracement_from_prev_first": retracement,
    })
    for bsp_type in bsp_type_set(previous_first_bsp):
        feature[f"prev_first_bsp_type_{bsp_type}"] = 1.0
    for feature_name, value in previous_first_bsp.features.items():
        if feature_name != "divergence_rate" or value is None:
            continue
        try:
            feature["prev_first_bsp_divergence_rate"] = float(value)
        except (TypeError, ValueError):
            pass
    return feature


def second_bi_feature(
    klus: List,
    pos: int,
    bi,
    target_is_buy: bool,
    previous_bsp=None,
    previous_first_bsp=None,
    parent_context=None,
    child_level_chan=None,
) -> Dict[str, float]:
    feature = confirmed_bi_feature(
        klus,
        pos,
        bi,
        target_is_buy,
        previous_bsp,
        parent_context,
        child_level_chan,
    )
    feature.update(previous_first_bsp_feature(klus[pos], bi, previous_first_bsp))
    return feature


def point_in_time_second_feature_builder(
    final_klus: List,
    pos: int,
    bi,
    target_is_buy: bool,
    sorted_bsp_list: List,
    parent_context=None,
    child_level_chan=None,
) -> Dict[str, float]:
    return second_bi_feature(
        final_klus,
        pos,
        bi,
        target_is_buy,
        latest_previous_bsp(sorted_bsp_list, bi.idx),
        latest_previous_first_bsp(sorted_bsp_list, bi.idx, target_is_buy),
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
) -> Tuple[str, List[SignalSample]]:
    if label_mode == "point_in_time":
        point_name = "buy_point" if target_is_buy else "sell_point"
        return collect_point_in_time_samples_for_code(
            code=code,
            begin_time=begin_time,
            end_time=end_time,
            target_is_buy=target_is_buy,
            target_bsp_types=set(TARGET_BSP_TYPES),
            build_chan_fn=build_second_chan,
            feature_builder=point_in_time_second_feature_builder,
            exit_reason_positive=f"correct_second_{point_name}",
            exit_reason_negative=f"not_second_{point_name}",
            decision_delay_bars=decision_delay_bars,
        )
    if label_mode != "final":
        raise ValueError(f"不支持的 label_mode: {label_mode}")

    parent_dates, parent_context_by_date = build_parent_level_context(code, begin_time, end_time)
    chan = build_second_chan(code, begin_time, end_time)
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
        if not bi.is_sure or not bi_matches_signal_side(bi, target_is_buy):
            continue

        entry_klu = bi.get_end_klu()
        pos = pos_by_idx.get(int(entry_klu.idx))
        if pos is None:
            continue
        bsp = target_bsp_by_bi_idx.get(int(bi.idx))
        previous_bsp = latest_previous_bsp(sorted_bsp_list, bi.idx)
        previous_first_bsp = latest_previous_first_bsp(sorted_bsp_list, bi.idx, target_is_buy)
        entry_date = ctime_to_date_str(entry_klu.time)
        parent_pos = bisect_left(parent_dates, entry_date) - 1
        parent_context = parent_context_by_date[parent_dates[parent_pos]] if parent_pos >= 0 else None

        sample = SignalSample(
            code=code,
            bsp_klu_idx=int(bsp.klu.idx) if bsp is not None else int(entry_klu.idx),
            open_klu_idx=int(entry_klu.idx),
            open_time=ctime_to_str(entry_klu.time),
            entry_price=float(entry_klu.close),
            feature=second_bi_feature(
                final_klus,
                pos,
                bi,
                target_is_buy,
                previous_bsp,
                previous_first_bsp,
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
        sample.exit_reason = f"correct_second_{point_name}" if sample.label == 1 else f"not_second_{point_name}"
        samples.append(sample)

    return code, samples


def collect_confirmed_bi_samples(
    codes: List[str],
    begin_time: str,
    end_time: Optional[str],
    signal_workers: int,
    target_is_buy: bool,
    label_mode: str = "point_in_time",
    decision_delay_bars: int = 0,
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


def train_correctness_model(
    train_samples: List[SignalSample],
    test_samples: List[SignalSample],
    feature_meta: Dict[str, int],
    random_state: int,
    score_thresholds: List[float],
    target_is_buy: bool,
    label_mode: str = "point_in_time",
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
        "label_definition": label_definition_text(target_is_buy, label_mode),
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
        )
        window_metrics.pop("time_period_metrics", None)
        row.update(window_metrics)
        row["status"] = "ok"
        row["feature_count"] = len(feature_meta)
        rows.append(row)
    return rows


def build_run_config(args, codes: List[str], split_info: Dict[str, str]) -> Dict:
    model_params = dict(MODEL_PARAMS)
    model_params["random_state"] = args.random_state
    target_is_buy = signal_side_is_buy(args.signal_side)
    return {
        "begin_time": args.begin_time,
        "end_time": args.end_time,
        "signal_side": args.signal_side,
        "label_group": LABEL_GROUP,
        "label_target": label_target_name(target_is_buy),
        "label_mode": args.label_mode,
        "label_source": "as_of_replay" if args.label_mode == "point_in_time" else "final_structure",
        "label_definition": label_definition_text(target_is_buy, args.label_mode),
        "label_decision_delay_bars": args.decision_delay_bars,
        "target_bsp_types": sorted(TARGET_BSP_TYPES),
        "dependency_bsp_types": sorted(FIRST_BSP_TYPES),
        "main_bs_type": MAIN_BS_TYPE,
        "data_src": DATA_SRC.CACHE_DB.name,
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
    parser = argparse.ArgumentParser(description="训练一个识别确认笔是否为二类买/卖点的30M结构模型。")
    parser.add_argument("--code", default="sz.000001")
    parser.add_argument("--codes", default=None, help="逗号分隔的股票列表；传入后会覆盖 --code。")
    parser.add_argument("--all", action="store_true", help="从缓存数据库读取所有有30M数据的股票。")
    parser.add_argument("--signal-side", choices=["buy", "sell"], default="buy", help="训练二类买点还是二类卖点识别。buy 使用确认下笔，sell 使用确认上笔。")
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
    parser.add_argument("--label-mode", choices=["point_in_time", "final"], default="point_in_time", help="point_in_time 使用当时可见结构贴标签；final 使用完整区间最终结构贴标签。")
    parser.add_argument("--decision-delay-bars", type=int, default=0, help="point_in_time 模式下，候选笔结束后至少等待 N 根30M K线再采样。")
    parser.add_argument("--output-dir", default=None)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    target_is_buy = signal_side_is_buy(args.signal_side)
    default_output_dir = "Debug/model_output/strategy_demo9_buy" if target_is_buy else "Debug/model_output/strategy_demo9_sell"
    output_dir = Path(args.output_dir or default_output_dir)
    bi_name = signal_side_bi_name(target_is_buy)
    if args.decision_delay_bars < 0:
        raise ValueError("--decision-delay-bars 不能小于 0")

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
    )
    if not samples:
        raise ValueError(f"没有生成任何确认{bi_name}样本，请检查数据源连接、股票代码或时间范围。")
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
    )
    metrics.update({
        "kl_type": DB_KL_TYPE,
        "parent_kl_type": PARENT_DB_KL_TYPE,
        "child_kl_type": CHILD_DB_KL_TYPE,
        "label_mode": args.label_mode,
        "label_source": "as_of_replay" if args.label_mode == "point_in_time" else "final_structure",
        "label_decision_delay_bars": args.decision_delay_bars,
        "label_target_bsp_types": sorted(TARGET_BSP_TYPES),
        "split_mode": split_info["mode"],
        "split_time": split_info["split_time"],
        "train_period": split_info["train_period"],
        "test_period": split_info["test_period"],
        "train_code_count": len({sample.code for sample in train_samples}),
        "test_code_count": len({sample.code for sample in test_samples}),
        "run_config": build_run_config(args, codes, split_info),
    })
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
    write_samples_csv(output_dir / "samples.csv", samples, score_by_key)
    write_libsvm(output_dir / "samples.libsvm", samples, feature_meta)
    write_feature_importance(output_dir / "feature_importance.csv", feature_importance)

    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"模型文件: {output_dir / 'model.pkl'}")
