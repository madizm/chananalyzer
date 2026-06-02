from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import sqlite3
from typing import Any

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from Plot.TradingViewDriver import build_tradingview_payload

from .bsp_final_analysis import build_bsp_final_payload
from .bsp_probability import build_bsp_probability_payload
from .bsp_signal_observation import sync_chart_signal_observations
from .chart_params import parse_autype, parse_data_src, parse_lv


DEFAULT_CONFIG = {
    "bi_strict": False,
    "bi_algo": "fx",
    "bi_fx_check": "half",
    "trigger_step": False,
    "skip_step": 0,
    "divergence_rate": float("inf"),
    "min_zs_cnt": 0,
    "bs1_peak": False,
    "macd_algo": "peak",
    "bs_type": "1,2,3a,1p,2s,3b",
    "print_warning": True,
    "zs_algo": "auto",
    "one_bi_zs": False,
    "left_seg_method": "all",
    "bsp2_follow_1": False,
    "bsp3_follow_1": False,
}

DEFAULT_PLOT_CONFIG = {
    "plot_kline": True,
    "plot_kline_combine": True,
    "plot_bi": True,
    "plot_seg": True,
    "plot_eigen": False,
    "plot_zs": True,
    "plot_macd": False,
    "plot_mean": False,
    "plot_channel": False,
    "plot_bsp": True,
    "plot_segbsp": True,
    "plot_extrainfo": False,
    "plot_demark": False,
    "plot_marker": False,
    "plot_rsi": False,
    "plot_kdj": False,
}

_INTRADAY_LEVELS = {
    KL_TYPE.K_1M,
    KL_TYPE.K_3M,
    KL_TYPE.K_5M,
    KL_TYPE.K_15M,
    KL_TYPE.K_30M,
    KL_TYPE.K_60M,
}


@dataclass(frozen=True)
class ChartRequest:
    code: str
    lv: KL_TYPE
    begin: str | None
    end: str | None
    data_src: DATA_SRC | str
    autype: AUTYPE
    x_range: int
    plot_mean: bool

    @property
    def cache_key(self) -> tuple[Any, ...]:
        src_key = self.data_src.name if isinstance(self.data_src, DATA_SRC) else self.data_src
        return (self.code, self.lv.name, self.begin, self.end, src_key, self.autype.name, self.x_range, self.plot_mean)


class PayloadCache:
    def __init__(self, ttl_seconds: int = 180, max_size: int = 64):
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self._store: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}

    def get(self, key: tuple[Any, ...]) -> dict[str, Any] | None:
        item = self._store.get(key)
        if not item:
            return None
        ts, value = item
        if time.time() - ts > self.ttl_seconds:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: tuple[Any, ...], value: dict[str, Any]) -> None:
        if len(self._store) >= self.max_size:
            oldest_key = min(self._store.items(), key=lambda item: item[1][0])[0]
            self._store.pop(oldest_key, None)
        self._store[key] = (time.time(), value)

    def clear(self) -> None:
        self._store.clear()


payload_cache = PayloadCache()


def _clean_stock_code(code: str) -> str:
    return code.strip().upper().split(".")[0]


def _load_stock_info(code: str) -> dict[str, str]:
    db_path = Path(__file__).resolve().parent.parent / "chan.db"
    if not db_path.exists():
        return {}

    clean_code = _clean_stock_code(code)
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name, industry, area FROM stock_info WHERE code = ? LIMIT 1",
                (clean_code,),
            )
            row = cursor.fetchone()
    except sqlite3.Error:
        return {}

    if not row:
        return {}
    name, industry, area = row
    return {
        "name": name or "",
        "industry": industry or "",
        "area": area or "",
    }


def _apply_stock_display(payload: dict[str, Any], req: ChartRequest) -> None:
    stock_info = _load_stock_info(req.code)
    stock_name = stock_info.get("name", "").strip()
    level_name = req.lv.name.split("K_")[-1]
    display_name = f"{stock_name}({req.code})" if stock_name else req.code
    display_title = f"{display_name}/{level_name}"

    payload["stockInfo"] = {
        "code": req.code,
        "name": stock_name,
        "industry": stock_info.get("industry", ""),
        "area": stock_info.get("area", ""),
        "displayName": display_name,
    }
    payload["title"] = display_title
    symbol_info = payload.get("symbolInfo")
    if isinstance(symbol_info, dict):
        symbol_info["description"] = f"{display_name} Chan"
        symbol_info["full_name"] = display_name


def _default_begin(lv: KL_TYPE) -> str:
    today = date.today()
    if lv in _INTRADAY_LEVELS:
        days = 90
    elif lv == KL_TYPE.K_DAY:
        days = 365
    elif lv == KL_TYPE.K_WEEK:
        days = 365 * 3
    else:
        days = 365 * 5
    return (today - timedelta(days=days)).isoformat()


def build_chart_request(
    *,
    code: str,
    lv: str | None = None,
    begin: str | None = None,
    end: str | None = None,
    data_src: str | None = None,
    autype: str | None = None,
    x_range: int = 500,
    plot_mean: bool = False,
) -> ChartRequest:
    parsed_lv = parse_lv(lv)
    clean_code = code.strip()
    if not clean_code:
        raise ValueError("code is required")
    if x_range < 0:
        raise ValueError("x_range must be greater than or equal to 0")
    return ChartRequest(
        code=clean_code,
        lv=parsed_lv,
        begin=begin or _default_begin(parsed_lv),
        end=end or date.today().isoformat(),
        data_src=parse_data_src(data_src),
        autype=parse_autype(autype),
        x_range=x_range,
        plot_mean=plot_mean,
    )


