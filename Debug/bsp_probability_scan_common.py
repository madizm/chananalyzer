from __future__ import annotations

import argparse
import csv
import json
import math
import os
import pickle
import sqlite3
import sys
from bisect import bisect_left
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
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
from Debug.bsp_point_in_time_label import (
    latest_confirmed_bi_idx,
    stability_context_feature,
    target_bsp_by_key,
)


DEFAULT_DB_PATH = ROOT_DIR / "chan.db"


@dataclass(frozen=True)
class BspProbabilityScanConfig:
    model_name: str
    target_group: str
    target_bsp_types: Tuple[str, ...]
    dependency_bsp_types: Tuple[str, ...]
    main_bs_type: str
    default_buy_model_dir: Path
    default_sell_model_dir: Path
    default_output_dir: Path
    feature_names: Tuple[str, ...]
    description: str
    label_task: str = "recognition"
    base_model_name: Optional[str] = None


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


def load_model_bundles(signal_sides: List[str], buy_model_dir: str, sell_model_dir: str) -> Dict[str, Tuple[object, Dict[str, int], str]]:
    model_bundles = {}
    if "buy" in signal_sides:
        model_bundles["buy"] = (*load_model_bundle(Path(buy_model_dir)), str(Path(buy_model_dir)))
    if "sell" in signal_sides:
        model_bundles["sell"] = (*load_model_bundle(Path(sell_model_dir)), str(Path(sell_model_dir)))
    return model_bundles


def config_base_model_name(config: BspProbabilityScanConfig) -> str:
    return config.base_model_name or config.model_name


def build_scan_chan(config: BspProbabilityScanConfig, code: str, begin_time: str, end_time: Optional[str]):
    base_model_name = config_base_model_name(config)
    if base_model_name == "demo8":
        return build_chan(code, begin_time, end_time)
    if base_model_name == "demo9":
        from Debug.strategy_demo9 import build_second_chan

        return build_second_chan(code, begin_time, end_time)
    raise ValueError(f"不支持的模型扫描配置：{config.model_name}")


def build_scan_feature(
    config: BspProbabilityScanConfig,
    final_klus: List,
    pos: int,
    bi,
    target_is_buy: bool,
    sorted_bsp_list: List,
    parent_context,
    child_level_chan,
) -> Dict[str, float]:
    previous_bsp = latest_previous_bsp(sorted_bsp_list, bi.idx)
    base_model_name = config_base_model_name(config)
    if base_model_name == "demo8":
        return confirmed_bi_feature(
            final_klus,
            pos,
            bi,
            target_is_buy,
            previous_bsp,
            parent_context,
            child_level_chan,
        )
    if base_model_name == "demo9":
        from Debug.strategy_demo9 import latest_previous_first_bsp, second_bi_feature

        previous_first_bsp = latest_previous_first_bsp(sorted_bsp_list, bi.idx, target_is_buy)
        return second_bi_feature(
            final_klus,
            pos,
            bi,
            target_is_buy,
            previous_bsp,
            previous_first_bsp,
            parent_context,
            child_level_chan,
    )
    raise ValueError(f"不支持的模型扫描配置：{config.model_name}")


