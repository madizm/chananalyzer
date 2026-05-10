from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT_DIR / "chan.db"
RUN_TABLE = "demo8_bsp_probability_scan_runs"
SIGNAL_TABLE = "demo8_bsp_probability_scan_signals"
TOP_INDUSTRY_LIMIT = 10


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _json_loads(value: Any, default):
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _row_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return dict(row)


def _parse_run(row: sqlite3.Row) -> Dict[str, Any]:
    data = _row_dict(row)
    data["signal_sides"] = _json_loads(data.get("signal_sides"), [])
    data["thresholds"] = _json_loads(data.get("thresholds"), [])
    data["failures"] = _json_loads(data.get("failures"), {})
    data["summary"] = _json_loads(data.get("summary_json"), {})
    data.pop("summary_json", None)
    return data


def _parse_signal(row: sqlite3.Row) -> Dict[str, Any]:
    data = _row_dict(row)
    data["hit_min_prob"] = bool(data.get("hit_min_prob"))
    data["threshold_hits"] = _json_loads(data.get("threshold_hits"), {})
    data["name"] = data.get("name") or data.get("code")
    data["chart_url"] = _chart_url(data)
    return data


def _chart_url(signal: Dict[str, Any]) -> str:
    open_time = str(signal.get("open_time") or "")
    begin = ""
    end = ""
    try:
        open_dt = datetime.strptime(open_time, "%Y/%m/%d %H:%M")
        begin = (open_dt - timedelta(days=20)).date().isoformat()
        end = (open_dt + timedelta(days=5)).date().isoformat()
    except ValueError:
        pass
    params = {
        "code": signal.get("code", ""),
        "lv": "30m",
        "data_src": "CACHE_DB",
        "x_range": "160",
    }
    if begin:
        params["begin"] = begin
    if end:
        params["end"] = end
    return f"/chart?{urlencode(params)}"


def _empty_payload(message: str) -> Dict[str, Any]:
    return {
        "available": False,
        "message": message,
        "runs": [],
        "selected_run": None,
        "summary": {},
        "signals": [],
        "stats": {
            "probability_distribution": [],
            "side_stats": [],
            "industry_stats": [],
        },
    }


