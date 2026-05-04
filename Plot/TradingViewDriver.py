import html
import json
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Tuple, Union

from Chan import CChan
from Common.CEnum import DATA_FIELD, FX_TYPE, KL_TYPE, KLINE_DIR, TREND_TYPE
from Common.CTime import CTime

from .PlotDriver import GetPlotMeta, cal_x_limit, parse_plot_config
from .PlotMeta import CChanPlotMeta


class CTradingViewDriver:
    RESOLUTION_MAP = {
        KL_TYPE.K_1M: "1",
        KL_TYPE.K_3M: "3",
        KL_TYPE.K_5M: "5",
        KL_TYPE.K_15M: "15",
        KL_TYPE.K_30M: "30",
        KL_TYPE.K_60M: "60",
        KL_TYPE.K_DAY: "1D",
        KL_TYPE.K_WEEK: "1W",
        KL_TYPE.K_MON: "1M",
        KL_TYPE.K_QUARTER: "3M",
        KL_TYPE.K_YEAR: "12M",
    }

    BAR_SPAN_SECONDS = {
        KL_TYPE.K_1M: 60,
        KL_TYPE.K_3M: 180,
        KL_TYPE.K_5M: 300,
        KL_TYPE.K_15M: 900,
        KL_TYPE.K_30M: 1800,
        KL_TYPE.K_60M: 3600,
        KL_TYPE.K_DAY: 86400,
        KL_TYPE.K_WEEK: 86400 * 7,
        KL_TYPE.K_MON: 86400 * 30,
        KL_TYPE.K_QUARTER: 86400 * 90,
        KL_TYPE.K_YEAR: 86400 * 365,
    }

    KLC_STYLE = {
        FX_TYPE.TOP: {"color": "#ef4444", "background": "#fee2e2", "label": "顶分型合并K线"},
        FX_TYPE.BOTTOM: {"color": "#2563eb", "background": "#dbeafe", "label": "底分型合并K线"},
        KLINE_DIR.UP: {"color": "#16a34a", "background": "#dcfce7", "label": "上涨合并K线"},
        KLINE_DIR.DOWN: {"color": "#16a34a", "background": "#dcfce7", "label": "下跌合并K线"},
        KLINE_DIR.COMBINE: {"color": "#7c3aed", "background": "#ede9fe", "label": "包含关系合并K线"},
        KLINE_DIR.INCLUDED: {"color": "#7c3aed", "background": "#ede9fe", "label": "包含关系合并K线"},
    }

    def __init__(self, chan: CChan, plot_config: Union[str, dict, list] = '', plot_para=None):
        if plot_para is None:
            plot_para = {}
        self.chan = chan
        self.plot_para = plot_para
        self.figure_config = plot_para.get('figure', {})
        self.plot_config: Dict[KL_TYPE, Dict[str, bool]] = parse_plot_config(plot_config, chan.lv_list)
        self.meta = GetPlotMeta(chan, {**self.figure_config, "only_top_lv": True})[0]
        self.lv = chan.lv_list[0]
        self.x_limits = cal_x_limit(self.meta, self._get_real_xrange(self.meta))
        self.charting_library_dir = Path(__file__).resolve().parent.parent / "charting_library" / "charting_library"
        self.payload = self._build_payload()

    def save_html(self, path):
        output_path = Path(path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(self._render_html(output_path), encoding="utf-8")

    def _get_real_xrange(self, meta: CChanPlotMeta):
        x_range = self.figure_config.get("x_range", 0)
        bi_cnt = self.figure_config.get("x_bi_cnt", 0)
        seg_cnt = self.figure_config.get("x_seg_cnt", 0)
        x_begin_date = self.figure_config.get("x_begin_date", 0)
        if x_range != 0:
            assert bi_cnt == 0 and seg_cnt == 0 and x_begin_date == 0, "x_range/x_bi_cnt/x_seg_cnt/x_begin_date can not be set at the same time"
            return x_range
        if bi_cnt != 0:
            assert seg_cnt == 0 and x_begin_date == 0, "x_range/x_bi_cnt/x_seg_cnt/x_begin_date can not be set at the same time"
            if len(meta.bi_list) < bi_cnt:
                return 0
            return meta.klu_len-meta.bi_list[-bi_cnt].begin_x
        if seg_cnt != 0:
            assert x_begin_date == 0, "x_range/x_bi_cnt/x_seg_cnt/x_begin_date can not be set at the same time"
            if len(meta.seg_list) < seg_cnt:
                return 0
            return meta.klu_len-meta.seg_list[-seg_cnt].begin_x
        if x_begin_date != 0:
            x_range = 0
            for date_tick in meta.datetick[::-1]:
                if date_tick >= x_begin_date:
                    x_range += 1
                else:
                    break
            return x_range
        return x_range

    def _time_at(self, idx: int):
        return self._times[idx]

    @staticmethod
    def _calc_precision(values: List[float]):
        precision = 0
        for value in values:
            try:
                decimal_value = Decimal(str(value)).normalize()
            except (InvalidOperation, ValueError):
                continue
            precision = max(precision, max(0, -decimal_value.as_tuple().exponent))
        return min(precision, 8)

    def _resolution(self):
        return self.RESOLUTION_MAP.get(self.lv, "1D")

    def _default_bar_span(self):
        return self.BAR_SPAN_SECONDS.get(self.lv, 86400)

    def _bar_time_bounds(self, idx: int) -> Tuple[int, int]:
        cur = self._times[idx]
        if len(self._times) == 1:
            half = max(1, self._default_bar_span() // 2)
            return cur - half, cur + half

        prev_time = self._times[idx - 1] if idx > 0 else None
        next_time = self._times[idx + 1] if idx < len(self._times) - 1 else None

        if prev_time is not None:
            left_half = max(1, (cur - prev_time) // 2)
        elif next_time is not None:
            left_half = max(1, (next_time - cur) // 2)
        else:
            left_half = max(1, self._default_bar_span() // 2)

        if next_time is not None:
            right_half = max(1, (next_time - cur) // 2)
        elif prev_time is not None:
            right_half = max(1, (cur - prev_time) // 2)
        else:
            right_half = max(1, self._default_bar_span() // 2)

        return cur - left_half, cur + right_half

    def _bar_span_at(self, idx: int):
        left, right = self._bar_time_bounds(idx)
        return max(1, right - left)

    def _build_payload(self):
        conf = self.plot_config[self.lv]
        klu_list = list(self.meta.klu_iter())
        x_begin, x_end = self.x_limits

        self._times = []
        bars = []
        price_values: List[float] = []
        volume_values: List[float] = []
        for klu in klu_list:
            time = int(klu.time.ts)
            volume = klu.trade_info.metric.get(DATA_FIELD.FIELD_VOLUME)
            volume_float = float(volume) if volume is not None else None
            self._times.append(time)
            bars.append({
                "time": time,
                "index": klu.idx,
                "open": float(klu.open),
                "high": float(klu.high),
                "low": float(klu.low),
                "close": float(klu.close),
                "volume": volume_float,
                "rawTime": klu.time.to_str(),
            })
            price_values.extend([float(klu.open), float(klu.high), float(klu.low), float(klu.close)])
            if volume_float is not None:
                volume_values.append(volume_float)

        min_price = min(float(klu.low) for klu in klu_list)
        max_price = max(float(klu.high) for klu in klu_list)
        price_span = max(max_price - min_price, max(abs(max_price), 1.0) * 0.03)
        resolution = self._resolution()
        has_volume = any(bar["volume"] is not None for bar in bars)
        pricescale = 10 ** self._calc_precision(price_values)
        volume_precision = self._calc_precision(volume_values)
        plot_single_klc = self.plot_para.get("klc", {}).get("plot_single_kl", False)

        payload = {
            "title": f"{self.chan.code}/{self.lv.name.split('K_')[-1]}",
            "symbol": self.chan.code,
            "resolution": resolution,
            "timezone": "Asia/Shanghai",
            "legend": self._build_legend(conf),
            "symbolInfo": self._build_symbol_info(resolution, pricescale, volume_precision, has_volume),
            "bars": bars,
            "visibleRange": {
                "from": self._time_at(x_begin),
                "to": self._time_at(x_end),
            },
            "klc": self._klc_ranges(plot_single_klc) if conf.get("plot_kline_combine", False) else [],
            "bi": self._lines(self.meta.bi_list) if conf.get("plot_bi", False) else [],
            "seg": self._lines(self.meta.seg_list) if conf.get("plot_seg", False) else [],
            "zs": self._zs_list(self.meta.zs_lst) if conf.get("plot_zs", False) else [],
            "mean": self._mean_lines() if conf.get("plot_mean", False) else [],
            "bspMarkers": [],
            "customMarkers": [],
        }
        if conf.get("plot_bsp", False):
            payload["bspMarkers"].extend(self._bsp_markers(self.meta.bs_point_lst, price_span))
        if conf.get("plot_segbsp", False):
            payload["bspMarkers"].extend(self._bsp_markers(self.meta.seg_bsp_lst, price_span))
        if conf.get("plot_marker", False):
            payload["customMarkers"].extend(self._custom_markers(klu_list, price_span))
        return payload

    def _build_symbol_info(self, resolution: str, pricescale: int, volume_precision: int, has_volume: bool):
        is_intraday = self.lv in {KL_TYPE.K_1M, KL_TYPE.K_3M, KL_TYPE.K_5M, KL_TYPE.K_15M, KL_TYPE.K_30M, KL_TYPE.K_60M}
        has_weekly_and_monthly = self.lv in {KL_TYPE.K_WEEK, KL_TYPE.K_MON, KL_TYPE.K_QUARTER, KL_TYPE.K_YEAR}
        return {
            "name": self.chan.code,
            "full_name": self.chan.code,
            "ticker": self.chan.code,
            "description": f"{self.chan.code} Chan",
            "type": "stock",
            "session": "24x7",
            "exchange": "CHAN",
            "listed_exchange": "CHAN",
            "timezone": "Asia/Shanghai",
            "format": "price",
            "pricescale": max(1, pricescale),
            "minmov": 1,
            "has_intraday": is_intraday,
            "supported_resolutions": [resolution],
            "intraday_multipliers": [resolution] if is_intraday else [],
            "has_daily": not is_intraday,
            "has_weekly_and_monthly": has_weekly_and_monthly,
            "has_no_volume": not has_volume,
            "volume_precision": volume_precision,
            "data_status": "streaming" if is_intraday else "endofday",
        }

    def _build_legend(self, conf: Dict[str, bool]):
        legend = [{"label": "K线", "color": "#d32f2f"}]
        if conf.get("plot_kline_combine", False):
            legend.append({"label": "合并K线", "color": "#7c3aed"})
        if conf.get("plot_bi", False):
            legend.append({"label": "笔", "color": "#111111"})
        if conf.get("plot_seg", False):
            legend.append({"label": "段", "color": "#00897b"})
        if conf.get("plot_zs", False):
            legend.append({"label": "中枢", "color": "#fb8c00"})
        if conf.get("plot_mean", False):
            legend.append({"label": "均线", "color": "#5e35b1"})
        if conf.get("plot_bsp", False) or conf.get("plot_segbsp", False):
            legend.extend([
                {"label": "买点", "color": "#d32f2f"},
                {"label": "卖点", "color": "#2e7d32"},
                {"label": "※=段级别", "color": "#546e7a"},
            ])
        return legend

    def _lines(self, line_list):
        x_begin, _ = self.x_limits
        result = []
        for item in line_list:
            if item.end_x < x_begin:
                continue
            result.append({
                "sure": bool(item.is_sure),
                "points": [
                    {"time": self._time_at(item.begin_x), "price": float(item.begin_y)},
                    {"time": self._time_at(item.end_x), "price": float(item.end_y)},
                ],
            })
        return result

    def _zs_list(self, zs_list):
        x_begin, x_end = self.x_limits
        result = []
        for zs in zs_list:
            if zs.end < x_begin or zs.begin > x_end:
                continue
            result.append({
                "leftTime": self._bar_time_bounds(zs.begin)[0],
                "rightTime": self._bar_time_bounds(zs.end)[1],
                "low": float(zs.low),
                "high": float(zs.high),
                "sure": bool(zs.is_sure),
            })
        return result

    def _klc_ranges(self, plot_single_kl: bool):
        result = []
        for klc in self.meta.klc_list:
            if klc.begin_idx == klc.end_idx and not plot_single_kl:
                continue
            style = self.KLC_STYLE.get(klc.type, {"color": "#64748b", "background": "#e2e8f0", "label": "合并K线"})
            left_time = self._bar_time_bounds(klc.begin_idx)[0]
            right_time = self._bar_time_bounds(klc.end_idx)[1]
            result.append({
                "leftTime": left_time,
                "rightTime": right_time,
                "low": float(klc.low),
                "high": float(klc.high),
                "color": style["color"],
                "background": style["background"],
                "label": style["label"],
                "single": klc.begin_idx == klc.end_idx,
            })
        return result

    def _mean_lines(self):
        klu_list = list(self.meta.klu_iter())
        if not klu_list or TREND_TYPE.MEAN not in klu_list[0].trend:
            return []
        palette = [
            "#5e35b1",
            "#1e88e5",
            "#43a047",
            "#f4511e",
            "#8e24aa",
            "#6d4c41",
        ]
        period_color = {34: "#FFD700", 233: "#FF00FF"}
        mean_dict = klu_list[0].trend[TREND_TYPE.MEAN]
        result = []
        for idx, mean_period in enumerate(sorted(mean_dict.keys())):
            result.append({
                "label": f"MA{mean_period}",
                "color": period_color.get(mean_period, palette[idx % len(palette)]),
                "points": [{
                    "time": int(klu.time.ts),
                    "price": float(klu.trend[TREND_TYPE.MEAN][mean_period]),
                } for klu in klu_list],
            })
        return result

    def _marker_payload(
        self,
        *,
        idx: int,
        price: float,
        badge: str,
        is_buy: bool,
        color: str,
        price_span: float,
        is_seg: bool = False,
    ):
        time = self._time_at(idx)
        text_offset = price_span * (0.055 if is_seg else 0.04)
        label_price = price - text_offset if is_buy else price + text_offset
        return {
            "time": time,
            "price": price,
            "labelPrice": label_price,
            "shape": "arrow_up" if is_buy else "arrow_down",
            "color": color,
            "badge": badge,
            "isSeg": is_seg,
        }

    def _bsp_markers(self, bsp_list, price_span: float):
        x_begin, x_end = self.x_limits
        result = []
        for bsp in bsp_list:
            if bsp.x < x_begin or bsp.x > x_end:
                continue
            result.append(self._marker_payload(
                idx=bsp.x,
                price=float(bsp.y),
                badge=bsp.desc(),
                is_buy=bool(bsp.is_buy),
                color="#d32f2f" if bsp.is_buy else "#2e7d32",
                price_span=price_span,
                is_seg=bool(bsp.is_seg),
            ))
        return result

    def _resolve_marker_idx(self, klu_list, date_str: str, date_to_idx: Dict[str, int]):
        if date_str in date_to_idx:
            return date_to_idx[date_str]
        for klu in klu_list:
            if klu.include_sub_lv_time(date_str):
                return klu.idx
        return None

    def _custom_markers(self, klu_list, price_span: float):
        marker_conf = self.plot_para.get("marker", {}).get("markers", {})
        if not marker_conf:
            return []

        date_to_idx = {klu.time.to_str(): klu.idx for klu in klu_list}
        klu_by_idx = {klu.idx: klu for klu in klu_list}
        result = []
        for date, marker in marker_conf.items():
            date_str = date.to_str() if isinstance(date, CTime) else str(date)
            idx = self._resolve_marker_idx(klu_list, date_str, date_to_idx)
            if idx is None or idx not in klu_by_idx:
                continue
            klu = klu_by_idx[idx]
            text, position = marker[:2]
            color = marker[2] if len(marker) == 3 else "#1e88e5"
            is_buy = position != "up"
            result.append(self._marker_payload(
                idx=idx,
                price=float(klu.low if is_buy else klu.high),
                badge=str(text),
                is_buy=is_buy,
                color=color,
                price_span=price_span,
                is_seg=False,
            ))
        return result

    def _render_html(self, output_path: Path):
        payload_json = json.dumps(self.payload, ensure_ascii=False)
        safe_title = html.escape(self.payload["title"])
        library_path = os.path.relpath(self.charting_library_dir, start=output_path.parent).replace(os.sep, "/")
        if not library_path.endswith("/"):
            library_path += "/"
        library_path_json = json.dumps(library_path)
        runtime_hint_json = json.dumps(
            f"请在 {output_path.parent} 目录执行 python -m http.server 8000，然后打开 http://127.0.0.1:8000/{output_path.name}",
            ensure_ascii=False,
        )

        template = """<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>__SAFE_TITLE__</title>
  <style>
    :root {
      color-scheme: light;
      font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", sans-serif;
    }
    html, body {
      margin: 0;
      height: 100%;
      background: #f6f8fb;
      color: #1f2937;
    }
    body {
      display: flex;
      flex-direction: column;
    }
    #topbar {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      box-sizing: border-box;
      min-height: 62px;
      padding: 10px 14px;
      border-bottom: 1px solid #e5e7eb;
      background: #ffffff;
    }
    #title {
      padding-top: 6px;
      font-size: 16px;
      font-weight: 600;
      white-space: nowrap;
    }
    #topbar-right {
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 8px;
      min-width: 0;
    }
    #controls {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 8px;
    }
    .toggle-chip {
      border: 1px solid #d0d7e2;
      background: #ffffff;
      color: #475569;
      border-radius: 999px;
      font-size: 12px;
      line-height: 1;
      padding: 7px 10px;
      cursor: pointer;
      transition: all 0.15s ease;
    }
    .toggle-chip:hover {
      border-color: #94a3b8;
      color: #1e293b;
    }
    .toggle-chip.is-active {
      border-color: transparent;
      color: #ffffff;
      box-shadow: 0 4px 12px rgba(15, 23, 42, 0.12);
    }
    #legend {
      display: flex;
      flex-wrap: wrap;
      gap: 8px 12px;
      justify-content: flex-end;
      font-size: 12px;
      color: #475569;
    }
    .legend-item {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .legend-dot {
      width: 10px;
      height: 10px;
      border-radius: 999px;
      flex: 0 0 auto;
    }
    #runtime-tip {
      display: none;
      padding: 8px 14px;
      background: #fff7ed;
      color: #9a3412;
      border-bottom: 1px solid #fed7aa;
      font-size: 12px;
      word-break: break-all;
    }
    #chart-wrap {
      position: relative;
      flex: 1;
      min-height: 0;
    }
    #chart {
      width: 100%;
      height: 100%;
    }
  </style>
  <script type=\"text/javascript\" src=\"__LIBRARY_PATH__charting_library.min.js\"></script>
</head>
<body>
  <div id=\"topbar\">
    <div id=\"title\"></div>
    <div id=\"topbar-right\">
      <div id=\"controls\"></div>
      <div id=\"legend\"></div>
    </div>
  </div>
  <div id=\"runtime-tip\"></div>
  <div id=\"chart-wrap\">
    <div id=\"chart\"></div>
  </div>
  <script>
    const payload = __PAYLOAD_JSON__;
    const libraryPath = __LIBRARY_PATH_JSON__;
    const runtimeHint = __RUNTIME_HINT_JSON__;

    const titleElement = document.getElementById('title');
    const legendElement = document.getElementById('legend');
    const controlsElement = document.getElementById('controls');
    const runtimeTipElement = document.getElementById('runtime-tip');

    titleElement.textContent = payload.title;
    legendElement.innerHTML = payload.legend.map(item => (
      `<span class=\"legend-item\"><span class=\"legend-dot\" style=\"background:${item.color}\"></span>${item.label}</span>`
    )).join('');

    if (location.protocol === 'file:') {
      runtimeTipElement.style.display = 'block';
      runtimeTipElement.textContent = runtimeHint;
    }

    if (!window.TradingView) {
      runtimeTipElement.style.display = 'block';
      runtimeTipElement.textContent = `TradingView 资源加载失败，请确认 ${libraryPath} 可访问。`;
      throw new Error('TradingView library is not available');
    }

    const controlSpecs = [
      { key: 'klc', label: '合并K线', color: '#7c3aed', available: payload.klc.length > 0 },
      { key: 'bi', label: '笔', color: '#111111', available: payload.bi.length > 0 },
      { key: 'seg', label: '段', color: '#00897b', available: payload.seg.length > 0 },
      { key: 'zs', label: '中枢', color: '#fb8c00', available: payload.zs.length > 0 },
      { key: 'mean', label: '均线', color: '#5e35b1', available: payload.mean.length > 0 },
      { key: 'bsp', label: '买卖点', color: '#d32f2f', available: payload.bspMarkers.length > 0 },
      { key: 'marker', label: '标记', color: '#1e88e5', available: payload.customMarkers.length > 0 },
    ].filter(item => item.available);

    const layerState = Object.fromEntries(controlSpecs.map(item => [item.key, true]));
    let chartApi = null;

    function createDatafeed(chartPayload) {
      const symbolInfo = chartPayload.symbolInfo;
      const searchItem = {
        symbol: chartPayload.symbol,
        full_name: chartPayload.symbol,
        description: chartPayload.title,
        exchange: symbolInfo.exchange,
        ticker: chartPayload.symbol,
        type: symbolInfo.type,
      };
      return {
        onReady(callback) {
          setTimeout(() => callback({
            supported_resolutions: symbolInfo.supported_resolutions,
            supports_marks: false,
            supports_timescale_marks: false,
            supports_time: true,
          }), 0);
        },
        searchSymbols(userInput, exchange, symbolType, onResult) {
          const keyword = String(userInput || '').toLowerCase();
          if (!keyword) {
            onResult([searchItem]);
            return;
          }
          const matched = [searchItem].filter(item => (
            item.symbol.toLowerCase().includes(keyword) || item.description.toLowerCase().includes(keyword)
          ));
          onResult(matched);
        },
        resolveSymbol(symbolName, onResolve, onError) {
          setTimeout(() => {
            if (symbolName && symbolName !== chartPayload.symbol) {
              onError(`Unknown symbol: ${symbolName}`);
              return;
            }
            onResolve(symbolInfo);
          }, 0);
        },
        getBars(symbolInfo, resolution, from, to, onResult, onError, isFirstCall) {
          try {
            let bars = chartPayload.bars;
            if (Number.isFinite(from) && Number.isFinite(to)) {
              const filtered = bars.filter(bar => bar.time >= from && bar.time <= to);
              if (filtered.length > 0) {
                bars = filtered;
              } else if (!isFirstCall) {
                onResult([], { noData: true });
                return;
              }
            }
            onResult(bars.map(bar => ({
              time: bar.time * 1000,
              open: bar.open,
              high: bar.high,
              low: bar.low,
              close: bar.close,
              volume: bar.volume == null ? undefined : bar.volume,
            })), { noData: bars.length === 0 });
          } catch (error) {
            console.error(error);
            onError(error && error.message ? error.message : String(error));
          }
        },
        subscribeBars(symbolInfo, resolution, onTick, listenerGuid, onResetCacheNeededCallback) {},
        unsubscribeBars(listenerGuid) {},
        getServerTime(callback) {
          const lastBar = chartPayload.bars[chartPayload.bars.length - 1];
          callback(lastBar ? lastBar.time : Math.floor(Date.now() / 1000));
        },
      };
    }

    function createShapeSafe(chart, point, options) {
      try {
        return chart.createShape(point, options);
      } catch (error) {
        console.warn('createShape failed', options, error);
        return null;
      }
    }

    function createMultipointShapeSafe(chart, points, options) {
      try {
        return chart.createMultipointShape(points, options);
      } catch (error) {
        console.warn('createMultipointShape failed', options, error);
        return null;
      }
    }

    function drawLineSet(chart, items, style) {
      items.forEach(item => {
        createMultipointShapeSafe(chart, item.points, {
          shape: 'trend_line',
          lock: true,
          disableSelection: true,
          disableSave: true,
          disableUndo: true,
          showInObjectsTree: false,
          zOrder: 'bottom',
          overrides: {
            showLabel: false,
            linewidth: style.lineWidth,
            linestyle: item.sure ? 0 : 2,
            linecolor: item.sure ? style.color : style.unsureColor,
          },
        });
      });
    }

    function drawRectangles(chart, items, style) {
      items.forEach(item => {
        createMultipointShapeSafe(chart, [
          { time: item.leftTime, price: item.high },
          { time: item.rightTime, price: item.low },
        ], {
          shape: 'rectangle',
          lock: true,
          disableSelection: true,
          disableSave: true,
          disableUndo: true,
          showInObjectsTree: false,
          zOrder: style.zOrder || 'bottom',
          overrides: {
            linecolor: item.color || style.color,
            linewidth: item.lineWidth || style.lineWidth,
            linestyle: item.sure === false ? 2 : style.lineStyle,
            fillBackground: true,
            backgroundColor: item.background || style.background,
            transparency: item.transparency == null ? style.transparency : item.transparency,
          },
        });
      });
    }

    function drawPolyline(chart, points, color) {
      if (!points || points.length < 2) {
        return;
      }
      for (let index = 1; index < points.length; index += 1) {
        createMultipointShapeSafe(chart, [points[index - 1], points[index]], {
          shape: 'trend_line',
          lock: true,
          disableSelection: true,
          disableSave: true,
          disableUndo: true,
          showInObjectsTree: false,
          zOrder: 'bottom',
          overrides: {
            showLabel: false,
            linecolor: color,
            linewidth: 2,
            linestyle: 0,
          },
        });
      }
    }

    function drawMeanLines(chart, items) {
      items.forEach(item => drawPolyline(chart, item.points, item.color));
    }

    function drawMarkers(chart, items) {
      items.forEach(item => {
        createShapeSafe(chart, { time: item.time, price: item.price }, {
          shape: item.shape,
          lock: true,
          disableSelection: true,
          disableSave: true,
          disableUndo: true,
          showInObjectsTree: false,
          zOrder: 'top',
          overrides: {
            color: item.color,
          },
        });
        createShapeSafe(chart, { time: item.time, price: item.labelPrice }, {
          shape: 'text',
          text: item.badge,
          lock: true,
          disableSelection: true,
          disableSave: true,
          disableUndo: true,
          showInObjectsTree: false,
          zOrder: 'top',
          overrides: {
            color: item.color,
            fontsize: item.isSeg ? 16 : 14,
            bold: item.isSeg,
          },
        });
      });
    }

    function drawPayload(chart) {
      chart.removeAllShapes();
      if (layerState.klc) {
        drawRectangles(chart, payload.klc, {
          color: '#7c3aed',
          background: '#ede9fe',
          lineWidth: 1,
          lineStyle: 0,
          transparency: 92,
          zOrder: 'bottom',
        });
      }
      if (layerState.bi) {
        drawLineSet(chart, payload.bi, { color: '#111111', unsureColor: '#9ca3af', lineWidth: 2 });
      }
      if (layerState.seg) {
        drawLineSet(chart, payload.seg, { color: '#00897b', unsureColor: '#80cbc4', lineWidth: 3 });
      }
      if (layerState.zs) {
        drawRectangles(chart, payload.zs, {
          color: '#fb8c00',
          background: '#ffedd5',
          lineWidth: 2,
          lineStyle: 0,
          transparency: 86,
          zOrder: 'bottom',
        });
      }
      if (layerState.mean) {
        drawMeanLines(chart, payload.mean);
      }
      if (layerState.bsp) {
        drawMarkers(chart, payload.bspMarkers);
      }
      if (layerState.marker) {
        drawMarkers(chart, payload.customMarkers);
      }
    }

    function renderControls() {
      controlsElement.innerHTML = controlSpecs.map(item => {
        const active = layerState[item.key];
        const cls = active ? 'toggle-chip is-active' : 'toggle-chip';
        const style = active ? `style=\"background:${item.color}\"` : '';
        return `<button class=\"${cls}\" ${style} data-key=\"${item.key}\">${item.label}</button>`;
      }).join('');
      controlsElement.querySelectorAll('[data-key]').forEach(button => {
        button.addEventListener('click', () => {
          const key = button.getAttribute('data-key');
          if (!key) {
            return;
          }
          layerState[key] = !layerState[key];
          renderControls();
          if (chartApi) {
            drawPayload(chartApi);
          }
        });
      });
    }

    renderControls();

    const widget = new TradingView.widget({
      symbol: payload.symbol,
      interval: payload.resolution,
      autosize: true,
      container_id: 'chart',
      datafeed: createDatafeed(payload),
      library_path: libraryPath,
      locale: 'zh',
      theme: 'Light',
      disabled_features: [
        'use_localstorage_for_settings',
        'header_symbol_search',
        'header_compare',
        'header_interval_dialog_button',
        'timeframes_toolbar',
      ],
      enabled_features: [
        'study_templates',
      ],
      overrides: {
        'mainSeriesProperties.style': 1,
        'mainSeriesProperties.candleStyle.upColor': '#d32f2f',
        'mainSeriesProperties.candleStyle.downColor': '#2e7d32',
        'mainSeriesProperties.candleStyle.borderUpColor': '#d32f2f',
        'mainSeriesProperties.candleStyle.borderDownColor': '#2e7d32',
        'mainSeriesProperties.candleStyle.wickUpColor': '#d32f2f',
        'mainSeriesProperties.candleStyle.wickDownColor': '#2e7d32',
        'mainSeriesProperties.showPriceLine': false,
        'paneProperties.background': '#ffffff',
        'paneProperties.vertGridProperties.color': '#eef2f7',
        'paneProperties.horzGridProperties.color': '#eef2f7',
        'scalesProperties.lineColor': '#e5e7eb',
        'scalesProperties.textColor': '#475569',
      },
    });

    widget.onChartReady(() => {
      chartApi = widget.chart();
      let rendered = false;
      const renderOnce = () => {
        if (rendered) {
          return;
        }
        rendered = true;
        drawPayload(chartApi);
        if (payload.visibleRange) {
          chartApi.setVisibleRange(payload.visibleRange).catch(error => {
            console.warn('setVisibleRange failed', error);
          });
        }
      };

      const readyNow = chartApi.dataReady(renderOnce);
      if (readyNow) {
        renderOnce();
      }
    });
  </script>
</body>
</html>
"""
        return (
            template
            .replace("__SAFE_TITLE__", safe_title)
            .replace("__PAYLOAD_JSON__", payload_json)
            .replace("__LIBRARY_PATH__", library_path)
            .replace("__LIBRARY_PATH_JSON__", library_path_json)
            .replace("__RUNTIME_HINT_JSON__", runtime_hint_json)
        )
