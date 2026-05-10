from __future__ import annotations

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
from typing import Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Debug.strategy_demo7 import (
    CHILD_DB_KL_TYPE,
    CHILD_LV_IDX,
    DB_KL_TYPE,
    MODEL_LV_IDX,
    PARENT_DB_KL_TYPE,
    build_chan,
    build_parent_level_context,
    ctime_to_date_str,
    ctime_to_str,
    get_stock_list_from_cache,
    normalize_cache_code,
    parse_code_list,
)
from Debug.strategy_demo8 import (
    bi_matches_signal_side,
    confirmed_bi_feature,
    latest_previous_bsp,
)


DEFAULT_BUY_MODEL_DIR = ROOT_DIR / "Debug" / "model_output" / "strategy_demo8_buy"
DEFAULT_SELL_MODEL_DIR = ROOT_DIR / "Debug" / "model_output" / "strategy_demo8_sell"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "Debug" / "model_output" / "strategy_demo8_scan"
DEFAULT_THRESHOLDS = (0.55, 0.60, 0.65)
KEY_FEATURES = (
    "candidate_divergence_rate",
    "candidate_break_prev_extreme",
    "entry_close_pos",
    "child_close_pos",
    "parent_range",
    "ma_dist_10",
    "prev_bsp_divergence_rate",
)


def load_model_bundle(model_dir: Path):
    model_path = model_dir / "model.pkl"
    feature_meta_path = model_dir / "feature.meta.json"
    if not model_path.exists() or not feature_meta_path.exists():
        raise FileNotFoundError(f"模型文件不完整：{model_dir}")
    with model_path.open("rb") as fid:
        model = pickle.load(fid)
    with feature_meta_path.open("r", encoding="utf-8") as fid:
        feature_meta = json.load(fid)
    return model, feature_meta


def feature_row(feature: Dict[str, float], feature_meta: Dict[str, int]) -> List[float]:
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


def predict_probability(model, feature_meta: Dict[str, int], feature: Dict[str, float]) -> float:
    return float(model.predict_proba([feature_row(feature, feature_meta)])[0][1])


def parse_thresholds(value: str) -> List[float]:
    thresholds = [float(item.strip()) for item in value.split(",") if item.strip()]
    if not thresholds:
        raise ValueError("--thresholds 至少需要一个阈值")
    return sorted(thresholds)


def resolve_workers(requested_workers: int, code_count: int) -> int:
    if requested_workers < 0:
        raise ValueError("--workers 不能小于 0")
    if code_count <= 1:
        return 1
    if requested_workers > 0:
        return min(requested_workers, code_count)
    cpu_count = os.cpu_count() or 2
    return max(1, min(cpu_count - 1, code_count, 6))


def signal_sides_from_arg(value: str) -> List[str]:
    if value == "both":
        return ["buy", "sell"]
    return [value]


def threshold_field_name(threshold: float) -> str:
    return f"threshold_hit_{int(round(threshold * 100)):03d}"


def threshold_hit_fields(probability: float, thresholds: List[float]) -> Dict[str, bool]:
    return {
        threshold_field_name(threshold): probability >= threshold
        for threshold in thresholds
    }


