const messageElement = document.getElementById('message');
const filtersElement = document.getElementById('filters');
const summaryElement = document.getElementById('summary');
const industryStatsElement = document.getElementById('industry-stats');
const conceptStatsElement = document.getElementById('concept-stats');
const resultsBodyElement = document.getElementById('results-body');
const resultCountElement = document.getElementById('result-count');

let runs = [];
let industries = [];
let concepts = [];

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function showMessage(text, isError = false) {
  messageElement.style.display = text ? 'block' : 'none';
  messageElement.style.borderColor = isError ? '#fecaca' : '#fed7aa';
  messageElement.style.background = isError ? '#fef2f2' : '#fff7ed';
  messageElement.style.color = isError ? '#991b1b' : '#9a3412';
  messageElement.textContent = text || '';
}

function formatNumber(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function formatPct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
  const num = Number(value);
  const cls = num >= 0 ? 'pct-up' : 'pct-down';
  return `<span class="${cls}">${num >= 0 ? '+' : ''}${num.toFixed(2)}%</span>`;
}

function directionText(value) {
  if (value === 'buy') return '买';
  if (value === 'sell') return '卖';
  return value || '-';
}

function biModeText(value) {
  if (value === 'down') return '最新笔下跌';
  if (value === 'down_sure') return '最新笔下跌且确认';
  return '关闭';
}

function metric(label, value) {
  return `<div class="metric"><div class="metric-label">${escapeHtml(label)}</div><div class="metric-value">${value}</div></div>`;
}

function dateText(value) {
  return value ? String(value).replace('T', ' ').slice(0, 19) : '-';
}

function renderRunOptions(selectedRunId) {
  const select = filtersElement.run_id;
  if (!runs.length) {
    select.innerHTML = '<option value="">暂无批次</option>';
    return;
  }
  select.innerHTML = runs.map(run => {
    const label = `#${run.id} ${run.sequence_text || '-'} ${run.signal_level || '30M'} ${run.created_at || run.finished_at || ''} 命中${run.result_count}`;
    const selected = String(run.id) === String(selectedRunId) ? 'selected' : '';
    return `<option value="${escapeHtml(run.id)}" ${selected}>${escapeHtml(label)}</option>`;
  }).join('');
}

function renderIndustryOptions(selectedIndustry) {
  const select = filtersElement.industry;
  const options = [{ industry: 'all', label: '全部', code_count: null }, ...industries.map(item => ({
    industry: item.industry,
    label: item.industry,
    code_count: item.code_count,
  }))];
  select.innerHTML = options.map(item => {
    const selected = String(item.industry) === String(selectedIndustry || 'all') ? 'selected' : '';
    const suffix = item.code_count == null ? '' : ` (${item.code_count})`;
    return `<option value="${escapeHtml(item.industry)}" ${selected}>${escapeHtml(item.label)}${escapeHtml(suffix)}</option>`;
  }).join('');
}

function renderConceptOptions(selectedConcept) {
  const select = filtersElement.concept;
  const options = [{ concept_code: 'all', concept_name: '全部', code_count: null }, ...concepts];
  select.innerHTML = options.map(item => {
    const selected = String(item.concept_code) === String(selectedConcept || 'all') ? 'selected' : '';
    const suffix = item.code_count == null ? '' : ` (${item.code_count})`;
    return `<option value="${escapeHtml(item.concept_code)}" ${selected}>${escapeHtml(item.concept_name)}${escapeHtml(suffix)}</option>`;
  }).join('');
}

function renderSummary(data) {
  const summary = data.summary || {};
  const windowText = [summary.begin_date || '-', summary.end_date || '-'].join(' ~ ');
  summaryElement.innerHTML = [
    metric('扫描股票', formatNumber(summary.scanned_count)),
    metric('命中数量', formatNumber(summary.result_count)),
    metric('序列', escapeHtml(summary.sequence || '-')),
    metric('信号级别', escapeHtml(summary.signal_level || '-')),
    metric('最大间隔', summary.max_gap_days == null ? '-' : `${formatNumber(summary.max_gap_days)} 日`),
    metric('笔过滤', escapeHtml(biModeText(summary.bi_mode))),
    metric('数据窗口', escapeHtml(windowText)),
    metric('运行ID', `#${escapeHtml(summary.id || '-')}`),
  ].join('');
}

function renderIndustryStats(items) {
  if (!items || !items.length) {
    industryStatsElement.innerHTML = '<tr><td>暂无数据</td><td></td><td></td></tr>';
    return;
  }
  industryStatsElement.innerHTML = items.map(item => (
    `<tr title="${escapeHtml(item.industry || '')}">
      <td><button class="stat-link" type="button" data-industry="${escapeHtml(item.industry || '')}">${escapeHtml(item.industry || '-')}</button></td>
      <td>命中 ${formatNumber(item.candidate_count)}</td>
      <td>${formatNumber(item.code_count)}股</td>
    </tr>`
  )).join('');
}