def score_chan_candidates(
    *,
    config: BspProbabilityScanConfig,
    chan,
    code: str,
    parent_dates: List[str],
    parent_context_by_date: Dict[str, Dict[str, float]],
    signal_sides: List[str],
    min_prob: float,
    recent_bars: int,
    thresholds: List[float],
    model_bundles: Dict[str, Tuple[object, Dict[str, int], str]],
) -> List[Dict]:
    level_chan = chan[MODEL_LV_IDX]
    child_level_chan = chan[CHILD_LV_IDX]
    final_klus = list(level_chan.klu_iter())
    decision_time = ctime_to_str(final_klus[-1].time) if final_klus else None
    decision_klu_idx = int(final_klus[-1].idx) if final_klus else -1
    pos_by_idx = {int(klu.idx): pos for pos, klu in enumerate(final_klus)}
    sorted_bsp_list = level_chan.bs_point_lst.getSortedBspList()
    latest_bi_idx = latest_confirmed_bi_idx(level_chan)
    recent_min_klu_idx = None
    if recent_bars > 0 and final_klus:
        recent_min_klu_idx = int(final_klus[max(0, len(final_klus) - recent_bars)].idx)

    rows: List[Dict] = []
    for signal_side in signal_sides:
        target_is_buy = signal_side == "buy"
        model, feature_meta, model_dir = model_bundles[signal_side]
        if config.label_task == "stability":
            bsps = target_bsp_by_key(
                code=code,
                signal_side=signal_side,
                sorted_bsp_list=sorted_bsp_list,
                target_is_buy=target_is_buy,
                target_bsp_types=set(config.target_bsp_types),
            )
            candidates = [
                (bsp.bi, bsp)
                for bsp in sorted(bsps.values(), key=lambda item: int(item.bi.idx))
            ]
        elif config.label_task == "recognition":
            candidates = [
                (bi, None)
                for bi in level_chan.bi_list
                if bi.is_sure and bi_matches_signal_side(bi, target_is_buy)
            ]
        else:
            raise ValueError(f"不支持的 label_task: {config.label_task}")

        for bi, bsp in candidates:

            entry_klu = bi.get_end_klu()
            if recent_min_klu_idx is not None and int(entry_klu.idx) < recent_min_klu_idx:
                continue

            pos = pos_by_idx.get(int(entry_klu.idx))
            if pos is None:
                continue

            entry_date = ctime_to_date_str(entry_klu.time)
            parent_pos = bisect_left(parent_dates, entry_date) - 1
            parent_context = parent_context_by_date[parent_dates[parent_pos]] if parent_pos >= 0 else None
            feature = build_scan_feature(
                config,
                final_klus,
                pos,
                bi,
                target_is_buy,
                sorted_bsp_list,
                parent_context,
                child_level_chan,
            )
            if config.label_task == "stability":
                feature.update(stability_context_feature(
                    final_klus=final_klus,
                    pos=pos,
                    level_chan=level_chan,
                    bi=bi,
                    bsp=bsp,
                    target_is_buy=target_is_buy,
                    sorted_bsp_list=sorted_bsp_list,
                    dependency_bsp_types=set(config.dependency_bsp_types),
                    decision_klu_idx=decision_klu_idx,
                    latest_bi_idx=latest_bi_idx,
                ))
            probability = predict_probability(model, feature_meta, feature)
            feature_snapshot = {
                feature_name: feature.get(feature_name)
                for feature_name in config.feature_names
            }
            row = {
                "model_name": config.model_name,
                "target_group": config.target_group,
                "target_bsp_types": ",".join(config.target_bsp_types),
                "code": code,
                "signal_side": signal_side,
                "open_time": ctime_to_str(entry_klu.time),
                "signal_time": ctime_to_str(entry_klu.time),
                "decision_time": decision_time,
                "bi_idx": int(bi.idx),
                "klu_idx": int(entry_klu.idx),
                "price": float(entry_klu.close),
                "probability": probability,
                "hit_min_prob": probability >= min_prob,
                "feature_snapshot": feature_snapshot,
                "model_dir": model_dir,
            }
            row.update(threshold_hit_fields(probability, thresholds))
            row.update(feature_snapshot)
            rows.append(row)

    rows.sort(key=lambda item: (-float(item["probability"]), item["open_time"], item["code"], item["signal_side"]))
    return rows