def scan_code(
    code: str,
    begin_time: str,
    end_time: Optional[str],
    signal_sides: List[str],
    min_prob: float,
    recent_bars: int,
    thresholds: List[float],
    buy_model_dir: str,
    sell_model_dir: str,
) -> Tuple[str, List[Dict], Optional[str]]:
    try:
        model_bundles = {}
        if "buy" in signal_sides:
            model_bundles["buy"] = (*load_model_bundle(Path(buy_model_dir)), str(Path(buy_model_dir)))
        if "sell" in signal_sides:
            model_bundles["sell"] = (*load_model_bundle(Path(sell_model_dir)), str(Path(sell_model_dir)))

        parent_dates, parent_context_by_date = build_parent_level_context(code, begin_time, end_time)
        chan = build_chan(code, begin_time, end_time)
        for _ in chan.step_load():
            pass

        level_chan = chan[MODEL_LV_IDX]
        child_level_chan = chan[CHILD_LV_IDX]
        final_klus = list(level_chan.klu_iter())
        pos_by_idx = {int(klu.idx): pos for pos, klu in enumerate(final_klus)}
        sorted_bsp_list = level_chan.bs_point_lst.getSortedBspList()
        recent_min_klu_idx = None
        if recent_bars > 0 and final_klus:
            recent_min_klu_idx = int(final_klus[max(0, len(final_klus) - recent_bars)].idx)

        rows: List[Dict] = []
        for signal_side in signal_sides:
            target_is_buy = signal_side == "buy"
            model, feature_meta, model_dir = model_bundles[signal_side]
            for bi in level_chan.bi_list:
                if not bi.is_sure or not bi_matches_signal_side(bi, target_is_buy):
                    continue

                entry_klu = bi.get_end_klu()
                if recent_min_klu_idx is not None and int(entry_klu.idx) < recent_min_klu_idx:
                    continue

                pos = pos_by_idx.get(int(entry_klu.idx))
                if pos is None:
                    continue

                previous_bsp = latest_previous_bsp(sorted_bsp_list, bi.idx)
                entry_date = ctime_to_date_str(entry_klu.time)
                parent_pos = bisect_left(parent_dates, entry_date) - 1
                parent_context = parent_context_by_date[parent_dates[parent_pos]] if parent_pos >= 0 else None
                feature = confirmed_bi_feature(
                    final_klus,
                    pos,
                    bi,
                    target_is_buy,
                    previous_bsp,
                    parent_context,
                    child_level_chan,
                )
                probability = predict_probability(model, feature_meta, feature)
                row = {
                    "code": code,
                    "signal_side": signal_side,
                    "open_time": ctime_to_str(entry_klu.time),
                    "bi_idx": int(bi.idx),
                    "klu_idx": int(entry_klu.idx),
                    "price": float(entry_klu.close),
                    "probability": probability,
                    "hit_min_prob": probability >= min_prob,
                    "model_dir": model_dir,
                }
                row.update(threshold_hit_fields(probability, thresholds))
                for feature_name in KEY_FEATURES:
                    row[feature_name] = feature.get(feature_name)
                rows.append(row)

        rows.sort(key=lambda item: (-float(item["probability"]), item["open_time"], item["code"], item["signal_side"]))
        return code, rows, None
    except Exception as exc:
        return code, [], str(exc)


def collect_codes(args) -> List[str]:
    if args.all:
        codes = get_stock_list_from_cache(DB_KL_TYPE)
        if not codes:
            raise ValueError("缓存数据库中没有找到30M股票数据")
        return codes
    return parse_code_list(args.codes or args.code)