function renderConceptStats(items) {
  if (!items || !items.length) {
    conceptStatsElement.innerHTML = '<tr><td>暂无数据</td><td></td><td></td></tr>';
    return;
  }
  conceptStatsElement.innerHTML = items.map(item => (
    `<tr title="${escapeHtml(item.concept_name || '')}">
      <td><button class="stat-link" type="button" data-concept="${escapeHtml(item.concept_code || '')}">${escapeHtml(item.concept_name || '-')}</button></td>
      <td>命中 ${formatNumber(item.candidate_count)}</td>
      <td>${formatNumber(item.code_count)}股</td>
    </tr>`
  )).join('');
}

function renderStats(data) {
  const stats = data.stats || {};
  renderIndustryStats(stats.industry_stats || []);
  renderConceptStats(stats.concept_stats || []);
}

function renderResults(results) {
  resultCountElement.textContent = `${results.length} 条`;
  resultsBodyElement.innerHTML = results.map(result => {
    const sideClass = result.direction === 'buy' ? 'buy' : 'sell';
    const signalText = `${directionText(result.direction)} ${result.signal_type || ''}`.trim();
    return `<tr>
      <td><a class="chart-link stock-name" href="${escapeHtml(result.chart_url)}" target="_blank" rel="noopener"><span>${escapeHtml(result.name || result.code)}</span><span class="stock-code">${escapeHtml(result.code)}</span></a></td>
      <td>${escapeHtml(result.industry || '-')}</td>
      <td class="concept-cell" title="${escapeHtml(result.concept_text || '')}">${escapeHtml(result.concept_text || '-')}</td>
      <td>${escapeHtml(result.area || '-')}</td>
      <td>${escapeHtml(result.signal_time || '-')}</td>
      <td><span class="side ${sideClass}">${escapeHtml(signalText || '-')}</span></td>
      <td>${formatNumber(result.signal_price, 2)}</td>
      <td>${formatNumber(result.latest_price, 2)}</td>
      <td>${formatPct(result.change_pct)}</td>
      <td>${escapeHtml(result.period || '-')}</td>
      <td><a class="chart-link" href="${escapeHtml(result.chart_url)}" target="_blank" rel="noopener">复盘</a></td>
    </tr>`;
  }).join('');
}

async function fetchJson(url) {
  const response = await fetch(url);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}

function paramsFromForm() {
  const params = new URLSearchParams();
  if (filtersElement.run_id.value) params.set('run_id', filtersElement.run_id.value);
  params.set('industry', filtersElement.industry.value || 'all');
  params.set('concept', filtersElement.concept.value || 'all');
  if (filtersElement.start_date.value) params.set('start_date', filtersElement.start_date.value);
  if (filtersElement.end_date.value) params.set('end_date', filtersElement.end_date.value);
  params.set('limit', filtersElement.limit.value || '200');
  return params;
}

async function loadDashboard() {
  showMessage('', false);
  const params = paramsFromForm();
  const data = await fetchJson(`/api/sequence/latest?${params.toString()}`);
  if (!data.available) {
    showMessage(data.message || '暂无 BSP 序列扫描结果', false);
    summaryElement.innerHTML = '';
    renderStats({ stats: {} });
    resultsBodyElement.innerHTML = '';
    resultCountElement.textContent = '';
    return;
  }
  runs = data.runs || runs;
  industries = data.industry_options || industries;
  concepts = data.concept_options || concepts;
  renderRunOptions(data.filters && data.filters.run_id);
  renderIndustryOptions(data.filters && data.filters.industry);
  renderConceptOptions(data.filters && data.filters.concept);
  renderSummary(data);
  renderStats(data);
  renderResults(data.results || []);
}

async function applyFiltersAndReload() {
  try {
    await loadDashboard();
  } catch (error) {
    console.error(error);
    showMessage(error && error.message ? error.message : String(error), true);
  }
}

async function init() {
  const runData = await fetchJson('/api/sequence/runs?limit=20');
  runs = runData.runs || [];
  renderRunOptions(runs[0] && runs[0].id);
  await loadDashboard();
}

filtersElement.addEventListener('submit', event => {
  event.preventDefault();
  void applyFiltersAndReload();
});

filtersElement.industry.addEventListener('change', () => {
  filtersElement.concept.value = 'all';
  void applyFiltersAndReload();
});

filtersElement.concept.addEventListener('change', () => {
  filtersElement.industry.value = 'all';
  void applyFiltersAndReload();
});

filtersElement.run_id.addEventListener('change', () => {
  filtersElement.industry.value = 'all';
  filtersElement.concept.value = 'all';
  void applyFiltersAndReload();
});

industryStatsElement.addEventListener('click', event => {
  const button = event.target.closest('[data-industry]');
  if (!button) return;
  filtersElement.industry.value = button.getAttribute('data-industry') || 'all';
  filtersElement.concept.value = 'all';
  void applyFiltersAndReload();
});

conceptStatsElement.addEventListener('click', event => {
  const button = event.target.closest('[data-concept]');
  if (!button) return;
  filtersElement.concept.value = button.getAttribute('data-concept') || 'all';
  filtersElement.industry.value = 'all';
  void applyFiltersAndReload();
});

init().catch(error => {
  console.error(error);
  showMessage(error && error.message ? error.message : String(error), true);
});
