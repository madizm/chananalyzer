const messageElement = document.getElementById('message');
const filtersElement = document.getElementById('filters');
const summaryElement = document.getElementById('summary');
const distributionElement = document.getElementById('distribution');
const sideStatsTitleElement = document.getElementById('side-stats-title');
const sideStatsElement = document.getElementById('side-stats');
const industryStatsTitleElement = document.getElementById('industry-stats-title');
const industryStatsElement = document.getElementById('industry-stats');
const conceptStatsTitleElement = document.getElementById('concept-stats-title');
const conceptStatsElement = document.getElementById('concept-stats');
const signalsBodyElement = document.getElementById('signals-body');
const signalCountElement = document.getElementById('signal-count');

let runs = [];
let dashboardData = null;
let selectedBucketIndex = null;
let industries = [];
let concepts = [];

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
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function metric(label, value) {
  return `<div class="metric"><div class="metric-label">${label}</div><div class="metric-value">${value}</div></div>`;
}

function renderRunOptions(selectedRunId) {
  const select = filtersElement.run_id;
  select.innerHTML = runs.map(run => {
    const label = `#${run.id} ${run.created_at || run.finished_at || ''} 候选${run.candidate_count}`;
    const selected = String(run.id) === String(selectedRunId) ? 'selected' : '';
    return `<option value="${run.id}" ${selected}>${label}</option>`;
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
    return `<option value="${item.industry}" ${selected}>${item.label}${suffix}</option>`;
  }).join('');
}

function renderConceptOptions(selectedConcept) {
  const select = filtersElement.concept;
  const options = [{ concept_code: 'all', concept_name: '全部', code_count: null }, ...concepts];
  select.innerHTML = options.map(item => {
    const selected = String(item.concept_code) === String(selectedConcept || 'all') ? 'selected' : '';
    const suffix = item.code_count == null ? '' : ` (${item.code_count})`;
    return `<option value="${item.concept_code}" ${selected}>${item.concept_name}${suffix}</option>`;
  }).join('');
}

function renderSummary(data) {
  const summary = data.summary || {};
  const run = data.selected_run || {};
  summaryElement.innerHTML = [
    metric('扫描股票', formatNumber(summary.scan_code_count ?? run.scan_code_count)),
    metric('成功 / 失败', `${formatNumber(summary.success_code_count ?? run.success_code_count)} / ${formatNumber(summary.failure_code_count ?? run.failure_code_count)}`),
    metric('候选总数', formatNumber(summary.candidate_count ?? run.candidate_count)),
    metric('过滤后', formatNumber(summary.filtered_count ?? run.filtered_count)),
    metric('买 / 卖候选', `${formatNumber(summary.buy_candidate_count ?? run.buy_candidate_count)} / ${formatNumber(summary.sell_candidate_count ?? run.sell_candidate_count)}`),
    metric('最近K线', formatNumber(summary.recent_bars ?? run.recent_bars)),
    metric('最小概率', formatPct(data.filters ? data.filters.min_prob : summary.min_prob)),
    metric('运行ID', `#${run.id || '-'}`),
  ].join('');
}

function renderDistribution(items) {
  const totalCount = items.reduce((sum, item) => sum + Number(item.count || 0), 0);
  distributionElement.innerHTML = items.map((item, index) => {
    const count = Number(item.count || 0);
    const share = totalCount > 0 ? count / totalCount : 0;
    const widthPct = Math.round(share * 1000) / 10;
    const bucketStart = Number(String(item.bucket).split('-')[0]);
    const tone = bucketStart >= 0.7 ? 'high' : (bucketStart >= 0.4 ? 'mid' : 'low');
    const fillWidth = count > 0 ? Math.max(widthPct, 1) : 0;
    const selectedClass = index === selectedBucketIndex ? ' is-selected' : '';
    return `<div class="bar-line${selectedClass}" data-bucket-index="${index}" title="查看 ${item.bucket} 分数段的方向对比">
      <span>${item.bucket}</span>
      <span class="bar-track"><span class="bar-fill ${tone}" style="width:${fillWidth}%"></span></span>
      <span>${count}</span>
      <span class="bar-pct">${widthPct.toFixed(1)}%</span>
    </div>`;
  }).join('');
}

function renderSideStats(items, title) {
  sideStatsTitleElement.textContent = title;
  sideStatsElement.innerHTML = (items || []).map(item => (
    `<tr><td>${item.signal_side === 'buy' ? '买' : '卖'}</td><td>候选 ${item.candidate_count}</td><td>高分 ${item.high_score_count}</td><td>均值 ${formatPct(item.avg_probability)}</td></tr>`
  )).join('');
}

function renderIndustryStats(items, title) {
  industryStatsTitleElement.textContent = title;
  industryStatsElement.innerHTML = (items || []).map(item => (
    `<tr>
      <td><button class="stat-link" type="button" data-industry="${item.industry}" data-side="both">${item.industry}</button></td>
      <td>${item.candidate_count}</td>
      <td><button class="stat-link" type="button" data-industry="${item.industry}" data-side="buy">买 ${item.buy_count}</button></td>
      <td><button class="stat-link" type="button" data-industry="${item.industry}" data-side="sell">卖 ${item.sell_count}</button></td>
      <td>均值 ${formatPct(item.avg_probability)}</td>
    </tr>`
  )).join('');
}