def list_signal_runs(limit: int = 20, db_path: Path = DEFAULT_DB_PATH) -> Dict[str, Any]:
    if not db_path.exists():
        return {"available": False, "runs": []}
    with _connect(db_path) as conn:
        if not _table_exists(conn, RUN_TABLE):
            return {"available": False, "runs": []}
        rows = conn.execute(
            f"""
            SELECT id, started_at, finished_at, begin_time, end_time, min_prob, recent_bars,
                   scan_code_count, success_code_count, failure_code_count,
                   candidate_count, filtered_count, buy_candidate_count, sell_candidate_count,
                   created_at
            FROM {RUN_TABLE}
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, min(limit, 100)),),
        ).fetchall()
    return {"available": True, "runs": [_row_dict(row) for row in rows]}


def _latest_run_id(conn: sqlite3.Connection) -> Optional[int]:
    row = conn.execute(f"SELECT id FROM {RUN_TABLE} ORDER BY id DESC LIMIT 1").fetchone()
    return int(row["id"]) if row else None


def _load_run(conn: sqlite3.Connection, run_id: Optional[int]) -> Optional[Dict[str, Any]]:
    selected_id = run_id if run_id is not None else _latest_run_id(conn)
    if selected_id is None:
        return None
    row = conn.execute(f"SELECT * FROM {RUN_TABLE} WHERE id=?", (selected_id,)).fetchone()
    return _parse_run(row) if row else None


def _load_signals(conn: sqlite3.Connection, run_id: int) -> List[Dict[str, Any]]:
    if not _table_exists(conn, "stock_info"):
        rows = conn.execute(
            f"""
            SELECT *
            FROM {SIGNAL_TABLE}
            WHERE run_id=?
            ORDER BY probability DESC, open_time DESC, code ASC, signal_side ASC
            """,
            (run_id,),
        ).fetchall()
        return [_parse_signal(row) for row in rows]

    rows = conn.execute(
        f"""
        SELECT s.*, i.name, i.industry, i.area
        FROM {SIGNAL_TABLE} AS s
        LEFT JOIN stock_info AS i ON i.code = s.code
        WHERE s.run_id=?
        ORDER BY s.probability DESC, s.open_time DESC, s.code ASC, s.signal_side ASC
        """,
        (run_id,),
    ).fetchall()
    return [_parse_signal(row) for row in rows]


def _distribution(signals: List[Dict[str, Any]], min_prob: float) -> List[Dict[str, Any]]:
    buckets = [
        {
            "bucket": f"{idx / 10:.1f}-{(idx + 1) / 10:.1f}",
            "count": 0,
            "side_stats": [],
            "industry_stats": [],
            "_signals": [],
        }
        for idx in range(10)
    ]
    for signal in signals:
        probability = float(signal.get("probability") or 0.0)
        idx = max(0, min(9, int(probability * 10)))
        buckets[idx]["count"] += 1
        buckets[idx]["_signals"].append(signal)
    for bucket in buckets:
        bucket["side_stats"] = _side_stats(bucket["_signals"], min_prob)
        bucket["industry_stats"] = _industry_stats(bucket["_signals"])
        bucket.pop("_signals", None)
    return buckets


def _side_stats(signals: List[Dict[str, Any]], min_prob: float) -> List[Dict[str, Any]]:
    rows = []
    for side in ("buy", "sell"):
        items = [signal for signal in signals if signal.get("signal_side") == side]
        high_items = [signal for signal in items if float(signal.get("probability") or 0.0) >= min_prob]
        rows.append({
            "signal_side": side,
            "candidate_count": len(items),
            "high_score_count": len(high_items),
            "avg_probability": sum(float(item.get("probability") or 0.0) for item in items) / len(items) if items else None,
            "max_probability": max((float(item.get("probability") or 0.0) for item in items), default=None),
            "code_count": len({item.get("code") for item in items}),
        })
    return rows


def _industry_stats(signals: List[Dict[str, Any]], limit: int = TOP_INDUSTRY_LIMIT) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for signal in signals:
        industry = signal.get("industry") or "未分类"
        grouped.setdefault(industry, []).append(signal)
    rows = []
    for industry, items in grouped.items():
        rows.append({
            "industry": industry,
            "candidate_count": len(items),
            "buy_count": sum(1 for item in items if item.get("signal_side") == "buy"),
            "sell_count": sum(1 for item in items if item.get("signal_side") == "sell"),
            "code_count": len({item.get("code") for item in items}),
            "avg_probability": sum(float(item.get("probability") or 0.0) for item in items) / len(items) if items else None,
            "max_probability": max((float(item.get("probability") or 0.0) for item in items), default=None),
        })
    rows.sort(key=lambda item: (-item["candidate_count"], -(item["avg_probability"] or 0.0), item["industry"]))
    return rows[:limit]


def _industry_options(signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, set] = {}
    for signal in signals:
        industry = signal.get("industry") or "未分类"
        grouped.setdefault(industry, set()).add(signal.get("code"))
    return [
        {"industry": industry, "code_count": len(codes)}
        for industry, codes in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
    ]


def _parse_date_filter(value: Optional[str], is_end: bool = False) -> Optional[datetime]:
    if not value:
        return None
    clean = value.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            parsed = datetime.strptime(clean, fmt)
            if fmt in ("%Y-%m-%d", "%Y/%m/%d") and is_end:
                return parsed + timedelta(days=1) - timedelta(seconds=1)
            return parsed
        except ValueError:
            continue
    raise ValueError(f"invalid date filter: {value}")


def _signal_time(signal: Dict[str, Any]) -> Optional[datetime]:
    try:
        return datetime.strptime(str(signal.get("open_time") or ""), "%Y/%m/%d %H:%M")
    except ValueError:
        return None


def _filter_signals(
    signals: List[Dict[str, Any]],
    *,
    side: str,
    min_prob: float,
    industry: str,
    start_date: Optional[str],
    end_date: Optional[str],
) -> List[Dict[str, Any]]:
    start_dt = _parse_date_filter(start_date)
    end_dt = _parse_date_filter(end_date, is_end=True)
    filtered = []
    for signal in signals:
        if side != "both" and signal.get("signal_side") != side:
            continue
        if industry and industry != "all" and (signal.get("industry") or "未分类") != industry:
            continue
        if float(signal.get("probability") or 0.0) < min_prob:
            continue
        open_dt = _signal_time(signal)
        if start_dt is not None and (open_dt is None or open_dt < start_dt):
            continue
        if end_dt is not None and (open_dt is None or open_dt > end_dt):
            continue
        filtered.append(signal)
    return filtered


def build_signal_dashboard(
    *,
    run_id: Optional[int] = None,
    min_prob: float = 0.60,
    side: str = "both",
    industry: str = "all",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 200,
    db_path: Path = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    if not db_path.exists():
        return _empty_payload("扫描数据库不存在，请先运行模型扫描。")

    with _connect(db_path) as conn:
        if not _table_exists(conn, RUN_TABLE) or not _table_exists(conn, SIGNAL_TABLE):
            return _empty_payload("扫描结果表不存在，请先运行模型扫描。")
        selected_run = _load_run(conn, run_id)
        if selected_run is None:
            return _empty_payload("暂无扫描记录。")
        all_signals = _load_signals(conn, int(selected_run["id"]))
        runs = list_signal_runs(limit=20, db_path=db_path)["runs"]

    filtered = _filter_signals(
        all_signals,
        side=side,
        min_prob=min_prob,
        industry=industry,
        start_date=start_date,
        end_date=end_date,
    )
    filtered = filtered[:max(1, min(limit, 1000))]
    return {
        "available": True,
        "message": "",
        "runs": runs,
        "selected_run": selected_run,
        "summary": selected_run.get("summary") or selected_run,
        "signals": filtered,
        "stats": {
            "probability_distribution": _distribution(all_signals, min_prob),
            "side_stats": _side_stats(all_signals, min_prob),
            "industry_stats": _industry_stats(all_signals),
        },
        "industry_options": _industry_options(all_signals),
        "filters": {
            "run_id": selected_run["id"],
            "min_prob": min_prob,
            "side": side,
            "industry": industry,
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit,
        },
    }
