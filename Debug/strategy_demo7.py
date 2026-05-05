import argparse
import csv
import json
import math
import pickle
import sqlite3
import sys
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
DB_KL_TYPE = "30M"
TARGET_BSP_TYPES = {"1", "1p"}


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


def strategy_feature(klus: List, pos: int, bsp, previous_bsp=None) -> Dict[str, float]:
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
    return feature


def build_chan(code: str, begin_time: str, end_time: Optional[str]) -> CChan:
    config = CChanConfig({
        "trigger_step": True,
        "bi_strict": True,
        "skip_step": 0,
        "divergence_rate": float("inf"),
        "bsp2_follow_1": False,
        "bsp3_follow_1": False,
        "min_zs_cnt": 0,
        "bs1_peak": False,
        "macd_algo": "peak",
        "bs_type": "1,1p",
        "print_warning": True,
        "zs_algo": "normal",
    })
    return CChan(
        code=code,
        begin_time=begin_time,
        end_time=end_time,
        data_src=DATA_SRC.CACHE_DB,
        lv_list=[MODEL_KL_TYPE],
        config=config,
        autype=AUTYPE.QFQ,
    )


def collect_buy_signals(chan: CChan, code: str) -> Tuple[List[SignalSample], List]:
    samples: List[SignalSample] = []
    seen_bsp_klu_idx = set()

    for chan_snapshot in chan.step_load():
        level_chan = chan_snapshot[0]
        if len(level_chan) < 2:
            continue

        last_klu = level_chan[-1][-1]
        bsp_list = chan_snapshot.get_latest_bsp()
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
        samples.append(
            SignalSample(
                code=code,
                bsp_klu_idx=int(last_bsp.klu.idx),
                open_klu_idx=int(last_klu.idx),
                open_time=ctime_to_str(last_klu.time),
                entry_price=float(last_klu.close),
                feature=strategy_feature(final_klus_so_far, pos, last_bsp, previous_bsp),
            )
        )
        seen_bsp_klu_idx.add(last_bsp.klu.idx)

    final_klus = list(chan[0].klu_iter())
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


def metric_or_none(func, y_true, y_score) -> Optional[float]:
    try:
        return float(func(y_true, y_score))
    except ValueError:
        return None


def avg_optional(values: Iterable[Optional[float]]) -> float:
    real_values = [float(value) for value in values if value is not None]
    if not real_values:
        return 0.0
    return sum(real_values) / len(real_values)


def summarize_score_buckets(
    test_prob,
    test_samples: List[SignalSample],
    buckets: Tuple[float, ...] = (0.05, 0.10, 0.20, 0.30),
) -> List[Dict[str, float]]:
    ranked_samples = sorted(zip(test_prob, test_samples), key=lambda item: item[0], reverse=True)
    bucket_rows = []
    for bucket in buckets:
        top_n = max(1, int(len(ranked_samples) * bucket))
        top_items = ranked_samples[:top_n]
        top_scores = [float(score) for score, _ in top_items]
        top_samples = [sample for _, sample in top_items]
        hit_rate = sum(int(sample.label) for sample in top_samples) / top_n
        bucket_rows.append({
            "top_pct": bucket,
            "sample_count": top_n,
            "min_score": min(top_scores),
            "avg_score": sum(top_scores) / top_n,
            "hit_rate": hit_rate,
            "avg_realized_return": avg_optional(sample.realized_return for sample in top_samples),
            "avg_forward_return": avg_optional(sample.forward_return for sample in top_samples),
            "avg_max_gain": avg_optional(sample.max_gain for sample in top_samples),
            "avg_max_drawdown": avg_optional(sample.max_drawdown for sample in top_samples),
        })
    return bucket_rows


def train_model(
    train_samples: List[SignalSample],
    test_samples: List[SignalSample],
    feature_meta: Dict[str, int],
    random_state: int,
):
    x_train = build_matrix(train_samples, feature_meta)
    y_train = [int(sample.label) for sample in train_samples]
    x_test = build_matrix(test_samples, feature_meta)
    y_test = [int(sample.label) for sample in test_samples]

    model = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("clf", RandomForestClassifier(
            n_estimators=300,
            max_depth=4,
            min_samples_leaf=5,
            class_weight="balanced_subsample",
            random_state=random_state,
        )),
    ])
    model.fit(x_train, y_train)

    test_prob = model.predict_proba(x_test)[:, 1]
    test_pred = [int(prob >= 0.5) for prob in test_prob]
    train_positive_rate = sum(y_train) / len(y_train)
    test_positive_rate = sum(y_test) / len(y_test)

    score_buckets = summarize_score_buckets(test_prob, test_samples)
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
        "test_avg_forward_return": avg_optional(sample.forward_return for sample in test_samples),
        "test_top20pct_hit_rate": top20_bucket["hit_rate"],
        "test_top20pct_avg_realized_return": top20_bucket["avg_realized_return"],
        "score_buckets": score_buckets,
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
            chan = build_chan(code, args.begin_time, args.end_time)
            code_samples, final_klus = collect_buy_signals(chan, code)
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
    model, metrics, test_prob = train_model(
        train_samples,
        test_samples,
        feature_meta,
        args.random_state,
    )
    metrics["kl_type"] = DB_KL_TYPE
    metrics["split_mode"] = split_info["mode"]
    metrics["split_time"] = split_info["split_time"]
    metrics["train_period"] = split_info["train_period"]
    metrics["test_period"] = split_info["test_period"]
    metrics["train_code_count"] = len({sample.code for sample in train_samples})
    metrics["test_code_count"] = len({sample.code for sample in test_samples})
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

    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"模型文件: {output_dir / 'model.pkl'}")
    print(f"特征映射: {output_dir / 'feature.meta.json'}")
    print(f"特征重要性: {output_dir / 'feature_importance.csv'}")
    print(f"样本明细: {output_dir / 'samples.csv'}")