def scan_code(
    config: BspProbabilityScanConfig,
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
        model_bundles = load_model_bundles(signal_sides, buy_model_dir, sell_model_dir)
        parent_dates, parent_context_by_date = build_parent_level_context(code, begin_time, end_time)
        chan = build_scan_chan(config, code, begin_time, end_time)
        for _ in chan.step_load():
            pass
        rows = score_chan_candidates(
            config=config,
            chan=chan,
            code=code,
            parent_dates=parent_dates,
            parent_context_by_date=parent_context_by_date,
            signal_sides=signal_sides,
            min_prob=min_prob,
            recent_bars=recent_bars,
            thresholds=thresholds,
            model_bundles=model_bundles,
        )
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


def write_csv(path: Path, rows: List[Dict], thresholds: List[float], feature_names: Tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    threshold_fields = [threshold_field_name(threshold) for threshold in thresholds]
    fieldnames = [
        "model_name",
        "target_group",
        "target_bsp_types",
        "code",
        "signal_side",
        "open_time",
        "signal_time",
        "decision_time",
        "bi_idx",
        "klu_idx",
        "price",
        "probability",
        "hit_min_prob",
        *threshold_fields,
        *feature_names,
        "model_dir",
    ]
    with path.open("w", newline="", encoding="utf-8") as fid:
        writer = csv.DictWriter(fid, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})


def init_scan_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS bsp_probability_scan_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            model_name TEXT NOT NULL,
            target_group TEXT NOT NULL,
            target_bsp_types TEXT NOT NULL,
            dependency_bsp_types TEXT NOT NULL,
            main_bs_type TEXT NOT NULL,
            begin_time TEXT,
            end_time TEXT,
            model_kl_type TEXT NOT NULL,
            parent_kl_type TEXT NOT NULL,
            child_kl_type TEXT NOT NULL,
            signal_sides TEXT NOT NULL,
            min_prob REAL NOT NULL,
            recent_bars INTEGER NOT NULL,
            thresholds TEXT NOT NULL,
            scan_code_count INTEGER NOT NULL,
            success_code_count INTEGER NOT NULL,
            failure_code_count INTEGER NOT NULL,
            candidate_count INTEGER NOT NULL,
            filtered_count INTEGER NOT NULL,
            buy_candidate_count INTEGER NOT NULL,
            sell_candidate_count INTEGER NOT NULL,
            workers INTEGER NOT NULL,
            buy_model_dir TEXT NOT NULL,
            sell_model_dir TEXT NOT NULL,
            output_dir TEXT NOT NULL,
            failures TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bsp_probability_scan_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            model_name TEXT NOT NULL,
            target_group TEXT NOT NULL,
            target_bsp_types TEXT NOT NULL,
            code TEXT NOT NULL,
            signal_side TEXT NOT NULL,
            open_time TEXT NOT NULL,
            signal_time TEXT,
            decision_time TEXT,
            bi_idx INTEGER NOT NULL,
            klu_idx INTEGER NOT NULL,
            price REAL NOT NULL,
            probability REAL NOT NULL,
            hit_min_prob INTEGER NOT NULL,
            threshold_hits TEXT NOT NULL,
            feature_snapshot_json TEXT NOT NULL,
            model_dir TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES bsp_probability_scan_runs(id)
        );

        CREATE INDEX IF NOT EXISTS idx_bsp_prob_runs_created_at
            ON bsp_probability_scan_runs(created_at);
        CREATE INDEX IF NOT EXISTS idx_bsp_prob_runs_model_target
            ON bsp_probability_scan_runs(model_name, target_group);
        CREATE INDEX IF NOT EXISTS idx_bsp_prob_signals_run_id
            ON bsp_probability_scan_signals(run_id);
        CREATE INDEX IF NOT EXISTS idx_bsp_prob_signals_model_target
            ON bsp_probability_scan_signals(model_name, target_group);
        CREATE INDEX IF NOT EXISTS idx_bsp_prob_signals_code
            ON bsp_probability_scan_signals(code);
        CREATE INDEX IF NOT EXISTS idx_bsp_prob_signals_open_time
            ON bsp_probability_scan_signals(open_time);
        CREATE INDEX IF NOT EXISTS idx_bsp_prob_signals_probability
            ON bsp_probability_scan_signals(probability);
        """
    )
    existing_columns = {
        row[1]
        for row in conn.execute(f"PRAGMA table_info(bsp_probability_scan_signals)").fetchall()
    }
    if "signal_time" not in existing_columns:
        conn.execute("ALTER TABLE bsp_probability_scan_signals ADD COLUMN signal_time TEXT")
    if "decision_time" not in existing_columns:
        conn.execute("ALTER TABLE bsp_probability_scan_signals ADD COLUMN decision_time TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bsp_prob_signals_decision_time "
        "ON bsp_probability_scan_signals(decision_time)"
    )
    conn.commit()


def json_safe_feature_snapshot(row: Dict) -> Dict[str, Optional[float]]:
    result = {}
    for key, value in row.get("feature_snapshot", {}).items():
        if value is None:
            result[key] = None
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            result[key] = None
            continue
        if math.isnan(number) or math.isinf(number):
            result[key] = None
        else:
            result[key] = number
    return result


def save_scan_to_db(
    *,
    db_path: Path,
    rows: List[Dict],
    summary: Dict,
    thresholds: List[float],
    output_dir: Path,
    started_at: str,
    finished_at: str,
) -> int:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now().isoformat(timespec="seconds")
    threshold_fields = [threshold_field_name(threshold) for threshold in thresholds]
    with sqlite3.connect(db_path) as conn:
        init_scan_db(conn)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO bsp_probability_scan_runs (
                started_at, finished_at, model_name, target_group,
                target_bsp_types, dependency_bsp_types, main_bs_type,
                begin_time, end_time, model_kl_type, parent_kl_type, child_kl_type,
                signal_sides, min_prob, recent_bars, thresholds,
                scan_code_count, success_code_count, failure_code_count,
                candidate_count, filtered_count, buy_candidate_count, sell_candidate_count,
                workers, buy_model_dir, sell_model_dir, output_dir, failures, summary_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                started_at,
                finished_at,
                summary["model_name"],
                summary["target_group"],
                json.dumps(summary["target_bsp_types"], ensure_ascii=False),
                json.dumps(summary["dependency_bsp_types"], ensure_ascii=False),
                summary["main_bs_type"],
                summary["begin_time"],
                summary["end_time"],
                summary["model_kl_type"],
                summary["parent_kl_type"],
                summary["child_kl_type"],
                json.dumps(summary["signal_sides"], ensure_ascii=False),
                float(summary["min_prob"]),
                int(summary["recent_bars"]),
                json.dumps(summary["thresholds"], ensure_ascii=False),
                int(summary["scan_code_count"]),
                int(summary["success_code_count"]),
                int(summary["failure_code_count"]),
                int(summary["candidate_count"]),
                int(summary["filtered_count"]),
                int(summary["buy_candidate_count"]),
                int(summary["sell_candidate_count"]),
                int(summary["workers"]),
                summary["buy_model_dir"],
                summary["sell_model_dir"],
                str(output_dir),
                json.dumps(summary["failures"], ensure_ascii=False),
                json.dumps(summary, ensure_ascii=False),
                created_at,
            ),
        )
        run_id = int(cursor.lastrowid)
        summary_with_db = {
            **summary,
            "db_path": str(db_path),
            "db_run_id": run_id,
        }
        cursor.execute(
            "UPDATE bsp_probability_scan_runs SET summary_json = ? WHERE id = ?",
            (json.dumps(summary_with_db, ensure_ascii=False), run_id),
        )
        signal_rows = []
        for row in rows:
            threshold_hits = {field: bool(row.get(field)) for field in threshold_fields}
            signal_rows.append((
                run_id,
                row["model_name"],
                row["target_group"],
                row["target_bsp_types"],
                row["code"],
                row["signal_side"],
                row["open_time"],
                row.get("signal_time") or row["open_time"],
                row.get("decision_time") or row["open_time"],
                int(row["bi_idx"]),
                int(row["klu_idx"]),
                float(row["price"]),
                float(row["probability"]),
                int(bool(row["hit_min_prob"])),
                json.dumps(threshold_hits, ensure_ascii=False),
                json.dumps(json_safe_feature_snapshot(row), ensure_ascii=False),
                row["model_dir"],
                created_at,
            ))
        cursor.executemany(
            """
            INSERT INTO bsp_probability_scan_signals (
                run_id, model_name, target_group, target_bsp_types, code, signal_side,
                open_time, signal_time, decision_time, bi_idx, klu_idx, price, probability, hit_min_prob,
                threshold_hits, feature_snapshot_json, model_dir, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            signal_rows,
        )
        conn.commit()
        return run_id


