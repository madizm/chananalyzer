from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT_DIR / "chan.db"
RUN_TABLE = "scan_runs"
RESULT_TABLE = "scan_results"
SIGNAL_TABLE = "scan_signals"
SEQUENCE_SOURCE = "scan_m30_bsp_sequence"


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


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")}


def _json_loads(value: Any, default):
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _run_select_sql(columns: set[str]) -> str:
    optional_cols = {
        "sequence_json": "sequence_json",
        "max_gap_days": "max_gap_days",
        "bi_mode": "bi_mode",
        "signal_level": "signal_level",
        "ma_period": "ma_period",
    }
    select_parts = [
        "id",
        "source",
        "started_at",
        "finished_at",
        "scanned_count",
        "result_count",
        "buy_types",
        "sell_types",
        "begin_date",
        "end_date",
        "bi_strict",
        "created_at",
    ]
    for col, alias in optional_cols.items():
        select_parts.append(col if col in columns else f"NULL AS {alias}")
    return f"SELECT {', '.join(select_parts)} FROM {RUN_TABLE}"


def _parse_run(row: sqlite3.Row) -> Dict[str, Any]:
    data = dict(row)
    buy_types = _json_loads(data.get("buy_types"), [])
    sell_types = _json_loads(data.get("sell_types"), [])
    sequence = _json_loads(data.get("sequence_json"), [])
    if not sequence:
        # Old scan rows did not store ordered sequence metadata.
        sequence = [*sell_types, *buy_types]
    data["buy_types"] = buy_types
    data["sell_types"] = sell_types
    data["sequence"] = sequence
    data["sequence_text"] = " ".join(str(item) for item in sequence) if sequence else "-"
    data["signal_level"] = data.get("signal_level") or _infer_level_from_types(data)
    data["bi_mode"] = data.get("bi_mode") or "off"
    return data


def _infer_level_from_types(run: Dict[str, Any]) -> str:
    # Existing rows do not carry level. The sequence scanner default is 30M.
    return "30M"


def _empty_payload(message: str) -> Dict[str, Any]:
    return {
        "available": False,
        "message": message,
        "runs": [],
        "selected_run": None,
        "summary": {},
        "results": [],
        "industry_options": [],
        "concept_options": [],
        "stats": {
            "industry_stats": [],
            "concept_stats": [],
        },
        "filters": {},
    }


