(function () {
  const state = {
    feedback: new Map(),
    payloads: {
      buy: null,
      sell: null,
    },
    filters: {
      signalDateFrom: "",
      signalDateTo: "",
      signalType: "",
      amountMin: null,
      turnoverMin: null,
    },
  };

  const FILTER_INPUTS = {
    signalDateFrom: "filter-signal-date-from",
    signalDateTo: "filter-signal-date-to",
    signalType: "filter-signal-type",
    amountMin: "filter-amount-min",
    turnoverMin: "filter-turnover-min",
  };

  const SIGNAL_TYPE_LABELS = {
    "1": "一买",
    "1p": "一买衍生",
    "2": "二买",
    "2s": "二卖",
    "3a": "三买A",
    "3b": "三买B",
  };

  async function fetchJson(path) {
    const base = window.PUBLIC_APP_CONFIG.resultBaseUrl.replace(/\/$/, "");
    const response = await fetch(`${base}/${path}`);
    if (!response.ok) {
      throw new Error(`加载 ${path} 失败`);
    }
    return response.json();
  }

  function formatDate(value) {
    if (!value) {
      return "-";
    }
    return value.replace("T", " ").slice(0, 19);
  }

  function formatPrice(value) {
    return typeof value === "number" ? value.toFixed(2) : "--";
  }

  function formatAmount(value) {
    return typeof value === "number" ? value.toFixed(2) : "--";
  }

  function formatTurnoverRate(value) {
    return typeof value === "number" ? `${value.toFixed(2)}%` : "--";
  }

  function parseNumberInput(value) {
    if (value === "") {
      return null;
    }
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function parseSignalDate(value) {
    if (!value || typeof value !== "string") {
      return null;
    }
    const normalized = value.replace(/\//g, "-");
    const timestamp = Date.parse(`${normalized}T00:00:00`);
    return Number.isFinite(timestamp) ? timestamp : null;
  }

  function filterStocks(stocks) {
    return (stocks || []).filter((stock) => {
      const signalDate = parseSignalDate(stock.latest_signal && stock.latest_signal.date);
      const signalType = stock.latest_signal && stock.latest_signal.type;

      if (state.filters.signalDateFrom) {
        const fromTs = parseSignalDate(state.filters.signalDateFrom);
        if (signalDate === null || fromTs === null || signalDate < fromTs) {
          return false;
        }
      }

      if (state.filters.signalDateTo) {
        const toTs = parseSignalDate(state.filters.signalDateTo);
        if (signalDate === null || toTs === null || signalDate > toTs) {
          return false;
        }
      }

      if (state.filters.signalType && signalType !== state.filters.signalType) {
        return false;
      }

      if (state.filters.amountMin !== null) {
        if (typeof stock.amount !== "number" || stock.amount < state.filters.amountMin) {
          return false;
        }
      }

      if (state.filters.turnoverMin !== null) {
        if (typeof stock.turnover_rate !== "number" || stock.turnover_rate < state.filters.turnoverMin) {
          return false;
        }
      }

      return true;
    });
  }

  function formatSignalType(type) {
    return SIGNAL_TYPE_LABELS[type] || type || "-";
  }

  function getAvailableSignalTypes(payloads) {
    return Array.from(
      new Set(
        payloads
          .flatMap((payload) => (payload && payload.stocks) || [])
          .map((stock) => stock.latest_signal && stock.latest_signal.type)
          .filter(Boolean)
      )
    ).sort((a, b) => formatSignalType(a).localeCompare(formatSignalType(b), "zh-CN"));
  }

  function renderSignalTypeOptions() {
    const select = document.getElementById(FILTER_INPUTS.signalType);
    const signalTypes = getAvailableSignalTypes([state.payloads.buy, state.payloads.sell]);
    const currentValue = state.filters.signalType;

    select.innerHTML = [
      '<option value="">全部信号</option>',
      ...signalTypes.map((type) => `<option value="${type}">${formatSignalType(type)}</option>`),
    ].join("");

    if (signalTypes.includes(currentValue)) {
      select.value = currentValue;
    } else {
      select.value = "";
      state.filters.signalType = "";
    }
  }

  function renderFeedbackCell(code) {
    const item = state.feedback.get(code) || {
      up_count: 0,
      down_count: 0,
      score: 0,
      my_vote: null,
    };
    const upActive = item.my_vote === "up" ? "vote-btn active" : "vote-btn";
    const downActive = item.my_vote === "down" ? "vote-btn active negative" : "vote-btn negative";

    return `
      <div class="feedback" data-code="${code}">
        <button class="${upActive}" data-action="up" type="button">赞 ${item.up_count}</button>
        <button class="${downActive}" data-action="down" type="button">踩 ${item.down_count}</button>
        <span class="score">分数 ${item.score}</span>
      </div>
    `;
  }

  function renderTable(tableBodyId, payload, countId, cacheTimeId, emptyText) {
    const tbody = document.getElementById(tableBodyId);
    const stocks = filterStocks(payload.stocks || []);
    document.getElementById(countId).textContent = stocks.length;
    document.getElementById(cacheTimeId).textContent = `更新时间 ${formatDate(payload.cache_time)}，每日更新一次`;

    if (!stocks.length) {
      tbody.innerHTML = `<tr><td colspan="9" class="empty">${emptyText}</td></tr>`;
      return;
    }

    tbody.innerHTML = stocks.map((stock) => {
      const signal = stock.latest_signal || {};
      return `
        <tr>
          <td>${stock.code}</td>
          <td>${stock.name || ""}</td>
          <td>${stock.industry || ""}</td>
          <td>${formatPrice(stock.current_price)}</td>
          <td>${formatAmount(stock.amount)}</td>
          <td>${formatTurnoverRate(stock.turnover_rate)}</td>
          <td>${signal.direction || "-"} ${signal.type || ""}</td>
          <td>${signal.date || "-"}</td>
          <td>${renderFeedbackCell(stock.code)}</td>
        </tr>
      `;
    }).join("");
  }

  function renderTables() {
    if (state.payloads.buy) {
      renderTable("buy-table-body", state.payloads.buy, "buy-count", "buy-cache-time", "筛选后暂无买点结果");
    }
    if (state.payloads.sell) {
      renderTable("sell-table-body", state.payloads.sell, "sell-count", "sell-cache-time", "筛选后暂无卖点结果");
    }
  }

  function syncFiltersFromInputs() {
    state.filters.signalDateFrom = document.getElementById(FILTER_INPUTS.signalDateFrom).value;
    state.filters.signalDateTo = document.getElementById(FILTER_INPUTS.signalDateTo).value;
    state.filters.signalType = document.getElementById(FILTER_INPUTS.signalType).value;
    state.filters.amountMin = parseNumberInput(document.getElementById(FILTER_INPUTS.amountMin).value);
    state.filters.turnoverMin = parseNumberInput(document.getElementById(FILTER_INPUTS.turnoverMin).value);
  }

  function resetFilters() {
    Object.values(FILTER_INPUTS).forEach((id) => {
      document.getElementById(id).value = "";
    });
    syncFiltersFromInputs();
    renderTables();
  }

  function bindFilterEvents() {
    Object.values(FILTER_INPUTS).forEach((id) => {
      document.getElementById(id).addEventListener("input", () => {
        syncFiltersFromInputs();
        renderTables();
      });
    });

    document.getElementById("filter-reset").addEventListener("click", resetFilters);
  }

  function bindVoteEvents() {
    document.body.addEventListener("click", async (event) => {
      const button = event.target.closest(".vote-btn");
      if (!button) {
        return;
      }

      const wrapper = button.closest(".feedback");
      const code = wrapper.dataset.code;
      const current = state.feedback.get(code) || {};
      const clicked = button.dataset.action;
      const action = current.my_vote === clicked ? "clear" : clicked;

      wrapper.classList.add("busy");
      try {
        const updated = await window.PublicFeedback.submitVote(code, action);
        state.feedback.set(code, updated);
        wrapper.outerHTML = renderFeedbackCell(code);
      } catch (error) {
        window.alert(error.message);
      } finally {
        const currentWrapper = document.querySelector(`.feedback[data-code="${code}"]`);
        if (currentWrapper) {
          currentWrapper.classList.remove("busy");
        }
      }
    });
  }

  async function init() {
    bindFilterEvents();
    bindVoteEvents();

    try {
      const [manifest, buyPayload, sellPayload] = await Promise.all([
        fetchJson("manifest.json"),
        fetchJson("buy_scan_results.json"),
        fetchJson("sell_scan_results.json"),
      ]);

      document.getElementById("manifest-version").textContent = manifest.version || "-";
      document.getElementById("manifest-time").textContent = formatDate(manifest.generated_at);

      const codes = Array.from(
        new Set([...(buyPayload.stocks || []), ...(sellPayload.stocks || [])].map((item) => item.code))
      );

      try {
        state.feedback = await window.PublicFeedback.loadSummary(codes);
      } catch (error) {
        console.error(error);
        state.feedback = new Map();
      }

      state.payloads.buy = buyPayload;
      state.payloads.sell = sellPayload;
      renderSignalTypeOptions();
      syncFiltersFromInputs();
      renderTables();
    } catch (error) {
      document.getElementById("buy-table-body").innerHTML = `<tr><td colspan="9" class="empty">${error.message}</td></tr>`;
      document.getElementById("sell-table-body").innerHTML = `<tr><td colspan="9" class="empty">${error.message}</td></tr>`;
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
