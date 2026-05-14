from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT_BASE = ROOT_DIR / "Debug" / "model_output" / "bsp_probability_scan" / "skill_runs"

KEY_FEATURES = [
    "candidate_divergence_rate",
    "candidate_break_prev_extreme",
    "entry_close_pos",
    "child_close_pos",
    "parent_range",
    "ma_dist_10",
    "prev_bsp_divergence_rate",
    "prev_first_bsp_exists",
    "prev_first_bsp_bi_gap",
    "prev_first_bsp_klu_gap",
    "entry_vs_prev_first_bsp_price",
    "retracement_from_prev_first",
    "prev_first_bsp_divergence_rate",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze specified stocks with Chan 30M BSP probability scanners.")
    parser.add_argument("--codes", required=True, help="Comma-separated stock codes, e.g. 000001,600000 or sz.000001")
    parser.add_argument("--target-group", default="first,second", help="Scan target group: first, second, first,second or all")
    parser.add_argument("--begin-time", default="2026-04-01")
    parser.add_argument("--end-time", default=None)
    parser.add_argument("--signal-side", choices=["buy", "sell", "both"], default="both")
    parser.add_argument("--min-prob", type=float, default=0.60)
    parser.add_argument("--recent-bars", type=int, default=48)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--db-path", default=str(ROOT_DIR / "chan.db"))
    parser.add_argument("--save-db", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as fid:
        return list(csv.DictReader(fid))


def split_stock_tokens(code_text: str) -> List[str]:
    return [item.strip() for item in code_text.split(",") if item.strip()]


def normalize_cache_code(code: str) -> str:
    value = code.strip().lower()
    if len(value) == 9 and value[2] == "." and value[:2] in {"sh", "sz"}:
        return value[3:]
    if len(value) == 9 and value[6] == "." and value[7:] in {"sh", "sz"}:
        return value[:6]
    if len(value) == 8 and value[:2] in {"sh", "sz"}:
        return value[2:]
    return value


def looks_like_stock_code(token: str) -> bool:
    code = normalize_cache_code(token)
    return len(code) == 6 and code.isdigit()


def load_stock_info(db_path: Path) -> Dict[str, Dict[str, str]]:
    if not db_path.exists():
        return {}
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT code, name, industry, area FROM stock_info").fetchall()
    return {
        str(code): {
            "code": str(code),
            "name": name or "",
            "industry": industry or "",
            "area": area or "",
        }
        for code, name, industry, area in rows
    }


def resolve_stock_inputs(code_text: str, db_path: Path) -> Tuple[List[str], Dict[str, Dict[str, str]], List[Dict[str, str]]]:
    """Resolve comma-separated codes or Chinese stock names via stock_info."""
    stock_info = load_stock_info(db_path)
    by_name: Dict[str, List[Dict[str, str]]] = {}
    for info in stock_info.values():
        name = info.get("name", "").strip()
        if name:
            by_name.setdefault(name, []).append(info)

    resolved_codes: List[str] = []
    resolution_rows: List[Dict[str, str]] = []
    unresolved: List[str] = []
    ambiguous: List[str] = []

    for token in split_stock_tokens(code_text):
        if looks_like_stock_code(token):
            code = normalize_cache_code(token)
            info = stock_info.get(code, {"code": code, "name": "", "industry": "", "area": ""})
            resolved_codes.append(code)
            resolution_rows.append({"input": token, **info})
            continue

        matches = by_name.get(token, [])
        if not matches:
            unresolved.append(token)
            continue
        if len(matches) > 1:
            ambiguous.append(f"{token} -> {', '.join(item['code'] for item in matches)}")
            continue
        info = matches[0]
        resolved_codes.append(info["code"])
        resolution_rows.append({"input": token, **info})

    if unresolved or ambiguous:
        details = []
        if unresolved:
            details.append("无法从 stock_info 解析：" + ", ".join(unresolved))
        if ambiguous:
            details.append("名称匹配不唯一：" + "; ".join(ambiguous))
        details.append(f"请确认 {db_path} 的 stock_info 表或改用 6 位股票代码。")
        raise ValueError("；".join(details))

    return resolved_codes, stock_info, resolution_rows


def stock_display(code: str, stock_info: Dict[str, Dict[str, str]]) -> str:
    info = stock_info.get(code, {})
    name = info.get("name")
    return f"{name} `{code}`" if name else f"`{code}`"


def fmt_float(value: object, digits: int = 3, default: str = "-") -> str:
    try:
        if value in (None, ""):
            return default
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return default


def signal_label(side: str) -> str:
    return {"buy": "买点候选", "sell": "卖点候选"}.get(side, side)


def target_label(target_group: str) -> str:
    return {"first": "一类/盘背", "second": "二类"}.get(target_group, target_group or "-")


def summary_target_groups(summary: Dict) -> List[str]:
    groups = summary.get("target_groups")
    if groups:
        return list(groups)
    group = summary.get("target_group")
    return [group] if group else []


def summary_failures(summary: Dict) -> Dict[str, str]:
    failures = dict(summary.get("failures") or {})
    for run in summary.get("runs") or []:
        group = run.get("target_group", "-")
        for code, error in (run.get("failures") or {}).items():
            failures[f"{group}/{code}"] = error
    return failures


def brief_interpret(row: Dict[str, str]) -> str:
    side = row.get("signal_side", "")
    div = row.get("candidate_divergence_rate")
    entry = row.get("entry_close_pos")
    child = row.get("child_close_pos")
    parent_range = row.get("parent_range")
    parts = []
    try:
        div_f = float(div) if div not in (None, "") else None
    except ValueError:
        div_f = None
    if div_f is not None:
        if div_f < 0.8:
            parts.append("力度有衰竭迹象")
        else:
            parts.append("力度衰竭不明显")
    try:
        entry_f = float(entry) if entry not in (None, "") else None
    except ValueError:
        entry_f = None
    if entry_f is not None:
        if side == "buy" and entry_f >= 0.6:
            parts.append("30M收盘位置偏强")
        elif side == "sell" and entry_f <= 0.4:
            parts.append("30M收盘位置偏弱")
        else:
            parts.append("30M确认力度一般")
    try:
        child_f = float(child) if child not in (None, "") else None
    except ValueError:
        child_f = None
    if child_f is not None:
        parts.append("15M有一定配合" if 0.35 <= child_f <= 0.75 else "15M配合需复核")
    try:
        pr_f = float(parent_range) if parent_range not in (None, "") else None
    except ValueError:
        pr_f = None
    if pr_f is not None and pr_f > 0.08:
        parts.append("日线波动偏大")
    if row.get("target_group") == "second":
        if str(row.get("prev_first_bsp_exists", "")).lower() in {"1", "1.0", "true"}:
            parts.append("已关联前序一类")
        retracement = row.get("retracement_from_prev_first")
        if retracement not in (None, ""):
            parts.append(f"二类回撤={fmt_float(retracement, 3)}")
    return "；".join(parts) if parts else "需结合走势图复核"


def build_markdown(
    summary: Dict,
    filtered_rows: List[Dict[str, str]],
    all_rows: List[Dict[str, str]],
    output_dir: Path,
    stock_info: Optional[Dict[str, Dict[str, str]]] = None,
    resolution_rows: Optional[List[Dict[str, str]]] = None,
) -> str:
    rows_for_table = filtered_rows if filtered_rows else all_rows[:10]
    recent_bars = summary.get("recent_bars")
    recent_desc = f"最近 {recent_bars} 根30M K线" if recent_bars else "全历史"
    if filtered_rows:
        conclusion = f"发现 {len(filtered_rows)} 条达到阈值的候选信号。"
    elif all_rows:
        conclusion = f"未发现达到阈值的候选，但存在 {len(all_rows)} 条低于阈值的结构候选，可作弱观察。"
    else:
        conclusion = "未发现近期确认笔候选信号。"

    stock_info = stock_info or {}
    target_groups = summary_target_groups(summary)
    lines = [
        "## 缠论概率扫描结论",
        "",
        f"- 股票数量：{summary.get('scan_code_count', '-')}",
        f"- 区间：{summary.get('begin_time') or '-'} ~ {summary.get('end_time') or '最新缓存'}",
        f"- 范围：{recent_desc}",
        f"- 目标：{', '.join(target_label(group) for group in target_groups) or '-'}",
        f"- 方向：{', '.join(summary.get('signal_sides', []))}",
        f"- 阈值：{summary.get('min_prob')}",
        f"- 结论：{conclusion}",
        "",
    ]
    if resolution_rows:
        lines.extend(["### 股票解析", ""])
        for item in resolution_rows:
            extra = " / ".join(part for part in [item.get("industry", ""), item.get("area", "")] if part)
            suffix = f"（{extra}）" if extra else ""
            lines.append(f"- {item.get('input')} -> {item.get('name') or '-'} `{item.get('code')}`{suffix}")
        lines.append("")

    failures = summary_failures(summary)
    if failures:
        lines.extend(["### 扫描失败", ""])
        for code, error in failures.items():
            lines.append(f"- `{code}`：{error}")
        lines.append("")

    lines.extend([
        "### 候选信号",
        "",
        "| 股票 | 目标 | 方向 | 时间 | 价格 | 概率 | 笔idx | 关键解读 |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | --- |",
    ])
    if rows_for_table:
        for row in rows_for_table:
            lines.append(
                "| {code} | {target} | {side} | {time} | {price} | {prob} | {bi} | {interp} |".format(
                    code=stock_display(row.get("code", "-"), stock_info),
                    target=target_label(row.get("target_group", "-")),
                    side=signal_label(row.get("signal_side", "-")),
                    time=row.get("open_time", "-"),
                    price=fmt_float(row.get("price"), 2),
                    prob=fmt_float(row.get("probability"), 3),
                    bi=row.get("bi_idx", "-"),
                    interp=brief_interpret(row),
                )
            )
    else:
        lines.append("| - | - | - | - | - | - | - | 无候选 |")
    lines.append("")

    if rows_for_table:
        top = rows_for_table[0]
        lines.extend([
            "### 最高分信号关键特征",
            "",
            f"- 股票/目标/方向：{stock_display(top.get('code', '-'), stock_info)} / {target_label(top.get('target_group', '-'))} / {signal_label(top.get('signal_side', '-'))}",
            f"- 概率：{fmt_float(top.get('probability'), 3)}",
        ])
        for name in KEY_FEATURES:
            lines.append(f"- `{name}`：{fmt_float(top.get(name), 4)}")
        lines.append("")

    lines.extend([
        "### 输出文件",
        "",
        f"- 全量候选：`{output_dir / 'signals_all.csv'}`",
        f"- 过滤候选：`{output_dir / 'signals_filtered.csv'}`",
        f"- 汇总：`{output_dir / 'summary.json'}`",
        "",
        "### 使用边界",
        "",
        "该结果是基于缠论结构和历史模型的候选排序，不是交易指令；高概率仍需结合走势图、日线环境、15M 子结构、止损和仓位管理人工复核。",
    ])
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_BASE / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    db_path = Path(args.db_path)
    resolved_codes, stock_info, resolution_rows = resolve_stock_inputs(args.codes, db_path)
    scanner_codes = ",".join(resolved_codes)
    if resolution_rows:
        print("股票解析:")
        for item in resolution_rows:
            print(f"  {item.get('input')} -> {item.get('code')} {item.get('name') or ''}".rstrip())

    cmd = [
        sys.executable,
        str(ROOT_DIR / "Debug" / "scan_bsp_probability.py"),
        "--target-group",
        args.target_group,
        "--codes",
        scanner_codes,
        "--begin-time",
        args.begin_time,
        "--signal-side",
        args.signal_side,
        "--min-prob",
        str(args.min_prob),
        "--recent-bars",
        str(args.recent_bars),
        "--workers",
        str(args.workers),
        "--output-dir",
        str(output_dir),
        "--db-path",
        str(db_path),
    ]
    if args.end_time:
        cmd.extend(["--end-time", args.end_time])
    if not args.save_db:
        cmd.append("--no-save-db")

    result = subprocess.run(cmd, cwd=ROOT_DIR, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if result.returncode != 0:
        return result.returncode

    summary_path = output_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    summary["requested_codes"] = args.codes
    summary["resolved_codes"] = resolved_codes
    summary["stock_resolution"] = resolution_rows
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    filtered_rows = read_csv(output_dir / "signals_filtered.csv")
    all_rows = read_csv(output_dir / "signals_all.csv")
    markdown = build_markdown(summary, filtered_rows, all_rows, output_dir, stock_info, resolution_rows)
    report_path = output_dir / "report.md"
    report_path.write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"\n报告文件: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