function renderConceptStats(items, title) {
  conceptStatsTitleElement.textContent = title;
  conceptStatsElement.innerHTML = (items || []).map(item => (
    `<tr>
      <td><button class="stat-link" type="button" data-concept="${item.concept_code}" data-side="both">${item.concept_name}</button></td>
      <td>${item.candidate_count}</td>
      <td><button class="stat-link" type="button" data-concept="${item.concept_code}" data-side="buy">买 ${item.buy_count}</button></td>
      <td><button class="stat-link" type="button" data-concept="${item.concept_code}" data-side="sell">卖 ${item.sell_count}</button></td>
      <td>均值 ${formatPct(item.avg_probability)}</td>
    </tr>`
  )).join('');
}

function renderStats(data) {
  const stats = data.stats || {};
  const distribution = stats.probability_distribution || [];
  renderDistribution(distribution);
  if (selectedBucketIndex !== null && distribution[selectedBucketIndex]) {
    const bucket = distribution[selectedBucketIndex];
    renderSideStats(bucket.side_stats || [], `方向对比（${bucket.bucket}）`);
    renderIndustryStats(bucket.industry_stats || [], `行业统计（${bucket.bucket}）`);
    renderConceptStats(bucket.concept_stats || [], `概念统计（${bucket.bucket}）`);
  } else {
    renderSideStats(stats.side_stats || [], '方向对比（全部）');
    renderIndustryStats(stats.industry_stats || [], '行业统计（全部）');
    renderConceptStats(stats.concept_stats || [], '概念统计（全部）');
  }
}

function renderSignals(signals) {
  signalCountElement.textContent = `${signals.length} 条`;
  signalsBodyElement.innerHTML = signals.map(signal => {
    const sideClass = signal.signal_side === 'buy' ? 'buy' : 'sell';
    const sideText = signal.signal_side === 'buy' ? '买' : '卖';
    return `<tr>
      <td><a class="chart-link stock-name" href="${signal.chart_url}" target="_blank" rel="noopener"><span>${signal.name || signal.code}</span><span class="stock-code">${signal.code}</span></a></td>
      <td>${signal.industry || '-'}</td>
      <td><span class="side ${sideClass}">${sideText}</span></td>
      <td>${signal.open_time}</td>
      <td class="prob">${formatPct(signal.probability)}</td>
      <td>${formatNumber(signal.price, 2)}</td>
      <td>${signal.bi_idx}</td>
      <td>${formatNumber(signal.candidate_divergence_rate, 3)}</td>
      <td>${formatPct(signal.entry_close_pos)}</td>
      <td>${formatPct(signal.child_close_pos)}</td>
      <td>${formatPct(signal.ma_dist_10)}</td>
      <td><a class="chart-link" href="${signal.chart_url}" target="_blank" rel="noopener">复盘</a></td>
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
  params.set('side', filtersElement.side.value || 'both');
  params.set('industry', filtersElement.industry.value || 'all');
  params.set('concept', filtersElement.concept.value || 'all');
  if (filtersElement.start_date.value) params.set('start_date', filtersElement.start_date.value);
  if (filtersElement.end_date.value) params.set('end_date', filtersElement.end_date.value);
  params.set('min_prob', filtersElement.min_prob.value || '0.6');
  params.set('limit', filtersElement.limit.value || '200');
  return params;
}

function applyFiltersAndReload() {
  return loadDashboard().catch(error => {
    console.error(error);
    showMessage(error && error.message ? error.message : String(error), true);
  });
}

async function loadDashboard() {
  showMessage('', false);
  const params = paramsFromForm();
  const data = await fetchJson(`/api/signals/latest?${params.toString()}`);
  dashboardData = data;
  selectedBucketIndex = null;
  if (!data.available) {
    showMessage(data.message || '暂无扫描结果', false);
    summaryElement.innerHTML = '';
    signalsBodyElement.innerHTML = '';
    signalCountElement.textContent = '';
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
  renderSignals(data.signals || []);
}

distributionElement.addEventListener('click', event => {
  const row = event.target.closest('[data-bucket-index]');
  if (!row || !dashboardData) return;
  const nextIndex = Number(row.getAttribute('data-bucket-index'));
  selectedBucketIndex = selectedBucketIndex === nextIndex ? null : nextIndex;
  renderStats(dashboardData);
});

industryStatsElement.addEventListener('click', event => {
  const button = event.target.closest('[data-industry]');
  if (!button) return;
  filtersElement.industry.value = button.getAttribute('data-industry') || 'all';
  filtersElement.concept.value = 'all';
  filtersElement.side.value = button.getAttribute('data-side') || 'both';
  void applyFiltersAndReload();
});

conceptStatsElement.addEventListener('click', event => {
  const button = event.target.closest('[data-concept]');
  if (!button) return;
  filtersElement.concept.value = button.getAttribute('data-concept') || 'all';
  filtersElement.industry.value = 'all';
  filtersElement.side.value = button.getAttribute('data-side') || 'both';
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

filtersElement.side.addEventListener('change', () => {
  void applyFiltersAndReload();
});

async function init() {
  const runData = await fetchJson('/api/signals/runs?limit=20');
  runs = runData.runs || [];
  renderRunOptions(runs[0] && runs[0].id);
  await loadDashboard();
}

filtersElement.addEventListener('submit', event => {
  event.preventDefault();
  loadDashboard().catch(error => {
    console.error(error);
    showMessage(error && error.message ? error.message : String(error), true);
  });
});

init().catch(error => {
  console.error(error);
  showMessage(error && error.message ? error.message : String(error), true);
});