def write_csv(path: Path, rows: List[Dict], thresholds: List[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    threshold_fields = [threshold_field_name(threshold) for threshold in thresholds]
    fieldnames = [
        "code",
        "signal_side",
        "open_time",
        "bi_idx",
        "klu_idx",
        "price",
        "probability",
        "hit_min_prob",
        *threshold_fields,
        *KEY_FEATURES,
        "model_dir",
    ]
    with path.open("w", newline="", encoding="utf-8") as fid:
        writer = csv.DictWriter(fid, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_summary(
    *,
    args,
    codes: List[str],
    rows: List[Dict],
    filtered_rows: List[Dict],
    failures: Dict[str, str],
    thresholds: List[float],
    signal_sides: List[str],
    worker_count: int,
) -> Dict:
    threshold_counts = {
        f">={threshold}": sum(1 for row in rows if float(row["probability"]) >= threshold)
        for threshold in thresholds
    }
    return {
        "begin_time": args.begin_time,
        "end_time": args.end_time,
        "model_kl_type": DB_KL_TYPE,
        "parent_kl_type": PARENT_DB_KL_TYPE,
        "child_kl_type": CHILD_DB_KL_TYPE,
        "signal_sides": signal_sides,
        "min_prob": args.min_prob,
        "recent_bars": args.recent_bars,
        "thresholds": thresholds,
        "scan_code_count": len(codes),
        "success_code_count": len(codes) - len(failures),
        "failure_code_count": len(failures),
        "candidate_count": len(rows),
        "filtered_count": len(filtered_rows),
        "buy_candidate_count": sum(1 for row in rows if row["signal_side"] == "buy"),
        "sell_candidate_count": sum(1 for row in rows if row["signal_side"] == "sell"),
        "threshold_counts": threshold_counts,
        "workers": worker_count,
        "buy_model_dir": str(Path(args.buy_model_dir)),
        "sell_model_dir": str(Path(args.sell_model_dir)),
        "failures": failures,
    }


def parse_args():
    parser = argparse.ArgumentParser(description="使用 demo8 训练模型扫描30M确认笔的一类买卖点概率。")
    parser.add_argument("--code", default="sz.000001")
    parser.add_argument("--codes", default=None, help="逗号分隔股票列表，传入后覆盖 --code。")
    parser.add_argument("--all", action="store_true", help="从缓存数据库读取所有有30M数据的股票。")
    parser.add_argument("--begin-time", default="2026-01-01")
    parser.add_argument("--end-time", default=None)
    parser.add_argument("--signal-side", choices=["buy", "sell", "both"], default="both")
    parser.add_argument("--min-prob", type=float, default=0.60)
    parser.add_argument("--recent-bars", type=int, default=48, help="只扫描最近 N 根30M K线内出现的确认笔；0 表示全历史。")
    parser.add_argument("--thresholds", default="0.55,0.60,0.65")
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--buy-model-dir", default=str(DEFAULT_BUY_MODEL_DIR))
    parser.add_argument("--sell-model-dir", default=str(DEFAULT_SELL_MODEL_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--output", default=None, help="可选：过滤结果 CSV 路径；不传则写入 output-dir/signals_filtered.csv。")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.recent_bars < 0:
        raise ValueError("--recent-bars 不能小于 0")
    thresholds = parse_thresholds(args.thresholds)
    signal_sides = signal_sides_from_arg(args.signal_side)
    codes = [normalize_cache_code(code) for code in collect_codes(args)]
    worker_count = resolve_workers(args.workers, len(codes))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    recent_desc = f"最近{args.recent_bars}根30M K线" if args.recent_bars > 0 else "全历史"
    print(f"扫描股票数量: {len(codes)}, signal_side={args.signal_side}, recent={recent_desc}, workers={worker_count}")

    rows_by_code: Dict[str, List[Dict]] = {}
    failures: Dict[str, str] = {}
    if worker_count == 1:
        for code in codes:
            _, code_rows, error = scan_code(
                code,
                args.begin_time,
                args.end_time,
                signal_sides,
                args.min_prob,
                args.recent_bars,
                thresholds,
                args.buy_model_dir,
                args.sell_model_dir,
            )
            if error:
                failures[code] = error
                print(f"{code}: 扫描失败，已跳过：{error}")
                continue
            rows_by_code[code] = code_rows
            print(f"{code}: 候选 {len(code_rows)}")
    else:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            future_to_code = {
                executor.submit(
                    scan_code,
                    code,
                    args.begin_time,
                    args.end_time,
                    signal_sides,
                    args.min_prob,
                    args.recent_bars,
                    thresholds,
                    args.buy_model_dir,
                    args.sell_model_dir,
                ): code
                for code in codes
            }
            for future in as_completed(future_to_code):
                code = future_to_code[future]
                _, code_rows, error = future.result()
                if error:
                    failures[code] = error
                    print(f"{code}: 扫描失败，已跳过：{error}")
                    continue
                rows_by_code[code] = code_rows
                print(f"{code}: 候选 {len(code_rows)}")

    rows: List[Dict] = []
    for code in codes:
        rows.extend(rows_by_code.get(code, []))
    rows.sort(key=lambda item: (-float(item["probability"]), item["open_time"], item["code"], item["signal_side"]))
    filtered_rows = [row for row in rows if float(row["probability"]) >= args.min_prob]

    all_csv = output_dir / "signals_all.csv"
    filtered_csv = Path(args.output) if args.output else output_dir / "signals_filtered.csv"
    summary_path = output_dir / "summary.json"
    write_csv(all_csv, rows, thresholds)
    write_csv(filtered_csv, filtered_rows, thresholds)

    summary = build_summary(
        args=args,
        codes=codes,
        rows=rows,
        filtered_rows=filtered_rows,
        failures=failures,
        thresholds=thresholds,
        signal_sides=signal_sides,
        worker_count=worker_count,
    )
    with summary_path.open("w", encoding="utf-8") as fid:
        json.dump(summary, fid, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"全量结果: {all_csv}")
    print(f"过滤结果: {filtered_csv}")
    print(f"汇总文件: {summary_path}")
