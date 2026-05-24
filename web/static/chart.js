const libraryPath = '/charting_library/';

const titleElement = document.getElementById('title');
const legendElement = document.getElementById('legend');
const controlsElement = document.getElementById('controls');
const messageElement = document.getElementById('message');
const loadingElement = document.getElementById('loading');
const formElement = document.getElementById('query-form');
const chartElement = document.getElementById('chart');

let widget = null;
let chartApi = null;
let payload = null;
let layerState = {};
let controlSpecs = [];

function showMessage(text, isError = false) {
  messageElement.style.display = text ? 'block' : 'none';
  messageElement.style.background = isError ? '#fef2f2' : '#fff7ed';
  messageElement.style.color = isError ? '#991b1b' : '#9a3412';
  messageElement.style.borderBottomColor = isError ? '#fecaca' : '#fed7aa';
  messageElement.textContent = text || '';
}

function setLoading(visible, text = '加载中...') {
  loadingElement.style.display = visible ? 'flex' : 'none';
  loadingElement.textContent = text;
}

function initFormFromUrl() {
  const params = new URLSearchParams(location.search);
  const today = new Date().toISOString().slice(0, 10);
  formElement.code.value = params.get('code') || '';
  formElement.lv.value = params.get('lv') || 'day';
  formElement.begin.value = params.get('begin') || '';
  formElement.end.value = params.get('end') || '';
  formElement.x_range.value = params.get('x_range') || '500';
  formElement.data_src.value = params.get('data_src') || 'TDX';
  formElement.end.placeholder = today;
}

function paramsFromForm() {
  const params = new URLSearchParams();
  ['code', 'lv', 'begin', 'end', 'x_range', 'data_src'].forEach(name => {
    const value = String(formElement[name].value || '').trim();
    if (value) params.set(name, value);
  });
  return params;
}

function syncUrl(params) {
  const nextUrl = `${location.pathname}?${params.toString()}`;
  history.replaceState(null, '', nextUrl);
}

