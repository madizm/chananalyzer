from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT_DIR / "chan.db"
OBSERVATION_TABLE = "chart_signal_observations"


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_observation_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {OBSERVATION_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            level TEXT NOT NULL,
            signal_key TEXT NOT NULL,
            label_group TEXT NOT NULL,
            signal_side TEXT NOT NULL,
            target_types TEXT NOT NULL,
            signal_time TEXT NOT NULL,
            signal_ts INTEGER NOT NULL,
            price REAL,
            stability_probability REAL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            last_final_seen_at TEXT,
            status TEXT NOT NULL,
            disappeared_at TEXT,
            warning_level TEXT,
            payload_json TEXT NOT NULL,
            UNIQUE(code, level, signal_key)
        )
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_chart_signal_obs_code_level_status
        ON {OBSERVATION_TABLE}(code, level, status)
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_chart_signal_obs_signal_ts
        ON {OBSERVATION_TABLE}(code, level, signal_ts)
        """
    )


def _visible_filter_sql(visible_range: Optional[Dict[str, int]]) -> tuple[str, list[Any]]:
    if not visible_range:
        return "", []
    clauses = []
    params: list[Any] = []
    visible_from = visible_range.get("from")
    visible_to = visible_range.get("to")
    if visible_from is not None:
        clauses.append("signal_ts >= ?")
        params.append(int(visible_from))
    if visible_to is not None:
        clauses.append("signal_ts <= ?")
        params.append(int(visible_to))
    return (" AND " + " AND ".join(clauses)) if clauses else "", params


def _warning_level(probability: Optional[float]) -> str:
    if probability is None:
        return "medium"
    if probability >= 0.75:
        return "high"
    if probability >= 0.60:
        return "medium"
    return "low"


def _disappeared_marker(row: sqlite3.Row) -> Dict[str, Any]:
    payload = json.loads(row["payload_json"] or "{}")
    probability = row["stability_probability"]
    warning_level = _warning_level(float(probability) if probability is not None else None)
    side_prefix = "B" if row["signal_side"] == "buy" else "S"
    group_suffix = "1" if row["label_group"] == "first" else "2"
    payload.update({
        "status": "disappeared",
        "warningLevel": warning_level,
        "color": "#f97316" if warning_level != "high" else "#dc2626",
        "badge": f"失{side_prefix}{group_suffix}",
        "labelMode": "disappeared",
        "labelSource": "chart_observation",
        "tooltip": (
            f"{row['target_types']} {row['signal_side']} 信号已消失; "
            f"首次出现={row['first_seen_at']}; final未确认"
        ),
    })
    return payload


def _warning_from_marker(marker: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "level": marker.get("warningLevel") or "medium",
        "signalKey": marker.get("signalKey"),
        "labelGroup": marker.get("labelGroup"),
        "signalSide": marker.get("signalSide"),
        "targetTypes": marker.get("targetTypes"),
        "signalTime": marker.get("signalTime"),
        "message": "历史信号在当前 final 结构中消失",
    }


def sync_chart_signal_observations(
    *,
    code: str,
    level: str,
    stability_markers: List[Dict[str, Any]],
    final_markers: List[Dict[str, Any]],
    visible_range: Optional[Dict[str, int]],
    db_path: Path = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    stability_by_key = {
        marker.get("signalKey"): marker
        for marker in stability_markers
        if marker.get("signalKey")
    }
    current_by_key: Dict[str, Dict[str, Any]] = {}
    for marker in final_markers:
        signal_key = marker.get("signalKey")
        if not signal_key:
            continue
        merged = dict(marker)
        stability_marker = stability_by_key.get(signal_key)
        if stability_marker:
            merged["stabilityProbability"] = stability_marker.get("stabilityProbability", stability_marker.get("probability"))
            merged["stabilityBadge"] = stability_marker.get("badge")
            merged["stabilityModelDir"] = stability_marker.get("modelDir")
        current_by_key[signal_key] = merged

    visible_sql, visible_params = _visible_filter_sql(visible_range)
    disappeared_markers: List[Dict[str, Any]] = []
    normalized_code = str(code).strip().upper().split(".")[0]
    normalized_level = str(level).strip().upper()

    conn = _connect(db_path)
    try:
        ensure_observation_table(conn)
        previous_rows = conn.execute(
            f"""
            SELECT *
            FROM {OBSERVATION_TABLE}
            WHERE code = ? AND level = ? AND status IN ('active', 'final_confirmed')
            {visible_sql}
            """,
            [normalized_code, normalized_level, *visible_params],
        ).fetchall()

        current_keys = set(current_by_key)
        disappeared_keys = [
            row["signal_key"]
            for row in previous_rows
            if row["signal_key"] not in current_keys
        ]
        if disappeared_keys:
            placeholders = ",".join("?" for _ in disappeared_keys)
            conn.execute(
                f"""
                UPDATE {OBSERVATION_TABLE}
                SET status = 'disappeared',
                    disappeared_at = ?,
                    warning_level = COALESCE(warning_level, 'medium')
                WHERE code = ? AND level = ? AND signal_key IN ({placeholders})
                """,
                [now, normalized_code, normalized_level, *disappeared_keys],
            )
            rows = conn.execute(
                f"""
                SELECT *
                FROM {OBSERVATION_TABLE}
                WHERE code = ? AND level = ? AND signal_key IN ({placeholders})
                ORDER BY signal_ts, signal_side
                """,
                [normalized_code, normalized_level, *disappeared_keys],
            ).fetchall()
            disappeared_markers = [_disappeared_marker(row) for row in rows]

        for signal_key, marker in current_by_key.items():
            stability_probability = marker.get("stabilityProbability")
            conn.execute(
                f"""
                INSERT INTO {OBSERVATION_TABLE} (
                    code, level, signal_key, label_group, signal_side, target_types,
                    signal_time, signal_ts, price, stability_probability,
                    first_seen_at, last_seen_at, last_final_seen_at,
                    status, disappeared_at, warning_level, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'final_confirmed', NULL, NULL, ?)
                ON CONFLICT(code, level, signal_key) DO UPDATE SET
                    label_group = excluded.label_group,
                    signal_side = excluded.signal_side,
                    target_types = excluded.target_types,
                    signal_time = excluded.signal_time,
                    signal_ts = excluded.signal_ts,
                    price = excluded.price,
                    stability_probability = excluded.stability_probability,
                    last_seen_at = excluded.last_seen_at,
                    last_final_seen_at = excluded.last_final_seen_at,
                    status = 'final_confirmed',
                    disappeared_at = NULL,
                    warning_level = NULL,
                    payload_json = excluded.payload_json
                """,
                (
                    normalized_code,
                    normalized_level,
                    signal_key,
                    marker.get("labelGroup") or "",
                    marker.get("signalSide") or "",
                    marker.get("targetTypes") or "",
                    marker.get("signalTime") or "",
                    int(marker.get("time") or 0),
                    marker.get("price"),
                    stability_probability,
                    now,
                    now,
                    now,
                    json.dumps(marker, ensure_ascii=False),
                ),
            )
        conn.commit()
    finally:
        conn.close()

    return {
        "status": "ok",
        "activeCount": len(current_by_key),
        "disappearedCount": len(disappeared_markers),
        "disappearedMarkers": disappeared_markers,
        "signalWarnings": [_warning_from_marker(marker) for marker in disappeared_markers],
    }