def build_summary(
    *,
    config: BspProbabilityScanConfig,
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
        "model_name": config.model_name,
        "target_group": config.target_group,
        "target_bsp_types": list(config.target_bsp_types),
        "dependency_bsp_types": list(config.dependency_bsp_types),
        "main_bs_type": config.main_bs_type,
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


def parse_args(config: BspProbabilityScanConfig):
    parser = argparse.ArgumentParser(description=config.description)
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
    parser.add_argument("--buy-model-dir", default=str(config.default_buy_model_dir))
    parser.add_argument("--sell-model-dir", default=str(config.default_sell_model_dir))
    parser.add_argument("--output-dir", default=str(config.default_output_dir))
    parser.add_argument("--output", default=None, help="可选：过滤结果 CSV 路径；不传则写入 output-dir/signals_filtered.csv。")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="扫描结果写入的 SQLite 数据库路径。")
    parser.add_argument("--save-db", action=argparse.BooleanOptionalAction, default=True, help="是否保存扫描结果到数据库。")
    return parser.parse_args()


def run_cli(config: BspProbabilityScanConfig) -> None:
    args = parse_args(config)
    if args.recent_bars < 0:
        raise ValueError("--recent-bars 不能小于 0")
    thresholds = parse_thresholds(args.thresholds)
    signal_sides = signal_sides_from_arg(args.signal_side)
    codes = [normalize_cache_code(code) for code in collect_codes(args)]
    worker_count = resolve_workers(args.workers, len(codes))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now().isoformat(timespec="seconds")

    recent_desc = f"最近{args.recent_bars}根30M K线" if args.recent_bars > 0 else "全历史"
    print(
        f"扫描股票数量: {len(codes)}, model={config.model_name}, "
        f"target_group={config.target_group}, signal_side={args.signal_side}, "
        f"recent={recent_desc}, workers={worker_count}"
    )

    rows_by_code: Dict[str, List[Dict]] = {}
    failures: Dict[str, str] = {}
    if worker_count == 1:
        for code in codes:
            _, code_rows, error = scan_code(
                config,
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
                    config,
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
    finished_at = datetime.now().isoformat(timespec="seconds")

    all_csv = output_dir / "signals_all.csv"
    filtered_csv = Path(args.output) if args.output else output_dir / "signals_filtered.csv"
    summary_path = output_dir / "summary.json"
    write_csv(all_csv, rows, thresholds, config.feature_names)
    write_csv(filtered_csv, filtered_rows, thresholds, config.feature_names)

    summary = build_summary(
        config=config,
        args=args,
        codes=codes,
        rows=rows,
        filtered_rows=filtered_rows,
        failures=failures,
        thresholds=thresholds,
        signal_sides=signal_sides,
        worker_count=worker_count,
    )
    if args.save_db:
        db_run_id = save_scan_to_db(
            db_path=Path(args.db_path),
            rows=rows,
            summary=summary,
            thresholds=thresholds,
            output_dir=output_dir,
            started_at=started_at,
            finished_at=finished_at,
        )
        summary["db_path"] = str(Path(args.db_path))
        summary["db_run_id"] = db_run_id
    with summary_path.open("w", encoding="utf-8") as fid:
        json.dump(summary, fid, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"全量结果: {all_csv}")
    print(f"过滤结果: {filtered_csv}")
    print(f"汇总文件: {summary_path}")
    if args.save_db:
        print(f"数据库运行ID: {summary['db_run_id']}")