def build_payload(req: ChartRequest, *, use_cache: bool = True) -> dict[str, Any]:
    cache_enabled = use_cache and req.lv != KL_TYPE.K_30M
    if cache_enabled:
        cached = payload_cache.get(req.cache_key)
        if cached is not None:
            return {**cached, "cache": {"hit": True}}

    plot_config = dict(DEFAULT_PLOT_CONFIG)
    plot_config["plot_mean"] = req.plot_mean

    config = CChanConfig(dict(DEFAULT_CONFIG))
    chan = CChan(
        code=req.code,
        begin_time=req.begin,
        end_time=req.end,
        data_src=req.data_src,
        lv_list=[req.lv],
        config=config,
        autype=req.autype,
    )
    payload = build_tradingview_payload(
        chan=chan,
        plot_config=plot_config,
        plot_para={"figure": {"x_range": req.x_range}},
    )
    _apply_stock_display(payload, req)
    payload["request"] = {
        "code": req.code,
        "lv": req.lv.name,
        "begin": req.begin,
        "end": req.end,
        "data_src": req.data_src.name if isinstance(req.data_src, DATA_SRC) else req.data_src,
        "autype": req.autype.name,
        "x_range": req.x_range,
    }
    payload["probabilityMarkers"] = []
    payload["firstProbabilityMarkers"] = []
    payload["secondProbabilityMarkers"] = []
    payload["stabilityMarkers"] = []
    payload["finalMarkers"] = []
    payload["disappearedMarkers"] = []
    payload["signalWarnings"] = []
    try:
        probability_payload = build_bsp_probability_payload(
            code=req.code,
            lv=req.lv,
            begin=req.begin,
            end=req.end,
            bars=payload.get("bars", []),
            visible_range=payload.get("visibleRange"),
        )
        payload["probabilityModel"] = {key: value for key, value in probability_payload.items() if key != "markers"}
        payload["probabilityMarkers"] = probability_payload.get("markers", [])
        payload["stabilityMarkers"] = payload["probabilityMarkers"]
        payload["firstProbabilityMarkers"] = [
            marker for marker in payload["probabilityMarkers"]
            if marker.get("labelGroup") == "first"
        ]
        payload["secondProbabilityMarkers"] = [
            marker for marker in payload["probabilityMarkers"]
            if marker.get("labelGroup") == "second"
        ]
        if payload["firstProbabilityMarkers"]:
            payload["legend"].extend([
                {"label": "一买稳定概率", "color": "#b91c1c"},
                {"label": "一卖稳定概率", "color": "#15803d"},
            ])
        if payload["secondProbabilityMarkers"]:
            payload["legend"].extend([
                {"label": "二买稳定概率", "color": "#b91c1c"},
                {"label": "二卖稳定概率", "color": "#15803d"},
            ])
    except Exception as exc:
        payload["probabilityModel"] = {
            "enabled": req.lv == KL_TYPE.K_30M,
            "status": "error",
            "reason": str(exc),
            "markers": [],
        }

    try:
        final_payload = build_bsp_final_payload(
            code=req.code,
            lv=req.lv,
            begin=req.begin,
            end=req.end,
            bars=payload.get("bars", []),
            visible_range=payload.get("visibleRange"),
        )
        payload["finalAnalysis"] = {key: value for key, value in final_payload.items() if key != "markers"}
        payload["finalMarkers"] = final_payload.get("markers", [])
        if payload["finalMarkers"]:
            payload["legend"].extend([
                {"label": "final确认买点", "color": "#2563eb"},
                {"label": "final确认卖点", "color": "#0f766e"},
            ])
    except Exception as exc:
        payload["finalAnalysis"] = {
            "enabled": req.lv == KL_TYPE.K_30M,
            "status": "error",
            "reason": str(exc),
            "confirmedCount": 0,
        }

    try:
        observation_payload = sync_chart_signal_observations(
            code=req.code,
            level="30M",
            stability_markers=payload.get("stabilityMarkers", []),
            final_markers=payload.get("finalMarkers", []),
            visible_range=payload.get("visibleRange"),
        ) if req.lv == KL_TYPE.K_30M else {
            "status": "skipped",
            "disappearedMarkers": [],
            "signalWarnings": [],
            "activeCount": 0,
            "disappearedCount": 0,
        }
        payload["signalObservation"] = {
            key: value for key, value in observation_payload.items()
            if key not in {"disappearedMarkers", "signalWarnings"}
        }
        payload["disappearedMarkers"] = observation_payload.get("disappearedMarkers", [])
        payload["signalWarnings"] = observation_payload.get("signalWarnings", [])
        if payload["disappearedMarkers"]:
            payload["legend"].append({"label": "消失告警", "color": "#f97316"})
    except Exception as exc:
        payload["signalObservation"] = {
            "status": "error",
            "reason": str(exc),
            "activeCount": 0,
            "disappearedCount": 0,
        }
    payload["cache"] = {"hit": False}

    if cache_enabled:
        payload_cache.set(req.cache_key, payload)
    return payload