def list_sequence_runs(limit: int = 20, db_path: Path = DEFAULT_DB_PATH) -> Dict[str, Any]:
    if not db_path.exists():
        return {"available": False, "runs": []}

    with _connect(db_path) as conn:
        if not _table_exists(conn, RUN_TABLE):
            return {"available": False, "runs": []}
        columns = _table_columns(conn, RUN_TABLE)
        rows = conn.execute(
            f"""
            {_run_select_sql(columns)}
            WHERE source=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (SEQUENCE_SOURCE, max(1, min(limit, 100))),
        ).fetchall()
    return {"available": True, "runs": [_parse_run(row) for row in rows]}


def _latest_run_id(conn: sqlite3.Connection) -> Optional[int]:
    row = conn.execute(
        f"SELECT id FROM {RUN_TABLE} WHERE source=? ORDER BY id DESC LIMIT 1",
        (SEQUENCE_SOURCE,),
    ).fetchone()
    return int(row["id"]) if row else None


def _load_run(conn: sqlite3.Connection, run_id: Optional[int]) -> Optional[Dict[str, Any]]:
    selected_id = run_id if run_id is not None else _latest_run_id(conn)
    if selected_id is None:
        return None
    columns = _table_columns(conn, RUN_TABLE)
    row = conn.execute(
        f"""
        {_run_select_sql(columns)}
        WHERE id=? AND source=?
        """,
        (selected_id, SEQUENCE_SOURCE),
    ).fetchone()
    return _parse_run(row) if row else None


def _parse_date_filter(value: Optional[str], is_end: bool = False) -> Optional[datetime]:
    if not value:
        return None
    clean = value.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(clean, fmt)
            if fmt in ("%Y-%m-%d", "%Y/%m/%d") and is_end:
                return parsed + timedelta(days=1) - timedelta(seconds=1)
            return parsed
        except ValueError:
            continue
    raise ValueError(f"invalid date filter: {value}")


def _parse_signal_time(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    clean = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(clean, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(clean)
    except ValueError:
        return None


def _lv_param(period: Optional[str], run_level: Optional[str]) -> str:
    value = (period or run_level or "30M").strip().upper()
    if value in {"DAY", "K_DAY"}:
        return "day"
    if value in {"WEEK", "K_WEEK"}:
        return "week"
    return value.replace("K_", "").lower()


def _chart_url(result: Dict[str, Any], selected_run: Dict[str, Any]) -> str:
    params = {
        "code": result.get("code", ""),
        "lv": _lv_param(result.get("period"), selected_run.get("signal_level")),
        "data_src": "CACHE_DB",
        "x_range": "500",
    }
    if selected_run.get("begin_date"):
        params["begin"] = selected_run["begin_date"]
    if selected_run.get("end_date"):
        params["end"] = selected_run["end_date"]
    return f"/chart?{urlencode(params)}"


def _parse_result(row: sqlite3.Row, selected_run: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(row)
    data["name"] = data.get("name") or data.get("code")
    data["signal_time"] = data.get("signal_time") or data.get("signal_date")
    data["chart_url"] = _chart_url(data, selected_run)
    return data


def _load_results(conn: sqlite3.Connection, selected_run: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = conn.execute(
        f"""
        SELECT
            r.id AS result_id,
            r.run_id,
            r.code,
            r.name,
            r.industry,
            r.area,
            r.latest_price,
            r.change_pct,
            r.signal_time,
            sig.signal_type,
            sig.direction,
            sig.signal_date,
            sig.signal_price,
            sig.period
        FROM {RESULT_TABLE} AS r
        LEFT JOIN {SIGNAL_TABLE} AS sig
            ON sig.id = (
                SELECT id
                FROM {SIGNAL_TABLE}
                WHERE result_id = r.id
                ORDER BY id DESC
                LIMIT 1
            )
        WHERE r.run_id=?
        ORDER BY COALESCE(r.signal_time, sig.signal_date) DESC, r.code ASC
        """,
        (int(selected_run["id"]),),
    ).fetchall()
    return [_parse_result(row, selected_run) for row in rows]


def _attach_concepts(conn: sqlite3.Connection, results: List[Dict[str, Any]]) -> None:
    if not results or not _table_exists(conn, "tdx_concept_sector_stocks") or not _table_exists(conn, "tdx_concept_sectors"):
        for result in results:
            result["concepts"] = []
            result["concept_text"] = ""
        return

    codes = sorted({str(result.get("code") or "") for result in results if result.get("code")})
    concept_by_code: Dict[str, List[Dict[str, str]]] = {code: [] for code in codes}
    for offset in range(0, len(codes), 800):
        batch = codes[offset:offset + 800]
        placeholders = ",".join("?" for _ in batch)
        rows = conn.execute(
            f"""
            SELECT t.code AS stock_code, s.code AS concept_code, s.name AS concept_name
            FROM tdx_concept_sector_stocks AS t
            JOIN tdx_concept_sectors AS s ON s.code = t.sector_code
            WHERE t.code IN ({placeholders})
            ORDER BY s.name, s.code
            """,
            batch,
        ).fetchall()
        for row in rows:
            concept_by_code.setdefault(row["stock_code"], []).append({
                "code": row["concept_code"],
                "name": row["concept_name"],
            })

    for result in results:
        concepts = concept_by_code.get(str(result.get("code") or ""), [])
        result["concepts"] = concepts
        result["concept_text"] = " / ".join(item.get("name") or item.get("code") or "" for item in concepts if item)


def _filter_results(
    results: List[Dict[str, Any]],
    *,
    industry: str,
    concept: str,
    start_date: Optional[str],
    end_date: Optional[str],
) -> List[Dict[str, Any]]:
    start_dt = _parse_date_filter(start_date)
    end_dt = _parse_date_filter(end_date, is_end=True)
    filtered = []
    for result in results:
        result_industry = result.get("industry") or "未分类"
        if industry and industry != "all" and result_industry != industry:
            continue
        if concept and concept != "all":
            concepts = result.get("concepts") or []
            if not any(concept in {item.get("code"), item.get("name")} for item in concepts):
                continue
        signal_dt = _parse_signal_time(result.get("signal_time"))
        if start_dt is not None and (signal_dt is None or signal_dt < start_dt):
            continue
        if end_dt is not None and (signal_dt is None or signal_dt > end_dt):
            continue
        filtered.append(result)
    return filtered


def _industry_options(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, set[str]] = {}
    for result in results:
        industry = result.get("industry") or "未分类"
        code = str(result.get("code") or "")
        grouped.setdefault(industry, set()).add(code)
    return [
        {"industry": industry, "code_count": len(codes)}
        for industry, codes in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
    ]


def _concept_options(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, set[str]] = {}
    name_by_code: Dict[str, str] = {}
    for result in results:
        for concept in result.get("concepts") or []:
            concept_code = concept.get("code") or concept.get("name")
            if not concept_code:
                continue
            name_by_code[concept_code] = concept.get("name") or concept_code
            grouped.setdefault(concept_code, set()).add(result.get("code"))
    return [
        {
            "concept_code": concept_code,
            "concept_name": name_by_code.get(concept_code, concept_code),
            "code_count": len(codes),
        }
        for concept_code, codes in sorted(grouped.items(), key=lambda item: (-len(item[1]), name_by_code.get(item[0], item[0])))
    ]


def _industry_stats(results: List[Dict[str, Any]], limit: int = 12) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for result in results:
        industry = result.get("industry") or "未分类"
        grouped.setdefault(industry, []).append(result)

    rows = []
    for industry, items in grouped.items():
        rows.append({
            "industry": industry,
            "candidate_count": len(items),
            "code_count": len({item.get("code") for item in items}),
        })
    rows.sort(key=lambda item: (-item["candidate_count"], item["industry"]))
    return rows[:limit]


def _concept_stats(results: List[Dict[str, Any]], limit: int = 12) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    concept_name_by_key: Dict[str, str] = {}
    for result in results:
        concepts = result.get("concepts") or []
        if not concepts:
            grouped.setdefault("未分类", []).append(result)
            concept_name_by_key["未分类"] = "未分类"
            continue
        for concept in concepts:
            concept_code = concept.get("code") or concept.get("name") or "未分类"
            concept_name_by_key[concept_code] = concept.get("name") or concept_code
            grouped.setdefault(concept_code, []).append(result)

    rows = []
    for concept_code, items in grouped.items():
        rows.append({
            "concept_code": concept_code,
            "concept_name": concept_name_by_key.get(concept_code, concept_code),
            "candidate_count": len(items),
            "code_count": len({item.get("code") for item in items}),
        })
    rows.sort(key=lambda item: (-item["candidate_count"], item["concept_name"]))
    return rows[:limit]


def _summary(selected_run: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": selected_run.get("id"),
        "started_at": selected_run.get("started_at"),
        "finished_at": selected_run.get("finished_at"),
        "created_at": selected_run.get("created_at"),
        "scanned_count": selected_run.get("scanned_count"),
        "result_count": selected_run.get("result_count"),
        "begin_date": selected_run.get("begin_date"),
        "end_date": selected_run.get("end_date"),
        "sequence": selected_run.get("sequence_text"),
        "signal_level": selected_run.get("signal_level"),
        "max_gap_days": selected_run.get("max_gap_days"),
        "bi_mode": selected_run.get("bi_mode"),
        "bi_strict": bool(selected_run.get("bi_strict")),
    }


def build_sequence_dashboard(
    *,
    run_id: Optional[int] = None,
    industry: str = "all",
    concept: str = "all",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 200,
    db_path: Path = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    if not db_path.exists():
        return _empty_payload("扫描数据库不存在，请先运行 BSP 序列扫描。")

    with _connect(db_path) as conn:
        required_tables = (RUN_TABLE, RESULT_TABLE, SIGNAL_TABLE)
        if not all(_table_exists(conn, table) for table in required_tables):
            return _empty_payload("扫描结果表不存在，请先运行 BSP 序列扫描。")
        selected_run = _load_run(conn, run_id)
        if selected_run is None:
            return _empty_payload("暂无 BSP 序列扫描记录。")
        all_results = _load_results(conn, selected_run)
        _attach_concepts(conn, all_results)
        runs = list_sequence_runs(limit=20, db_path=db_path)["runs"]

    filtered = _filter_results(
        all_results,
        industry=industry,
        concept=concept,
        start_date=start_date,
        end_date=end_date,
    )
    filtered = filtered[:max(1, min(limit, 1000))]
    return {
        "available": True,
        "message": "",
        "runs": runs,
        "selected_run": selected_run,
        "summary": _summary(selected_run),
        "results": filtered,
        "industry_options": _industry_options(all_results),
        "concept_options": _concept_options(all_results),
        "stats": {
            "industry_stats": _industry_stats(all_results),
            "concept_stats": _concept_stats(all_results),
        },
        "filters": {
            "run_id": selected_run["id"],
            "industry": industry,
            "concept": concept,
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit,
        },
    }
