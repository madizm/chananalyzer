from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Tuple

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Debug.bsp_probability_scan_common import (
    DEFAULT_DB_PATH,
    BspProbabilityScanConfig,
    build_summary,
    collect_codes,
    parse_thresholds,
    resolve_workers,
    save_scan_to_db,
    scan_code,
    signal_sides_from_arg,
    write_csv,
)
from Debug.scan_demo8_bsp_probability import CONFIG as FIRST_CONFIG
from Debug.scan_demo9_bsp_probability import CONFIG as SECOND_CONFIG
from Debug.strategy_demo7 import normalize_cache_code


CONFIG_BY_TARGET_GROUP: Dict[str, BspProbabilityScanConfig] = {
    FIRST_CONFIG.target_group: FIRST_CONFIG,
    SECOND_CONFIG.target_group: SECOND_CONFIG,
}
DEFAULT_OUTPUT_DIR = ROOT_DIR / "Debug" / "model_output" / "bsp_probability_scan"


def parse_target_groups(value: str) -> List[str]:
    if value.strip().lower() == "all":
        return list(CONFIG_BY_TARGET_GROUP)
    groups = []
    for item in value.split(","):
        group = item.strip().lower()
        if not group:
            continue
        if group not in CONFIG_BY_TARGET_GROUP:
            raise ValueError(f"不支持的 target group: {group}")
        if group not in groups:
            groups.append(group)
    if not groups:
        raise ValueError("--target-group 至少需要一个目标组")
    return groups


def parse_args():
    parser = argparse.ArgumentParser(description="统一扫描30M确认笔的一类/二类买卖点模型概率。")
    parser.add_argument("--target-group", default="first,second", help="扫描目标组：first、second、first,second 或 all。")
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
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="扫描结果写入的 SQLite 数据库路径。")
    parser.add_argument("--save-db", action=argparse.BooleanOptionalAction, default=True, help="是否保存扫描结果到数据库。")
    return parser.parse_args()


def make_summary_args(args, buy_model_dir: Path, sell_model_dir: Path):
    return SimpleNamespace(
        begin_time=args.begin_time,
        end_time=args.end_time,
        min_prob=args.min_prob,
        recent_bars=args.recent_bars,
        buy_model_dir=str(buy_model_dir),
        sell_model_dir=str(sell_model_dir),
    )


def scan_config(
    *,
    config: BspProbabilityScanConfig,
    args,
    codes: List[str],
    signal_sides: List[str],
    thresholds: List[float],
    worker_count: int,
    output_dir: Path,
) -> Tuple[Dict, List[Dict]]:
    buy_model_dir = config.default_buy_model_dir
    sell_model_dir = config.default_sell_model_dir
    started_at = datetime.now().isoformat(timespec="seconds")
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
                str(buy_model_dir),
                str(sell_model_dir),
            )
            if error:
                failures[code] = error
                print(f"{config.target_group}/{code}: 扫描失败，已跳过：{error}")
                continue
            rows_by_code[code] = code_rows
            print(f"{config.target_group}/{code}: 候选 {len(code_rows)}")
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
                    str(buy_model_dir),
                    str(sell_model_dir),
                ): code
                for code in codes
            }
            for future in as_completed(future_to_code):
                code = future_to_code[future]
                _, code_rows, error = future.result()
                if error:
                    failures[code] = error
                    print(f"{config.target_group}/{code}: 扫描失败，已跳过：{error}")
                    continue
                rows_by_code[code] = code_rows
                print(f"{config.target_group}/{code}: 候选 {len(code_rows)}")

    rows: List[Dict] = []
    for code in codes:
        rows.extend(rows_by_code.get(code, []))
    rows.sort(key=lambda item: (-float(item["probability"]), item["open_time"], item["code"], item["signal_side"]))
    filtered_rows = [row for row in rows if float(row["probability"]) >= args.min_prob]
    finished_at = datetime.now().isoformat(timespec="seconds")

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "signals_all.csv", rows, thresholds, config.feature_names)
    write_csv(output_dir / "signals_filtered.csv", filtered_rows, thresholds, config.feature_names)

    summary = build_summary(
        config=config,
        args=make_summary_args(args, buy_model_dir, sell_model_dir),
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
    with (output_dir / "summary.json").open("w", encoding="utf-8") as fid:
        json.dump(summary, fid, ensure_ascii=False, indent=2)
    return summary, rows


def main() -> None:
    args = parse_args()
    if args.recent_bars < 0:
        raise ValueError("--recent-bars 不能小于 0")
    target_groups = parse_target_groups(args.target_group)
    thresholds = parse_thresholds(args.thresholds)
    signal_sides = signal_sides_from_arg(args.signal_side)
    codes = [normalize_cache_code(code) for code in collect_codes(args)]
    worker_count = resolve_workers(args.workers, len(codes))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    recent_desc = f"最近{args.recent_bars}根30M K线" if args.recent_bars > 0 else "全历史"
    print(
        f"统一扫描股票数量: {len(codes)}, target_groups={target_groups}, "
        f"signal_side={args.signal_side}, recent={recent_desc}, workers={worker_count}"
    )

    summaries = []
    all_rows: List[Dict] = []
    feature_names = []
    for target_group in target_groups:
        config = CONFIG_BY_TARGET_GROUP[target_group]
        for feature_name in config.feature_names:
            if feature_name not in feature_names:
                feature_names.append(feature_name)
        summary, rows = scan_config(
            config=config,
            args=args,
            codes=codes,
            signal_sides=signal_sides,
            thresholds=thresholds,
            worker_count=worker_count,
            output_dir=output_dir / target_group,
        )
        summaries.append(summary)
        all_rows.extend(rows)

    all_rows.sort(key=lambda item: (-float(item["probability"]), item["target_group"], item["open_time"], item["code"], item["signal_side"]))
    filtered_rows = [row for row in all_rows if float(row["probability"]) >= args.min_prob]
    write_csv(output_dir / "signals_all.csv", all_rows, thresholds, tuple(feature_names))
    write_csv(output_dir / "signals_filtered.csv", filtered_rows, thresholds, tuple(feature_names))

    summary = {
        "target_groups": target_groups,
        "begin_time": args.begin_time,
        "end_time": args.end_time,
        "signal_sides": signal_sides,
        "min_prob": args.min_prob,
        "recent_bars": args.recent_bars,
        "thresholds": thresholds,
        "scan_code_count": len(codes),
        "candidate_count": len(all_rows),
        "filtered_count": len(filtered_rows),
        "runs": summaries,
    }
    with (output_dir / "summary.json").open("w", encoding="utf-8") as fid:
        json.dump(summary, fid, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"合并全量结果: {output_dir / 'signals_all.csv'}")
    print(f"合并过滤结果: {output_dir / 'signals_filtered.csv'}")
    print(f"合并汇总文件: {output_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