async function fetchPayload(params) {
  const response = await fetch(`/api/chart/payload?${params.toString()}`);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `HTTP ${response.status}`);
  }
  return data;
}

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
      onResult([searchItem].filter(item => (
        item.symbol.toLowerCase().includes(keyword) || item.description.toLowerCase().includes(keyword)
      )));
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
        let bars = chartPayload.bars || [];
        if (!isFirstCall && Number.isFinite(from) && Number.isFinite(to)) {
          const filtered = bars.filter(bar => bar.time >= from && bar.time <= to);
          if (filtered.length > 0) {
            bars = filtered;
          } else {
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
  try { return chart.createShape(point, options); } catch (error) { console.warn('createShape failed', options, error); return null; }
}

function createMultipointShapeSafe(chart, points, options) {
  try { return chart.createMultipointShape(points, options); } catch (error) { console.warn('createMultipointShape failed', options, error); return null; }
}

function drawLineSet(chart, items, style) {
  items.forEach(item => {
    createMultipointShapeSafe(chart, item.points, {
      shape: 'trend_line', lock: true, disableSelection: true, disableSave: true, disableUndo: true,
      showInObjectsTree: false, zOrder: 'bottom',
      overrides: { showLabel: false, extendLeft: false, extendRight: false, linewidth: style.lineWidth, linestyle: item.sure ? 0 : 2, linecolor: item.sure ? style.color : style.unsureColor },
    });
  });
}

function drawRectangles(chart, items, style) {
  items.forEach(item => {
    createMultipointShapeSafe(chart, [
      { time: item.leftTime, price: item.high },
      { time: item.rightTime, price: item.low },
    ], {
      shape: 'rectangle', lock: true, disableSelection: true, disableSave: true, disableUndo: true,
      showInObjectsTree: false, zOrder: style.zOrder || 'bottom',
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
  if (!points || points.length < 2) return;
  for (let index = 1; index < points.length; index += 1) {
    createMultipointShapeSafe(chart, [points[index - 1], points[index]], {
      shape: 'trend_line', lock: true, disableSelection: true, disableSave: true, disableUndo: true,
      showInObjectsTree: false, zOrder: 'bottom',
      overrides: { showLabel: false, linecolor: color, linewidth: 2, linestyle: 0 },
    });
  }
}

function drawMeanLines(chart, items) {
  items.forEach(item => drawPolyline(chart, item.points, item.color));
}

function drawMarkers(chart, items) {
  items.forEach(item => {
    createShapeSafe(chart, { time: item.time, price: item.price }, {
      shape: item.shape, lock: true, disableSelection: true, disableSave: true, disableUndo: true,
      showInObjectsTree: false, zOrder: 'top', overrides: { color: item.color },
    });
    createShapeSafe(chart, { time: item.time, price: item.labelPrice }, {
      shape: 'text', text: item.badge, lock: true, disableSelection: true, disableSave: true, disableUndo: true,
      showInObjectsTree: false, zOrder: 'top', overrides: { color: item.color, fontsize: item.isSeg ? 16 : 14, bold: item.isSeg },
    });
  });
}

function drawPayload(chart) {
  if (!payload) return;
  chart.removeAllShapes();
  if (layerState.klc) drawRectangles(chart, payload.klc, { color: '#7c3aed', background: '#ede9fe', lineWidth: 1, lineStyle: 0, transparency: 92, zOrder: 'bottom' });
  if (layerState.bi) drawLineSet(chart, payload.bi, { color: '#111111', unsureColor: '#9ca3af', lineWidth: 2 });
  if (layerState.seg) drawLineSet(chart, payload.seg, { color: '#00897b', unsureColor: '#80cbc4', lineWidth: 3 });
  if (layerState.zs) drawRectangles(chart, payload.zs, { color: '#fb8c00', background: '#ffedd5', lineWidth: 2, lineStyle: 0, transparency: 86, zOrder: 'bottom' });
  if (layerState.mean) drawMeanLines(chart, payload.mean);
  if (layerState.bsp) drawMarkers(chart, payload.bspMarkers);
  if (layerState.firstProbability) drawMarkers(chart, payload.firstProbabilityMarkers || []);
  if (layerState.secondProbability) drawMarkers(chart, payload.secondProbabilityMarkers || []);
  if (layerState.marker) drawMarkers(chart, payload.customMarkers);
}

function renderLegend() {
  legendElement.innerHTML = (payload.legend || []).map(item => (
    `<span class="legend-item"><span class="legend-dot" style="background:${item.color}"></span>${item.label}</span>`
  )).join('');
}

function renderControls() {
  controlsElement.innerHTML = controlSpecs.map(item => {
    const active = layerState[item.key];
    const cls = active ? 'toggle-chip is-active' : 'toggle-chip';
    const style = active ? `style="background:${item.color}"` : '';
    return `<button class="${cls}" ${style} data-key="${item.key}">${item.label}</button>`;
  }).join('');
  controlsElement.querySelectorAll('[data-key]').forEach(button => {
    button.addEventListener('click', () => {
      const key = button.getAttribute('data-key');
      if (!key) return;
      layerState[key] = !layerState[key];
      renderControls();
      if (chartApi) drawPayload(chartApi);
    });
  });
}

function setupLayers() {
  controlSpecs = [
    { key: 'klc', label: '合并K线', color: '#7c3aed', available: payload.klc && payload.klc.length > 0 },
    { key: 'bi', label: '笔', color: '#111111', available: payload.bi && payload.bi.length > 0 },
    { key: 'seg', label: '段', color: '#00897b', available: payload.seg && payload.seg.length > 0 },
    { key: 'zs', label: '中枢', color: '#fb8c00', available: payload.zs && payload.zs.length > 0 },
    { key: 'mean', label: '均线', color: '#5e35b1', available: payload.mean && payload.mean.length > 0 },
    { key: 'bsp', label: '买卖点', color: '#d32f2f', available: payload.bspMarkers && payload.bspMarkers.length > 0 },
    { key: 'firstProbability', label: '一类稳定', color: '#b91c1c', available: payload.firstProbabilityMarkers && payload.firstProbabilityMarkers.length > 0 },
    { key: 'secondProbability', label: '二类稳定', color: '#dc2626', available: payload.secondProbabilityMarkers && payload.secondProbabilityMarkers.length > 0 },
    { key: 'marker', label: '标记', color: '#1e88e5', available: payload.customMarkers && payload.customMarkers.length > 0 },
  ].filter(item => item.available);
  layerState = Object.fromEntries(controlSpecs.map(item => [item.key, true]));
  renderControls();
}

function cleanupWidget() {
  chartApi = null;
  if (widget && typeof widget.remove === 'function') {
    try { widget.remove(); } catch (error) { console.warn('widget remove failed', error); }
  }
  widget = null;
  chartElement.innerHTML = '';
}

function renderChart() {
  if (!window.TradingView) throw new Error('TradingView 资源加载失败，请确认 /charting_library/ 可访问。');
  cleanupWidget();
  widget = new TradingView.widget({
    symbol: payload.symbol,
    interval: payload.resolution,
    autosize: true,
    container_id: 'chart',
    datafeed: createDatafeed(payload),
    library_path: libraryPath,
    locale: 'zh',
    timezone: payload.timezone || 'Asia/Shanghai',
    theme: 'Light',
    disabled_features: ['use_localstorage_for_settings', 'header_symbol_search', 'header_compare', 'header_interval_dialog_button', 'timeframes_toolbar'],
    enabled_features: [],
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
    const renderOnce = async () => {
      if (rendered) return;
      rendered = true;
      try {
        if (payload.visibleRange) {
          await chartApi.setVisibleRange(payload.visibleRange);
        }
        drawPayload(chartApi);
      } catch (error) {
        console.warn('chart render failed', error);
        drawPayload(chartApi);
      } finally {
        setLoading(false);
      }
    };
    const readyNow = chartApi.dataReady(renderOnce);
    if (readyNow) void renderOnce();
  });
}

async function loadFromParams(params) {
  if (!params.get('code')) {
    setLoading(false);
    showMessage('请输入股票代码，例如：http://127.0.0.1:8000/chart?code=002112&lv=30m', false);
    return;
  }
  setLoading(true, '正在加载数据并计算缠论结构...');
  showMessage('', false);
  controlsElement.innerHTML = '';
  legendElement.innerHTML = '';
  payload = await fetchPayload(params);
  if (!payload.bars || payload.bars.length === 0) throw new Error('没有返回 K 线数据');
  titleElement.textContent = `${payload.title}${payload.cache && payload.cache.hit ? '（缓存）' : ''}`;
  renderLegend();
  setupLayers();
  renderChart();
}

formElement.addEventListener('submit', async event => {
  event.preventDefault();
  const params = paramsFromForm();
  syncUrl(params);
  try {
    await loadFromParams(params);
  } catch (error) {
    console.error(error);
    setLoading(false);
    showMessage(error && error.message ? error.message : String(error), true);
  }
});

initFormFromUrl();
loadFromParams(new URLSearchParams(location.search)).catch(error => {
  console.error(error);
  setLoading(false);
  showMessage(error && error.message ? error.message : String(error), true);
});
